"""ECM "hs11": DOAS + air-source heat pump + zone PTHPs (port of NECB ECMS
add_ecm_hs11_ashp_pthp topology). A 100% outdoor-air DOAS with single-speed DX
heating/cooling (ASHP) and a supplemental coil serves ventilation at a constant
20C supply; each zone gets a packaged terminal heat pump (DX heat/cool + electric
supplemental) with ~zero outdoor air, plus uncontrolled diffusers.

Topology only: the ECM equipment performance curves and COPs (capacity-binned
HS11_PTHP data) are applied by the host's ECM efficiency pass
(ECMS#apply_efficiency_ecm_hs11_ashp_pthp) after sizing — exactly as in the legacy
flow, where build-time curve application is provisional and re-done post-sizing."""

from __future__ import annotations

import re

import openstudio

from btap._compat import sorted_by_name
from btap.modeling.hvac import naming
from btap.modeling.hvac.components import coils, schedules
from btap.modeling.hvac.components import curves as curves_mod
from btap.modeling.hvac.systems.base_system import BaseSystem


class DoasPthp(BaseSystem):
    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        """:return: list of openstudio.model.AirLoopHVAC"""
        always_on = model.alwaysOnDiscreteSchedule()
        always_off = model.alwaysOffDiscreteSchedule()
        supp_htg_fuel = self.config.get('supp_htg_fuel', 'Electric')

        # --- DOAS air loop ---
        air_loop = openstudio.model.AirLoopHVAC(model)
        self.apply_system_sizing(air_loop)

        clg_coil = openstudio.model.CoilCoolingDXSingleSpeed(model)
        clg_coil.setName('CoilCoolingDxSingleSpeed_ASHP')
        clg_coil.setCrankcaseHeaterCapacity(1.0e-6)

        htg_coil = openstudio.model.CoilHeatingDXSingleSpeed(model)
        htg_coil.setName('CoilHeatingDXSingleSpeed_ASHP')
        htg_coil.setDefrostStrategy('ReverseCycle')
        htg_coil.setDefrostControl('OnDemand')
        # REQUIRED once the strategy is ReverseCycle — see curves.defrost_eir_ft
        htg_coil.setDefrostEnergyInputRatioFunctionofTemperatureCurve(
            curves_mod.defrost_eir_ft(model))
        htg_coil.setCrankcaseHeaterCapacity(1.0e-6)

        supp_coil = coils.heating_coil(model, supp_htg_fuel, always_on, hw_loop=hw_loop)
        if re.search('Electric', supp_htg_fuel, re.IGNORECASE):
            supp_coil.setName('CoilHeatingElectric')

        fan = openstudio.model.FanConstantVolume(model)
        fan.setName('Supply Fan')   # 'Supply' substring is load-bearing for host fan rules

        # Legacy insertion order (each added at the supply outlet): clg, htg, supp, fan, spm
        clg_coil.addToNode(air_loop.supplyOutletNode())
        htg_coil.addToNode(air_loop.supplyOutletNode())
        supp_coil.addToNode(air_loop.supplyOutletNode())
        fan.addToNode(air_loop.supplyOutletNode())

        sat = self.sizing.get('system_supply_air_temperature', 20.0)
        spm = openstudio.model.SetpointManagerScheduled(
            model, schedules.constant_ruleset(model, 'DOAS Supply Air Temp', sat))
        spm.addToNode(air_loop.supplyOutletNode())

        oa_system = self.build_oa_system(model)
        oa_system.addToNode(air_loop.supplyInletNode())

        # --- zones: sizing, diffuser, PTHP ---
        for zone in sorted_by_name(zones):
            self.apply_zone_sizing(zone)

            diffuser = openstudio.model.AirTerminalSingleDuctUncontrolled(model, always_on)
            air_loop.addBranchForZone(zone, diffuser.to_StraightComponent())

            pthp_clg = openstudio.model.CoilCoolingDXSingleSpeed(model)
            pthp_clg.setName('CoilCoolingDXSingleSpeed_PTHP')
            pthp_clg.setCrankcaseHeaterCapacity(1.0e-6)

            pthp_htg = openstudio.model.CoilHeatingDXSingleSpeed(model)
            pthp_htg.setName('CoilHeatingDXSingleSpeed_PTHP')
            pthp_htg.setDefrostStrategy('ReverseCycle')
            pthp_htg.setDefrostControl('OnDemand')
            pthp_htg.setDefrostEnergyInputRatioFunctionofTemperatureCurve(
                curves_mod.defrost_eir_ft(model))
            pthp_htg.setCrankcaseHeaterCapacity(1.0e-6)

            pthp_supp = openstudio.model.CoilHeatingElectric(model, always_on)
            pthp_supp.setName('CoilHeatingElectric')

            pthp_fan = openstudio.model.FanOnOff(model)
            pthp_fan.setName('FanOnOff')

            pthp = openstudio.model.ZoneHVACPackagedTerminalHeatPump(
                model, always_on, pthp_fan, pthp_htg, pthp_clg, pthp_supp)
            pthp.setName('ZoneHVACPackagedTerminalHeatPump')
            pthp.setOutdoorAirFlowRateDuringCoolingOperation(1.0e-6)
            pthp.setOutdoorAirFlowRateDuringHeatingOperation(1.0e-6)
            pthp.setOutdoorAirFlowRateWhenNoCoolingorHeatingisNeeded(1.0e-6)
            pthp.setSupplyAirFanOperatingModeSchedule(always_off)
            pthp.addToThermalZone(zone)

        # Legacy final name (assign_base_sys_name + update_sys_name):
        # sys_1|doas|shr>none|sc>ashp|sh>ashp|ssf>cv|zh>pthp|zc>pthp|srf>none|
        naming.apply(namer, air_loop,
                     system_name=self.config['name'],
                     sys_abbr=self.config.get('sys_abbr', 'sys_1'),
                     sys_oa='doas',
                     parts={
                         'sys_hr': 'none',
                         'sys_clg': 'ashp',
                         'sys_htg': 'ashp',
                         'sys_sf': 'cv',
                         'zone_htg': 'pthp',
                         'zone_clg': 'pthp',
                         'sys_rf': 'none',
                     },
                     suffix=None)
        return [air_loop]
