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


def reference_of(proposed, *, code='necb2020', storeys=2, space_type=None):
    if space_type is not None:
        for st in proposed.getSpaceTypes():
            if st.spaces():
                st.setStandardsSpaceType(space_type)
    audit = AuditLog()
    result = hvac.reference_hvac(proposed, code=code,
                                 building={'storeys': storeys}, audit=audit)
    return result.model, audit


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
        # A kitchen selects System 4 (the make-up air unit) rather than 3.
        for code in EDITIONS:
            with self.subTest(code=code):
                proposed = proposed_with_hvac(MULTIZONE_PROPOSED)
                blocks = self.assert_proposed_is_one_multizone_loop(proposed)
                reference, _ = reference_of(proposed, code=code, storeys=2,
                                            space_type='Food preparation area')
                self.assertEqual(
                    [(b,) for b in blocks], loop_zones(reference),
                    'System 4 is "Single-zone" in the same table')

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
