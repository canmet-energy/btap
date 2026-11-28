"""True two-deck VAV. By default the hot deck carries a hot-water coil and the
cold deck a chilled-water coil; `heating_type` and `cooling_type` select a
direct coil instead (#259): 'Gas' or 'Electric' on the hot deck, 'dx' (a
two-speed DX coil, as the packaged-VAV rows use) on the cold deck."""

from __future__ import annotations

import math

import openstudio

from btap._compat import sorted_by_name
from btap.modeling.hvac import naming
from btap.modeling.hvac.components import coils, schedules
from btap.modeling.hvac.systems.base_system import BaseSystem


def _finite(config, key):
    value = config.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{key} must be a finite number')
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f'{key} must be a finite number')
    return value


_HYDRONIC_HEAT = ('Hot Water', 'HotWater')
_DIRECT_HEAT = ('Gas', 'NaturalGas', 'Electric', 'Electricity')


class DualDuctVAV(BaseSystem):
    def _heating_type(self):
        return self.config.get('heating_type', 'Hot Water')

    def _dx_cooling(self):
        return self.config.get('cooling_type', 'chilled_water') == 'dx'

    def preflight(self, model, zones, control_zone=None, namer='default',
                  remove_existing=False):
        heating_type = self._heating_type()
        if heating_type not in _HYDRONIC_HEAT + _DIRECT_HEAT:
            raise ValueError(
                f'DualDuctVAV heating_type {heating_type!r} is not one of '
                f'{list(_HYDRONIC_HEAT + _DIRECT_HEAT)}')
        cooling_type = self.config.get('cooling_type', 'chilled_water')
        if cooling_type not in ('chilled_water', 'dx'):
            raise ValueError(
                f"DualDuctVAV cooling_type {cooling_type!r} is not "
                "'chilled_water' or 'dx'")
        if heating_type in _HYDRONIC_HEAT and not self.config.get('needs_boiler'):
            raise ValueError('DualDuctVAV with a hot-water hot deck requires needs_boiler=True')
        if not self._dx_cooling() and not self.config.get('needs_chiller'):
            raise ValueError('DualDuctVAV with a chilled-water cold deck requires needs_chiller=True')
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
        heating_type = self._heating_type()
        dx_cooling = self._dx_cooling()
        if heating_type in _HYDRONIC_HEAT and hw_loop is None:
            raise ValueError('DualDuctVAV requires a hot-water loop for its hot deck')
        if not dx_cooling and chw_loop is None:
            raise ValueError('DualDuctVAV requires a chilled-water loop for its cold deck')

        always_on = model.alwaysOnDiscreteSchedule()
        air_loop = openstudio.model.AirLoopHVAC(model, True)
        self.apply_system_sizing(air_loop)

        fan = openstudio.model.FanVariableVolume(model, always_on)
        fan.setName('Dual-Duct Supply Fan')
        fan.addToNode(air_loop.supplyInletNode())
        oa_system = self.build_oa_system(model)
        # #217: attach through BaseSystem so energy recovery reaches
        # the OA nodes, which only exist once attached.
        self.attach_oa_system(model, oa_system, air_loop.supplyInletNode())

        hot_outlet, cold_outlet = air_loop.supplyOutletNodes()
        hot_outlet.setName('Dual-Duct Hot Deck Outlet')
        cold_outlet.setName('Dual-Duct Cold Deck Outlet')

        # Through `coils.heating_coil`, which hangs a hot-water coil on
        # `hw_loop` exactly as this builder did by hand.
        heating_coil = coils.heating_coil(
            model, heating_type, always_on, hw_loop=hw_loop,
            performance_profile=self.performance_profile)
        heating_coil.setName('Dual-Duct Hot Deck Heating Coil')
        heating_coil.addToNode(hot_outlet)

        if dx_cooling:
            cooling_coil = openstudio.model.CoilCoolingDXTwoSpeed(model)
        else:
            cooling_coil = openstudio.model.CoilCoolingWater(model, always_on)
            chw_loop.addDemandBranchForComponent(cooling_coil)
        cooling_coil.setName('Dual-Duct Cold Deck Cooling Coil')
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
            namer, air_loop, system_name=self.config['id'],
            sys_abbr=self.config.get('sys_abbr', 'dual_duct'),
            sys_oa='mixed',
            parts={
                'sys_hr': 'none',
                'sys_htg': 'Hot Water' if heating_type in _HYDRONIC_HEAT else heating_type,
                'sys_clg': 'dx' if dx_cooling else 'Chilled Water',
                'sys_sf': 'vv',
                'zone_htg': 'none',
                'zone_clg': 'none',
                'sys_rf': 'none',
            })
        return [air_loop]
