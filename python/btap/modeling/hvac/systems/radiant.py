"""DOAS with hydronic low-temperature radiant floors."""

from __future__ import annotations

import openstudio

from btap.modeling.hvac.systems import plant_loops
from btap.modeling.hvac.systems.base_system import BaseSystem
from btap.modeling.hvac.systems.doas import (
    build_dehumidifying_doas,
    validate_dehumidifying_doas_inputs,
)

ORIGINAL_CONSTRUCTION_FEATURE = 'btap_radiant_original_construction'
ORIGINAL_DEFAULTED_FEATURE = 'btap_radiant_original_defaulted'
OWNED_CONSTRUCTION_FEATURE = 'btap_radiant_owned_construction'
OWNED_OBJECT_FEATURE = 'btap_radiant_floor_owned'


def _numeric(config, key, lower, upper):
    value = config.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{key} must be numeric')
    value = float(value)
    if not lower <= value <= upper:
        raise ValueError(f'{key} must be between {lower} and {upper}')
    return value


def _integer(config, key, lower):
    value = config.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < lower:
        raise ValueError(f'{key} must be an integer greater than or equal to {lower}')
    return value


def _floors(zone):
    return [
        surface
        for space in zone.spaces()
        for surface in space.surfaces()
        if surface.surfaceType() == 'Floor'
    ]


def _object_by_handle(objects, handle):
    return next(
        (obj for obj in objects if str(obj.handle()) == handle),
        None)


def _ordinary_construction(surface, *, allow_owned):
    props = surface.additionalProperties()
    owned = props.getFeatureAsString(OWNED_CONSTRUCTION_FEATURE)
    current = surface.construction()
    if not current.is_initialized():
        return None

    construction = current.get()
    if owned.is_initialized() and str(construction.handle()) == owned.get():
        if not allow_owned:
            raise ValueError(
                f"surface '{surface.nameString()}' already has a BTAP radiant "
                'construction; use remove_existing=True to replace it')
        original = props.getFeatureAsString(ORIGINAL_CONSTRUCTION_FEATURE)
        if not original.is_initialized():
            raise ValueError(
                f"surface '{surface.nameString()}' has incomplete radiant "
                'construction provenance')
        construction = _object_by_handle(
            surface.model().getConstructionBases(), original.get())
        if construction is None:
            raise ValueError(
                f"surface '{surface.nameString()}' original construction no "
                'longer exists')

    ordinary = construction.to_Construction()
    return ordinary.get() if ordinary.is_initialized() else None


def _validated_floor_constructions(zones, *, allow_owned, source_layer,
                                    temperature_layer):
    selected = []
    for zone in zones:
        floors = _floors(zone)
        if not floors:
            raise ValueError(
                f"radiant floor zone '{zone.nameString()}' has no floor surfaces")
        for surface in floors:
            if surface.adjacentSurface().is_initialized():
                raise ValueError(
                    f"radiant floor surface '{surface.nameString()}' is adjacent "
                    'to another space; the floor-only catalog row supports '
                    'non-adjacent slabs only')
            construction = _ordinary_construction(
                surface, allow_owned=allow_owned)
            if construction is None:
                raise ValueError(
                    f"radiant floor surface '{surface.nameString()}' needs an "
                    'ordinary opaque layered construction')
            if any(not layer.to_OpaqueMaterial().is_initialized()
                   for layer in construction.layers()):
                raise ValueError(
                    f"radiant floor surface '{surface.nameString()}' has a "
                    'non-opaque construction layer')
            layer_count = len(construction.layers()) + 1
            for label, number in (
                    ('radiant_source_after_layer_number', source_layer),
                    ('radiant_temperature_after_layer_number',
                     temperature_layer)):
                if number >= layer_count:
                    raise ValueError(
                        f'{label} must be less than the {layer_count}-layer '
                        f"radiant construction for '{surface.nameString()}'")
            selected.append((surface, construction))
    return selected


def _install_internal_source_constructions(model, selected, config):
    by_original = {}
    for surface, construction in selected:
        by_original.setdefault(str(construction.handle()), {
            'construction': construction,
            'surfaces': [],
        })['surfaces'].append(surface)

    for handle, group in by_original.items():
        insulation = openstudio.model.StandardOpaqueMaterial(
            model,
            config['radiant_insulation_roughness'],
            config['radiant_insulation_thickness'],
            config['radiant_insulation_conductivity'],
            config['radiant_insulation_density'],
            config['radiant_insulation_specific_heat'])
        insulation.setName(
            f'BTAP Radiant Floor Insulation {handle[:8]}')
        insulation.additionalProperties().setFeature(
            OWNED_OBJECT_FEATURE, True)

        original = group['construction']
        layers = openstudio.model.OpaqueMaterialVector()
        layers.append(insulation)
        for layer in original.layers():
            layers.append(layer.to_OpaqueMaterial().get())
        construction = openstudio.model.ConstructionWithInternalSource(
            layers)
        construction.setName(
            f'BTAP Radiant Floor {original.nameString()} {handle[:8]}')
        construction.setSourcePresentAfterLayerNumber(
            config['radiant_source_after_layer_number'])
        construction.setTemperatureCalculationRequestedAfterLayerNumber(
            config['radiant_temperature_after_layer_number'])
        construction.setTubeSpacing(config['radiant_tube_spacing'])
        construction.additionalProperties().setFeature(
            OWNED_OBJECT_FEATURE, True)

        for surface in group['surfaces']:
            props = surface.additionalProperties()
            props.setFeature(
                ORIGINAL_CONSTRUCTION_FEATURE, str(original.handle()))
            props.setFeature(
                ORIGINAL_DEFAULTED_FEATURE, surface.isConstructionDefaulted())
            props.setFeature(
                OWNED_CONSTRUCTION_FEATURE, str(construction.handle()))
            if not surface.setConstruction(construction):
                raise RuntimeError(
                    f"could not assign radiant construction to "
                    f"'{surface.nameString()}'")


def restore_owned_surface_constructions(model, zones):
    """Restore only surfaces still using the construction this builder assigned."""
    actions = []
    for zone in zones:
        for surface in _floors(zone):
            props = surface.additionalProperties()
            owned = props.getFeatureAsString(OWNED_CONSTRUCTION_FEATURE)
            if not owned.is_initialized():
                continue

            current = surface.construction()
            still_owned = (
                current.is_initialized()
                and str(current.get().handle()) == owned.get())
            original_defaulted = props.getFeatureAsBoolean(
                ORIGINAL_DEFAULTED_FEATURE)
            original = props.getFeatureAsString(
                ORIGINAL_CONSTRUCTION_FEATURE)
            replacement = None
            if still_owned and not (
                    original_defaulted.is_initialized()
                    and original_defaulted.get()):
                if not original.is_initialized():
                    raise ValueError(
                        f"surface '{surface.nameString()}' has incomplete "
                        'radiant construction provenance')
                replacement = _object_by_handle(
                    model.getConstructionBases(), original.get())
                if replacement is None:
                    raise ValueError(
                        f"surface '{surface.nameString()}' original "
                        'construction no longer exists')
            actions.append(
                (surface, still_owned, original_defaulted, replacement))

    for surface, still_owned, original_defaulted, replacement in actions:
        if still_owned:
            if original_defaulted.is_initialized() and original_defaulted.get():
                surface.resetConstruction()
            elif not surface.setConstruction(replacement):
                raise RuntimeError(
                    f"could not restore construction on '{surface.nameString()}'")
        props = surface.additionalProperties()
        props.resetFeature(ORIGINAL_CONSTRUCTION_FEATURE)
        props.resetFeature(ORIGINAL_DEFAULTED_FEATURE)
        props.resetFeature(OWNED_CONSTRUCTION_FEATURE)


def cleanup_owned_constructions(model):
    """Remove builder-owned construction resources after their last surface."""
    for construction in list(model.getConstructionWithInternalSources()):
        owned = construction.additionalProperties().getFeatureAsBoolean(
            OWNED_OBJECT_FEATURE)
        if (owned.is_initialized() and owned.get()
                and construction.directUseCount() <= 1):
            construction.remove()
    for material in list(model.getStandardOpaqueMaterials()):
        owned = material.additionalProperties().getFeatureAsBoolean(
            OWNED_OBJECT_FEATURE)
        if (owned.is_initialized() and owned.get()
                and material.directUseCount() <= 1):
            material.remove()


def _constant_schedule(model, name, value):
    schedule = openstudio.model.ScheduleConstant(model)
    schedule.setName(name)
    schedule.setValue(value)
    return schedule


class RadiantFloor(BaseSystem):
    def preflight(self, model, zones, control_zone=None, namer='default',
                  remove_existing=False):
        if not self.config.get('needs_boiler'):
            raise ValueError('hydronic radiant floors require needs_boiler=true')
        if not self.config.get('needs_chiller'):
            raise ValueError('hydronic radiant floors require needs_chiller=true')

        hot_profile = plant_loops._normalize_temperature_profile(
            self.config.get('hot_water_profile'), 'hot_water')
        chilled_profile = plant_loops._normalize_temperature_profile(
            self.config.get('chilled_water_profile'), 'chilled_water')
        if hot_profile is None or chilled_profile is None:
            raise ValueError(
                'hydronic radiant floors require explicit hot- and '
                'chilled-water profiles')

        heating_control = _numeric(
            self.config, 'radiant_heating_control_temperature', 10.0, 30.0)
        cooling_control = _numeric(
            self.config, 'radiant_cooling_control_temperature', 15.0, 35.0)
        throttling = _numeric(
            self.config, 'radiant_control_throttling_range', 0.1, 10.0)
        if heating_control + throttling / 2 >= cooling_control - throttling / 2:
            raise ValueError(
                'radiant heating and cooling control bands must not overlap')
        if hot_profile['setpoint_temperature'] <= heating_control:
            raise ValueError(
                'hot-water setpoint must exceed the radiant heating control temperature')
        if chilled_profile['setpoint_temperature'] >= cooling_control:
            raise ValueError(
                'chilled-water setpoint must be below the radiant cooling '
                'control temperature')

        _numeric(self.config, 'radiant_changeover_delay_hours', 0.0, 168.0)
        _numeric(self.config, 'dewpoint_margin', 0.01, 10.0)
        _numeric(self.config, 'radiant_tube_spacing', 0.05, 0.6)
        inside = _numeric(
            self.config, 'radiant_tubing_inside_diameter', 0.001, 0.1)
        outside = _numeric(
            self.config, 'radiant_tubing_outside_diameter', 0.001, 0.12)
        if outside <= inside:
            raise ValueError(
                'radiant_tubing_outside_diameter must exceed inside diameter')
        _numeric(self.config, 'radiant_circuit_length', 1.0, 1000.0)
        for key in (
                'radiant_insulation_thickness',
                'radiant_insulation_conductivity',
                'radiant_insulation_density',
                'radiant_insulation_specific_heat'):
            _numeric(self.config, key, 0.001, 5000.0)
        if self.config.get('radiant_insulation_roughness') not in (
                'VeryRough', 'Rough', 'MediumRough', 'MediumSmooth',
                'Smooth', 'VerySmooth'):
            raise ValueError('invalid radiant_insulation_roughness')
        if self.config.get('radiant_number_of_circuits') not in (
                'CalculateFromCircuitLength', 'OnePerSurface'):
            raise ValueError(
                'invalid radiant_number_of_circuits')
        if self.config.get('radiant_condensation_control_type') not in (
                'SimpleOff', 'VariableOff'):
            raise ValueError(
                'radiant_condensation_control_type must be SimpleOff or VariableOff')

        source_layer = _integer(
            self.config, 'radiant_source_after_layer_number', 1)
        temperature_layer = _integer(
            self.config, 'radiant_temperature_after_layer_number', 1)
        _validated_floor_constructions(
            zones, allow_owned=remove_existing,
            source_layer=source_layer,
            temperature_layer=temperature_layer)
        validate_dehumidifying_doas_inputs(
            supply_air_temperature=self.config.get(
                'doas_supply_air_temperature'),
            maximum_humidity_ratio=self.config.get(
                'doas_maximum_humidity_ratio'))

    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        if hw_loop is None or chw_loop is None:
            raise ValueError(
                'RadiantFloor requires hot- and chilled-water loops')

        selected = _validated_floor_constructions(
            zones, allow_owned=False,
            source_layer=self.config[
                'radiant_source_after_layer_number'],
            temperature_layer=self.config[
                'radiant_temperature_after_layer_number'])
        _install_internal_source_constructions(
            model, selected, self.config)

        system_name = self.config['name']
        air_loop = build_dehumidifying_doas(
            self, model,
            system_name=system_name,
            namer=namer,
            sys_abbr=self.config.get('sys_abbr', 'radiant_floor'),
            supply_air_temperature=self.config[
                'doas_supply_air_temperature'],
            maximum_humidity_ratio=self.config[
                'doas_maximum_humidity_ratio'],
            zone_heating='radiant_floor',
            zone_cooling='radiant_floor')
        always_on = model.alwaysOnDiscreteSchedule()
        heating_control = _constant_schedule(
            model, f'{system_name} Radiant Heating Control',
            self.config['radiant_heating_control_temperature'])
        cooling_control = _constant_schedule(
            model, f'{system_name} Radiant Cooling Control',
            self.config['radiant_cooling_control_temperature'])
        changeover = _constant_schedule(
            model, f'{system_name} Radiant Changeover Delay',
            self.config['radiant_changeover_delay_hours'])

        for zone in zones:
            self.apply_zone_sizing(zone)
            heating_coil = (
                openstudio.model.CoilHeatingLowTempRadiantVarFlow(
                    model, heating_control))
            heating_coil.setName(
                f'Radiant Floor Heating Coil — {zone.nameString()}')
            heating_coil.setHeatingControlThrottlingRange(
                self.config['radiant_control_throttling_range'])
            heating_coil.autosizeMaximumHotWaterFlow()
            heating_coil.autosizeHeatingDesignCapacity()
            hw_loop.addDemandBranchForComponent(heating_coil)

            cooling_coil = (
                openstudio.model.CoilCoolingLowTempRadiantVarFlow(
                    model, cooling_control))
            cooling_coil.setName(
                f'Radiant Floor Cooling Coil — {zone.nameString()}')
            cooling_coil.setCoolingControlThrottlingRange(
                self.config['radiant_control_throttling_range'])
            cooling_coil.setCondensationControlType(
                self.config['radiant_condensation_control_type'])
            cooling_coil.setCondensationControlDewpointOffset(
                self.config['dewpoint_margin'])
            cooling_coil.autosizeMaximumColdWaterFlow()
            cooling_coil.autosizeCoolingDesignCapacity()
            chw_loop.addDemandBranchForComponent(cooling_coil)

            radiant = openstudio.model.ZoneHVACLowTempRadiantVarFlow(
                model, always_on, heating_coil, cooling_coil)
            radiant.setName(
                f'Hydronic Radiant Floor — {zone.nameString()}')
            radiant.setRadiantSurfaceType('Floors')
            radiant.setTemperatureControlType('MeanAirTemperature')
            radiant.setSetpointControlType('HalfFlowPower')
            radiant.setChangeoverDelayTimePeriodSchedule(changeover)
            radiant.setHydronicTubingInsideDiameter(
                self.config['radiant_tubing_inside_diameter'])
            radiant.setHydronicTubingOutsideDiameter(
                self.config['radiant_tubing_outside_diameter'])
            radiant.autosizeHydronicTubingLength()
            radiant.setNumberofCircuits(
                self.config['radiant_number_of_circuits'])
            radiant.setCircuitLength(
                self.config['radiant_circuit_length'])
            radiant.addToThermalZone(zone)

            terminal = (
                openstudio.model.AirTerminalSingleDuctConstantVolumeNoReheat(
                    model, always_on))
            terminal.setName(
                f'Radiant Floor DOAS Terminal — {zone.nameString()}')
            air_loop.addBranchForZone(
                zone, terminal.to_StraightComponent())

        plant_loops.configure_dewpoint_reset(
            chw_loop, zones, self.config['dewpoint_margin'])
        return [air_loop]
