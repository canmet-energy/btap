"""True two-deck VAV with hot- and cold-deck hydronic coils."""

from __future__ import annotations

import math

import openstudio

from btap._compat import sorted_by_name
from btap.modeling.hvac import naming
from btap.modeling.hvac.components import schedules
from btap.modeling.hvac.systems.base_system import BaseSystem


def _finite(config, key):
    value = config.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{key} must be a finite number')
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f'{key} must be a finite number')
    return value


class DualDuctVAV(BaseSystem):
    def preflight(self, model, zones, control_zone=None, namer='default',
                  remove_existing=False):
        if not self.config.get('needs_boiler'):
            raise ValueError('DualDuctVAV requires needs_boiler=True')
        if not self.config.get('needs_chiller'):
            raise ValueError('DualDuctVAV requires needs_chiller=True')
        hot = _finite(self.sizing, 'hot_deck_supply_air_temperature')
        cold = _finite(self.sizing, 'cold_deck_supply_air_temperature')
        minimum = _finite(self.sizing, 'zone_minimum_air_flow_fraction')
        if not hot > cold:
            raise ValueError(
                'hot_deck_supply_air_temperature must exceed '
                'cold_deck_supply_air_temperature')
        if not 0.0 <= minimum <= 1.0:
            raise ValueError(
                'zone_minimum_air_flow_fraction must be between 0 and 1')

    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        if hw_loop is None or chw_loop is None:
            raise ValueError(
                'DualDuctVAV requires hot-water and chilled-water loops')

        always_on = model.alwaysOnDiscreteSchedule()
        air_loop = openstudio.model.AirLoopHVAC(model, True)
        self.apply_system_sizing(air_loop)

        fan = openstudio.model.FanVariableVolume(model, always_on)
        fan.setName('Dual-Duct Supply Fan')
        fan.addToNode(air_loop.supplyInletNode())
        oa_system = self.build_oa_system(model)
        oa_system.addToNode(air_loop.supplyInletNode())

        hot_outlet, cold_outlet = air_loop.supplyOutletNodes()
        hot_outlet.setName('Dual-Duct Hot Deck Outlet')
        cold_outlet.setName('Dual-Duct Cold Deck Outlet')

        heating_coil = openstudio.model.CoilHeatingWater(model, always_on)
        heating_coil.setName('Dual-Duct Hot Deck Heating Coil')
        hw_loop.addDemandBranchForComponent(heating_coil)
        heating_coil.addToNode(hot_outlet)

        cooling_coil = openstudio.model.CoilCoolingWater(model, always_on)
        cooling_coil.setName('Dual-Duct Cold Deck Cooling Coil')
        chw_loop.addDemandBranchForComponent(cooling_coil)
        cooling_coil.addToNode(cold_outlet)

        hot_setpoint = openstudio.model.SetpointManagerScheduled(
            model, schedules.constant_ruleset(
                model, 'Dual-Duct Hot Deck Temperature',
                self.sizing['hot_deck_supply_air_temperature']))
        hot_setpoint.setName('Dual-Duct Hot Deck Setpoint Manager')
        hot_setpoint.addToNode(hot_outlet)
        cold_setpoint = openstudio.model.SetpointManagerScheduled(
            model, schedules.constant_ruleset(
                model, 'Dual-Duct Cold Deck Temperature',
                self.sizing['cold_deck_supply_air_temperature']))
        cold_setpoint.setName('Dual-Duct Cold Deck Setpoint Manager')
        cold_setpoint.addToNode(cold_outlet)

        for zone in sorted_by_name(zones):
            self.apply_zone_sizing(zone)
            terminal = openstudio.model.AirTerminalDualDuctVAV(model)
            terminal.setName(f'{zone.nameString()} Dual-Duct VAV Terminal')
            terminal.autosizeMaximumDamperAirFlowRate()
            terminal.setZoneMinimumAirFlowFraction(
                self.sizing['zone_minimum_air_flow_fraction'])
            air_loop.addBranchForZone(zone, terminal)

        naming.apply(
            namer, air_loop, system_name=self.config['name'],
            sys_abbr=self.config.get('sys_abbr', 'dual_duct'),
            sys_oa='mixed',
            parts={
                'sys_hr': 'none',
                'sys_htg': 'Hot Water',
                'sys_clg': 'Chilled Water',
                'sys_sf': 'vv',
                'zone_htg': 'none',
                'zone_clg': 'none',
                'sys_rf': 'none',
            })
        return [air_loop]
