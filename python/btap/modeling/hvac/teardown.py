"""Zone-scoped HVAC removal: clear the given zones so a new system replaces (rather
than stacks on top of) whatever served them, leaving other zones' systems untouched.
Ported from the openstudio-standards remove_hvac_from_zones work, including the
fixpoint that handles water-cooled chiller -> condenser-loop chains."""

from __future__ import annotations


def remove_hvac_from_zones(model, zones):
    """:param model: openstudio.model.Model
    :param zones: list of openstudio.model.ThermalZone to clear of HVAC
    :return: the model"""
    zone_handles = [str(zone.handle()) for zone in zones]

    from btap.modeling.hvac.systems import plant_loops, vav_reheat

    for plant_loop in model.getPlantLoops():
        plant_loops.remove_zones_from_dewpoint_reset(plant_loop, zones)

    # 1. Zone equipment on the given zones (baseboards, PTAC/PTHP, fan coils, VRF
    #    terminals...). Exhaust fans are preserved (they represent code-required
    #    exhaust, not the system).
    #
    # Preserving the OBJECT is not enough, and this is issue #201. Removing a
    # zone component that occupies an exhaust port — a unit heater, a fan coil,
    # anything drawing zone air — can clear the zone's ENTIRE exhaust
    # `PortList`, taking the preserved fan's port with it. The fan then keeps
    # an inlet-node reference the zone no longer registers, and EnergyPlus
    # reports "Node Connection Error, Inlet node did not find an appropriate
    # matching outlet node" for every one of them.
    #
    # Measured on `gagetown_coldlake_Office_pre-1960.osm`: five of its seven
    # exhaust fans, in exactly the five zones whose other equipment is a
    # `ZoneHVAC:UnitHeater`. The two zones with baseboards are unaffected,
    # because a baseboard has no air inlet and so never occupies a port. The
    # five became five extra EnergyPlus Severes in any model generated from
    # that archetype's recipe.
    #
    # Isolated to `ZoneHVACComponent::removeFromThermalZone()` — `remove()`
    # calls it, and calling it alone reproduces the wipe. It is upstream SDK
    # behaviour that nine probes could not reproduce on a hand-built zone
    # (single and multi zone, electric and hydronic coils, both add orders,
    # with and without an air loop, and through a save/VersionTranslator round
    # trip), so the remaining trigger lives somewhere in the real model's
    # object graph. What matters here is that THIS function's documented
    # contract is "exhaust fans are preserved", so this function is the right
    # place to make that true rather than leave callers to discover it.
    preserved = []
    for zone in zones:
        for equipment in zone.equipment():
            fan = equipment.to_FanZoneExhaust()
            if fan.is_initialized():
                preserved.append((zone, fan.get()))

    for zone in zones:
        for equipment in zone.equipment():
            if equipment.to_FanZoneExhaust().is_initialized():
                continue

            equipment.remove()

    # Re-assert the preserved fans. `addToThermalZone` is a no-op when the port
    # is still registered, so a zone that kept its ports pays nothing; only a
    # fan whose port was dropped is re-attached, and re-attaching carries the
    # fan's own fields (efficiency, pressure rise, schedules) unchanged because
    # only the connection is rebuilt.
    for zone, fan in preserved:
        registered = {
            node.nameString()
            for node in zone.exhaustPortList().modelObjects()
        }
        inlet = fan.inletNode()
        if inlet.is_initialized() and inlet.get().nameString() in registered:
            continue
        fan.removeFromThermalZone()
        fan.addToThermalZone(zone)

    # 2. Air loops serving the given zones: remove entirely if they serve only these
    #    zones, otherwise detach just the given zones from the shared loop.
    for air_loop in model.getAirLoopHVACs():
        served = air_loop.thermalZones()
        if not any(str(z.handle()) in zone_handles for z in served):
            continue

        if all(str(z.handle()) in zone_handles for z in served):
            air_loop.remove()
        else:
            for z in served:
                if str(z.handle()) in zone_handles:
                    air_loop.removeBranchForZone(z)

    # 3. Remove plant loops orphaned by the above (no demand-side equipment left),
    #    keeping service-hot-water loops. Iterate to a fixpoint: a water-cooled
    #    chiller straddles its chilled-water loop (supply) and condenser loop
    #    (demand), so removing the chilled-water loop only strands the chiller;
    #    removing the stranded chiller then frees the condenser loop on the next pass.
    while True:
        changed = False

        for plant_loop in model.getPlantLoops():
            shw_use = any(
                component.to_WaterUseConnections().is_initialized()
                or component.to_CoilWaterHeatingDesuperheater().is_initialized()
                for component in plant_loop.demandComponents())
            if shw_use:
                continue

            demand_equipment = [
                component for component in plant_loop.demandComponents()
                if not (component.to_Node().is_initialized()
                        or component.to_ConnectorMixer().is_initialized()
                        or component.to_ConnectorSplitter().is_initialized()
                        or component.to_PipeAdiabatic().is_initialized()
                        or component.to_PipeIndoor().is_initialized()
                        or component.to_PipeOutdoor().is_initialized())]
            if demand_equipment:
                continue

            plant_loop.remove()
            changed = True

        for chiller in model.getChillerElectricEIRs():
            if chiller.plantLoop().is_initialized():
                continue

            chiller.remove()
            changed = True

        # Water coils stranded by an air-loop removal stay attached as plant demand
        # components; remove them so their loop can empty on the next pass.
        water_coils = (
            list(model.getCoilCoolingWaters())
            + list(model.getCoilHeatingWaters())
            + list(model.getCoilCoolingCooledBeams())
            + list(model.getCoilHeatingLowTempRadiantVarFlows())
            + list(model.getCoilCoolingLowTempRadiantVarFlows()))
        for coil in water_coils:
            if coil.airLoopHVAC().is_initialized():
                continue
            if coil.containingHVACComponent().is_initialized():
                continue
            if coil.containingZoneHVACComponent().is_initialized():
                continue

            coil.remove()
            changed = True

        if not changed:
            break

    # 4. Remove now-unused performance curves.
    for curve in model.getCurves():
        if curve.directUseCount() == 0:
            model.removeObject(curve.handle())

    used_independent_variables = {
        str(variable.handle())
        for table in model.getTableLookups()
        for variable in table.independentVariables()
    }
    for variable in list(model.getTableIndependentVariables()):
        source = variable.additionalProperties().getFeatureAsString(
            vav_reheat.ENERGY_RECOVERY_SOURCE_FEATURE)
        if (source.is_initialized()
                and source.get() == vav_reheat.ENERGY_RECOVERY_SOURCE_CATALOG
                and str(variable.handle()) not in used_independent_variables):
            variable.remove()

    return model
