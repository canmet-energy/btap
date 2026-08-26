"""VRF: outdoor VRF unit + per-zone terminal units (the CBECS 'VRF' name). Standalone
'VRF' lets terminals ventilate (default OA); in 'DOAS with VRF' composites the
terminals' OA is zeroed (config 'zone_ventilation': false) and the DOAS ventilates."""

from __future__ import annotations

from btap._compat import sorted_by_name
from btap.modeling.hvac.components import ecm_air
from btap.modeling.hvac.systems.base_system import BaseSystem


class Vrf(BaseSystem):
    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        outdoor_unit = ecm_air.add_outdoor_vrf_unit(model)
        vent = self.config.get('zone_ventilation', True)
        for zone in sorted_by_name(zones):
            terminal = ecm_air.add_zone_vrf_terminal(model, zone, outdoor_unit)
            if not vent:
                continue

            # restore default (autosized) OA on the terminal for the self-ventilating case
            terminal.autosizeOutdoorAirFlowRateDuringCoolingOperation()
            terminal.autosizeOutdoorAirFlowRateDuringHeatingOperation()
            terminal.autosizeOutdoorAirFlowRateWhenNoCoolingorHeatingisNeeded()
        return []
