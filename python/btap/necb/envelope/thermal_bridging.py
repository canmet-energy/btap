"""NECB 3.1.1.7: the Table 3.2.2.x values are EFFECTIVE overall thermal
transmittance — Ut = Uo + (Σψ·L)/A + (Σχ·n)/A — so clear-field U-values alone
under-insulate relative to code intent. The Ruby module integrates the TBD gem
(rd2/tbd: linear/point thermal-bridge derating with BETBG PSI sets) to UPRATE
each opaque assembly so its DERATED effective transmittance meets the
prescriptive target.

PORT STATUS (M7): **TBD has no Python equivalent.** rd2/tbd is a Ruby gem with
no PyPI counterpart, and reaching it needs the M7 TBD bridge (a Ruby
subprocess speaking to the same SDK model). Until that exists:

- ``is_available()`` is False, so ``apply`` takes the SAME unavailable branch
  the Ruby takes when the gem is missing: it returns False and writes the
  LOUD audit warning that 3.1.1.7 is not accounted. Never a silent
  clear-field result — that contract is preserved exactly.
- the uprate path itself (``_process``) raises a RuntimeError naming the M7
  bridge rather than pretending to compute anything.

Everything around the gem call — HDD resolution, the effective-U targets, the
TBD argument hash, and the audit narration of a result — is ported, so wiring
M7 means supplying ``_process``/``_logs`` and flipping ``_bridge_available``.
"""

from __future__ import annotations

import os

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

TBD_BRIDGE_MESSAGE = (
    "NECB 3.1.1.7 thermal bridging needs the TBD engine (rd2/tbd), which is a "
    "RUBY gem with no Python equivalent. The M7 TBD bridge — the Ruby "
    "subprocess that runs TBD.process on the model and returns its :surfaces "
    "result — is not built yet, so the uprate/derate path cannot run from "
    "Python. Until M7 lands, call the Ruby btap-necb gem for thermal bridging, "
    "or accept the audited clear-field warning (is_available() is False, so "
    "apply() warns loudly and returns False rather than raising)."
)


def _bridge_available() -> bool:
    """The M7 TBD bridge. False until it is built — flipping this to True is
    the whole wiring change, alongside ``_process``/``_logs``."""
    return False


def is_available() -> bool:
    if os.environ.get("OPENSTUDIO_ENVELOPE_DISABLE_TBD") == "1":
        return False
    return _bridge_available()


def _process(model, argh):
    """TBD.clean! + TBD.process — the M7 bridge's job."""
    raise RuntimeError(TBD_BRIDGE_MESSAGE)


def _logs():
    """TBD.logs — the M7 bridge's job."""
    raise RuntimeError(TBD_BRIDGE_MESSAGE)


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

    result = _process(model, argh)
    return _record(result, psi_set, hdd, targets, audit)


def _record(result, psi_set, hdd, targets, audit):
    """Narrate a TBD result into the audit (the second half of the Ruby
    ``apply``); split out so the M7 bridge only has to supply the result."""
    surfaces = result.get("surfaces") or {}
    derated = {name: s for name, s in surfaces.items()
               if s.get("deratable") and abs(float(s.get("heatloss") or 0.0)) > 1e-9}

    # Forward every TBD warning+ into the audit — 'Unable to uprate X' means
    # the geometry's edge losses alone exceed the effective target with this
    # PSI set (physically infeasible), which must be visible, never swallowed.
    for entry in _logs():
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
