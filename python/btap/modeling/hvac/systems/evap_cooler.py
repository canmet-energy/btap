"""Per-zone direct evaporative coolers (port of the generic model_add_evap_cooler
essentials): one air loop per zone with a direct research-special evaporative
cooler and a supply-air setpoint that follows outdoor wet-bulb. The legacy EMS
availability program (cooling-load-driven on/off) is NOT replicated — documented
simplification; the follow-OAT setpoint still governs operation."""

from __future__ import annotations

import openstudio

from btap._compat import sorted_by_name
from btap.modeling.hvac.systems.base_system import BaseSystem


class EvapCooler(BaseSystem):
    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        always_on = model.alwaysOnDiscreteSchedule()
        air_loops = []
        for zone in sorted_by_name(zones):
            air_loop = openstudio.model.AirLoopHVAC(model)
            air_loop.setName(f"{self.config['name']} | {zone.nameString()}")

            fan = openstudio.model.FanConstantVolume(model, always_on)
            fan.setName(f"{air_loop.nameString()} Fan")

            evap = openstudio.model.EvaporativeCoolerDirectResearchSpecial(
                model, always_on)
            evap.setName(f"{air_loop.nameString()} Evap Media")
            # 90% design effectiveness, per legacy model_add_evap_cooler
            # (Prototype.hvac_systems.rb:4501), which cites
            # https://basc.pnnl.gov/resource-guides/evaporative-cooling-systems#edit-group-description
            evap.setCoolerDesignEffectiveness(0.90)

            supply_inlet_node = air_loop.supplyInletNode()
            fan.addToNode(supply_inlet_node)
            evap.addToNode(supply_inlet_node)
            self.build_oa_system(model).addToNode(supply_inlet_node)

            # Supply setpoint follows the outdoor WET BULB plus a 3 R wet-bulb approach,
            # clamped to the legacy evap-cooler design supply temperatures of 70 F
            # (minimum) and 78 F (maximum). Mirrors legacy model_add_evap_cooler
            # (Prototype.hvac_systems.rb:4427-4432 for the temperatures, :4451-4457 for
            # the setpoint manager); the conversions are the same OpenStudio.convert
            # calls the legacy code makes, so the SI field values are bit-identical
            # (21.111111111111143 / 25.5555555555556 C, 1.6666666666666667 K).
            clg_dsgn_sup_air_temp_c = openstudio.convert(70.0, 'F', 'C').get()
            max_clg_dsgn_sup_air_temp_c = openstudio.convert(78.0, 'F', 'C').get()
            approach_k = openstudio.convert(3.0, 'R', 'K').get()
            spm = openstudio.model.SetpointManagerFollowOutdoorAirTemperature(model)
            spm.setReferenceTemperatureType('OutdoorAirWetBulb')
            spm.setMaximumSetpointTemperature(max_clg_dsgn_sup_air_temp_c)
            spm.setMinimumSetpointTemperature(clg_dsgn_sup_air_temp_c)
            spm.setOffsetTemperatureDifference(approach_k)
            spm.addToNode(air_loop.supplyOutletNode())

            diffuser = openstudio.model.AirTerminalSingleDuctUncontrolled(model, always_on)
            air_loop.addBranchForZone(zone, diffuser.to_StraightComponent())
            air_loops.append(air_loop)
        return air_loops
