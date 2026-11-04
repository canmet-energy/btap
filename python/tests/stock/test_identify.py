"""Catalogue system CANDIDATES for an unidentified zone group (#196/#198).

phylroy asked to try identifying the system, because HVAC drives 85.6% of site
energy on `Office_pre-1960` — heating alone 71.4% — and with every group
unresolved the reader rebuilds only the other 14%.

This never resolves a group. It ranks candidates and reports what matched and
what did not, so a wrong-looking candidate carries its own contradiction.
"""

from __future__ import annotations

import unittest

from btap.stock.identify import FAMILY_CANDIDATES, identify_candidates, suggest
from tests.support import needs_sdk


def _group(**facts):
    base = {'family_guess': None, 'heated': True, 'cooled': False,
            'heating_energy_types': [], 'cooling_energy_types': [],
            'terminal_type': 'none', 'zonal_units': []}
    base.update(facts)
    return {'resolved': False, 'descriptive': base}


class TestItNeverResolves(unittest.TestCase):

    def test_an_already_resolved_group_gets_no_candidates(self):
        self.assertEqual([], identify_candidates(
            {'resolved': True, 'system': 'PSZ RTU Gas and DX Coils'}))

    def test_suggest_writes_candidates_but_never_a_system(self):
        section = {'zone_groups': [_group(
            family_guess='zonal_heating_only',
            heating_energy_types=['NaturalGas'],
            zonal_units=['unit_heater'])]}
        suggest(section)
        group = section['zone_groups'][0]
        self.assertFalse(group['resolved'],
                         'a candidate must not make a group resolved')
        self.assertNotIn('system', group)
        self.assertTrue(group['candidates'])
        self.assertIn('not identifications', group['candidate_note'])

    def test_an_unconditioned_group_gets_NO_candidate(self):
        section = {'zone_groups': [_group(family_guess='unconditioned',
                                          heated=False, cooled=False)]}
        suggest(section)
        group = section['zone_groups'][0]
        self.assertEqual([], group['candidates'])
        self.assertIn('unconditioned', group['candidate_note'])
        self.assertEqual((), FAMILY_CANDIDATES['unconditioned'])


@needs_sdk
class TestTheCoilMediumIsNotAFuel(unittest.TestCase):
    """The bug that inverted the VAV result.

    The `vav_reheat` family has NO gas coil — 12 rows are 'Hot Water', 8
    'Electric' — because a reheat coil is hydronic or electric and gas reaches
    it THROUGH A BOILER. A first version asked whether the coil string
    contained the fuel word, so for a gas-heated building the CORRECT
    hot-water rows were penalised exactly like the wrong electric ones and
    electric won on name order.
    """

    def test_a_gas_heated_vav_prefers_a_HOT_WATER_coil(self):
        candidates = identify_candidates(_group(
            family_guess='multizone_vav', cooled=True,
            heating_energy_types=['NaturalGas'],
            cooling_energy_types=['Electricity'],
            terminal_type='vav_reheat', zonal_units=['baseboard']), limit=5)
        self.assertTrue(candidates)
        top = candidates[0]
        # Assert the PROPERTY, not a name substring. The first version of this
        # test required 'Hot Water' in the name, which was a proxy for
        # "hydronic" — and once `boiler_fuel` was scored the winner became
        # 'PVAV with gas boiler reheat and plate HRV', which is hydronic AND
        # names its gas boiler but does not contain that string. The proxy
        # would have failed a better answer.
        self.assertNotIn(
            'Electric Heating Coil', top['system'],
            f"got {top['system']!r} — an electric coil cannot be fed by a "
            'gas boiler')
        self.assertTrue(
            any('boiler' in m or 'Hot Water' in m for m in top['matched']),
            f"nothing in {top['matched']} establishes a hydronic or "
            'boiler-fed heat source')

    def test_an_electric_coil_is_penalised_for_a_gas_building(self):
        candidates = identify_candidates(_group(
            family_guess='multizone_vav', cooled=True,
            heating_energy_types=['NaturalGas'],
            cooling_energy_types=['Electricity'],
            terminal_type='vav_reheat', zonal_units=['baseboard']), limit=20)
        electric = [c for c in candidates
                    if 'Electric Heating Coil' in (c['system'] or '')]
        hot_water = [c for c in candidates
                     if 'Hot Water Heating Coil' in (c['system'] or '')]
        self.assertTrue(electric and hot_water, 'both kinds must be ranked')
        self.assertGreater(
            hot_water[0]['score'], electric[0]['score'],
            'the hydronic coil must outrank the electric one')
        self.assertTrue(any('no boiler can feed it' in a
                            for a in electric[0]['against']))

    def test_an_electric_heated_group_prefers_an_ELECTRIC_coil(self):
        """The inverse, so the fix is not just a thumb on one scale."""
        candidates = identify_candidates(_group(
            family_guess='multizone_vav', cooled=True,
            heating_energy_types=['Electricity'],
            cooling_energy_types=['Electricity'],
            terminal_type='vav_reheat', zonal_units=['baseboard']), limit=20)
        electric = [c for c in candidates
                    if 'Electric Heating Coil' in (c['system'] or '')]
        hot_water = [c for c in candidates
                     if 'Hot Water Heating Coil' in (c['system'] or '')]
        self.assertGreater(electric[0]['score'], hot_water[0]['score'])


@needs_sdk
class TestWhatItFindsOnTheRealSIGNATURES(unittest.TestCase):
    """The signatures measured on `Office_pre-1960`, and what should win."""

    def test_unit_heaters_find_the_CAMPUS_row(self):
        """Six catalogue rows carry `origin: campus`, curated from the project
        these archetypes come from."""
        candidates = identify_candidates(_group(
            family_guess='zonal_heating_only',
            heating_energy_types=['NaturalGas'],
            zonal_units=['unit_heater']))
        self.assertEqual('Hot water unit heaters', candidates[0]['system'])
        self.assertEqual('campus', candidates[0]['origin'])

    def test_a_ptac_group_finds_the_campus_MAU_row(self):
        candidates = identify_candidates(_group(
            family_guess='zonal_heat_cool', cooled=True,
            heating_energy_types=['NaturalGas'],
            cooling_energy_types=['Electricity'], zonal_units=['ptac']))
        self.assertEqual('PSZ MAU Hot Water with water-heated PTAC',
                         candidates[0]['system'])

    def test_a_central_cv_group_finds_a_PSZ_row(self):
        candidates = identify_candidates(_group(
            family_guess='central_doas_or_cv', cooled=True,
            heating_energy_types=['NaturalGas'],
            cooling_energy_types=['Electricity'], terminal_type='cv',
            zonal_units=['baseboard']))
        self.assertIn('PSZ', candidates[0]['system'])
        self.assertIn('Hot Water Baseboard', candidates[0]['system'])

    def test_provenance_is_a_TIEBREAK_and_cannot_outweigh_a_fact(self):
        """A provenance tag is not evidence about the equipment."""
        candidates = identify_candidates(_group(
            family_guess='zonal_heating_only',
            heating_energy_types=['Electricity'],
            zonal_units=['unit_heater']), limit=5)
        top = candidates[0]
        self.assertEqual(
            'Electric unit heaters', top['system'],
            'the electric row must win on the FACT, not lose to the '
            'campus-origin hot-water row on provenance')
        campus = [c for c in candidates if c['origin'] == 'campus'][0]
        self.assertLess(campus['score'], top['score'])


@needs_sdk
class TestEveryCandidateCarriesItsEvidence(unittest.TestCase):

    def test_matched_and_against_are_both_populated(self):
        candidates = identify_candidates(_group(
            family_guess='multizone_vav', cooled=True,
            heating_energy_types=['NaturalGas'],
            cooling_energy_types=['Electricity'],
            terminal_type='vav_reheat', zonal_units=['baseboard']), limit=20)
        self.assertTrue(all('matched' in c and 'against' in c
                            for c in candidates))
        self.assertTrue(any(c['against'] for c in candidates),
                        'a wrong-looking candidate must state its own '
                        'contradiction, or the ranking is unfalsifiable')

    def test_candidates_are_ranked_best_first(self):
        candidates = identify_candidates(_group(
            family_guess='psz' and 'central_doas_or_cv', cooled=True,
            heating_energy_types=['NaturalGas'],
            cooling_energy_types=['Electricity'], terminal_type='cv',
            zonal_units=['baseboard']), limit=10)
        scores = [c['score'] for c in candidates]
        self.assertEqual(sorted(scores, reverse=True), scores)


@needs_sdk
class TestItIsOffByDefault(unittest.TestCase):

    def test_write_recipe_adds_no_candidates_unless_asked(self):
        """A guess must not look like a finding to someone who did not read
        the flag."""
        import openstudio

        from btap.stock import write_recipe

        model = openstudio.model.Model()
        air_loop = openstudio.model.AirLoopHVAC(model)
        zone = openstudio.model.ThermalZone(model)
        air_loop.addBranchForZone(zone)

        plain = write_recipe(model, building_type='Probe')
        for group in plain['hvac']['zone_groups']:
            self.assertNotIn('candidates', group)

        asked = write_recipe(model, building_type='Probe',
                             suggest_systems=True)
        for group in asked['hvac']['zone_groups']:
            self.assertIn('candidates', group)
            self.assertFalse(group['resolved'])


@needs_sdk
class TestTheDistrictTieBreak(unittest.TestCase):
    """The tie that cost 75,600 kWh in a generated model.

    `Baseboard gas boiler` and `Baseboard district hot water` both scored 3.50
    on the baseboard medium alone, so the alphabetical sort picked DISTRICT
    for a NaturalGas building. Generating from that candidate produced a model
    carrying 75,600 kWh of district heating against the original's ZERO —
    a purchased-heat stream the building does not have.

    Nine catalogue rows declare `boiler_fuel` and one declares
    `hw_source: district`. Both were being ignored.
    """

    @staticmethod
    def _gas_baseboard_group():
        return {'resolved': False, 'descriptive': {
            'family_guess': 'zonal_heating_only',
            'heating_energy_types': ['NaturalGas'],
            'cooling_energy_types': [], 'zonal_units': ['baseboard'],
            'terminal_type': 'none'}}

    def test_a_gas_building_picks_the_GAS_BOILER_not_district(self):
        candidates = identify_candidates(self._gas_baseboard_group(),
                                         limit=10)
        self.assertEqual('Baseboard gas boiler', candidates[0]['system'])
        district = next(c for c in candidates
                        if c['system'] == 'Baseboard district hot water')
        self.assertLess(
            district['score'], candidates[0]['score'],
            'district must LOSE, and not by a tie-break — by the facts')

    def test_the_district_candidate_states_WHY_it_is_wrong(self):
        candidates = identify_candidates(self._gas_baseboard_group(),
                                         limit=10)
        district = next(c for c in candidates
                        if c['system'] == 'Baseboard district hot water')
        self.assertTrue(
            any('purchased-heat stream' in a for a in district['against']),
            'the contradiction has to be legible, not just scored')

    def test_a_DISTRICT_heated_building_does_pick_district(self):
        """The inverse, so the penalty is not a blanket one."""
        group = self._gas_baseboard_group()
        group['descriptive']['heating_energy_types'] = ['DistrictHeating']
        candidates = identify_candidates(group, limit=10)
        self.assertEqual('Baseboard district hot water',
                         candidates[0]['system'])

    def test_the_boiler_fuel_field_is_what_decides_it(self):
        """An electric-heated building must not get the gas boiler."""
        group = self._gas_baseboard_group()
        group['descriptive']['heating_energy_types'] = ['Electricity']
        candidates = identify_candidates(group, limit=10)
        self.assertEqual('Baseboard electric', candidates[0]['system'])
        gas = next(c for c in candidates
                   if c['system'] == 'Baseboard gas boiler')
        self.assertTrue(any("boiler fuel 'NaturalGas' against" in a
                            for a in gas['against']))


if __name__ == '__main__':
    unittest.main()
