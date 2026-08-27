"""Reference-building lighting — NECB 2020 8.4.4.5 (2025: renumbered
performance path):
  (1) installed interior lighting power = the Part 4 allowance
      (apply_lights with NECB_Default IS the allowance)
  (2) dwelling units at 5 W/m2
  (3) occupancy/personal-control factors (Table 4.3.2.10) — applied via the
      sensor-schedule synthesis (schedule modulation), the legacy NECB2015+
      interpretation of the power-multiplier wording
  (4) radiant/convective/return-air fractions identical to proposed — holds
      by construction (same space-type records drive both models)
  (5)-(12) daylighting geometry + photocontrols — modeled by the SEPARATE
      reference_daylighting transform (reference_daylighting.py), which
      audits (5)-(12) itself. This transform therefore says nothing about
      them when it is told daylighting ran (daylighting=True) and warns
      loudly only when it did not.
"""

from __future__ import annotations

import re

from btap._compat import sorted_by_name
from btap.audit import AuditLog
from btap.necb import lighting as _lighting
from btap.necb.lighting import apply_lights as ApplyLights


def _inspect(value):
    """Ruby ``String#inspect`` / ``nil.inspect`` for the audit message."""
    return 'nil' if value is None else f'"{value}"'


def reference_lighting(model, vintage='2020', daylighting=False, audit=None):
    """:param daylighting: whether the caller ALSO runs reference_daylighting
    on this model. When it does, (5)-(12) are modeled and audited there, so
    this transform stays silent about them; when it does not, the gap is
    shouted here. Defaults to False so a caller that never runs the
    daylighting transform still gets the loud gap without opting in."""
    audit = audit if audit is not None else AuditLog()
    prefix = '8.4.5' if str(vintage) == '2025' else '8.4.4'

    # HARD GATE: apply_lights silently skips space types with no NECB
    # catalog record, and the reference is a clone — so an unmatched type
    # keeps the PROPOSED's lighting power verbatim, waiving the Part 4
    # allowance for exactly the spaces where it matters (an over-lit space
    # then incurs zero penalty). The allowance for an unlisted space
    # function is a human judgement (4.2.1.6.(1)(b): "most closely
    # represents the proposed use"), so no fallback value is invented here:
    # the transform refuses, loudly, before a wrong reference can exist.
    unmatched = ApplyLights.unmatched_space_types(model, vintage)
    if unmatched:
        pairs = [f"'{u['name']}' [{_inspect(u['building_type'])}, {_inspect(u['space_type'])}]"
                 for u in unmatched]
        for u in unmatched:
            audit.warn('lighting_reference',
                       f"space type '{u['name']}' is UNRESOLVABLE against the NECB catalog — "
                       f"the {prefix}.5.(1) "
                       'reference lighting allowance cannot be established for it',
                       article=f"{prefix}.5.(1); 4.2.1.6.")
        raise ValueError(
            f"reference lighting ABORTED: {len(unmatched)} space type(s) have no NECB {vintage} catalog "
            f"record, so the {prefix}.5.(1) interior lighting allowance cannot be established: "
            f"{'; '.join(pairs)}. Tag the model with NECB space functions "
            '(btap.necb.loads assign_space_types, or correct standardsBuildingType/standardsSpaceType) — '
            'proceeding would silently keep the proposed lighting power in the reference.')

    ApplyLights.apply_lights(model, vintage=vintage, lights_type='NECB_Default', audit=audit)
    audit.decision('lighting_reference',
                   'reference interior lighting set to the Part 4 allowance (space-type LPDs)',
                   article=f"{prefix}.5.(1)")

    _apply_dwelling_rule(model, vintage, prefix, audit)
    audit.info('lighting_reference',
               'occupancy/personal-control factors applied via the sensor-schedule synthesis '
               '(schedule modulation of the Table 4.3.2.10 factors — legacy NECB2015+ interpretation '
               'of the power-multiplier wording)', article=f"{prefix}.5.(3); 4.3.2.10.")
    audit.info('lighting_reference',
               'lighting heat fractions identical to proposed by construction (same space-type records)',
               article=f"{prefix}.5.(4)")
    if not daylighting:
        audit.warn('lighting_reference',
                   f"{prefix}.5.(5)-(12): reference daylighting geometry (centered-window sidelighting, "
                   'centred-skylight toplighting) and photocontrol evaluation are NOT modeled on this run '
                   '(reference_daylighting was not run)',
                   article=f"{prefix}.5.(5)-(12)")
    return audit


def _apply_dwelling_rule(model, vintage, prefix, audit):
    """8.4.4.5.(2): dwelling units at 5 W/m2."""
    lpd = float(_lighting.rules(vintage)['dwelling_unit_lpd_w_per_m2'])
    changed = 0
    for space_type in sorted_by_name(model.getSpaceTypes()):
        optional = space_type.standardsSpaceType()
        standards = optional.get() if optional.is_initialized() else ''
        if not re.search(r'dwelling', standards, re.IGNORECASE):
            continue

        for lights in sorted_by_name(space_type.lights()):
            lights.lightsDefinition().setWattsperSpaceFloorArea(lpd)
            changed += 1
    audit.decision('lighting_reference', f"dwelling units modeled at {lpd} W/m2",
                   inputs={'lights_instances': changed}, article=f"{prefix}.5.(2)")
