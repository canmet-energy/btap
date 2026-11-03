"""Zone thermostat and setpoint-schedule primitives — code-family-neutral.

#192's controls cluster. `canmet-energy/campus` carries
`adjust_thermostat_deadband`, `unoccupied_temp_setback` and
`windowed_setpoint_and_load_override`, and `btap.modeling` had NO setpoint
setter at all — measured, zero hits for
`setHeatingSetpointTemperatureSchedule` or its cooling counterpart. The one
thermostat in the package (`hvac/catalog_report.py:290`) constructs a BARE
`ThermostatSetpointDualSetpoint` for the catalogue's sizing probe and sets no
setpoints, which is why a grep for the class looked like capability and was
not.

For stock work the setpoints and their setback are a vintage marker as much as
a comfort choice: a building with no night setback runs its plant through
unoccupied hours, and that is much of why a pre-1980 operation looks unlike a
modern one. A recipe that cannot say "this vintage had no setback" cannot
describe the building.

Nothing here holds a value. WHICH setpoints a code requires stays in
`btap.codes`; `btap.codes.necb` has its own thermostat path and this module
does not change it.
"""

from __future__ import annotations

from btap._compat import opt, sorted_by_name
from btap.modeling.hvac.components.schedules import constant_ruleset


def setback_schedule(model, name, *, occupied_c, setback_c,
                     occupied_from_hour, occupied_to_hour):
    """A daily schedule at ``occupied_c`` during occupied hours and
    ``setback_c`` outside them.

    The vintage shape the campus measures reach for: a setback is a step
    between two values at two hours of the day, not a continuous profile.

    Built on the same `ScheduleDay.addValue(Time, value)` idiom as
    `components/schedules.py::constant_ruleset`, and REUSED BY NAME the same
    way — a recipe applying one setback to forty zones should produce one
    schedule, not forty. The name is the dedupe key, so it has to encode the
    values; this is `opaque_at_conductance`'s pattern, and it is safe here for
    the reason it is safe there: this function RETURNS the schedule and writes
    nothing into it afterwards. (#186 is the counter-example — reuse by name
    is unsafe when the caller then writes.)

    :param occupied_from_hour: whole hour the occupied period starts, 0-23.
    :param occupied_to_hour: whole hour it ends, 1-24 and after the start.
    :returns: an `openstudio.model.ScheduleRuleset`.
    """
    import openstudio

    start, end = int(occupied_from_hour), int(occupied_to_hour)
    if not 0 <= start < end <= 24:
        raise ValueError(
            f'the occupied period must satisfy 0 <= from < to <= 24; got '
            f'from={occupied_from_hour!r} to={occupied_to_hour!r}')
    if start == 0 and end == 24:
        # No unoccupied hours, so there is no setback. Say so rather than
        # emitting a two-step schedule whose second step never applies.
        return constant_ruleset(model, name, float(occupied_c))

    existing = next((s for s in model.getScheduleRulesets()
                     if s.nameString() == name), None)
    if existing is not None:
        return existing

    schedule = openstudio.model.ScheduleRuleset(model)
    schedule.setName(name)
    day = schedule.defaultDaySchedule()
    day.setName(f'{name} Default')
    # Steps are "the value UNTIL this time", so the setback leads and trails.
    if start > 0:
        day.addValue(openstudio.Time(0, start, 0, 0), float(setback_c))
    day.addValue(openstudio.Time(0, end, 0, 0), float(occupied_c))
    if end < 24:
        day.addValue(openstudio.Time(0, 24, 0, 0), float(setback_c))
    return schedule


def _as_schedule(model, value, *, name):
    """A schedule from either a schedule or a scalar temperature.

    phylroy's rule for the load primitives — "there should be flexibility on
    how the loads are set, a scaling factor or setting the value directly" —
    applied to setpoints: a recipe usually carries a number, while a caller
    with a real profile already holds a schedule object.
    """
    if value is None:
        return None
    if hasattr(value, 'nameString'):
        return value
    return constant_ruleset(model, name, float(value))


def set_zone_thermostat(zone, *, heating=None, cooling=None, audit=None,
                        step='hvac'):
    """Heating and/or cooling setpoints on ``zone``'s dual-setpoint thermostat.

    Creates the thermostat if the zone has none, which is the case that
    matters: CLAUDE.md records that a model with NO thermostat anywhere is a
    fatal preflight gate precisely because it RUNS and produces a numerically
    valid, physically meaningless answer. A stock generator that builds zones
    must be able to give them setpoints.

    :param heating: a `Schedule`, or a scalar temperature in degrees C.
    :param cooling: likewise.
    :returns: the `ThermostatSetpointDualSetpoint`, or None when given
        neither setpoint.
    """
    import openstudio

    if heating is None and cooling is None:
        return None

    model = zone.model()
    thermostat = opt(zone.thermostatSetpointDualSetpoint())
    if thermostat is None:
        thermostat = openstudio.model.ThermostatSetpointDualSetpoint(model)
        thermostat.setName(f'{zone.nameString()} Thermostat')
        if not zone.setThermostatSetpointDualSetpoint(thermostat):
            raise ValueError(
                f'the model refused a thermostat on {zone.nameString()!r}')

    heating_schedule = _as_schedule(
        model, heating, name=f'Heating Setpoint {heating} C')
    cooling_schedule = _as_schedule(
        model, cooling, name=f'Cooling Setpoint {cooling} C')

    # The long names, not `setHeatingSchedule` — the header marks that pair
    # `\\deprecated`, the same trap as the fan efficiency alias in #192's
    # cluster 1.
    if heating_schedule is not None:
        if not thermostat.setHeatingSetpointTemperatureSchedule(
                heating_schedule):
            raise ValueError(
                'the model refused the heating setpoint schedule on '
                f'{zone.nameString()!r}')
    if cooling_schedule is not None:
        if not thermostat.setCoolingSetpointTemperatureSchedule(
                cooling_schedule):
            raise ValueError(
                'the model refused the cooling setpoint schedule on '
                f'{zone.nameString()!r}')

    if audit is not None:
        audit.info(step, 'zone setpoints set', target=zone.nameString(),
                   inputs={'heating': getattr(heating_schedule, 'nameString',
                                              lambda: None)(),
                           'cooling': getattr(cooling_schedule, 'nameString',
                                              lambda: None)()})
    return thermostat


def set_thermostats_in_model(model, *, heating=None, cooling=None, audit=None,
                             step='hvac'):
    """`set_zone_thermostat` on every thermal zone in ``model``.

    :returns: the number of zones set.
    """
    if heating is None and cooling is None:
        return 0
    count = 0
    for zone in sorted_by_name(model.getThermalZones()):
        if set_zone_thermostat(zone, heating=heating, cooling=cooling,
                               audit=audit, step=step) is not None:
            count += 1
    return count
