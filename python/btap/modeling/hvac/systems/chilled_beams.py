"""DOAS with active or passive chilled-beam terminals and perimeter heat."""

from __future__ import annotations

import openstudio

from btap.modeling.hvac.systems import baseboards, plant_loops
from btap.modeling.hvac.systems.base_system import BaseSystem
from btap.modeling.hvac.systems.doas import (
    build_dehumidifying_doas,
    validate_dehumidifying_doas_inputs,
)


def _numeric(config, key, lower, upper):
    value = config.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{key} must be numeric')
    value = float(value)
    if not lower <= value <= upper:
        raise ValueError(f'{key} must be between {lower} and {upper}')
    return value


class ChilledBeams(BaseSystem):
    def preflight(self, model, zones, control_zone=None, namer='default',
                  remove_existing=False):
        beam_type = self.config.get('beam_type')
        if beam_type not in ('Active', 'Passive'):
            raise ValueError("beam_type must be 'Active' or 'Passive'")

        baseboard_type = self.config.get('baseboard_type')
        if baseboard_type not in ('Electric', 'Hot Water'):
            raise ValueError(
                "chilled-beam baseboard_type must be 'Electric' or 'Hot Water'")
        if baseboard_type == 'Hot Water' and not self.config.get('needs_boiler'):
            raise ValueError(
                'Hot Water chilled-beam baseboards require needs_boiler=true')
        if not self.config.get('needs_chiller'):
            raise ValueError('chilled beams require needs_chiller=true')
        if self.config.get('chw_source', 'water_cooled') not in (
                'water_cooled', 'air_cooled', 'district'):
            raise ValueError(
                "chw_source must be 'water_cooled', 'air_cooled', or 'district'")

        profile = plant_loops._normalize_temperature_profile(
            self.config.get('chilled_water_profile'), 'chilled_water')
        if profile is None:
            raise ValueError(
                'chilled beams require an explicit chilled_water_profile')

        inlet = _numeric(
            self.config, 'beam_design_inlet_water_temperature', 5.0, 30.0)
        outlet = _numeric(
            self.config, 'beam_design_outlet_water_temperature', 5.0, 35.0)
        if outlet <= inlet:
            raise ValueError(
                'beam_design_outlet_water_temperature must exceed inlet temperature')
        if abs(profile['design_exit_temperature'] - inlet) > 1e-9:
            raise ValueError(
                'chilled-water design exit temperature must equal beam inlet temperature')
        if abs(profile['design_temperature_difference'] - (outlet - inlet)) > 1e-9:
            raise ValueError(
                'chilled-water design temperature difference must equal the beam '
                'outlet-to-inlet difference')
        if abs(profile['setpoint_temperature'] - inlet) > 1e-9:
            raise ValueError(
                'chilled-water setpoint temperature must equal beam inlet temperature')

        _numeric(self.config, 'dewpoint_margin', 0.01, 10.0)
        validate_dehumidifying_doas_inputs(
            supply_air_temperature=self.config.get(
                'doas_supply_air_temperature'),
            maximum_humidity_ratio=self.config.get(
                'doas_maximum_humidity_ratio'))

    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        if chw_loop is None:
            raise ValueError('ChilledBeams requires a chilled water loop')
        if (self.config['baseboard_type'] == 'Hot Water'
                and hw_loop is None):
            raise ValueError(
                'ChilledBeams requires a hot water loop for Hot Water baseboards')

        system_name = self.config['name']
        beam_type = self.config['beam_type']
        air_loop = build_dehumidifying_doas(
            self, model,
            system_name=system_name,
            namer=namer,
            sys_abbr=self.config.get('sys_abbr', 'chilled_beam'),
            supply_air_temperature=self.config['doas_supply_air_temperature'],
            maximum_humidity_ratio=self.config[
                'doas_maximum_humidity_ratio'],
            zone_heating=self.config['baseboard_type'],
            zone_cooling='chilled_beam')
        always_on = model.alwaysOnDiscreteSchedule()

        for zone in zones:
            self.apply_zone_sizing(zone)
            cooling_coil = openstudio.model.CoilCoolingCooledBeam(model)
            cooling_coil.setName(
                f'{beam_type} Chilled Beam Cooling Coil — {zone.nameString()}')
            chw_loop.addDemandBranchForComponent(cooling_coil)

            terminal = (
                openstudio.model.AirTerminalSingleDuctConstantVolumeCooledBeam(
                    model, always_on, cooling_coil))
            terminal.setName(
                f'{beam_type} Chilled Beam Terminal — {zone.nameString()}')
            terminal.setCooledBeamType(beam_type)
            terminal.setDesignInletWaterTemperature(
                self.config['beam_design_inlet_water_temperature'])
            terminal.setDesignOutletWaterTemperature(
                self.config['beam_design_outlet_water_temperature'])
            terminal.autosizeSupplyAirVolumetricFlowRate()
            terminal.autosizeMaximumTotalChilledWaterVolumetricFlowRate()
            terminal.autosizeNumberofBeams()
            terminal.autosizeBeamLength()
            air_loop.addBranchForZone(zone, terminal.to_StraightComponent())

            baseboards.add(
                model, zone, self.config['baseboard_type'], hw_loop=hw_loop)

        plant_loops.configure_dewpoint_reset(
            chw_loop, zones, self.config['dewpoint_margin'])
        return [air_loop]
