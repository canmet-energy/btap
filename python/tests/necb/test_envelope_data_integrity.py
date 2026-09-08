"""P1 gate: the vendored rules data is complete, internally consistent,
provenance-tagged, and structurally identical to the legacy
openstudio-standards data (2020).

Port of btap-necb/test/test_envelope_data_integrity.rb. The Ruby suite's
``test_2020_matches_legacy_surface_thermal_transmittance`` reads the U-table
straight out of the PINNED oracle's gem tree; the Python port consumes the
same probe's frozen output instead — see
``tests/necb/test_oracle_goldens_envelope.py::test_u_table_matches_the_oracle``
(D-78 Leg C). This file keeps every edition-internal check.
"""

from __future__ import annotations

import json
import unittest

from tests.necb.support import needs_sdk

EDITIONS = ['2020', '2025']
SURFACES = {'outdoors': ['wall', 'roofceiling', 'floor', 'window', 'skylight', 'door'],
            'ground': ['wall', 'roofceiling', 'floor']}
BINS = ['3000', '4000', '5000', '6000', '7000', '9999']


@needs_sdk
class TestDataIntegrity(unittest.TestCase):
    @property
    def n(self):
        from btap.codes.necb import envelope
        return envelope

    def test_rules_load_and_unknown_edition_raises(self):
        for v in EDITIONS:
            self.assertIsNotNone(self.n.rules(v))
        with self.assertRaises(ValueError):
            self.n.rules('1997')

    def test_u_values_complete_and_monotone(self):
        for edition in EDITIONS:
            u = self.n.rules(edition)['u_values']
            for boundary, surfaces in SURFACES.items():
                for surface in surfaces:
                    bins = u[boundary][surface]
                    self.assertEqual(BINS, list(bins.keys()),
                                     f'{edition}/{boundary}/{surface}: bin keys')
                    values = [bins[b] for b in BINS]
                    self.assertTrue(all(isinstance(v, (int, float))
                                        and not isinstance(v, bool) and v > 0
                                        for v in values))
                    # colder zones require equal-or-lower U (monotone non-increasing)
                    for a, b in zip(values, values[1:]):
                        self.assertLessEqual(
                            b, a,
                            f'{edition}/{boundary}/{surface}: U must not increase with '
                            f'HDD ({values})')

    def test_fdwr_piecewise_continuity(self):
        for edition in EDITIONS:
            pieces = self.n.rules(edition)['fdwr']['pieces']
            self.assertEqual(3, len(pieces))
            linear = pieces[1]['linear']
            at4000 = (linear['intercept'] + linear['slope'] * 4000) / linear['divisor']
            at7000 = (linear['intercept'] + linear['slope'] * 7000) / linear['divisor']
            self.assertAlmostEqual(pieces[0]['value'], at4000, delta=1e-9,
                                   msg='continuous at HDD 4000')
            self.assertAlmostEqual(pieces[2]['value'], at7000, delta=1e-9,
                                   msg='continuous at HDD 7000')

    def test_srr_is_two_percent(self):
        for edition in EDITIONS:
            srr = self.n.rules(edition)['srr_max']
            self.assertAlmostEqual(0.02, srr['value'], delta=1e-9)
            self.assertRegex(srr['article'], r'3\.2\.1\.4')

    def test_provenance_and_coverage_lint(self):
        valid = ['implemented', 'partial', 'not_implemented', 'satisfied_by_clone',
                 'host_scope']
        for edition in EDITIONS:
            rules = self.n.rules(edition)
            prov = rules['provenance']
            self.assertEqual(edition, prov['edition'])
            self.assertRegex(prov['source'], r'MCP')
            coverage = rules['article_coverage']['articles']
            # 14 + 8.4.1.1 (envelope slice) + 8.4.2.9 air leakage
            self.assertEqual(17, len(coverage))
            for art in coverage:
                self.assertIn(art['status'], valid, f"{art['article']}: invalid status")
                self.assertTrue(art['title'])
                if art['status'] in ('partial', 'not_implemented'):
                    self.assertTrue(art.get('gaps'),
                                    f"{art['article']} is {art['status']} but declares no gaps")
            # Only the reference-building subsection is renumbered between
            # editions (2020 8.4.4 == 2025 8.4.5); 8.4.1-8.4.3 and 8.4.6 are
            # edition-invariant.
            wrong = '8.4.5' if edition == '2020' else '8.4.4'
            renumbered = [a for a in coverage
                          if a['article'].startswith(('8.4.4', '8.4.5'))]
            self.assertFalse(any(a['article'].startswith(wrong) for a in renumbered),
                             f'{edition}: reference-building articles must not use the '
                             f'{wrong} numbering')

    def test_2025_values_equal_2020(self):
        self.assertEqual(
            self.n.rules('2020')['u_values'], self.n.rules('2025')['u_values'],
            'verified via MCP: 2025 envelope tables are numerically identical to 2020')

    def test_table_c1_vendored(self):
        from btap.codes.necb import edition_file
        path = edition_file('2020', 'tables', 'table_c1.json')
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
        self.assertGreaterEqual(len(data['table']), 679)
        row = data['table'][0]
        for k in ('city', 'province', 'degree_days_below_18_c', 'lat_long'):
            self.assertIn(k, row)
        self.assertRegex(data['provenance']['source'], r'Table C-1')

    def test_audit_log_schema_matches_hvac_gem(self):
        from btap.audit import AuditLog
        audit = AuditLog()
        audit.decision('test', 'x', article='3.2.1.4.')
        entry = json.loads(audit.to_json())[0]
        wanted = ['step', 'action', 'article', 'level']
        self.assertEqual(sorted(wanted),
                         sorted(k for k in entry if k in wanted))


if __name__ == '__main__':
    unittest.main()
