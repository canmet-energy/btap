"""D-101: the thermal block selects the system, and the larger scopes stay large.

Sol's `139` item 4 asked for positive tests where ONE PROPOSED MULTI-ZONE AIR
LOOP serves several blocks — not the singleton-group case the dispatch test
already covered, which observes one unit per zone for a reason that has nothing
to do with this ruling. Each test here starts from a proposed model whose five
retained zones share one air loop, which is the configuration that produced a
"single-zone" System 3 over five thermal blocks.

Three distinct Code scopes are asserted separately, because the defect was
collapsing them into one:

* the THERMAL BLOCK selects the system — `8.4.x.7.(1)`, one unit per block for
  Systems 3 and 4 and the Article 13 redirects;
* the SYSTEMS SERVED BY A PLANT size the plant — `8.4.x.9.(6)(a)`, so a plant
  is not multiplied by the blocks its systems serve;
* the PROPOSED HEAT PUMP or source-loop SET scopes the election —
  `8.4.x.13.(2)(g)`, D-52's contract.

System 6 is the control: Table 8.4.x.7.-B Note (3) grants it the grouping the
single-zone rows are denied, so a passing System 6 case proves the per-block
assertions are not simply "more loops is better".
"""

import unittest

from btap.audit import AuditLog
from btap.codes.necb import hvac

from .support import proposed_with_hvac

#: One proposed VAV loop over all five retained zones — the shape that made a
#: reference "single-zone" unit serve five blocks.
MULTIZONE_PROPOSED = 'MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard'

EDITIONS = ('necb2020', 'necb2025')


def reference_of(proposed, *, code='necb2020', storeys=2, space_type=None,
                 **building):
    if space_type is not None:
        for st in proposed.getSpaceTypes():
            if st.spaces():
                st.setStandardsSpaceType(space_type)
    audit = AuditLog()
    result = hvac.reference_hvac(proposed, code=code,
                                 building=dict(building, storeys=storeys),
                                 audit=audit)
    return result.model, audit


def selected_systems(audit):
    """The reference system each block was assigned, in audit order."""
    return [str(entry.get('value') or '').split('->')[0].strip()
            for entry in audit.entries
            if entry.get('action') == 'reference system selected']


def loop_zones(model):
    """Each reference air loop's served zone names, sorted for comparison."""
    return sorted(
        tuple(sorted(z.nameString() for z in loop.thermalZones()))
        for loop in model.getAirLoopHVACs())


class TestOneProposedLoopBecomesOneUnitPerBlock(unittest.TestCase):
    """The precondition is the point: ONE proposed loop, several blocks."""

    def assert_proposed_is_one_multizone_loop(self, proposed):
        loops = list(proposed.getAirLoopHVACs())
        self.assertEqual(1, len(loops),
                         'fixture precondition: ONE proposed air loop')
        self.assertGreater(
            len(loops[0].thermalZones()), 1,
            'fixture precondition: that loop serves SEVERAL thermal blocks')
        return sorted(z.nameString() for z in loops[0].thermalZones())

    def test_a_single_zone_system_3_gets_one_unit_per_block(self):
        for code in EDITIONS:
            with self.subTest(code=code):
                proposed = proposed_with_hvac(MULTIZONE_PROPOSED)
                blocks = self.assert_proposed_is_one_multizone_loop(proposed)
                # 2 storeys + a general space type selects System 3.
                reference, _ = reference_of(proposed, code=code, storeys=2)
                served = loop_zones(reference)
                self.assertEqual(
                    [(b,) for b in blocks], served,
                    'Table 8.4.x.7.-B "Single-zone": one unit per thermal '
                    'block, each serving only its own block')

    def test_a_single_zone_system_4_gets_one_unit_per_block(self):
        """System 4 needs the HOOD, not just the space type.

        This test first used `Food preparation area` alone and asserted only the
        loop topology — which passed while selecting System 3, because the
        Supermarket/Food Service row elects System 4 only for a HOODED space and
        a hood is a condition the model cannot express. So it asserts the
        selected system too, and supplies `kitchen_hood_zones`.
        """
        for code in EDITIONS:
            with self.subTest(code=code):
                proposed = proposed_with_hvac(MULTIZONE_PROPOSED)
                blocks = self.assert_proposed_is_one_multizone_loop(proposed)
                audit_model, audit = None, None
                audit_model, audit = reference_of(
                    proposed, code=code, storeys=2,
                    space_type='Food preparation area',
                    kitchen_hood_zones=list(blocks))
                self.assertEqual(
                    ['System 4'] * len(blocks), selected_systems(audit),
                    'the hooded Supermarket/Food Service row selects System 4')
                self.assertEqual(
                    [(b,) for b in blocks], loop_zones(audit_model),
                    'System 4 is "Single-zone" in the same table')

    def test_a_MIXED_proposed_loop_selects_PER_BLOCK_not_by_majority(self):
        """Sol's `139` item 5: selection, not only construction.

        One proposed air loop, five blocks, and a condition that holds for only
        two of them. `_category_for` used to MAJORITY-VOTE over the serving
        group and warn that it was applying one row to the whole thing (D-22);
        with the block as the unit each block answers for itself, and the
        warning has nothing left to report.
        """
        proposed = proposed_with_hvac(MULTIZONE_PROPOSED)
        blocks = self.assert_proposed_is_one_multizone_loop(proposed)
        hooded = blocks[:2]
        reference, audit = reference_of(
            proposed, storeys=2, space_type='Food preparation area',
            kitchen_hood_zones=list(hooded))
        systems = selected_systems(audit)
        self.assertEqual(
            {'System 3': 3, 'System 4': 2},
            {name: systems.count(name) for name in sorted(set(systems))},
            'the two hooded blocks take System 4 and the other three take '
            'System 3 — one serving system, two Table -A rows')
        self.assertEqual(
            [(b,) for b in blocks], loop_zones(reference),
            'and each block still gets its own single-zone unit')
        # The D-22 warning says "mixes categories". A bare 'mixes' also matches
        # "system 4 mixes outdoor air into the supply stream", which fires five
        # times here and has nothing to do with selection.
        mixed = [e for e in audit.entries
                 if 'mixes categories' in str(e.get('action') or '')]
        self.assertEqual(
            [], mixed,
            'no majority was applied, so the D-22 mixed-category warning must '
            'not fire: {}'.format([e.get('action') for e in mixed]))

    def test_a_multizone_system_6_KEEPS_its_Note_3_grouping(self):
        """The control. Note (3) is marked on System 6 ALONE, and the express
        permission would be unnecessary if any list of zones could be served by
        one unit — so System 6 must still produce ONE loop over every block.

        If this failed while the two tests above passed, the implementation
        would be splitting by habit rather than by the table.
        """
        for code in EDITIONS:
            with self.subTest(code=code):
                proposed = proposed_with_hvac(MULTIZONE_PROPOSED)
                blocks = self.assert_proposed_is_one_multizone_loop(proposed)
                # 3 storeys selects System 6.
                reference, _ = reference_of(proposed, code=code, storeys=3)
                self.assertEqual(
                    [tuple(blocks)], loop_zones(reference),
                    'Table 8.4.x.7.-B Note (3): one multi-zone system spans '
                    'the thermal blocks')

    def test_every_single_zone_unit_has_its_OWN_control_zone(self):
        """One unit per block is not enough on its own: the defect was one
        thermostat driving five blocks, so each loop must also be controlled by
        the block it serves.
        """
        proposed = proposed_with_hvac(MULTIZONE_PROPOSED)
        self.assert_proposed_is_one_multizone_loop(proposed)
        reference, _ = reference_of(proposed, storeys=2)
        for loop in reference.getAirLoopHVACs():
            served = [z.nameString() for z in loop.thermalZones()]
            self.assertEqual(1, len(served), loop.nameString())
            controlled = []
            for manager in loop.supplyOutletNode().setpointManagers():
                single = manager.to_SetpointManagerSingleZoneReheat()
                if single.is_initialized():
                    zone = single.get().controlZone()
                    if zone.is_initialized():
                        controlled.append(zone.get().nameString())
            if controlled:
                self.assertEqual(
                    served, controlled,
                    'the loop must be controlled by the block it serves, not '
                    'by another block')


class TestTheLargerScopesDoNotMULTIPLY(unittest.TestCase):
    """Per-block SELECTION must not become per-block everything."""

    def test_the_plant_is_not_multiplied_by_the_blocks_it_serves(self):
        """`8.4.x.9.(6)(a)` sizes a plant from the systems it serves. Five
        single-zone units drawing on one hot-water plant is one plant.
        """
        proposed = proposed_with_hvac(MULTIZONE_PROPOSED)
        reference, _ = reference_of(proposed, storeys=2)
        loops = list(reference.getAirLoopHVACs())
        self.assertGreater(len(loops), 1, 'precondition: several block units')
        # The plants that actually carry a boiler, found from the boilers
        # rather than from loop names.
        hot_water = sorted({b.plantLoop().get().nameString()
                            for b in reference.getBoilerHotWaters()
                            if b.plantLoop().is_initialized()})
        self.assertLessEqual(
            len(hot_water), 1,
            'one hydronic plant serves the block systems; got {}'.format(
                hot_water))

    def test_one_disclosure_per_choice_not_per_block(self):
        """`8.4.x.9.(5)` transfers ONE capacity allocation and ONE operating
        priority from one proposed heating system, so one multi-energy plant
        serving five blocks raises ONE unresolved question. Five copies would
        obscure it.
        """
        proposed = proposed_with_hvac(MULTIZONE_PROPOSED)
        boilers = sorted(proposed.getBoilerHotWaters(),
                         key=lambda b: b.nameString())
        self.assertGreater(len(boilers), 1,
                           'fixture precondition: a multi-boiler plant')
        boilers[0].setFuelType('Electricity')
        reference, audit = reference_of(proposed, storeys=2)
        blocks = [z.nameString() for z in reference.getThermalZones()]
        self.assertGreater(len(blocks), 1,
                           'fixture precondition: several thermal blocks')
        # `ahj` carries every disposition that applies to the choice, so this
        # entry reads "AHJ-1 AHJ-3". An `== "AHJ-1"` filter matched NOTHING and
        # made an `assertLessEqual(1)` pass on zero disclosures — the whole
        # assertion was vacuous until this fixture was measured.
        disclosures = [e for e in audit.entries
                       if 'AHJ-1' in str(e.get('ahj') or '')]
        self.assertEqual(
            1, len(disclosures),
            'ONE choice means exactly one disclosure, not one per block and '
            'not none; got {}'.format([e.get('target') for e in disclosures]))
        self.assertTrue(
            str(disclosures[0].get('target') or ''),
            'the disclosure must name what it affects')


class TestTheArticle13ElectionTRACKSTHEHEATPUMP(unittest.TestCase):
    """Sol's `141` and `143`: the election's scope is the proposed heat pump, or
    the set sharing a source water loop — `8.4.x.13.(2)(g)(i)` and `(g)(ii)` —
    and it is neither the thermal block nor the whole building.

    These tests COUNTED election entries in their first version and passed no
    annual data, so they proved the cache fires once or twice and nothing else.
    That missed a live defect: the cache key was computed on the unsplit group,
    but the election itself was handed the one-BLOCK view, so it weighed one
    block's auxiliary energy and answered for all of them. Keying the cache on
    the full scope stopped a second call; it did not make the first call
    full-scope.

    Every case therefore supplies `proposed_annual` SPLIT so that the
    first-block answer differs from the full-scope answer, and asserts the
    elected value, the affected blocks, `scope_zone_count` and the per-fuel
    totals — not the entry count.
    """

    SYS3_ASHP = ('PSZ RTU ASHP with Gas and ASHP with Gas Supp. Heat Coils '
                 'and Electric Baseboard')
    GSHP = 'DOAS with water source heat pumps with ground source heat pump'

    def built(self, system, splits, *, rename_first_loop=None):
        from btap import modeling

        from .hvac_helpers import load_fixture, sorted_zones

        model = load_fixture()
        zones = sorted_zones(model)
        for index, (start, stop) in enumerate(splits):
            if index == 1 and rename_first_loop:
                for plant in model.getPlantLoops():
                    if 'Heat Pump' in plant.nameString():
                        plant.setName(rename_first_loop)
            modeling.build_system(model, system, zones[start:stop])
        return model, modeling.characterize(model, audit=None)

    @staticmethod
    def annual_for(groups, fuels):
        """Delivered heat on every group's loop, and ONE auxiliary fuel per
        group so a scope error shows up as the wrong winner."""
        annual = {'loops': {}, 'zones': {}}
        for group in groups:
            if group.get('air_loop'):
                annual['loops'][group['air_loop']] = {'hp_j': 1000e9, 'aux': []}
        for group, (fuel, gj) in zip(groups, fuels):
            for zone in group['zones']:
                annual['zones'][zone] = [{'role': 'aux', 'fuel': fuel,
                                          'j': gj * 1e9}]
        return annual

    def elections(self, model, annual):
        audit = AuditLog()
        hvac.reference_hvac(model, code='necb2020', building={'storeys': 2},
                            audit=audit, proposed_annual=annual)
        out = []
        for entry in audit.entries:
            if 'ELECTED' not in str(entry.get('action')):
                continue
            inputs = entry.get('inputs') or {}
            out.append({
                'elected': str(entry.get('value') or ''),
                'target': str(entry.get('target') or ''),
                'zones': inputs.get('scope_zone_count'),
                'by_fuel': inputs.get('by_fuel_gj'),
                'article': str(entry.get('article') or ''),
                'level': entry.get('level'),
            })
        return out

    @staticmethod
    def groups_of(facts):
        return sorted(facts['zone_groups'], key=lambda g: sorted(g['zones']))

    def test_ONE_heat_pump_elects_over_EVERY_block_it_serves(self):
        """(g)(i), and the case that found the defect.

        One ASHP over five blocks, with 10 GJ of auxiliary GAS on the first
        block and 100 GJ of auxiliary ELECTRICITY on the second. The first
        block alone elects `gas`; the proposed heat pump's full scope elects
        `electric`. Only the second is the Code's answer.
        """
        model, facts = self.built(self.SYS3_ASHP, [(0, None)])
        groups = self.groups_of(facts)
        self.assertEqual(1, len(groups), 'precondition: one proposed heat pump')
        blocks = list(groups[0]['zones'])
        self.assertEqual(5, len(blocks), 'precondition: five blocks')

        annual = {'loops': {groups[0]['air_loop']: {'hp_j': 1000e9, 'aux': []}},
                  'zones': {blocks[0]: [{'role': 'aux', 'fuel': 'NaturalGas',
                                         'j': 10e9}],
                            blocks[1]: [{'role': 'aux', 'fuel': 'Electricity',
                                         'j': 100e9}]}}
        found = self.elections(model, annual)
        self.assertEqual(1, len(found),
                         'one proposed heat pump is ONE election')
        got = found[0]
        self.assertEqual('electric', got['elected'],
                         'the largest auxiliary energy type over ALL blocks '
                         'the heat pump serves; the first block alone would '
                         'elect gas')
        self.assertEqual({'NaturalGas': 10.0, 'Electricity': 100.0},
                         got['by_fuel'],
                         'both blocks must be weighed')
        self.assertEqual(5, got['zones'],
                         'the scope is five blocks, not one')
        self.assertEqual(sorted(blocks), sorted(got['target'].split(',')),
                         'the entry must name every affected block')
        self.assertEqual('decision', got['level'])

    def test_TWO_heat_pumps_elect_INDEPENDENTLY(self):
        """Each proposed heat pump answers from its own members only, so a
        cache keyed too coarsely would hand the second one the first one's
        data and elect the same fuel twice.
        """
        model, facts = self.built(self.SYS3_ASHP, [(0, 3), (3, None)])
        groups = self.groups_of(facts)
        self.assertEqual(2, len(groups), 'precondition: two proposed heat pumps')
        annual = self.annual_for(groups, [('NaturalGas', 50), ('Electricity', 50)])
        found = sorted(self.elections(model, annual), key=lambda r: r['zones'])
        self.assertEqual(2, len(found), 'two heat pumps are two elections')
        self.assertEqual(['electric', 'gas'],
                         sorted(r['elected'] for r in found),
                         'they must elect DIFFERENTLY from their own data')
        self.assertEqual([{'Electricity': 100.0}, {'NaturalGas': 150.0}],
                         [found[0]['by_fuel'], found[1]['by_fuel']],
                         'neither may see the other heat pump\'s auxiliary '
                         'energy')
        self.assertEqual([2, 3], [r['zones'] for r in found])

    def test_a_SHARED_source_loop_COMBINES_its_members_once(self):
        """(g)(ii): an 'external'-source heat pump elects over the thermal
        blocks of ALL heat pumps on the same source water loop. Two zone
        groups, 10 GJ of gas across one and 100 GJ of electricity across the
        other, must COMBINE into one election — and each group alone would
        elect the other way.
        """
        model, facts = self.built(self.GSHP, [(0, 3), (3, None)])
        loops = [p.nameString() for p in model.getPlantLoops()]
        self.assertEqual(1, len(loops),
                         'precondition: the second build JOINS the same source '
                         'loop; got {}'.format(loops))
        groups = self.groups_of(facts)
        annual = self.annual_for(groups, [('NaturalGas', 10), ('Electricity', 100)])
        found = self.elections(model, annual)
        self.assertEqual(1, len(found), 'one source water loop is one election')
        got = found[0]
        self.assertEqual('electric', got['elected'])
        self.assertEqual({'NaturalGas': 30.0, 'Electricity': 200.0},
                         got['by_fuel'],
                         'the union of both groups on the loop')
        self.assertEqual(5, got['zones'], 'every block on the source loop')
        self.assertIn('(g)(ii)', got['article'],
                      'the shared-source-loop sentence, not (g)(i)')

    def test_DISTINCT_source_loops_elect_from_THEIR_OWN_members(self):
        """And two source loops are two questions. The first loop is renamed so
        the second build cannot join it — without that the builder reuses
        `Heat Pump Loop` and this silently becomes the shared case above.
        """
        model, facts = self.built(self.GSHP, [(0, 3), (3, None)],
                                  rename_first_loop='East Heat Pump Loop')
        self.assertEqual(2, len(model.getPlantLoops()),
                         'precondition: two DISTINCT source water loops')
        groups = self.groups_of(facts)
        annual = self.annual_for(groups, [('NaturalGas', 50), ('Electricity', 50)])
        found = sorted(self.elections(model, annual), key=lambda r: r['zones'])
        self.assertEqual(2, len(found), 'two source loops are two elections')
        self.assertEqual(['electric', 'gas'],
                         sorted(r['elected'] for r in found))
        self.assertEqual([{'Electricity': 100.0}, {'NaturalGas': 150.0}],
                         [found[0]['by_fuel'], found[1]['by_fuel']],
                         'neither loop may see the other loop\'s members')


class TestPurchasedEnergyStillGetsBlocks(unittest.TestCase):
    """The purchased-energy path has its own capacity-share rule under
    `8.4.x.6.` and RETURNS before the multi-energy disclosure, so it is the one
    place a block could plausibly have been lost on the way to the builder.

    Sol's `141` asked for a purchased-heating AND purchased-cooling witness.
    Both fire here on one fixture, and what is asserted is that the per-block
    rule survives them: the article that makes the reference's heating and
    cooling plant purchased says nothing about how many secondary systems serve
    how many thermal blocks.
    """

    SYS = 'DOAS with fan coil district chilled water with district hot water'

    def test_both_purchased_services_keep_one_unit_per_block(self):
        proposed = proposed_with_hvac(self.SYS)
        reference, audit = reference_of(proposed, storeys=2)
        blocks = sorted(z.nameString() for z in reference.getThermalZones())
        self.assertEqual(
            [(b,) for b in blocks], loop_zones(reference),
            'the purchased path must not reintroduce a shared unit')

        applied = [str(e.get('action')) for e in audit.entries
                   if 'Purchased Energy' in str(e.get('action'))]
        self.assertTrue(
            any('purchased HEATING' in a for a in applied),
            'fixture precondition: purchased heating applied')
        self.assertTrue(
            any('purchased COOLING' in a for a in applied),
            'fixture precondition: purchased cooling applied')

        # And 8.4.x.6. owns it, so the 8.4.x.9.(5) disclosure must stay silent
        # — the purchased branch returns above it (Sol's `110`).
        self.assertEqual(
            [], [e for e in audit.entries
                 if 'AHJ-1' in str(e.get('ahj') or '')],
            'purchased energy never reaches the multi-energy disclosure')


class TestAMixedCopyAndBuildClosure(unittest.TestCase):
    """Sol's `143` blocker 3: phased teardown is not enough on its own.

    `remove_hvac_from_zones` drops a plant only once its demand side empties,
    so a plant shared by a RETAINED `copy_proposed` block and replaced blocks
    correctly survives for the copied block. The first reference builder then
    found it — by boiler presence, part-load class, or failing those by NAME —
    and connected the replaced blocks to it. An `action == 'build'` assignment
    was still adopting proposed plant equipment, through retained demand rather
    than teardown order.

    These tests trace DEMAND-SIDE CONNECTIONS rather than boiler presence,
    because every fixture here ends with proposed boilers still in the model:
    that is the point, since the copied block is entitled to them.
    """

    MARKER = 'PROPOSED MARKER'
    SYS = 'FPFC MAU DX Coils with Scroll Chiller'

    def mixed_proposed(self):
        """One four-pipe fan-coil serving group over five blocks: block 1
        residential (reaching `copy_proposed`), blocks 2-5 office (built)."""
        proposed = proposed_with_hvac(self.SYS)
        zones = sorted(proposed.getThermalZones(), key=lambda z: z.nameString())
        for index, zone in enumerate(zones):
            wanted = 'Dwelling unit' if index == 0 else 'Office - enclosed'
            for space in zone.spaces():
                space_type = space.spaceType()
                if space_type.is_initialized():
                    clone = space_type.get().clone(proposed).to_SpaceType().get()
                    clone.setName('Block type {}'.format(index))
                    clone.setStandardsSpaceType(wanted)
                    space.setSpaceType(clone)
        boilers = sorted(proposed.getBoilerHotWaters(),
                         key=lambda b: b.nameString())
        self.assertGreater(len(boilers), 1, 'fixture: a multi-boiler plant')
        boilers[0].setFuelType('Electricity')
        for index, boiler in enumerate(boilers):
            boiler.setName('{} {}'.format(self.MARKER, index))
        return proposed, [zone.nameString() for zone in zones]

    def marked_plants(self, model):
        return [plant for plant in model.getPlantLoops()
                if any(self.MARKER in component.nameString()
                       for component in plant.supplyComponents())]

    @staticmethod
    def demand_names(plant):
        return sorted(component.nameString()
                      for component in plant.demandComponents()
                      if 'Coil' in component.nameString()
                      or 'Baseboard' in component.nameString())

    def test_the_copied_block_KEEPS_its_plant_and_no_built_block_joins_it(self):
        proposed, blocks = self.mixed_proposed()
        reference, audit = reference_of(proposed, storeys=1)

        # The precondition is the mixed closure itself.
        retained = [e for e in audit.entries
                    if 'retained in reference' in str(e.get('action'))]
        self.assertEqual(1, len(retained),
                         'fixture: exactly one copy_proposed block')
        self.assertEqual(blocks[0], str(retained[0].get('target')))

        marked = self.marked_plants(reference)
        self.assertEqual(
            1, len(marked),
            'the proposed boilers must still exist — the copied block is '
            'entitled to them')
        # ONE demand connection, the copied block's own fan coil. Four
        # `Coil Heating Water Baseboard` objects here was the defect.
        self.assertEqual(
            ['Coil Heating Water 1'], self.demand_names(marked[0]),
            'no newly built block may be attached to the retained proposed '
            'plant')

        marked_handles = {str(plant.handle()) for plant in marked}
        unmarked = [plant for plant in reference.getPlantLoops()
                    if str(plant.handle()) not in marked_handles
                    and any('Boiler' in component.nameString()
                            for component in plant.supplyComponents())]
        self.assertEqual(
            1, len(unmarked),
            'the built blocks need a separately planned reference plant')
        self.assertEqual(
            4, len(self.demand_names(unmarked[0])),
            'and all four replaced blocks connect to THAT one')

    def test_the_reservation_is_AUDITED(self):
        proposed, _ = self.mixed_proposed()
        _, audit = reference_of(proposed, storeys=1)
        reserved = [e for e in audit.entries
                    if 'RESERVED to the retained blocks' in str(e.get('action'))]
        self.assertEqual(1, len(reserved),
                         'the ownership decision must be visible, not implicit')
        inputs = reserved[0].get('inputs') or {}
        self.assertEqual(1, inputs.get('copied_blocks'))
        self.assertEqual(4, inputs.get('replaced_blocks'))
        self.assertEqual('D-101', reserved[0].get('ruling'))

    def test_AHJ_1_names_only_the_blocks_that_RECEIVE_the_substitution(self):
        """Sol's `143` blocker 2, test 4. The copied block keeps the proposed
        system and BOTH its fuels, so it faces no single-fuel substitution and
        must not be counted among the affected blocks — the disclosure listed
        the whole service set, including it.
        """
        proposed, blocks = self.mixed_proposed()
        _, audit = reference_of(proposed, storeys=1)
        disclosures = [e for e in audit.entries
                       if 'AHJ-1' in str(e.get('ahj') or '')]
        self.assertEqual(1, len(disclosures), 'one service choice')
        inputs = disclosures[0].get('inputs') or {}
        self.assertEqual(
            blocks[1:], inputs.get('affected_blocks'),
            'the four REPLACED blocks, not the retained one')
        self.assertEqual(
            blocks, inputs.get('service_set'),
            'the service set is still recorded in full, so a reader can see '
            'the difference')


class TestDistinctSourceLoopServiceSetsStayDISTINCT(unittest.TestCase):
    """Sol's `143` blocker 2, test 5: one Article 13 source-loop scope must not
    collapse two service sets into one disclosure.

    The election's scope and the disclosure's scope are different questions —
    `8.4.x.13.(2)(g)(ii)` unions the blocks of every heat pump on a shared
    source water loop, while `8.4.x.9.(5)` follows each proposed heating
    service and allocation choice.
    """

    SYS = 'DOAS with water source heat pumps fluid cooler with boiler'

    def test_two_WSHP_service_sets_on_one_source_loop_disclose_SEPARATELY(self):
        from btap import modeling

        from .hvac_helpers import load_fixture, sorted_zones

        model = load_fixture()
        zones = sorted_zones(model)
        modeling.build_system(model, self.SYS, zones[:3])
        modeling.build_system(model, self.SYS, zones[3:])
        facts = modeling.characterize(model, audit=None)
        groups = sorted(facts['zone_groups'], key=lambda g: sorted(g['zones']))
        self.assertEqual(2, len(groups), 'fixture: two serving systems')
        self.assertEqual(
            [['Heat Pump Loop'], ['Heat Pump Loop']],
            [list(g.get('heat_pump_source_loops') or ()) for g in groups],
            'fixture: and ONE shared source water loop')

        audit = AuditLog()
        hvac.reference_hvac(model, code='necb2020', building={'storeys': 2},
                            audit=audit)
        affected = sorted(
            tuple((e.get('inputs') or {}).get('affected_blocks') or ())
            for e in audit.entries if 'AHJ-1' in str(e.get('ahj') or ''))
        self.assertEqual(
            [tuple(sorted(groups[0]['zones'])), tuple(sorted(groups[1]['zones']))],
            affected,
            'two service sets, two disclosures, each naming its own blocks')
