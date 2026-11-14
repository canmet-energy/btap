"""Zone baseboards with no air system (CBECS 'Baseboard electric' / 'Baseboard gas
boiler'): electric convective baseboards, or hot-water baseboards served by the
(gas) boiler loop. Heating-only; builds no air loops."""

from __future__ import annotations

from btap.modeling.hvac.systems import baseboards
from btap.modeling.hvac.systems.base_system import BaseSystem


class BaseboardsOnly(BaseSystem):
    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        """:return: list of openstudio.model.AirLoopHVAC — empty (no air system)"""
        baseboard_type = self.config['baseboard_type']
        for zone in zones:
            baseboards.add(model, zone, baseboard_type, hw_loop=hw_loop)
        return []
