"""#184 — resolving a performance profile from an authored vintage table.

The design is defined AGAINST `codes/necb/hvac/efficiency.find_row`, which
treats a missing key, a `None` and the literal `'Any'` as wildcards and then
returns `rows[0]`. That combination produced AHJ-17 (#181): one `AirCooled`
chiller row with `compressor_type: null` matched every compressor type across
a capacity band.

So these tests pin the REFUSALS as hard as the successes. A resolver that
silently falls back is worse than one that raises, because a 1972 Ottawa
office's assumed boiler efficiency cannot be checked against anything the way
an NECB coefficient can.
"""

from __future__ import annotations

import unittest

from btap.stock.performance import (
    ANY,
    CRITERIA,
    ProfileResolutionError,
    ProfileTableError,
    resolve_performance_profile,
    uncovered_combinations,
    validate_table,
)


def row(vintage, zone, building_type, cop, source=None):
    return {'vintage': vintage, 'climate_zone': zone,
            'building_type': building_type,
            'values': {'vrf_rated_heating_cop': cop},
            'source': source}


class TestTheTableMustBeExplicit(unittest.TestCase):

    def test_a_MISSING_criteria_key_is_an_authoring_error(self):
        """The AHJ-17 shape, refused.

        `find_row` would treat the absent key as a wildcard. Here it is a
        mistake, because absence cannot express intent.
        """
        bad = [{'vintage': '1960-1979', 'climate_zone': '6',
                'values': {'vrf_rated_heating_cop': 2.4}}]
        with self.assertRaises(ProfileTableError) as caught:
            validate_table(bad)
        message = str(caught.exception)
        self.assertIn('building_type', message)
        self.assertIn('AUTHORING ERROR', message)
        self.assertIn(ANY, message)

    def test_None_is_refused_and_the_message_names_the_alternative(self):
        bad = [row('1960-1979', None, 'office', 2.4)]
        with self.assertRaises(ProfileTableError) as caught:
            validate_table(bad)
        self.assertIn('climate_zone=None', str(caught.exception))

    def test_every_offending_row_is_reported_at_once(self):
        """One pass, not a fix-and-rerun loop."""
        bad = [{'vintage': 'any', 'values': {'x': 1}},
               {'climate_zone': 'any', 'values': {'x': 1}}]
        with self.assertRaises(ProfileTableError) as caught:
            validate_table(bad)
        message = str(caught.exception)
        self.assertIn('row 0', message)
        self.assertIn('row 1', message)

    def test_a_row_with_no_values_is_refused(self):
        bad = [{'vintage': ANY, 'climate_zone': ANY, 'building_type': ANY,
                'values': {}}]
        with self.assertRaises(ProfileTableError):
            validate_table(bad)


class TestMostSpecificWins(unittest.TestCase):

    def setUp(self):
        #: The general row is FIRST deliberately — under find_row's
        #: first-row-wins it would shadow both specific rows below.
        self.table = [
            row(ANY, ANY, ANY, 2.0, source='stock-wide default'),
            row('1960-1979', ANY, ANY, 2.4, source='vintage study'),
            row('1960-1979', '6', 'office', 2.9, source='Ottawa office audit'),
        ]

    def resolve(self, **kwargs):
        return resolve_performance_profile(self.table, **kwargs)

    def test_the_most_specific_row_wins_not_the_first(self):
        values, provenance = self.resolve(
            vintage='1960-1979', climate_zone='6', building_type='office')
        self.assertAlmostEqual(2.9, values['vrf_rated_heating_cop'])
        self.assertEqual(3, provenance['specificity'])
        self.assertTrue(provenance['exact'])
        self.assertEqual([], provenance['wildcards'])
        self.assertEqual('Ottawa office audit', provenance['source'])

    def test_a_partial_match_falls_to_the_next_most_specific(self):
        values, provenance = self.resolve(
            vintage='1960-1979', climate_zone='7A', building_type='warehouse')
        self.assertAlmostEqual(2.4, values['vrf_rated_heating_cop'])
        self.assertEqual(1, provenance['specificity'])
        self.assertEqual(['climate_zone', 'building_type'],
                         provenance['wildcards'])
        self.assertFalse(provenance['exact'])

    def test_the_wildcard_row_is_reached_only_when_nothing_better_matches(self):
        values, provenance = self.resolve(
            vintage='2005-2014', climate_zone='4', building_type='retail')
        self.assertAlmostEqual(2.0, values['vrf_rated_heating_cop'])
        self.assertEqual(0, provenance['specificity'])
        self.assertEqual(list(CRITERIA), provenance['wildcards'])

    def test_the_returned_values_are_a_COPY(self):
        """A caller mutating the profile must not edit the table."""
        values, _ = self.resolve(vintage='1960-1979', climate_zone='6',
                                 building_type='office')
        values['vrf_rated_heating_cop'] = 99.0
        again, _ = self.resolve(vintage='1960-1979', climate_zone='6',
                                building_type='office')
        self.assertAlmostEqual(2.9, again['vrf_rated_heating_cop'])


class TestItRefusesRatherThanGuessing(unittest.TestCase):

    def test_no_match_RAISES_instead_of_falling_back(self):
        table = [row('1960-1979', '6', 'office', 2.9)]
        with self.assertRaises(ProfileResolutionError) as caught:
            resolve_performance_profile(
                table, vintage='pre-1960', climate_zone='6',
                building_type='office')
        self.assertIn('does NOT fall back silently', str(caught.exception))

    def test_a_TIE_is_an_error_because_first_row_wins_was_the_bug(self):
        """Two rows equally specific and mutually exclusive on no criterion.

        Each matches with one wildcard, so neither is more specific. `find_row`
        would return whichever came first; here the table is declared
        ambiguous, which is the author's problem to fix.
        """
        table = [row('1960-1979', '6', ANY, 2.5),
                 row('1960-1979', ANY, 'office', 2.7)]
        with self.assertRaises(ProfileResolutionError) as caught:
            resolve_performance_profile(
                table, vintage='1960-1979', climate_zone='6',
                building_type='office')
        message = str(caught.exception)
        self.assertIn('tie at specificity 2', message)
        self.assertIn('AHJ-17', message)


class TestTheProvenanceIsAudited(unittest.TestCase):

    def test_a_wildcard_fallback_is_disclosed_as_such(self):
        from btap.audit import AuditLog

        table = [row(ANY, ANY, ANY, 2.0, source='stock-wide default')]
        audit = AuditLog()
        resolve_performance_profile(
            table, vintage='1972', climate_zone='6', building_type='office',
            audit=audit)

        entries = [e for e in audit.entries
                   if 'vintage performance profile' in e['action']]
        self.assertEqual(1, len(entries))
        self.assertIn('WILDCARD fallback', entries[0]['action'])
        self.assertEqual(['vintage', 'climate_zone', 'building_type'],
                         entries[0]['inputs']['wildcards'])

    def test_an_exact_match_is_distinguishable_in_the_trail(self):
        """The whole reason provenance exists: the VALUES alone cannot tell a
        real measurement from a three-wildcard guess."""
        from btap.audit import AuditLog

        table = [row('1960-1979', '6', 'office', 2.9, source='audit')]
        audit = AuditLog()
        resolve_performance_profile(
            table, vintage='1960-1979', climate_zone='6',
            building_type='office', audit=audit)

        entry = next(e for e in audit.entries
                     if 'vintage performance profile' in e['action'])
        self.assertIn('exact match', entry['action'])
        self.assertNotIn('WILDCARD', entry['action'])


class TestCoverageReporting(unittest.TestCase):

    def test_it_names_what_the_table_answers_only_vaguely(self):
        """A table can be entirely VALID and still answer most of the stock
        with one three-wildcard row. Nothing else would say so."""
        table = [row('1960-1979', '6', 'office', 2.9),
                 row(ANY, ANY, ANY, 2.0)]
        report = uncovered_combinations(
            table, vintages=('1960-1979', 'pre-1960'),
            climate_zones=('6', '7A'), building_types=('office', 'retail'))

        self.assertEqual([], report['unmatched'])
        self.assertEqual(7, len(report['wildcard_only']),
                         'one of eight combinations is exact; the rest are '
                         'answered by the catch-all')

    def test_it_names_combinations_nothing_matches(self):
        table = [row('1960-1979', '6', 'office', 2.9)]
        report = uncovered_combinations(
            table, vintages=('1960-1979',), climate_zones=('6', '7A'),
            building_types=('office',))

        self.assertEqual(1, len(report['unmatched']))
        self.assertEqual('7A', report['unmatched'][0]['climate_zone'])


class TestNoVintageDataShips(unittest.TestCase):
    """phylroy, 2026-11-02: "none initially"."""

    def test_the_package_ships_no_stock_data_directory(self):
        import pathlib

        import btap.stock as stock

        data = pathlib.Path(stock.__file__).parent / 'data'
        self.assertFalse(
            data.exists(),
            'btap/stock/CLAUDE.md says an author adding this should expect to '
            'be asked which authority its numbers come from — a vintage '
            'performance table is a PARAMETER, not a shipped artifact')
