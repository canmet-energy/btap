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
                    if 'RESERVED to whatever retained it' in str(e.get('action'))]
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


class TestTheMergeCitesTheNOTEThatApplies(unittest.TestCase):
    """Sol's `143` blocker 4. Table 8.4.x.7.-B marks its own notes, and the
    structured payload carries the markers in both editions even though it
    omits the note text:

        System 1   Unitary air conditioner with baseboard heating(2)
        System 2   Four-pipe fan-coil(2)
        System 3   Single-zone packaged rooftop unit with baseboard heating
        System 4   Single-zone make-up air unit with baseboard heating
        System 5   Two-pipe fan-coil(2)
        System 6(3)  Multi-zone built-up system with baseboard heating

    Note (3), on the System 6 name alone, authorizes one multizone system to
    span groups of thermal blocks. Note (2), on Systems 1, 2 and 5, authorizes
    a common VENTILATION system and distinguishes it from the block-level HVAC
    systems. A merged System 1 was audited under Note (3), citing a permission
    that is not marked on it.
    """

    MZ = MULTIZONE_PROPOSED

    def merge_entries(self, audit):
        return [e for e in audit.entries
                if 'Note (' in str(e.get('article') or '')]

    def test_system_6_cites_Note_3_and_D_28(self):
        for code in EDITIONS:
            with self.subTest(code=code):
                proposed = proposed_with_hvac(self.MZ)
                _, audit = reference_of(proposed, code=code, storeys=3)
                entries = self.merge_entries(audit)
                self.assertEqual(1, len(entries))
                self.assertIn('Note (3)', entries[0]['article'])
                self.assertEqual('D-28', entries[0]['ruling'])
                self.assertEqual(6, entries[0]['inputs']['reference_system'])

    def test_system_1_cites_Note_2_and_NOT_Note_3(self):
        for code in EDITIONS:
            with self.subTest(code=code):
                proposed = proposed_with_hvac(self.MZ)
                _, audit = reference_of(proposed, code=code, storeys=1,
                                        space_type='Dwelling unit')
                entries = self.merge_entries(audit)
                self.assertEqual(1, len(entries))
                self.assertIn('Note (2)', entries[0]['article'],
                              'Note (2) is what is marked on System 1')
                self.assertNotIn(
                    'Note (3)', entries[0]['article'],
                    "System 6's grouping permission is not System 1's")
                self.assertEqual(1, entries[0]['inputs']['reference_system'])
                self.assertIn('ventilation', entries[0]['action'].lower(),
                              'what Note (2) actually permits is a common '
                              'VENTILATION system')


class TestTheCoolingThresholdBASISIsDeclared(unittest.TestCase):
    """Sol's `143` blocker 5. Table 8.4.x.7.-A sends a Data Processing Area to
    a different system "where the proposed building or space has a cooling
    capacity exceeding" a threshold. `design_cooling_kw` is a SERVING-SYSTEM
    total, and a block view inherits it unchanged.

    Whether "building or space" means the serving system or the one thermal
    block being assigned is a Code reading D-101 does not settle. Inheriting
    the total silently would decide it by accident, so the runtime says which
    basis it used — "record a narrow, visible gap with a non-silent runtime
    consequence".

    These call `_assign` directly. The threshold is only reached on a SIZED
    model, which the selection-level fixtures are not: an unsized group takes
    the "needs a sized model" branch instead, so a pipeline test would exercise
    the wrong path.
    """

    def rule_selection(self):
        from btap.codes import resolve

        return resolve('necb2020').rules('hvac')['selection']

    def assign(self, *, zones, serving, cooling_kw):
        from btap.codes.necb.hvac import reference as ref

        group = {'zones': list(zones), 'air_loop': 'Loop 1',
                 'design_cooling_kw': cooling_kw,
                 '_serving_zones': tuple(serving),
                 'heated': True, 'cooled': True,
                 'heating_energy_types': ['Electricity'],
                 'heat_pump': False, 'heat_pump_sources': [],
                 'heat_pump_source_loops': []}
        building = {'storeys': 2,
                    'zone_types': {z: 'Computer/Server room' for z in serving}}
        audit = AuditLog()
        selection = self.rule_selection()
        category = ref._category_for(group, building, selection, audit)
        assignment = ref._assign(group, category, building, selection, audit)
        basis = [e for e in audit.entries
                 if 'threshold deciding THIS thermal block' in str(e.get('action'))]
        return assignment, basis

    def test_a_block_assigned_on_the_SERVING_SYSTEM_total_says_so(self):
        serving = ('Zone 1', 'Zone 2', 'Zone 3', 'Zone 4', 'Zone 5')
        _, basis = self.assign(zones=('Zone 1',), serving=serving,
                               cooling_kw=500.0)
        self.assertEqual(
            1, len(basis),
            'assigning ONE block from a five-block total must not be silent')
        inputs = basis[0]['inputs']
        self.assertEqual(['Zone 1'], inputs['assigned_block'])
        self.assertEqual(sorted(serving), inputs['measured_over_blocks'])
        self.assertEqual(500.0, inputs['measured_kw'])
        self.assertIn('building or space', inputs['basis'],
                      'the entry must name the unresolved term')
        self.assertEqual('D-101', basis[0]['ruling'])

    def test_a_single_block_serving_system_says_NOTHING(self):
        """The control: where the serving system IS one block, the two readings
        of "building or space" agree and there is no gap to declare.
        """
        _, basis = self.assign(zones=('Zone 1',), serving=('Zone 1',),
                               cooling_kw=500.0)
        self.assertEqual([], basis,
                         'no ambiguity, so no warning — otherwise the gap '
                         'notice becomes noise on every sized run')


class TestTheCOOLINGPlantOwnershipToo(unittest.TestCase):
    """Sol's `145` blocker 1: the reservation protected hot water only.

    `reference.py` says it reserves EVERY surviving plant and passes all their
    handles, but `builder.py` forwarded them only to `plant_loops.hot_water`.
    The chilled-water call had no exclusion, `find_chilled_water` tested no
    blocked set, and the composite recursion dropped the argument — so built
    System 2 cooling coils joined the copied block's proposed chiller plant
    while the hot-water split looked correct.
    """

    MARKER = 'PROPOSED MARKER'
    SYS = 'FPFC MAU DX Coils with Scroll Chiller'

    def mixed_proposed(self):
        """Block 1 residential (`copy_proposed`); blocks 2-5 a Museum archive,
        which Table -A sends to System 2 — a family needing BOTH plants."""
        proposed = proposed_with_hvac(self.SYS)
        zones = sorted(proposed.getThermalZones(), key=lambda z: z.nameString())
        for index, zone in enumerate(zones):
            wanted = 'Dwelling unit' if index == 0 else 'Museum archive'
            for space in zone.spaces():
                space_type = space.spaceType()
                if space_type.is_initialized():
                    clone = space_type.get().clone(proposed).to_SpaceType().get()
                    clone.setName('Block type {}'.format(index))
                    clone.setStandardsSpaceType(wanted)
                    space.setSpaceType(clone)
        for index, boiler in enumerate(sorted(proposed.getBoilerHotWaters(),
                                              key=lambda b: b.nameString())):
            boiler.setName('{} boiler {}'.format(self.MARKER, index))
        chillers = sorted(proposed.getChillerElectricEIRs(),
                          key=lambda c: c.nameString())
        self.assertTrue(chillers, 'fixture: the proposed model has chillers')
        for index, chiller in enumerate(chillers):
            chiller.setName('{} chiller {}'.format(self.MARKER, index))
        return proposed, [zone.nameString() for zone in zones]

    def plants(self, model):
        """(marked, unmarked) plant loops, split by whether a marked proposed
        device sits on the supply side."""
        marked, unmarked = [], []
        for plant in model.getPlantLoops():
            bucket = marked if any(
                self.MARKER in component.nameString()
                for component in plant.supplyComponents()) else unmarked
            bucket.append(plant)
        return marked, unmarked

    @staticmethod
    def demand(plant, kind):
        return sorted(component.nameString()
                      for component in plant.demandComponents()
                      if kind in component.nameString())

    def test_the_copied_block_keeps_its_CHILLER_plant_alone(self):
        proposed, blocks = self.mixed_proposed()
        reference, audit = reference_of(proposed, storeys=1)

        retained = [e for e in audit.entries
                    if 'retained in reference' in str(e.get('action'))]
        self.assertEqual(1, len(retained), 'fixture: one copy_proposed block')
        self.assertEqual(blocks[0], str(retained[0].get('target')))

        marked, unmarked = self.plants(reference)
        marked_chilled = [p for p in marked if self.demand(p, 'Coil Cooling')]
        self.assertEqual(
            1, len(marked_chilled),
            'the proposed chiller plant must survive for the copied block')
        self.assertEqual(
            ['Coil Cooling Water 1'], self.demand(marked_chilled[0], 'Coil Cooling'),
            'and ONLY the copied block may draw on it — five more cooling '
            'coils here was the defect')

        built_chilled = [p for p in unmarked if self.demand(p, 'Coil Cooling')]
        self.assertEqual(
            1, len(built_chilled),
            'the built blocks need a separately planned reference chiller plant')
        built_coils = self.demand(built_chilled[0], 'Coil Cooling')
        self.assertNotIn(
            'Coil Cooling Water 1', built_coils,
            "the copied block's coil stays on the retained plant")
        # Five, not four: System 2 builds one coil per block PLUS the Note (2)
        # make-up air unit's coil. The count is not the point — the ownership
        # split is — so it is asserted as "every remaining coil".
        self.assertEqual(
            5, len(built_coils),
            'four block coils plus the common make-up air coil')

    def test_BOTH_plants_split_the_same_way(self):
        """Hot and chilled must agree: a fix to one is not a fix to the other,
        which is exactly how this defect hid behind a passing hot-water test.
        """
        proposed, _ = self.mixed_proposed()
        reference, _ = reference_of(proposed, storeys=1)
        marked, unmarked = self.plants(reference)
        self.assertEqual(
            [1, 1],
            [len(self.demand(p, 'Coil Heating Water')) for p in marked
             if self.demand(p, 'Coil Heating Water')]
            + [len(self.demand(p, 'Coil Cooling Water')) for p in marked
               if self.demand(p, 'Coil Cooling Water')],
            'each marked plant serves exactly the one copied block')
        # Only plants that serve ZONE COILS are compared. A water-cooled
        # chiller sits on its condenser loop's DEMAND side, so the proposed
        # condenser loop legitimately carries a marked device and is not a
        # reference plant adopting proposed equipment.
        for plant in unmarked:
            coils = (self.demand(plant, 'Coil Heating Water')
                     + self.demand(plant, 'Coil Cooling Water'))
            if not coils:
                continue
            for name in coils:
                self.assertNotIn(
                    self.MARKER, name,
                    'no proposed device may appear on a reference plant')


class TestTheUnsizedWarningDoesNotDependOnORDER(unittest.TestCase):
    """Sol's `145` blocker 2.

    The unsized-threshold warning was emitted only from the block marked
    `_first_block`, but an office block never VISITS the data-processing
    threshold rule. So with the office first the warning vanished entirely,
    and with the data block first it fired while claiming both blocks were
    assigned on that basis. Selection order cannot decide whether a material
    assumption is disclosed.
    """

    MZ = MULTIZONE_PROPOSED

    def run_with(self, data_indices):
        proposed = proposed_with_hvac(self.MZ)
        zones = sorted(proposed.getThermalZones(), key=lambda z: z.nameString())
        for index, zone in enumerate(zones):
            wanted = ('Computer/Server room' if index in data_indices
                      else 'Office - enclosed')
            for space in zone.spaces():
                space_type = space.spaceType()
                if space_type.is_initialized():
                    clone = space_type.get().clone(proposed).to_SpaceType().get()
                    clone.setName('Block type {}'.format(index))
                    clone.setStandardsSpaceType(wanted)
                    space.setSpaceType(clone)
        names = [zone.nameString() for zone in zones]
        _, audit = reference_of(proposed, storeys=2)
        hits = [e for e in audit.entries
                if 'needs a sized model' in str(e.get('action'))]
        return names, hits

    def test_a_LATER_data_block_is_still_disclosed(self):
        """Office first. This emitted NOTHING."""
        names, hits = self.run_with({4})
        self.assertEqual(1, len(hits),
                         'the assumption must be disclosed wherever the data '
                         'block sorts')
        self.assertEqual([names[4]],
                         hits[0]['inputs']['blocks_assigned_on_this_basis'])

    def test_a_FIRST_data_block_does_not_over_claim(self):
        """Data first. This claimed every block on the serving system."""
        names, hits = self.run_with({0})
        self.assertEqual(1, len(hits))
        self.assertEqual([names[0]],
                         hits[0]['inputs']['blocks_assigned_on_this_basis'],
                         'only the block whose smaller-system branch was '
                         'assumed')

    def test_SEVERAL_data_blocks_are_aggregated_into_one_entry(self):
        names, hits = self.run_with({1, 3})
        self.assertEqual(1, len(hits), 'one serving system, one entry')
        self.assertEqual([names[1], names[3]],
                         hits[0]['inputs']['blocks_assigned_on_this_basis'])

    def test_NO_data_block_says_nothing(self):
        """The control: the rule is never reached, so there is no assumption to
        disclose and the entry must not appear at all.
        """
        _, hits = self.run_with(set())
        self.assertEqual([], hits)


class TestAPlantKeptAliveByNONZONEDemand(unittest.TestCase):
    """Sol's `147` blocker 1: the reservation was gated on `copy_proposed`.

    `remove_hvac_from_zones` drops a plant only when its DEMAND SIDE empties,
    and zone coils are not the only demand. A `WaterUseConnections` carrying
    process or service water keeps the proposed loop alive with no copied
    block anywhere in the model — and the reservation, which only ran when an
    assignment was `copy_proposed`, never fired. Every newly built reference
    baseboard then joined the proposed plant, with both marked fuels on it.

    The process demand IS entitled to keep that loop. The built blocks are not
    entitled to join it, and what retained the plant does not change that.
    """

    MARKER = 'PROPOSED MARKER'

    def proposed_with_process_water(self):
        import openstudio

        proposed = proposed_with_hvac('Baseboard gas boiler')
        boilers = sorted(proposed.getBoilerHotWaters(),
                         key=lambda b: b.nameString())
        self.assertGreater(len(boilers), 1, 'fixture: a multi-boiler plant')
        loop = boilers[0].plantLoop()
        self.assertTrue(loop.is_initialized(), 'fixture: the boilers have a loop')
        loop = loop.get()
        boilers[0].setFuelType('Electricity')
        for index, boiler in enumerate(boilers):
            boiler.setName('{} boiler {}'.format(self.MARKER, index))

        definition = openstudio.model.WaterUseEquipmentDefinition(proposed)
        definition.setName('PROCESS WATER DEF')
        definition.setPeakFlowRate(0.001)
        equipment = openstudio.model.WaterUseEquipment(definition)
        equipment.setName('PROCESS WATER LOAD')
        connections = openstudio.model.WaterUseConnections(proposed)
        connections.setName('PROCESS WATER CONNECTIONS')
        connections.addWaterUseEquipment(equipment)
        loop.addDemandBranchForComponent(connections)
        return proposed

    def test_no_built_block_joins_a_plant_kept_alive_by_process_water(self):
        proposed = self.proposed_with_process_water()
        reference, audit = reference_of(proposed, storeys=2)

        self.assertEqual(
            [], [e for e in audit.entries
                 if 'retained in reference' in str(e.get('action'))],
            'fixture precondition: NO copy_proposed assignment — every block '
            'is rebuilt, which is what made the old gate miss this')

        marked, unmarked = [], []
        for plant in reference.getPlantLoops():
            bucket = marked if any(self.MARKER in c.nameString()
                                   for c in plant.supplyComponents()) else unmarked
            bucket.append(plant)
        self.assertEqual(1, len(marked),
                         'the proposed plant survives, as the process demand '
                         'entitles it to')

        demand = sorted(c.nameString() for c in marked[0].demandComponents()
                        if 'Baseboard' in c.nameString()
                        or 'PROCESS WATER CONNECTIONS' in c.nameString())
        self.assertEqual(
            ['PROCESS WATER CONNECTIONS'], demand,
            'and ONLY the demand that retained it — five reference baseboards '
            'here was the defect')

        built = [p for p in unmarked
                 if any('Boiler' in c.nameString() for c in p.supplyComponents())]
        self.assertEqual(1, len(built),
                         'the five built blocks need a reference plant')
        self.assertEqual(
            5, len([c for c in built[0].demandComponents()
                    if 'Baseboard' in c.nameString()]),
            'all five of them on it')

    def test_the_reservation_is_audited_without_any_copied_block(self):
        proposed = self.proposed_with_process_water()
        _, audit = reference_of(proposed, storeys=2)
        reserved = [e for e in audit.entries
                    if 'RESERVED to whatever retained it' in str(e.get('action'))]
        self.assertEqual(1, len(reserved),
                         'the ownership decision must be visible here too')
        inputs = reserved[0].get('inputs') or {}
        self.assertEqual(0, inputs.get('copied_blocks'),
                         'no copied block, and the reservation still applies')
        self.assertEqual(5, inputs.get('replaced_blocks'))


class TestAHETEROGENEOUSMergeAuditsOnlyWhatMerged(unittest.TestCase):
    """Sol's `147` blocker 2: one global `len(merged) < len(assignments)` gate.

    It says only that SOMETHING merged. `collapsed` was then filled from every
    keyed survivor, so a family that survived as ONE assignment was reported as
    a merge — a Note (2) record claiming a common ventilation system for a
    single thermal block. The homogeneous Note (2) and Note (3) tests pass
    because every family in those fixtures really does merge; they cannot see
    this composition boundary.
    """

    MZ = MULTIZONE_PROPOSED

    def test_a_singleton_System_2_beside_merging_System_6_is_not_audited(self):
        proposed = proposed_with_hvac(self.MZ)
        zones = sorted(proposed.getThermalZones(), key=lambda z: z.nameString())
        for index, zone in enumerate(zones):
            wanted = 'Museum archive' if index == 0 else 'Office - enclosed'
            for space in zone.spaces():
                space_type = space.spaceType()
                if space_type.is_initialized():
                    clone = space_type.get().clone(proposed).to_SpaceType().get()
                    clone.setName('Block type {}'.format(index))
                    clone.setStandardsSpaceType(wanted)
                    space.setSpaceType(clone)
        _, audit = reference_of(proposed, storeys=5)

        systems = selected_systems(audit)
        self.assertEqual(
            {'System 2': 1, 'System 6': 4},
            {name: systems.count(name) for name in sorted(set(systems))},
            'fixture precondition: ONE System 2 block beside four that merge')

        merges = [e for e in audit.entries
                  if 'Note (' in str(e.get('article') or '')]
        self.assertEqual(
            1, len(merges),
            'only System 6 merged, so only System 6 is audited; got {}'.format(
                [(e['inputs'].get('reference_system'), e['article'])
                 for e in merges]))
        self.assertEqual(6, merges[0]['inputs']['reference_system'])
        self.assertIn('Note (3)', merges[0]['article'])
        self.assertEqual(4, merges[0]['inputs']['thermal_blocks_spanned'])


class TestTWOMergedSystem6ConstructionsStaySEPARATE(unittest.TestCase):
    """Sol's `149`: measuring multiplicity per merge key and then grouping the
    survivors by `reference_system` throws that identity away again.

    Two independent proposed serving systems whose blocks all select System 6 —
    a gas hot-water variant over three blocks and an electric variant over two
    — are two legitimate Note (3) merges. They cannot become one construction,
    because their heating realisations differ. The audit claimed ONE system
    spanned all five, with `merged_groups: 2` beside a singular value
    contradicting it, erasing the gas/electric boundary an AHJ-facing audit has
    to preserve.
    """

    GAS = 'MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard'
    ELECTRIC = ('MZ BU RTU Electric Heating Coil Scroll Chiller and '
                'Electric Baseboard')

    def two_service_sets(self):
        from btap import modeling

        from .hvac_helpers import load_fixture, sorted_zones

        model = load_fixture()
        zones = sorted_zones(model)
        modeling.build_system(model, self.GAS, zones[:3])
        modeling.build_system(model, self.ELECTRIC, zones[3:])
        facts = modeling.characterize(model, audit=None)
        self.assertEqual(2, len(facts['zone_groups']),
                         'fixture precondition: two proposed serving systems')
        return model, [zone.nameString() for zone in zones]

    def test_each_merged_construction_gets_its_OWN_record(self):
        model, blocks = self.two_service_sets()
        # 5 storeys sends every block to System 6.
        _, audit = reference_of(model, storeys=5)
        systems = selected_systems(audit)
        self.assertEqual(['System 6'] * 5, systems,
                         'fixture precondition: all five select System 6')

        merges = [e for e in audit.entries
                  if 'Note (' in str(e.get('article') or '')]
        self.assertEqual(
            2, len(merges),
            'two distinct catalogue realisations are two merges, not one')

        by_blocks = {tuple(e['inputs']['thermal_blocks']): e for e in merges}
        self.assertEqual(
            [tuple(blocks[:3]), tuple(blocks[3:])],
            sorted(by_blocks),
            'each record names its OWN blocks')

        gas = by_blocks[tuple(blocks[:3])]
        electric = by_blocks[tuple(blocks[3:])]
        self.assertEqual(3, gas['inputs']['selection_assignments_absorbed'])
        self.assertEqual(2, electric['inputs']['selection_assignments_absorbed'])
        self.assertIn('Hot Water', gas['inputs']['catalogue'])
        self.assertIn('Electric', electric['inputs']['catalogue'])

        # And no record may claim a system spanning the union.
        for entry in merges:
            self.assertNotEqual(
                len(blocks), entry['inputs']['thermal_blocks_spanned'],
                'no single System 6 realisation spans all five blocks')

    def test_the_counts_are_the_RECORD_scope_not_the_building(self):
        """`selection_groups`/`merged_groups` were whole-building numbers in a
        per-key record, which invites the same conflation from the other side.
        """
        model, _ = self.two_service_sets()
        _, audit = reference_of(model, storeys=5)
        for entry in [e for e in audit.entries
                      if 'Note (' in str(e.get('article') or '')]:
            inputs = entry['inputs']
            self.assertNotIn('selection_groups', inputs)
            self.assertNotIn('merged_groups', inputs)
            self.assertEqual(
                inputs['thermal_blocks_spanned'], len(inputs['thermal_blocks']),
                'the span is this record\'s own block list')
            self.assertEqual(
                inputs['selection_assignments_absorbed'],
                len(inputs['thermal_blocks']),
                'and each absorbed assignment was one thermal block')


class TestSAMECatalOGUEDifferentCONFIGKeepsItsFuel(unittest.TestCase):
    """Sol's `151`: the merge key stopped before plant reuse.

    Systems 2 and 5 use ONE catalogue name for their gas and electric
    variants; the variants differ in `config`. The merge pass kept the keys
    separate, and the builder then joined both assignments to whichever boiler
    plant was built first, because `find_hot_water` matched source, exclusion
    and part-load class but NOT the requested fuel — and its name fallback was
    likewise fuel-blind. The second assignment's config never reached plant
    construction.

    Renaming only the PROPOSED air loops, which `characterize()` sorts, then
    flipped the whole reference plant:

        A Gas / Z Electric   ->  one plant, NaturalGas only
        A Electric / Z Gas   ->  one plant, Electricity only

    One single-energy proposed service therefore got the wrong reference energy
    source, chosen by a display name, with ZERO AHJ records — each service set
    is individually single-energy, so AHJ-1 correctly does not fire and cannot
    make the substitution conditional. That is the assignment-order dependence
    D-101 removed on the teardown side, surviving on the construction side.
    """

    GAS = 'MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard'
    ELECTRIC = ('MZ BU RTU Electric Heating Coil Scroll Chiller and '
                'Electric Baseboard')

    def build(self, *, gas_loop_name, electric_loop_name, code):
        from btap import modeling

        from .hvac_helpers import load_fixture, sorted_zones

        model = load_fixture()
        zones = sorted_zones(model)
        # Museum archive sends every block to System 2, whose gas and electric
        # variants share a catalogue name.
        for space_type in model.getSpaceTypes():
            if space_type.spaces():
                space_type.setStandardsSpaceType('Museum archive')
        gas = modeling.build_system(model, self.GAS, zones[:3])
        electric = modeling.build_system(model, self.ELECTRIC, zones[3:])
        for loop in gas.air_loops:
            loop.setName(gas_loop_name)
        for loop in electric.air_loops:
            loop.setName(electric_loop_name)
        audit = AuditLog()
        result = hvac.reference_hvac(model, code=code,
                                     building={'storeys': 5}, audit=audit)
        return result.model, audit, [z.nameString() for z in zones]

    @staticmethod
    def boiler_plants(model):
        """(fuel, served heating coils) per reference boiler plant."""
        out = []
        for plant in model.getPlantLoops():
            fuels = sorted(
                component.to_BoilerHotWater().get().fuelType()
                for component in plant.supplyComponents()
                if component.to_BoilerHotWater().is_initialized())
            if not fuels:
                continue
            coils = len([c for c in plant.demandComponents()
                         if 'Coil Heating Water' in c.nameString()])
            out.append((fuels[0], coils))
        return sorted(out)

    def test_each_config_gets_its_own_plant_whatever_sorts_first(self):
        for code in EDITIONS:
            for label, gas_name, electric_name in (
                    ('gas sorts first', 'A Gas', 'Z Electric'),
                    ('electric sorts first', 'Z Gas', 'A Electric')):
                with self.subTest(code=code, order=label):
                    model, _, _ = self.build(gas_loop_name=gas_name,
                                             electric_loop_name=electric_name,
                                             code=code)
                    self.assertEqual(
                        [('Electricity', 2), ('NaturalGas', 3)],
                        self.boiler_plants(model),
                        'one NaturalGas plant for blocks 1-3 and one '
                        'Electricity plant for blocks 4-5, under EITHER '
                        'proposed loop name — a display name must not choose '
                        "a service's reference energy source")

    def test_the_record_carries_the_CONFIG_that_separates_the_keys(self):
        """Sol's second point: the records exposed the same system and
        catalogue with nothing saying why they were separate. The System 6
        fixture cannot catch this — its variants have different catalogue
        names.
        """
        _, audit, blocks = self.build(gas_loop_name='A Gas',
                                      electric_loop_name='Z Electric',
                                      code='necb2020')
        merges = [e for e in audit.entries
                  if 'Note (' in str(e.get('article') or '')]
        self.assertEqual(2, len(merges))
        by_blocks = {tuple(e['inputs']['thermal_blocks']): e['inputs']
                     for e in merges}
        gas = by_blocks[tuple(blocks[:3])]
        electric = by_blocks[tuple(blocks[3:])]

        self.assertEqual(gas['catalogue'], electric['catalogue'],
                         'precondition: the catalogue name does NOT separate '
                         'these two records')
        self.assertEqual('gas', gas['energy_type'])
        self.assertEqual('electric', electric['energy_type'])
        self.assertEqual({'boiler_fuel': 'Electricity'}, electric['config'],
                         'the config is what separates them, so the record '
                         'must carry it')
        self.assertIsNone(gas['config'])


class TestAnOMITTEDBackupOnlyNeedsItsFuelPresent(unittest.TestCase):
    """The fuel check that fixed Sol's `151` was EQUALITY first, and the frozen
    corpus caught it where this suite did not.

    This class was called `...IsASUBSETRule` for one round. Subset was the
    second wrong answer — it loses order and multiplicity, which is Sol's
    `153`. The rule these cases actually pin is the OMITTED-backup half: a
    caller that supplies no backup is attaching demand to whatever plant
    realises its fuel, so it needs that fuel present and nothing more.
    `TestAnEXPLICITBackupIsAnORDEREDRealization` pins the other half.

    Sample 11 is generated by building a mixed gas-lead/electric-backup plant
    and THEN building `Baseboard gas boiler`, which asks for NaturalGas and
    must JOIN that mixed plant — being a mixed-fuel plant the reference keeps
    unchanged is the entire point of the sample. Under equality the gas request
    refused `{NaturalGas, Electricity}` and built a second plant, so sample 11
    stopped being multi-energy and AHJ-1/AHJ-3 stopped firing on the only
    corpus model that witnesses them. The freeze refused the baseline:

        determination-02: ahj_ids is ['AHJ-14', 'AHJ-15'],
                          expected ['AHJ-1', 'AHJ-3', 'AHJ-14']

    So an omitted backup requires only that the fuel be PRESENT.
    """

    def test_a_gas_caller_JOINS_a_mixed_gas_electric_plant(self):
        import openstudio

        from btap.modeling.hvac.systems import plant_loops

        model = openstudio.model.Model()
        mixed = plant_loops.hot_water(model, fuel='NaturalGas',
                                      backup_fuel='Electricity', reuse=False)
        self.assertEqual(['NaturalGas', 'Electricity'],
                         plant_loops.boiler_fuels(mixed),
                         'precondition: one mixed-fuel plant')

        again = plant_loops.hot_water(model, fuel='NaturalGas')
        self.assertEqual(
            str(mixed.handle()), str(again.handle()),
            'a NaturalGas caller must JOIN the mixed plant: the fuel it asked '
            'for is already there')
        self.assertEqual(1, len([p for p in model.getPlantLoops()
                                 if plant_loops.boiler_fuels(p)]),
                         'and no second plant is built')

    def test_an_electric_caller_does_NOT_join_a_gas_only_plant(self):
        """The other half, which is what `151` required. Subset must still
        refuse an incompatible fuel in either direction.
        """
        import openstudio

        from btap.modeling.hvac.systems import plant_loops

        model = openstudio.model.Model()
        gas = plant_loops.hot_water(model, fuel='NaturalGas', reuse=False)
        electric = plant_loops.hot_water(model, fuel='Electricity')
        self.assertNotEqual(
            str(gas.handle()), str(electric.handle()),
            'an Electricity caller may not adopt a NaturalGas-only plant')
        self.assertEqual(
            [['Electricity', 'Electricity'], ['NaturalGas', 'NaturalGas']],
            sorted(plant_loops.boiler_fuels(p) for p in model.getPlantLoops()
                   if plant_loops.boiler_fuels(p)),
            'two single-fuel plants, one per requested realisation')

    def test_the_mixed_plant_shape_SURVIVES_the_reference_build(self):
        """And end to end, on sample 11's own shape: the group stays
        multi-energy, so the disclosure that depends on it still fires.
        """

        from btap import modeling
        from btap.modeling.hvac.systems import plant_loops

        from .hvac_helpers import load_fixture, sorted_zones

        model = load_fixture()
        loop = plant_loops.hot_water(model, fuel='NaturalGas',
                                     backup_fuel='Electricity', reuse=False)
        loop.setLoadDistributionScheme('SequentialLoad')
        modeling.build_system(model, 'Baseboard gas boiler',
                              sorted_zones(model))
        facts = modeling.characterize(model, audit=None)
        hot = [p for p in facts['plants'] if p['type'] == 'hot_water']
        self.assertEqual(
            1, len(hot),
            'ONE hot-water plant, mixed: {}'.format(
                [(p['name'], p['fuels']) for p in hot]))
        self.assertEqual({'NaturalGas', 'Electricity'}, set(hot[0]['fuels']))

        audit = AuditLog()
        hvac.reference_hvac(model, code='necb2020', building={'storeys': 1},
                            audit=audit)
        cited = {token for entry in audit.entries
                 for token in str(entry.get('ahj') or '').split()}
        self.assertIn('AHJ-1', cited,
                      'the group is multi-energy, so the allocation question '
                      'must still be raised')
        self.assertIn('AHJ-3', cited,
                      'and one plant carries both fuels, so the cardinality '
                      'question must too')


class TestAnEXPLICITBackupIsAnORDEREDRealization(unittest.TestCase):
    """Sol's `153`: a fuel SET is not a primary/secondary realization.

    Subset fixed `151` and lost both order and multiplicity, so a caller asking
    for an explicit gas-lead/electric-backup plant reused a plant whose roles
    were REVERSED, and an explicit gas/gas request was satisfied by one gas and
    one electric boiler. The roles are not display labels: the builder stamps
    `btap_plant_role`, D-90's staging pass consumes it, and 8.4.x.9.(5)(b)
    makes cross-energy operating priority substantive — so adopting the
    reversal changes which fuel occupies which role before staging runs.

    `backup_fuel` therefore carries meaning. Omitted, the caller is attaching
    demand to whatever plant realises its fuel and needs only that fuel
    PRESENT. Supplied, it is an ordered two-role realization and both roles
    must match in order.
    """

    GAS = 'NaturalGas'
    ELECTRIC = 'Electricity'

    def reuse(self, existing, requested):
        """Build `existing` as a staged pair, then ask for `requested`.

        Returns (reused, boiler_plant_count).
        """
        import openstudio

        from btap.modeling.hvac.systems import plant_loops

        model = openstudio.model.Model()
        first = plant_loops.hot_water(model, fuel=existing[0],
                                      backup_fuel=existing[1], reuse=False)
        self.assertEqual(list(existing), plant_loops.boiler_fuels(first),
                         'precondition: the staged pair is in the order asked')
        got = plant_loops.hot_water(model, fuel=requested[0],
                                    backup_fuel=requested[1])
        plants = len([p for p in model.getPlantLoops()
                      if plant_loops.boiler_fuels(p)])
        return str(got.handle()) == str(first.handle()), plants

    def test_a_REVERSED_pair_is_not_the_same_plant(self):
        for existing, requested in (
                ((self.GAS, self.ELECTRIC), (self.ELECTRIC, self.GAS)),
                ((self.ELECTRIC, self.GAS), (self.GAS, self.ELECTRIC))):
            with self.subTest(existing=existing, requested=requested):
                reused, plants = self.reuse(existing, requested)
                self.assertFalse(
                    reused,
                    'the same two fuels in the opposite roles are a different '
                    'plant realization')
                self.assertEqual(2, plants, 'so a second plant is built')

    def test_an_explicit_SAME_FUEL_pair_is_not_a_mixed_pair(self):
        """Multiplicity, not just order: gas/gas asks for TWO gas-fired
        positions and a mixed plant supplies one.
        """
        reused, plants = self.reuse((self.GAS, self.ELECTRIC),
                                    (self.GAS, self.GAS))
        self.assertFalse(reused)
        self.assertEqual(2, plants)

    def test_an_OMITTED_backup_only_needs_its_fuel_present(self):
        """The sample 11 and sample 12 shapes, in both orientations. This is
        what plain equality broke, and the frozen corpus caught it.
        """
        for existing in ((self.GAS, self.ELECTRIC), (self.ELECTRIC, self.GAS)):
            with self.subTest(existing=existing):
                reused, plants = self.reuse(existing, (self.GAS, None))
                self.assertTrue(
                    reused,
                    'a caller with no backup is attaching demand, not '
                    'electing the other role')
                self.assertEqual(1, plants, 'and no second plant is built')

    def test_a_MATCHING_ordered_pair_still_shares_one_plant(self):
        """The control: ordered matching must not stop same-config assignments
        sharing a planned plant.
        """
        reused, plants = self.reuse((self.GAS, self.ELECTRIC),
                                    (self.GAS, self.ELECTRIC))
        self.assertTrue(reused)
        self.assertEqual(1, plants)

    def test_a_HALF_MARKED_pair_refuses_an_explicit_match(self):
        """`153`: unknown order must not silently count as a match.

        This was called `..._an_UNMARKED_imported_pair_...`, which named the
        wrong thing: a WHOLLY unmarked two-boiler plant DOES establish its
        order, by the loop's supply order — D-90's third source, and what lets
        an imported pair match at all. What is refused is a HALF-marked pair,
        where one boiler claims a role and the other does not, so no
        primary/secondary assignment is established (Sol, `155`).
        """
        import openstudio

        from btap.modeling.hvac.systems import plant_loops

        model = openstudio.model.Model()
        loop = plant_loops.hot_water(model, fuel=self.GAS,
                                     backup_fuel=self.ELECTRIC, reuse=False)
        boilers = [c.to_BoilerHotWater().get()
                   for c in loop.supplyComponents(
                       openstudio.model.BoilerHotWater.iddObjectType())]
        # Strip one role mark and rename both away from the conventional
        # names, leaving the pair half-marked.
        boilers[1].additionalProperties().resetFeature(
            plant_loops.BOILER_PLANT_ROLE_FEATURE)
        boilers[1].setName('Imported Boiler B')
        got = plant_loops.hot_water(model, fuel=self.GAS,
                                    backup_fuel=self.ELECTRIC)
        self.assertNotEqual(
            str(loop.handle()), str(got.handle()),
            'a half-marked pair has no established order, so an explicit '
            'ordered request must not adopt it')

    def test_a_WHOLLY_unmarked_pair_DOES_match_by_supply_order(self):
        """The control the rename needs, and D-90's third source.

        Two unmarked boilers on one loop ARE the pair, ordered by the loop's
        own supply order, so an explicit request matching that order reuses the
        plant. Without this case the refusal above would read as "imported
        pairs never match", which is not the contract.
        """
        import openstudio

        from btap.modeling.hvac.systems import plant_loops

        model = openstudio.model.Model()
        loop = plant_loops.hot_water(model, fuel=self.GAS,
                                     backup_fuel=self.ELECTRIC, reuse=False)
        boilers = [c.to_BoilerHotWater().get()
                   for c in loop.supplyComponents(
                       openstudio.model.BoilerHotWater.iddObjectType())]
        for index, boiler in enumerate(boilers):
            boiler.additionalProperties().resetFeature(
                plant_loops.BOILER_PLANT_ROLE_FEATURE)
            boiler.setName('Imported Boiler {}'.format(index))
        self.assertEqual(
            [self.GAS, self.ELECTRIC], plant_loops.boiler_fuels(loop),
            'precondition: unmarked, gas then electric in supply order')

        same = plant_loops.hot_water(model, fuel=self.GAS,
                                     backup_fuel=self.ELECTRIC)
        self.assertEqual(str(loop.handle()), str(same.handle()),
                         'supply order establishes the roles, so the matching '
                         'request reuses the plant')
        reversed_ = plant_loops.hot_water(model, fuel=self.ELECTRIC,
                                          backup_fuel=self.GAS)
        self.assertNotEqual(str(loop.handle()), str(reversed_.handle()),
                            'and the reversed request still does not')


class TestTheCOOLINGSourceGuardFalsifies(unittest.TestCase):
    """Fable's `158` F6: `find_chilled_water(source=...)` had no falsifying
    test.

    `chilled_water` documents that "a caller asking for district cooling must
    never be handed a chiller loop, and vice versa" — the cooling analogue of
    the hot-water source guard, which exists because 8.4.4.6.(1)(a) was once
    half-applied by exactly that adoption. Mutation M3 replaced the source
    comparison with a bare chiller-presence test and the whole targeted set of
    186 tests stayed green.
    """

    def loops(self, model):
        from btap.modeling.hvac.systems import plant_loops

        return [(p.nameString(), plant_loops._cooling_source(p))
                for p in model.getPlantLoops()
                if plant_loops._cooling_source(p) is not None]

    def test_a_district_caller_is_not_handed_a_CHILLER_loop(self):
        import openstudio

        from btap.modeling.hvac.systems import plant_loops

        model = openstudio.model.Model()
        chilled = plant_loops.chilled_water(model, source='water_cooled',
                                            reuse=False)
        self.assertEqual('water_cooled',
                         plant_loops._cooling_source(chilled),
                         'precondition: a chiller loop exists')
        district = plant_loops.chilled_water(model, source='district')
        self.assertNotEqual(
            str(chilled.handle()), str(district.handle()),
            'a district-cooling caller must build its own loop, not adopt '
            'chillers')
        self.assertEqual(
            'district', plant_loops._cooling_source(district),
            'and what it built is district-cooled')

    def test_a_CHILLER_caller_is_not_handed_a_district_loop(self):
        """And the other direction, which is the half the hot-water side
        learned the hard way.
        """
        import openstudio

        from btap.modeling.hvac.systems import plant_loops

        model = openstudio.model.Model()
        district = plant_loops.chilled_water(model, source='district',
                                             reuse=False)
        self.assertEqual('district', plant_loops._cooling_source(district),
                         'precondition: a district-cooling loop exists')
        chilled = plant_loops.chilled_water(model, source='water_cooled')
        self.assertNotEqual(
            str(district.handle()), str(chilled.handle()),
            'a chiller caller must not adopt a district loop')
        self.assertEqual('water_cooled',
                         plant_loops._cooling_source(chilled))

    def test_a_MATCHING_source_still_shares_one_loop(self):
        """The control: source matching must not stop legitimate reuse."""
        import openstudio

        from btap.modeling.hvac.systems import plant_loops

        model = openstudio.model.Model()
        first = plant_loops.chilled_water(model, source='water_cooled',
                                          reuse=False)
        again = plant_loops.chilled_water(model, source='water_cooled')
        self.assertEqual(str(first.handle()), str(again.handle()))


class TestTheAHJ1ACTIONTextDoesNotOfferAdoption(unittest.TestCase):
    """Sol's `160` blocker 1: the withdrawn outcome was still in the live
    warning's ACTION, which is what reaches an authority.

    `inputs['live_capacity_outcome']` was corrected, the code comment beside
    it said adoption is no longer an outcome, AHJ-1's register entry said
    `adopted` was removed, and D-101 said a retained block never reaches this
    disclosure — while the action string one line away still said the
    reference plant depends "on whether the plant is adopted or torn down".
    It appeared in four frozen audits, and `determination-02` copied it into
    every AHJ-1 condition's `detail` and into the report warnings, so the
    AHJ-facing artifact stated the withdrawn outcome five times.

    Pinning the ACTION, not just the inputs, because the action is the text a
    reader sees first and the one surface the earlier sweep missed.
    """

    def disclosure(self):
        from btap.audit import AuditLog
        from btap.codes.necb.hvac import reference as ref

        plant = {'name': 'Hot Water Loop', 'type': 'hot_water',
                 'fuels': ['NaturalGas', 'Electricity'], 'boiler_count': 2,
                 'fuel_capacities_w': {'NaturalGas': None, 'Electricity': None}}
        facts = {'plants': [plant], 'purchased_energy': {}}
        group = {'zones': ['Zone 1'],
                 'heating_energy_types': ['NaturalGas', 'Electricity']}
        selection = {'special_rules': {
            'purchased_heating': {'article': '8.4.4.6.(1)',
                                  'part_load_curve_class': 'modulating'},
            'heat_pump': {'article': '8.4.4.13.(1)-(2)'}}}
        audit = AuditLog()
        ref._disclose_multi_energy(group, selection, facts, audit)
        found = [e for e in audit.entries
                 if 'AHJ-1' in str(e.get('ahj') or '')]
        self.assertEqual(1, len(found), 'precondition: the disclosure fired')
        return found[0]

    def test_the_action_does_not_say_the_plant_may_be_adopted(self):
        entry = self.disclosure()
        action = str(entry['action'])
        self.assertIn('MORE THAN ONE ENERGY', action,
                      'precondition: this is the allocation disclosure')
        self.assertNotIn(
            'adopted', action.lower(),
            'the action a reader sees first must not offer an outcome the '
            'branch made unreachable')

    def test_the_inputs_do_not_offer_it_either(self):
        """The half that was already right, kept as a control so a future
        edit cannot reintroduce it on the other surface.
        """
        inputs = self.disclosure()['inputs']
        self.assertNotIn('adopted',
                         str(inputs.get('live_capacity_outcome')).lower())
        self.assertIn('DIFFERENT plant',
                      str(inputs.get('live_capacity_outcome')),
                      'replacement is still listed')


class TestAMergedConstructionKeepsPERBLOCKActions(unittest.TestCase):
    """Sol's `160` blocker 2, which is Fable's F8 reproduced.

    The merge keys on `[catalogue, config]` and NOT on `action`, deliberately:
    adding action would split one Note (2) common ventilation system into two
    central MAUs. So one construction can legitimately cover blocks whose
    SELECTION branches differed — an unsized Data Processing block falls back
    to System 1 with `action='build'`, and a cooled Multi-unit residential
    block reaches System 1 with `action='through_the_wall'` — and both resolve
    to the same gas System 1 catalogue and config.

    The construction then published `assignment.action`, a scalar that is the
    FIRST absorbed assignment's branch, for a record targeting both blocks.
    Swapping which block sorted first changed the published provenance while
    the model stayed one MAU over the same two blocks.
    """

    VAV = MULTIZONE_PROPOSED

    def build(self, *, data_first, code):
        proposed = proposed_with_hvac(self.VAV)
        zones = sorted(proposed.getThermalZones(), key=lambda z: z.nameString())
        for extra in zones[2:]:
            extra.remove()
        kept = zones[:2]
        for index, zone in enumerate(kept):
            is_data = (index == 0) if data_first else (index == 1)
            wanted = ('Computer/Server room' if is_data
                      else 'Multi-unit residential')
            for space in zone.spaces():
                space_type = space.spaceType()
                if space_type.is_initialized():
                    clone = space_type.get().clone(proposed).to_SpaceType().get()
                    clone.setName('Block type {}'.format(index))
                    clone.setStandardsSpaceType(wanted)
                    space.setSpaceType(clone)
        names = [zone.nameString() for zone in kept]
        audit = AuditLog()
        result = hvac.reference_hvac(proposed, code=code,
                                     building={'storeys': 1}, audit=audit)
        built = [e for e in audit.entries
                 if e.get('action') == 'reference system built']
        data_block = names[0] if data_first else names[1]
        residential = names[1] if data_first else names[0]
        return result, built, data_block, residential

    def test_one_construction_and_truthful_per_block_actions(self):
        for code in EDITIONS:
            for data_first in (True, False):
                with self.subTest(code=code, data_first=data_first):
                    result, built, data_block, residential = self.build(
                        data_first=data_first, code=code)

                    # 1. one System 1 construction in BOTH orders
                    self.assertEqual(1, len(built),
                                     'one merged Note (2) construction')
                    self.assertEqual(
                        1, len(result.model.getAirLoopHVACs()),
                        'and one central make-up air unit, not two — adding '
                        'action to the merge key would split it')

                    inputs = built[0]['inputs']
                    actions = inputs['source_actions']

                    # 2 and 3. each block keeps its OWN selection branch
                    self.assertEqual(
                        'build', actions[data_block],
                        'the Data Processing block fell back to System 1 by '
                        'the build branch, whichever order it sorted in')
                    self.assertEqual(
                        'through_the_wall', actions[residential],
                        'and the residential block reached System 1 through '
                        'the through-the-wall branch')

                    # 4. no scalar first-action is attributed to both
                    self.assertNotIn(
                        'action', inputs,
                        'a scalar label on a record targeting both blocks '
                        'claims one branch applied to both')
                    self.assertEqual(
                        ['build', 'through_the_wall'],
                        inputs['selection_branches'],
                        'the record says both branches are present')

                    # AND the RETURNED assignment, not only the audit. This
                    # test inspected `inputs` alone while holding `result`,
                    # so the public `ReferenceResult.assignments` kept an
                    # order-dependent `build`/`through_the_wall` scalar — a
                    # truthful map beside a contradictory scalar does not make
                    # the scalar true for callers (Sol, `162`).
                    from btap.codes.necb.hvac.reference import (
                        MIXED_SOURCE_ACTIONS,
                    )

                    returned = result.assignments[0]
                    self.assertEqual(
                        MIXED_SOURCE_ACTIONS, returned.action,
                        'the merged scalar must be neutral and the SAME in '
                        'both block orders')
                    self.assertEqual(actions, returned.source_actions,
                                     'and the per-block map rides with it')


class TestTheClassifierMatchesTheREUSEPathsExactly(unittest.TestCase):
    """Sol's `162` blocker 2: `plant_is_hvac_candidate` claimed to mirror the
    reuse paths and omitted one.

    Its cooling branch recognised only chillers or district cooling, while
    `chilled_water()` has another path — an EXACT builder-named
    `Chilled Water Loop` with no cooling source yet is reusable for ANY
    requested source. A source-less loop therefore classified False while the
    builder would have adopted it, the false-NEGATIVE counterpart of the
    service-water noise the filter was added to remove.

    No test called the predicate directly before this, which is why the four
    hot-water examples did not close the claimed equivalence. Each case here
    asserts the classifier AND what the reuse path actually returns, so the two
    cannot drift apart again.
    """

    def classify_and_reuse(self, build_loop, *, medium, source):
        """(candidate, reused) for one loop shape and one requested lookup.

        `medium` is explicit because `'district'` is a valid source for BOTH
        hot and chilled water: dispatching on the source name alone sent a
        district HOT-water case to `chilled_water` and reported a false
        mismatch.
        """
        import openstudio

        from btap.modeling.hvac.systems import plant_loops

        model = openstudio.model.Model()
        loop = build_loop(model, plant_loops)
        candidate = plant_loops.plant_is_hvac_candidate(loop)
        lookup = (plant_loops.chilled_water if medium == 'chilled'
                  else plant_loops.hot_water)
        got = lookup(model, source=source)
        return candidate, str(got.handle()) == str(loop.handle())

    @staticmethod
    def _sourceless_chilled(model, plant_loops):
        import openstudio

        loop = openstudio.model.PlantLoop(model)
        loop.setName('Chilled Water Loop')
        return loop

    def test_a_sourceless_CHILLED_WATER_LOOP_is_a_candidate_for_every_source(self):
        for source in ('water_cooled', 'air_cooled', 'district'):
            with self.subTest(source=source):
                candidate, reused = self.classify_and_reuse(
                    self._sourceless_chilled, medium='chilled', source=source)
                self.assertTrue(reused,
                                'chilled_water adopts an exact source-less '
                                'Chilled Water Loop for any source')
                self.assertTrue(candidate,
                                'so the classifier must call it a candidate')

    def test_a_DIFFERENTLY_NAMED_sourceless_loop_is_neither(self):
        """The name test is EXACT, so it must not broaden past what
        `chilled_water` can return.
        """
        def other(model, plant_loops):
            import openstudio

            loop = openstudio.model.PlantLoop(model)
            loop.setName('PROCESS CHW LOOP')
            return loop

        candidate, reused = self.classify_and_reuse(other, medium='chilled',
                                                    source='water_cooled')
        self.assertFalse(reused, 'the builder cannot adopt it')
        self.assertFalse(candidate, 'so it is not an audited candidate')

    def test_the_hot_water_boundaries_agree_too(self):
        """The four shapes from the previous round, now asserted against the
        reuse paths rather than against my reading of them.
        """
        def district_oddly_named(model, plant_loops):
            loop = plant_loops.hot_water(model, source='district', reuse=False)
            loop.setName('DISTRICT PROCESS LOOP')
            return loop

        def hybrid(model, plant_loops):
            import openstudio

            loop = plant_loops.hot_water(model, source='boiler', reuse=False)
            loop.addSupplyBranchForComponent(
                openstudio.model.DistrictHeating(model))
            return loop

        def ordinary_boiler(model, plant_loops):
            return plant_loops.hot_water(model, source='boiler', reuse=False)

        def builder_named_district(model, plant_loops):
            return plant_loops.hot_water(model, source='district', reuse=False)

        for shape, source, expected in (
                (district_oddly_named, 'district', False),
                (district_oddly_named, 'boiler', False),
                (hybrid, 'boiler', False),
                (hybrid, 'district', False),
                (ordinary_boiler, 'boiler', True),
                (builder_named_district, 'district', True)):
            with self.subTest(shape=shape.__name__, source=source):
                candidate, reused = self.classify_and_reuse(shape, medium='hot',
                                                            source=source)
                self.assertEqual(
                    expected, reused,
                    'precondition: what the reuse path does with this shape')
                # UNCONDITIONALLY, in both directions. `if reused:` asserted
                # only that adoptable loops classify true, so restoring the
                # exact `160` false positive — `candidate or
                # _district_heated(loop)` — left this test passing (Sol,
                # `164`). An over-broad classifier is the noise this filter
                # exists to remove, so the negative half is the half that
                # matters.
                self.assertEqual(
                    expected, candidate,
                    'the classifier must agree with the reuse path in BOTH '
                    'directions: an adoptable survivor is audited, and a loop '
                    'no lookup can return is not')

    def test_a_retained_sourceless_CHW_loop_is_NAMED_in_the_reservation(self):
        """Sol's `162` second required control, through the full reference path.

        A source-less `Chilled Water Loop` kept alive by process demand must
        appear in the RESERVED audit — the builder would have adopted it
        without the exclusion — while the built blocks' cooling coils go on a
        new plant. Before the fix the exclusion protected them correctly and
        the audit said nothing, which is the false negative.
        """
        import openstudio

        from btap.modeling.hvac.systems import plant_loops

        proposed = proposed_with_hvac(MULTIZONE_PROPOSED)
        # Strip the proposed chillers so the loop has no cooling SOURCE, and
        # give it process demand so teardown keeps it.
        chilled = next(p for p in proposed.getPlantLoops()
                       if p.nameString() == 'Chilled Water Loop')
        for component in list(plant_loops._chillers(chilled)):
            component.to_ChillerElectricEIR().get().remove()
        self.assertIsNone(plant_loops._cooling_source(chilled),
                          'fixture: the loop has no cooling source')
        definition = openstudio.model.WaterUseEquipmentDefinition(proposed)
        definition.setPeakFlowRate(0.001)
        equipment = openstudio.model.WaterUseEquipment(definition)
        equipment.setName('PROCESS COOLING LOAD')
        connections = openstudio.model.WaterUseConnections(proposed)
        connections.setName('PROCESS COOLING CONNECTIONS')
        connections.addWaterUseEquipment(equipment)
        chilled.addDemandBranchForComponent(connections)

        reference, audit = reference_of(proposed, storeys=5)
        reserved = [e for e in audit.entries
                    if 'RESERVED to whatever retained it' in str(e.get('action'))]
        self.assertEqual(1, len(reserved),
                         'the survivor the builder could have adopted must be '
                         'audited')
        self.assertIn('Chilled Water Loop', str(reserved[0].get('target')),
                      'and named in it')

        # And the built blocks are still kept off it.
        retained = next(p for p in reference.getPlantLoops()
                        if p.nameString() == 'Chilled Water Loop')
        coils = [c.nameString() for c in retained.demandComponents()
                 if 'Coil Cooling' in c.nameString()]
        self.assertEqual([], coils,
                         'no reference cooling coil may join the retained loop')
        self.assertTrue(
            [c for c in retained.demandComponents()
             if 'PROCESS COOLING CONNECTIONS' in c.nameString()],
            'and the demand that retained it is still on it')

        # BOTH HALVES of the ownership claim. Asserting only that the retained
        # loop has no reference coil would also pass if the built blocks had
        # no cooling plant at all, which is not what the contract says
        # (Sol, `164`).
        built = [p for p in reference.getPlantLoops()
                 if str(p.handle()) != str(retained.handle())
                 and [c for c in p.demandComponents()
                      if 'Coil Cooling' in c.nameString()]]
        self.assertEqual(
            1, len(built),
            'the built blocks need exactly one new chilled-water plant')
        self.assertEqual(
            5, len([c for c in built[0].demandComponents()
                    if 'Coil Cooling' in c.nameString()]),
            'carrying all five built blocks\' cooling coils')
