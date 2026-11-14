"""ECM "hs09"/"hs12": air-source heat pump air system + zone baseboards (port of NECB
ECMS add_ecm_hs09_ccashp_baseboard / add_ecm_hs12_ashp_baseboard topologies).
config 'air_eqpt': 'ccashp' (hs09, cold-climate variable-speed DX) or 'ashp' (hs12,
single-speed DX). config 'vent_type':
- 'doas' (default): DOAS at constant 20C + per-zone PTAC (DX cooling, always-off
  electric heat section, ~zero OA) + baseboards
- 'mixed': multizone VAV (warmest SPM 13/22, VV supply+return fans, VAV terminals
  with electric reheat) + baseboards; single-zone gets CV single-zone-reheat"""

from __future__ import annotations

from btap._compat import sorted_by_name
from btap.modeling.hvac import naming
from btap.modeling.hvac.components import ecm_air
from btap.modeling.hvac.systems import baseboards
from btap.modeling.hvac.systems.base_system import BaseSystem


class AshpBaseboard(BaseSystem):
    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        air_eqpt = self.config.get('air_eqpt', 'ashp')
        vent_type = self.config.get('vent_type', 'doas')
        baseboard_type = self.config.get('baseboard_type', 'Electric')
        supp = ('coil_gas' if self.config.get('supp_htg_fuel', 'Electric') == 'Gas'
                else 'coil_electric')

        doas = vent_type == 'doas'
        multizone = len(zones) > 1

        air_loop = ecm_air.assemble(
            model, zones,
            air_eqpt=air_eqpt,
            supp_htg_type=supp,
            spm_type=('scheduled' if doas
                      else ('warmest' if multizone else 'single_zone_reheat')),
            supply_fan_type=('variable_volume' if not doas and multizone
                             else 'constant_volume'),
            return_fan=not doas and multizone,
            hw_loop=hw_loop)[0]
        self.apply_system_sizing(air_loop)

        diffuser_type = ('single_duct_uncontrolled' if doas or not multizone
                         else 'single_duct_vav_reheat')
        for zone in sorted_by_name(zones):
            self.apply_zone_sizing(zone)
            ecm_air.add_diffuser(model, air_loop, zone, diffuser_type)
            if doas:
                ecm_air.add_zone_ptac_electric_off(model, zone)
            baseboards.add(model, zone, baseboard_type=baseboard_type, hw_loop=hw_loop)

        # Legacy naming quirk: in DOAS mode the zone tokens come from the PTAC pass
        # (zh>b-e, zc>ptac) regardless of the actual baseboard type.
        zone_htg_part = 'Electric' if doas else baseboard_type
        naming.apply(namer, air_loop,
                     system_name=self.config['name'],
                     sys_abbr=self.config.get('sys_abbr', 'sys_1'),
                     sys_oa='doas' if doas else 'mixed',
                     parts={
                         'sys_hr': 'none',
                         'sys_clg': air_eqpt,
                         'sys_htg': air_eqpt,
                         'sys_sf': 'vv' if not doas and multizone else 'cv',
                         'zone_htg': zone_htg_part,
                         'zone_clg': 'ptac' if doas else 'none',
                         'sys_rf': 'vv' if not doas and multizone else 'none',
                     },
                     suffix=None)
        return [air_loop]
