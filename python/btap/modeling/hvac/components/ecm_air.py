"""Shared machinery for the NECB ECM air systems (port of the ECMS create_airloop /
create_air_sys_* / create_zone_* creators). Topology only: ECM performance curves and
COPs are the host efficiency pass's job."""

from __future__ import annotations

import openstudio

from btap.modeling.hvac.components import curves as curves_mod
from btap.modeling.hvac.components import schedules

# --- air-loop-side equipment -------------------------------------------------------


def air_cooling_eqpt(model, type_):
    if type_ == 'ashp':
        coil = openstudio.model.CoilCoolingDXSingleSpeed(model)
        coil.setName('CoilCoolingDxSingleSpeed_ASHP')
        # 1.0e-6 ~ zero: legacy-parity near-zero (E+ rejects or special-cases a hard 0 on
        # these fields); used throughout this file.
        coil.setCrankcaseHeaterCapacity(1.0e-6)
        return coil
    if type_ == 'ccashp':
        coil = openstudio.model.CoilCoolingDXVariableSpeed(model)
        coil.setName('CoilCoolingDXVariableSpeed_CCASHP')
        coil.addSpeed(openstudio.model.CoilCoolingDXVariableSpeedSpeedData(model))
        coil.setNominalSpeedLevel(1)
        coil.setCrankcaseHeaterCapacity(1.0e-6)
        return coil
    if type_ == 'coil_chw':
        coil = openstudio.model.CoilCoolingWater(model)
        coil.setName('CoilCoolingWater')
        return coil   # unattached; caller sweeps it onto the CHW plant once built
    raise ValueError(f"unknown ECM air cooling equipment '{type_}'")


def air_heating_eqpt(model, type_, hw_loop=None):
    always_on = model.alwaysOnDiscreteSchedule()
    if type_ == 'ashp':
        coil = openstudio.model.CoilHeatingDXSingleSpeed(model)
        coil.setName('CoilHeatingDXSingleSpeed_ASHP')
        coil.setDefrostStrategy('ReverseCycle')
        coil.setDefrostControl('OnDemand')
        # REQUIRED once the strategy is ReverseCycle — see curves.defrost_eir_ft
        coil.setDefrostEnergyInputRatioFunctionofTemperatureCurve(
            curves_mod.defrost_eir_ft(model))
        coil.setCrankcaseHeaterCapacity(1.0e-6)
        return coil
    if type_ == 'ccashp':
        coil = openstudio.model.CoilHeatingDXVariableSpeed(model)
        coil.setName('CoilHeatingDXVariableSpeed_CCASHP')
        coil.addSpeed(openstudio.model.CoilHeatingDXVariableSpeedSpeedData(model))
        coil.setNominalSpeedLevel(1)
        coil.setMinimumOutdoorDryBulbTemperatureforCompressorOperation(-25.0)
        coil.setDefrostStrategy('ReverseCycle')
        coil.setDefrostControl('OnDemand')
        coil.setDefrostEnergyInputRatioFunctionofTemperatureCurve(
            curves_mod.defrost_eir_ft(model))
        coil.setCrankcaseHeaterCapacity(1.0e-6)
        return coil
    if type_ in ('coil_electric', 'Electric'):
        coil = openstudio.model.CoilHeatingElectric(model, always_on)
        coil.setName('CoilHeatingElectric')
        return coil
    if type_ in ('coil_gas', 'Gas'):
        coil = openstudio.model.CoilHeatingGas(model, always_on)
        coil.setName('CoilHeatingGas')
        return coil
    if type_ in ('coil_hw', 'Hot Water'):
        coil = openstudio.model.CoilHeatingWater(model)
        coil.setName('CoilHeatingWater')
        if hw_loop is not None:
            hw_loop.addDemandBranchForComponent(coil)
        return coil
    if type_ in ('none', None):
        return None
    raise ValueError(f"unknown ECM air heating equipment '{type_}'")


def assemble(model, zones, *, air_eqpt=None, htg_type=None, clg_type=None,
             supp_htg_type='none', spm_type, supply_fan_type,
             return_fan=False, hw_loop=None):
    """Assemble an ECM air loop: components added at the supply outlet in the legacy
    order (clg, htg, supp, fan, spm), OA system (ZoneSum) at the inlet, optional VV
    return fan on the return-air node.

    :param spm_type: 'scheduled' (20C), 'single_zone_reheat' (13/43), 'warmest' (13/22)
    :param supply_fan_type: 'constant_volume' or 'variable_volume'
    :return: [air_loop, clg_coil, htg_coil, return_fan]
    """
    air_loop = openstudio.model.AirLoopHVAC(model)

    clg_coil = air_cooling_eqpt(model, clg_type if clg_type is not None else air_eqpt)
    htg_coil = air_heating_eqpt(model, htg_type if htg_type is not None else air_eqpt)
    supp_coil = air_heating_eqpt(model, supp_htg_type, hw_loop=hw_loop)

    fan = (openstudio.model.FanVariableVolume(model)
           if supply_fan_type == 'variable_volume'
           else openstudio.model.FanConstantVolume(model))
    fan.setName('Supply Fan')   # 'Supply' substring is load-bearing for host fan rules

    clg_coil.addToNode(air_loop.supplyOutletNode())
    htg_coil.addToNode(air_loop.supplyOutletNode())
    if supp_coil is not None:
        supp_coil.addToNode(air_loop.supplyOutletNode())
    fan.addToNode(air_loop.supplyOutletNode())

    # Setpoint temps are legacy parity with ECMS create_air_sys_spm
    # (necb/ECMS/hvac_systems.rb:674-696): 'scheduled' = constant 20.0 C neutral DOAS
    # supply; 'single_zone_reheat' = 13.0 C min / 43.0 C max supply (43 C is the NECB
    # warm-air heating design supply temperature, cf. add_zone_eqpt's 43.0 C zone
    # heating design supply at hvac_systems.rb:991); 'warmest' = 13.0/22.0 C band.
    spm = None
    if spm_type == 'scheduled':
        spm = openstudio.model.SetpointManagerScheduled(
            model, schedules.constant_ruleset(model, 'DOAS Supply Air Temp', 20.0))
    elif spm_type == 'single_zone_reheat':
        spm = openstudio.model.SetpointManagerSingleZoneReheat(model)
        spm.setControlZone(zones[0])
        spm.setMinimumSupplyAirTemperature(13.0)
        spm.setMaximumSupplyAirTemperature(43.0)
    elif spm_type == 'warmest':
        spm = openstudio.model.SetpointManagerWarmest(model)
        spm.setMinimumSetpointTemperature(13.0)
        spm.setMaximumSetpointTemperature(22.0)
    spm.addToNode(air_loop.supplyOutletNode())

    oa_controller = openstudio.model.ControllerOutdoorAir(model)
    oa_controller.autosizeMinimumOutdoorAirFlowRate()
    oa_controller.controllerMechanicalVentilation().setSystemOutdoorAirMethod('ZoneSum')
    openstudio.model.AirLoopHVACOutdoorAirSystem(model, oa_controller).addToNode(
        air_loop.supplyInletNode())

    rfan = None
    if return_fan:
        rfan = openstudio.model.FanVariableVolume(model)
        rfan.setName('Return Fan')
        rfan.addToNode(air_loop.returnAirNode().get())

    return [air_loop, clg_coil, htg_coil, rfan]


# --- zone-side equipment -----------------------------------------------------------


def add_diffuser(model, air_loop, zone, type_):
    always_on = model.alwaysOnDiscreteSchedule()
    diffuser = None
    if type_ == 'single_duct_uncontrolled':
        diffuser = openstudio.model.AirTerminalSingleDuctUncontrolled(model, always_on)
    elif type_ == 'single_duct_vav_reheat':
        reheat = openstudio.model.CoilHeatingElectric(model, always_on)
        diffuser = openstudio.model.AirTerminalSingleDuctVAVReheat(model, always_on, reheat)
        # legacy parity: ECMS create_zone_diffuser (hvac_systems.rb:850)
        diffuser.setMaximumReheatAirTemperature(43.0)
        diffuser.setDamperHeatingAction('Normal')
    air_loop.addBranchForZone(zone, diffuser.to_StraightComponent())
    return diffuser


def add_zone_ptac_electric_off(model, zone):
    """PTAC with DX cooling and an always-off electric heating section (~zero OA) —
    the ECM 'ptac_electric_off' zone cooling unit."""
    always_on = model.alwaysOnDiscreteSchedule()
    always_off = model.alwaysOffDiscreteSchedule()
    htg = openstudio.model.CoilHeatingElectric(model, always_on)
    htg.setName('CoilHeatingElectric')
    htg.setAvailabilitySchedule(always_off)
    clg = openstudio.model.CoilCoolingDXSingleSpeed(model)
    clg.setName('CoilCoolingDXSingleSpeed_PTAC')
    clg.setCrankcaseHeaterCapacity(1.0e-6)
    fan = openstudio.model.FanOnOff(model)
    fan.setName('FanOnOff')
    ptac = openstudio.model.ZoneHVACPackagedTerminalAirConditioner(
        model, always_on, fan, htg, clg)
    ptac.setName('ZoneHVACPackagedTerminalAirConditioner')
    ptac.setSupplyAirFanOperatingModeSchedule(always_off)
    ptac.setOutdoorAirFlowRateDuringCoolingOperation(1.0e-6)
    ptac.setOutdoorAirFlowRateDuringHeatingOperation(1.0e-6)
    ptac.setOutdoorAirFlowRateWhenNoCoolingorHeatingisNeeded(1.0e-6)
    ptac.addToThermalZone(zone)
    return ptac


def add_zone_fancoil(model, zone):
    """Four-pipe fan coil with unattached hot/chilled-water coils (~zero OA, always-off
    fan operating schedule) — the ECM 'fancoil_4pipe' zone unit. The caller attaches the
    coils to plant loops afterwards (the legacy flow sweeps all CoilHeating/CoolingWaters
    onto the HP plant loops once they exist)."""
    always_on = model.alwaysOnDiscreteSchedule()
    always_off = model.alwaysOffDiscreteSchedule()
    htg = openstudio.model.CoilHeatingWater(model)
    htg.setName('CoilHeatingWater_FanCoil')
    clg = openstudio.model.CoilCoolingWater(model)
    clg.setName('CoilCoolingWater_FanCoil')
    fan = openstudio.model.FanOnOff(model)
    fan.setName('FanOnOff')
    fc = openstudio.model.ZoneHVACFourPipeFanCoil(model, always_on, fan, clg, htg)
    fc.setName('ZoneHVACFourPipeFanCoil')
    fc.setSupplyAirFanOperatingModeSchedule(always_off)
    fc.setMaximumOutdoorAirFlowRate(1.0e-6)
    fc.addToThermalZone(zone)
    return fc


def add_zone_vrf_terminal(model, zone, outdoor_unit):
    """VRF terminal unit attached to an outdoor VRF unit."""
    always_off = model.alwaysOffDiscreteSchedule()
    clg = openstudio.model.CoilCoolingDXVariableRefrigerantFlow(model)
    clg.setName('CoilCoolingDXVariableRefrigerantFlow')
    htg = openstudio.model.CoilHeatingDXVariableRefrigerantFlow(model)
    htg.setName('CoilHeatingDXVariableRefrigerantFlow')
    fan = openstudio.model.FanOnOff(model)
    fan.setName('FanOnOff')
    terminal = openstudio.model.ZoneHVACTerminalUnitVariableRefrigerantFlow(
        model, clg, htg, fan)
    terminal.setName('ZoneHVACTerminalUnitVariableRefrigerantFlow')
    terminal.setSupplyAirFanOperatingModeSchedule(always_off)
    terminal.setOutdoorAirFlowRateDuringCoolingOperation(1.0e-6)
    terminal.setOutdoorAirFlowRateDuringHeatingOperation(1.0e-6)
    terminal.setOutdoorAirFlowRateWhenNoCoolingorHeatingisNeeded(1.0e-6)
    terminal.setZoneTerminalUnitOffParasiticElectricEnergyUse(1.0e-6)
    terminal.setZoneTerminalUnitOnParasiticElectricEnergyUse(1.0e-6)
    terminal.addToThermalZone(zone)
    outdoor_unit.addTerminal(terminal)
    return terminal


def add_outdoor_vrf_unit(model, condenser_type='AirCooled'):
    """Outdoor VRF unit with the ECM hs08 settings (port of add_outdoor_vrf_unit, minus
    the defrost-EIR curve lookup — curve application is the host efficiency pass's job).

    SOURCE: every numeric below is verbatim legacy parity with ECMS add_outdoor_vrf_unit
    (necb/ECMS/hvac_systems.rb:266-314, verified 2026-08). The legacy source carries the
    values bare (no derivation given there either); the ECM models a
    'Mitsubishi_Hyper_Heating_VRF_Outdoor_Unit', so the odd-looking constants are
    manufacturer-flavoured performance settings."""
    unit = openstudio.model.AirConditionerVariableRefrigerantFlow(model)
    unit.setName('VRF Outdoor Unit')
    unit.setHeatPumpWasteHeatRecovery(True)
    unit.setRatedHeatingCOP(4.0)          # legacy hvac_systems.rb:272
    unit.setGrossRatedCoolingCOP(4.0)     # legacy hvac_systems.rb:276
    unit.setMinimumOutdoorTemperatureinHeatingMode(-25.0)   # cold-climate cutoff, legacy :278
    unit.setHeatingPerformanceCurveOutdoorTemperatureType('WetBulbTemperature')
    unit.setMasterThermostatPriorityControlType('ThermostatOffsetPriority')
    unit.setDefrostControl('OnDemand')
    unit.setDefrostStrategy('ReverseCycle')
    # REQUIRED once the strategy is ReverseCycle — see curves.defrost_eir_ft
    unit.setDefrostEnergyInputRatioModifierFunctionofTemperatureCurve(
        curves_mod.defrost_eir_ft(model))
    unit.autosizeResistiveDefrostHeaterCapacity()
    # -0.00019231 piping height correction: legacy verbatim (:284-285), no derivation
    # given in the legacy source (~ -1/5200 per metre of height).
    unit.setPipingCorrectionFactorforHeightinHeatingModeCoefficient(-0.00019231)
    unit.setPipingCorrectionFactorforHeightinCoolingModeCoefficient(-0.00019231)
    unit.setMinimumOutdoorTemperatureinHeatRecoveryMode(-5.0)   # legacy :286
    unit.setMaximumOutdoorTemperatureinHeatRecoveryMode(26.2)   # legacy verbatim :287, no derivation given there
    # Heat-recovery startup fractions/time constants: legacy verbatim :288-294.
    unit.setInitialHeatRecoveryCoolingCapacityFraction(0.5)
    unit.setHeatRecoveryCoolingCapacityTimeConstant(0.15)
    unit.setInitialHeatRecoveryCoolingEnergyFraction(1.0)
    unit.setHeatRecoveryCoolingEnergyTimeConstant(0.0)
    unit.setInitialHeatRecoveryHeatingCapacityFraction(1.0)
    unit.setHeatRecoveryHeatingCapacityTimeConstant(0.15)
    unit.setInitialHeatRecoveryHeatingEnergyFraction(1.0)
    unit.setMinimumHeatPumpPartLoadRatio(0.5)   # legacy :296
    unit.setCondenserType(condenser_type)
    unit.setCrankcaseHeaterPowerperCompressor(1.0e-6)
    unit.setMinimumOutdoorTemperatureinCoolingMode(-10)   # legacy :299
    return unit
