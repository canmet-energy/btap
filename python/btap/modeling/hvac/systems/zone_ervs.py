"""Per-zone energy recovery ventilators (the 'with ERVs' suffix).

#217: the device itself now lives in `hvac/energy_recovery.py` so any family
can carry one as an OPTION, not only this standalone row. This class is the
row that builds nothing else.
"""
from __future__ import annotations

from btap._compat import sorted_by_name
from btap.modeling.hvac import energy_recovery
from btap.modeling.hvac.systems.base_system import BaseSystem


class ZoneErvs(BaseSystem):
    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        for zone in sorted_by_name(zones):
            energy_recovery.add_zone_energy_recovery(model, zone)
        return []
