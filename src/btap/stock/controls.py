"""The controls section of a recipe: setpoints, economizer, DCV, daylighting.

Covers osruby's `ecm_temp_setback`, `ecm_heating_cooling_setpoints`,
`ecm_economizers` and `ecm_dcv`, and campus's `adjust_thermostat_deadband`,
`unoccupied_temp_setback`, `economizer_control`,
`demand_controlled_ventilation`, `add_daylight_sensors` and
`daylight_and_occupancy_controls`.

For a stock building these are vintage markers as much as controls: a
pre-1980 building generally has no setback, no economizer and no daylight
control, and the recipe has to be able to say so by RECORDING the absence
rather than by staying silent about it. An omitted key and a key that says
"none" are different claims, and only the second is a measurement.
"""

from __future__ import annotations

from btap._compat import opt, sorted_by_name

# 24:00 reads back as hours() == 0 because it rolls into the next day;
# totalHours() gives 24.0. Using hours() here would make a 24:00 step sort
# first and invert every schedule read.
_DAY_END_HOURS = 24.0


def _schedule_steps(schedule):
    """A ruleset's default-day steps as (hour, value), or None.

    Only a `ScheduleRuleset` is read. A `ScheduleCompact`, a
    `ScheduleConstant` or an EMS-driven schedule is reported as unreadable
    rather than approximated: a setpoint profile the writer cannot see is not
    a setpoint profile it may guess.
    """
    ruleset = opt(schedule.to_ScheduleRuleset())
    if ruleset is None:
        return None
    day = ruleset.defaultDaySchedule()
    return [(round(t.totalHours(), 4), round(v, 4))
            for t, v in zip(day.times(), day.values())]


def _setpoint_profile(steps):
    """A setback profile from a step list: the two values and the hours.

    A setback is a step between two values at two hours of the day, so the
    recipe records the OCCUPIED and SETBACK values and the occupied window
    rather than the raw step list. A profile with one step has no setback and
    says so; one with more than three steps is reported verbatim, because
    collapsing it would be a guess about which value is "the" setpoint.
    """
    if not steps:
        return None
    values = [v for _h, v in steps]
    if len(steps) == 1:
        return {'constant_c': values[0], 'has_setback': False}
    if len(steps) > 3:
        return {'steps': steps, 'has_setback': True,
                'note': 'more than three steps — reported verbatim rather '
                        'than collapsed to an occupied/setback pair'}
    occupied, setback = max(values), min(values)
    # "Value until this hour", so the occupied block is the step whose value
    # is the occupied one.
    window = [h for h, v in steps if v == occupied]
    return {'occupied_c': occupied, 'setback_c': setback,
            'has_setback': True,
            'occupied_until_hour': window[0] if window else None}


def _thermostats(model):
    heating, cooling, unreadable = [], [], []
    for zone in sorted_by_name(model.getThermalZones()):
        thermostat = opt(zone.thermostatSetpointDualSetpoint())
        if thermostat is None:
            continue
        for schedule_opt, bucket, label in (
                (thermostat.heatingSetpointTemperatureSchedule(), heating,
                 'heating'),
                (thermostat.coolingSetpointTemperatureSchedule(), cooling,
                 'cooling')):
            schedule = opt(schedule_opt)
            if schedule is None:
                continue
            steps = _schedule_steps(schedule)
            if steps is None:
                unreadable.append(
                    {'zone': zone.nameString(), 'which': label,
                     'schedule': schedule.nameString(),
                     'why': 'not a ScheduleRuleset, so its daily profile is '
                            'not readable without approximating it'})
                continue
            bucket.append((schedule.nameString(), tuple(steps)))

    out = {}
    for label, bucket in (('heating', heating), ('cooling', cooling)):
        if not bucket:
            continue
        distinct = sorted({steps for _n, steps in bucket})
        profile = _setpoint_profile(list(distinct[0])) if distinct else None
        out[f'{label}_setpoint'] = profile
        out[f'{label}_setpoint_from'] = {
            'zones': len(bucket),
            'distinct_profiles': len(distinct),
            'schedules': sorted({n for n, _s in bucket})[:5],
        }
        if len(distinct) > 1:
            out[f'{label}_setpoint_from']['spread_warning'] = (
                f'{len(distinct)} distinct {label} profiles across '
                f'{len(bucket)} zones — the first is reported and one profile '
                'cannot stand for the set')
    if unreadable:
        out['unreadable'] = unreadable
    return out


def _economizers(model):
    """Economizer control per air loop, with absence recorded as a value."""
    from btap.modeling.hvac.ventilation import economizer_controller

    rows = []
    for air_loop in sorted_by_name(model.getAirLoopHVACs()):
        controller = economizer_controller(air_loop)
        if controller is None:
            continue
        rows.append({
            'air_loop': air_loop.nameString(),
            'economizer_control_type': controller.getEconomizerControlType(),
            'economizer_control_action_type':
                controller.getEconomizerControlActionType(),
            'economizer_maximum_limit_dry_bulb_temperature':
                opt(controller.getEconomizerMaximumLimitDryBulbTemperature()),
            'economizer_minimum_limit_dry_bulb_temperature':
                opt(controller.getEconomizerMinimumLimitDryBulbTemperature()),
            'economizer_maximum_limit_enthalpy':
                opt(controller.getEconomizerMaximumLimitEnthalpy()),
            'economizer_maximum_limit_dewpoint_temperature':
                opt(controller.getEconomizerMaximumLimitDewpointTemperature()),
            'dcv_enabled':
                controller.controllerMechanicalVentilation()
                .demandControlledVentilation(),
        })
    if not rows:
        return None
    types = sorted({r['economizer_control_type'] for r in rows})
    return {
        'by_air_loop': rows,
        'from': {
            'air_loops_with_outdoor_air': len(rows),
            'distinct_control_types': types,
            # 'NoEconomizer' is the IDD default, so this is the distinction
            # between "none of these loops has one" and "we did not look".
            'any_economizer': any(t != 'NoEconomizer' for t in types),
            'any_dcv': any(r['dcv_enabled'] for r in rows),
        },
    }


def _daylighting(model):
    controls = sorted_by_name(model.getDaylightingControls())
    if not controls:
        # Recorded, not omitted: "this building has no daylighting control"
        # is a vintage fact and a different claim from silence.
        return {'controls': [], 'from': {'count': 0,
                                         'note': 'no daylighting control in '
                                                 'this model'}}
    rows = []
    for control in controls:
        space = opt(control.space())
        rows.append({
            'name': control.nameString(),
            'space': space.nameString() if space is not None else None,
            # A plain `double`, per the header — NOT an optional. The four
            # economizer limits above ARE `boost::optional<double>`, so the
            # two cases sit a few lines apart and only the header tells them
            # apart. D-79's guard is for optionals; over-applying it raises.
            'illuminance_setpoint_lux': control.illuminanceSetpoint(),
            'control_type': control.lightingControlType(),
            'position': [round(control.positionXCoordinate(), 3),
                         round(control.positionYCoordinate(), 3),
                         round(control.positionZCoordinate(), 3)],
        })
    return {'controls': rows, 'from': {'count': len(rows)}}


def controls_section(model, audit=None):
    """The recipe's controls section.

    :returns: ``{'thermostats': {...}, 'economizers': {...}|None,
                 'daylighting': {...}}``
    """
    section = {
        'thermostats': _thermostats(model),
        'economizers': _economizers(model),
        'daylighting': _daylighting(model),
    }
    if audit is not None:
        economizers = section['economizers'] or {}
        audit.info('recipe', 'controls read',
                   inputs={
                       'air_loops_with_outdoor_air':
                           economizers.get('from', {})
                           .get('air_loops_with_outdoor_air', 0),
                       'any_economizer':
                           economizers.get('from', {}).get('any_economizer'),
                       'daylighting_controls':
                           section['daylighting']['from']['count'],
                   })
    return section
