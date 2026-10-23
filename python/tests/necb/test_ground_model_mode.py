"""Method-neutral ground preparation, equivalent UA and factor-method limits."""

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


def _air_gap_floors(model, names):
    import openstudio

    names = set(names)
    floors = [surface for surface in model.getSurfaces()
              if surface.nameString() in names]
    if {surface.nameString() for surface in floors} != names:
        raise AssertionError(f"fixture floors not found: {sorted(names)}")
    air = openstudio.model.AirGap(model)
    air.setName("Legitimate slab air gap")
    air.setThermalResistance(0.2)
    concrete = openstudio.model.StandardOpaqueMaterial(
        model, "MediumRough", 0.1, 1.8, 2300.0, 900.0)
    construction = openstudio.model.Construction(model)
    construction.setName("Slab with air gap")
    construction.setLayers([air, concrete])
    for floor in floors:
        floor.setConstruction(construction)


def _unusable_ground_construction(model, name="Surface 7"):
    import openstudio

    floor = model.getSurfaceByName(name).get()
    construction = openstudio.model.ConstructionAirBoundary(model)
    construction.setName("Not a lawful ground slab construction")
    floor.setConstruction(construction)
    return floor


def _valid_f_factor_floor(model, name="Surface 7"):
    import openstudio

    floor = model.getSurfaceByName(name).get()
    construction = openstudio.model.FFactorGroundFloorConstruction(model)
    construction.setName("Valid F-factor ground floor")
    construction.setFFactor(0.7)
    construction.setArea(floor.grossArea())
    construction.setPerimeterExposed(40.0)
    floor.setConstruction(construction)
    floor.setOutsideBoundaryCondition("GroundFCfactorMethod")
    return floor


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
    def test_model_defect_refuses_before_sizing_even_in_simple_mode(self):
        model = proposed_with_hvac()
        _unusable_ground_construction(model)
        original = pipeline._size_proposed
        sizing_called = []

        def must_not_size(run):
            sizing_called.append(run)
            self.fail("the ground-strip gate must run before proposed sizing")

        pipeline._size_proposed = must_not_size
        try:
            with self.assertRaises(compliance.PreflightError) as caught:
                _run(model, ground_model="simple", hdd=STRIP_HDD)
        finally:
            pipeline._size_proposed = original

        self.assertEqual([], sizing_called)
        self.assertIn("ground-strip pre-flight FAILED", str(caught.exception))
        self.assertIn("Surface 7", str(caught.exception))
        self.assertIn("slab-field U cannot be established",
                      str(caught.exception))

    def test_cli_maps_the_gate_to_exit_3_without_space_type_advice(self):
        import openstudio

        model = proposed_with_hvac()
        _unusable_ground_construction(model)
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
        _unusable_ground_construction(model)
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
        _unusable_ground_construction(model, "Surface 19")
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
class TestSimpleGroundModeEstablishesTarget(unittest.TestCase):
    def test_simple_applies_the_equivalent_ua_at_the_real_reference_call_site(self):
        from btap.modeling.envelope import constructions

        result = _run(proposed_with_hvac(), ground_model="simple",
                      hdd=STRIP_HDD)

        self.assertIsNone(result.compliant)
        self.assertNotIn("compliance_determination", result.report)
        self.assertNotIn("no_determination", result.report)
        self.assertEqual([], list(result.proposed_model.getFoundationKivas()))
        self.assertEqual([], list(result.reference_model.getFoundationKivas()))

        proposed = result.proposed_model.getSurfaceByName("Surface 7").get()
        reference = result.reference_model.getSurfaceByName("Surface 7").get()
        field_c = (
            proposed.construction().get().to_LayeredConstruction().get()
            .thermalConductance().get())
        film_r = constructions.film_r("floor", "ground")
        field_u = 1.0 / ((1.0 / field_c) + film_r)
        fraction = min(1.0, 40.0 * 1.2 / proposed.grossArea())
        strip_u = min(field_u, 0.757)
        expected_u = fraction * strip_u + (1.0 - fraction) * field_u
        expected_c = 1.0 / ((1.0 / expected_u) - film_r)
        reference_c = (
            reference.construction().get().to_LayeredConstruction().get()
            .thermalConductance().get())
        self.assertAlmostEqual(expected_c, reference_c, delta=1e-6)

        mode_entries = [
            entry for entry in result.audit.entries
            if entry.get("step") == "prepare"
            and "equivalent-UA approximation" in entry.get("action", "")
        ]
        self.assertEqual(1, len(mode_entries))
        self.assertIsNone(
            mode_entries[0].get("building"),
            "a method selection must not be attributed to the input model")

    def test_cli_simple_exit_6_is_only_because_simulation_was_skipped(self):
        import openstudio

        model = proposed_with_hvac()
        with tempfile.TemporaryDirectory(prefix="ground-simple-cli-") as tmp:
            osm = Path(tmp, "input.osm")
            model.save(openstudio.path(str(osm)), True)
            out, err = io.StringIO(), io.StringIO()

            exit_code = codes_cli.run([
                str(osm), "--simulate", "none", "--hdd", str(STRIP_HDD),
                "--storeys", "1", "--ground-model", "simple",
                "--no-report", "--quiet", "-o", str(Path(tmp, "run")),
            ], out=out, err=err)

            self.assertEqual(codes_cli.EXIT["no_determination"], exit_code)
            self.assertNotEqual(codes_cli.EXIT["preflight"], exit_code)
            self.assertNotIn("REJECTED before any simulation ran",
                             err.getvalue())
            report = json.loads(
                Path(tmp, "run", "report.json").read_text(encoding="utf-8"))
            self.assertNotIn("compliance_determination", report)
            self.assertNotIn("no_determination", report)

    def test_better_than_table_slab_is_not_made_worse(self):
        from btap.modeling.envelope import constructions

        model = proposed_with_hvac()
        floor = model.getSurfaceByName("Surface 7").get()
        original = floor.construction().get().to_LayeredConstruction().get()
        target_c = 1.0 / (
            (1.0 / 0.5) - constructions.film_r("floor", "ground"))
        floor.setConstruction(
            constructions.opaque_at_conductance(model, original, target_c))

        result = _run(model, ground_model="simple", hdd=STRIP_HDD)
        proposed = result.proposed_model.getSurfaceByName("Surface 7").get()
        reference = result.reference_model.getSurfaceByName("Surface 7").get()
        proposed_c = (
            proposed.construction().get().to_LayeredConstruction().get()
            .thermalConductance().get())
        reference_c = (
            reference.construction().get().to_LayeredConstruction().get()
            .thermalConductance().get())
        self.assertAlmostEqual(target_c, proposed_c, delta=1e-9)
        self.assertAlmostEqual(proposed_c, reference_c, delta=1e-9)
        row = next(
            row
            for entry in result.audit.entries
            if "uniform equivalent UA" in entry.get("action", "")
            for row in entry["inputs"]["surfaces"]
            if row["floor"] == "Surface 7"
        )
        self.assertFalse(row["construction_changed"])
        self.assertEqual(
            row["field_u_overall_w_m2k"],
            row["strip_u_overall_w_m2k"])

    def test_measured_zero_has_fraction_zero_and_no_reference_change(self):
        result = _run(proposed_with_hvac(), ground_model="simple",
                      hdd=STRIP_HDD)

        zero_proposed = result.proposed_model.getSurfaceByName("Surface 25").get()
        zero_reference = result.reference_model.getSurfaceByName("Surface 25").get()
        positive_proposed = result.proposed_model.getSurfaceByName("Surface 7").get()
        positive_reference = result.reference_model.getSurfaceByName("Surface 7").get()

        def conductance(surface):
            return (
                surface.construction().get().to_LayeredConstruction().get()
                .thermalConductance().get())

        self.assertAlmostEqual(
            conductance(zero_proposed), conductance(zero_reference), delta=1e-9)
        self.assertNotAlmostEqual(
            conductance(positive_proposed), conductance(positive_reference),
            delta=1e-6)
        row = next(
            row
            for entry in result.audit.entries
            if "uniform equivalent UA" in entry.get("action", "")
            for row in entry["inputs"]["surfaces"]
            if row["floor"] == "Surface 25"
        )
        self.assertEqual(0.0, row["strip_area_fraction"])
        self.assertFalse(row["construction_changed"])

    def test_factor_method_override_preserves_diagnostic_energies(self):
        report = {
            "proposed": {"total_site_kwh": 120.0},
            "reference": {"total_site_kwh": 100.0},
            "compliance_determination": "conditional",
            "compliance_determination_reason": {"ahj_ids": ["AHJ-1"]},
        }
        run = SimpleNamespace(
            compliant=True, report=report, audit=AuditLog())

        necb_path._refuse_determination(
            run, {"reason": "ground_method_not_supported",
                  "ground_model": "kiva", "floors": ["Floor 1"]})

        self.assertIsNone(run.compliant)
        self.assertEqual(120.0, report["proposed"]["total_site_kwh"])
        self.assertEqual(100.0, report["reference"]["total_site_kwh"])
        self.assertEqual("no_determination",
                         report["compliance_determination"])
        self.assertNotIn("compliance_determination_reason", report)
        self.assertIn("DIAGNOSTIC only", run.audit.entries[-1]["action"])
        self.assertIn(
            "submitter is not required",
            report["no_determination"]["what_would_fix_it"])


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
            and "measured zero exposed edge" in entry.get("action", "")
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
        self.assertNotIn("no_determination", result.report)


@needs_sdk
class TestEveryInvalidMeasurementIsRefused(unittest.TestCase):
    def test_unknown_massless_layer_falls_back_to_simple_on_both_sides(self):
        model = proposed_with_hvac()
        _unknown_massless_floors(model, ["Surface 7"])

        result = _run(model, ground_model="kiva", hdd=STRIP_HDD)

        proposed = result.proposed_model.getSurfaceByName("Surface 7").get()
        reference = result.reference_model.getSurfaceByName("Surface 7").get()
        self.assertEqual("Ground", proposed.outsideBoundaryCondition())
        self.assertEqual("Ground", reference.outsideBoundaryCondition())
        self.assertNotIn("no_determination", result.report)
        fallback = [
            entry for entry in result.audit.entries
            if "otherwise valid simple-Ground floors" in entry.get("action", "")
        ]
        self.assertEqual(1, len(fallback))
        self.assertEqual(
            ["Surface 7"],
            [row["floor"] for row in fallback[0]["inputs"]["surfaces"]])

    def test_all_kiva_incompatibilities_are_reported_together(self):
        model = proposed_with_hvac()
        names = ["Surface 1", "Surface 7", "Surface 13", "Surface 19"]
        _unknown_massless_floors(model, names)

        result = _run(model, ground_model="kiva", hdd=STRIP_HDD)

        fallback = next(
            entry for entry in result.audit.entries
            if "otherwise valid simple-Ground floors" in entry.get("action", "")
        )
        self.assertEqual(
            sorted(names),
            sorted(row["floor"] for row in fallback["inputs"]["surfaces"]))

    def test_air_gap_is_legal_for_the_simple_fallback(self):
        model = proposed_with_hvac()
        _air_gap_floors(model, ["Surface 7"])

        result = _run(model, ground_model="kiva", hdd=STRIP_HDD)

        proposed = result.proposed_model.getSurfaceByName("Surface 7").get()
        reference = result.reference_model.getSurfaceByName("Surface 7").get()
        self.assertEqual("Ground", proposed.outsideBoundaryCondition())
        self.assertEqual("Ground", reference.outsideBoundaryCondition())
        proposed_c = (
            proposed.construction().get().to_LayeredConstruction().get()
            .thermalConductance().get())
        reference_c = (
            reference.construction().get().to_LayeredConstruction().get()
            .thermalConductance().get())
        self.assertLess(reference_c, proposed_c)

    def test_valid_f_factor_method_runs_but_withholds_the_determination(self):
        for hdd in (STRIP_HDD, FULL_AREA_HDD):
            with self.subTest(hdd=hdd):
                model = proposed_with_hvac()
                _valid_f_factor_floor(model)

                result = _run(model, ground_model="kiva", hdd=hdd)

                self.assertEqual(
                    "GroundFCfactorMethod",
                    result.proposed_model.getSurfaceByName(
                        "Surface 7").get().outsideBoundaryCondition())
                self.assertEqual(
                    "GroundFCfactorMethod",
                    result.reference_model.getSurfaceByName(
                        "Surface 7").get().outsideBoundaryCondition())
                self.assertEqual(
                    "no_determination",
                    result.report["compliance_determination"])
                block = result.report["no_determination"]
                self.assertEqual(
                    "ground_method_not_supported",
                    block["detail"]["reason"])
                self.assertEqual(["Surface 7"], block["detail"]["floors"])
                self.assertIn(
                    "submitter is not required",
                    block["what_would_fix_it"])

    def test_cli_maps_valid_f_factor_to_exit_6_not_preflight(self):
        import openstudio

        model = proposed_with_hvac()
        _valid_f_factor_floor(model)
        with tempfile.TemporaryDirectory(prefix="ground-factor-cli-") as tmp:
            osm = Path(tmp, "input.osm")
            model.save(openstudio.path(str(osm)), True)
            out, err = io.StringIO(), io.StringIO()

            exit_code = codes_cli.run([
                str(osm), "--simulate", "none", "--hdd", str(STRIP_HDD),
                "--storeys", "1", "--ground-model", "kiva",
                "--no-report", "--quiet", "-o", str(Path(tmp, "run")),
            ], out=out, err=err)

            self.assertEqual(codes_cli.EXIT["no_determination"], exit_code)
            self.assertNotIn("REJECTED before any simulation ran",
                             err.getvalue())
            report = json.loads(
                Path(tmp, "run", "report.json").read_text(encoding="utf-8"))
            self.assertEqual(
                "ground_method_not_supported",
                report["no_determination"]["detail"]["reason"])

    def test_zero_edge_waives_even_a_kiva_incompatible_air_gap(self):
        model = proposed_with_hvac()
        _air_gap_floors(model, ["Surface 25"])

        result = _run(model, ground_model="kiva", hdd=STRIP_HDD)

        zero = result.proposed_model.getSurfaceByName("Surface 25").get()
        self.assertEqual("Ground", zero.outsideBoundaryCondition())
        self.assertFalse(zero.adjacentFoundation().is_initialized())
        self.assertNotIn("no_determination", result.report)
        self.assertTrue(
            result.proposed_model.getSurfaceByName(
                "Surface 7").get().adjacentFoundation().is_initialized())

    def test_absolute_elevation_alone_is_not_an_input_defect(self):
        model = proposed_with_hvac()
        floor = model.getSurfaceByName("Surface 7").get()
        floor.space().get().setZOrigin(4.055)

        run = _path_run(model)
        necb_path.prepare_model(run)

        self.assertTrue(floor.adjacentFoundation().is_initialized())

    def test_exact_coplanar_counterpart_is_a_contradictory_adjacency(self):
        import openstudio

        model = proposed_with_hvac()
        floor = model.getSurfaceByName("Surface 7").get()
        counterpart = openstudio.model.Surface(floor.vertices(), model)
        counterpart.setName("Surface 7 counterpart")
        counterpart.setSurfaceType("RoofCeiling")
        counterpart.setSpace(floor.space().get())
        counterpart.setConstruction(floor.construction().get())

        with self.assertRaises(compliance.PreflightError) as caught:
            necb_path.prepare_model(_path_run(model))

        self.assertIn("Surface 7 counterpart", str(caught.exception))
        self.assertIn("exact co-planar surface", str(caught.exception))

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


@needs_sdk
class TestZeroEdgeFactorFloorDoesNotContradictItself(unittest.TestCase):
    """The audit and the report must agree about whether a target exists.

    A zero-edge `GroundFCfactorMethod` floor was reported both ways at once:
    `path.py#prepare_model` filtered it out as zero-edge and the run
    determined normally, while the reference pass appended it to
    `unsupported_ground_methods` BEFORE looking at the perimeter and warned
    that "the building energy target is NOT established by this transform".
    Fable's `299`, LOW.

    A measured zero exposed edge means 3.2.3.3.(3) prescribes no strip
    segment for that floor, so the missing F-factor translation costs the
    target nothing. The rule mirrors `prepare_model` exactly — an ABSENT or
    non-finite measurement is not a measured zero and still reports.
    """

    @staticmethod
    def _unsupported_method_warnings(result):
        """ONLY the reference transform's warning.

        `path.py#prepare_model` emits its own "no validated ... foundation
        method" line, so a loose filter matches that instead and is blind to
        the code under test — with it, waiving EVERY perimeter still passed.
        "retain a submitted foundation method" is unique to
        `prescriptive.py`'s warning.
        """
        return [w for w in (result.report.get("warnings") or [])
                if "retain a submitted foundation method" in w]

    def _fixture(self, *, factor_floor):

        model = proposed_with_hvac()
        # Surface 25 is the fixture's interior floor: fully enclosed by its
        # neighbours, so its measured exposed perimeter is zero.
        floor = model.getSurfaceByName("Surface 25").get()
        if factor_floor:
            floor.setOutsideBoundaryCondition("GroundFCfactorMethod")
        return model, floor

    def test_a_zero_edge_factor_floor_reports_no_unestablished_target(self):
        model, _floor = self._fixture(factor_floor=True)
        result = _run(model, ground_model="kiva", hdd=STRIP_HDD)

        # Assert on the SPECIFIC warning, not a substring: "NOT established"
        # also appears in the interzone temperature-difference warnings that
        # every run of this fixture emits, so a broad match passes or fails
        # for reasons unrelated to ground methods.
        self.assertEqual([], self._unsupported_method_warnings(result))
        self.assertNotEqual("no_determination",
                            result.report.get("compliance_determination"))

    def test_an_ABSENT_measurement_is_not_a_measured_zero(self):
        """`None` was claimed to report and never checked.

        The code comment and D-32 both say an absent measurement is not a
        measured zero and still reports, but nothing exercised it: mutating
        the condition to `perimeter is None or (...)` passed 26/26. That
        matters because absent is exactly what an embedded floor's perimeter
        is in the pipeline's dict, so the mutation would have exempted every
        embedded factor floor silently. Fable's `300`.
        """
        from btap.audit import AuditLog
        from btap.codes import resolve
        from btap.codes.necb.envelope import prescriptive

        model, floor = self._fixture(factor_floor=True)
        audit = AuditLog()
        unsupported = []
        prescriptive._assign_ground_floor(
            model, floor, resolve("necb2020"), STRIP_HDD, True, {}, audit,
            prescriptive._embedded_floor_inventory(model),
            ground_floor_perimeters={},      # the floor's key is ABSENT
            simple_ground_applied=[],
            unsupported_ground_methods=unsupported)

        self.assertEqual(1, len(unsupported),
                         "an unmeasurable edge is not proof of zero and must "
                         "still report the unsupported method")
        self.assertEqual("Surface 25", unsupported[0]["floor"])

    def test_an_EMBEDDED_zero_edge_factor_floor_is_NOT_exempt(self):
        """The exemption's rationale is strip-only, so it needs the extent gate.

        3.2.3.3.(3) prescribes no strip segment for a zero-edge floor — but an
        EMBEDDED floor takes full area under 3.2.3.3.(4)(b) whatever its edge
        measures, and there the missing applier DOES cost the target. Keying
        only on the perimeter exempted it with a rationale that does not apply.

        The embedded case is the one that reaches this: a full-area CLIMATE
        leaves `ground_floor_perimeters` empty, so the perimeter is absent and
        the floor reports anyway. An embedded floor in a STRIP climate has its
        perimeter measured while its extent is already full area. Fable's
        `300`, probe D.
        """
        from btap.audit import AuditLog
        from btap.codes import resolve
        from btap.codes.necb.envelope import prescriptive
        from tests.necb.test_envelope_prescriptive import (
            embedded_ground_floor_model,
        )

        model, floor, _foundation, _radiant = embedded_ground_floor_model()
        floor.setOutsideBoundaryCondition("GroundFCfactorMethod")
        inventory = prescriptive._embedded_floor_inventory(model)
        self.assertEqual("embedded", inventory.status(floor.nameString()))

        unsupported = []
        prescriptive._assign_ground_floor(
            model, floor, resolve("necb2020"), STRIP_HDD, True, {}, AuditLog(),
            inventory,
            # measured zero, as an interior embedded slab would be
            ground_floor_perimeters={floor.nameString(): 0.0},
            simple_ground_applied=[],
            unsupported_ground_methods=unsupported)

        self.assertEqual(
            1, len(unsupported),
            "an embedded floor is insulated over its FULL AREA, so a zero "
            "exposed edge does not excuse the missing applier")

    def test_an_EXPOSED_factor_floor_still_reports(self):
        """The control. Without it this test could pass by never reporting at
        all, and the unsupported-method disclosure is the thing we rely on."""

        model = proposed_with_hvac()
        floor = next(s for s in model.getSurfaces()
                     if s.surfaceType() == "Floor"
                     and s.outsideBoundaryCondition() == "Ground"
                     and s.nameString() != "Surface 25")
        floor.setOutsideBoundaryCondition("GroundFCfactorMethod")
        result = _run(model, ground_model="kiva", hdd=STRIP_HDD)

        self.assertEqual("no_determination",
                         result.report.get("compliance_determination"),
                         "an exposed factor floor has a strip segment BTAP "
                         "cannot represent, so it must still refuse")
        self.assertNotEqual([], self._unsupported_method_warnings(result),
                            "and it must still SAY so")


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


if __name__ == "__main__":
    unittest.main()
