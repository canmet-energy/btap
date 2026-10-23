"""Preflight refusal when a required reference ground strip is unrepresentable.

The proposed building is exempt from 3.2.3.3.(3)'s perimeter strip, but the
8.4.1.1.(1) building energy target must include it. Phase 2b is the first point
that knows the climate-dependent extent. It therefore inventories every
applicable floor without mutating any of them and rejects the input before
sizing when a positive or unmeasurable exposed edge cannot take Kiva.
"""

import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from btap.audit import AuditLog
from btap.codes import cli as codes_cli
from btap.codes import compliance, pipeline, resolve
from btap.codes.necb import path as necb_path
from tests.necb.support import needs_sdk, proposed_with_hvac, zone_types_for

STRIP_HDD = 3890      # Toronto — below full_area_min_hdd (7000)
FULL_AREA_HDD = 8000  # above it: 3.2.3.3.(4) full area, applied by construction


def _run(model, *, ground_model, hdd):
    with tempfile.TemporaryDirectory(prefix="ground-model-") as run_dir:
        return compliance.performance_compliance(
            model, code="necb2020", simulate="none", hdd=hdd,
            ground_model=ground_model,
            building={"storeys": 1, "zone_types": zone_types_for(model)},
            run_dir=run_dir)


def _path_run(model, *, ground_model="kiva", hdd=STRIP_HDD):
    return SimpleNamespace(
        proposed=model,
        audit=AuditLog(),
        ruleset=resolve("necb2020"),
        hdd=hdd,
        state={},
        opts={"ground_model": ground_model},
    )


def _unknown_massless_floors(model, names):
    import openstudio

    names = set(names)
    floors = [surface for surface in model.getSurfaces()
              if surface.nameString() in names]
    if {surface.nameString() for surface in floors} != names:
        raise AssertionError(f"fixture floors not found: {sorted(names)}")
    material = openstudio.model.MasslessOpaqueMaterial(model)
    material.setName("Unknown Kiva finish")
    material.setThermalResistance(0.2)
    construction = openstudio.model.Construction(model)
    construction.setName("Unsupported Kiva construction")
    construction.setLayers([material])
    for floor in floors:
        floor.setConstruction(construction)


def _space_less_floor(model):
    import openstudio

    points = openstudio.Point3dVector()
    for x, y in ((100.0, 0.0), (110.0, 0.0),
                 (110.0, 10.0), (100.0, 10.0)):
        points.append(openstudio.Point3d(x, y, 0.0))
    surface = openstudio.model.Surface(points, model)
    surface.setName("Parentless Ground Floor")
    surface.setSurfaceType("Floor")
    surface.setOutsideBoundaryCondition("Ground")
    source = model.getSurfaceByName("Surface 7").get()
    surface.setConstruction(source.construction().get())
    return surface


@needs_sdk
class TestGroundStripPreflight(unittest.TestCase):
    def test_simple_refuses_before_sizing_in_a_perimeter_strip_climate(self):
        original = pipeline._size_proposed
        sizing_called = []

        def must_not_size(run):
            sizing_called.append(run)
            self.fail("the ground-strip gate must run before proposed sizing")

        pipeline._size_proposed = must_not_size
        try:
            with self.assertRaises(compliance.PreflightError) as caught:
                _run(proposed_with_hvac(), ground_model="simple",
                     hdd=STRIP_HDD)
        finally:
            pipeline._size_proposed = original

        self.assertEqual([], sizing_called)
        self.assertIn("ground-strip pre-flight FAILED", str(caught.exception))
        self.assertIn("ground-model mode 'simple'", str(caught.exception))
        self.assertIn("Surface 7", str(caught.exception))

    def test_cli_maps_the_gate_to_exit_3_without_space_type_advice(self):
        import openstudio

        model = proposed_with_hvac()
        _unknown_massless_floors(model, ["Surface 7"])
        with tempfile.TemporaryDirectory(prefix="ground-gate-cli-") as tmp:
            osm = Path(tmp, "input.osm")
            model.save(openstudio.path(str(osm)), True)
            out, err = io.StringIO(), io.StringIO()

            exit_code = codes_cli.run([
                str(osm), "--simulate", "none", "--hdd", str(STRIP_HDD),
                "--storeys", "1", "--ground-model", "kiva",
                "--no-report", "--quiet", "-o", str(Path(tmp, "run")),
            ], out=out, err=err)

            self.assertEqual(codes_cli.EXIT["preflight"], exit_code)
            self.assertIn("REJECTED before any simulation ran", err.getvalue())
            self.assertIn("Surface 7", err.getvalue())
            self.assertNotIn("--space-type", err.getvalue(),
                             "ground geometry must not receive the unrelated "
                             "space-type repair advice")
            report = json.loads(
                Path(tmp, "run", "report.json").read_text(encoding="utf-8"))
            self.assertEqual({}, report)

    def test_the_failure_is_recorded_against_the_input_model(self):
        model = proposed_with_hvac()
        _unknown_massless_floors(model, ["Surface 7"])
        with tempfile.TemporaryDirectory(prefix="ground-gate-audit-") as run_dir:
            with self.assertRaises(compliance.PreflightError):
                compliance.performance_compliance(
                    model, code="necb2020", simulate="none", hdd=STRIP_HDD,
                    ground_model="kiva",
                    building={"storeys": 1,
                              "zone_types": zone_types_for(model)},
                    run_dir=run_dir)

            entries = json.loads(
                Path(run_dir, "audit.json").read_text(encoding="utf-8"))
        failures = [
            entry for entry in entries
            if entry.get("step") == "prepare"
            and entry.get("ruling") == "D-32"
            and "PREFLIGHT FAILED" in entry.get("action", "")
        ]
        self.assertEqual(1, len(failures))
        self.assertEqual("input model", failures[0].get("building"))
        self.assertEqual(["Surface 7"],
                         failures[0]["inputs"]["floors"])

    def test_all_floors_are_checked_before_any_floor_is_changed(self):
        model = proposed_with_hvac()
        _unknown_massless_floors(model, ["Surface 7"])
        before = {
            surface.nameString(): str(surface.construction().get().handle())
            for surface in model.getSurfaces()
            if surface.surfaceType() == "Floor"
            and surface.outsideBoundaryCondition() == "Ground"
        }

        with self.assertRaises(compliance.PreflightError):
            necb_path.prepare_model(_path_run(model))

        self.assertEqual([], list(model.getFoundationKivas()))
        self.assertEqual(
            before,
            {
                surface.nameString(): str(surface.construction().get().handle())
                for surface in model.getSurfaces()
                if surface.surfaceType() == "Floor"
                and surface.outsideBoundaryCondition() == "Ground"
            },
            "a later invalid floor must be found before an earlier floor's "
            "construction is converted",
        )


@needs_sdk
class TestGroundStripPreflightScope(unittest.TestCase):
    def test_simple_is_ordinary_where_the_full_area_requirement_applies(self):
        result = _run(proposed_with_hvac(), ground_model="simple",
                      hdd=FULL_AREA_HDD)

        self.assertIsNotNone(result.reference_model)
        self.assertEqual([], list(result.proposed_model.getFoundationKivas()))

    def test_kiva_prepares_the_exposed_floors_and_waives_confirmed_zero_edge(self):
        result = _run(proposed_with_hvac(), ground_model="kiva", hdd=STRIP_HDD)

        self.assertTrue(list(result.proposed_model.getFoundationKivas()))
        self.assertTrue(any(
            entry.get("step") == "prepare"
            and "could NOT take a Kiva foundation" in entry.get("action", "")
            and entry.get("inputs", {}).get("floors") == 1
            for entry in result.audit.entries
        ), "the measured-zero interior tile remains unchanged and disclosed")
        interior = result.proposed_model.getSurfaceByName("Surface 25").get()
        self.assertEqual("Ground", interior.outsideBoundaryCondition())
        self.assertFalse(interior.adjacentFoundation().is_initialized())

    def test_unconditioned_floor_matches_the_reference_envelope_scope(self):
        model = proposed_with_hvac()
        floor = model.getSurfaceByName("Surface 7").get()
        space = floor.space().get()
        space.setPartofTotalFloorArea(False)
        self.assertTrue(
            floor.setOutsideBoundaryCondition("GroundFCfactorMethod"))

        result = _run(model, ground_model="kiva", hdd=STRIP_HDD)

        prepared = result.proposed_model.getSurfaceByName("Surface 7").get()
        self.assertEqual("GroundFCfactorMethod",
                         prepared.outsideBoundaryCondition())
        self.assertFalse(prepared.adjacentFoundation().is_initialized())


@needs_sdk
class TestEveryInvalidMeasurementIsRefused(unittest.TestCase):
    def test_one_unknown_material_names_the_offending_floor(self):
        model = proposed_with_hvac()
        _unknown_massless_floors(model, ["Surface 7"])

        with self.assertRaises(compliance.PreflightError) as caught:
            _run(model, ground_model="kiva", hdd=STRIP_HDD)

        message = str(caught.exception)
        self.assertIn("Surface 7", message)
        self.assertIn("no sourced Kiva-compatible replacement", message)

    def test_all_unknown_materials_are_reported_together(self):
        model = proposed_with_hvac()
        names = ["Surface 1", "Surface 7", "Surface 13", "Surface 19"]
        _unknown_massless_floors(model, names)

        with self.assertRaises(compliance.PreflightError) as caught:
            _run(model, ground_model="kiva", hdd=STRIP_HDD)

        for name in names:
            self.assertIn(name, str(caught.exception))

    def test_f_factor_floor_without_kiva_is_refused(self):
        model = proposed_with_hvac()
        floor = model.getSurfaceByName("Surface 7").get()
        self.assertTrue(
            floor.setOutsideBoundaryCondition("GroundFCfactorMethod"))

        with self.assertRaises(compliance.PreflightError) as caught:
            _run(model, ground_model="kiva", hdd=STRIP_HDD)

        self.assertIn("GroundFCfactorMethod", str(caught.exception))
        self.assertIn("Surface 7", str(caught.exception))

    def test_space_less_floor_is_unmeasurable_not_zero(self):
        model = proposed_with_hvac()
        _space_less_floor(model)

        with self.assertRaises(compliance.PreflightError) as caught:
            necb_path.prepare_model(_path_run(model))

        self.assertIn("Parentless Ground Floor", str(caught.exception))
        self.assertIn("could not measure the exposed perimeter",
                      str(caught.exception))

    def test_nonfinite_perimeter_is_unmeasurable_not_zero(self):
        from btap.modeling.envelope import foundations

        model = proposed_with_hvac()
        original = foundations.exposed_perimeters

        def with_nan(candidate_model, floors):
            measured = original(candidate_model, floors)
            measured["perimeters"]["Surface 7"] = math.nan
            return measured

        foundations.exposed_perimeters = with_nan
        try:
            with self.assertRaises(compliance.PreflightError) as caught:
                necb_path.prepare_model(_path_run(model))
        finally:
            foundations.exposed_perimeters = original

        self.assertIn("Surface 7", str(caught.exception))
        self.assertIn("not a finite length", str(caught.exception))
        self.assertEqual([], list(model.getFoundationKivas()))


class TestTheModeIsValidatedAtTheBoundary(unittest.TestCase):
    def test_the_two_modes_are_accepted(self):
        for mode in ("kiva", "simple"):
            self.assertEqual(mode, pipeline._ground_model(mode))

    def test_anything_else_raises_rather_than_meaning_simple(self):
        for bad in (None, "Kiva", "KIVA", "", "nonsense", 0, True):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError) as caught:
                    pipeline._ground_model(bad)
                self.assertIn("ground_model must be one of",
                              str(caught.exception))


@needs_sdk
class TestHangarInteriorFloorAdjacency(unittest.TestCase):
    def test_surface_335_is_matched_to_the_ceiling_below_and_passes_the_gate(self):
        from btap._sdk import load_model

        root = Path(__file__).resolve().parents[3]
        model = load_model(
            root / "models" / "gagetown_coldlake_Hangar_pre-1960.osm")
        floor = model.getSurfaceByName("Surface 335").get()
        ceiling = model.getSurfaceByName("Surface 563").get()

        self.assertEqual("Surface", floor.outsideBoundaryCondition())
        self.assertEqual("Surface", ceiling.outsideBoundaryCondition())
        self.assertEqual(ceiling.handle(), floor.adjacentSurface().get().handle())
        self.assertEqual(floor.handle(), ceiling.adjacentSurface().get().handle())
        self.assertEqual(
            "000 Interior Floor", floor.construction().get().nameString())
        self.assertEqual(
            floor.construction().get().handle(),
            ceiling.construction().get().handle(),
            "the exact co-planar pair uses the same interior floor assembly",
        )

        necb_path.prepare_model(_path_run(model))

        self.assertEqual("Surface", floor.outsideBoundaryCondition())
        self.assertEqual(ceiling.handle(), floor.adjacentSurface().get().handle())
        self.assertFalse(floor.adjacentFoundation().is_initialized())


if __name__ == "__main__":
    unittest.main()
