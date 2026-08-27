"""Article 4.2.2.2 — Lighting Controls in Storage Garages.

Table 4.2.1.6. defers interior storage/parking garages to THIS article
rather than to 4.2.2.1.(10)/(13), so a garage is deliberately excluded
from the ordinary photocontrol rule and carries its own, different one.

  (1) lighting divided into zones no larger than 360 m2
  (2) >=30% automatic reduction when no activity is detected for 20 min
  (3) covered vehicle entrances/exits separately controlled, >=50%
      reduction from sunset to sunrise
  (4) where the combined input of luminaires within 6.1 m of a perimeter
      wall with >=40% net opening-to-wall ratio (and no exterior
      obstruction within 6.1 m) exceeds 150 W, those luminaires reduce
      automatically in response to daylight
  (5) daylight transition zones and ramps without parking are exempt from
      (1), (2) and (4)

Controls are modelled the way the rest of this gem models them: as
SCHEDULE MODULATION and audited determinations, not as sensor objects.
That is the 4.2.2.1.(16)-(23) precedent and it is deliberate — the SDK has
no occupancy-sensor object, and inventing one would put hardware in the
model that the code never asked to be simulated.

Port layout: Ruby's storage_garage/schedules.rb REOPENS this module with the
schedule/sensor helpers; here they live in ``schedules.py`` and are imported
at the bottom, so ``StorageGarage.build_reduced_ruleset`` and friends resolve
exactly as they do in Ruby.
"""

from __future__ import annotations

import re

from btap._compat import ruby_round
from btap.audit import AuditLog
from btap.necb import lighting as _lighting

ZONE_AREA_LIMIT_M2 = 360.0          # (1)
OCCUPANCY_REDUCTION = 0.30          # (2) at least 30%
ENTRANCE_REDUCTION = 0.50           # (3) at least 50%
PERIMETER_BAND_M = 6.1              # (4)
GLAZED_WALL_RATIO = 0.40            # (4) net opening-to-wall
DAYLIGHT_POWER_THRESHOLD_W = 150.0  # (4)

# Table 4.2.1.6. sends 'Storage garage interior' here; 'Storage garage' is
# the building-type row. 'Emergency vehicle garage' is deliberately NOT
# matched — the control matrix lists it as required/required under
# 4.2.2.1, so it is not deferred to this article.
GARAGE_SPACE_TYPES = [re.compile(r'\Astorage garage', re.IGNORECASE),
                      re.compile(r'\Aparking garage', re.IGNORECASE)]


def is_garage(space):
    st = space.spaceType()
    if not st.is_initialized():
        return False

    name = st.get().standardsSpaceType()
    building = st.get().standardsBuildingType()
    candidates = [c for c in [name.get() if name.is_initialized() else None,
                              building.get() if building.is_initialized() else None]
                  if c is not None]
    return any(regex.search(c) for c in candidates for regex in GARAGE_SPACE_TYPES)


def garage_spaces(model):
    from btap._compat import sorted_by_name
    return [s for s in sorted_by_name(model.getSpaces())
            if s.partofTotalFloorArea() and is_garage(s)]


def apply(model, vintage='2020', entrance_spaces=None, audit=None):
    """:param entrance_spaces: names of spaces that ARE covered vehicle
        entrances/exits. Geometry cannot tell an entrance bay from an ordinary
        bay, so (3) is applied only when the modeller says which spaces they
        are, and is declared otherwise.
    :return: the determinations, keyed by sentence"""
    audit = audit if audit is not None else AuditLog()
    spaces = garage_spaces(model)
    if not spaces:
        audit.info('lighting',
                   'no storage-garage space types in the model — Article 4.2.2.2. does not apply',
                   article='4.2.2.2.')
        return {'applies': False}

    article = '4.2.2.2.' if str(vintage) == '2025' else '4.2.2.2.'
    result = {'applies': True, 'spaces': len(spaces)}
    result['zoning'] = _check_zoning(spaces, audit, article)
    result['occupancy'] = _apply_occupancy_reduction(model, spaces, vintage, audit, article)
    result['entrances'] = _apply_entrance_control(model, spaces, entrance_spaces, audit, article)
    result['daylight'] = _apply_daylight_response(model, spaces, audit, article)
    _declare_exemptions(audit, article)
    return result


def _check_zoning(spaces, audit, article):
    """(1) zones no larger than 360 m2. A CHECK, not a transform: re-zoning a
    model to satisfy a lighting-control rule would silently change the
    thermal results."""
    zones = []
    for s in spaces:
        if s.thermalZone().is_initialized():
            zone = s.thermalZone().get()
            if not any(zone.handle() == z.handle() for z in zones):
                zones.append(zone)
    oversized = [z for z in zones if z.floorArea() > ZONE_AREA_LIMIT_M2]
    inputs = {'garage_zones': len(zones), 'limit_m2': ZONE_AREA_LIMIT_M2,
              'oversized': [z.nameString() for z in oversized]}
    if not oversized:
        audit.decision('lighting', 'storage-garage lighting zones are within the 360 m2 limit',
                       inputs=inputs, article=f"{article}(1)")
    else:
        audit.warn('lighting',
                   "STORAGE-GARAGE LIGHTING ZONE EXCEEDS 360 m2: "
                   f"{', '.join(z.nameString() for z in oversized)} "
                   '— 4.2.2.2.(1) requires the lighting to be divided into zones no larger than 360 m2',
                   inputs=inputs, article=f"{article}(1)")
    return {'oversized': len(oversized), 'zones': len(zones)}


def _apply_occupancy_reduction(model, spaces, vintage, audit, article):
    """(2) >=30% reduction when no activity for 20 min.

    The gem's existing occupancy-sensor path cannot serve this: it is gated
    on LPD > 8.6 W/m2 and both garage records sit at 1.5-1.9 W/m2, so it
    never fires for a garage. And the Table 4.3.2.10 factors it would use
    give a 26.8% reduction for 'Storage garage interior' and 0% for the
    building-type row — both short of the 30% this sentence demands. So the
    floor is applied explicitly here."""
    from btap._compat import sorted_by_name
    from btap.necb import loads

    data_vintage = _lighting.data_vintage(vintage)
    applied = []
    for space_type in space_types(spaces):
        record = space_type_record(space_type, data_vintage)
        if record is None:
            continue

        lighting_name = '' if record['lighting_schedule'] is None else str(record['lighting_schedule'])
        occupancy_name = '' if record['occupancy_schedule'] is None else str(record['occupancy_schedule'])
        schedules = loads.table(data_vintage, 'schedules')
        lighting_rows = [r for r in schedules if r['name'] == lighting_name]
        occupancy_rows = [r for r in schedules if r['name'] == occupancy_name]
        if not lighting_rows or not occupancy_rows:
            audit.warn('lighting',
                       f"4.2.2.2.(2) needs both '{occupancy_name}' and '{lighting_name}' schedules "
                       '— the 30% unoccupied reduction was NOT applied',
                       target=space_type.nameString(), article=f"{article}(2)")
            continue

        name = f"{lighting_name}-garage-occ{ruby_round(OCCUPANCY_REDUCTION * 100)}-Light Ruleset"
        ruleset = next((s for s in sorted_by_name(model.getSchedules())
                        if s.nameString() == name), None)
        if ruleset is None:
            ruleset = build_reduced_ruleset(model, name, occupancy_rows, lighting_rows,
                                            OCCUPANCY_REDUCTION)
        set_lighting_schedule(space_type, ruleset)
        applied.append(space_type.nameString())

    audit.decision('lighting',
                   'storage-garage lighting reduced by 30% when unoccupied (schedule modulation, '
                   'the 4.2.2.1.(16)-(23) convention — no sensor object is created)',
                   inputs={'space_types': applied, 'reduction': OCCUPANCY_REDUCTION,
                           'detection_delay_min': 20},
                   article=f"{article}(2)")
    return {'space_types': applied}


def _apply_entrance_control(model, spaces, entrance_spaces, audit, article):
    """(3) covered vehicle entrances/exits, >=50% sunset to sunrise.

    No geometry distinguishes an entrance bay from any other bay, and no
    space-type row marks one. Applied when the modeller names the spaces;
    declared as requiring identification otherwise, rather than guessed."""
    from btap._compat import sorted_by_name

    names = [str(n) for n in _array(entrance_spaces)]
    if not names:
        audit.info('lighting',
                   'requires identification by the modeller: 4.2.2.2.(3) separately controls COVERED VEHICLE '
                   'ENTRANCES AND EXITS at >=50% reduction from sunset to sunrise, and no geometry or space '
                   'type distinguishes an entrance bay from an ordinary parking bay — pass entrance_spaces: '
                   'to apply it',
                   article=f"{article}(3)")
        return {'applied': [], 'declared': True}

    matched = [s for s in spaces if s.nameString() in names]
    matched_names = [s.nameString() for s in matched]
    missing = [n for n in names if n not in matched_names]
    if missing:
        audit.warn('lighting',
                   f"entrance_spaces named spaces that are not storage garages: {', '.join(missing)}",
                   article=f"{article}(3)")
    applied = []
    for space_type in space_types(matched):
        schedule = space_type.defaultScheduleSet()
        if not schedule.is_initialized():
            continue

        lighting = schedule.get().lightingSchedule()
        if not lighting.is_initialized():
            continue

        name = (f"{lighting.get().nameString()}-garage-entrance-night"
                f"{ruby_round(ENTRANCE_REDUCTION * 100)}")
        ruleset = next((s for s in sorted_by_name(model.getSchedules())
                        if s.nameString() == name), None)
        if ruleset is None:
            ruleset = build_night_reduced_ruleset(model, name, lighting.get(), ENTRANCE_REDUCTION)
        set_lighting_schedule(space_type, ruleset)
        applied.append(space_type.nameString())
    audit.decision('lighting',
                   'covered vehicle entrance/exit lighting reduced by 50% from sunset to sunrise',
                   inputs={'spaces': matched_names, 'space_types': applied,
                           'reduction': ENTRANCE_REDUCTION},
                   article=f"{article}(3)")
    return {'applied': applied, 'declared': False}


def _apply_daylight_response(model, spaces, audit, article):
    """(4) daylight response where >150 W of luminaires sit within 6.1 m of a
    >=40%-glazed perimeter wall.

    Power is LPD x band area, the same convention 4.2.2.1's own >150 W /
    >300 W thresholds use (DaylightControlRequirement) — the model carries no
    luminaire inventory, so installed power per band is derived, not counted."""
    findings = []
    for space in spaces:
        band = Perimeter.qualifying_band_area(space, audit)
        if band['area_m2'] <= 0.0:
            continue

        lpd = lighting_power_density(space)
        power = lpd * band['area_m2']
        inputs = {'glazed_walls': band['walls'], 'band_depth_m': PERIMETER_BAND_M,
                  'opening_ratio_threshold': GLAZED_WALL_RATIO,
                  'band_area_m2': ruby_round(band['area_m2'], 2), 'lpd_w_per_m2': ruby_round(lpd, 3),
                  'luminaire_power_w': ruby_round(power, 1),
                  'threshold_w': DAYLIGHT_POWER_THRESHOLD_W}
        if power > DAYLIGHT_POWER_THRESHOLD_W:
            add_daylight_control(space, band['area_m2'], audit, article, inputs)
            findings.append({'space': space.nameString(), 'power_w': ruby_round(power, 1),
                             'controlled': True})
        else:
            audit.decision('lighting',
                           'storage-garage perimeter luminaire power is at or below 150 W — 4.2.2.2.(4) '
                           'does not require a daylight response',
                           target=space.nameString(), inputs=inputs, article=f"{article}(4)")
            findings.append({'space': space.nameString(), 'power_w': ruby_round(power, 1),
                             'controlled': False})
    if not findings:
        audit.info('lighting',
                   'no storage-garage space has a perimeter wall at or above 40% net opening — '
                   '4.2.2.2.(4) does not apply',
                   article=f"{article}(4)")
    return findings


def _declare_exemptions(audit, article):
    """(5) is an exemption the model cannot evaluate: neither a daylight
    transition zone nor a ramp-without-parking is distinguishable from an
    ordinary bay by geometry or by space type."""
    audit.info('lighting',
               'requires identification by the modeller: 4.2.2.2.(5) exempts DAYLIGHT TRANSITION ZONES and '
               'RAMPS WITHOUT PARKING from Sentences (1), (2) and (4). Neither is distinguishable from an '
               'ordinary parking bay in the model, so the determinations above are applied to every '
               'garage space and an exempt space should be excluded by the reviewer',
               article=f"{article}(5)")


def _array(value):
    """Ruby's ``Array(x)``: nil -> [], a list stays, anything else wraps."""
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


# Ruby's storage_garage/{perimeter,schedules}.rb, required at the bottom of
# storage_garage.rb — the helpers below (space_types, build_reduced_ruleset,
# add_daylight_control, ...) are what the transforms above call.
from btap.necb.lighting.storage_garage import perimeter as Perimeter  # noqa: E402,F401
from btap.necb.lighting.storage_garage.schedules import (  # noqa: E402,F401
    # Re-exported: schedules.rb REOPENS StorageGarage in Ruby, so these names
    # belong to this module's public surface even though nothing here calls them.
    add_daylight_control,
    build_night_reduced_ruleset,
    build_reduced_ruleset,
    day_values,
    lighting_power_density,
    set_lighting_schedule,
    space_centre,
    space_type_record,
    space_types,
    write_day,
    write_values,
)
