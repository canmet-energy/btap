"""Make-up air unit + per-zone PTAC (port of NECB sys1, non-heat-pump path): a 100%
outdoor-air constant-volume MAU (sized on the ventilation requirement, constant 20C
supply) delivers ventilation through uncontrolled diffusers, while each zone gets a
PTAC (DX cooling with NECB curves, always-off electric heating section, zero OA) for
cooling and baseboards for heating."""

from __future__ import annotations

import openstudio

from btap.modeling.hvac import naming
from btap.modeling.hvac.components import coils, schedules
from btap.modeling.hvac.systems import baseboards
from btap.modeling.hvac.systems.base_system import BaseSystem


class MauPtac(BaseSystem):
    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        """:param control_zone: unused (MAU has a scheduled setpoint); accepted for the
            shared build contract
        :param hw_loop: for hot-water MAU coil/baseboards (or None)
        :return: list of openstudio.model.AirLoopHVAC
        """
        always_on = model.alwaysOnDiscreteSchedule()
        always_off = schedules.always_off(model)
        reference_hp = self.config.get('reference_hp') is True
        mau_heating_coil_type = self.config.get('mau_heating_coil_type', 'Electric')
        baseboard_type = self.config.get('baseboard_type')
        supp_fuel = self.config.get('supp_htg_fuel', 'Electric')

        # --- make-up air unit ---
        air_loop = openstudio.model.AirLoopHVAC(model)
        self.apply_system_sizing(air_loop)

        fan = openstudio.model.FanConstantVolume(model, always_on)
        fan.setName(f"{self.config['sys_abbr']} MAU Supply Fan")

        if reference_hp:
            htg_coil = coils.dx_heating_single_speed(
                model, always_on, name='CoilHeatingDXSingleSpeed_ashp')
            clg_coil = coils.dx_cooling_single_speed(
                model, always_on, name='CoilCoolingDXSingleSpeed_ashp')
        else:
            htg_coil = coils.heating_coil(model, mau_heating_coil_type, always_on,
                                          hw_loop=hw_loop)
            clg_coil = coils.dx_cooling_single_speed(model, always_on)
        oa_system = self.build_oa_system(model)

        supply_inlet_node = air_loop.supplyInletNode()
        fan.addToNode(supply_inlet_node)
        htg_coil.addToNode(supply_inlet_node)
        clg_coil.addToNode(supply_inlet_node)
        oa_system.addToNode(supply_inlet_node)

        if reference_hp:
            spm = openstudio.model.SetpointManagerWarmest(model)
            spm.setName('SAT Warmest Reset Heatpump')
            spm.setStrategy('MaximumTemperature')
            spm.setMinimumSetpointTemperature(13.0)
            spm.setMaximumSetpointTemperature(20.0)
        else:
            sat = self.sizing.get('system_supply_air_temperature', 20.0)
            spm = openstudio.model.SetpointManagerScheduled(
                model,
                schedules.constant_ruleset(model, 'Makeup-Air Unit Supply Air Temp', sat))
        spm.addToNode(air_loop.supplyOutletNode())

        # --- zones ---
        # non-HP: PTAC (cooling) + baseboards + uncontrolled diffusers (MAU ventilates)
        # ref-HP: CAV reheat terminals (reheat coil per name-encoded supplemental fuel) + baseboards
        for zone in zones:
            self.apply_zone_sizing(zone)
            if reference_hp:
                rh_coil = coils.heating_coil(model, supp_fuel, always_on, hw_loop=hw_loop)
                terminal = openstudio.model.AirTerminalSingleDuctConstantVolumeReheat(
                    model, always_on, rh_coil)
                air_loop.addBranchForZone(zone, terminal.to_StraightComponent())
            else:
                self._add_ptac(model, zone, always_on, always_off)
                diffuser = openstudio.model.AirTerminalSingleDuctUncontrolled(
                    model, always_on)
                air_loop.addBranchForZone(zone, diffuser.to_StraightComponent())
            baseboards.add(model, zone, baseboard_type=baseboard_type, hw_loop=hw_loop)

        htg_part = mau_heating_coil_type
        if reference_hp:
            if supp_fuel in ('Gas', 'NaturalGas'):
                htg_part = 'ashp>c-g'
            elif supp_fuel in ('Hot Water', 'HotWater'):
                htg_part = 'ashp>c-hw'
            else:
                htg_part = 'ashp>c-e'
        naming.apply(namer, air_loop,
                     system_name=self.config['name'],
                     sys_abbr=self.config['sys_abbr'],
                     # legacy sys1 ref-HP reads 'mixed'
                     sys_oa='mixed' if reference_hp else 'doas',
                     parts={
                         'sys_hr': 'none',
                         'sys_clg': 'ashp' if reference_hp else 'dx',
                         'sys_htg': htg_part,
                         'sys_sf': 'cv',
                         'zone_htg': baseboard_type,
                         'zone_clg': 'none' if reference_hp else 'ptac',
                         'sys_rf': 'none',
                     },
                     suffix=None)
        return [air_loop]

    def _add_ptac(self, model, zone, always_on, always_off):
        """PTAC with DX cooling (NECB curves), an always-off electric heating section
        (heating is the baseboards' job), and effectively zero outdoor air (the MAU
        ventilates). Port of NECB add_ptac_dx_cooling with zero_outdoor_air = true."""
        htg_coil = openstudio.model.CoilHeatingElectric(model, always_off)
        clg_coil = coils.dx_cooling_single_speed(
            model, always_on, name=f"{zone.nameString()} PTAC DX Clg Coil")

        fan = openstudio.model.FanOnOff(model)
        fan.setPressureRise(640)

        ptac = openstudio.model.ZoneHVACPackagedTerminalAirConditioner(
            model, always_on, fan, htg_coil, clg_coil)
        ptac.setName(f"{zone.nameString()} PTAC")
        ptac.setSupplyAirFanOperatingModeSchedule(always_off)
        ptac.setOutdoorAirFlowRateWhenNoCoolingorHeatingisNeeded(1.0e-5)
        ptac.setOutdoorAirFlowRateDuringCoolingOperation(1.0e-5)
        ptac.setOutdoorAirFlowRateDuringHeatingOperation(1.0e-5)
        ptac.addToThermalZone(zone)
