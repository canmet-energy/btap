"""Cross-cutting Ruby-parity contracts for the btap port (D-79).

Every helper here papers over ONE specific Ruby-vs-Python semantic difference
the port-hazard census identified as a silent-drift hazard. Ported code MUST
use these instead of the raw Python equivalents:

- ``ruby_round``   — Ruby ``Float#round`` (half AWAY from zero, on the
  shortest decimal representation); Python's ``round()`` is banker's.
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

from contextlib import contextmanager
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


def ruby_round(x, ndigits: int = 0):
    """Ruby ``Float#round(ndigits)``: half away from zero on the value's
    shortest decimal representation (so ``ruby_round(2.675, 2) == 2.68`` even
    though the double is 2.67499...). Returns int for ``ndigits <= 0`` and
    float otherwise, exactly as Ruby returns Integer/Float."""
    if isinstance(x, int) and ndigits >= 0:
        return x
    quantum = Decimal(1).scaleb(-ndigits)
    d = Decimal(repr(float(x))).quantize(quantum, rounding=ROUND_HALF_UP)
    return int(d) if ndigits <= 0 else float(d)


def opt(optional):
    """Unwrap an SDK Optional: the value, or None when empty (Ruby's
    ``x.is_initialized ? x.get : nil``). None passes through."""
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
