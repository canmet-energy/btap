"""#221: three facts the model states that the suggester could not see.

`identify.py` is a SUGGESTION mechanism — `suggest_systems=` and
`accept_candidates=` are both off by default, and approximate HVAC is the
documented contract (`btap/stock/CLAUDE.md`). So none of these corrupted a
default-path build. Each made a suggestion that contradicted something
`characterize` had already measured, which is worth refusing on its own terms.

Found by two independent agent reviews on 2026-11-06; the first was found by
both of them separately.
"""
import pathlib
import unittest

import openstudio

from btap.modeling.hvac import catalog, classify
from btap.stock.identify import FAMILY_CANDIDATES, identify_candidates


def _score(facts, limit=99):
    return identify_candidates(
        {'resolved': False, 'descriptive': facts}, limit=limit)


BASE = {
    'family_guess': 'packaged_single_zone', 'heated': True, 'cooled': True,
    'heating_energy_types': ['NaturalGas'],
    'cooling_energy_types': ['Electricity'],
    'loop_dx_cooling': True, 'zonal_units': [],
}


class TestHydronicSupplyCoolingIsLoopCooling(unittest.TestCase):
    """A chilled-water air handler cools on the supply side like a DX one.

    `loop_cools` read `loop_dx_cooling` alone, so `zonal_cools` became true
    for a chilled-water loop and every row putting cooling on the air handler
    drew the explicit objection that the loop has no cooling coil. One
    reviewer measured the consequence: all 8 chilled-water
    `MZ BU RTU Hot Water` rows came back as a `cooling: False` air handler,
    the chiller plant deleted.
    """

    CHILLED_WATER = dict(
        BASE, family_guess='multizone_vav', loop_dx_cooling=False,
        loop_hydronic_cooling_supply=True,
        supply_heating_media=['Hot Water'], terminal_type='reheat')

    def test_no_row_is_told_the_loop_has_no_cooling_coil(self):
        for hit in _score(self.CHILLED_WATER):
            for line in hit['against']:
                self.assertNotIn(
                    'its loop has no cooling coil', line,
                    f"{hit['system']!r} drew a false objection: {line}")

    def test_a_DX_loop_still_counts_as_loop_cooling(self):
        """The control: widening loop cooling must not stop DX counting."""
        facts = dict(BASE, family_guess='multizone_vav',
                     loop_dx_cooling=True, terminal_type='reheat')
        for hit in _score(facts):
            for line in hit['against']:
                self.assertNotIn('its loop has no cooling coil', line)

    def test_a_TRULY_zonal_group_still_draws_the_objection(self):
        """The other control, and the one that makes the first meaningful.

        A group cooled ONLY by zone equipment must still object to a row that
        cools the air handler, or the fix has simply deleted the rule.
        """
        facts = dict(BASE, family_guess='zonal_heat_cool',
                     loop_dx_cooling=False,
                     loop_hydronic_cooling_supply=False,
                     zonal_units=['ptac'])
        objected = [h for h in _score(facts)
                    if any('its loop has no cooling coil' in a
                           for a in h['against'])]
        self.assertTrue(
            objected,
            'no row was told its loop lacks cooling, so the rule is gone')

    def test_the_fact_is_scoped_to_the_SUPPLY_path(self):
        """A TERMINAL hydronic cooling coil must NOT claim loop cooling.

        `_scan_cooling_component` is called from the supply scan AND from
        `_terminal_facts`, and the unscoped `loop_hydronic_cooling` is set by
        both. Reading that flag instead would trade this false negative for a
        false positive, so the supply fact is set by the CALL SITE.
        """
        model = openstudio.model.Model()
        loop = openstudio.model.AirLoopHVAC(model)
        zone = openstudio.model.ThermalZone(model)
        terminal = openstudio.model.AirTerminalSingleDuctVAVReheat(
            model, model.alwaysOnDiscreteSchedule(),
            openstudio.model.CoilHeatingWater(
                model, model.alwaysOnDiscreteSchedule()))
        loop.multiAddBranchForZone(zone, terminal)
        facts = classify.characterize(model)
        for group in facts['zone_groups']:
            self.assertIsNot(
                group.get('loop_hydronic_cooling_supply'), True,
                'a terminal coil claimed SUPPLY-side cooling')


class TestEveryStructuralGuessHasCandidates(unittest.TestCase):
    """Four of nine `_structural_family_guess` returns had no entry, and an
    unmapped guess yields NOTHING — so a dual-duct or chilled-beam building
    got no suggestion, and those catalogue rows could never be proposed."""

    GUESSES = ('central_doas_or_cv', 'chilled_beam', 'dual_duct_vav',
               'multizone_cv', 'multizone_vav', 'zonal_cooling_only',
               'zonal_heat_cool', 'zonal_heating_only')

    def test_each_guess_proposes_something(self):
        for guess in self.GUESSES:
            with self.subTest(guess=guess):
                self.assertIn(guess, FAMILY_CANDIDATES)
                got = _score(dict(BASE, family_guess=guess))
                self.assertTrue(
                    got, f'{guess!r} proposed nothing at all')

    def test_every_named_family_has_catalogue_rows(self):
        """A mapping to a family with no rows is the same silence."""
        families = {row['family'] for row in catalog.rows()}
        for guess, candidates in FAMILY_CANDIDATES.items():
            with self.subTest(guess=guess):
                missing = [f for f in candidates if f not in families]
                self.assertEqual([], missing)

    def test_unconditioned_is_mapped_to_NOTHING_not_left_unmapped(self):
        """The distinction the four missing entries got wrong.

        `unconditioned` has no system to suggest, and the table says so
        EXPLICITLY with an empty tuple rather than by omitting the key. Both
        produce no candidates; only one of them says it meant to. My first
        version of this test asserted the key was absent, which would have
        locked in the weaker form.
        """
        self.assertIn('unconditioned', FAMILY_CANDIDATES)
        self.assertEqual((), FAMILY_CANDIDATES['unconditioned'])

    def test_no_structural_guess_is_merely_MISSING(self):
        """Every return of `_structural_family_guess` is a key here, whether
        its value is a candidate list or a deliberate empty tuple."""
        import re

        src = pathlib.Path(classify.__file__).read_text(encoding='utf-8')
        start = src.index('def _structural_family_guess')
        emitted = set(re.findall(r"return '([a-z_]+)'", src[start:start + 4000]))
        self.assertTrue(emitted, 'found no structural guesses to check')
        self.assertEqual(set(), emitted - set(FAMILY_CANDIDATES))


class TestTheBaseboardMediumIsMeasuredNotInferred(unittest.TestCase):
    """`zonal_units` carries the KIND, so both baseboard classes read as
    'baseboard'. The medium was inferred from `heating_energy_types`, which is
    the fuel resolved THROUGH the plant — so a hydronic baseboard on a gas
    boiler reports gas, and the proxy coincides with the medium on this
    archetype without measuring it."""

    def _top_medium(self, media):
        facts = dict(BASE, zonal_units=['baseboard'], baseboard_media=media)
        top = _score(facts, limit=3)[0]
        return catalog.resolve(top['system']).get('baseboard_type')

    def test_electric_baseboards_pick_an_electric_row(self):
        self.assertEqual('Electric', self._top_medium(['Electric']))

    def test_hot_water_baseboards_pick_a_hot_water_row(self):
        self.assertEqual('Hot Water', self._top_medium(['Hot Water']))

    def test_the_recorded_medium_uses_the_CATALOGUE_spelling(self):
        """The bug in the first version of this fix.

        `ZONAL` says 'hydronic' and 'Electricity'; `baseboard_type` says
        'Hot Water' and 'Electric'. Translating only the hydronic half made
        the scorer penalise the CORRECT electric row for "building 'Electric'
        where the group has Electricity", ranking it 6th. The medium must be
        recorded in the vocabulary its consumer compares against.
        """
        model = openstudio.model.Model()
        zone = openstudio.model.ThermalZone(model)
        openstudio.model.ZoneHVACBaseboardConvectiveElectric(
            model).addToThermalZone(zone)
        facts = classify.characterize(model)
        media = {m for g in facts['zone_groups']
                 for m in (g.get('baseboard_media') or [])}
        self.assertIn('Electric', media)
        self.assertNotIn('Electricity', media)

    def test_an_unrecorded_medium_falls_back_rather_than_penalising(self):
        """An absent fact is not evidence of disagreement.

        A recipe written before `baseboard_media` existed must score as it did
        before, not take a mismatch penalty for a fact nobody measured.
        """
        facts = dict(BASE, zonal_units=['baseboard'])
        top = _score(facts, limit=3)[0]
        self.assertFalse(
            any('but this row builds' in a for a in top['against']),
            'an unmeasured medium was treated as a contradiction')


if __name__ == '__main__':
    unittest.main()
