"""Envelope + thermal-bridging costing: database resolution, interpolation
semantics, per-surface costing, SHGC film, TB id-matching (legacy defect
fixed), parapet allowance, and the unified compliance+costing audit.

Port of btap-costing/test/test_envelope_costing.rb. Divergence (noted per
D-79): the Ruby suite costs a model with NECB prescriptive constructions
applied (BtapNECB::Envelope.apply_prescriptive); btap.necb is not yet ported,
so these tests cost the fixture's OWN constructions — every assertion kept is
independent of which constructions are applied (geometry areas, >0 costs,
ratio identities, audit shape). The one test that spans compliance +
costing in one audit skips until the necb milestone lands.
"""

import tempfile
import unittest
from pathlib import Path

from tests.costing.support import load_fixture, needs_sdk

CITY = "TORONTO"
PROVINCE = "ONTARIO"


class TestEnvelopeDatabase(unittest.TestCase):
    def test_database_loads_and_resolves_priced_tables(self):
        from btap.costing.envelope.database import Database
        db = Database()
        self.assertTrue(db.materials_opaque)
        self.assertTrue(db.materials_glazing)
        self.assertTrue(db.thermal_bridging)
        self.assertTrue(db.constructions)
        # priced tables resolved from the shared data/ copies
        record = db.cost_record("070026")
        self.assertGreater(record["materialOpCost"] + record["laborOpCost"], 0)
        # vendored materials sheets are UNPRICED (reference columns blanked at
        # vendoring; '' loads as None per the port's CSV normalization)
        self.assertTrue(all(self._blank(r["material_cost"]) for r in db.materials_opaque))
        self.assertTrue(all(self._blank(r["material_cost"]) for r in db.materials_glazing))

    @staticmethod
    def _blank(value):
        return value is None or str(value).strip() == ""

    def test_costs_csv_override(self):
        from btap.costing.envelope.database import Database
        db = Database()
        base = db.cost_record("070026")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "override.csv"
            path.write_text(
                "id,sheet,source,description,city,province_state,"
                "materialOpCost,laborOpCost,equipmentOpCost\n"
                "070026,materials_opaque,test,override,,,999.0,111.0,0.0\n",
                encoding="utf-8")
            injected = Database(costs_csv=str(path))
            self.assertAlmostEqual(999.0, injected.cost_record("070026")["materialOpCost"],
                                   delta=1e-9)
            self.assertNotAlmostEqual(base["materialOpCost"],
                                      injected.cost_record("070026")["materialOpCost"],
                                      delta=1e-9)


class TestInterpolate(unittest.TestCase):
    def test_interpolate_semantics(self):
        from btap.costing.envelope.interpolate import interpolate
        points = [[1.0, 10.0], [2.0, 20.0], [4.0, 30.0]]
        self.assertAlmostEqual(15.0, interpolate(x_y_array=points, x2=1.5).value, delta=1e-9)
        self.assertAlmostEqual(25.0, interpolate(x_y_array=points, x2=3.0).value, delta=1e-9)
        # below data but within clamp band -> linear extrapolation from first two points
        self.assertAlmostEqual(9.9, interpolate(x_y_array=points, x2=0.99).value, delta=1e-9)
        # beyond the +2% clamp -> clamped bound + the honest flag (legacy adds $10^12 instead)
        high = interpolate(x_y_array=points, x2=5.0)
        self.assertTrue(high.upper_bound_exceeded)
        self.assertAlmostEqual(30.6, high.value, delta=1e-9)  # 1.02 x 30
        low = interpolate(x_y_array=points, x2=0.5)
        self.assertFalse(low.upper_bound_exceeded)
        self.assertAlmostEqual(9.8, low.value, delta=1e-9)  # 0.98 x 10
        self.assertAlmostEqual(7.0, interpolate(x_y_array=[[3.0, 7.0]], x2=99.0).value,
                               delta=1e-9)


@needs_sdk
class TestEnvelopeCosting(unittest.TestCase):
    def costed_model(self):
        # Ruby: load_fixture + BtapNECB::Envelope.apply_prescriptive — see the
        # module docstring for why the raw fixture (with its own constructions)
        # stands in until btap.necb is ported.
        return load_fixture()

    def test_envelope_costing_covers_all_present_surface_types(self):
        import btap.costing.envelope as envelope
        from btap.audit import AuditLog
        audit = AuditLog()
        report = envelope.cost(self.costed_model(), city=CITY,
                               province_state=PROVINCE, audit=audit)

        self.assertGreater(report.total, 0)
        types = report.envelope["surface_types"]
        for surface_type in ("exterior_wall", "exterior_roof", "ground_contact_floor"):
            self.assertGreater(types[surface_type]["cost"], 0, f"{surface_type} costed")
            self.assertGreater(types[surface_type]["area_m2"], 0)
            self.assertAlmostEqual(
                types[surface_type]["cost"] / types[surface_type]["area_m2"],
                types[surface_type]["cost_per_m2"], delta=0.01)
        self.assertAlmostEqual(273.6, types["exterior_wall"]["area_m2"], delta=1.0)
        self.assertAlmostEqual(800.0, types["exterior_roof"]["area_m2"], delta=1.0)

        total_from_types = sum(v["cost"] for v in types.values())
        if "parapet_cost" in report.envelope:  # not requested here, guard anyway
            total_from_types += report.envelope["parapet_cost"]
        self.assertAlmostEqual(report.envelope["total_envelope_cost"],
                               total_from_types, delta=0.5)

        decision = next((e for e in audit.entries
                         if e["step"] == "costing_envelope"
                         and "cost-curve interpolation" in e["action"]), None)
        self.assertIsNotNone(decision)
        self.assertEqual(
            0, sum(1 for w in report.warnings if "regional adjustment" in w),
            "canonical TORONTO/ONTARIO resolves every prefix")

    def test_glazing_film_cost_applies_to_windows(self):
        import openstudio

        import btap.costing.envelope as envelope
        model = self.costed_model()
        wall = next(s for s in model.getSurfaces()
                    if s.outsideBoundaryCondition() == "Outdoors"
                    and s.surfaceType() == "Wall")
        wall.setWindowToWallRatio(0.4)
        # Ruby re-runs apply_prescriptive, which rebuilds every window as a
        # SimpleGlazing construction (U + SHGC); the fixture's own windows are
        # StandardGlazing with EMPTY thermalConductance/uFactor Optionals and
        # cannot be costed. Stand in for the prescriptive pass with one
        # SimpleGlazing construction on every window.
        glazing = openstudio.model.SimpleGlazing(model)
        glazing.setUFactor(1.9)
        glazing.setSolarHeatGainCoefficient(0.4)
        glazed = openstudio.model.Construction(model)
        glazed.setName("Test SimpleGlazing Window")
        glazed.setLayers([glazing])
        for sub in model.getSubSurfaces():
            sub.setConstruction(glazed)
        report = envelope.cost(model, city=CITY, province_state=PROVINCE)

        window = report.envelope["surface_types"]["exterior_fixed_window"]
        self.assertGreater(window["cost"], 0,
                           "windows costed (assembly curve + SHGC film premium)")
        row = next((r for r in report.envelope["construction_costs"]
                    if r["surface_type"] == "ExteriorFixedWindow"), None)
        self.assertIsNotNone(row)
        self.assertEqual("BTAP-ExteriorWindow-FixedWindow-1", row["assembly_name"])

    def test_zone_multiplier_scales_cost(self):
        import btap.costing.envelope as envelope
        base_model = self.costed_model()
        base = envelope.cost(base_model, city=CITY, province_state=PROVINCE)

        scaled_model = self.costed_model()
        for zone in scaled_model.getThermalZones():
            zone.setMultiplier(3)
        scaled = envelope.cost(scaled_model, city=CITY, province_state=PROVINCE)
        self.assertAlmostEqual(base.total * 3.0, scaled.total, delta=base.total * 0.01)

    def test_thermal_bridging_costed_by_material_id_not_first_row(self):
        import btap.costing.envelope as envelope
        from btap.audit import AuditLog
        tallies = {"parapet": {"BTAP-ExteriorWall-SteelFramed-1 good": 100.0},
                   "jamb": {"BTAP-ExteriorWall-SteelFramed-1 good": 50.0},
                   "transition": {"BTAP-ExteriorWall-SteelFramed-1 good": 500.0},
                   "ceiling": {"BTAP-ExteriorWall-SteelFramed-1 good": 500.0}}
        audit = AuditLog()
        report = envelope.cost(self.costed_model(), city=CITY, province_state=PROVINCE,
                               tb_tallies=tallies, audit=audit)

        tb = report.thermal_bridging
        self.assertGreater(tb["total_thermal_bridging_cost"], 0)
        descriptions = [m["description"] for m in tb["by_material"]]
        self.assertFalse(
            all("gypsum wallboard" in d for d in descriptions),
            "legacy defect: every edge priced as materials_opaque row 1 (gypsum); "
            "the port matches BY id")
        ids = [m["materials_opaque_id"] for m in tb["by_material"]]
        self.assertEqual(sorted(set(ids)), sorted(ids))
        decision = next((e for e in audit.entries
                         if e["step"] == "costing_thermal_bridging"
                         and e["level"] == "decision"), None)
        self.assertIsNotNone(decision)
        self.assertIn("matched BY ID", decision["action"])
        self.assertIn("gypsum", decision["evidence"])

        # parapet allowance rides on the envelope side (length x wall $/m2)
        self.assertGreater(report.envelope["parapet_cost"], 0)
        wall = report.envelope["surface_types"]["exterior_wall"]
        self.assertAlmostEqual(100.0 * wall["cost_per_m2"],
                               report.envelope["parapet_cost"], delta=1.0)

    def test_unknown_wall_reference_and_id_zero_warn_never_silent(self):
        import btap.costing.envelope as envelope
        from btap.audit import AuditLog
        tallies = {"corner": {"No-Such-Assembly good": 10.0}}
        audit = AuditLog()
        envelope.cost(self.costed_model(), city=CITY, province_state=PROVINCE,
                      tb_tallies=tallies, audit=audit)
        self.assertTrue(any("wall reference 'No-Such-Assembly good'" in w["action"]
                            for w in audit.warnings))

        # corner rows for SteelFramed-1 reference material id '0' (no materials_opaque row)
        tallies2 = {"corner": {"BTAP-ExteriorWall-SteelFramed-1 good": 10.0}}
        audit2 = AuditLog()
        envelope.cost(self.costed_model(), city=CITY, province_state=PROVINCE,
                      tb_tallies=tallies2, audit=audit2)
        self.assertTrue(any("material id '0'" in w["action"] for w in audit2.warnings),
                        "id '0' rows are skipped LOUDLY")

    def test_tallies_from_tbd_result(self):
        from btap.costing.envelope import thermal_bridging_costs
        tbd_result = {"io": {"edges": [
            {"type": "parapetconvex", "length": 12.0},
            {"type": "cornerconcave", "length": 4.0},
            {"type": "jamb", "length": 2.0},
            {"type": "transition", "length": 9.0},
        ]}}
        tallies = thermal_bridging_costs.tallies_from_tbd(
            tbd_result, "BTAP-ExteriorWall-SteelFramed-1 good")
        self.assertAlmostEqual(
            12.0, tallies["parapet"]["BTAP-ExteriorWall-SteelFramed-1 good"], delta=1e-9)
        self.assertAlmostEqual(
            4.0, tallies["corner"]["BTAP-ExteriorWall-SteelFramed-1 good"], delta=1e-9)
        self.assertIn("transition", tallies,
                      "kept in tallies; skipped at costing time")

    def test_unified_audit_spans_compliance_and_costing(self):
        """ONE audit spans reference generation + costing: the steps
        prescriptive/reference/coverage/costing_envelope/
        costing_thermal_bridging all land in a single log. Unblocked by M5's
        envelope domain."""
        import json

        import btap.costing.envelope as envelope
        from btap.audit import AuditLog
        from btap.necb import envelope as necb_envelope

        model = load_fixture()
        audit = AuditLog()
        necb_envelope.reference_envelope(model, vintage="2020", hdd=3890, audit=audit)
        envelope.cost(
            model, city=CITY, province_state=PROVINCE,
            tb_tallies={"parapet": {"BTAP-ExteriorWall-SteelFramed-1 good": 10.0}},
            audit=audit)

        steps = list(dict.fromkeys(e["step"] for e in audit.entries))
        for step in ("prescriptive", "reference", "coverage",
                     "costing_envelope", "costing_thermal_bridging"):
            self.assertIn(step, steps, "ONE audit spans reference generation + costing")
        self.assertGreater(len(json.loads(audit.to_json())), 30)


if __name__ == "__main__":
    unittest.main()
