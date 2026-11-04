"""Catalogue system CANDIDATES for an unidentified zone group (#196/#198).

phylroy asked to try identifying the system, because HVAC drives 85.6% of site
energy on `Office_pre-1960` — heating alone 71.4% — and with every group
unresolved the reader rebuilds only the other 14%.

This never resolves a group. It ranks candidates and reports what matched and
what did not, so a wrong-looking candidate carries its own contradiction.
"""

from __future__ import annotations

import pathlib
import unittest

from btap.stock.identify import FAMILY_CANDIDATES, identify_candidates, suggest
from tests.support import needs_sdk


def _group(**facts):
    base = {'family_guess': None, 'heated': True, 'cooled': False,
            'heating_energy_types': [], 'cooling_energy_types': [],
            'terminal_type': 'none', 'zonal_units': [],
            # The two facts the scorer used to ignore. `loop_dx_cooling`
            # distinguishes a cooled LOOP from a group cooled only at the
            # zone; `system_outdoor_air_method` is what actually encodes OA
            # presence, where `ventilation_sized` does not.
            'loop_dx_cooling': False, 'system_outdoor_air_method': None}
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

    def test_a_central_cv_group_finds_a_SHARED_hydronic_psz(self):
        """Assert the PROPERTIES, not the name. My earlier version required
        'Hot Water Baseboard' as a substring, which the correct answer — the
        row added 2026-11-04 — does not contain.

        Two independent agent reads established what this group needs: ONE
        shared CV loop (not per-zone), a HOT WATER central coil on a gas
        boiler (not a direct-gas coil), and hot-water baseboards.
        """
        from btap.modeling.hvac import catalog

        candidates = identify_candidates(_group(
            family_guess='central_doas_or_cv', cooled=True,
            heating_energy_types=['NaturalGas'],
            cooling_energy_types=['Electricity'], terminal_type='cv',
            zonal_units=['baseboard'], loop_dx_cooling=True,
            system_outdoor_air_method='ZoneSum'))
        row = catalog.resolve(candidates[0]['system'])
        self.assertEqual('psz', row['family'])
        self.assertFalse(row.get('per_zone'),
                         'the model has 6-7 zones on ONE loop')
        self.assertEqual('Hot Water', row.get('heating_coil_type'),
                         "the model's central coil is Coil:Heating:Water")
        self.assertEqual('Hot Water', row.get('baseboard_type'))
        self.assertEqual('NaturalGas', row.get('boiler_fuel'))

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


@needs_sdk
class TestTheTwoFieldVocabularies(unittest.TestCase):
    """Why the Gagetown systems were unreachable although the library has them.

    `3d343f60` added SIX rows with `origin: campus` — "Six catalogue variants
    for reconstructing the Campus models" (#152). They were unreachable for two
    reasons, and only the second was mine:

    1. the archetypes' air loops are named generically — 'Packaged Rooftop Air
       Conditioner', 'AHU 2 - First Floor' — so `_recognize_gem_name`, which
       resolves the loop NAME against the catalogue, finds nothing. A naming
       gap, not a capability gap;
    2. the campus rows use a DIFFERENT field vocabulary — `heating`,
       `cooling`, `heating_type`, `cooling_type`, `ventilation`, `reheat`,
       `per_zone`, `mau_heating_coil_type`, `ptac_heating_type` — where the
       NECB-shaped rows use `baseboard_type` and `heating_coil_type`. The
       scorer read only the NECB names, so a campus row scored nothing
       informative AND was penalised 1.5 for a `baseboard_type` it never
       carries, because in that reconstruction baseboards are separate zone
       equipment with their own row.
    """

    @staticmethod
    def _ptac_group():
        return {'resolved': False, 'descriptive': {
            'family_guess': 'zonal_heat_cool', 'heated': True, 'cooled': True,
            'heating_energy_types': ['NaturalGas'],
            'cooling_energy_types': ['Electricity'],
            'terminal_type': 'none', 'zonal_units': ['ptac'],
            'ventilation_sized': False}}

    def test_the_campus_PTAC_row_wins_its_own_case(self):
        candidates = identify_candidates(self._ptac_group(), limit=5)
        top = candidates[0]
        self.assertEqual('PSZ MAU Hot Water with water-heated PTAC',
                         top['system'])
        self.assertEqual('campus', top['origin'])

    def test_a_row_with_NO_baseboard_field_is_not_penalised_for_it(self):
        """The penalty that made the campus rows unreachable. Their baseboards
        are a separate catalogue row, so silence is not disagreement."""
        group = {'resolved': False, 'descriptive': {
            'family_guess': 'central_doas_or_cv', 'heated': True,
            'cooled': True, 'heating_energy_types': ['NaturalGas'],
            'cooling_energy_types': ['Electricity'], 'terminal_type': 'cv',
            'zonal_units': ['baseboard'], 'ventilation_sized': False}}
        candidates = identify_candidates(group, limit=30)
        campus = [c for c in candidates if c['origin'] == 'campus']
        self.assertTrue(campus, 'a campus furnace row must be RANKED at all')
        for c in campus:
            self.assertFalse(
                any('baseboard present but row has none' in a
                    for a in c['against']),
                f"{c['system']!r} penalised for a field its vocabulary does "
                'not use')

    def test_the_campus_heating_type_is_read_as_a_coil_medium(self):
        """`heating_type: 'Hot Water'` means what `heating_coil_type:
        'Hot Water'` means, and reading only the second made it invisible."""
        candidates = identify_candidates(self._ptac_group(), limit=5)
        top = candidates[0]
        self.assertTrue(
            any('Hot Water' in m or 'boiler' in m for m in top['matched']),
            f"nothing in {top['matched']} reads the row's hydronic heating")

    def test_a_non_cooling_row_loses_a_LOOP_cooled_group_and_wins_a_zonal_one(self):
        """`cooling: False` counts against only when the LOOP cools.

        My first version of this test asserted it always counts against, on a
        fact set that was incoherent: cooled=True with neither loop nor zonal
        cooling. `cooled` is a UNION, and the distinction is the whole point —
        'Shared hot water heating-only air handler' is WRONG for a loop with a
        DX coil and RIGHT for the four-zone loop whose cooling is two PTACs.
        """
        name = 'Shared hot water heating-only air handler'

        loop_cooled = {'resolved': False, 'descriptive': {
            'family_guess': 'central_doas_or_cv', 'heated': True,
            'cooled': True, 'heating_energy_types': ['NaturalGas'],
            'cooling_energy_types': ['Electricity'], 'terminal_type': 'cv',
            'zonal_units': [], 'loop_dx_cooling': True,
            'system_outdoor_air_method': 'ZoneSum',
            'ventilation_sized': False}}
        hit = next(c for c in identify_candidates(loop_cooled, limit=30)
                   if c['system'] == name)
        self.assertTrue(any('DX cooling' in a for a in hit['against']),
                        f"expected a cooling objection, got {hit['against']}")

        zonal_cooled = dict(loop_cooled)
        zonal_cooled['descriptive'] = dict(loop_cooled['descriptive'])
        zonal_cooled['descriptive']['loop_dx_cooling'] = False
        zonal_cooled['descriptive']['zonal_units'] = ['ptac', 'baseboard']
        hit = next(c for c in identify_candidates(zonal_cooled, limit=30)
                   if c['system'] == name)
        self.assertTrue(
            any('its cooling is zonal' in m for m in hit['matched']),
            'a row that does not cool the air handler is CORRECT when the '
            f"group's cooling is zonal; got {hit['matched']}")

    def test_the_reheat_field_matches_a_vav_reheat_terminal(self):
        group = {'resolved': False, 'descriptive': {
            'family_guess': 'multizone_vav', 'heated': True, 'cooled': False,
            'heating_energy_types': ['NaturalGas'],
            'cooling_energy_types': [], 'terminal_type': 'vav_reheat',
            'zonal_units': [], 'ventilation_sized': True}}
        candidates = identify_candidates(group, limit=30)
        reheat = [c for c in candidates
                  if c['system'] == 'Shared hot water air handler with water '
                                    'reheat']
        self.assertTrue(reheat, 'the campus reheat row must be ranked')
        self.assertTrue(any('reheat terminals' in m
                            for m in reheat[0]['matched']))


if __name__ == '__main__':
    unittest.main()


class TestTheBuilderDefaultsAreNotGuessed(unittest.TestCase):
    """`_BUILDER_COIL_DEFAULTS` mirrors knowledge that LIVES in the builders.

    Duplicated knowledge drifts silently, so this re-reads each builder's own
    source and fails if a default moves — the table is not allowed to be a
    guess that happens to be right today.
    """

    def test_the_builder_coil_defaults_match_this_table(self):
        import re

        from btap.stock.identify import _BUILDER_COIL_DEFAULTS

        root = (pathlib.Path(__file__).resolve().parents[2]
                / 'btap' / 'modeling' / 'hvac' / 'systems')
        pattern = re.compile(
            r"config\.get\('(?:heating_type|heating_coil_type"
            r"|mau_heating_coil_type)',\s*'([^']*)'\)")

        for family, expected in sorted(_BUILDER_COIL_DEFAULTS.items()):
            source = (root / f'{family}.py')
            self.assertTrue(source.exists(), f'no builder named {family}.py')
            found = pattern.findall(source.read_text(encoding='utf-8'))
            self.assertTrue(
                found,
                f'{family}.py no longer supplies a coil default, so '
                f'_BUILDER_COIL_DEFAULTS should not claim {expected!r}')
            self.assertEqual(
                {expected}, set(found),
                f"{family}.py's coil default is {set(found)}, but "
                f'_BUILDER_COIL_DEFAULTS says {expected!r}')

    def test_psz_and_vav_take_no_default_so_silence_is_silence(self):
        from btap.stock.identify import _BUILDER_COIL_DEFAULTS

        for family in ('psz', 'vav_reheat'):
            self.assertNotIn(
                family, _BUILDER_COIL_DEFAULTS,
                f'{family} passes no default to config.get, so a row that '
                'omits the coil field makes no claim about medium')


class TestTheFuelCannotStandInForTheMedium(unittest.TestCase):
    """The primary error, named independently by two agent reads.

    `heating_energy_types` is the fuel resolved THROUGH the plant, so a
    `Coil:Heating:Water` on a gas boiler and a `Coil:Heating:Gas` burner both
    report ['NaturalGas']. Scoring the fuel alone let a direct-gas row match a
    hydronic building. Measured on the Gagetown Office archetype: all four
    central loops report fuel=['NaturalGas'] AND media=['hydronic'].
    """

    GAS_FUELLED_HYDRONIC = {
        'family_guess': 'central_doas_or_cv', 'heated': True, 'cooled': True,
        'heating_energy_types': ['NaturalGas'],
        'cooling_energy_types': ['Electricity'], 'terminal_type': 'cv',
        'zonal_units': ['baseboard'], 'loop_dx_cooling': True,
        'system_outdoor_air_method': 'ZoneSum', 'ventilation_sized': False,
        'supply_heating_media': ['hydronic'],
    }
    COMBUSTION = 'PSZ RTU Gas and DX Coils and Hot Water Baseboard'
    HYDRONIC = 'Shared PSZ with gas boiler coils and hot water baseboard'

    def _find(self, group, name):
        return next(c for c in identify_candidates(
            {'resolved': False, 'descriptive': group}, limit=120)
            if c['system'] == name)

    def test_a_direct_gas_row_is_marked_down_for_a_hydronic_loop(self):
        hit = self._find(self.GAS_FUELLED_HYDRONIC, self.COMBUSTION)
        self.assertTrue(
            any('substitutes the heating MEDIUM' in a for a in hit['against']),
            'a direct-gas coil on a hydronic loop substitutes the medium, '
            f"which the fuel alone cannot see; got {hit['against']}")

    def test_the_hydronic_row_is_credited_for_the_same_group(self):
        hit = self._find(self.GAS_FUELLED_HYDRONIC, self.HYDRONIC)
        self.assertTrue(
            any('hydronic coil and so does this row' in m
                for m in hit['matched']), hit['matched'])

    def test_the_RANKING_FLIPS_when_only_the_medium_changes(self):
        """A flip, because "the hydronic row ranks higher" passes either way.

        My first version of this asserted exactly that, and it survived a
        mutation that blinded the scorer to the medium — the hydronic row wins
        on baseboards whatever the medium, so the assertion was measuring
        something it did not name. Two runs differing ONLY in medium must
        REVERSE the pair; a scorer that cannot see the medium returns the same
        order twice and fails here.
        """
        def order_of(media):
            group = dict(self.GAS_FUELLED_HYDRONIC, supply_heating_media=media)
            ranked = [c['system'] for c in identify_candidates(
                {'resolved': False, 'descriptive': group}, limit=120)]
            return ranked.index(self.HYDRONIC) < ranked.index(self.COMBUSTION)

        self.assertTrue(
            order_of(['hydronic']),
            'on a hydronic loop the hydronic row must rank higher')
        self.assertFalse(
            order_of(['combustion']),
            'on a combustion loop the direct-gas row must rank higher — if '
            'the order is unchanged, the medium is not being read')

    def test_CONTROL_the_MEDIUM_drives_this_and_not_the_fuel(self):
        """The control. Same fuel, same everything — only the MEDIUM flips.

        If this passed while the test above also passed on a scorer that
        ignored the medium, the assertions would be measuring the row's name
        or the group's fuel instead of the thing under test.
        """
        combustion_loop = dict(self.GAS_FUELLED_HYDRONIC,
                               supply_heating_media=['combustion'])
        self.assertEqual(
            self.GAS_FUELLED_HYDRONIC['heating_energy_types'],
            combustion_loop['heating_energy_types'],
            'the control must differ ONLY in medium')

        hit = self._find(combustion_loop, self.COMBUSTION)
        self.assertTrue(
            any('combustion coil and so does this row' in m
                for m in hit['matched']),
            f"the direct-gas row is now CORRECT; got {hit['matched']}")
        self.assertFalse(
            any('substitutes the heating MEDIUM' in a for a in hit['against']),
            'the same row must not be marked down once the loop is combustion')


class TestCompositesAreReachable(unittest.TestCase):
    """A `composite` row is a LOOP PLUS ZONE EQUIPMENT on the same zones.

    That is what 5 of the 47 groups in `Office_pre-1960` are, and
    `build_system` has always built them correctly — the teardown runs once at
    the top and each part layers on. They were reachable from NO group shape:
    measured 0 composite candidates out of 27/25/32/25 for the four layerable
    shapes.
    """

    LAYERED = {
        'family_guess': 'central_doas_or_cv', 'heated': True, 'cooled': True,
        'heating_energy_types': ['NaturalGas'],
        'cooling_energy_types': ['Electricity'], 'terminal_type': 'cv',
        'zonal_units': ['baseboard'], 'loop_dx_cooling': True,
        'system_outdoor_air_method': 'ZoneSum', 'ventilation_sized': False,
        'supply_heating_media': ['hydronic'],
    }

    def _candidates(self, **over):
        group = dict(self.LAYERED, **over)
        return identify_candidates(
            {'resolved': False, 'descriptive': group}, limit=200)

    def test_a_layered_group_can_reach_a_composite(self):
        comps = [c for c in self._candidates() if c['family'] == 'composite']
        self.assertTrue(
            comps,
            'a group with a loop AND zone equipment must be able to reach a '
            'composite row — the mechanism that builds exactly that shape')

    def test_every_layerable_shape_can_reach_one(self):
        for shape in ('central_doas_or_cv', 'packaged_single_zone',
                      'multizone_vav', 'zonal_heat_cool'):
            with self.subTest(shape=shape):
                comps = [c for c in self._candidates(family_guess=shape)
                         if c['family'] == 'composite']
                self.assertTrue(comps, f'{shape} cannot reach a composite')

    def test_CONTROL_a_group_with_no_zone_equipment_does_not_rank_one(self):
        """Reachable is not the same as preferred.

        With nothing at the zone there is nothing for a composite's second
        part to serve, so none should reach the top. If this fails, the
        reachability change is suggesting composites indiscriminately.
        """
        top = self._candidates(zonal_units=[])[:5]
        self.assertNotIn('composite', [c['family'] for c in top],
                         'a composite should not outrank simple rows for a '
                         'group with no zone equipment')

    def test_the_layering_credit_names_the_unit_it_would_build(self):
        hit = next(c for c in self._candidates()
                   if c['family'] == 'composite'
                   and 'baseboard' in c['system'].lower())
        self.assertTrue(
            any('AND this row builds it as a part' in m
                for m in hit['matched']), hit['matched'])


class TestTheZonalVocabularyIsComplete(unittest.TestCase):
    """`_ZONAL_UNIT_FAMILY` mirrors classify's zone-equipment table.

    An incomplete mirror does not fail — it silently under-credits. Using the
    3-entry `_ZONAL_FAMILY` for this starved every DOAS+fan-coil, DOAS+VRF and
    DOAS+WSHP composite (10 of the 12 shipped) because their zone equipment
    mapped to nothing.
    """

    def test_every_kind_classify_can_emit_is_mapped(self):
        import re

        from btap.stock.identify import _ZONAL_UNIT_FAMILY

        source = (pathlib.Path(__file__).resolve().parents[2] / 'btap'
                  / 'modeling' / 'hvac' / 'classify.py').read_text(
                      encoding='utf-8')
        kinds = set(re.findall(r"'kind': '([a-z_]+)'", source))
        self.assertTrue(kinds, 'found no zone-equipment kinds to check')
        self.assertEqual(
            set(), kinds - set(_ZONAL_UNIT_FAMILY),
            'classify can emit these zonal_units kinds and '
            '_ZONAL_UNIT_FAMILY does not map them, so a composite carrying '
            'one earns no credit')
        self.assertEqual(
            set(), set(_ZONAL_UNIT_FAMILY) - kinds,
            'these mapped kinds are not emitted by classify any more')

    def test_every_named_family_exists_in_the_catalogue(self):
        import json

        from btap.stock.identify import _ZONAL_UNIT_FAMILY

        rows = json.loads(
            (pathlib.Path(__file__).resolve().parents[2] / 'btap' / 'modeling'
             / 'hvac' / 'data' / 'systems.json').read_text(encoding='utf-8')
        )['systems']
        families = {r['family'] for r in rows}
        for kind, family in sorted(_ZONAL_UNIT_FAMILY.items()):
            if family is None:
                continue
            with self.subTest(kind=kind):
                self.assertIn(family, families,
                              f'{kind} maps to {family!r}, which no '
                              'catalogue row has')
