"""Config-driven plant loop builders (NECB setpoints ported from
openstudio-standards setup_hw_loop_with_components et al.)."""

from __future__ import annotations

import openstudio

from btap.modeling.hvac.components import schedules


def find_hot_water(model):
    """Find an existing hot-water loop (one with a boiler on the supply side), or None.

    :param model: openstudio.model.Model
    :return: openstudio.model.PlantLoop or None
    """
    return next(
        (pl for pl in model.getPlantLoops()
         if len(pl.supplyComponents(openstudio.model.BoilerHotWater.iddObjectType())) > 0),
        None)


def _district_heated(loop):
    """Is this loop heated by PURCHASED energy rather than a boiler?

    Both SDK spellings: DistrictHeating was deprecated for DistrictHeatingWater
    at 3.7.0 and older models still carry the former.
    """
    for c in loop.supplyComponents():
        if c.to_DistrictHeating().is_initialized():
            return True
        if (hasattr(c, 'to_DistrictHeatingWater')
                and c.to_DistrictHeatingWater().is_initialized()):
            return True
    return False


def hot_water(model, fuel='NaturalGas', backup_fuel=None, reuse=True, source='boiler'):
    """Build a hot-water loop: primary + secondary boiler, variable-speed pump,
    82C design exit / 16K dT, OA-reset 82C@-16C down to 60C@0C.

    :param model: openstudio.model.Model
    :param fuel: primary boiler fuel (OpenStudio Boiler fuel type keyword)
    :param backup_fuel: secondary boiler fuel (defaults to primary)
    :param reuse: return an existing boiler loop when present (default True)
    :param source: 'boiler' (default) or 'district' (DistrictHeating object
        instead of boilers — the CBECS 'district hot water' pattern)
    :return: openstudio.model.PlantLoop
    """
    if reuse:
        existing = find_hot_water(model)
        # The name fallback catches a loop that has no boiler YET. It must not
        # adopt a loop heated by a DIFFERENT SOURCE than the one asked for:
        # every loop this builder makes is named 'Hot Water Loop', district
        # ones included, so a bare name match happily hands a district loop to
        # a caller that asked for boilers.
        #
        # That is exactly how 8.4.4.6.(1)(a) ended up half-applied. The
        # reference builder tears down and rebuilds ONE GROUP AT A TIME, and
        # Teardown only drops a plant loop whose demand side is empty — so with
        # several single-zone groups the district loop still carries the other
        # groups' coils, survives, and was then re-adopted here by name. The
        # reference kept purchased heating while its energy type said gas.
        # Refusing the adoption lets the district loop drain group by group and
        # be removed by the teardown's own fixpoint.
        if existing is None:
            existing = next(
                (pl for pl in model.getPlantLoops()
                 if pl.nameString() == 'Hot Water Loop'
                 and _district_heated(pl) == (source == 'district')),
                None)
        if existing is not None:
            return existing

    if backup_fuel is None:
        backup_fuel = fuel
    hw_loop = openstudio.model.PlantLoop(model)
    hw_loop.setName('Hot Water Loop')
    sizing_plant = hw_loop.sizingPlant()
    sizing_plant.setLoopType('Heating')
    sizing_plant.setDesignLoopExitTemperature(82.0)
    sizing_plant.setLoopDesignTemperatureDifference(16.0)

    # Variable speed (legacy note: constant-speed showed run-away plant temperatures)
    pump = openstudio.model.PumpVariableSpeed(model)
    pump.addToNode(hw_loop.supplyInletNode())

    if source == 'district':
        if model.version() < openstudio.VersionString('3.7.0'):
            district = openstudio.model.DistrictHeating(model)
        else:
            district = openstudio.model.DistrictHeatingWater(model)
        district.setName('District Hot Water')
        hw_loop.addSupplyBranchForComponent(district)
    else:
        boiler1 = openstudio.model.BoilerHotWater(model)
        boiler2 = openstudio.model.BoilerHotWater(model)
        boiler1.setFuelType(fuel)
        boiler2.setFuelType(backup_fuel)
        # Names are load-bearing downstream (NECB boiler efficiency rules match on them).
        boiler1.setName('Primary Boiler')
        boiler2.setName('Secondary Boiler')
        hw_loop.addSupplyBranchForComponent(boiler1)
        hw_loop.addSupplyBranchForComponent(boiler2)

    hw_loop.addSupplyBranchForComponent(openstudio.model.PipeAdiabatic(model))
    openstudio.model.PipeAdiabatic(model).addToNode(hw_loop.supplyOutletNode())

    stpt = openstudio.model.SetpointManagerOutdoorAirReset(model)
    stpt.setControlVariable('Temperature')
    stpt.setSetpointatOutdoorLowTemperature(82.0)
    stpt.setOutdoorLowTemperature(-16.0)
    stpt.setSetpointatOutdoorHighTemperature(60.0)
    stpt.setOutdoorHighTemperature(0.0)
    stpt.addToNode(hw_loop.supplyOutletNode())

    return hw_loop


def find_chilled_water(model):
    """Find an existing chilled-water loop (one with a chiller on the supply side),
    or None."""
    return next(
        (pl for pl in model.getPlantLoops()
         if len(pl.supplyComponents(openstudio.model.ChillerElectricEIR.iddObjectType())) > 0),
        None)


def chilled_water(model, chiller_type='Scroll', reuse=True, source='water_cooled'):
    """Build a chilled-water loop (7C exit / 6K dT, variable-speed pump, primary +
    secondary water-cooled chillers, constant 7C setpoint) AND its condenser-water
    loop (29C / 6K, single-speed cooling tower 24/35/5/6 design temps, constant 29C
    setpoint), ported from NECB setup_chw_loop_with_components /
    setup_cw_loop_with_components.

    :param model: openstudio.model.Model
    :param chiller_type: 'Scroll', 'Centrifugal', 'Rotary Screw', 'Reciprocating'
        (embedded in the chiller names, which host efficiency rules key on)
    :param reuse: return an existing chiller loop when present (default True)
    :param source: 'water_cooled' (default: dual chillers + condenser loop + tower),
        'air_cooled' (single air-cooled chiller, no condenser loop), or
        'district' (DistrictCooling object — the CBECS 'district chilled water' pattern)
    :return: openstudio.model.PlantLoop (the chilled-water loop)
    """
    if reuse:
        existing = find_chilled_water(model)
        if existing is None:
            existing = next((pl for pl in model.getPlantLoops()
                             if pl.nameString() == 'Chilled Water Loop'), None)
        if existing is not None:
            return existing

    # --- chilled water ---
    chw_loop = openstudio.model.PlantLoop(model)
    chw_loop.setName('Chilled Water Loop')
    sizing_plant = chw_loop.sizingPlant()
    sizing_plant.setLoopType('Cooling')
    sizing_plant.setDesignLoopExitTemperature(7.0)
    sizing_plant.setLoopDesignTemperatureDifference(6.0)

    chw_pump = openstudio.model.PumpVariableSpeed(model)
    chw_pump.addToNode(chw_loop.supplyInletNode())

    if source == 'district':
        district = openstudio.model.DistrictCooling(model)
        district.setName('District Chilled Water')
        chw_loop.addSupplyBranchForComponent(district)
        chiller1 = chiller2 = None
    elif source == 'air_cooled':
        chiller1 = openstudio.model.ChillerElectricEIR(model)
        chiller1.setCondenserType('AirCooled')
        chiller1.setName(f"Primary Chiller AirCooled {chiller_type}".strip())
        chw_loop.addSupplyBranchForComponent(chiller1)
        chiller2 = None
    else:  # water_cooled
        chiller1 = openstudio.model.ChillerElectricEIR(model)
        chiller2 = openstudio.model.ChillerElectricEIR(model)
        chiller1.setCondenserType('WaterCooled')
        chiller2.setCondenserType('WaterCooled')
        # Names are load-bearing downstream (NECB chiller efficiency rules match on them).
        chiller1.setName(f"Primary Chiller WaterCooled {chiller_type}".strip())
        chiller2.setName(f"Secondary Chiller WaterCooled {chiller_type}".strip())
        chw_loop.addSupplyBranchForComponent(chiller1)
        chw_loop.addSupplyBranchForComponent(chiller2)
    chw_loop.addSupplyBranchForComponent(openstudio.model.PipeAdiabatic(model))
    openstudio.model.PipeAdiabatic(model).addToNode(chw_loop.supplyOutletNode())

    chw_stpt = openstudio.model.SetpointManagerScheduled(
        model, schedules.constant_ruleset(model, 'CHW Temp', 7.0))
    chw_stpt.addToNode(chw_loop.supplyOutletNode())

    if source != 'water_cooled':
        return chw_loop

    # --- condenser water ---
    cw_loop = openstudio.model.PlantLoop(model)
    cw_loop.setName('Condenser Water Loop')
    cw_sizing = cw_loop.sizingPlant()
    cw_sizing.setLoopType('Condenser')
    cw_sizing.setDesignLoopExitTemperature(29.0)
    cw_sizing.setLoopDesignTemperatureDifference(6.0)

    cw_pump = openstudio.model.PumpVariableSpeed(model)
    clg_tower = openstudio.model.CoolingTowerSingleSpeed(model)
    clg_tower.setDesignInletAirWetBulbTemperature(24.0)
    clg_tower.setDesignInletAirDryBulbTemperature(35.0)
    clg_tower.setDesignApproachTemperature(5.0)
    clg_tower.setDesignRangeTemperature(6.0)

    cw_pump.addToNode(cw_loop.supplyInletNode())
    cw_loop.addSupplyBranchForComponent(clg_tower)
    cw_loop.addSupplyBranchForComponent(openstudio.model.PipeAdiabatic(model))
    openstudio.model.PipeAdiabatic(model).addToNode(cw_loop.supplyOutletNode())
    cw_loop.addDemandBranchForComponent(chiller1)
    cw_loop.addDemandBranchForComponent(chiller2)

    cw_stpt = openstudio.model.SetpointManagerScheduled(
        model, schedules.constant_ruleset(model, 'CW Temp', 29.0))
    cw_stpt.addToNode(cw_loop.supplyOutletNode())

    return chw_loop
