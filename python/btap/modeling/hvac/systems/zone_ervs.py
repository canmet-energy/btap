"""Per-zone energy recovery ventilators (the 'with ERVs' suffix): a standalone zone ERV
with supply/exhaust fans and a sensible+latent air-to-air heat exchanger."""

from __future__ import annotations

import openstudio

from btap._compat import sorted_by_name
from btap.modeling.hvac.systems.base_system import BaseSystem


class ZoneErvs(BaseSystem):
    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        for zone in sorted_by_name(zones):
            supply_fan = openstudio.model.FanOnOff(model)
            supply_fan.setName(f"{zone.nameString()} ERV Supply Fan")
            exhaust_fan = openstudio.model.FanOnOff(model)
            exhaust_fan.setName(f"{zone.nameString()} ERV Exhaust Fan")

            erv_controller = openstudio.model.ZoneHVACEnergyRecoveryVentilatorController(
                model)
            heat_exchanger = openstudio.model.HeatExchangerAirToAirSensibleAndLatent(
                model)
            heat_exchanger.setName(f"{zone.nameString()} ERV HX")
            heat_exchanger.setSupplyAirOutletTemperatureControl(False)

            erv = openstudio.model.ZoneHVACEnergyRecoveryVentilator(
                model, heat_exchanger, supply_fan, exhaust_fan)
            erv.setName(f"{zone.nameString()} ERV")
            erv.setController(erv_controller)
            erv.addToThermalZone(zone)
        return []
