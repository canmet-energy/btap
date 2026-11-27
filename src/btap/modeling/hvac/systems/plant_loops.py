"""Config-driven plant loop builders (NECB setpoints ported from
openstudio-standards setup_hw_loop_with_components et al.)."""

from __future__ import annotations

import json
import re

import openstudio

from btap.modeling.hvac.components import schedules

#: Feature stamped on a boiler's additionalProperties to carry the part-load
#: curve class the reference selection elected (D-89). The NECB efficiency
#: pass reads it; nothing in this layer interprets its value.
BOILER_PART_LOAD_CLASS_FEATURE = 'btap_part_load_curve_class'
#: Feature stamped on a boiler to say which half of a staged plant it is
#: ('primary' / 'secondary'), so the NECB 8.4.x.9.(6) staging rules identify the
#: pair by the builder's own mark rather than by matching its display name
#: (DF-13). Set where this layer builds the pair, and read in TWO places: by
#: `_boiler_role` below, as the first source of a loop's primary/secondary
#: order for reuse matching, and by the codes-side D-90 staging pass
#: (`btap.codes.necb.hvac.efficiency._plant_role`).
BOILER_PLANT_ROLE_FEATURE = 'btap_plant_role'
#: Serialized, normalized temperature/setpoint profile on an explicitly
#: configured plant. Unstamped loops are the legacy 82/7 C plants.
TEMPERATURE_PROFILE_FEATURE = 'btap_temperature_profile'
#: Positive margin, in kelvins, applied above the warmest served-zone
#: dew-point sensor by the chilled-water EMS reset. This is the maximum of
#: the per-zone margins stored in ``DEWPOINT_ZONE_MARGINS_FEATURE``.
DEWPOINT_MARGIN_FEATURE = 'btap_dewpoint_margin_k'
#: Serialized ``{zone_handle: margin_k}`` identity for a shared chilled-water
#: loop's dew-point reset. Handles keep EMS object names collision-free when
#: distinct zone names sanitize to the same identifier.
DEWPOINT_ZONE_MARGINS_FEATURE = 'btap_dewpoint_zone_margins'
HOT_WATER_SOURCES = frozenset({'boiler', 'district', 'awhp'})

#: How an air-to-water heat-pump hot-water plant meets its load (phylroy,
#: 2026-11-26): ``low_temperature`` — the new-design norm — runs the loop at
#: 60 C with terminals autosized for it and the boiler as backup to the SAME
#: setpoint; ``boiler_lift`` — the retrofit arrangement — keeps the
#: conventional 82 C loop, the heat pump preheating to its 60 C limit and the
#: boiler lifting the rest of the way.
HOT_WATER_SUPPLY_MODES = ('low_temperature', 'boiler_lift')
#: A heat-pump plant's backup boiler burns one of these.
HEAT_PUMP_BACKUP_FUELS = ('NaturalGas', 'Electricity')
HOT_WATER_SOURCE_FEATURE = 'btap_hot_water_source'
HOT_WATER_SUPPLY_FEATURE = 'btap_hot_water_supply'
HEAT_PUMP_CONTROLS_FEATURE = 'btap_heat_pump_controls'

#: The heat-pump plant's control settings (#244, Stream C). Every value is an
#: authored engineering default, not a code value, and the defaults reproduce
#: the plant as first built (PR #243) exactly:
#:
#: - ``outdoor_reset_c``: the outdoor temperatures [cold, mild] the loop
#:   reset runs between;
#: - ``loop_reset_c``: the loop supply setpoints [at cold, at mild]. The
#:   default depends on ``hw_supply``: [60, 45] low temperature, [82, 60]
#:   boiler lift;
#: - ``heat_pump_max_c``: the heat pump's outlet setpoint ceiling. Low
#:   temperature needs the loop reset at or below it; boiler lift needs the
#:   cold end above it (that is what the boiler lifts);
#: - ``backup_deadband_k``: how far below the loop setpoint the backup boiler
#:   holds wherever the heat pump can reach the loop setpoint. At 0 the boiler
#:   chased the heat pump's defrost dip (Fable, PR #243).
#:
#: There is deliberately NO sizing factor. EnergyPlus scales the heat pump's
#: load-side FLOW with it, and the heat pump is in series on the loop's only
#: supply branch, so a smaller one starves the loop. Measured on the
#: boiler-lift baseboard plant (2026-11-27): factor 0.4 gave 0.3 instead of
#: 0.8 L/s, and occupied unmet heating rose from 57 h to 135 h (260 h at 0.25).
HEAT_PUMP_CONTROL_DEFAULTS = {
    'outdoor_reset_c': (-16.0, 0.0),
    'heat_pump_max_c': 60.0,
    'backup_deadband_k': 1.0,
}
HEAT_PUMP_LOOP_RESET_DEFAULTS = {
    'low_temperature': (60.0, 45.0),
    'boiler_lift': (82.0, 60.0),
}
HEAT_PUMP_CONTROL_KEYS = frozenset(HEAT_PUMP_CONTROL_DEFAULTS) | {'loop_reset_c'}
#: The loop's fixed design temperature difference, K, per supply mode.
HEAT_PUMP_LOOP_DELTA_T = {'low_temperature': 11.0, 'boiler_lift': 16.0}
_HEAT_PUMP_LOOP_NAME = 'Heat Pump Hot Water Loop'
CHILLED_WATER_SOURCES = frozenset({
    'water_cooled', 'air_cooled', 'district',
})
_HOT_WATER_SHELL_COMPONENT_TYPES = frozenset({
    'OS_Connector_Mixer',
    'OS_Connector_Splitter',
    'OS_Node',
    'OS_Pipe_Adiabatic',
    'OS_Pump_VariableSpeed',
})


def _normalize_temperature_profile(profile, loop_kind):
    """Validate and normalize an explicit plant temperature profile.

    ``None`` deliberately means the legacy profile and remains unstamped.
    Explicit profiles are data, not mutable defaults: their complete
    temperature identity is serialized onto the loop and participates in
    reuse matching.
    """
    if profile is None:
        return None
    if not isinstance(profile, dict):
        raise ValueError(f'{loop_kind} temperature profile must be a dict')

    required = {
        'name',
        'design_exit_temperature',
        'design_temperature_difference',
        'setpoint_temperature',
    }
    unknown = sorted(set(profile) - required)
    missing = sorted(required - set(profile))
    if missing:
        raise ValueError(
            f"{loop_kind} temperature profile is missing {', '.join(missing)}")
    if unknown:
        raise ValueError(
            f"{loop_kind} temperature profile has unknown keys {unknown!r}")

    name = profile['name']
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f'{loop_kind} temperature profile name must be non-empty')

    normalized = {'name': name.strip()}
    for key in required - {'name'}:
        value = profile[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f'{loop_kind} temperature profile {key} must be numeric')
        normalized[key] = float(value)

    if not -20.0 <= normalized['design_exit_temperature'] <= 100.0:
        raise ValueError(
            f'{loop_kind} design_exit_temperature must be between -20 and 100 C')
    if not 0.0 < normalized['design_temperature_difference'] <= 50.0:
        raise ValueError(
            f'{loop_kind} design_temperature_difference must be between 0 and 50 K')
    if not -20.0 <= normalized['setpoint_temperature'] <= 100.0:
        raise ValueError(
            f'{loop_kind} setpoint_temperature must be between -20 and 100 C')
    return normalized


def validate_plant_config(config):
    """Validate plant flags, sources, and profiles without mutating a model."""
    for key in ('needs_boiler', 'needs_chiller'):
        if key in config and not isinstance(config[key], bool):
            raise ValueError(f'{key} must be a boolean')

    hot_source = config.get('hw_source', 'boiler')
    if hot_source not in HOT_WATER_SOURCES:
        raise ValueError(
            f"hw_source must be one of {sorted(HOT_WATER_SOURCES)!r}")
    if 'hw_supply' in config:
        if hot_source != 'awhp':
            raise ValueError("hw_supply applies only to hw_source 'awhp'")
        if config['hw_supply'] not in HOT_WATER_SUPPLY_MODES:
            raise ValueError(
                f"hw_supply must be one of {list(HOT_WATER_SUPPLY_MODES)!r}")
    if config.get('hw_controls') is not None:
        if hot_source != 'awhp':
            raise ValueError("hw_controls applies only to hw_source 'awhp'")
        heat_pump_controls(config.get('hw_supply', 'low_temperature'), config['hw_controls'])
    if hot_source == 'awhp':
        if config.get('boiler_fuel', 'NaturalGas') not in HEAT_PUMP_BACKUP_FUELS:
            raise ValueError(
                f"a heat-pump plant's backup boiler_fuel must be one of {list(HEAT_PUMP_BACKUP_FUELS)!r}")
        # Refused HERE, before any teardown, not inside the builder (Fable,
        # PR #243: the builder raised after remove_existing had run).
        for key in ('hot_water_profile', 'boiler_part_load_curve_class'):
            if config.get(key) is not None:
                raise ValueError(
                    f"{key} does not apply to a heat-pump plant (hw_source 'awhp'), "
                    "which sets its own temperatures and has one backup boiler")
    chilled_source = config.get('chw_source', 'water_cooled')
    if chilled_source not in CHILLED_WATER_SOURCES:
        raise ValueError(
            f"chw_source must be one of {sorted(CHILLED_WATER_SOURCES)!r}")

    _normalize_temperature_profile(
        config.get('hot_water_profile'), 'hot_water')
    _normalize_temperature_profile(
        config.get('chilled_water_profile'), 'chilled_water')


def _temperature_profile_key(profile, loop_kind):
    normalized = _normalize_temperature_profile(profile, loop_kind)
    if normalized is None:
        return None
    return json.dumps({'loop_kind': loop_kind, **normalized},
                      sort_keys=True, separators=(',', ':'))


def _temperature_profile_matches(loop, profile, loop_kind):
    requested = _temperature_profile_key(profile, loop_kind)
    stored = loop.additionalProperties().getFeatureAsString(
        TEMPERATURE_PROFILE_FEATURE)
    if requested is None:
        return not stored.is_initialized()
    return stored.is_initialized() and stored.get() == requested


def _stamp_temperature_profile(loop, profile, loop_kind):
    key = _temperature_profile_key(profile, loop_kind)
    if key is not None:
        loop.additionalProperties().setFeature(TEMPERATURE_PROFILE_FEATURE, key)


def temperature_profile(loop):
    """Return an explicitly stamped plant profile, or ``None`` for legacy."""
    stored = loop.additionalProperties().getFeatureAsString(
        TEMPERATURE_PROFILE_FEATURE)
    return json.loads(stored.get()) if stored.is_initialized() else None


def _scheduled_plant_setpoint(model, loop, temperature, label):
    schedule = openstudio.model.ScheduleConstant(model)
    schedule.setName(f'{loop.nameString()} {label} Setpoint')
    schedule.setValue(temperature)
    manager = openstudio.model.SetpointManagerScheduled(model, schedule)
    manager.setName(f'{loop.nameString()} {label} Setpoint Manager')
    manager.addToNode(loop.supplyOutletNode())
    return schedule


def _plant_setpoint_schedule(loop):
    outlet = loop.supplyOutletNode().handle()
    for manager in loop.model().getSetpointManagerScheduleds():
        node = manager.setpointNode()
        if not node.is_initialized() or node.get().handle() != outlet:
            continue
        schedule = manager.schedule().to_ScheduleConstant()
        if schedule.is_initialized():
            return schedule.get()
    return None


def _ems_identifier(value):
    identifier = re.sub(r'[^A-Za-z0-9_]', '_', str(value))
    if not identifier or identifier[0].isdigit():
        identifier = f'BTAP_{identifier}'
    return identifier


def _dewpoint_zone_margins(loop):
    stored = loop.additionalProperties().getFeatureAsString(
        DEWPOINT_ZONE_MARGINS_FEATURE)
    if not stored.is_initialized():
        return {}
    margins = json.loads(stored.get())
    if not isinstance(margins, dict):
        raise ValueError('dew-point zone margins must be a JSON object')
    return {str(handle): float(margin)
            for handle, margin in margins.items()}


def _dewpoint_sensor_name(sensor_prefix, zone_handle):
    token = _ems_identifier(str(zone_handle).replace('-', ''))
    return f'{sensor_prefix}{token}'


def _stamp_dewpoint_margins(loop, margins):
    maximum = max(margins.values())
    properties = loop.additionalProperties()
    properties.setFeature(
        DEWPOINT_ZONE_MARGINS_FEATURE,
        json.dumps(margins, sort_keys=True, separators=(',', ':')))
    properties.setFeature(DEWPOINT_MARGIN_FEATURE, maximum)
    return maximum


def _set_dewpoint_program_lines(program, sensors, pressure_sensor, actuator,
                                prefix, margin, base_setpoint):
    maximum = f'{prefix}_Maximum'
    candidate = f'{prefix}_Candidate'

    def dewpoint(sensor):
        return f'@TdpFnWPb {sensor.nameString()} {pressure_sensor.nameString()}'

    lines = [f'SET {maximum} = {dewpoint(sensors[0])}']
    for sensor in sensors[1:]:
        lines.extend([
            f'SET {candidate} = {dewpoint(sensor)}',
            f'IF {candidate} > {maximum}',
            f'  SET {maximum} = {candidate}',
            'ENDIF',
        ])
    lines.extend([
        f'SET {actuator.nameString()} = {maximum} + {margin:g}',
        f'IF {actuator.nameString()} < {base_setpoint:g}',
        f'  SET {actuator.nameString()} = {base_setpoint:g}',
        'ENDIF',
    ])
    program.setLines(lines)


def configure_dewpoint_reset(loop, zones, margin):
    """Reset an explicit chilled-water profile above served-zone dew point.

    The setpoint is ``max(profile setpoint, warmest zone dew point + margin)``.
    Raising chilled-water temperature sacrifices cooling capacity rather than
    allowing condensation. Calling again with more zones updates the one
    program for this loop instead of creating competing actuators.
    """
    profile = temperature_profile(loop)
    if profile is None or profile.get('loop_kind') != 'chilled_water':
        raise ValueError('dew-point reset requires an explicit chilled-water profile')
    if isinstance(margin, bool) or not isinstance(margin, (int, float)):
        raise ValueError('dew-point margin must be numeric')
    margin = float(margin)
    if not 0.0 < margin <= 10.0:
        raise ValueError('dew-point margin must be between 0 and 10 K')
    if not zones:
        raise ValueError('dew-point reset requires at least one thermal zone')

    schedule = _plant_setpoint_schedule(loop)
    if schedule is None:
        raise ValueError(
            'dew-point reset requires the explicit profile ScheduleConstant setpoint')

    model = loop.model()
    token = _ems_identifier(str(loop.handle()).replace('-', ''))
    prefix = f'BTAP_{token}_Dewpoint_Reset'
    sensor_prefix = f'{prefix}_Humidity_'

    by_name = {sensor.nameString(): sensor
               for sensor in model.getEnergyManagementSystemSensors()}
    margins = _dewpoint_zone_margins(loop)
    for zone in zones:
        handle = str(zone.handle())
        margins[handle] = max(margins.get(handle, 0.0), margin)
        name = _dewpoint_sensor_name(sensor_prefix, handle)
        sensor = by_name.get(name)
        if sensor is None:
            sensor = openstudio.model.EnergyManagementSystemSensor(
                model, 'Zone Mean Air Humidity Ratio')
            sensor.setName(name)
            by_name[name] = sensor
        sensor.setKeyName(zone.nameString())

    zones_by_handle = {
        str(zone.handle()): zone for zone in model.getThermalZones()
    }
    for handle in list(margins):
        if handle not in zones_by_handle:
            stale = by_name.get(_dewpoint_sensor_name(sensor_prefix, handle))
            if stale is not None:
                stale.remove()
            margins.pop(handle)
    sensors = []
    for handle in sorted(margins):
        name = _dewpoint_sensor_name(sensor_prefix, handle)
        sensor = by_name.get(name)
        if sensor is None:
            sensor = openstudio.model.EnergyManagementSystemSensor(
                model, 'Zone Mean Air Humidity Ratio')
            sensor.setName(name)
            sensor.setKeyName(zones_by_handle[handle].nameString())
            by_name[name] = sensor
        sensors.append(sensor)
    effective_margin = _stamp_dewpoint_margins(loop, margins)

    pressure_name = f'{prefix}_Pressure'
    pressure_sensor = by_name.get(pressure_name)
    if pressure_sensor is None:
        pressure_sensor = openstudio.model.EnergyManagementSystemSensor(
            model, 'Site Outdoor Air Barometric Pressure')
        pressure_sensor.setName(pressure_name)
        pressure_sensor.setKeyName('Environment')

    actuator_name = f'{prefix}_Setpoint'
    actuator = next(
        (item for item in model.getEnergyManagementSystemActuators()
         if item.nameString() == actuator_name),
        None)
    if actuator is None:
        actuator = openstudio.model.EnergyManagementSystemActuator(
            schedule, 'Schedule:Constant', 'Schedule Value')
        actuator.setName(actuator_name)

    program_name = f'{prefix}_Program'
    program = next(
        (item for item in model.getEnergyManagementSystemPrograms()
         if item.nameString() == program_name),
        None)
    if program is None:
        program = openstudio.model.EnergyManagementSystemProgram(model)
        program.setName(program_name)

    _set_dewpoint_program_lines(
        program, sensors, pressure_sensor, actuator, prefix, effective_margin,
        profile['setpoint_temperature'])

    manager_name = f'{prefix}_Manager'
    manager = next(
        (item for item in model.getEnergyManagementSystemProgramCallingManagers()
         if item.nameString() == manager_name),
        None)
    if manager is None:
        manager = openstudio.model.EnergyManagementSystemProgramCallingManager(
            model)
        manager.setName(manager_name)
        manager.setCallingPoint('BeginTimestepBeforePredictor')
    if not any(item.handle() == program.handle() for item in manager.programs()):
        manager.addProgram(program)

    return program


def remove_zones_from_dewpoint_reset(loop, zones):
    """Remove zones from this loop's dew-point control during subset teardown."""
    margins = _dewpoint_zone_margins(loop)
    if not margins:
        return

    model = loop.model()
    token = _ems_identifier(str(loop.handle()).replace('-', ''))
    prefix = f'BTAP_{token}_Dewpoint_Reset'
    sensor_prefix = f'{prefix}_Humidity_'
    target_handles = {str(zone.handle()) for zone in zones}
    target_names = {
        _dewpoint_sensor_name(sensor_prefix, handle)
        for handle in target_handles
    }
    for sensor in list(model.getEnergyManagementSystemSensors()):
        if sensor.nameString() in target_names:
            sensor.remove()
    for handle in target_handles:
        margins.pop(handle, None)

    by_name = {
        sensor.nameString(): sensor
        for sensor in model.getEnergyManagementSystemSensors()
    }
    remaining = [
        by_name[_dewpoint_sensor_name(sensor_prefix, handle)]
        for handle in sorted(margins)
        if _dewpoint_sensor_name(sensor_prefix, handle) in by_name
    ]
    actuator = next(
        (item for item in model.getEnergyManagementSystemActuators()
         if item.nameString() == f'{prefix}_Setpoint'),
        None)
    program = next(
        (item for item in model.getEnergyManagementSystemPrograms()
         if item.nameString() == f'{prefix}_Program'),
        None)
    manager = next(
        (item for item in model.getEnergyManagementSystemProgramCallingManagers()
         if item.nameString() == f'{prefix}_Manager'),
        None)
    pressure_sensor = next(
        (item for item in model.getEnergyManagementSystemSensors()
         if item.nameString() == f'{prefix}_Pressure'),
        None)

    if (remaining and pressure_sensor is not None
            and actuator is not None and program is not None):
        profile = temperature_profile(loop)
        effective_margin = _stamp_dewpoint_margins(loop, margins)
        _set_dewpoint_program_lines(
            program, remaining, pressure_sensor, actuator, prefix,
            effective_margin,
            profile['setpoint_temperature'])
        return

    if pressure_sensor is not None:
        pressure_sensor.remove()
    if manager is not None:
        manager.remove()
    if program is not None:
        program.remove()
    if actuator is not None:
        actuator.remove()
    properties = loop.additionalProperties()
    properties.resetFeature(DEWPOINT_MARGIN_FEATURE)
    properties.resetFeature(DEWPOINT_ZONE_MARGINS_FEATURE)


def boiler_part_load_class(loop):
    """The part-load class the loop's boilers carry, or None when unstamped."""
    for comp in loop.supplyComponents(openstudio.model.BoilerHotWater.iddObjectType()):
        boiler = comp.to_BoilerHotWater().get()
        feature = boiler.additionalProperties().getFeatureAsString(
            BOILER_PART_LOAD_CLASS_FEATURE)
        if feature.is_initialized() and feature.get():
            return feature.get()
    return None


def boiler_fuels(loop):
    """The boiler fuels on a loop's supply side, in supply order.

    Part of a hot-water loop's REUSE IDENTITY. Without it, two reference
    assignments that differ only in `config` — Systems 2 and 5 use one
    catalogue name for their gas and electric variants — both adopted whichever
    plant was built first, so the second assignment's fuel never reached plant
    construction. Renaming only the PROPOSED air loops, which `characterize()`
    sorts, then flipped the whole reference plant between NaturalGas and
    Electricity (Sol, `151`).
    """
    return [component.to_BoilerHotWater().get().fuelType()
            for component in loop.supplyComponents(
                openstudio.model.BoilerHotWater.iddObjectType())]


def _boiler_role(boiler):
    """``'primary'``, ``'secondary'`` or None, by D-90's three sources.

    The same contract `btap.codes.necb.hvac.efficiency._plant_role` applies on
    the codes side — the builder's own feature, then the conventional name,
    then a two-boiler plant's supply order. It is reimplemented here rather
    than imported because `btap.modeling` may not depend on `btap.codes`
    (the D-77 direction), and the FEATURE itself is modeling-owned.
    """
    stored = boiler.additionalProperties().getFeatureAsString(
        BOILER_PLANT_ROLE_FEATURE)
    if stored.is_initialized() and stored.get() in ('primary', 'secondary'):
        return stored.get()
    name = boiler.nameString()
    if 'Primary Boiler' in name:
        return 'primary'
    if 'Secondary Boiler' in name:
        return 'secondary'
    return None


def _ordered_boiler_fuels(loop):
    """``(primary_fuel, secondary_fuel)`` for a staged pair, else None.

    None means the ORDER could not be established, and a caller that supplied
    an explicit backup must then NOT reuse the loop: unknown order may not
    silently count as a match (Sol, `153`).

    Order IS established for two WHOLLY UNMARKED boilers, by the loop's own
    supply order — D-90's third source, which is what lets an imported pair
    match at all. What returns None is a plant that is not a two-boiler pair,
    a HALF-marked pair (one boiler claiming a role, one not), or a pair whose
    marks do not form one primary and one secondary.
    """
    boilers = [component.to_BoilerHotWater().get()
               for component in loop.supplyComponents(
                   openstudio.model.BoilerHotWater.iddObjectType())]
    if len(boilers) != 2:
        return None
    roles = [_boiler_role(boiler) for boiler in boilers]
    if set(roles) == {'primary', 'secondary'}:
        by_role = dict(zip(roles, boilers))
        return (by_role['primary'].fuelType(),
                by_role['secondary'].fuelType())
    if any(role is not None for role in roles):
        # Half-marked: one boiler claims a role and the other does not. The
        # order is not established, so refuse rather than guess.
        return None
    # D-90's last resort: exactly two unmarked boilers on one loop ARE the
    # pair, ordered by the loop's own supply order so the choice is
    # deterministic.
    return (boilers[0].fuelType(), boilers[1].fuelType())


def _fuels_compatible(loop, fuel, backup_fuel):
    """Whether `loop` can serve a caller asking for this boiler realization.

    TWO DIFFERENT REQUESTS, because `backup_fuel` carries meaning (Sol, `153`):

    * **backup omitted** — the caller is attaching demand to whatever plant
      already realises its fuel and is NOT electing the other role. It needs
      its fuel PRESENT, nothing more. This is the sample 11/12 shape: a mixed
      gas-lead/electric-backup plant is built, then `Baseboard gas boiler`
      asks for NaturalGas and must join it.
    * **backup supplied** — this is an ordered primary/secondary plant
      realization, and reuse must match BOTH roles IN ORDER. A reversed pair
      is a different plant: the roles are durable runtime facts that D-90's
      staging pass consumes, so adopting the reversal changes which fuel
      occupies which role before that pass runs, and 8.4.x.9.(5)(b) makes
      cross-energy operating priority substantive. An explicit gas/gas request
      is likewise not satisfied by one gas and one electric boiler.

    A set subset satisfied all three of those wrongly — it loses order AND
    multiplicity. Plain equality fails the omitted-backup case instead, which
    the frozen corpus caught by way of sample 11 losing AHJ-1/AHJ-3.

    A loop with no boilers is provisionally fuel-compatible with anything.
    ``hot_water`` separately requires a source-less shell, then completes it
    with the requested boiler realization before returning it.
    """
    existing = boiler_fuels(loop)
    if not existing:
        return True
    if backup_fuel is None:
        return fuel in existing
    ordered = _ordered_boiler_fuels(loop)
    if ordered is None:
        return False
    return ordered == (fuel, backup_fuel)


_HOT_WATER_LOOP_NAME = re.compile(r'^Hot Water Loop( \d+)?$')


def _named_hot_water_loop(loop):
    """A loop this builder made: 'Hot Water Loop', or the SDK's uniqueness
    suffix 'Hot Water Loop 1' once a second one exists."""
    return bool(_HOT_WATER_LOOP_NAME.match(loop.nameString()))


def find_hot_water(model, part_load_curve_class=None, exclude=(), fuel=None,
                   backup_fuel=None, temperature_profile=None):
    """Find an existing hot-water loop (one with a boiler on the supply side), or None.

    :param model: openstudio.model.Model
    :param exclude: handles (as strings) of loops that must NOT be adopted,
        however well they otherwise match. The NECB reference path uses it for
        any PROPOSED plant that survived teardown — because a `copy_proposed`
        block, process or service water, or another non-zone demand still
        draws on it: a reference system being built must connect to a planned
        reference plant, not to proposed equipment kept alive for something
        else (D-101; Sol, `143`/`149`).
    :return: openstudio.model.PlantLoop or None
    """
    # Source matching is EXCLUSIVE: a hybrid loop (boilers AND a district
    # object on the supply side) is neither a boiler loop nor a district loop
    # for reuse, so the two callers can never be handed the same object.
    blocked = {str(handle) for handle in exclude}
    return next(
        (pl for pl in model.getPlantLoops()
         if str(pl.handle()) not in blocked
         and _boiler_heated(pl) and not _district_heated(pl)
         and not _heat_pump_heated(pl)
         and boiler_part_load_class(pl) == part_load_curve_class
         and _temperature_profile_matches(
             pl, temperature_profile, 'hot_water')
         and (fuel is None or _fuels_compatible(pl, fuel, backup_fuel))),
        None)


#: Every IDD type that is PURCHASED heating, whatever the medium: the deprecated
#: pre-3.7 DistrictHeating, and the water and steam objects that replaced it.
#: Shared with classify, so reuse and purchased-energy detection agree.
DISTRICT_HEATING_TYPES = frozenset({
    'OS_DistrictHeating', 'OS_DistrictHeating_Water', 'OS_DistrictHeating_Steam'})


def _district_heated(loop):
    """Is this loop heated by PURCHASED energy rather than a boiler?

    Both SDK spellings: DistrictHeating was deprecated for DistrictHeatingWater
    at 3.7.0 and older models still carry the former.
    """
    # By IDD type, not by the typed casts: to_DistrictHeating() is the
    # deprecated class and the SDK logs a deprecation line to stdout on every
    # call, which leaked into audit.txt once reuse checked every loop.
    for c in loop.supplyComponents():
        if c.iddObjectType().valueName() in DISTRICT_HEATING_TYPES:
            return True
    return False


def _boiler_heated(loop):
    return len(loop.supplyComponents(openstudio.model.BoilerHotWater.iddObjectType())) > 0


def _heat_pump_heated(loop):
    """A heating heat pump on the supply side — a heat-pump plant, whose
    boiler is a backup and which an ordinary boiler caller must never adopt."""
    return len(loop.supplyComponents(
        openstudio.model.HeatPumpPlantLoopEIRHeating.iddObjectType())) > 0


def _source_less_hot_water_shell(loop):
    """Whether a named loop has distribution topology but no heating source."""
    if _boiler_heated(loop) or _district_heated(loop):
        return False
    components = loop.supplyComponents()
    if not all(
        component.iddObjectType().valueName() in _HOT_WATER_SHELL_COMPONENT_TYPES
        for component in components
    ):
        return False
    pipes = loop.supplyComponents(openstudio.model.PipeAdiabatic.iddObjectType())
    pumps = loop.supplyComponents(
        openstudio.model.PumpVariableSpeed.iddObjectType())
    return len(pipes) in (0, 2) and len(pumps) <= 1


def _feature(obj, key):
    value = obj.additionalProperties().getFeatureAsString(key)
    return value.get() if value.is_initialized() else None


def heat_pump_controls(supply, controls=None):
    """Resolve and validate a heat-pump plant's ``hw_controls`` for ``supply``.

    Returns a dict with every key of HEAT_PUMP_CONTROL_KEYS, the pairs as
    tuples of floats. Raises ValueError, before any model is touched, on an
    unknown key, a non-numeric value, or settings that contradict ``supply``.
    """
    import math

    if supply not in HOT_WATER_SUPPLY_MODES:
        raise ValueError(f"hw_supply must be one of {list(HOT_WATER_SUPPLY_MODES)!r}")
    controls = {} if controls is None else controls
    if not isinstance(controls, dict):
        raise ValueError('hw_controls must be a mapping')
    unknown = sorted(set(map(str, controls)) - HEAT_PUMP_CONTROL_KEYS)
    if unknown:
        raise ValueError(f'hw_controls does not take {unknown}; '
                         f'it takes {sorted(HEAT_PUMP_CONTROL_KEYS)}')

    def number(key, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f'hw_controls {key} must be a finite number')
        try:
            value = float(value)
        except OverflowError:
            raise ValueError(f'hw_controls {key} must be a finite number') from None
        if not math.isfinite(value):
            raise ValueError(f'hw_controls {key} must be a finite number')
        return value + 0.0          # -0.0 -> 0.0, so equal controls share a plant

    def pair(key, value):
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError(f'hw_controls {key} must be a pair [cold, mild]')
        return (number(key, value[0]), number(key, value[1]))

    resolved = {**HEAT_PUMP_CONTROL_DEFAULTS,
                'loop_reset_c': HEAT_PUMP_LOOP_RESET_DEFAULTS[supply]}
    for key, value in controls.items():
        key = str(key)
        resolved[key] = pair(key, value) if key.endswith('_reset_c') else number(key, value)

    outdoor_cold, outdoor_mild = resolved['outdoor_reset_c']
    loop_cold, loop_mild = resolved['loop_reset_c']
    top = resolved['heat_pump_max_c']
    if not outdoor_cold < outdoor_mild:
        raise ValueError('hw_controls outdoor_reset_c must be [colder, milder]')
    if not loop_cold >= loop_mild:
        raise ValueError('hw_controls loop_reset_c must not be hotter at the mild end')
    if not (30.0 <= loop_mild and loop_cold <= 100.0):
        raise ValueError('hw_controls loop_reset_c must lie between 30 and 100 C')
    # The loop sizes on a fixed design temperature difference (11 K low
    # temperature, 16 K boiler lift); its design return must still be warm
    # enough to heat a room (Fable, review of #250: [22, 20] was accepted).
    design_return = loop_cold - HEAT_PUMP_LOOP_DELTA_T[supply]
    if design_return < 25.0:
        raise ValueError(
            f'hw_controls loop_reset_c cold end {loop_cold:g} C leaves a design return of '
            f'{design_return:g} C at the {HEAT_PUMP_LOOP_DELTA_T[supply]:g} K design '
            'temperature difference; it must be at least 25 C')
    if not 30.0 <= top <= 90.0:
        raise ValueError('hw_controls heat_pump_max_c must lie between 30 and 90 C')
    if not 0.0 <= resolved['backup_deadband_k'] <= 5.0:
        raise ValueError('hw_controls backup_deadband_k must lie between 0 and 5 K')
    if supply == 'low_temperature' and loop_cold > top:
        raise ValueError(
            f'a low_temperature loop at {loop_cold:g} C is hotter than the heat pump '
            f'makes ({top:g} C); that is hw_supply boiler_lift')
    if supply == 'boiler_lift' and loop_cold <= top:
        raise ValueError(
            f'a boiler_lift loop at {loop_cold:g} C is within the heat pump\'s reach '
            f'({top:g} C), so the boiler lifts nothing; that is hw_supply low_temperature')
    # The boiler-lift heat pump runs at a CONSTANT setpoint, so a loop reset
    # that falls below it leaves the heat pump overshooting the loop through
    # the mild end (Fable, review of #250).
    if supply == 'boiler_lift' and loop_mild < top:
        raise ValueError(
            f'a boiler_lift loop resets down to {loop_mild:g} C, below the heat pump\'s '
            f'constant {top:g} C; lower heat_pump_max_c to the mild end or raise the reset')
    # Where the heat pump never reaches the loop, the boiler holds the loop
    # setpoint everywhere and a deadband does nothing: refused rather than
    # silently ignored (Fable, review of #250).
    if (supply == 'boiler_lift' and loop_mild > top
            and 'backup_deadband_k' in map(str, controls)):
        raise ValueError(
            f'a boiler_lift loop that never falls to the heat pump\'s {top:g} C has no '
            'hours where the heat pump alone meets it, so backup_deadband_k has no effect')
    return resolved


def _effective_controls(supply, resolved):
    """The resolved controls that change what is built — the reuse key's
    content. An unused key must not split two identical plants (Fable,
    review of #250): ``heat_pump_max_c`` builds nothing on a low-temperature
    loop, and the deadband nothing on a boiler-lift loop the heat pump never
    reaches."""
    effective = dict(resolved)
    if supply == 'low_temperature':
        effective.pop('heat_pump_max_c')
    elif resolved['loop_reset_c'][1] > resolved['heat_pump_max_c']:
        effective.pop('backup_deadband_k')
    return effective


def _controls_signature(resolved):
    """The plant-reuse key for resolved controls: a canonical string."""
    import json
    return json.dumps({k: resolved[k] for k in sorted(resolved)}, sort_keys=True)


def _node_after(optional_object, what):
    """The Node a just-connected component's outlet lands on, through `opt`:
    an empty crash-family optional SEGFAULTS on a bare `.get()` (D-79)."""
    from btap._compat import opt
    obj = opt(optional_object)
    node = opt(obj.to_Node()) if obj is not None else None
    if node is None:
        raise RuntimeError(f"the {what} is not connected to a node")
    return node


def _air_to_water_heat_pump_hot_water(model, backup_fuel, supply, reuse, exclude,
                                      minimum_part_load_ratio, controls=None):
    """A hot-water loop led by an air-to-water heat pump, with ONE backup
    boiler in series downstream of it (the hp_plant_fancoils arrangement,
    generalised to every hydronic system).

    The heat pump runs on its outlet setpoint and the boiler tops up to the
    loop's. In ``low_temperature`` both setpoints follow the same outdoor
    reset (60 C at -16 C down to 45 C at 0 C), so the boiler fires only when
    the heat pump falls short — at capacity or below its -15 C cutoff. In
    ``boiler_lift`` the heat pump is held at its 60 C limit and the loop keeps
    the conventional 82 C-at--16 C reset, so the boiler lifts whatever the
    heat pump cannot reach. Both setpoint schedules are authored defaults,
    not code values, and ``controls`` (``hw_controls``) overrides them; see
    HEAT_PUMP_CONTROL_DEFAULTS.
    """
    from btap.modeling.hvac.components import curves as curves_mod

    if supply not in HOT_WATER_SUPPLY_MODES:
        raise ValueError(f"hw_supply must be one of {list(HOT_WATER_SUPPLY_MODES)!r}")
    if backup_fuel not in HEAT_PUMP_BACKUP_FUELS:
        raise ValueError(
            f"a heat-pump plant's backup fuel must be one of {list(HEAT_PUMP_BACKUP_FUELS)!r}")
    resolved = heat_pump_controls(supply, controls)
    signature = _controls_signature(_effective_controls(supply, resolved))
    default_signature = _controls_signature(
        _effective_controls(supply, heat_pump_controls(supply)))
    if reuse:
        blocked = {str(handle) for handle in exclude}
        for pl in model.getPlantLoops():
            if (str(pl.handle()) not in blocked and _heat_pump_heated(pl)
                    and _feature(pl, HOT_WATER_SOURCE_FEATURE) == 'awhp'
                    and _feature(pl, HOT_WATER_SUPPLY_FEATURE) == supply
                    and boiler_fuels(pl) == [backup_fuel]
                    # A loop built before hw_controls existed carries no
                    # signature and has the default controls.
                    and (_feature(pl, HEAT_PUMP_CONTROLS_FEATURE)
                         or default_signature) == signature):
                return pl

    low = supply == 'low_temperature'
    outdoor_cold, outdoor_mild = resolved['outdoor_reset_c']
    loop_cold, loop_mild = resolved['loop_reset_c']
    top, deadband = resolved['heat_pump_max_c'], resolved['backup_deadband_k']
    loop = openstudio.model.PlantLoop(model)
    loop.setName(_HEAT_PUMP_LOOP_NAME)
    sizing = loop.sizingPlant()
    sizing.setLoopType('Heating')
    sizing.setDesignLoopExitTemperature(loop_cold)
    sizing.setLoopDesignTemperatureDifference(HEAT_PUMP_LOOP_DELTA_T[supply])
    loop.setLoadDistributionScheme('SequentialLoad')
    loop.additionalProperties().setFeature(HOT_WATER_SOURCE_FEATURE, 'awhp')
    loop.additionalProperties().setFeature(HOT_WATER_SUPPLY_FEATURE, supply)
    if signature != default_signature:
        loop.additionalProperties().setFeature(HEAT_PUMP_CONTROLS_FEATURE, signature)
    openstudio.model.PumpVariableSpeed(model).addToNode(loop.supplyInletNode())

    # Heat-pump settings: the hp_plant_fancoils / ECM hs15 CAWHP equipment
    # (COP 3, -15 C low-ambient cutoff, the CAWHP-HS15 curves), except that a
    # heating-only plant has no companion cooling heat pump to size from.
    hp = openstudio.model.HeatPumpPlantLoopEIRHeating(model)
    hp.setName('Air-to-Water Heat Pump')
    hp.setCondenserType('AirSource')
    hp.setMinimumSourceInletTemperature(-15.0)
    hp.setReferenceCoefficientofPerformance(3.0)
    hp.setHeatPumpSizingMethod('HeatingCapacity')
    hp.setHeatPumpDefrostControl('OnDemand')
    hp.setFlowMode('VariableSpeedPumping')
    hp.setControlType('Setpoint')
    hp.setMinimumPartLoadRatio(minimum_part_load_ratio)
    hp.setCapacityModifierFunctionofTemperatureCurve(
        curves_mod.build(model, 'CAWHP-HS15-HCAPFT'))
    hp.setElectricInputtoOutputRatioModifierFunctionofTemperatureCurve(
        curves_mod.build(model, 'CAWHP-HS15-HEIRFT'))
    loop.addSupplyBranchForComponent(hp)
    loop.addSupplyBranchForComponent(openstudio.model.PipeAdiabatic(model))
    openstudio.model.PipeAdiabatic(model).addToNode(loop.supplyOutletNode())

    hp_outlet = _node_after(hp.supplyOutletModelObject(), 'heat pump supply outlet')
    boiler = openstudio.model.BoilerHotWater(model)
    boiler.setFuelType(backup_fuel)
    boiler.setName('Backup Boiler')
    # SETPOINT-controlled, on its own outlet: in series behind the heat pump
    # a load-dispatched boiler was handed almost nothing, and the loop ran
    # 4-12 K under setpoint whenever the heat pump fell short (measured; the
    # boiler-only control holds setpoint every hour).
    boiler.setBoilerFlowMode('LeavingSetpointModulated')
    boiler.addToNode(hp_outlet)
    boiler_outlet = _node_after(boiler.outletModelObject(), 'backup boiler outlet')

    def reset(node, low_temperature, high_temperature, label):
        spm = openstudio.model.SetpointManagerOutdoorAirReset(model)
        spm.setName(label)
        spm.setControlVariable('Temperature')
        spm.setSetpointatOutdoorLowTemperature(low_temperature)
        spm.setOutdoorLowTemperature(outdoor_cold)
        spm.setSetpointatOutdoorHighTemperature(high_temperature)
        spm.setOutdoorHighTemperature(outdoor_mild)
        spm.addToNode(node)

    # A 1 K DEADBAND below the heat pump: with identical setpoints the boiler
    # chased the 0.1-0.5 K the heat pump runs short while defrosting (active
    # below 10 C) and fired in nearly every heating hour (Fable, PR #243:
    # 67% of annual boiler heat came while the heat pump had capacity).
    #
    # The boiler holds `deadband` below the loop wherever the heat pump alone
    # can meet the loop setpoint, and AT the loop setpoint wherever it cannot.
    #
    # Low temperature: the heat pump follows the loop reset, so the boiler is
    # the same line `deadband` lower.
    #
    # Boiler lift: the heat pump holds `top` and the loop resets down to it
    # at the mild end. Moving only the boiler's mild endpoint down by
    # `deadband` put it BELOW the loop everywhere between the endpoints, where
    # neither machine then met the loop (Fable, review of #250: 0.96 K at the
    # default, 4 K at a 5 K deadband). Instead the boiler follows the loop's
    # own ramp and carries on past the mild end until it is `deadband` below
    # the heat pump, so it equals the loop wherever the loop is above `top`.
    # Where the loop never falls to `top`, the boiler is the loop's reset.
    if low:
        reset(hp_outlet, loop_cold, loop_mild, 'Heat Pump Outlet Reset')
        reset(boiler_outlet, loop_cold - deadband, loop_mild - deadband,
              'Backup Boiler Outlet Reset')
    else:
        schedule = openstudio.model.ScheduleConstant(model)
        schedule.setName(f'Heat Pump Outlet {top:g}C')
        schedule.setValue(top)
        spm = openstudio.model.SetpointManagerScheduled(model, schedule)
        spm.setName('Heat Pump Outlet Setpoint')
        spm.addToNode(hp_outlet)
        boiler_reset = openstudio.model.SetpointManagerOutdoorAirReset(model)
        boiler_reset.setName('Backup Boiler Outlet Reset')
        boiler_reset.setControlVariable('Temperature')
        boiler_reset.setSetpointatOutdoorLowTemperature(loop_cold)
        boiler_reset.setOutdoorLowTemperature(outdoor_cold)
        if loop_mild > top or deadband == 0.0:
            boiler_reset.setSetpointatOutdoorHighTemperature(loop_mild)
            boiler_reset.setOutdoorHighTemperature(outdoor_mild)
        else:
            slope = (loop_cold - loop_mild) / (outdoor_mild - outdoor_cold)   # K per K outdoor
            boiler_reset.setSetpointatOutdoorHighTemperature(top - deadband)
            boiler_reset.setOutdoorHighTemperature(
                outdoor_cold + (loop_cold - top + deadband) / slope)
        boiler_reset.addToNode(boiler_outlet)
    reset(loop.supplyOutletNode(), loop_cold, loop_mild, 'Hot Water Loop Reset')
    return loop


def hot_water(model, fuel='NaturalGas', backup_fuel=None, reuse=True, source='boiler',
              part_load_curve_class=None, exclude=(), profile=None,
              supply='low_temperature', minimum_part_load_ratio=None, controls=None):
    """Build a hot-water loop: primary + secondary boiler, variable-speed pump,
    82C design exit / 16K dT, OA-reset 82C@-16C down to 60C@0C.

    :param model: openstudio.model.Model
    :param fuel: primary boiler fuel (OpenStudio Boiler fuel type keyword)
    :param backup_fuel: secondary boiler fuel. IT ALSO SELECTS THE REUSE RULE,
        because supplying it states an ordered two-role realization while
        omitting it does not:

        * omitted — REUSE returns any compatible plant that CONTAINS ``fuel``,
          whatever its other role carries, because the caller is attaching
          demand rather than electing a pair; NEW CONSTRUCTION defaults the
          secondary to ``fuel``. So a caller asking for NaturalGas may be
          handed an existing Electricity-primary/NaturalGas-secondary plant,
          and that plant's roles are NOT re-defaulted.
        * supplied — REUSE requires the loop's primary and secondary to match
          ``(fuel, backup_fuel)`` IN THAT ORDER; NEW CONSTRUCTION uses the
          supplied value as the secondary fuel.

        The omitted-backup reuse branch is what samples 11 and 12 depend on
        (Sol, `153`).
    :param reuse: return a complete compatible loop, or complete a compatible
        named loop that has no heating source yet (default True)
    :param source: 'boiler' (default) or 'district' (DistrictHeating object
        instead of boilers — the CBECS 'district hot water' pattern)
    :param part_load_curve_class: the part-load curve class the caller's
        selection elected for these boilers (D-89; None = unstamped). Reuse
        is class-aware: a loop whose boilers carry a different class (or none)
        is not adopted, so a purchased-heating group never lands on an
        ordinary group's boilers and vice versa.
    :param supply: for ``source='awhp'`` only — ``'low_temperature'`` or
        ``'boiler_lift'`` (see HOT_WATER_SUPPLY_MODES); ``fuel`` is then the
        BACKUP boiler's fuel
    :param controls: for ``source='awhp'`` only — the ``hw_controls``
        overrides of HEAT_PUMP_CONTROL_DEFAULTS
    :return: openstudio.model.PlantLoop
    """
    if source not in HOT_WATER_SOURCES:
        raise ValueError(
            f"hot-water source must be one of {sorted(HOT_WATER_SOURCES)!r}")
    if source == 'awhp':
        if profile is not None:
            raise ValueError("a heat-pump plant sets its own temperatures; pass hw_supply, "
                             "not a hot_water_profile")
        if minimum_part_load_ratio is None:
            from btap.modeling.hvac import performance
            minimum_part_load_ratio = performance.resolve()[
                'plant_heating_heat_pump_minimum_part_load_ratio']
        return _air_to_water_heat_pump_hot_water(
            model, fuel, supply, reuse, exclude, minimum_part_load_ratio, controls)
    if controls is not None:
        raise ValueError("hw_controls applies only to hw_source 'awhp'")
    profile = _normalize_temperature_profile(profile, 'hot_water')
    hw_loop = None
    if reuse:
        # Source first: a caller asking for DISTRICT heat must never adopt a
        # boiler loop (and a boiler caller never a district loop), whatever
        # order the two were built in; then class-aware within boiler loops.
        if source == 'district':
            # Name-guarded: a ground-loop condenser loop is modelled with a
            # DistrictHeating object too (hp_plant_fancoils), and must never
            # serve as the hot-water loop (independent review, 2026-09-13).
            blocked = {str(handle) for handle in exclude}
            existing = next((pl for pl in model.getPlantLoops()
                             if str(pl.handle()) not in blocked
                             and _named_hot_water_loop(pl)
                             and _district_heated(pl) and not _boiler_heated(pl)
                             and _temperature_profile_matches(
                                 pl, profile, 'hot_water')), None)
        else:
            existing = find_hot_water(model, part_load_curve_class,
                                      exclude=exclude, fuel=fuel,
                                      backup_fuel=backup_fuel,
                                      temperature_profile=profile)
        # The name fallback catches a loop that has no boiler YET. It must not
        # adopt a loop heated by a DIFFERENT SOURCE than the one asked for:
        # every loop this builder makes is named 'Hot Water Loop', district
        # ones included, so a bare name match happily hands a district loop to
        # a caller that asked for boilers.
        #
        # That is how 8.4.4.6.(1)(a) ended up half-applied before D-101 phased
        # teardown ahead of construction. The old reference builder rebuilt
        # one group at a time, so a district loop still serving later groups
        # survived and was re-adopted here by name. Refusing that cross-source
        # adoption let the loop drain and be removed by teardown's fixpoint.
        #
        # The fallback honours `exclude` too. It did not, and an excluded loop
        # came straight back through it by NAME: `find_hot_water` returned None
        # and this matched `Hot Water Loop` anyway, so reserving a retained
        # proposed plant had no effect at all (measured while fixing Sol's
        # `143` blocker 3).
        if existing is None:
            blocked_by_name = {str(handle) for handle in exclude}
            existing = next(
                (pl for pl in model.getPlantLoops()
                 if str(pl.handle()) not in blocked_by_name
                 and _named_hot_water_loop(pl)
                 and _district_heated(pl) == (source == 'district')
                 and not (source == 'district' and _boiler_heated(pl))
                 and boiler_part_load_class(pl) == part_load_curve_class
                 and _temperature_profile_matches(
                     pl, profile, 'hot_water')
                 and (_boiler_heated(pl) or source == 'district'
                      or _source_less_hot_water_shell(pl))
                 # FUEL-AWARE here too. The typed lookup above and this
                 # fallback are two paths to the same adoption, and fixing one
                 # of a pair has already been the shape of two defects in this
                 # function.
                 and _fuels_compatible(pl, fuel, backup_fuel)),
                None)
        if existing is not None:
            if _boiler_heated(existing) or _district_heated(existing):
                return existing
            hw_loop = existing

    if backup_fuel is None:
        backup_fuel = fuel
    if hw_loop is None:
        hw_loop = openstudio.model.PlantLoop(model)
        hw_loop.setName('Hot Water Loop')
    sizing_plant = hw_loop.sizingPlant()
    sizing_plant.setLoopType('Heating')
    sizing_plant.setDesignLoopExitTemperature(
        profile['design_exit_temperature'] if profile else 82.0)
    sizing_plant.setLoopDesignTemperatureDifference(
        profile['design_temperature_difference'] if profile else 16.0)
    _stamp_temperature_profile(hw_loop, profile, 'hot_water')

    # Variable speed (legacy note: constant-speed showed run-away plant temperatures)
    if not hw_loop.supplyComponents(
            openstudio.model.PumpVariableSpeed.iddObjectType()):
        pump = openstudio.model.PumpVariableSpeed(model)
        pump.addToNode(hw_loop.supplyInletNode())

    if source == 'district':
        if model.version() < openstudio.VersionString('3.7.0'):
            district = openstudio.model.DistrictHeating(model)
        else:
            district = openstudio.model.DistrictHeatingWater(model)
        district.setName('District Hot Water')
        hw_loop.addSupplyBranchForComponent(district)
    else:
        boiler1 = openstudio.model.BoilerHotWater(model)
        boiler2 = openstudio.model.BoilerHotWater(model)
        boiler1.setFuelType(fuel)
        boiler2.setFuelType(backup_fuel)
        # The NAME is a display label; the ROLE is the durable fact. DF-13: the
        # efficiency pass used to identify the staged pair by matching these
        # strings, so a plant that merely happened to be named this way was
        # staged and re-controlled, while a genuine two-boiler plant named
        # anything else was never staged at all. The feature says which boiler
        # this is regardless of what the name later becomes.
        boiler1.setName('Primary Boiler')
        boiler2.setName('Secondary Boiler')
        boiler1.additionalProperties().setFeature(BOILER_PLANT_ROLE_FEATURE, 'primary')
        boiler2.additionalProperties().setFeature(BOILER_PLANT_ROLE_FEATURE, 'secondary')
        if part_load_curve_class:
            for boiler in (boiler1, boiler2):
                boiler.additionalProperties().setFeature(
                    BOILER_PART_LOAD_CLASS_FEATURE, part_load_curve_class)
        hw_loop.addSupplyBranchForComponent(boiler1)
        hw_loop.addSupplyBranchForComponent(boiler2)

    pipe_count = len(hw_loop.supplyComponents(
        openstudio.model.PipeAdiabatic.iddObjectType()))
    if pipe_count == 0:
        hw_loop.addSupplyBranchForComponent(openstudio.model.PipeAdiabatic(model))
    if pipe_count < 2:
        openstudio.model.PipeAdiabatic(model).addToNode(hw_loop.supplyOutletNode())

    if not hw_loop.supplyOutletNode().setpointManagers():
        if profile:
            _scheduled_plant_setpoint(
                model, hw_loop, profile['setpoint_temperature'], 'Hot Water')
        else:
            stpt = openstudio.model.SetpointManagerOutdoorAirReset(model)
            stpt.setControlVariable('Temperature')
            stpt.setSetpointatOutdoorLowTemperature(82.0)
            stpt.setOutdoorLowTemperature(-16.0)
            stpt.setSetpointatOutdoorHighTemperature(60.0)
            stpt.setOutdoorHighTemperature(0.0)
            stpt.addToNode(hw_loop.supplyOutletNode())

    return hw_loop


def _chillers(loop):
    return loop.supplyComponents(
        openstudio.model.ChillerElectricEIR.iddObjectType())


def _district_cooled(loop):
    return len(loop.supplyComponents(
        openstudio.model.DistrictCooling.iddObjectType())) > 0


def _cooling_source(loop):
    """'district', 'air_cooled', 'water_cooled', or None for neither."""
    if _district_cooled(loop):
        return 'district'
    condensers = set()
    for component in _chillers(loop):
        chiller = component.to_ChillerElectricEIR()
        if chiller.is_initialized():
            condensers.add(chiller.get().condenserType())
    if not condensers:
        return None
    return 'air_cooled' if condensers == {'AirCooled'} else 'water_cooled'


def plant_is_hvac_candidate(loop):
    """Whether a reference HVAC build could ever ADOPT this loop.

    The NECB reference path reserves every plant surviving its teardown pass,
    which is right — the exclusion costs nothing and a loop misjudged here
    would otherwise be adoptable. But the AUDIT of that reservation should name
    only the loops a build could have taken: every corpus model carries a
    `Main Service Water Loop` that teardown skips by design, so an
    unclassified record fired on all 35 corpus scenarios and made the one run
    where a reservation MATTERS indistinguishable from the rest
    (Fable, `158` F2).

    The classification MIRRORS the lookups rather than approximating them,
    which the first version did not: it counted `_district_heated` alone as
    enough, while district hot-water reuse is NAME-guarded and boiler reuse
    explicitly EXCLUDES a district-heated loop. A district-heated
    `DISTRICT PROCESS LOOP` was therefore audited as an adoptable survivor
    though neither source-specific lookup can return it and the reference
    builds its own plant — the same false reservation signal this filter
    exists to remove, on a less common source boundary (Sol, `160`).

    Mirroring the four reuse paths exactly:

    * boiler hot water — boiler-heated and NOT district-heated, which also
      rejects a boiler/district HYBRID, as `find_hot_water` does;
    * district hot water — district-heated, NOT boiler-heated, AND carrying
      the builder's own hot-water name;
    * the hot-water name fallback — the builder's name, with a source that
      matches or a distribution-only shell with no heating source yet;
    * chilled water — chillers or district cooling, which `chilled_water`
      reaches by source;
    * the CHILLED-WATER name fallback — an exact `Chilled Water Loop` with no
      cooling source yet, which `chilled_water` returns for ANY requested
      source. Omitting it hid a real survivor: a source-less
      `Chilled Water Loop` retained by process demand classified False while
      the builder would have adopted it without the broad exclusion — the
      false-NEGATIVE counterpart of the service-water noise this filter
      removed (Sol, `162`). Its name test is EXACT, unlike the hot-water
      suffix regex, so it is not broadened beyond what `chilled_water` can
      return.

    A service-water loop satisfies none of them.
    """
    boiler_hw = _boiler_heated(loop) and not _district_heated(loop)
    district_hw = (_district_heated(loop) and not _boiler_heated(loop)
                   and _named_hot_water_loop(loop))
    hw_name_fallback = (
        _named_hot_water_loop(loop) and _source_less_hot_water_shell(loop))
    cooling = bool(_chillers(loop) or _district_cooled(loop))
    chw_name_fallback = (loop.nameString() == 'Chilled Water Loop'
                         and _cooling_source(loop) is None)
    return bool(boiler_hw or district_hw or hw_name_fallback or cooling
                or chw_name_fallback)


def find_chilled_water(model, exclude=(), source=None,
                       temperature_profile=None):
    """Find an existing chilled-water loop (one with a chiller on the supply side),
    or None.

    :param exclude: handles (as strings) of loops that must NOT be adopted. The
        NECB reference path uses it for any PROPOSED plant kept alive by
        something the teardown does not remove — a `copy_proposed` block,
        process or service water, or another non-zone demand
        (D-101; Sol, `145`/`149`).
    :param source: when given, only a loop of that cooling source matches —
        'water_cooled', 'air_cooled' or 'district'. A caller asking for
        district cooling must never be handed a chiller loop, and vice versa,
        which is the cooling analogue of the hot-water source guard.
    """
    blocked = {str(handle) for handle in exclude}
    for loop in model.getPlantLoops():
        if str(loop.handle()) in blocked:
            continue
        if source is None:
            if (len(_chillers(loop)) > 0
                    and _temperature_profile_matches(
                        loop, temperature_profile, 'chilled_water')):
                return loop
            continue
        if (_cooling_source(loop) == source
                and _temperature_profile_matches(
                    loop, temperature_profile, 'chilled_water')):
            return loop
    return None


def chilled_water(model, chiller_type='Scroll', reuse=True, source='water_cooled',
                  exclude=(), profile=None):
    """Build a chilled-water loop (7C exit / 6K dT, variable-speed pump, primary +
    secondary water-cooled chillers, constant 7C setpoint) AND its condenser-water
    loop (29C / 6K, single-speed cooling tower 24/35/5/6 design temps, constant 29C
    setpoint), ported from NECB setup_chw_loop_with_components /
    setup_cw_loop_with_components.

    :param model: openstudio.model.Model
    :param chiller_type: 'Scroll', 'Centrifugal', 'Rotary Screw', 'Reciprocating'
        (embedded in the chiller names, which host efficiency rules key on)
    :param reuse: return an existing chiller loop when present (default True)
    :param source: 'water_cooled' (default: dual chillers + condenser loop + tower),
        'air_cooled' (single air-cooled chiller, no condenser loop), or
        'district' (DistrictCooling object — the CBECS 'district chilled water' pattern)
    :return: openstudio.model.PlantLoop (the chilled-water loop)
    """
    if source not in CHILLED_WATER_SOURCES:
        raise ValueError(
            'chilled-water source must be one of '
            f'{sorted(CHILLED_WATER_SOURCES)!r}')
    profile = _normalize_temperature_profile(profile, 'chilled_water')
    if reuse:
        # SOURCE-MATCHED and EXCLUSION-AWARE, for the same two reasons the
        # hot-water side already is. A district-cooling caller must not be
        # handed a chiller loop, and a loop reserved to whatever retained it
        # must not be adopted by a block the reference REPLACES — the exclusion
        # reached hot water only, so built System 2 cooling coils joined the
        # copied block's proposed chiller plant (Sol, `145`). The retainer need
        # not be a copied block: process cooling on a `WaterUseConnections`
        # keeps a chilled-water loop alive the same way (`149`).
        blocked = {str(handle) for handle in exclude}
        existing = find_chilled_water(
            model, exclude=exclude, source=source,
            temperature_profile=profile)
        if existing is None:
            # The name fallback catches a loop with no chiller YET. It honours
            # the exclusion too: on the hot-water side this exact fallback
            # silently defeated the first reservation fix.
            existing = next((pl for pl in model.getPlantLoops()
                             if pl.nameString() == 'Chilled Water Loop'
                             and str(pl.handle()) not in blocked
                             and _cooling_source(pl) in (None, source)
                             and _temperature_profile_matches(
                                 pl, profile, 'chilled_water')), None)
        if existing is not None:
            return existing

    # --- chilled water ---
    chw_loop = openstudio.model.PlantLoop(model)
    chw_loop.setName('Chilled Water Loop')
    sizing_plant = chw_loop.sizingPlant()
    sizing_plant.setLoopType('Cooling')
    sizing_plant.setDesignLoopExitTemperature(
        profile['design_exit_temperature'] if profile else 7.0)
    sizing_plant.setLoopDesignTemperatureDifference(
        profile['design_temperature_difference'] if profile else 6.0)
    _stamp_temperature_profile(chw_loop, profile, 'chilled_water')

    chw_pump = openstudio.model.PumpVariableSpeed(model)
    chw_pump.addToNode(chw_loop.supplyInletNode())

    if source == 'district':
        district = openstudio.model.DistrictCooling(model)
        district.setName('District Chilled Water')
        chw_loop.addSupplyBranchForComponent(district)
        chiller1 = chiller2 = None
    elif source == 'air_cooled':
        chiller1 = openstudio.model.ChillerElectricEIR(model)
        chiller1.setCondenserType('AirCooled')
        chiller1.setName(f"Primary Chiller AirCooled {chiller_type}".strip())
        chw_loop.addSupplyBranchForComponent(chiller1)
        chiller2 = None
    else:  # water_cooled
        chiller1 = openstudio.model.ChillerElectricEIR(model)
        chiller2 = openstudio.model.ChillerElectricEIR(model)
        chiller1.setCondenserType('WaterCooled')
        chiller2.setCondenserType('WaterCooled')
        # Names are load-bearing downstream (NECB chiller efficiency rules match on them).
        chiller1.setName(f"Primary Chiller WaterCooled {chiller_type}".strip())
        chiller2.setName(f"Secondary Chiller WaterCooled {chiller_type}".strip())
        chw_loop.addSupplyBranchForComponent(chiller1)
        chw_loop.addSupplyBranchForComponent(chiller2)
    chw_loop.addSupplyBranchForComponent(openstudio.model.PipeAdiabatic(model))
    openstudio.model.PipeAdiabatic(model).addToNode(chw_loop.supplyOutletNode())

    if profile:
        _scheduled_plant_setpoint(
            model, chw_loop, profile['setpoint_temperature'], 'Chilled Water')
    else:
        chw_stpt = openstudio.model.SetpointManagerScheduled(
            model, schedules.constant_ruleset(model, 'CHW Temp', 7.0))
        chw_stpt.addToNode(chw_loop.supplyOutletNode())

    if source != 'water_cooled':
        return chw_loop

    # --- condenser water ---
    cw_loop = openstudio.model.PlantLoop(model)
    cw_loop.setName('Condenser Water Loop')
    cw_sizing = cw_loop.sizingPlant()
    cw_sizing.setLoopType('Condenser')
    cw_sizing.setDesignLoopExitTemperature(29.0)
    cw_sizing.setLoopDesignTemperatureDifference(6.0)

    cw_pump = openstudio.model.PumpVariableSpeed(model)
    clg_tower = openstudio.model.CoolingTowerSingleSpeed(model)
    clg_tower.setDesignInletAirWetBulbTemperature(24.0)
    clg_tower.setDesignInletAirDryBulbTemperature(35.0)
    clg_tower.setDesignApproachTemperature(5.0)
    clg_tower.setDesignRangeTemperature(6.0)

    cw_pump.addToNode(cw_loop.supplyInletNode())
    cw_loop.addSupplyBranchForComponent(clg_tower)
    cw_loop.addSupplyBranchForComponent(openstudio.model.PipeAdiabatic(model))
    openstudio.model.PipeAdiabatic(model).addToNode(cw_loop.supplyOutletNode())
    cw_loop.addDemandBranchForComponent(chiller1)
    cw_loop.addDemandBranchForComponent(chiller2)

    cw_stpt = openstudio.model.SetpointManagerScheduled(
        model, schedules.constant_ruleset(model, 'CW Temp', 29.0))
    cw_stpt.addToNode(cw_loop.supplyOutletNode())

    return chw_loop
