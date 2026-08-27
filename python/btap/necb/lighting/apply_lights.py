"""Interior lighting — port of legacy apply_standard_lights (NECB2011 base) with
the NECB2020-lineage overrides: set_lighting_per_area WITHOUT the 2011 0.9
occupancy-sensor derate (2015+ models sensing via the lighting SCHEDULE), the
NECB2015 apply_lighting_schedule sensor-synthesis, and the NECB2017 LED
atrium equations.

LEGACY DEFECTS fixed here (both in the never-exercised atrium/LED path —
no archetype has an atrium): set_lighting_per_area_led_lighting references
an undefined `space_height` (NameError), and
get_max_space_height_for_space_type calls `select(&:surfaceType == 'Wall')`
which is `select(&false)` (TypeError). The gem computes the height correctly
and uses it.

Ruby ``ApplyLights`` — the private_class_method tail of the Ruby module is the
leading-underscore naming here (``_is_plenum`` etc.); ``apply_lights`` and
``unmatched_space_types`` are the API.
"""

from __future__ import annotations

import re
from datetime import datetime

import openstudio

from btap._compat import ruby_round, sorted_by_name
from btap.audit import AuditLog, emit_coverage
from btap.necb import lighting as _lighting

_WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
_TOKEN_DAYS = {'Mon': 'Monday', 'Tue': 'Tuesday', 'Wed': 'Wednesday',
               'Thu': 'Thursday', 'Fri': 'Friday', 'Sat': 'Saturday',
               'Sun': 'Sunday'}


def _f(value):
    """Ruby ``.to_f``: nil -> 0.0, numeric/string -> Float (a string that does
    not start with a number reads 0.0, as Ruby's does)."""
    if value is None:
        return 0.0
    if isinstance(value, str):
        match = re.match(r'\s*[-+]?(\d+(\.\d*)?([eE][-+]?\d+)?|\.\d+)', value)
        return float(match.group(0)) if match else 0.0
    return float(value)


def _inspect(value):
    """Ruby ``String#inspect`` / ``nil.inspect`` for the audit message."""
    return 'nil' if value is None else f'"{value}"'


def apply_lights(model, vintage='2020', lights_type='NECB_Default',
                 lights_scale=1.0, audit=None):
    """Apply NECB interior lighting to every tagged space type.

    :param lights_type: 'NECB_Default' or 'LED'
    """
    audit = audit if audit is not None else AuditLog()
    if lights_type is None or lights_type == 'none':
        lights_type = 'NECB_Default'
    if lights_scale is None or lights_scale == 'none' or lights_scale == 'NECB_Default':
        lights_scale = 1.0
    if isinstance(lights_scale, str):
        lights_scale = _f(lights_scale.strip())
    applied = 0
    eligible = 0

    for space_type in sorted_by_name(model.getSpaceTypes()):
        if not _is_plenum(space_type):
            eligible += 1
        if _apply_to_space_type(model, space_type, vintage, lights_type, lights_scale, audit):
            applied += 1
    # applied vs eligible: a numerator alone hid a total no-op — 3-of-10 and
    # 10-of-10 were indistinguishable in the log (how the reference-LPD
    # defect survived). Unmatched CONSEQUENTIAL types (ones with floor-area
    # spaces) are warned individually in _apply_to_space_type.
    audit.decision('lighting', f"interior lighting applied ({lights_type}, scale {lights_scale})",
                   inputs={'space_types_applied': applied, 'space_types_eligible': eligible,
                           'vintage': vintage},
                   article='4.2.1.4.; 4.2.1.5.; 4.2.1.6.')
    _emit_article_coverage(vintage, audit)
    return audit


def _is_plenum(space_type):
    standards = space_type.standardsSpaceType()
    return ('plenum' in space_type.nameString().lower()
            or (standards.is_initialized() and 'plenum' in standards.get().lower()))


def _is_consequential(space_type):
    """A space type only matters to lighting power if a floor-area space uses
    it — the shared fixture carries six orphan space types nothing uses."""
    return any(s.partofTotalFloorArea() for s in space_type.spaces())


def unmatched_space_types(model, vintage):
    """Space types (with their standards tags) that a Part 4 LPD could NOT be
    established for, restricted to ones that matter. The reference
    transform hard-fails on these: reference LPD == proposed LPD means the
    8.4.5.5.(1) allowance is silently waived."""
    from btap.necb import loads
    from btap.necb.loads import space_types as SpaceTypes

    result = []
    for space_type in sorted_by_name(model.getSpaceTypes()):
        if _is_plenum(space_type) or not _is_consequential(space_type):
            continue

        building = space_type.standardsBuildingType()
        building_type = building.get() if building.is_initialized() else None
        standards = space_type.standardsSpaceType()
        standards_type = standards.get() if standards.is_initialized() else None
        record = SpaceTypes.find(building_type=building_type, space_type=standards_type,
                                 vintage=loads.data_vintage(vintage))
        if not (record is None or SpaceTypes.is_undefined(record)):
            continue

        result.append({'name': space_type.nameString(), 'building_type': building_type,
                       'space_type': standards_type})
    return result


def _apply_to_space_type(model, space_type, vintage, lights_type, lights_scale, audit):
    from btap.necb import loads
    from btap.necb.loads import space_types as SpaceTypes

    name = space_type.nameString()
    if _is_plenum(space_type):
        return False

    building = space_type.standardsBuildingType()
    building_type = building.get() if building.is_initialized() else None
    standards = space_type.standardsSpaceType()
    standards_type = standards.get() if standards.is_initialized() else None
    record = SpaceTypes.find(building_type=building_type, space_type=standards_type,
                             vintage=loads.data_vintage(vintage))
    if record is None or SpaceTypes.is_undefined(record):
        if _is_consequential(space_type):
            audit.warn('lighting',
                       f"space type '{name}' [{_inspect(building_type)}, "
                       f"{_inspect(standards_type)}] has no NECB "
                       f"{vintage} record — interior lighting power NOT applied; any existing Lights are left "
                       'untouched, so a reference built from this model would keep the proposed LPD verbatim',
                       article='4.2.1.6.')
        return False

    lpd = _f(record['lighting_per_area'])
    per_person = _f(record['lighting_per_person'])
    if lpd == 0.0 and per_person == 0.0:
        # No real catalog row hits this ('- undefined -' is caught above);
        # defensive only, but never silent if the data ever grows one.
        if _is_consequential(space_type):
            audit.warn('lighting',
                       f"space type '{name}' catalog record carries zero LPD — no Lights applied",
                       article='4.2.1.6.')
        return False

    instance = _single_lights_instance(space_type, lights_type)
    definition = instance.lightsDefinition()
    applied_lpd_w_ft2 = None

    if lpd != 0.0:
        if lights_type == 'LED':
            led = _lighting.led_record(building_type=building_type, space_type=standards_type)
            if led is None:
                raise ValueError(
                    f"no LED lighting data for ['{building_type}', '{standards_type}']")

            applied_lpd_w_ft2 = _led_lpd_w_ft2(space_type, standards_type, led, vintage,
                                               audit) * lights_scale
            definition.setWattsperSpaceFloorArea(
                openstudio.convert(applied_lpd_w_ft2, 'W/ft^2', 'W/m^2').get())
            _set_fraction(definition, 'setReturnAirFraction', led['lighting_fraction_to_return_air'])
            _set_fraction(definition, 'setFractionRadiant', led['lighting_fraction_radiant'])
            _set_fraction(definition, 'setFractionVisible', led['lighting_fraction_visible'])
        else:
            applied_lpd_w_ft2 = lpd * lights_scale
            definition.setWattsperSpaceFloorArea(
                openstudio.convert(applied_lpd_w_ft2, 'W/ft^2', 'W/m^2').get())
            _set_fraction(definition, 'setReturnAirFraction',
                          record['lighting_fraction_to_return_air'])
            _set_fraction(definition, 'setFractionRadiant', record['lighting_fraction_radiant'])
            _set_fraction(definition, 'setFractionVisible', record['lighting_fraction_visible'])
    if per_person != 0.0:
        definition.setWattsperPerson(per_person)

    _add_additional_lights(space_type, record)
    _wire_lighting_schedule(model, space_type, record, vintage, audit)

    audit.info('lighting', 'lights set', target=name,
               inputs={'lpd_w_per_ft2': (None if applied_lpd_w_ft2 is None
                                         else ruby_round(applied_lpd_w_ft2, 4)),
                       'type': lights_type},
               article='4.2.1.6.' if building_type == 'Space Function' else '4.2.1.5.')
    return True


def _led_lpd_w_ft2(space_type, standards_type, led, vintage, audit):
    """LED LPD with the atrium height rule (W/ft2 in, W/ft2 out; equations are SI
    W/m2 = intercept + slope x height, converted x0.092903 as legacy does)."""
    lpd = _f(led['lighting_per_area'])
    if 'Atrium' not in ('' if standards_type is None else str(standards_type)):
        return lpd

    height = _max_space_height(space_type)
    equations = _lighting.rules(vintage)['atrium_led']
    equation = equations['below_12m'] if height < 12.0 else equations['at_or_above_12m']
    atrium_lpd = (equation['intercept'] + equation['slope'] * height) * 0.092903
    audit.info('lighting', 'LED atrium LPD from height equation (legacy defect fixed: undefined space_height)',
               target=space_type.nameString(),
               inputs={'height_m': ruby_round(height, 2), 'intercept': equation['intercept'],
                       'slope': equation['slope']},
               value=f"{ruby_round(atrium_lpd, 4)} W/ft2", article='4.2.1.6. (atrium)')
    return atrium_lpd


def _max_space_height(space_type):
    """Max wall-vertex height over the space type's spaces (correct version of the
    legacy method whose select(&:surfaceType == 'Wall') is select(&false))."""
    height = 0.0
    for space in sorted_by_name(space_type.spaces()):
        for wall in space.surfaces():
            if wall.surfaceType() != 'Wall':
                continue
            top = max((v.z() for v in wall.vertices()), default=None)
            if top is not None and top > height:
                height = top
    return height


def _add_additional_lights(space_type, record):
    additional = _f(record['additional_lighting_per_area'])
    if additional == 0.0:
        return
    if any('Additional' in light.nameString() for light in space_type.lights()):
        return

    definition = openstudio.model.LightsDefinition(space_type.model())
    definition.setName(f"{space_type.nameString()} Additional Lights Definition")
    definition.setWattsperSpaceFloorArea(
        openstudio.convert(additional, 'W/ft^2', 'W/m^2').get())
    _set_fraction(definition, 'setReturnAirFraction', record['lighting_fraction_to_return_air'])
    _set_fraction(definition, 'setFractionRadiant', record['lighting_fraction_radiant'])
    _set_fraction(definition, 'setFractionVisible', record['lighting_fraction_visible'])
    lights = openstudio.model.Lights(definition)
    lights.setName(f"{space_type.nameString()} Additional Lights")
    lights.setSpaceType(space_type)


def _wire_lighting_schedule(model, space_type, record, vintage, audit):
    """NECB2015-lineage apply_lighting_schedule: plain schedule at/below the 8.6
    W/m2 threshold; above it, synthesize the occupancy-sensor ruleset —
    hour-by-hour, when occupancy < rel_absence_occ the lighting value is
    multiplied by (1 - rel_absence_occ x occ_sense - personal_control)."""
    from btap.necb import loads
    from btap.necb.loads import schedules as Schedules

    default_set = space_type.defaultScheduleSet()
    schedule_set = default_set.get() if default_set.is_initialized() else None
    if schedule_set is None:
        schedule_set = openstudio.model.DefaultScheduleSet(model)
        schedule_set.setName(f"{space_type.nameString()} Schedule Set")
        space_type.setDefaultScheduleSet(schedule_set)

    data_vintage = loads.data_vintage(vintage)
    lpd = _f(record['lighting_per_area'])
    threshold = _f(_lighting.rules(vintage)['sensor_schedule_lpd_threshold_w_per_ft2'])
    lighting_name = record['lighting_schedule']
    if lighting_name is None:
        return

    if lpd <= threshold:
        schedule_set.setLightingSchedule(
            Schedules.add(model, lighting_name, vintage=data_vintage, audit=audit))
        return

    occupancy_name = '' if record['occupancy_schedule'] is None else str(record['occupancy_schedule'])
    rel_absence = _f(record['rel_absence_occ'])
    personal = _f(record['personal_control'])
    occ_sense = _f(record['occ_sense'])
    schedules = loads.table(data_vintage, 'schedules')
    occupancy_rows = [r for r in schedules if r['name'] == occupancy_name]
    lighting_rows = [r for r in schedules if r['name'] == lighting_name]
    if not occupancy_rows or not lighting_rows:
        audit.warn('lighting',
                   f"sensor-schedule synthesis needs both '{occupancy_name}' and '{lighting_name}' — "
                   'falling back to the plain lighting schedule', target=space_type.nameString())
        schedule_set.setLightingSchedule(
            Schedules.add(model, lighting_name, vintage=data_vintage, audit=audit))
        return

    ruleset_name = (f"{occupancy_name}-{lighting_name}-{_num(rel_absence)}-{_num(personal)}-"
                    f"{_num(occ_sense)}-Light Ruleset")
    existing = next((s for s in sorted_by_name(model.getSchedules())
                     if s.nameString() == ruleset_name), None)
    if existing is not None:
        schedule_set.setLightingSchedule(existing)
        return

    ruleset = _synthesize_sensor_ruleset(model, ruleset_name, occupancy_rows, lighting_rows,
                                         rel_absence, personal, occ_sense)
    schedule_set.setLightingSchedule(ruleset)
    audit.info('lighting', 'occupancy-sensor lighting schedule synthesized (LPD > 8.6 W/m2)',
               target=space_type.nameString(),
               inputs={'rel_absence_occ': rel_absence, 'personal_control': personal,
                       'occ_sense': occ_sense,
                       'occ_control_factor': ruby_round(1 - (rel_absence * occ_sense) - personal, 4)},
               # 4.2.2.1.(16)-(23), NOT 4.2.2.2. — this is the general occupancy-sensor
               # rule. 4.2.2.2. is Lighting Controls in STORAGE GARAGES and has its own
               # module; misciting it here made the storage-garage manifest entry report
               # citations it never earned.
               article='4.2.2.1.(16)-(23); 4.3.2.10. (8.4.4.5.(3) via schedule modulation)')


def _num(value):
    """Ruby's ``"#{float}"`` inside the ruleset NAME: the schedule name is
    matched against existing schedules, so its float rendering is
    load-bearing (0.5 stays '0.5', 0.0 stays '0.0')."""
    from btap._compat import ruby_float_str
    return ruby_float_str(float(value))


def _synthesize_sensor_ruleset(model, name, occupancy_rows, lighting_rows,
                               rel_absence, personal, occ_sense):
    ruleset = openstudio.model.ScheduleRuleset(model)
    ruleset.setName(name)
    occ_control = 1 - (rel_absence * occ_sense) - personal

    for occupancy_row in occupancy_rows:
        day_types = '' if occupancy_row['day_types'] is None else str(occupancy_row['day_types'])
        lighting_row = next((r for r in lighting_rows
                             if r['day_types'] == occupancy_row['day_types']), None)
        if lighting_row is None:
            continue

        values = []
        for hour, occ_value in enumerate(occupancy_row['values']):
            light_value = _f(lighting_row['values'][hour])
            values.append(light_value * occ_control if _f(occ_value) < rel_absence else light_value)

        if 'Default' in day_types:
            day = ruleset.defaultDaySchedule()
            day.setName(f"{name.replace(' Ruleset', '', 1)} Default")
            _add_values(day, values)
        if any(token in day_types for token in _day_tokens()):
            rule = openstudio.model.ScheduleRule(ruleset)
            day = rule.daySchedule()
            day.setName(f"{name.replace(' Ruleset', '', 1)}-{day_types}-Light Day")
            _add_values(day, values)
            start_date = _parse_date(occupancy_row['start_date'])
            end_date = _parse_date(occupancy_row['end_date'])
            rule.setStartDate(openstudio.Date(openstudio.MonthOfYear(start_date.month),
                                              start_date.day))
            rule.setEndDate(openstudio.Date(openstudio.MonthOfYear(end_date.month),
                                            end_date.day))
            if 'Wknd' in day_types:
                rule.setApplySaturday(True)
                rule.setApplySunday(True)
            if 'Wkdy' in day_types:
                for d in _WEEKDAYS:
                    getattr(rule, f"setApply{d}")(True)
            for token, method in _TOKEN_DAYS.items():
                if token in day_types:
                    getattr(rule, f"setApply{method}")(True)
        if 'WntrDsn' in day_types:
            day = openstudio.model.ScheduleDay(model)
            ruleset.setWinterDesignDaySchedule(day)
            _add_values(ruleset.winterDesignDaySchedule(), values)
        if 'SmrDsn' in day_types:
            day = openstudio.model.ScheduleDay(model)
            ruleset.setSummerDesignDaySchedule(day)
            _add_values(ruleset.summerDesignDaySchedule(), values)
    return ruleset


def _day_tokens():
    from btap.necb.loads import schedules as Schedules
    return Schedules.DAY_TOKENS


def _add_values(day_schedule, values):
    for i in range(24):
        # Ruby indexes past the end for the last hour: values[24] is nil, so
        # the 24:00 value is ALWAYS added.
        nxt = values[i + 1] if i + 1 < len(values) else None
        if values[i] == nxt:
            continue
        day_schedule.addValue(openstudio.Time(0, i + 1, 0, 0), _f(values[i]))


def _single_lights_instance(space_type, lights_type):
    instances = [light for light in sorted_by_name(space_type.lights())
                 if 'Additional' not in light.nameString()]
    if not instances:
        definition = openstudio.model.LightsDefinition(space_type.model())
        suffix = ' - LED lighting' if lights_type == 'LED' else ''
        definition.setName(f"{space_type.nameString()} Lights Definition{suffix}")
        lights = openstudio.model.Lights(definition)
        lights.setName(f"{space_type.nameString()} Lights")
        lights.setSpaceType(space_type)
        return lights

    for extra in instances[1:]:
        extra.remove()
    return instances[0]


def _set_fraction(definition, setter, value):
    v = _f(value)
    if v != 0.0:
        getattr(definition, setter)(v)


def _emit_article_coverage(vintage, audit):
    emit_coverage(_lighting.rules(vintage)['article_coverage'], audit)


def _parse_date(text):
    """Ruby's ``Date.parse`` over the vendored ISO-8601 stamps — only month and
    day are read."""
    return datetime.fromisoformat(str(text))
