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

    # 1. Zone equipment on the given zones (baseboards, PTAC/PTHP, fan coils, VRF
    #    terminals...). Exhaust fans are preserved (they represent code-required
    #    exhaust, not the system).
    for zone in zones:
        for equipment in zone.equipment():
            if equipment.to_FanZoneExhaust().is_initialized():
                continue

            equipment.remove()

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
        for coil in (list(model.getCoilCoolingWaters()) + list(model.getCoilHeatingWaters())):
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

    return model
