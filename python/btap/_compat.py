"""Cross-cutting Ruby-parity contracts for the btap port (D-79).

Every helper here papers over ONE specific Ruby-vs-Python semantic difference
the port-hazard census identified as a silent-drift hazard. Ported code MUST
use these instead of the raw Python equivalents:

- ``ruby_round``   — Ruby ``Float#round`` (half AWAY from zero, on the
  shortest decimal representation); Python's ``round()`` is banker's.
- ``ruby_div``     — Ruby FLOAT division, which never raises: x/0.0 is
  ±Infinity and 0.0/0.0 is NaN, where Python raises ZeroDivisionError.
- ``opt``/``opt_or`` — SDK ``Optional`` unwrapping; routes every call through
  one greppable site and retires the missing-``()`` truthy-bound-method bug.
- ``NullAudit``    — null-object stand-in for AuditLog, replacing Ruby's 235
  ``audit&.warn`` safe-navigation sites with plain ``audit.warn``.
- ``sorted_by_name`` — the determinism-critical ``sort_by(&:nameString)``.
- ``esc``/``Raw``  — the report's HTML escaping (exactly Ruby's four
  substitutions; ``html.escape`` also escapes ``'`` and would diff).
- ``ruby_str``     — Ruby string interpolation of scalars (``true``/``false``/
  ``nil``→empty, Ruby float rendering) for byte-parity narrative text.

Stdlib only. This module must never import openstudio.
"""

from __future__ import annotations

import math
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


def ruby_round(x, ndigits: int = 0):
    """Ruby ``Float#round(ndigits)``: half away from zero on the value's
    shortest decimal representation (so ``ruby_round(2.675, 2) == 2.68`` even
    though the double is 2.67499...). Returns int for ``ndigits <= 0`` and
    float otherwise, exactly as Ruby returns Integer/Float.

    Non-finite input follows Ruby exactly: with ndigits > 0 the value comes
    back unchanged (``Infinity.round(2) == Infinity``, ``NaN.round(4) ==
    NaN``), while ndigits <= 0 must produce an Integer and so raises, as
    Ruby's FloatDomainError does. This matters because Ruby float division
    never raises — see ``ruby_div`` — so NaN/Infinity reach rounding on
    perfectly ordinary code paths."""
    if isinstance(x, int) and ndigits >= 0:
        return x
    value = float(x)
    if math.isnan(value) or math.isinf(value):
        if ndigits > 0:
            return value
        raise ValueError(f"cannot round {value} to an integer (Ruby: FloatDomainError)")
    quantum = Decimal(1).scaleb(-ndigits)
    d = Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return int(d) if ndigits <= 0 else float(d)


def ruby_div(numerator, denominator) -> float:
    """Ruby FLOAT division, which never raises: ``x/0.0`` is ±Infinity and
    ``0.0/0.0`` is NaN, where Python raises ZeroDivisionError.

    This is a family-wide porting hazard, not a curiosity. Ruby code
    routinely divides by a possibly-zero area or count and then relies on the
    result comparing false (``NaN <= 0.006`` is false), which is how several
    NECB criteria skip an inapplicable half. Transliterating such a division
    turns a silent skip into a crash, so every ported float division whose
    denominator can be zero goes through here."""
    n, d = float(numerator), float(denominator)
    if d != 0.0:
        return n / d
    if n == 0.0 or math.isnan(n):
        return math.nan
    return math.inf if (n > 0) == (not math.copysign(1.0, d) < 0) else -math.inf


def opt(optional):
    """Unwrap an SDK Optional: the value, or None when empty (Ruby's
    ``x.is_initialized ? x.get : nil``). None passes through.

    ALWAYS route through this rather than calling ``.get()`` directly.
    Unwrapping an EMPTY optional does not fail the way Ruby does, and what it
    does is not a stable function of the type. Three outcomes occur, measured
    on 3.11.0 (#164):

    - it SEGFAULTS the interpreter. 615 of the 617 ``Optional*`` names in
      ``openstudio.model`` do this — every one wrapping a
      NON-DEFAULT-CONSTRUCTIBLE type, which is most model objects plus some
      value types like ``ClimateZone`` and ``ViewFactor``. This is what a
      failed ``to_X()`` cast returns, and equally what ``.thermalZone()``,
      ``.construction()``, ``.spaceType()`` and the other optional accessors
      return — the accessors are the larger population. History makes no
      difference, and a crash takes the whole process with it (in a test run,
      the whole xdist worker, which reports as a lost node rather than a
      failure).
    - it RAISES ``SystemError``, caused by ``RuntimeError: Optional not
      initialized``. The value optionals ``OptionalDouble``,
      ``OptionalString`` and ``OptionalInt`` do this on their FIRST call.
    - it RETURNS A DEFAULT-CONSTRUCTED OBJECT, silently. ``OptionalModel`` and
      ``OptionalScheduleType``, the namespace's two default-constructible
      types, do this in a fresh interpreter. That is how an unwrapped failed
      ``Model.load(...)`` flows onward as a model with no spaces and no
      zones, and how the packaged catalog report came to emit 97 "diagram
      unavailable" cards from a wheel instead of one clear error.

    Which of the last two a default-constructible optional gives you depends
    on what the process has already done, per class — and NOT in a way worth
    writing down. Two sequences are pinned in
    ``tests/test_sdk_invariants.py`` because they anchor the hazard; the rest
    of the ordering was measured and deliberately left undocumented, because
    two successive attempts to state a rule for it (#164, both mine) each
    described behaviour the SDK does not have. Treat every unguarded unwrap as
    one of the three outcomes above, unpredictably.

    One further trap, which D-79 half-saw and put on the wrong case: after a
    SURVIVING unwrap, the NEXT CHECKED C CALL — whatever it happens to be —
    can raise ``SystemError`` caused by ``RuntimeError: Optional not
    initialized``. Unwrap, construct a ``Model()``, unwrap again, and the
    next call raises; a bare ``[].append(0)`` shows it as readily as any SDK
    call, so the failure surfaces in code with no visible connection to an
    optional. The RAISING case is the one that leaves nothing behind —
    CPython chains the ``RuntimeError`` as ``__cause__`` and clears it.

    The error is set DURING that next call, not left pending before it:
    ``ctypes.pythonapi.PyErr_Occurred()`` read in the same position is clear,
    and disabling the garbage collector changes nothing. Why is not known,
    and this docstring deliberately does not guess — three successive attempts
    to state a mechanism here (#164) each described something the SDK does not
    do.

    It IS pinned, by two tests in ``tests/test_sdk_invariants.py`` that must
    stay two: the probe is stable at one subprocess launch per test and fails
    roughly 7% of the time when the control and the subject share one. Even so,
    do not rely on SEEING this in the wild, and never read a clean run as
    evidence it is gone — the trap fires on whatever checked call comes next,
    which may be nowhere near the unwrap that caused it.

    Ruby raises cleanly in all of these. See D-79.
    """
    if optional is None:
        return None
    return optional.get() if optional.is_initialized() else None


def opt_or(optional, default):
    """Unwrap an SDK Optional with a default (Ruby's ``.empty? ? d : .get``)."""
    value = opt(optional)
    return default if value is None else value


def sorted_by_name(objects):
    """``sort_by(&:nameString)`` — THE determinism idiom: every iteration whose
    order reaches an output must pass through here (reference models, audit
    entries, costing line items are reproducible because of it)."""
    return sorted(objects, key=lambda o: o.nameString())


class NullAudit:
    """Null-object AuditLog: absorbs every write, so callers take
    ``audit=NullAudit()`` instead of Ruby's ``audit&.`` at 235 sites.
    API-compatible with btap.audit.AuditLog; never import that here
    (audit imports _compat, not the reverse)."""

    building = None
    entries: list = []  # always empty; writes are discarded, not stored

    def decision(self, *args, **kwargs):
        return self

    def info(self, *args, **kwargs):
        return self

    def warn(self, *args, **kwargs):
        return self

    @property
    def warnings(self):
        return []

    @contextmanager
    def with_building(self, name):
        yield


@dataclass(frozen=True)
class Raw:
    """Marks a pre-built HTML fragment as safe to embed unescaped
    (Ruby's ``Html::Raw`` struct)."""

    html: str


def esc(value) -> str:
    """HTML-escape any value — exactly Ruby ``Html.esc``'s four gsubs, in
    order. Deliberately NOT ``html.escape``: that escapes ``'`` too and the
    report goldens would diff."""
    return (
        ruby_str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def ruby_str(value) -> str:
    """Ruby string interpolation (``"#{value}"``) for the scalar types the
    audit narrative and report text actually carry: None→'' (nil), booleans
    lowercase, Ruby float rendering (``1.0e+16``, not ``1e+16``), lists in
    Ruby ``Array#to_s`` style. Best-effort beyond those — audit.txt is
    narrative, only audit.json/report.json are Leg-B-gated."""
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, float):
        return ruby_float_str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_ruby_inspect(v) for v in value) + "]"
    return str(value)


def ruby_float_str(x: float) -> str:
    """Ruby ``Float#to_s``: same shortest-repr digits and sci-notation
    thresholds as Python's repr, but the mantissa always carries a decimal
    point (Ruby ``1.0e+16`` vs Python ``1e+16``)."""
    s = repr(x)
    if "e" in s:
        mantissa, exponent = s.split("e")
        if "." not in mantissa:
            mantissa += ".0"
        return f"{mantissa}e{exponent}"
    return s


def _ruby_inspect(value) -> str:
    """Ruby ``#inspect`` for array elements: strings quoted, nil literal."""
    if value is None:
        return "nil"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return ruby_str(value)


# NOTE: SDK-touching helpers (ensure_sdk_hashable) live in btap._sdk — this
# module stays stdlib-only so btap.audit can depend on it and still run on a
# runner with no OpenStudio. The import-linter contract enforces that.
