"""Fan coils + make-up air unit (port of NECB sys2 FPFC / sys5 TPFC): a constant-volume
MAU delivers ventilation through uncontrolled diffusers while per-zone four-pipe fan
coils (FPFC) or two-pipe fan coils (TPFC, via seasonal heating/cooling availability
schedules) do the conditioning. Hot-water and chilled/condenser-water plant serve the
fan coils; the MAU cooling coil is DX (NECB curves) or hydronic per config.

Legacy parity notes:
- The MAU DX cooling coil uses the SEASONAL cooling availability schedule even for
  FPFC (legacy behavior, preserved).
- The MAU's SetpointManagerSingleZoneReheat has NO explicit control zone (legacy lets
  OpenStudio pick), and its min/max supply temps are inverted (13.1/13.0) — preserved.
"""

from __future__ import annotations

import openstudio

from btap.modeling.hvac import naming
from btap.modeling.hvac.components import coils, schedules
from btap.modeling.hvac.systems.base_system import BaseSystem


class FanCoils(BaseSystem):
    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        """:param control_zone: unused (legacy MAU sets no control zone); accepted for
            the shared build contract
        :param hw_loop: fan-coil heating (always hydronic)
        :param chw_loop: fan-coil cooling
        :return: list of openstudio.model.AirLoopHVAC
        """
        # D-39 (A4): config 'heating' => 'none' builds the COOLING-ONLY variant
        # (Table 8.4.4.7.-B System 5 heating "None") — no hot-water loop, no MAU
        # heating coil, zone fan coils with a zero-capacity always-off
        # placeholder heating coil (the FourPipeFanCoil object requires one).
        heating_none = str(self.config.get('heating')) == 'none'
        if hw_loop is None and not heating_none:
            raise ValueError('FanCoils requires a hot water loop (needs_boiler)')
        if chw_loop is None:
            raise ValueError('FanCoils requires a chilled water loop (needs_chiller)')

        always_on = model.alwaysOnDiscreteSchedule()
        fan_coil_type = self.config.get('fan_coil_type', 'FPFC')
        mau_cooling_type = self.config.get('mau_cooling_type', 'DX')
        mau_heating_coil_type = ('None' if heating_none
                                 else self.config.get('mau_heating_coil_type', 'Gas'))
        with_mau = self.config.get('mau', True)

        clg_avail_sch, htg_avail_sch = schedules.seasonal_availability(model)

        # --- fan coils only (no MAU): ventilation comes from elsewhere, e.g. a DOAS
        #     composite part (the CBECS 'DOAS with fan coil ...' pattern) ---
        if not with_mau:
            for zone in zones:
                self.apply_zone_sizing(zone)
                self._add_zone_fan_coil(model, zone, fan_coil_type, always_on,
                                        htg_avail_sch, clg_avail_sch,
                                        hw_loop=hw_loop, chw_loop=chw_loop)
            return []

        # --- make-up air unit ---
        air_loop = openstudio.model.AirLoopHVAC(model)
        self.apply_system_sizing(air_loop)

        fan = openstudio.model.FanConstantVolume(model, always_on)
        fan.setName(f"{self.config['sys_abbr']} MAU Supply Fan")

        htg_coil = (None if mau_heating_coil_type == 'None'
                    else coils.heating_coil(model, mau_heating_coil_type, always_on,
                                            hw_loop=hw_loop))

        if mau_cooling_type == 'DX':
            clg_coil = coils.dx_cooling_single_speed(model, clg_avail_sch)
        elif mau_cooling_type in ('Hydronic', 'Hot Water', 'HotWater', 'Chilled Water'):
            clg_coil = openstudio.model.CoilCoolingWater(model, clg_avail_sch)
            chw_loop.addDemandBranchForComponent(clg_coil)
        else:
            raise ValueError(f"'{mau_cooling_type}' is not a valid MAU cooling type")

        oa_system = self.build_oa_system(model)

        supply_inlet_node = air_loop.supplyInletNode()
        fan.addToNode(supply_inlet_node)
        if htg_coil is not None:
            htg_coil.addToNode(supply_inlet_node)
        clg_coil.addToNode(supply_inlet_node)
        oa_system.addToNode(supply_inlet_node)

        spm = openstudio.model.SetpointManagerSingleZoneReheat(model)
        if self.sizing.get('setpoint_manager_single_zone_reheat_supply_temp_min') is not None:
            spm.setMinimumSupplyAirTemperature(
                self.sizing['setpoint_manager_single_zone_reheat_supply_temp_min'])
        if self.sizing.get('setpoint_manager_single_zone_reheat_supply_temp_max') is not None:
            spm.setMaximumSupplyAirTemperature(
                self.sizing['setpoint_manager_single_zone_reheat_supply_temp_max'])
        spm.addToNode(air_loop.supplyOutletNode())

        # --- zones: sizing, fan coils, diffusers ---
        for zone in zones:
            self.apply_zone_sizing(zone)
            self._add_zone_fan_coil(model, zone, fan_coil_type, always_on,
                                    htg_avail_sch, clg_avail_sch,
                                    hw_loop=hw_loop, chw_loop=chw_loop)
            diffuser = openstudio.model.AirTerminalSingleDuctUncontrolled(model, always_on)
            air_loop.addBranchForZone(zone, diffuser.to_StraightComponent())

        # parts insertion order matches legacy sys2/5: hr, clg, htg, sf, zone_htg, zone_clg, rf
        mau_clg_part = ('Hydronic'
                        if mau_cooling_type in ('Hydronic', 'Hot Water', 'HotWater',
                                                'Chilled Water')
                        else 'DX')
        naming.apply(namer, air_loop,
                     system_name=self.config['name'],
                     sys_abbr=self.config['sys_abbr'],
                     sys_oa='doas',
                     parts={
                         'sys_hr': 'none',
                         'sys_clg': mau_clg_part,
                         'sys_htg': self._legacy_htg_part(mau_heating_coil_type),
                         'sys_sf': 'cv',
                         'zone_htg': fan_coil_type,
                         'zone_clg': fan_coil_type,
                         'sys_rf': 'none',
                     },
                     suffix=None)
        return [air_loop]

    def _add_zone_fan_coil(self, model, zone, fan_coil_type, always_on,
                           htg_avail_sch, clg_avail_sch, *, hw_loop, chw_loop):
        fc_fan = openstudio.model.FanConstantVolume(model, always_on)
        if hw_loop is None:  # D-39 cooling-only: zero-capacity always-off placeholder
            fc_htg_coil = openstudio.model.CoilHeatingElectric(
                model, model.alwaysOffDiscreteSchedule())
            fc_htg_coil.setNominalCapacity(0.0)
            fc_clg_coil = openstudio.model.CoilCoolingWater(
                model, clg_avail_sch if fan_coil_type == 'TPFC' else always_on)
        elif fan_coil_type == 'TPFC':
            fc_htg_coil = openstudio.model.CoilHeatingWater(model, htg_avail_sch)
            fc_clg_coil = openstudio.model.CoilCoolingWater(model, clg_avail_sch)
        else:  # FPFC
            fc_htg_coil = openstudio.model.CoilHeatingWater(model, always_on)
            fc_clg_coil = openstudio.model.CoilCoolingWater(model, always_on)
        if hw_loop is not None:
            hw_loop.addDemandBranchForComponent(fc_htg_coil)
        chw_loop.addDemandBranchForComponent(fc_clg_coil)

        fan_coil = openstudio.model.ZoneHVACFourPipeFanCoil(
            model, always_on, fc_fan, fc_clg_coil, fc_htg_coil)
        fan_coil.addToThermalZone(zone)
        return fan_coil

    def _legacy_htg_part(self, mau_heating_coil_type):
        """Legacy sys2 emits short fuel tokens ('g'/'e') for the MAU heating coil."""
        if mau_heating_coil_type in ('Gas', 'NaturalGas'):
            return 'g'
        if mau_heating_coil_type in ('Electric', 'Electricity', 'FuelOilNo2'):
            return 'e'
        if mau_heating_coil_type == 'None':
            return 'none'
        return mau_heating_coil_type
