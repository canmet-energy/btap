"""The recipe's space-type mix by floor area (#196).

phylroy's addition: a reader needs the PROPORTIONS to generate a building,
not just the space-type names.

Three things make an area wrong if ignored — multipliers,
`partofTotalFloorArea`, and spaces with no space type — and NONE of them
occurs on `Office_pre-1960` or `Hangar_pre-1960` (measured: no excluded
spaces, none unassigned, every multiplier 1). So the corpus cannot exercise
those branches and these tests construct them.
"""

from __future__ import annotations

import unittest

from btap.audit import AuditLog
from btap.stock import space_types_section
from tests.support import needs_sdk


def _space(model, name, space_type=None, area=100.0, multiplier=1,
           part_of_floor_area=True):
    import openstudio

    space = openstudio.model.Space(model)
    space.setName(name)
    if space_type is not None:
        space.setSpaceType(space_type)
    # The multiplier lives on the THERMAL ZONE, not the space: the header says
    # `Space::multiplier()` "comes from thermal zone, defaults to 1", and
    # there is no `Space::setMultiplier`. My first version called one.
    if multiplier != 1:
        zone = openstudio.model.ThermalZone(model)
        zone.setName(f'{name} Zone')
        zone.setMultiplier(multiplier)
        space.setThermalZone(zone)
    space.setPartofTotalFloorArea(part_of_floor_area)
    side = area ** 0.5
    pts = openstudio.Point3dVector()
    for x, y in ((0, 0), (side, 0), (side, side), (0, side)):
        pts.append(openstudio.Point3d(x, y, 0.0))
    floor = openstudio.model.Surface(pts, model)
    floor.setSpace(space)
    floor.setSurfaceType('Floor')
    return space


def _space_type(model, name, building_type=None, space_type_name=None):
    import openstudio

    st = openstudio.model.SpaceType(model)
    st.setName(name)
    if building_type is not None:
        st.setStandardsBuildingType(building_type)
    if space_type_name is not None:
        st.setStandardsSpaceType(space_type_name)
    return st


@needs_sdk
class TestTheMix(unittest.TestCase):

    def test_areas_and_fractions(self):
        import openstudio

        model = openstudio.model.Model()
        office = _space_type(model, 'Office')
        corridor = _space_type(model, 'Corridor')
        _space(model, 'O1', office, area=300.0)
        _space(model, 'O2', office, area=100.0)
        _space(model, 'C1', corridor, area=100.0)

        section = space_types_section(model)
        self.assertAlmostEqual(500.0, section['total_floor_area_m2'],
                               places=1)
        self.assertAlmostEqual(
            400.0, section['by_space_type']['Office']['floor_area_m2'],
            places=1)
        self.assertEqual(2, section['by_space_type']['Office']['spaces'])
        self.assertAlmostEqual(
            0.8, section['by_space_type']['Office']['fraction_of_total'],
            places=4)
        self.assertAlmostEqual(
            0.2, section['by_space_type']['Corridor']['fraction_of_total'],
            places=4)

    def test_the_fractions_SUM_TO_ONE_with_the_unassigned_share(self):
        """On `Office_pre-1960` they sum to 1.000000 exactly; this pins the
        property including the unattributed share."""
        import openstudio

        model = openstudio.model.Model()
        office = _space_type(model, 'Office')
        _space(model, 'O1', office, area=300.0)
        _space(model, 'Nowhere', None, area=100.0)

        section = space_types_section(model)
        total = sum(e['fraction_of_total']
                    for e in section['by_space_type'].values())
        total += section['unassigned']['fraction_of_total']
        self.assertAlmostEqual(1.0, total, places=6)

    def test_a_MULTIPLIER_counts_its_repeats(self):
        """A space with multiplier 5 represents five, so ignoring it would
        understate every repeated space type in a multi-storey model."""
        import openstudio

        model = openstudio.model.Model()
        office = _space_type(model, 'Office')
        corridor = _space_type(model, 'Corridor')
        _space(model, 'O1', office, area=100.0, multiplier=5)
        _space(model, 'C1', corridor, area=100.0)

        section = space_types_section(model)
        self.assertAlmostEqual(
            500.0, section['by_space_type']['Office']['floor_area_m2'],
            places=1, msg='100 m2 x 5, not 100')
        self.assertAlmostEqual(600.0, section['total_floor_area_m2'],
                               places=1)

    def test_a_space_EXCLUDED_from_floor_area_is_not_in_the_total(self):
        """A plenum is excluded by the SDK's own flag. Counting it would
        dilute every fraction and describe a larger building."""
        import openstudio

        model = openstudio.model.Model()
        office = _space_type(model, 'Office')
        plenum_type = _space_type(model, 'Plenum')
        _space(model, 'O1', office, area=400.0)
        _space(model, 'Plenum 1', plenum_type, area=400.0,
               part_of_floor_area=False)

        section = space_types_section(model)
        self.assertAlmostEqual(400.0, section['total_floor_area_m2'],
                               places=1)
        self.assertAlmostEqual(
            1.0, section['by_space_type']['Office']['fraction_of_total'],
            places=6, msg='the office is ALL of the floor area')
        self.assertNotIn('Plenum', section['by_space_type'])
        excluded = section['excluded_from_floor_area']
        self.assertEqual(1, excluded['spaces'])
        self.assertAlmostEqual(400.0, excluded['floor_area_m2'], places=1)
        self.assertIn('Plenum 1', excluded['names'])

    def test_UNASSIGNED_area_is_reported_not_dropped(self):
        """Area that vanishes between model and recipe is area a reader
        cannot account for."""
        import openstudio

        model = openstudio.model.Model()
        office = _space_type(model, 'Office')
        _space(model, 'O1', office, area=300.0)
        _space(model, 'Nowhere', None, area=100.0)

        audit = AuditLog()
        section = space_types_section(model, audit=audit)
        self.assertEqual(1, section['unassigned']['spaces'])
        self.assertAlmostEqual(100.0,
                               section['unassigned']['floor_area_m2'],
                               places=1)
        self.assertAlmostEqual(400.0, section['total_floor_area_m2'],
                               places=1,
                               msg='unattributed area is still floor area')
        self.assertTrue(any('unattributed' in str(e.get('value')
                                                  or e.get('action') or '')
                            for e in audit.entries))


@needs_sdk
class TestTheStandardsKeys(unittest.TestCase):
    """These are what a reader needs to resolve a space type against a code
    catalogue, and all 15 are absent on `Office_pre-1960` — which is why a
    model built from it would fail NECB's space-type preflight gate."""

    def test_tagged_keys_are_carried(self):
        import openstudio

        model = openstudio.model.Model()
        tagged = _space_type(model, 'Office', building_type='Office',
                             space_type_name='WholeBuilding')
        _space(model, 'O1', tagged)

        entry = space_types_section(model)['by_space_type']['Office']
        self.assertEqual('Office', entry['standards_building_type'])
        self.assertEqual('WholeBuilding', entry['standards_space_type'])

    def test_UNTAGGED_space_types_are_counted_and_WARNED(self):
        import openstudio

        model = openstudio.model.Model()
        _space(model, 'O1', _space_type(model, 'Untagged One'))
        _space(model, 'O2', _space_type(model, 'Untagged Two'))
        _space(model, 'O3', _space_type(model, 'Tagged',
                                        building_type='Office',
                                        space_type_name='Open'))

        audit = AuditLog()
        section = space_types_section(model, audit=audit)
        self.assertEqual(3, section['from']['space_types'])
        self.assertEqual(2, section['from']['untagged_space_types'])
        self.assertEqual(['Untagged One', 'Untagged Two'],
                         section['from']['untagged'])
        warnings = [e for e in audit.entries if e.get('level') == 'warning']
        self.assertEqual(1, len(warnings))
        self.assertIn('preflight', str(warnings[0].get('value')
                                       or warnings[0].get('action') or ''))

    def test_a_HALF_tagged_space_type_counts_as_untagged(self):
        """Both keys are needed to resolve against a catalogue, so one
        without the other is not resolvable."""
        import openstudio

        model = openstudio.model.Model()
        _space(model, 'O1', _space_type(model, 'Half', building_type='Office'))

        section = space_types_section(model)
        self.assertEqual(1, section['from']['untagged_space_types'])


@needs_sdk
class TestEmptyModel(unittest.TestCase):

    def test_no_spaces_gives_a_zero_total_and_no_division_error(self):
        import openstudio

        section = space_types_section(openstudio.model.Model())
        self.assertEqual(0.0, section['total_floor_area_m2'])
        self.assertEqual({}, section['by_space_type'])
        self.assertIsNone(section['unassigned']['fraction_of_total'])


if __name__ == '__main__':
    unittest.main()
