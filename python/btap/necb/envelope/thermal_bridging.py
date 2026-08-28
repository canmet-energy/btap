"""NECB 3.1.1.7: the Table 3.2.2.x values are EFFECTIVE overall thermal
transmittance — Ut = Uo + (Σψ·L)/A + (Σχ·n)/A — so clear-field U-values alone
under-insulate relative to code intent. The Ruby module integrates the TBD gem
(rd2/tbd: linear/point thermal-bridge derating with BETBG PSI sets) to UPRATE
each opaque assembly so its DERATED effective transmittance meets the
prescriptive target.

M7 (D-79, Option A of the M6/M7 review): the engine is **py-tbd**, the
native Python port of rd2/tbd, pinned to the ``tbd-3.5.2-compat`` branch —
a revision verified against the SAME Ruby TBD 3.5.2 / OSut 0.8.2 baseline
the family's verification oracle is frozen on (main ports 3.6.0, which
PARTIALLY uprates an infeasible construction where 3.5.2 refuses — ~43%
apart on the same wall; see py-tbd's UPSTREAM.md). No Ruby subprocess
bridge: ``tbd.process(model, argh)`` mutates the same in-process SDK model
the Ruby gem's TBD.process does.

The optional dependency is declared in pyproject's ``[project.optional-
dependencies] tbd`` extra; because py-tbd has no PyPI release yet, install
is pinned by commit SHA (py-topolys first, then ``--no-deps`` py-tbd — pip
refuses two spellings of the same git direct reference). When unavailable,
``apply`` takes the SAME branch the Ruby takes without the gem: returns
False with the LOUD 3.1.1.7-not-accounted warning. Never a silent
clear-field result. Logs are CALL-LOCAL: ``_process`` returns (result,
logs) from the one operation, so concurrent calls cannot interleave.
"""

from __future__ import annotations

import os
import threading

from btap._compat import ruby_round, ruby_str
from btap.audit import AuditLog
from btap.necb.envelope import climate
from btap.necb.envelope.rules import max_u

# TBD built-in PSI sets (BETBG-derived); a dict of detail=>psi may be given
# instead for custom sets (kept vocabulary-compatible with btap/bridging.rb
# detail types for the future thermal-bridging costing linkage).
BUILT_IN_PSI_SETS = ["poor (BETBG)", "regular (BETBG)", "efficient (BETBG)",
                     "spandrel (BETBG)", "spandrel HP (BETBG)",
                     "code (Quebec)", "uncompliant (Quebec)", "(non thermal bridging)"]

#: The verified engine baseline (Option A): the py-tbd tbd-3.5.2-compat
#: branch. tests/necb/test_envelope_thermal_bridging.py asserts the
#: installed engine matches — a silently different engine would compare
#: different physics against the frozen goldens.
PINNED_TBD_VERSION = "3.5.2"
PINNED_TBD_UPSTREAM_SHA = "95156a922f54e45293e1896eba11bc29cd1b5c6d"

_available: bool | None = None

#: One engine operation at a time: tbd.oslg is PROCESS-GLOBAL state, so the
#: clean -> process -> logs sequence must not interleave across threads.
#: (Ruby's TBD shares the same global-log pattern; both integrations are
#: process-safe — pytest-xdist forks processes — and this lock makes the
#: Python side thread-safe too.)
_ENGINE_LOCK = threading.Lock()


def _bridge_available() -> bool:
    """Is the py-tbd engine importable? Memoized per process, like Ruby's
    ``@available`` (the env-var opt-out is checked BEFORE this, uncached).

    Only ABSENCE of py-tbd itself is the benign fallback. An import failure
    from inside it — a missing/broken py_topolys, osut, oslg or openstudio —
    is a BROKEN configured engine and PROPAGATES: relabeling it as
    unavailability would hand a user who requested thermal bridging
    clear-field values behind a warning that claims the gem is missing
    (review, 2026-08-28; the Ruby module discriminates on LoadError#path the
    same way)."""
    global _available
    if _available is None:
        try:
            import tbd  # noqa: F401

            _available = True
        except ModuleNotFoundError as e:
            if e.name != "tbd":
                raise
            _available = False
    return _available


def is_available() -> bool:
    if os.environ.get("OPENSTUDIO_ENVELOPE_DISABLE_TBD") == "1":
        return False
    return _bridge_available()


def _process(model, argh):
    """TBD.clean! + TBD.process + TBD.logs — one engine operation, under
    the engine lock (tbd.oslg is process-global).

    :return: (the TBD result dict, THAT call's logs) — logs are captured
        here, call-locally, so a later operation cannot mutate them.
    :raises RuntimeError: when the engine logged error/fatal — TBD reports
        invalid input by LOGGING it and returning a PARTIAL result
        (reproduced: an invalid PSI set returns 30 surfaces at status 5);
        narrating that partial result would record 'assemblies uprated' for
        a failed run. Same fix landed Ruby-first (review, 2026-08-28)."""
    import tbd

    with _ENGINE_LOCK:
        tbd.oslg.clean()
        result = tbd.process(model, argh)
        logs = [dict(entry) for entry in tbd.oslg.logs()]
        status = int(tbd.oslg.status())
        failed = bool(tbd.oslg.is_fatal() or tbd.oslg.is_error())
    if failed:
        problems = "; ".join(str(entry["message"]) for entry in logs
                             if int(entry["level"]) >= 4)
        raise RuntimeError(
            f"TBD FAILED (status {status}) — NECB 3.1.1.7 effective "
            f"transmittance has NOT been applied: {problems}")
    return result, logs


def apply(model, *, vintage, hdd=None, psi_set="regular (BETBG)", audit=None):
    """Uprate walls/roofs/exposed floors so the TBD-derated effective Ut meets
    the NECB maximum U at this HDD, using the given PSI set.

    :param psi_set: a TBD built-in set name or {detail: psi W/(m.K)}
    :return: the TBD result dict (:io, :surfaces), or False when tbd is
        unavailable (audited)
    """
    audit = audit if audit is not None else AuditLog()
    if not is_available():
        audit.warn("thermal_bridging",
                   "NECB 3.1.1.7 EFFECTIVE transmittance NOT accounted: the 'tbd' gem is not "
                   "available, so applied U-values remain clear-field (Uo). Install tbd to "
                   "uprate/derate for thermal bridging.",
                   article="3.1.1.7.")
        return False

    hdd = climate.hdd18(model, hdd=hdd, audit=audit)
    if hdd is None:
        raise ValueError("HDD unresolvable: pass hdd: explicitly or set a weather file")

    targets = {
        "wall_ut": max_u(vintage=vintage, surface="wall", boundary="outdoors", hdd=hdd),
        "roof_ut": max_u(vintage=vintage, surface="roofceiling", boundary="outdoors", hdd=hdd),
        "floor_ut": max_u(vintage=vintage, surface="floor", boundary="outdoors", hdd=hdd),
    }

    argh = {"uprate_walls": True, "uprate_roofs": True, "uprate_floors": True,
            "wall_option": "all wall constructions",
            "roof_option": "all roof constructions",
            "floor_option": "all floor constructions"}
    argh.update(targets)
    if isinstance(psi_set, dict):
        argh["option"] = "(non thermal bridging)"
        argh["io_path"] = {"psis": [{"id": "custom", "building": psi_set}],
                           "building": {"psi": "custom"}}
    else:
        argh["option"] = psi_set

    result, logs = _process(model, argh)
    return _record(result, logs, psi_set, hdd, targets, audit)


def _record(result, logs, psi_set, hdd, targets, audit):
    """Narrate a TBD result into the audit (the second half of the Ruby
    ``apply``). ``logs`` are the engine logs of THIS call (call-local)."""
    surfaces = result.get("surfaces") or {}
    derated = {name: s for name, s in surfaces.items()
               if s.get("deratable") and abs(float(s.get("heatloss") or 0.0)) > 1e-9}

    # Forward every TBD warning+ into the audit — 'Unable to uprate X' means
    # the geometry's edge losses alone exceed the effective target with this
    # PSI set (physically infeasible), which must be visible, never swallowed.
    for entry in logs:
        if int(entry["level"]) >= 3:
            audit.warn("thermal_bridging", f"TBD: {entry['message']}", article="3.1.1.7.")

    total_heatloss = sum(float(s.get("heatloss") or 0.0) for s in derated.values())
    audit.decision("thermal_bridging",
                   "assemblies uprated so the TBD-derated effective Ut meets the "
                   "prescriptive targets",
                   inputs={"psi_set": "custom" if isinstance(psi_set, dict) else psi_set,
                           "hdd": hdd,
                           "wall_ut": targets["wall_ut"], "roof_ut": targets["roof_ut"],
                           "floor_ut": targets["floor_ut"],
                           "surfaces_derated": len(derated)},
                   value=(f"total edge heat loss {ruby_str(ruby_round(total_heatloss, 1))} "
                          f"W/K over {len(derated)} surfaces"),
                   article="3.1.1.7. (Ut = Uo + Σψ·L/A + Σχ·n/A; PSI per BETBG)")
    for name, s in sorted(derated.items(), key=lambda kv: str(kv[0]))[:50]:
        audit.info("thermal_bridging", "surface derated for linear thermal bridging",
                   target=str(name),
                   inputs={"heatloss_w_per_k": ruby_round(float(s.get("heatloss") or 0.0), 3)},
                   article="3.1.1.7.")
    return result
