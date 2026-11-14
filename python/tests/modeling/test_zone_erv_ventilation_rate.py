"""A zone ERV ventilates at the ZONE's requirement, not the SDK's defaults.

A `ZoneHVAC:EnergyRecoveryVentilator` autosizes from its own
`VentilationRateperUnitFloorArea` and `VentilationRateperOccupant` — 0.000508
m3/s-m2 and 0.00236 m3/s-person on SDK 3.11.0 — and never reads the zone's
`DesignSpecificationOutdoorAir`. Found by a Fable review, verified against the
live SDK.

**Those defaults are a different BASIS, not a biased value.** They are
area-dominant where an ASHRAE 62.1 requirement is occupancy-dominant, so the
error swings with occupancy density:

    0.005 person/m2   966% of the requirement   (a warehouse)
    0.054             110%                      (where they cross over)
    0.200              46%                      (a classroom)

`tests/necb/hvac_helpers.load_fixture` sits near 0.054, which is why a test
written only against it would read ~110% and look acceptable. The divergent
fixtures below exist for that reason.

The rates come from the MODEL, not from a standard. NECB 8.4.3.6 sets peak
outdoor-air rates to "the minimum rates required by the applicable ventilation
standard" — ASHRAE 62.1 for commercial work, NBC Division B 9.32.3 for
dwelling units, which is the Canadian path rather than ASHRAE 62.2
(A-5.2.10.4.(1)). Whichever applied, its rates are already in the DSOA.
"""
import unittest

import openstudio

from btap._compat import opt
from btap.modeling import build_system
from btap.modeling.hvac import energy_recovery
from tests.necb.hvac_helpers import load_fixture, sorted_zones
from tests.support import needs_sdk

SDK_PER_AREA = 0.000508
SDK_PER_PERSON = 0.00236


def _zone_with(model, *, area, people, per_area, per_person, method='Sum',
               absolute=0.0, ach=0.0, name='Z'):
    """A one-space zone carrying an explicit outdoor-air specification."""
    zone = openstudio.model.ThermalZone(model)
    zone.setName(name)
    space = openstudio.model.Space(model)
    space.setName(f'{name} space')
    points = openstudio.Point3dVector()
    side = area ** 0.5
    # CLOCKWISE seen from above, so the outward normal points DOWN and the
    # surface is a Floor. The other winding makes a RoofCeiling, whose area
    # does not count toward `Space.floorArea()` — my first version used it and
    # the per-area rate came back 0.0 from a divide-by-zero guard.
    for x, y in ((0, 0), (0, side), (side, side), (side, 0)):
        points.append(openstudio.Point3d(x, y, 0))
    surface = openstudio.model.Surface(points, model)
    surface.setSpace(space)
    space.setThermalZone(zone)

    if people:
        definition = openstudio.model.PeopleDefinition(model)
        definition.setNumberofPeople(people)
        openstudio.model.People(definition).setSpace(space)

    spec = openstudio.model.DesignSpecificationOutdoorAir(model)
    spec.setName(f'{name} DSOA')
    spec.setOutdoorAirMethod(method)
    spec.setOutdoorAirFlowperFloorArea(per_area)
    spec.setOutdoorAirFlowperPerson(per_person)
    if absolute:
        spec.setOutdoorAirFlowRate(absolute)
    if ach:
        spec.setOutdoorAirFlowAirChangesperHour(ach)
    space.setDesignSpecificationOutdoorAir(spec)
    return zone


@needs_sdk
class TestTheRatesComeFromTheZone(unittest.TestCase):
    def test_a_person_only_requirement_is_carried_exactly(self):
        model = openstudio.model.Model()
        zone = _zone_with(model, area=100.0, people=5.0,
                          per_area=0.0, per_person=0.01076)
        erv = energy_recovery.add_zone_energy_recovery(model, zone)
        self.assertAlmostEqual(0.01076, erv.ventilationRateperOccupant())
        self.assertAlmostEqual(0.0, erv.ventilationRateperUnitFloorArea())

    def test_an_area_only_requirement_is_carried_exactly(self):
        model = openstudio.model.Model()
        zone = _zone_with(model, area=100.0, people=5.0,
                          per_area=0.0009, per_person=0.0)
        erv = energy_recovery.add_zone_energy_recovery(model, zone)
        self.assertAlmostEqual(0.0009, erv.ventilationRateperUnitFloorArea())
        self.assertAlmostEqual(0.0, erv.ventilationRateperOccupant())

    def test_a_DENSE_zone_diverges_sharply_from_the_SDK_defaults(self):
        """The case the shared fixture cannot show.

        At 0.20 person/m2 the defaults move 46% of the requirement. A test
        built only on `load_fixture`, which sits where the two bases cross,
        would pass against the unfixed code.
        """
        model = openstudio.model.Model()
        area, people = 100.0, 20.0           # 0.20 person/m2
        zone = _zone_with(model, area=area, people=people,
                          per_area=0.0, per_person=0.01076)
        erv = energy_recovery.add_zone_energy_recovery(model, zone)

        required = 0.01076 * people
        got = (erv.ventilationRateperUnitFloorArea() * area
               + erv.ventilationRateperOccupant() * people)
        defaults = SDK_PER_AREA * area + SDK_PER_PERSON * people
        self.assertAlmostEqual(required, got, places=6)
        self.assertLess(
            defaults, 0.6 * required,
            'the fixture no longer diverges from the defaults, so it has '
            'stopped testing what it exists to test')

    def test_a_SPARSE_zone_diverges_the_other_way(self):
        """At 0.005 person/m2 the defaults move ~10x the requirement, so the
        error is not a consistent bias in one direction."""
        model = openstudio.model.Model()
        area, people = 1000.0, 5.0           # 0.005 person/m2
        zone = _zone_with(model, area=area, people=people,
                          per_area=0.0, per_person=0.01076)
        erv = energy_recovery.add_zone_energy_recovery(model, zone)

        required = 0.01076 * people
        defaults = SDK_PER_AREA * area + SDK_PER_PERSON * people
        self.assertAlmostEqual(
            required,
            erv.ventilationRateperOccupant() * people, places=6)
        self.assertGreater(defaults, 5.0 * required)


@needs_sdk
class TestSeveralSpacesAreWeighted(unittest.TestCase):
    """One zone of `Office_pre-1960` carries TWO distinct DSOAs, so the
    combination rule is exercised by real data, not only by construction."""

    def test_per_person_is_weighted_by_PEOPLE_not_averaged(self):
        model = openstudio.model.Model()
        zone = _zone_with(model, area=100.0, people=1.0,
                          per_area=0.0, per_person=0.02, name='A')
        # a second space in the SAME zone, with many more people and a
        # different rate: an unweighted mean would give 0.015
        space = openstudio.model.Space(model)
        space.setName('B space')
        points = openstudio.Point3dVector()
        for x, y in ((0, 0), (0, 10), (10, 10), (10, 0)):
            points.append(openstudio.Point3d(x, y, 0))
        openstudio.model.Surface(points, model).setSpace(space)
        space.setThermalZone(zone)
        definition = openstudio.model.PeopleDefinition(model)
        definition.setNumberofPeople(9.0)
        openstudio.model.People(definition).setSpace(space)
        spec = openstudio.model.DesignSpecificationOutdoorAir(model)
        spec.setOutdoorAirMethod('Sum')
        spec.setOutdoorAirFlowperPerson(0.01)
        space.setDesignSpecificationOutdoorAir(spec)

        erv = energy_recovery.add_zone_energy_recovery(model, zone)
        # (0.02*1 + 0.01*9) / 10 = 0.011, not the 0.015 of an unweighted mean
        self.assertAlmostEqual(0.011, erv.ventilationRateperOccupant())


@needs_sdk
class TestWhatCannotBeExpressedIsRefused(unittest.TestCase):
    """A zone ERV ADDS its two rates. Silently moving more outdoor air than
    the building asked for is worse than a refusal naming the zone."""

    def test_a_Maximum_requirement_is_refused(self):
        model = openstudio.model.Model()
        zone = _zone_with(model, area=100.0, people=5.0, per_area=0.0009,
                          per_person=0.01076, method='Maximum')
        with self.assertRaises(ValueError) as caught:
            energy_recovery.add_zone_energy_recovery(model, zone)
        self.assertIn('Maximum', str(caught.exception))

    def test_an_absolute_flow_is_refused(self):
        model = openstudio.model.Model()
        zone = _zone_with(model, area=100.0, people=5.0, per_area=0.0,
                          per_person=0.01076, absolute=0.25)
        with self.assertRaises(ValueError):
            energy_recovery.add_zone_energy_recovery(model, zone)

    def test_an_air_changes_rate_is_refused(self):
        model = openstudio.model.Model()
        zone = _zone_with(model, area=100.0, people=5.0, per_area=0.0,
                          per_person=0.01076, ach=0.5)
        with self.assertRaises(ValueError):
            energy_recovery.add_zone_energy_recovery(model, zone)

    def test_a_zone_with_NO_requirement_keeps_the_defaults(self):
        """Inventing zero would stop ventilating a zone the caller asked to
        ventilate, which is a worse failure than an imperfect rate."""
        model = openstudio.model.Model()
        zone = openstudio.model.ThermalZone(model)
        space = openstudio.model.Space(model)
        space.setThermalZone(zone)
        erv = energy_recovery.add_zone_energy_recovery(model, zone)
        self.assertAlmostEqual(SDK_PER_AREA,
                               erv.ventilationRateperUnitFloorArea())
        self.assertAlmostEqual(SDK_PER_PERSON,
                               erv.ventilationRateperOccupant())


@needs_sdk
class TestTheShippedRowUsesIt(unittest.TestCase):
    def test_the_Zone_ERVs_row_carries_each_zones_own_rate(self):
        model = load_fixture()
        build_system(model, 'Zone ERVs', sorted_zones(model))
        for erv in model.getZoneHVACEnergyRecoveryVentilators():
            zone = opt(erv.thermalZone())
            with self.subTest(zone=zone.nameString()):
                spec = opt(next(iter(zone.spaces()))
                           .designSpecificationOutdoorAir())
                self.assertAlmostEqual(
                    spec.outdoorAirFlowperPerson(),
                    erv.ventilationRateperOccupant())
                self.assertNotAlmostEqual(
                    SDK_PER_PERSON, erv.ventilationRateperOccupant())


if __name__ == '__main__':
    unittest.main()
