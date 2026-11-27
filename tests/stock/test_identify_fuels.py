"""#244: every OpenStudio fuel is visible to the identifier, and a fuel no
catalogue row burns is scored honestly.

The catalogue has no oil- or coal-fired row, so the goal is that no candidate
claims a match it does not have — not that a new row wins.
"""

from __future__ import annotations

import unittest

from btap.stock.identify import _fuel_tokens, identify_candidates
from tests.stock.test_identify import _group
from tests.support import needs_sdk

#: The SDK's `FuelType` enum, OpenStudio 3.11 (`utilities/data/DataEnums.hpp`),
#: both spellings, with the token each must yield.
SDK_FUELS = {
    'Electricity': 'electric', 'Gas': 'gas', 'NaturalGas': 'gas',
    'Propane': 'gas', 'FuelOil_1': 'oil', 'FuelOilNo1': 'oil',
    'FuelOil_2': 'oil', 'FuelOilNo2': 'oil', 'Diesel': 'oil',
    'Gasoline': 'other', 'Coal': 'other', 'OtherFuel_1': 'other',
    'OtherFuel1': 'other', 'OtherFuel_2': 'other', 'OtherFuel2': 'other',
    'Steam': 'district', 'DistrictHeating': 'district',
    'DistrictHeatingWater': 'district', 'DistrictHeatingSteam': 'district',
    'DistrictCooling': 'district',
}


def _hot_water(fuels, **extra):
    return _group(family_guess='zonal_heating_only', cooled=False,
                  zonal_units=['baseboard'], baseboard_media=['Hot Water'],
                  heating_energy_types=fuels, **extra)


def _candidate(group, system):
    return next(c for c in identify_candidates(group, limit=50)
                if c['system'] == system)


class TestEveryFuelIsVisible(unittest.TestCase):

    def test_every_sdk_fuel_yields_its_token(self):
        for fuel, token in SDK_FUELS.items():
            with self.subTest(fuel=fuel):
                self.assertEqual({token}, _fuel_tokens([fuel]))

    def test_classifys_purchased_marker_is_still_unread(self):
        """A RECORDED GAP, pinned so its fix is a visible decision: classify
        reports district heating/cooling as 'Purchased', and reading it moves
        the district rows' scores, which #244's oil fix must not do."""
        self.assertEqual(set(), _fuel_tokens(['Purchased']))

    def test_a_coal_building_is_not_scored_as_burning_nothing(self):
        """Coal was dropped, so the gas-boiler row's fuel was never checked."""
        gas = _candidate(_hot_water(['Coal']), 'bb-hwbb-gasboiler')
        self.assertTrue(any("boiler fuel 'NaturalGas' against ['other']" in a
                            for a in gas['against']), gas['against'])

    def test_gasoline_is_not_natural_gas(self):
        gas = _candidate(_hot_water(['Gasoline']), 'bb-hwbb-gasboiler')
        self.assertFalse(any("boiler fuel 'NaturalGas' matches" in m
                             for m in gas['matched']), gas['matched'])


class TestAFuelNoRowBurns(unittest.TestCase):

    def test_every_candidate_says_the_fuel_is_substituted(self):
        for fuels in (['FuelOilNo2'], ['Coal'], ['Electricity', 'FuelOilNo1']):
            with self.subTest(fuels=fuels):
                candidates = identify_candidates(_hot_water(fuels), limit=50)
                self.assertTrue(candidates)
                for c in candidates:
                    self.assertTrue(
                        any('no catalogue system burns it' in a for a in c['against']),
                        f"{c['system']} is offered with nothing said about the fuel")

    def test_an_oil_backed_heat_pump_credits_no_electric_backup_match(self):
        """The heat pump explains the electricity; the backup burns the oil.
        Before #244 the electric-backup row took "boiler fuel 'Electricity'
        matches ['electric', 'oil']" and ranked first."""
        electric = _candidate(_hot_water(['Electricity', 'FuelOilNo2'], heat_pump=True),
                              'bb-hwbb-awhp-elecbu')
        self.assertFalse(any("boiler fuel 'Electricity' matches" in m
                             for m in electric['matched']), electric['matched'])
        self.assertTrue(any("boiler fuel 'Electricity' against ['oil']" in a
                            for a in electric['against']), electric['against'])
        # ...and the backup check, now on the tokens, agrees.
        self.assertTrue(any('burns a non-electric fuel' in a
                            for a in electric['against']))

    def test_CONTROL_a_gas_backed_heat_pump_is_scored_as_before(self):
        """The scoping: on a fuel the catalogue builds, nothing moves."""
        group = _hot_water(['Electricity', 'NaturalGas'], heat_pump=True)
        electric = _candidate(group, 'bb-hwbb-awhp-elecbu')
        self.assertTrue(any("boiler fuel 'Electricity' matches" in m
                            for m in electric['matched']))
        self.assertFalse(any('no catalogue system burns it' in a
                             for c in identify_candidates(group, limit=50)
                             for a in c['against']))


@needs_sdk
class TestAnOilFiredModelEndToEnd(unittest.TestCase):
    """The fact comes from a BUILT model, not a hand-written dict: an oil
    boiler's fuel survives `classify` and reaches the scorer."""

    def test_an_oil_boiler_is_seen_and_disclosed(self):
        from btap.modeling import build_system
        from btap.stock.hvac import hvac_section
        from tests.necb.hvac_helpers import load_fixture, sorted_zones

        model = load_fixture()
        build_system(model, 'bb-hwbb-gasboiler', sorted_zones(model),
                     config={'boiler_fuel': 'FuelOilNo2'})
        for i, loop in enumerate(model.getPlantLoops()):
            loop.setName(f'Plant {i + 1}')
        groups = [g for g in hvac_section(model, audit=None)['zone_groups']
                  if not g['resolved']]
        self.assertTrue(groups, 'the scrub must leave a group to identify')
        for group in groups:
            facts = group.get('descriptive') or group
            self.assertIn('FuelOilNo2', facts.get('heating_energy_types') or [])
            candidates = identify_candidates(group, limit=50)
            self.assertTrue(candidates)
            gas = _candidate(group, 'bb-hwbb-gasboiler')
            self.assertTrue(any("'NaturalGas' against ['oil']" in a
                                for a in gas['against']), gas['against'])
            for c in candidates:
                self.assertTrue(any('no catalogue system burns it' in a
                                    for a in c['against']), c['system'])



class TestUnknownIsNotAFuel(unittest.TestCase):
    """Fable, review of #248: classify writes 'Unknown' for a fuel it cannot
    resolve. The catch-all read it as `other` ("the group burns other"), a
    fabricated fact that moved candidates unevenly. It must score exactly as
    if no fuel were reported."""

    def test_unknown_scores_exactly_like_no_fuel(self):
        from btap.stock import identify_candidates
        from tests.stock.test_identify import _group
        base = dict(family_guess='zonal_heating_only', zonal_units=['baseboard'],
                    baseboard_media=['Hot Water'])
        unknown = identify_candidates(_group(heating_energy_types=['Unknown'], **base), limit=15)
        empty = identify_candidates(_group(heating_energy_types=[], **base), limit=15)
        self.assertEqual([(c['system'], c['score']) for c in empty],
                         [(c['system'], c['score']) for c in unknown])
        self.assertFalse(any('other' in a for c in unknown for a in c['against']))

    def test_the_token_function_drops_it(self):
        from btap.stock.identify import _fuel_tokens
        self.assertEqual(set(), _fuel_tokens(['Unknown']))
        self.assertEqual({'gas'}, _fuel_tokens(['Unknown', 'NaturalGas']))


if __name__ == '__main__':
    unittest.main()
