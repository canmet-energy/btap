import unittest

from btap.modeling.hvac import naming


class TestNaming(unittest.TestCase):
    def test_pipe_name_matches_legacy_format_electric(self):
        """The pipe-name must byte-match the legacy openstudio-standards
        assign_base_sys_name output for the same inputs (it is a de-facto API parsed
        by ECM/costing/QAQC code)."""
        name = naming.necb_pipe_name(
            sys_abbr='sys_3', sys_oa='mixed',
            parts={'sys_hr': 'none', 'sys_clg': 'dx', 'sys_htg': 'Electric',
                   'sys_sf': 'cv', 'zone_htg': 'Electric', 'zone_clg': 'none',
                   'sys_rf': 'none'})
        # Observed from a legacy build in openstudio-standards (smoke test):
        self.assertEqual(
            'sys_3|mixed|shr>none|sc>dx|sh>c-e|ssf>cv|zh>b-e|zc>none|srf>none|', name)

    def test_pipe_name_gas_hot_water(self):
        name = naming.necb_pipe_name(
            sys_abbr='sys_4', sys_oa='mixed',
            parts={'sys_hr': 'none', 'sys_clg': 'dx', 'sys_htg': 'Gas',
                   'sys_sf': 'cv', 'zone_htg': 'Hot Water', 'zone_clg': 'none',
                   'sys_rf': 'none'})
        self.assertEqual(
            'sys_4|mixed|shr>none|sc>dx|sh>c-g|ssf>cv|zh>b-hw|zc>none|srf>none|', name)

    def test_dx_cooling_with_hp_heating_reads_ashp(self):
        name = naming.necb_pipe_name(
            sys_abbr='sys_3', sys_oa='mixed',
            parts={'sys_hr': 'none', 'sys_clg': 'dx', 'sys_htg': 'dx',
                   'sys_sf': 'cv', 'zone_htg': 'Electric', 'zone_clg': 'none',
                   'sys_rf': 'none'})
        self.assertIn('sc>ashp', name)
        self.assertIn('sh>ashp', name)


if __name__ == '__main__':
    unittest.main()
