"""Per-zone forced-air furnace / central AC (port of the generic
model_add_furnace_central_ac essentials): one CV air loop per zone with a gas
heating coil (config 'heating': true) and/or single-speed DX cooling
(config 'cooling': true); outdoor air per config 'ventilation'."""

from __future__ import annotations

import openstudio

from btap._compat import sorted_by_name
from btap.modeling.hvac.systems.base_system import BaseSystem


class Furnace(BaseSystem):
    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        always_on = model.alwaysOnDiscreteSchedule()
        heating = self.config.get('heating', True)
        cooling = self.config.get('cooling', False)
        ventilation = self.config.get('ventilation', True)

        air_loops = []
        for zone in sorted_by_name(zones):
            air_loop = openstudio.model.AirLoopHVAC(model)
            air_loop.setName(f"{self.config['name']} | {zone.nameString()}")

            fan = openstudio.model.FanConstantVolume(model, always_on)
            fan.setName(f"{air_loop.nameString()} Fan")

            supply_inlet_node = air_loop.supplyInletNode()
            fan.addToNode(supply_inlet_node)
            if heating:
                htg = openstudio.model.CoilHeatingGas(model, always_on)
                htg.setName(f"{air_loop.nameString()} Heating Coil")
                htg.addToNode(supply_inlet_node)
            if cooling:
                clg = openstudio.model.CoilCoolingDXSingleSpeed(model)
                clg.setName(f"{air_loop.nameString()} Cooling Coil")
                clg.addToNode(supply_inlet_node)
            if ventilation:
                self.build_oa_system(model).addToNode(supply_inlet_node)

            spm = openstudio.model.SetpointManagerSingleZoneReheat(model)
            spm.setControlZone(zone)
            spm.addToNode(air_loop.supplyOutletNode())

            diffuser = openstudio.model.AirTerminalSingleDuctUncontrolled(model, always_on)
            air_loop.addBranchForZone(zone, diffuser.to_StraightComponent())
            air_loops.append(air_loop)
        return air_loops
