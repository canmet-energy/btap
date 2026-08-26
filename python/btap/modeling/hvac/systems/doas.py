"""Standalone ventilation DOAS: 100% outdoor-air CV loop at a constant neutral supply
temperature with uncontrolled diffusers — the ventilation half of the CBECS
'DOAS with <zone system>' composites (built here in the NECB MAU style)."""

from __future__ import annotations

import openstudio

from btap.modeling.hvac import naming
from btap.modeling.hvac.components import coils, schedules
from btap.modeling.hvac.systems.base_system import BaseSystem


class Doas(BaseSystem):
    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        always_on = model.alwaysOnDiscreteSchedule()
        air_loop = openstudio.model.AirLoopHVAC(model)
        self.apply_system_sizing(air_loop)

        fan = openstudio.model.FanConstantVolume(model, always_on)
        fan.setName('DOAS Supply Fan')
        htg = coils.heating_coil(model, self.config.get('heating_type', 'Electric'),
                                 always_on, hw_loop=hw_loop)
        clg = coils.dx_cooling_single_speed(model, always_on, name='DOAS DX Clg Coil')

        supply_inlet_node = air_loop.supplyInletNode()
        fan.addToNode(supply_inlet_node)
        htg.addToNode(supply_inlet_node)
        clg.addToNode(supply_inlet_node)
        self.build_oa_system(model).addToNode(supply_inlet_node)

        spm = openstudio.model.SetpointManagerScheduled(
            model,
            schedules.constant_ruleset(model, 'DOAS Neutral Supply Air Temp', 20.0))
        spm.addToNode(air_loop.supplyOutletNode())

        for zone in zones:
            diffuser = openstudio.model.AirTerminalSingleDuctUncontrolled(model, always_on)
            air_loop.addBranchForZone(zone, diffuser.to_StraightComponent())

        naming.apply(namer, air_loop,
                     system_name=self.config['name'], sys_abbr='doas', sys_oa='doas',
                     parts={'sys_hr': 'none', 'sys_clg': 'dx',
                            'sys_htg': self.config.get('heating_type', 'Electric'),
                            'sys_sf': 'cv', 'zone_htg': 'none', 'zone_clg': 'none',
                            'sys_rf': 'none'},
                     suffix=None)
        return [air_loop]
