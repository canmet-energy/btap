"""Standalone ventilation DOAS: 100% outdoor-air CV loop at a constant neutral supply
temperature with uncontrolled diffusers — the ventilation half of the CBECS
'DOAS with <zone system>' composites (built here in the NECB MAU style)."""

from __future__ import annotations

import openstudio

from btap.modeling.hvac import naming
from btap.modeling.hvac.components import coils, schedules
from btap.modeling.hvac.systems.base_system import BaseSystem


def validate_dehumidifying_doas_inputs(*, supply_air_temperature,
                                       maximum_humidity_ratio):
    """Validate the modern DOAS controls without creating model objects."""
    normalized = {}
    for name, value, lower, upper in (
            ('supply_air_temperature', supply_air_temperature, 5.0, 30.0),
            ('maximum_humidity_ratio', maximum_humidity_ratio, 0.001, 0.03)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f'{name} must be numeric')
        value = float(value)
        if not lower <= value <= upper:
            raise ValueError(f'{name} must be between {lower} and {upper}')
        normalized[name] = value
    return normalized


def build_dehumidifying_doas(system, model, *, system_name, namer,
                             sys_abbr, supply_air_temperature,
                             maximum_humidity_ratio, zone_heating,
                             zone_cooling):
    """Build the supply side of a 100% OA, cool-and-reheat DOAS.

    New modern systems use this path. The legacy ``Doas`` class below keeps
    its original neutral-temperature-only behavior unchanged.
    """
    inputs = validate_dehumidifying_doas_inputs(
        supply_air_temperature=supply_air_temperature,
        maximum_humidity_ratio=maximum_humidity_ratio)
    supply_air_temperature = inputs['supply_air_temperature']
    maximum_humidity_ratio = inputs['maximum_humidity_ratio']

    always_on = model.alwaysOnDiscreteSchedule()
    air_loop = openstudio.model.AirLoopHVAC(model)
    system.apply_system_sizing(air_loop)

    fan = openstudio.model.FanConstantVolume(model, always_on)
    fan.setName(f'{system_name} Supply Fan')
    reheat = openstudio.model.CoilHeatingElectric(model, always_on)
    reheat.setName(f'{system_name} Reheat Coil')
    cooling = coils.dx_cooling_single_speed(
        model, always_on, name=f'{system_name} Dehumidification Coil')

    oa_system = system.build_oa_system(model)
    oa_controller = oa_system.getControllerOutdoorAir()
    oa_controller.setMinimumFractionofOutdoorAirSchedule(always_on)
    oa_controller.setMaximumFractionofOutdoorAirSchedule(always_on)
    oa_controller.setEconomizerControlType('NoEconomizer')

    inlet = air_loop.supplyInletNode()
    fan.addToNode(inlet)
    reheat.addToNode(inlet)
    cooling.addToNode(inlet)
    oa_system.addToNode(inlet)

    humidity_schedule = openstudio.model.ScheduleConstant(model)
    humidity_schedule.setName(f'{system_name} Maximum Supply Humidity Ratio')
    humidity_schedule.setValue(float(maximum_humidity_ratio))
    humidity_manager = openstudio.model.SetpointManagerScheduled(
        model, humidity_schedule)
    humidity_manager.setName(f'{system_name} Humidity Setpoint Manager')
    humidity_manager.setControlVariable('MaximumHumidityRatio')
    cooling_outlet = cooling.outletModelObject()
    if not cooling_outlet.is_initialized():
        raise RuntimeError('the DOAS cooling coil has no outlet node')
    humidity_manager.addToNode(cooling_outlet.get().to_Node().get())

    temperature_schedule = openstudio.model.ScheduleConstant(model)
    temperature_schedule.setName(f'{system_name} Supply Air Temperature')
    temperature_schedule.setValue(float(supply_air_temperature))
    temperature_manager = openstudio.model.SetpointManagerScheduled(
        model, temperature_schedule)
    temperature_manager.setName(f'{system_name} Temperature Setpoint Manager')
    temperature_manager.addToNode(air_loop.supplyOutletNode())

    naming.apply(
        namer, air_loop, system_name=system_name, sys_abbr=sys_abbr,
        sys_oa='doas',
        parts={'sys_hr': 'none', 'sys_clg': 'dx', 'sys_htg': 'electric',
               'sys_sf': 'cv', 'zone_htg': zone_heating,
               'zone_clg': zone_cooling, 'sys_rf': 'none'},
        suffix=None)
    return air_loop


class Doas(BaseSystem):
    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        always_on = model.alwaysOnDiscreteSchedule()
        air_loop = openstudio.model.AirLoopHVAC(model)
        self.apply_system_sizing(air_loop)

        fan = openstudio.model.FanConstantVolume(model, always_on)
        fan.setName('DOAS Supply Fan')
        htg = coils.heating_coil(model, self.config.get('heating_type', 'Electric'),
                                 always_on, hw_loop=hw_loop)
        clg = coils.dx_cooling_single_speed(model, always_on, name='DOAS DX Clg Coil')

        supply_inlet_node = air_loop.supplyInletNode()
        fan.addToNode(supply_inlet_node)
        htg.addToNode(supply_inlet_node)
        clg.addToNode(supply_inlet_node)
        self.build_oa_system(model).addToNode(supply_inlet_node)

        spm = openstudio.model.SetpointManagerScheduled(
            model,
            schedules.constant_ruleset(model, 'DOAS Neutral Supply Air Temp', 20.0))
        spm.addToNode(air_loop.supplyOutletNode())

        for zone in zones:
            diffuser = openstudio.model.AirTerminalSingleDuctUncontrolled(model, always_on)
            air_loop.addBranchForZone(zone, diffuser.to_StraightComponent())

        naming.apply(namer, air_loop,
                     system_name=self.config['name'], sys_abbr='doas', sys_oa='doas',
                     parts={'sys_hr': 'none', 'sys_clg': 'dx',
                            'sys_htg': self.config.get('heating_type', 'Electric'),
                            'sys_sf': 'cv', 'zone_htg': 'none', 'zone_clg': 'none',
                            'sys_rf': 'none'},
                     suffix=None)
        return [air_loop]
