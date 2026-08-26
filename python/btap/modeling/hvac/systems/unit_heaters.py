"""Per-zone unit heaters (port of the generic model_add_unitheater essentials):
constant-volume fan + gas/electric/hot-water heating coil, no cooling."""

from __future__ import annotations

import openstudio

from btap._compat import sorted_by_name
from btap.modeling.hvac.components import coils
from btap.modeling.hvac.systems.base_system import BaseSystem


class UnitHeaters(BaseSystem):
    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        heating_type = self.config.get('heating_type', 'Gas')
        always_on = model.alwaysOnDiscreteSchedule()

        for zone in sorted_by_name(zones):
            fan = openstudio.model.FanConstantVolume(model, always_on)
            fan.setName(f"{zone.nameString()} Unit Heater Fan")
            fan.setPressureRise(openstudio.convert(0.2, 'inH_{2}O', 'Pa').get())

            htg_coil = coils.heating_coil(model, heating_type, always_on, hw_loop=hw_loop)
            htg_coil.setName(f"{zone.nameString()} Unit Heater Coil")

            heater = openstudio.model.ZoneHVACUnitHeater(model, always_on, fan, htg_coil)
            heater.setName(f"{zone.nameString()} Unit Heater")
            heater.setFanControlType('OnOff')
            heater.addToThermalZone(zone)
        return []
