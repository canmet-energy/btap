"""Lighting costing smoke test (M4).

Not a port: the lighting domain's real acceptance is a btap-necb parity gate
plus the lighting_costing Leg-C golden, both arriving with M5. Until then this
smoke test exercises the ported database / fixture / facade layers directly:
the fixture model tagged with a lighting_sets catalog key (set via the SDK —
no btap.necb involved), costed twice for determinism, plus the
daylighting-areas provider contract (the RAISE that guards against silent
under-costing) and the database lookup layer.
"""

import unittest

from tests.support import load_fixture, needs_sdk

# A concurrent agent may own tests/costing/support.py; import it if present,
# inline what we need otherwise (never create it here).
try:
    from tests.costing import support as costing_support  # noqa: F401
except ImportError:
    costing_support = None

CITY = "TORONTO"
PROVINCE = "ONTARIO"

# Catalog keys matched against lighting_sets.csv 'NECB 2020' rows — never rename.
BUILDING_TYPE = "Space Function"
SPACE_TYPE = "Office enclosed > 25 m2"


def tagged_model():
    """The fixture with every space type carrying the standards tags the
    lighting_sets lookup keys on (what BtapNECB::Loads.assign_space_types
    produces; set directly with the SDK so this stays a COSTING-layer unit
    test — the real necb-built path is covered by tests/necb/test_lighting_costing.py)."""
    model = load_fixture()
    for space in model.getSpaces():
        space_type = space.spaceType().get()
        space_type.setStandardsBuildingType(BUILDING_TYPE)
        space_type.setStandardsSpaceType(SPACE_TYPE)
    return model


@needs_sdk
class TestLightingCostingSmoke(unittest.TestCase):
    def test_cost_structure(self):
        from btap.audit import AuditLog
        from btap.costing.lighting import report as lighting

        audit = AuditLog()
        rep = lighting.cost(tagged_model(), vintage="2020", city=CITY,
                            province_state=PROVINCE, audit=audit)
        self.assertGreater(rep.total, 0)
        self.assertEqual(rep.total, rep.lighting["total_lighting_cost"])
        self.assertEqual(5, len(rep.lighting["space_report"]))
        for line in rep.lighting["space_report"]:
            self.assertEqual(BUILDING_TYPE, line["building_type"])
            self.assertEqual(SPACE_TYPE, line["space_type"])
            self.assertGreater(line["cost"], 0)
            self.assertGreater(line["floor_area_ft2"], 0)
            # 12.47 ft average ceiling -> the middle height bin
            self.assertAlmostEqual(12.5, line["height_avg_ft"], places=1)
        # one space type everywhere -> one accumulated fixture row over 5 spaces
        self.assertEqual(1, len(rep.lighting["fixture_report"]))
        self.assertEqual(5, rep.lighting["fixture_report"][0]["number_of_spaces"])
        self.assertEqual(CITY, rep.city)
        self.assertEqual(PROVINCE, rep.province_state)
        decisions = [e for e in audit.entries
                     if e["step"] == "costing_lighting" and e["level"] == "decision"]
        self.assertTrue(any("lighting fixtures costed by space" in e["action"]
                            for e in decisions))

    def test_cost_is_deterministic(self):
        from btap.costing.lighting import report as lighting

        first = lighting.cost(tagged_model(), vintage="2020", city=CITY,
                              province_state=PROVINCE)
        second = lighting.cost(tagged_model(), vintage="2020", city=CITY,
                               province_state=PROVINCE)
        self.assertEqual(first.total, second.total)
        self.assertEqual(first.lighting["space_report"], second.lighting["space_report"])
        self.assertEqual(first.lighting["fixture_report"], second.lighting["fixture_report"])

    def test_location_resolves_from_model_site(self):
        from btap.costing.lighting import report as lighting

        rep = lighting.cost(tagged_model(), vintage="2020")  # fixture site: Toronto Intl AP
        self.assertEqual("TORONTO", rep.city)
        self.assertEqual("ONTARIO", rep.province_state)
        self.assertTrue(any("cost location resolved from the model site" in e["action"]
                            for e in rep.audit.entries))

    def test_untagged_space_warns_not_costed(self):
        from btap.audit import AuditLog
        from btap.costing.lighting import report as lighting

        audit = AuditLog()
        rep = lighting.cost(load_fixture(), vintage="2020", city=CITY,
                            province_state=PROVINCE, audit=audit)
        self.assertEqual(0.0, rep.total)
        self.assertEqual([], rep.lighting["space_report"])
        self.assertTrue(any("has no standards space type — not costed" in w
                            for w in rep.warnings))

    def test_daylighting_without_provider_raises(self):
        """THE TRAP: daylighting controls in the model + no daylighting_areas
        provider must RAISE — silently under-costing is the failure this
        guards (the NECB layer supplies the provider by default)."""
        import openstudio

        from btap.costing.lighting import report as lighting

        model = tagged_model()
        space = sorted(model.getSpaces(), key=lambda s: s.nameString())[0]
        control = openstudio.model.DaylightingControl(model)
        control.setSpace(space)
        space.thermalZone().get().setPrimaryDaylightingControl(control)

        with self.assertRaises(ValueError) as ctx:
            lighting.cost(model, vintage="2020", city=CITY, province_state=PROVINCE)
        self.assertIn("no daylighting_areas: provider was given", str(ctx.exception))

        # with a provider the same model costs, and the sensor section appears
        rep = lighting.cost(model, vintage="2020", city=CITY, province_state=PROVINCE,
                            daylighting_areas=lambda s: {"sidelighted_m2": 10.0,
                                                         "skylight_m2": 0.0})
        self.assertIn("daylighting_sensor_cost", rep.lighting)
        self.assertGreater(rep.lighting["daylighting_sensor_cost"], 0)
        self.assertGreaterEqual(rep.total, rep.lighting["daylighting_sensor_cost"])

    def test_database_lookup_layer(self):
        from btap.costing.lighting.database import Database

        db = Database()
        with self.assertRaises(ValueError):
            db.cost_record("no-such-id")
        # ids are matched case-insensitively (upcased on both sides)
        record = db.cost_record("180135")
        self.assertEqual(sorted(record), ["equipmentOpCost", "laborOpCost", "materialOpCost"])
        # unknown city falls back to 100/100 WITH a recorded warning — never silent
        factors = db.regional_factors("NOWHERE", "NOWHERE CITY", "170391")
        self.assertEqual([100.0, 100.0], factors)
        self.assertTrue(any("using 100/100" in w for w in db.warnings))
        location = db.closest_location(43.67, -79.63)
        self.assertEqual("TORONTO", location["city"])


if __name__ == "__main__":
    unittest.main()
