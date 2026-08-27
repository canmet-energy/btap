"""P4 gate: the MURB / DWELLING reference path — HAS NEVER EXECUTED with a real
NECB catalog dwelling space-type name in this repo. Existing tests use
'Multi-unit residential' (test_hvac_necb_reference, test_hvac_necb_selector),
which is only a `building_type` string in the space-types catalog and
happens to match the "residential" keyword — it is NOT a dwelling-unit
`space_type` row. The real catalog dwelling row is:
  { "building_type": "Space Function", "space_type": "Dwelling units general" }
(btap/necb/loads/data/space_types_2020.json).

This file tags a model with that exact name and exercises BOTH domains'
dwelling detection through the SAME model, on MODEL VALUES only:
 1. the lighting domain's reference_lighting: dwelling units are overridden
    to 5 W/m2 (8.4.4.5.(2)) via `standardsSpaceType =~ /dwelling/i`
    (necb/lighting/reference.py apply_dwelling_rule) — regardless of the
    Part-4 catalog LPD row, and regardless of a deliberately hostile
    99 W/m2 input.
 2. the hvac domain's _category_for keyword vote: 'dwelling' is a keyword of
    the "Residential/Accommodation Area" category (selection.categories in
    reference_rules_2020.json) — a real model tagged with the dwelling
    catalog name must vote that category and take the `special: residential`
    branch, exercised end-to-end via reference_hvac (not just the synthetic
    facts test_hvac_necb_selector already covers)."""

from __future__ import annotations

import unittest

import openstudio

import btap.modeling as modeling
from btap.audit import AuditLog
from btap.necb import hvac, lighting
from tests.necb.hvac_helpers import load_fixture, sorted_zones
from tests.support import needs_sdk

DWELLING_BUILDING_TYPE = 'Space Function'
DWELLING_SPACE_TYPE = 'Dwelling units general'
HOSTILE_W_PER_M2 = 99.0


@needs_sdk
class TestNecbMurbDwellingReference(unittest.TestCase):

    @staticmethod
    def tag_fixture_as_dwelling(model):
        for st in model.getSpaceTypes():
            if len(st.spaces()):
                st.setStandardsBuildingType(DWELLING_BUILDING_TYPE)
                st.setStandardsSpaceType(DWELLING_SPACE_TYPE)
        return model

    @staticmethod
    def dwelling_tagged_space_type(model):
        st = openstudio.model.SpaceType(model)
        st.setName(f'{DWELLING_BUILDING_TYPE} {DWELLING_SPACE_TYPE}')
        st.setStandardsBuildingType(DWELLING_BUILDING_TYPE)
        st.setStandardsSpaceType(DWELLING_SPACE_TYPE)
        return st

    # ---- (1) HVAC selector dwelling detection, exercised through a real model ----

    def test_hvac_selector_votes_residential_accommodation_for_a_real_dwelling_tagged_model(self):
        model = self.tag_fixture_as_dwelling(load_fixture())
        # Heated-only proposed system: the special residential rule's
        # "heated only -> System 1" sentence, hit via the auto-derived zone_types
        # (no building={'zone_types': ...} override — the tag alone must drive selection).
        modeling.build_system(model, 'Baseboard gas boiler', sorted_zones(model))

        audit = AuditLog()
        result = hvac.reference_hvac(model, vintage='2020', audit=audit)

        self.assertEqual(['Residential/Accommodation Area'],
                         sorted({a.category for a in result.assignments}),
                         "the 'dwelling' keyword must route a real dwelling-tagged model into "
                         'the residential category (selection.categories in '
                         'reference_rules_2020.json), not just in the synthetic facts of '
                         'test_hvac_necb_selector')
        self.assertEqual([1], sorted({a.reference_system for a in result.assignments}))
        self.assertEqual(['build'], sorted({a.action for a in result.assignments}))
        self.assertTrue(len(result.model.getZoneHVACPackagedTerminalAirConditioners()),
                        'System 1 = MAU + PTAC per zone')

    # ---- (2) reference lighting dwelling override, at MODEL level ----

    def test_reference_lighting_applies_5_w_per_m2_dwelling_override_over_a_hostile_lpd(self):
        model = openstudio.model.Model()
        space_type = self.dwelling_tagged_space_type(model)
        definition = openstudio.model.LightsDefinition(model)
        definition.setName('Hostile Dwelling Lights Definition')
        definition.setWattsperSpaceFloorArea(HOSTILE_W_PER_M2)
        lights = openstudio.model.Lights(definition)
        lights.setSpaceType(space_type)
        # a floor-area space so the type is consequential
        space = openstudio.model.Space(model)
        space.setSpaceType(space_type)

        audit = AuditLog()
        lighting.reference_lighting(model, vintage='2020', audit=audit)

        dwelling_lpd = float(lighting.rules('2020')['dwelling_unit_lpd_w_per_m2'])
        self.assertAlmostEqual(5.0, dwelling_lpd, delta=1e-9,
                               msg='sanity: the data file still declares 5.0 W/m2 (8.4.4.5.(2))')

        actual = space_type.lights()[0].lightsDefinition().wattsperSpaceFloorArea().get()
        self.assertAlmostEqual(dwelling_lpd, actual, delta=1e-6,
                               msg='8.4.4.5.(2): dwelling units must be modeled at 5 W/m2, '
                                   'overriding BOTH the hostile proposed value and the ordinary '
                                   'Part-4 catalog LPD for this space type')
        self.assertNotAlmostEqual(HOSTILE_W_PER_M2, actual, delta=1e-6,
                                  msg='reference retained the hostile proposed dwelling LPD')


if __name__ == '__main__':
    unittest.main()
