"""P2 gate (standalone half): lookup semantics — legacy-exact bin scan,
piecewise FDWR, SRR, HDD resolution from explicit/table-C1/.stat sources.

Port of btap-necb/test/test_envelope_lookups.rb.
"""

from __future__ import annotations

import unittest

from tests.necb.support import EPW, load_raw_fixture, needs_sdk


def attach_weather(model):
    """Ruby FixtureHelper#attach_weather! — the EPW half (the DDY design days
    matter only to EnergyPlus, never to HDD resolution)."""
    import openstudio

    epw = openstudio.EpwFile(openstudio.path(str(EPW)))
    openstudio.model.WeatherFile.setWeatherFile(model, epw)
    return model


@needs_sdk
class TestLookups(unittest.TestCase):
    @property
    def n(self):
        from btap.necb import envelope
        return envelope

    # "first value where hdd < bin ceiling" — spot values from NECB 2020 Table 3.2.2.2
    def test_max_u_bin_semantics(self):
        n = self.n
        self.assertAlmostEqual(
            0.290, n.max_u(vintage='2020', surface='wall', boundary='outdoors', hdd=2999),
            delta=1e-9)
        self.assertAlmostEqual(
            0.265, n.max_u(vintage='2020', surface='wall', boundary='outdoors', hdd=3000),
            delta=1e-9,
            msg='hdd == bin ceiling falls to the NEXT bin (strict <)')
        self.assertAlmostEqual(
            0.215, n.max_u(vintage='2020', surface='wall', boundary='outdoors', hdd=5000),
            delta=1e-9)
        self.assertAlmostEqual(
            0.165, n.max_u(vintage='2020', surface='wall', boundary='outdoors', hdd=7000),
            delta=1e-9)
        # beyond the last bin: legacy fallback 0.110
        self.assertAlmostEqual(
            0.110, n.max_u(vintage='2020', surface='wall', boundary='outdoors', hdd=9999),
            delta=1e-9)
        # ground + fenestration
        self.assertAlmostEqual(
            0.379, n.max_u(vintage='2020', surface='floor', boundary='ground', hdd=7500),
            delta=1e-9)
        self.assertAlmostEqual(
            1.90, n.max_u(vintage='2020', surface='window', boundary='outdoors', hdd=3500),
            delta=1e-9)
        with self.assertRaises(ValueError):
            n.max_u(vintage='2020', surface='porthole', boundary='outdoors', hdd=1)
        with self.assertRaises(ValueError):
            n.max_u(vintage='2020', surface='window', boundary='ground', hdd=1)

    # 3.2.1.4.(1): 0.40 / linear / 0.20 with continuity at the boundaries
    def test_max_fdwr_piecewise(self):
        n = self.n
        self.assertAlmostEqual(0.4, n.max_fdwr(vintage='2020', hdd=3999), delta=1e-9)
        self.assertAlmostEqual(0.4, n.max_fdwr(vintage='2020', hdd=4000), delta=1e-9,
                               msg='continuous at 4000')
        self.assertAlmostEqual((2000 - 0.2 * 5000) / 3000.0,
                               n.max_fdwr(vintage='2020', hdd=5000), delta=1e-9)
        self.assertAlmostEqual(0.2, n.max_fdwr(vintage='2020', hdd=7000), delta=1e-9)
        self.assertAlmostEqual(0.2, n.max_fdwr(vintage='2020', hdd=12_000), delta=1e-9)

    def test_max_srr(self):
        self.assertAlmostEqual(0.02, self.n.max_srr(vintage='2020'), delta=1e-9)
        self.assertAlmostEqual(0.02, self.n.max_srr(vintage='2025'), delta=1e-9)

    def test_hdd_explicit_wins(self):
        from btap.audit import AuditLog
        audit = AuditLog()
        self.assertEqual(4321, self.n.climate.hdd18(load_raw_fixture(), hdd=4321, audit=audit))
        self.assertTrue(any('explicitly' in e['action'] for e in audit.entries))

    def test_hdd_from_table_c1_for_toronto(self):
        from btap.audit import AuditLog
        model = attach_weather(load_raw_fixture())
        audit = AuditLog()
        hdd = self.n.climate.hdd18(model, audit=audit)
        decision = next((e for e in audit.entries if 'Table C-1' in e['action']), None)
        self.assertIsNotNone(decision, 'Toronto is well within the 500 km tolerance')
        # the EPW is Toronto Intl AP = Pearson, whose Table C-1 row is Mississauga
        self.assertRegex(decision['inputs']['city'], r'(?i)Toronto|Mississauga|Pearson')
        self.assertGreater(hdd, 3000)
        self.assertLess(hdd, 4500)

    def test_hdd_from_stat_file(self):
        hdd = self.n.climate.stat_hdd18(str(EPW), None)
        self.assertEqual(3579, hdd,
                         'annual (wthr file) heating degree-days, 18 C baseline')

    def test_hdd_unresolvable_warns(self):
        from btap.audit import AuditLog
        audit = AuditLog()
        self.assertIsNone(self.n.climate.hdd18(load_raw_fixture(), audit=audit))
        self.assertTrue(any('no weather file' in w['action'] for w in audit.warnings))


if __name__ == '__main__':
    unittest.main()
