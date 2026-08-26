"""Water-source heat pumps: a condenser loop (10-35C, boiler + evaporative fluid
cooler) serving per-zone water-to-air heat pump units (equation-fit coils,
electric supplemental, cycling fan). Port of the generic model_add_hp_loop +
model_add_water_source_hp essentials. Ventilation defaults off (the CBECS WSHP
names are all DOAS composites — the DOAS part ventilates)."""

from __future__ import annotations

import openstudio

from btap._compat import sorted_by_name
from btap.modeling.hvac.components import schedules
from btap.modeling.hvac.systems.base_system import BaseSystem


class Wshp(BaseSystem):
    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        always_on = model.alwaysOnDiscreteSchedule()
        hp_loop = self._build_hp_loop(
            model, boiler_fuel=self.config.get('boiler_fuel', 'NaturalGas'))

        for zone in sorted_by_name(zones):
            self.apply_zone_sizing(zone)

            fan = openstudio.model.FanOnOff(model)
            fan.setName(f"{zone.nameString()} WSHP Fan")

            htg_coil = openstudio.model.CoilHeatingWaterToAirHeatPumpEquationFit(model)
            htg_coil.setName(f"{zone.nameString()} Water-to-Air HP Htg Coil")
            clg_coil = openstudio.model.CoilCoolingWaterToAirHeatPumpEquationFit(model)
            clg_coil.setName(f"{zone.nameString()} Water-to-Air HP Clg Coil")
            supp_coil = openstudio.model.CoilHeatingElectric(model, always_on)
            supp_coil.setName(f"{zone.nameString()} Supplemental Htg Coil")

            wshp = openstudio.model.ZoneHVACWaterToAirHeatPump(
                model, always_on, fan, htg_coil, clg_coil, supp_coil)
            wshp.setName(f"{zone.nameString()} WSHP")
            if not self.config.get('ventilation', False):
                wshp.setOutdoorAirFlowRateDuringCoolingOperation(
                    openstudio.OptionalDouble(0.0))
                wshp.setOutdoorAirFlowRateDuringHeatingOperation(
                    openstudio.OptionalDouble(0.0))
                wshp.setOutdoorAirFlowRateWhenNoCoolingorHeatingisNeeded(
                    openstudio.OptionalDouble(0.0))
            wshp.addToThermalZone(zone)

            hp_loop.addDemandBranchForComponent(htg_coil)
            hp_loop.addDemandBranchForComponent(clg_coil)
        return []

    def _build_hp_loop(self, model, *, boiler_fuel):
        """config 'heat_rejection': 'fluid_cooler' (default), 'cooling_tower', or
        'ground' (vertical ground heat exchanger, no boiler — the GSHP variant)."""
        existing = next((pl for pl in model.getPlantLoops()
                         if pl.nameString() == 'Heat Pump Loop'), None)
        if existing is not None:
            return existing

        heat_rejection = self.config.get('heat_rejection', 'fluid_cooler')

        loop = openstudio.model.PlantLoop(model)
        loop.setName('Heat Pump Loop')
        # 10/35 C loop limits: legacy parity with model_add_hp_loop
        # (Prototype.hvac_systems.rb:794-795).
        loop.setMinimumLoopTemperature(10.0)
        loop.setMaximumLoopTemperature(35.0)
        sizing = loop.sizingPlant()
        sizing.setLoopType('Heating')
        # 30.0 C exit is NOT the legacy default (model_add_hp_loop sizes at 102.2 F =
        # 39.0 C): gem choice — sized inside the loop's own 10-35 C operating band.
        # 11.0 K deltaT IS legacy parity (the 19.8 R default, converted).
        sizing.setDesignLoopExitTemperature(30.0)
        sizing.setLoopDesignTemperatureDifference(11.0)

        pump = openstudio.model.PumpConstantSpeed(model)
        pump.setName(f"{loop.nameString()} Pump")
        pump.addToNode(loop.supplyInletNode())

        if heat_rejection != 'ground':
            boiler = openstudio.model.BoilerHotWater(model)
            boiler.setName(f"{loop.nameString()} Boiler")
            boiler.setFuelType(boiler_fuel)
            loop.addSupplyBranchForComponent(boiler)

        if heat_rejection == 'ground':
            ghx = openstudio.model.GroundHeatExchangerVertical(model)
            ghx.setName(f"{loop.nameString()} Ground HX")
            loop.addSupplyBranchForComponent(ghx)
        elif heat_rejection == 'cooling_tower':
            tower = openstudio.model.CoolingTowerSingleSpeed(model)
            tower.setName(f"{loop.nameString()} Cooling Tower")
            loop.addSupplyBranchForComponent(tower)
        else:  # fluid_cooler
            cooler = openstudio.model.EvaporativeFluidCoolerSingleSpeed(model)
            cooler.setName(f"{loop.nameString()} Fluid Cooler")
            # legacy parity: model_add_hp_loop (Prototype.hvac_systems.rb:870,
            # "Based on HighRiseApartment")
            cooler.setDesignSprayWaterFlowRate(0.002208)
            cooler.setPerformanceInputMethod('UFactorTimesAreaAndDesignWaterFlowRate')
            loop.addSupplyBranchForComponent(cooler)

        loop.addSupplyBranchForComponent(openstudio.model.PipeAdiabatic(model))
        openstudio.model.PipeAdiabatic(model).addToNode(loop.supplyOutletNode())

        # Dual-setpoint 35/10 C reuses the loop max/min above; NOT the legacy defaults
        # (model_add_hp_loop uses 87/67 F = 30.6/19.4 C) — gem choice.
        spm = openstudio.model.SetpointManagerScheduledDualSetpoint(model)
        spm.setName(f"{loop.nameString()} Scheduled Dual Setpoint")
        spm.setHighSetpointSchedule(
            schedules.constant_ruleset(model, 'HP Loop High Temp', 35.0))
        spm.setLowSetpointSchedule(
            schedules.constant_ruleset(model, 'HP Loop Low Temp', 10.0))
        spm.addToNode(loop.supplyOutletNode())
        return loop
