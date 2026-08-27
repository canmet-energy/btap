"""The storage-garage schedule/sensor helpers (port of
storage_garage/schedules.rb, which reopens StorageGarage there and is
re-exported from this package's ``__init__`` here)."""

from __future__ import annotations

import math
from datetime import datetime

import openstudio

from btap._compat import ruby_round, sorted_by_name

_WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']

#: Sunset-to-sunrise reduction for (3). Astronomical sunset varies through
#: the year; a fixed night window is the schedule-level approximation, and
#: the audit says so. (The gem's one true sunset/sunrise control is
#: Exterior's AstronomicalClock option, which applies to exterior luminaires
#: and cannot drive an interior lighting schedule.)
NIGHT_HOURS = list(range(0, 7)) + list(range(19, 24))


def space_types(spaces):
    result = []
    for s in spaces:
        if not s.spaceType().is_initialized():
            continue
        space_type = s.spaceType().get()
        if not any(space_type.handle() == st.handle() for st in result):
            result.append(space_type)
    return sorted_by_name(result)


def space_type_record(space_type, data_vintage):
    from btap.necb.loads import space_types as SpaceTypes

    bt = space_type.standardsBuildingType()
    st = space_type.standardsSpaceType()
    if not (bt.is_initialized() and st.is_initialized()):
        return None

    return SpaceTypes.find(building_type=bt.get(), space_type=st.get(), vintage=data_vintage)


def lighting_power_density(space):
    floor_area = space.floorArea()
    if not floor_area > 0:
        return 0.0

    instances = list(space.lights())
    if space.spaceType().is_initialized():
        instances += list(space.spaceType().get().lights())
    total = 0.0
    for instance in instances:
        definition = instance.lightsDefinition()
        multiplier = instance.multiplier()
        method = definition.designLevelCalculationMethod()
        if method == 'Watts/Area':
            watts = definition.wattsperSpaceFloorArea()
            total += watts.get() * multiplier if watts.is_initialized() else 0.0
        elif method == 'LightingLevel':
            level = definition.lightingLevel()
            total += level.get() * multiplier / floor_area if level.is_initialized() else 0.0
    return total


def set_lighting_schedule(space_type, ruleset):
    schedule_set = space_type.defaultScheduleSet()
    if not schedule_set.is_initialized():
        return False

    schedule_set.get().setLightingSchedule(ruleset)
    return True


def build_reduced_ruleset(model, name, occupancy_rows, lighting_rows, reduction):
    """A copy of the lighting schedule with the unoccupied hours scaled down.

    "No activity detected for 20 min" has no representation in an hourly
    schedule — the shortest thing a ScheduleRuleset can express is the hour.
    Modulating the hours the occupancy schedule reports as unoccupied is the
    honest approximation, and it is what 4.2.2.1.(16)-(23) already does; the
    20-minute delay is recorded in the audit inputs rather than modelled."""
    ruleset = openstudio.model.ScheduleRuleset(model)
    ruleset.setName(name)
    factor = 1.0 - reduction

    for occupancy_row in occupancy_rows:
        lighting_row = next((r for r in lighting_rows
                             if r['day_types'] == occupancy_row['day_types']), None)
        if lighting_row is None:
            continue

        day_types = '' if occupancy_row['day_types'] is None else str(occupancy_row['day_types'])
        values = []
        for hour, occ in enumerate(occupancy_row['values']):
            light = float(lighting_row['values'][hour])
            values.append(light * factor if float(occ) == 0.0 else light)
        write_day(model, ruleset, day_types, values, occupancy_row, name)
    return ruleset


def build_night_reduced_ruleset(model, name, source, reduction):
    ruleset = openstudio.model.ScheduleRuleset(model)
    ruleset.setName(name)
    factor = 1.0 - reduction
    base = source.to_ScheduleRuleset()
    default_values = (day_values(base.get().defaultDaySchedule()) if base.is_initialized()
                      else [1.0] * 24)
    values = [v * factor if hour in NIGHT_HOURS else v
              for hour, v in enumerate(default_values)]
    write_values(ruleset.defaultDaySchedule(), values)
    return ruleset


def day_values(day_schedule):
    values = [0.0] * 24
    times = list(day_schedule.times())
    schedule_values = list(day_schedule.values())
    for i, time in enumerate(times):
        hour = math.ceil(time.totalHours())
        value = schedule_values[i]
        for h in range(24):
            if h < hour and values[h] == 0.0:
                values[h] = value
    return values


def write_day(model, ruleset, day_types, values, row, name):
    from btap.necb.loads import schedules as Schedules

    if 'Default' in day_types:
        ruleset.defaultDaySchedule().setName(f"{name.replace(' Ruleset', '', 1)} Default")
        write_values(ruleset.defaultDaySchedule(), values)
    if not any(token in day_types for token in Schedules.DAY_TOKENS):
        return

    rule = openstudio.model.ScheduleRule(ruleset)
    rule.daySchedule().setName(f"{name.replace(' Ruleset', '', 1)}-{day_types}")
    write_values(rule.daySchedule(), values)
    start_date = _parse_date(row['start_date'])
    end_date = _parse_date(row['end_date'])
    rule.setStartDate(openstudio.Date(openstudio.MonthOfYear(start_date.month), start_date.day))
    rule.setEndDate(openstudio.Date(openstudio.MonthOfYear(end_date.month), end_date.day))
    if 'Wknd' in day_types:
        rule.setApplySaturday(True)
        rule.setApplySunday(True)
    if 'Wkdy' in day_types:
        for d in _WEEKDAYS:
            getattr(rule, f"setApply{d}")(True)


def write_values(day_schedule, values):
    day_schedule.clearValues()
    for hour, value in enumerate(values):
        day_schedule.addValue(openstudio.Time(0, hour + 1, 0, 0), value)


def add_daylight_control(space, band_area_m2, audit, article, inputs):
    """The zone-level daylighting control for (4).

    Daylighting.add_controls SKIPS a zone that already carries a primary
    control, so a garage that also qualified under 4.2.2.1 would silently
    lose this one. Table 4.2.1.6. defers garages to 4.2.2.2 precisely so the
    two rules do not both apply, but the precedence is made explicit here
    rather than left to whichever pass ran first."""
    zone = space.thermalZone()
    if not zone.is_initialized():
        audit.warn('lighting',
                   f"STORAGE GARAGE '{space.nameString()}' HAS NO THERMAL ZONE — the 4.2.2.2.(4) daylight "
                   'response cannot be attached', target=space.nameString(),
                   article=f"{article}(4)")
        return False

    zone = zone.get()
    if zone.primaryDaylightingControl().is_initialized():
        audit.info('lighting',
                   f"zone '{zone.nameString()}' already carries a primary daylighting control — the "
                   '4.2.2.2.(4) response is satisfied by it and no second control is added',
                   target=space.nameString(), inputs=inputs, article=f"{article}(4)")
        return False

    control = openstudio.model.DaylightingControl(space.model())
    control.setName(f"{space.nameString()} Garage Daylight Sensor")
    control.setSpace(space)
    control.setLightingControlType('Stepped')
    control.setNumberofSteppedControlSteps(1)  # on/off: the sentence asks only that power be reduced
    centre = space_centre(space) if space.floorArea() > 0 else None
    if centre:
        control.setPositionXCoordinate(centre[0])
        control.setPositionYCoordinate(centre[1])
        control.setPositionZCoordinate(0.8)
    zone.setPrimaryDaylightingControl(control)
    fraction = min(band_area_m2 / space.floorArea(), 1.0) if space.floorArea() > 0 else 0.0
    zone.setFractionofZoneControlledbyPrimaryDaylightingControl(fraction)
    merged = dict(inputs)
    merged['zone_fraction_controlled'] = ruby_round(fraction, 4)
    audit.decision('lighting',
                   'storage-garage perimeter luminaires respond to daylight (>150 W within 6.1 m of a '
                   '40%-glazed perimeter wall)',
                   target=space.nameString(),
                   inputs=merged,
                   article=f"{article}(4)")
    return True


def space_centre(space):
    points = [v for s in space.surfaces() if s.surfaceType() == 'Floor' for v in s.vertices()]
    if not points:
        return None

    return [sum(p.x() for p in points) / len(points), sum(p.y() for p in points) / len(points)]


def _parse_date(text):
    """Ruby's ``Date.parse`` over the vendored ISO-8601 stamps — only month and
    day are read."""
    return datetime.fromisoformat(str(text))
