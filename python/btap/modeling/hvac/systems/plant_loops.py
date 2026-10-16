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
HOT_WATER_SOURCES = frozenset({'boiler', 'district'})
CHILLED_WATER_SOURCES = frozenset({
    'water_cooled', 'air_cooled', 'district',
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

    A loop with no boilers is compatible with anything.
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


def hot_water(model, fuel='NaturalGas', backup_fuel=None, reuse=True, source='boiler',
              part_load_curve_class=None, exclude=(), profile=None):
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
    :param reuse: return an existing boiler loop when present (default True)
    :param source: 'boiler' (default) or 'district' (DistrictHeating object
        instead of boilers — the CBECS 'district hot water' pattern)
    :param part_load_curve_class: the part-load curve class the caller's
        selection elected for these boilers (D-89; None = unstamped). Reuse
        is class-aware: a loop whose boilers carry a different class (or none)
        is not adopted, so a purchased-heating group never lands on an
        ordinary group's boilers and vice versa.
    :return: openstudio.model.PlantLoop
    """
    if source not in HOT_WATER_SOURCES:
        raise ValueError(
            f"hot-water source must be one of {sorted(HOT_WATER_SOURCES)!r}")
    profile = _normalize_temperature_profile(profile, 'hot_water')
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
        # That is exactly how 8.4.4.6.(1)(a) ended up half-applied. The
        # reference builder tears down and rebuilds ONE GROUP AT A TIME, and
        # Teardown only drops a plant loop whose demand side is empty — so with
        # several single-zone groups the district loop still carries the other
        # groups' coils, survives, and was then re-adopted here by name. The
        # reference kept purchased heating while its energy type said gas.
        # Refusing the adoption lets the district loop drain group by group and
        # be removed by the teardown's own fixpoint.
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
                 # FUEL-AWARE here too. The typed lookup above and this
                 # fallback are two paths to the same adoption, and fixing one
                 # of a pair has already been the shape of two defects in this
                 # function.
                 and _fuels_compatible(pl, fuel, backup_fuel)),
                None)
        if existing is not None:
            return existing

    if backup_fuel is None:
        backup_fuel = fuel
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

    hw_loop.addSupplyBranchForComponent(openstudio.model.PipeAdiabatic(model))
    openstudio.model.PipeAdiabatic(model).addToNode(hw_loop.supplyOutletNode())

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
      matches or no boilers yet;
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
    hw_name_fallback = _named_hot_water_loop(loop) and not boiler_fuels(loop)
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
