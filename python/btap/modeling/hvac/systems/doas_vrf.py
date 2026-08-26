"""ECM "hs08"/"hs13": DOAS + VRF (port of NECB ECMS add_ecm_hs08_ccashp_vrf /
add_ecm_hs13_ashp_vrf topologies). An air-cooled outdoor VRF unit with heat recovery
serves per-zone VRF terminal units; a DOAS (CCASHP for hs08 or ASHP for hs13, with a
supplemental coil) delivers ventilation at a constant 20C supply.

Topology only: the Mitsubishi/NECB2015 performance curves are applied by the host's
ECM efficiency pass after sizing (including the outdoor unit's defrost-EIR curve)."""

from __future__ import annotations

from btap._compat import sorted_by_name
from btap.modeling.hvac import naming
from btap.modeling.hvac.components import ecm_air
from btap.modeling.hvac.systems.base_system import BaseSystem


class DoasVrf(BaseSystem):
    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        air_eqpt = self.config.get('air_eqpt', 'ccashp')
        supp = ('coil_gas' if self.config.get('supp_htg_fuel', 'Electric') == 'Gas'
                else 'coil_electric')

        outdoor_unit = ecm_air.add_outdoor_vrf_unit(model)

        air_loop = ecm_air.assemble(model, zones,
                                    air_eqpt=air_eqpt,
                                    supp_htg_type=supp,
                                    spm_type='scheduled',
                                    supply_fan_type='constant_volume',
                                    hw_loop=hw_loop)[0]
        self.apply_system_sizing(air_loop)

        for zone in sorted_by_name(zones):
            self.apply_zone_sizing(zone)
            ecm_air.add_diffuser(model, air_loop, zone, 'single_duct_uncontrolled')
            ecm_air.add_zone_vrf_terminal(model, zone, outdoor_unit)

        naming.apply(namer, air_loop,
                     system_name=self.config['name'],
                     sys_abbr=self.config.get('sys_abbr', 'sys_1'),
                     sys_oa='doas',
                     parts={
                         'sys_hr': 'none',
                         'sys_clg': air_eqpt,
                         'sys_htg': air_eqpt,
                         'sys_sf': 'cv',
                         'zone_htg': 'vrf',
                         'zone_clg': 'vrf',
                         'sys_rf': 'none',
                     },
                     suffix=None)
        return [air_loop]
