"""ECM "hs14"/"hs15"/"hs16": heat-pump plant + four-pipe fan coils (port of NECB ECMS
add_ecm_hs14_cgshp_fancoils / add_ecm_hs15_cawhp_fancoils / add_ecm_hs16_...).
A DOAS (hot/chilled-water coils, or ASHP DX for hs16) ventilates; per-zone four-pipe
fan coils condition; heating and cooling plants are heat-pump-led with boiler backup:

- 'gshp' (hs14): water-to-water equation-fit heating HP (W2W HCAPF/HPOWERF curves) +
  series boilers on the HW loop; water-cooled + series air-cooled chillers on the CHW
  loop; a ground-loop heat exchanger condenser loop modeled as district heating +
  cooling in series (5C/25C setpoints), serving the HP and the water-cooled chiller.
- 'cawhp' (hs15/hs16): air-source plant-loop-EIR heating HP (60C, min -15C source,
  COP 3) + series boilers; companion plant-loop-EIR cooling HP (7C/6K); the four
  CAWHP performance biquadratics are part of the equipment definition (curves.json).

Deviations from legacy (documented): the legacy 'AirSoure' typo (a silently failing
setCondenserType on the heating HP), since fixed upstream by #2119 — the gem always
wrote 'AirSource'. Live deviation: legacy hs14's destructive
`model.getOutputVariables.each(&:remove)` is NOT replicated (the two
district-rate output variables are still added) — this was NOT fixed upstream."""

from __future__ import annotations

import openstudio

from btap._compat import sorted_by_name
from btap.modeling.hvac import naming
from btap.modeling.hvac.components import curves as curves_mod
from btap.modeling.hvac.components import ecm_air
from btap.modeling.hvac.systems.base_system import BaseSystem


class HpPlantFanCoils(BaseSystem):
    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        plant_type = self.config.get('plant_type', 'cawhp')
        # 'hydronic' (coil_hw/chw) or 'ashp' (hs16)
        air_eqpt = self.config.get('air_eqpt', 'hydronic')
        supp = self.config.get('supp_htg_fuel', 'None')

        # --- DOAS + zone fan coils (coils intentionally unattached until plants exist) ---
        air_loop = ecm_air.assemble(
            model, zones,
            htg_type='ashp' if air_eqpt == 'ashp' else 'coil_hw',
            clg_type='ashp' if air_eqpt == 'ashp' else 'coil_chw',
            supp_htg_type=('none' if supp == 'None'
                           else ('coil_gas' if supp == 'Gas' else 'coil_electric')),
            spm_type='warmest',
            supply_fan_type='constant_volume')[0]
        self.apply_system_sizing(air_loop)

        for zone in sorted_by_name(zones):
            self.apply_zone_sizing(zone)
            ecm_air.add_diffuser(model, air_loop, zone, 'single_duct_uncontrolled')
            ecm_air.add_zone_fancoil(model, zone)

        boiler_fuels = [self.config.get('boiler_fuel', 'Electricity')]

        # --- heating plant ---
        hp_hw_loop, hw_hp = self._build_hw_plant(model, plant_type, boiler_fuels)
        for c in sorted_by_name(model.getCoilHeatingWaters()):
            hp_hw_loop.addDemandBranchForComponent(c)

        # --- cooling plant ---
        hp_chw_loop, chw_eqpt = self._build_chw_plant(model, plant_type, hw_hp)
        for c in sorted_by_name(model.getCoilCoolingWaters()):
            hp_chw_loop.addDemandBranchForComponent(c)

        # --- ground loop (hs14 only) ---
        if plant_type == 'gshp':
            self._build_glhx_loop(model, hw_hp, chw_eqpt)

        naming.apply(namer, air_loop,
                     system_name=self.config['name'],
                     sys_abbr=self.config.get('sys_abbr', 'sys_1'),
                     sys_oa='doas',
                     parts={
                         'sys_hr': 'none',
                         'sys_clg': 'ashp' if air_eqpt == 'ashp' else 'coil_chw',
                         'sys_htg': 'ashp' if air_eqpt == 'ashp' else 'coil_hw',
                         'sys_sf': 'cv',
                         'zone_htg': 'fancoil_4pipe',
                         'zone_clg': 'fancoil_4pipe',
                         'sys_rf': 'none',
                     },
                     suffix=None)
        return [air_loop]

    def _base_plant_loop(self, model, name, loop_type, setpoint, temp_diff):
        loop = openstudio.model.PlantLoop(model)
        loop.setName(name)
        loop.sizingPlant().setLoopType(loop_type)
        if setpoint is not None:
            loop.sizingPlant().setDesignLoopExitTemperature(setpoint)
        if temp_diff is not None:
            loop.sizingPlant().setLoopDesignTemperatureDifference(temp_diff)
        pump = openstudio.model.PumpVariableSpeed(model)
        pump.setName('PumpVariableSpeed')
        pump.addToNode(loop.supplyInletNode())
        return loop

    def _finish_plant_loop(self, model, loop, eqpt, setpoint):
        loop.addSupplyBranchForComponent(eqpt)
        loop.addSupplyBranchForComponent(openstudio.model.PipeAdiabatic(model))
        openstudio.model.PipeAdiabatic(model).addToNode(loop.supplyOutletNode())
        if setpoint is None:
            return

        sch = openstudio.model.ScheduleConstant(model)
        sch.setValue(setpoint)
        spm = openstudio.model.SetpointManagerScheduled(model, sch)
        spm.setName('SetpointManagerScheduled')
        spm.addToNode(loop.supplyOutletNode())

    def _add_series_boilers(self, model, hp_outlet_node, fuels):
        boilers = []
        for fuel in fuels:
            boiler = openstudio.model.BoilerHotWater(model)
            boiler.setFuelType(fuel)
            boilers.append(boiler)
        for b in reversed(boilers):
            b.addToNode(hp_outlet_node)
        return boilers

    def _build_hw_plant(self, model, plant_type, boiler_fuels):
        # 60.0 C setpoint / 5.0 K deltaT: legacy parity — hs14 add_plantloop args
        # (ECMS/hvac_systems.rb:1834-1835) and hs15 (:2146-2147).
        loop = self._base_plant_loop(model, 'HW PlantLoop', 'Heating', 60.0, 5.0)
        if plant_type == 'gshp':
            hp = openstudio.model.HeatPumpWaterToWaterEquationFitHeating(model)
            hp.setName('HeatPumpWaterToWaterEquationFitHeating')
            hp.setHeatingCapacityCurve(
                curves_mod.build(model, 'HEATPUMP_WATERTOWATER_HCAPF'))
            hp.setHeatingCompressorPowerCurve(
                curves_mod.build(model, 'HEATPUMP_WATERTOWATER_HPOWERF'))
        else:
            # Heating-HP settings: legacy parity with add_ecm_hs15_cawhp_fancoils
            # (ECMS/hvac_systems.rb:2149-2156) — min source inlet -15.0 C (:2150,
            # air-source low-ambient cutoff), reference COP 3.0 (:2151),
            # min PLR 0.2 (:2156). The legacy source carries the values bare.
            hp = openstudio.model.HeatPumpPlantLoopEIRHeating(model)
            hp.setName('HeatPumpPlantLoopEIRHeating')
            # legacy 'AirSoure' typo corrected (also fixed upstream by #2119)
            hp.setCondenserType('AirSource')
            hp.setMinimumSourceInletTemperature(-15.0)
            hp.setReferenceCoefficientofPerformance(3.0)
            hp.setHeatPumpSizingMethod('CoolingCapacity')
            hp.setHeatPumpDefrostControl('OnDemand')
            hp.setFlowMode('VariableSpeedPumping')
            hp.setControlType('Setpoint')
            hp.setMinimumPartLoadRatio(0.2)
            hp.setCapacityModifierFunctionofTemperatureCurve(
                curves_mod.build(model, 'CAWHP-HS15-HCAPFT'))
            hp.setElectricInputtoOutputRatioModifierFunctionofTemperatureCurve(
                curves_mod.build(model, 'CAWHP-HS15-HEIRFT'))
            loop.setLoadDistributionScheme('SequentialLoad')
        self._finish_plant_loop(model, loop, hp, 60.0)

        hp_outlet = hp.supplyOutletModelObject().get().to_Node().get()
        self._add_series_boilers(model, hp_outlet, boiler_fuels)
        if plant_type != 'gshp':
            # 60.0 C SPM at the HP outlet: legacy parity, hs15 (ECMS/hvac_systems.rb:2173-2177).
            sch = openstudio.model.ScheduleConstant(model)
            sch.setValue(60.0)
            spm = openstudio.model.SetpointManagerScheduled(model, sch)
            spm.setName('HeatPumpHtgSetpointManager')
            spm.addToNode(hp_outlet)
        return [loop, hp]

    def _build_chw_plant(self, model, plant_type, hw_hp):
        # 7.0 C setpoint / 6.0 K deltaT: legacy parity — hs14 add_plantloop args
        # (ECMS/hvac_systems.rb:1871-1872) and hs15 (:2185-2186).
        loop = self._base_plant_loop(model, 'CHW PlantLoop', 'Cooling', 7.0, 6.0)
        if plant_type == 'gshp':
            chiller = openstudio.model.ChillerElectricEIR(model)
            chiller.setName('ChillerWaterCooled')
            chiller.setCondenserType('WaterCooled')
            self._finish_plant_loop(model, loop, chiller, 7.0)
            sec = openstudio.model.ChillerElectricEIR(model)
            sec.addToNode(chiller.supplyOutletModelObject().get().to_Node().get())
            sec.setName('ChillerAirCooled')
            return [loop, chiller]

        # Cooling-HP settings: legacy parity with add_ecm_hs15_cawhp_fancoils
        # (ECMS/hvac_systems.rb:2188-2193) — reference COP 3.0 (:2190),
        # min PLR 0.2 (:2193).
        hp = openstudio.model.HeatPumpPlantLoopEIRCooling(model)
        hp.setName('HeatPumpPlantLoopEIRCooling')
        hp.setCondenserType('AirSource')
        hp.setReferenceCoefficientofPerformance(3.0)
        hp.setFlowMode('VariableSpeedPumping')
        hp.setControlType('Load')
        hp.setMinimumPartLoadRatio(0.2)
        hp.setCapacityModifierFunctionofTemperatureCurve(
            curves_mod.build(model, 'CAWHP-HS15-CCAPFT'))
        hp.setElectricInputtoOutputRatioModifierFunctionofTemperatureCurve(
            curves_mod.build(model, 'CAWHP-HS15-CEIRFT'))
        hw_hp.setCompanionCoolingHeatPump(hp)
        self._finish_plant_loop(model, loop, hp, 7.0)
        return [loop, hp]

    def _build_glhx_loop(self, model, hw_hp, chiller):
        """Ground-loop heat exchanger modeled as district heating + cooling in series
        (the legacy hs14 GLHX pattern), serving the W2W HP and the water-cooled
        chiller."""
        # 10.0 K condenser deltaT: legacy parity — hs14 GLHX add_plantloop arg
        # (ECMS/hvac_systems.rb:1890).
        loop = self._base_plant_loop(model, 'Condenser PlantLoop GLHX', 'Condenser',
                                     None, 10.0)
        if model.version() < openstudio.VersionString('3.7.0'):
            district_htg = openstudio.model.DistrictHeating(model)
        else:
            district_htg = openstudio.model.DistrictHeatingWater(model)
        district_htg.setName('DistrictHeating GLHX')
        loop.addSupplyBranchForComponent(district_htg)
        loop.addSupplyBranchForComponent(openstudio.model.PipeAdiabatic(model))
        openstudio.model.PipeAdiabatic(model).addToNode(loop.supplyOutletNode())

        htg_outlet = district_htg.outletModelObject().get().to_Node().get()
        district_clg = openstudio.model.DistrictCooling(model)
        district_clg.setName('DistrictCooling GLHX')
        district_clg.addToNode(htg_outlet)

        # 5.0 C heating-side / 25.0 C cooling-side setpoints (the ground-loop supply-temp
        # proxy band): legacy parity — hs14 (ECMS/hvac_systems.rb:1896 and :1899).
        htg_sch = openstudio.model.ScheduleConstant(model)
        htg_sch.setValue(5.0)
        openstudio.model.SetpointManagerScheduled(model, htg_sch).addToNode(htg_outlet)
        clg_sch = openstudio.model.ScheduleConstant(model)
        clg_sch.setValue(25.0)
        openstudio.model.SetpointManagerScheduled(model, clg_sch).addToNode(
            loop.supplyOutletNode())

        loop.addDemandBranchForComponent(hw_hp)
        loop.addDemandBranchForComponent(chiller)

        # District-rate reporting used downstream for GLHX sizing (legacy also removes ALL
        # pre-existing output variables; that destructive step is deliberately not ported).
        for var in ('District Heating Water Rate', 'District Cooling Water Rate'):
            ov = openstudio.model.OutputVariable(var, model)
            ov.setReportingFrequency('hourly')
            ov.setKeyValue('*')
        return loop
