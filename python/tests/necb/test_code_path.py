"""Stage 9a (docs/NECB_MULTI_EDITION_PLAN.md, "Stage 9 — independent code
families"): the determination lifecycle is code-family-NEUTRAL, and NECB is
one implementation of it behind ``CodePath``.

Two properties are worth a permanent gate:

* **the boundary** — every registered edition names a ``path`` module in its
  manifest, the registry resolves it the way it resolves ``behaviours``, and
  the neutral pipeline imports no code family (import-linter enforces the
  same thing over the whole graph; the AST check here fails with the offending
  line rather than a contract report).
* **the evidence** — ``compliance._build_reference``, ``._evaluate`` and
  ``._evaluate_unmet`` are the symbols the article-coverage pointers name
  (``necb_rules.json``, ``reference_rules.json``). After Stage 9a they are
  FORWARDING functions, and a forwarder that resolves the pointer without
  ever running would make the evidence technically valid and substantively
  false. These tests prove each one is on the executed call path.

Stage 9a's scope was CORRECTED afterwards (see the plan's "9a scope,
corrected" entry): 9a is an NECB-PRESERVING scaffold. Two properties more are
therefore gated here — the two NECB sentences that moved OFF the neutral
pipeline onto the family, and the inventory of NECB Section 8.4 article paths
still hardcoded in the shared renderer, which 9b/9c must neutralize.
"""

from __future__ import annotations

import ast
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import btap.codes as codes
from btap.codes import compliance, pipeline
from btap.codes.necb import path as necb_path
from btap.codes.report import sections
from tests.necb.support import load_raw_fixture, needs_sdk, proposed_with_hvac, zone_types_for

#: The protocol's members, by the names the plan fixed, plus ``prepare_model``
#: and ``abort`` — later lifecycle hooks whose family ownership keeps the
#: neutral pipeline from speaking NECB's requirements.
HOOKS = ("validate", "climate", "prepare_model", "prepare_annual", "consume_annual",
         "determine", "citations", "report_sections", "abort",
         "alternate_path")


class TestCodePathBinding(unittest.TestCase):
    def test_every_edition_names_a_code_path_that_resolves(self):
        for code_id in codes.code_ids():
            with self.subTest(code_id=code_id):
                ruleset = codes.resolve(code_id)
                self.assertTrue(ruleset.code_path,
                                f"{code_id}: manifest declares no 'path'")
                module = ruleset.path()
                self.assertEqual(ruleset.code_path, module.__name__)
                missing = [hook for hook in HOOKS if not callable(getattr(module, hook, None))]
                self.assertEqual([], missing, f"{code_id}: missing hooks {missing}")

    def test_the_same_module_object_comes_back(self):
        """Resolution is cached, like the behaviour modules: a determination
        asks for the path on every phase."""
        ruleset = codes.resolve("necb2020")
        self.assertIs(ruleset.path(), ruleset.path())

    def test_an_edition_without_a_path_raises_naming_the_manifest(self):
        bare = codes.Ruleset(id="necb2020", family="necb", edition="2020",
                             label="NECB 2020")
        with self.assertRaises(ValueError) as ctx:
            bare.path()
        message = str(ctx.exception)
        self.assertIn("necb2020", message)
        self.assertIn("manifest.json", message)

    def test_the_neutral_pipeline_imports_no_code_family(self):
        """Import-linter says the same thing over the whole graph; this names
        the line, and covers a family reached by a string that grimp would
        not see."""
        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                    "btap.codes.necb"):
                offenders.append(f"{node.lineno}: from {node.module} import ...")
            if isinstance(node, ast.Import):
                offenders.extend(f"{node.lineno}: import {alias.name}"
                                 for alias in node.names
                                 if alias.name.startswith("btap.codes.necb"))
        self.assertEqual([], offenders, f"btap/codes/pipeline.py: {offenders}")


class TestForwardingFunctionsAreExecuted(unittest.TestCase):
    """The three evidence-bearing symbols that moved must still RUN."""

    def test_evaluate_forwards_to_the_family(self):
        calls = []
        ruleset = codes.resolve("necb2020")
        original = necb_path.evaluate
        necb_path.evaluate = lambda *a: calls.append(a) or "verdict"
        try:
            self.assertEqual("verdict",
                             compliance._evaluate({}, ruleset, None, "audit"))
        finally:
            necb_path.evaluate = original
        self.assertEqual([({}, ruleset, None, "audit")], calls)

    def test_evaluate_unmet_forwards_to_the_family(self):
        calls = []
        ruleset = codes.resolve("necb2020")
        original = necb_path.evaluate_unmet
        necb_path.evaluate_unmet = lambda *a: calls.append(a) or "unmet"
        try:
            self.assertEqual("unmet",
                             compliance._evaluate_unmet({}, ruleset, "audit"))
        finally:
            necb_path.evaluate_unmet = original
        self.assertEqual([({}, ruleset, "audit")], calls)

    def test_the_determination_calls_the_evaluate_forwarder(self):
        """Not the family function directly — the source is the contract."""
        source = Path(necb_path.__file__).read_text(encoding="utf-8")
        self.assertIn("compliance._evaluate(", source)
        self.assertIn("compliance._evaluate_unmet(", source)
        self.assertIn("compliance._build_reference(run)", source)
        self.assertIn("compliance._run_annual(", source)

    @needs_sdk
    def test_build_reference_forwarder_runs_in_a_real_determination(self):
        seen = []
        original = compliance._build_reference

        def counted(run):
            seen.append(run.ruleset.id)
            return original(run)

        compliance._build_reference = counted
        try:
            result = compliance.performance_compliance(
                proposed_with_hvac(), code="necb2020", simulate="none",
                hdd=3890,
                building={"storeys": 1,
                          "zone_types": zone_types_for(load_raw_fixture()),
                          "winter_design_temp_c": -20},
                run_dir=tempfile.mkdtemp(prefix="stage9a-forward-"))
        finally:
            compliance._build_reference = original
        self.assertEqual(["necb2020"], seen,
                         "compliance._build_reference must be ON the executed "
                         "call path, not a stub that resolves the pointer")
        self.assertIsNotNone(result.reference_model)

    @needs_sdk
    def test_real_pipeline_uses_kiva_on_both_sides_before_applying_the_strip(self):
        proposed = proposed_with_hvac()
        convertible_name = "Surface 7"
        interior_name = "Surface 25"
        input_floor = proposed.getSurfaceByName(convertible_name).get()
        input_conductance = (
            input_floor.construction().get().to_LayeredConstruction().get()
            .thermalConductance().get())

        with tempfile.TemporaryDirectory(prefix="d32-real-path-") as run_dir:
            result = compliance.performance_compliance(
                proposed, code="necb2020", simulate="none", hdd=3890,
                building={
                    "storeys": 1,
                    "zone_types": zone_types_for(proposed),
                    "winter_design_temp_c": -20,
                },
                run_dir=run_dir)

        prepared_floor = result.proposed_model.getSurfaceByName(
            convertible_name).get()
        reference_floor = result.reference_model.getSurfaceByName(
            convertible_name).get()
        self.assertEqual("Foundation", prepared_floor.outsideBoundaryCondition())
        self.assertEqual("Foundation", reference_floor.outsideBoundaryCondition())
        prepared_conductance = (
            prepared_floor.construction().get().to_LayeredConstruction().get()
            .thermalConductance().get())
        self.assertAlmostEqual(
            input_conductance, prepared_conductance, delta=1e-9,
            msg="method normalization must retain the proposed slab-field R")

        proposed_foundation = prepared_floor.adjacentFoundation().get()
        reference_foundation = reference_floor.adjacentFoundation().get()
        self.assertFalse(
            proposed_foundation.interiorHorizontalInsulationMaterial()
            .is_initialized(),
            "the proposed receives the Kiva method, not the prescribed strip")
        self.assertTrue(
            reference_foundation.interiorHorizontalInsulationMaterial()
            .is_initialized(),
            "D-32's 1.2 m strip belongs only on the reference")
        self.assertAlmostEqual(
            1.2, reference_foundation.interiorHorizontalInsulationWidth().get(),
            delta=1e-9)

        refused_interior = result.proposed_model.getSurfaceByName(
            interior_name).get()
        self.assertEqual(
            "Ground", refused_interior.outsideBoundaryCondition(),
            "a floor with no exposed perimeter must be refused before conversion")
        self.assertFalse(refused_interior.adjacentFoundation().is_initialized())
        self.assertTrue(any(
            entry.get("ruling") == "D-32"
            and entry.get("article") == "8.4.1.2.(2)"
            and entry.get("level") == "decision"
            for entry in result.audit.entries
        ))
        self.assertFalse(any(
            entry.get("ruling") == "D-105"
            for entry in result.audit.entries
        ), "ordinary strip floors must not enter D-105's embedded-floor path")

    @needs_sdk
    def test_real_pipeline_leaves_full_area_climates_outside_kiva_preparation(self):
        from btap.modeling.envelope import constructions as Constructions

        proposed = proposed_with_hvac()
        with tempfile.TemporaryDirectory(prefix="d32-full-area-") as run_dir:
            result = compliance.performance_compliance(
                proposed, code="necb2020", simulate="none", hdd=7000,
                building={
                    "storeys": 1,
                    "zone_types": zone_types_for(proposed),
                    "winter_design_temp_c": -30,
                },
                run_dir=run_dir)

        self.assertEqual([], list(result.proposed_model.getFoundationKivas()))
        self.assertTrue(all(
            surface.outsideBoundaryCondition() == "Ground"
            for surface in result.proposed_model.getSurfaces()
            if surface.surfaceType() == "Floor" and surface.isGroundSurface()
        ))
        self.assertEqual([], list(result.reference_model.getFoundationKivas()))
        reference_floor = result.reference_model.getSurfaceByName(
            "Surface 7").get()
        self.assertEqual("Ground", reference_floor.outsideBoundaryCondition())
        full_area_target = 1.0 / (
            (1.0 / 0.379) - Constructions.film_r("floor", "ground"))
        reference_conductance = (
            reference_floor.construction().get().to_LayeredConstruction().get()
            .thermalConductance().get())
        self.assertAlmostEqual(
            full_area_target, reference_conductance, delta=1e-4,
            msg="zone 8 keeps D-32's existing full-area construction path")
        self.assertFalse(any(
            entry.get("ruling") == "D-32"
            and entry.get("article") == "8.4.1.2.(2)"
            for entry in result.audit.entries
        ), "the symmetry ruling is limited to the perimeter-strip branch")

    @needs_sdk
    def test_refused_foundation_write_rolls_back_conversion_and_its_material(self):
        from btap.audit import AuditLog
        from btap.modeling.envelope import foundations

        proposed = proposed_with_hvac()
        construction_handles = {
            str(obj.handle()) for obj in proposed.getLayeredConstructions()}
        material_handles = {str(obj.handle()) for obj in proposed.getMaterials()}
        original = foundations.create_kiva_foundation

        def refuse(_model, floor, _walls=(), *, perimeter_m=None, name=None):
            return {
                "created": False,
                "foundation": None,
                "floor": floor.nameString(),
                "walls": [],
                "perimeter_m": perimeter_m,
                "refusals": ["forced post-conversion refusal"],
            }

        foundations.create_kiva_foundation = refuse
        try:
            run = SimpleNamespace(
                proposed=proposed,
                audit=AuditLog(),
                ruleset=codes.resolve("necb2020"),
                hdd=3890,
                state={},
                opts={"ground_model": "kiva"},
            )
            necb_path.prepare_model(run)
        finally:
            foundations.create_kiva_foundation = original

        fallbacks = [
            entry for entry in run.audit.entries
            if "otherwise valid simple-Ground floors" in entry.get("action", "")
        ]
        self.assertEqual(1, len(fallbacks))
        self.assertTrue(all(
            "forced post-conversion refusal" in row["reasons"]
            for row in fallbacks[0]["inputs"]["surfaces"]))
        self.assertEqual(
            construction_handles,
            {str(obj.handle()) for obj in proposed.getLayeredConstructions()},
        )
        self.assertEqual(
            material_handles,
            {str(obj.handle()) for obj in proposed.getMaterials()},
            "rollback must remove the temporary carpet material as well as "
            "its cloned construction",
        )
        self.assertEqual([], list(proposed.getFoundationKivas()))
        self.assertTrue(all(
            surface.outsideBoundaryCondition() == "Ground"
            for surface in proposed.getSurfaces()
            if surface.surfaceType() == "Floor" and surface.isGroundSurface()
        ))

    @needs_sdk
    def test_real_pipeline_preserves_unresolved_embedded_floor_inventory(self):
        import openstudio

        proposed = proposed_with_hvac()
        floor = proposed.getSurfaceByName('Surface 7').get()
        self.assertEqual('Floor', floor.surfaceType())
        self.assertTrue(floor.isGroundSurface())
        foundation = openstudio.model.FoundationKiva(proposed)
        foundation.setName('Unresolved embedded floor foundation')
        self.assertTrue(floor.setAdjacentFoundation(foundation))

        availability = openstudio.model.ScheduleConstant(proposed)
        availability.setValue(1.0)
        temperature_limits = openstudio.model.ScheduleTypeLimits(proposed)
        temperature_limits.setUnitType('Temperature')
        temperature = openstudio.model.ScheduleConstant(proposed)
        temperature.setScheduleTypeLimits(temperature_limits)
        temperature.setValue(20.0)
        radiant = openstudio.model.ZoneHVACLowTemperatureRadiantElectric(
            proposed, availability, temperature)
        radiant.setName('Unresolved floor radiant')
        radiant.setRadiantSurfaceType('Floors')
        zone = floor.space().get().thermalZone().get()
        self.assertTrue(radiant.addToThermalZone(zone))
        self.assertEqual(
            [], list(radiant.surfaces()),
            'the SDK derives surfaces only from internal-source constructions')

        with tempfile.TemporaryDirectory(prefix='d105-real-path-') as run_dir:
            result = compliance.performance_compliance(
                proposed, code='necb2020', simulate='none', hdd=3890,
                building={
                    'storeys': 1,
                    'zone_types': zone_types_for(proposed),
                    'winter_design_temp_c': -20,
                },
                run_dir=run_dir)

        reference_floor = result.reference_model.getSurfaceByName(
            floor.nameString()).get()
        reference_foundation = reference_floor.adjacentFoundation().get()
        warnings = [
            entry for entry in result.audit.warnings
            if entry.get('ruling') == 'D-105'
            and entry.get('article') == '3.2.3.3.(4)(b)'
        ]
        self.assertEqual(1, len(warnings))
        self.assertEqual('reference building', warnings[0].get('building'))
        self.assertIn('UNRESOLVED', warnings[0]['action'])
        self.assertFalse(
            reference_foundation.interiorHorizontalInsulationMaterial()
            .is_initialized(),
            'the real envelope call must receive the pre-teardown inventory')

    @needs_sdk
    def test_real_pipeline_preserves_resolved_embedded_floor_inventory(self):
        import openstudio

        from btap.modeling.envelope import constructions as Constructions

        proposed = proposed_with_hvac()
        floor = proposed.getSurfaceByName('Surface 7').get()
        insulation = openstudio.model.StandardOpaqueMaterial(
            proposed, 'MediumSmooth', 0.03, 0.03, 30, 1200)
        slab = openstudio.model.StandardOpaqueMaterial(
            proposed, 'MediumRough', 0.1, 1.8, 2300, 900)
        internal = openstudio.model.ConstructionWithInternalSource(proposed)
        internal.setName('Resolved embedded floor construction')
        self.assertTrue(internal.setLayers([insulation, slab]))
        self.assertTrue(internal.setSourcePresentAfterLayerNumber(1))
        self.assertTrue(
            internal.setTemperatureCalculationRequestedAfterLayerNumber(1))
        self.assertTrue(internal.setInsulation(insulation))
        self.assertTrue(floor.setConstruction(internal))

        foundation = openstudio.model.FoundationKiva(proposed)
        foundation.setName('Resolved embedded floor foundation')
        self.assertTrue(floor.setAdjacentFoundation(foundation))

        with tempfile.TemporaryDirectory(prefix='d105-real-path-') as run_dir:
            result = compliance.performance_compliance(
                proposed, code='necb2020', simulate='none', hdd=3890,
                building={
                    'storeys': 1,
                    'zone_types': zone_types_for(proposed),
                    'winter_design_temp_c': -20,
                },
                run_dir=run_dir)

        reference_floor = result.reference_model.getSurfaceByName(
            floor.nameString()).get()
        reference_foundation = reference_floor.adjacentFoundation().get()
        target = 1.0 / (
            (1.0 / 0.757) - Constructions.film_r('floor', 'ground'))
        reference_construction = (
            reference_floor.construction().get().to_LayeredConstruction().get())
        self.assertAlmostEqual(
            target, reference_construction.thermalConductance().get(),
            delta=1e-4,
            msg='the real pipeline must apply the full-area table target')
        self.assertFalse(
            reference_foundation.interiorHorizontalInsulationMaterial()
            .is_initialized(),
            'the real envelope call must not fall through to the 1.2 m strip')
        decisions = [
            entry for entry in result.audit.entries
            if entry.get('ruling') == 'D-105'
            and entry.get('article') == '3.2.3.3.(4)(b)'
            and entry.get('level') == 'decision'
        ]
        self.assertEqual(1, len(decisions))
        self.assertEqual('reference building', decisions[0].get('building'))
        self.assertTrue(any(
            entry.get('ruling') == 'D-105'
            and entry.get('article') == '3.2.3.3.(5)'
            and 'ENERGYPLUS REJECTS' in entry['action']
            for entry in result.audit.warnings
        ))

    def test_build_reference_tells_the_hvac_pass_whether_sizing_FOLLOWS(self):
        """Witnesses the CALL SITE, which nothing else does.

        Fable's `302`: reverting `path.py`'s `sizing_follows=` argument so the
        flag is never passed left all 89 tests in the two efficiency modules
        green. The leaf guards were witnessed; the thing that switches them on
        was not — only verify-lane frozen scenarios covered it, and those do
        not run on a pull request.

        Both directions matter. `simulate: none` must send False, because then
        `_size_reference` returns before the second efficiency pass and the
        first pass's capacity warnings are the only disclosure there will be.
        Anything else must send True, because the determinations are redone
        after sizing.

        The absent key is pinned too: it reached `path.py` as a bracket read
        and raised `KeyError: 'simulate'` — the same defect this change fixes
        in `cli.py`. Absent now means False, which keeps the warnings.
        """
        from btap.audit import AuditLog
        from btap.codes.necb import envelope, hvac, lighting
        from btap.codes.necb.shw import reference as shw_reference

        originals = (
            envelope.prescriptive._embedded_floor_inventory,
            hvac.reference._reference_hvac,
            envelope.reference._apply,
            lighting.Reference._reference_lighting,
            shw_reference._reference_shw,
        )
        seen = []

        def reference_hvac(model, ruleset, **kwargs):
            seen.append(kwargs.get('sizing_follows', '<absent>'))
            # `assignments` because that is what ReferenceResult carries;
            # a fake missing a field its caller reads tests the fake.
            return SimpleNamespace(model=object(), assignments=[])

        envelope.prescriptive._embedded_floor_inventory = lambda _m: None
        hvac.reference._reference_hvac = reference_hvac
        envelope.reference._apply = lambda *_a, **_k: None
        lighting.Reference._reference_lighting = lambda *_a, **_k: None
        shw_reference._reference_shw = lambda *_a, **_k: None
        try:
            for simulate, expected in (('annual', True), ('sizing', True),
                                       ('none', False), (None, False)):
                opts = {
                    'building': {},
                    'actual_roof_absorptance_used': False,
                    'thermal_bridging': None,
                    'reference_daylighting': False,
                }
                if simulate is not None:
                    opts['simulate'] = simulate
                run = SimpleNamespace(
                    opts=opts, audit=AuditLog(), proposed=object(),
                    proposed_annual_data=None,
                    ruleset=codes.resolve('necb2020'), hdd=3890,
                    state={'ground_floor_perimeters': {}})
                seen.clear()
                necb_path.build_reference(run)
                with self.subTest(simulate=simulate):
                    self.assertEqual(
                        [expected], seen,
                        f'simulate={simulate!r} must pass '
                        f'sizing_follows={expected}: a False here reports the '
                        'pre-sizing state as a finding, and a True where no '
                        'second pass runs loses the disclosure entirely')
        finally:
            (envelope.prescriptive._embedded_floor_inventory,
             hvac.reference._reference_hvac,
             envelope.reference._apply,
             lighting.Reference._reference_lighting,
             shw_reference._reference_shw) = originals

    def test_embedded_floor_inventory_precedes_reference_hvac_teardown(self):
        from btap.audit import AuditLog
        from btap.codes.necb import envelope, hvac, lighting
        from btap.codes.necb.shw import reference as shw_reference

        calls = []
        sentinel = object()
        perimeter_sentinel = {"Floor 1": 12.5}
        proposed = object()
        reference = object()

        originals = (
            envelope.prescriptive._embedded_floor_inventory,
            hvac.reference._reference_hvac,
            envelope.reference._apply,
            lighting.Reference._reference_lighting,
            shw_reference._reference_shw,
        )

        def inventory(model):
            calls.append(('inventory', model))
            return sentinel

        def reference_hvac(model, ruleset, **_kwargs):
            calls.append(('hvac', model, ruleset.id))
            return SimpleNamespace(model=reference, assignments=[])

        def reference_envelope(model, ruleset, **kwargs):
            calls.append((
                'envelope', model, ruleset.id,
                kwargs['embedded_floor_inventory'],
                kwargs['ground_floor_perimeters']))

        envelope.prescriptive._embedded_floor_inventory = inventory
        hvac.reference._reference_hvac = reference_hvac
        envelope.reference._apply = reference_envelope
        lighting.Reference._reference_lighting = lambda *_a, **_k: None
        shw_reference._reference_shw = lambda *_a, **_k: None
        run = SimpleNamespace(
            opts={
                'building': {},
                'actual_roof_absorptance_used': False,
                'thermal_bridging': None,
                'reference_daylighting': False,
            },
            audit=AuditLog(),
            proposed=proposed,
            proposed_annual_data=None,
            ruleset=codes.resolve('necb2020'),
            hdd=3890,
            reference=None,
            state={'ground_floor_perimeters': perimeter_sentinel},
        )
        try:
            necb_path.build_reference(run)
        finally:
            (
                envelope.prescriptive._embedded_floor_inventory,
                hvac.reference._reference_hvac,
                envelope.reference._apply,
                lighting.Reference._reference_lighting,
                shw_reference._reference_shw,
            ) = originals

        self.assertEqual('inventory', calls[0][0])
        self.assertEqual('hvac', calls[1][0])
        self.assertEqual(
            ('envelope', reference, 'necb2020', sentinel,
             perimeter_sentinel), calls[2])
        self.assertIs(reference, run.reference)


class TestRenderHooks(unittest.TestCase):
    def test_citations_are_the_editions_article_map(self):
        for code_id in codes.code_ids():
            ruleset = codes.resolve(code_id)
            self.assertEqual(dict(ruleset.articles),
                             ruleset.path().citations(ruleset))

    def test_report_sections_list_what_the_run_produced(self):
        run = pipeline._Run(report={"proposed": {"total_site_kwh": 1.0},
                                    "reference": {}, "tier": "Tier 1"})
        self.assertEqual(["proposed", "tier"], necb_path.report_sections(run))

    def test_report_sections_of_an_empty_run(self):
        self.assertEqual([], necb_path.report_sections(pipeline._Run(report={})))


class TestTheFamilySpeaksForTheCode(unittest.TestCase):
    """The two NECB sentences the neutral pipeline used to speak itself.

    Both moved to ``btap.codes.necb.path`` with their text, article, level,
    inputs and ORDER unchanged (verified against a captured audit trail: the
    unsized warning stays index 3 of a ``simulate="none"`` run, the abort
    stays the last entry of a flushed failure). These tests keep them on the
    family side — a second family must not inherit NECB's citations."""

    #: audit-surface call names, matching the decisions registry's walker.
    AUDIT_CALLS = {"warn", "warning", "info", "decision"}

    def test_the_pipeline_cites_no_code_article_on_any_audit_surface(self):
        """The narrow, load-bearing property: nothing the NEUTRAL pipeline
        writes into an audit trail names a NECB article or section. (Prose
        about NECB in a comment is documentation, not an emission; the
        PreflightError texts in ``_validate_input_model`` still name 8.4.4.7
        and 8.4.1.2 and are recorded as deferred to 9b/9c.)"""
        tree = ast.parse(Path(pipeline.__file__).read_text(encoding="utf-8"))
        offenders = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in self.AUDIT_CALLS):
                continue
            literals = [value.value for value in
                        [*node.args, *(k.value for k in node.keywords)]
                        if isinstance(value, ast.Constant)
                        and isinstance(value.value, str)]
            if any(re.search(r"\b[58]\.\d+\.\d+", text) for text in literals):
                offenders.append(f"line {node.lineno}: {node.func.attr}()")
            if any(keyword.arg == "article" for keyword in node.keywords):
                offenders.append(f"line {node.lineno}: article=")
        self.assertEqual(
            [], offenders,
            "btap/codes/pipeline.py is code-family-neutral: an audit entry "
            "that cites a code article belongs to the family's CodePath — "
            f"{offenders}")

    def test_the_unsized_warning_is_the_familys(self):
        self.assertIn("5.2.10.1 energy-recovery determination needs",
                      Path(necb_path.__file__).read_text(encoding="utf-8"))

    def test_the_abort_hook_carries_the_necb_citation(self):
        class Recorder:
            def __init__(self):
                self.calls = []

            def warn(self, step, action, **keywords):
                self.calls.append((step, action, keywords))

        audit = Recorder()
        necb_path.abort(audit, ValueError("weather['ddy'] is required"))
        self.assertEqual(1, len(audit.calls))
        step, action, keywords = audit.calls[0]
        self.assertEqual("compliance", step)
        self.assertEqual(
            "run ABORTED before completion: ValueError: weather['ddy'] is "
            "required", action)
        self.assertEqual("8.4.2.1.", keywords["article"])
        self.assertEqual({"error_class": "ValueError"}, keywords["inputs"])

    def test_the_failure_flush_delegates_to_the_family(self):
        """Ordering is the pipeline's: the abort is the LAST entry written."""
        events = []

        class Path_:
            def abort(self, audit, error):
                events.append(("abort", type(error).__name__))

        original = pipeline._write_outputs
        pipeline._write_outputs = lambda *a: events.append(("write", ))
        try:
            pipeline._flush_on_failure("/nonexistent", {}, None,
                                       ValueError("boom"), Path_())
        finally:
            pipeline._write_outputs = original
        self.assertEqual([("abort", "ValueError"), ("write", )], events)


class TestDeferredRendererInventory(unittest.TestCase):
    """9a delivered an NECB-PRESERVING scaffold: the shared HTML renderer
    still writes NECB Section 8.4 article paths as literals, and neutralizing
    them is deferred to 9b/9c, where a second family makes the neutral shape
    testable rather than speculative.

    This pins the inventory so a later edit to ``report/sections.py`` is
    DELIBERATE — a new hardcoded citation fails here, and so does a removal
    that has not been recorded as 9b/9c progress."""

    #: ``{function: lines mentioning an 8.4.x article path}`` in
    #: ``btap/codes/report/sections.py`` at the 9a scope correction.
    DEFERRED_8_4_SITES = {
        "verdict_banner": 6,
        "path_declaration": 2,
        "energy": 3,
        "hvac_building_block": 2,
    }

    @staticmethod
    def _sites_by_function():
        source = Path(sections.__file__).read_text(encoding="utf-8")
        lines = source.splitlines()
        tree = ast.parse(source)
        tops = sorted(
            (node.lineno, node.name) for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)))
        counts = {}
        for number, line in enumerate(lines, 1):
            if "8.4" not in line:
                continue
            owner = None
            for start, name in tops:
                if start <= number:
                    owner = name
                else:
                    break
            counts[owner] = counts.get(owner, 0) + 1
        return counts

    def test_the_hardcoded_8_4_inventory_is_unchanged(self):
        self.assertEqual(self.DEFERRED_8_4_SITES, self._sites_by_function())

    def test_thirteen_sites_remain_for_9b_9c(self):
        self.assertEqual(13, sum(self.DEFERRED_8_4_SITES.values()))

    def test_the_render_hooks_have_no_product_call_site_yet(self):
        """``citations`` and ``report_sections`` are declared and tested but
        NOT wired: the renderer takes a report dict, not a run or a ruleset,
        so wiring either today would add or move a report leaf. Recorded as
        deferred rather than claimed as delivered."""
        product = sorted(Path(sections.__file__).parents[2].rglob("*.py"))
        self.assertIn(Path(pipeline.__file__), product,
                      "product source glob went stale")
        callers = [f"{p}:{n}" for p in product
                   for n, line in enumerate(
                       p.read_text(encoding="utf-8").splitlines(), 1)
                   if re.search(r"\.(citations|report_sections)\(", line)]
        self.assertEqual(
            [], callers,
            "a product call site appeared for a hook the plan records as "
            f"deferred to 9b/9c — update the narrowed claim: {callers}")


class TestAlternatePath(unittest.TestCase):
    def test_an_unknown_path_name_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            necb_path.alternate_path(
                None, "step-code", ruleset=codes.resolve("necb2025"),
                weather={}, hdd=None, run_dir=".", simulate="none",
                run_period=None, archetypes_map=None, process_loads_kwh=0.0,
                costing=False, city=None, province_state=None, costs_csv=None,
                necb_loads=None, report_html=False, report_options={},
                audit=None)
        self.assertIn("step-code", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
