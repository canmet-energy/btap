"""Port of btap-necb/test/test_compliance.rb: the umbrella pipeline —
proposed -> reference (HVAC + envelope, one clone, one audit) ->
sizing/annual EnergyPlus -> 8.4.1.2 comparison -> unified costing ->
report.json + audit.json."""

import json
import os
import tempfile
import unittest
from pathlib import Path

from btap.necb import performance_compliance
from btap.necb.compliance import (
    _bump_capacities,
    _next_sizing_factor,
)
from tests.necb.support import (
    DDY,
    EPW,
    load_raw_fixture,
    needs_engine,
    needs_sdk,
    proposed_with_hvac,
    zone_types_for,
)


def weather():
    return {"epw": str(EPW), "ddy": str(DDY)}


def building_for(model):
    return {"storeys": 1, "zone_types": zone_types_for(model),
            "winter_design_temp_c": -20}


def week(end_day=7):
    return {"begin_month": 1, "begin_day": 1, "end_month": 1,
            "end_day": end_day}


@needs_sdk
class TestComplianceNoEngine(unittest.TestCase):
    def test_failed_run_still_writes_audit_trail(self):
        # A run that aborts mid-pipeline must still flush its audit trail to
        # run_dir (a broken proposed dies before the reference is even
        # built). The missing weather['ddy'] raises the existing ValueError
        # at the weather guard, which sits inside the diagnostics-capturing
        # try.
        dir = tempfile.mkdtemp(prefix="osnecb-fail-")
        model = proposed_with_hvac()
        with self.assertRaises(ValueError) as ctx:
            performance_compliance(
                model, vintage="2020", simulate="annual",
                weather={"epw": str(EPW)},  # deliberately missing ddy
                building=building_for(model), run_dir=dir)
        self.assertIn("ddy", str(ctx.exception),
                      "original error propagates unchanged")

        self.assertTrue(os.path.exists(os.path.join(dir, "audit.txt")),
                        "audit.txt written despite the failure")
        self.assertTrue(os.path.exists(os.path.join(dir, "audit.json")),
                        "audit.json written despite the failure")
        self.assertTrue(os.path.exists(os.path.join(dir, "report.json")),
                        "partial report.json written")
        audit_txt = Path(dir, "audit.txt").read_text(encoding="utf-8")
        self.assertIn("ABORTED", audit_txt,
                      "the abort is recorded in the audit trail")
        self.assertIn("performance-path run started", audit_txt,
                      "the pre-failure narrative is preserved for debugging")

    def test_preflight_rejects_unresolvable_space_type_with_suggestions(self):
        # Pre-flight gate: a space type that does not resolve against the
        # NECB catalog must abort the run BEFORE any transform — an
        # unresolvable type silently keeps the proposed's lighting/loads in
        # the reference (the clone), waiving the allowance. The refusal must
        # be actionable (nearest catalog names) and must still flush the
        # audit trail.
        dir = tempfile.mkdtemp(prefix="osnecb-preflight-")
        model = proposed_with_hvac()
        for st in model.getSpaceTypes():
            if st.spaces():
                st.setStandardsSpaceType("Office - enclosed")  # legacy name
        with self.assertRaises(ValueError) as ctx:
            performance_compliance(
                model, vintage="2020", simulate="none", hdd=3890,
                building=building_for(model), run_dir=dir)
        self.assertIn("pre-flight FAILED", str(ctx.exception))
        self.assertIn("Office - enclosed", str(ctx.exception),
                      "names the offending type")
        self.assertIn("Office enclosed > 25 m2", str(ctx.exception),
                      "suggests the nearest real catalog names")
        audit_txt = Path(dir, "audit.txt").read_text(encoding="utf-8")
        self.assertIn("UNRESOLVABLE", audit_txt,
                      "refusal recorded in the flushed audit trail")

    def test_none_mode_transforms_without_simulation(self):
        result = performance_compliance(
            proposed_with_hvac(), vintage="2020", simulate="none", hdd=3890,
            building=building_for(load_raw_fixture()),
            run_dir=tempfile.mkdtemp(prefix="osnecb-none-"))

        self.assertIsNone(result.compliant,
                          "compliance undetermined without annual runs")
        self.assertTrue(
            list(result.reference_model.getAirLoopHVACs())
            + list(result.reference_model.getPlantLoops()),
            "reference HVAC generated")
        wall = next(s for s in result.reference_model.getSurfaces()
                    if s.outsideBoundaryCondition() == "Outdoors"
                    and s.surfaceType() == "Wall")
        self.assertIn("Lightweight", wall.construction().get().nameString(),
                      "reference envelope applied to the SAME clone")
        self.assertTrue(any("UNSIZED" in w["action"]
                            for w in result.audit.warnings),
                        "unsized path warns loudly")
        entries = result.audit.entries
        self.assertTrue(any(e.get("article") == "8.4.3.2.(1)-(2)"
                            for e in entries),
                        "8.4.3.2 loads-identity satisfied-by-clone note")
        self.assertTrue(
            any("8.4.4.5." in str(e.get("article") or "")
                and e.get("building") == "reference building"
                for e in entries),
            "reference_lighting Part 4 allowance cited, stamped reference")
        self.assertTrue(
            any("8.4.4.20." in str(e.get("article") or "")
                and e.get("building") == "reference building"
                for e in entries),
            "reference_shw Part 6 efficiencies cited, stamped reference")
        # D-51: reference daylighting is ON by default — the pipeline builds
        # the 8.4.4.5.(9)-(12) photocontrols; reference_lighting must NOT
        # claim (5)-(12) are unmodeled.
        d51 = next((e for e in entries
                    if e.get("step") == "compliance"
                    and "D-51" in str(e.get("ruling") or "")
                    and e.get("building") == "reference building"), None)
        self.assertIsNotNone(d51, "reference daylighting ran by default, "
                                  "cited as D-51 and stamped reference")
        self.assertEqual("decision", d51["level"],
                         "daylighting ON is a decision, not a warning")
        self.assertIn("8.4.4.5.(9)-(12)", str(d51.get("article")))
        self.assertFalse(
            any(w.get("step") == "lighting_reference"
                and "8.4.4.5.(5)-(12)" in str(w.get("article") or "")
                for w in result.audit.warnings),
            'the "(5)-(12) NOT modeled" warning is silenced when '
            "reference_daylighting ran")
        # the transform really ran (whether it PLACES controls depends on the
        # 4.2.2 threshold selection, which excepts this fixture's spaces)
        self.assertTrue(any(e.get("step") == "daylighting"
                            and e.get("building") == "reference building"
                            for e in entries),
                        "the reference daylighting transform ran and audited "
                        "itself")

        # The umbrella's OWN manifest is emitted at runtime (D-09): real
        # pipeline limitations warn; gap_owner "modeller" entries are info
        # scope notes. 8.4.2.2 / 8.4.2.3 are per-sentence.
        umbrella_coverage = [e for e in entries if e.get("step") == "coverage"]
        calc = next((e for e in umbrella_coverage
                     if e.get("article") == "8.4.2.2.(1)"), None)
        self.assertIsNotNone(calc, "umbrella 8.4.2.2.(1) coverage emitted")
        self.assertEqual("warning", calc["level"],
                         "(1) has a real pipeline limitation (elevators)")
        backup = next(e for e in umbrella_coverage
                      if e.get("article") == "8.4.2.2.(5)")
        self.assertEqual("modeller", backup["inputs"]["gap_owner"],
                         "(5) redundant-equipment exclusion is a modeller call")
        climate = next((e for e in umbrella_coverage
                        if e.get("article") == "8.4.2.3.(2)"), None)
        self.assertIsNotNone(climate, "umbrella 8.4.2.3.(2) coverage emitted")
        self.assertEqual("info", climate["level"],
                         "modeller-scope gap is a scope note, NOT a warning")
        self.assertEqual("modeller", climate["inputs"]["gap_owner"])
        self.assertIn("modeller scope", climate["action"])
        attach = next(e for e in umbrella_coverage
                      if e.get("article") == "8.4.2.3.(1)")
        self.assertEqual("implemented", attach["inputs"]["status"],
                         "(1) weather attach is implemented")
        determination = next((e for e in umbrella_coverage
                              if e.get("article") == "8.4.1.2."), None)
        self.assertEqual("info",
                         determination and determination.get("level"),
                         "umbrella 8.4.1.2 implemented — info")

        report = json.loads(Path(result.run_dir,
                                 "report.json").read_text(encoding="utf-8"))
        self.assertIsNone(report["compliant"])
        self.assertTrue(os.path.exists(os.path.join(result.run_dir,
                                                    "audit.json")))
        self.assertTrue(os.path.exists(os.path.join(result.run_dir,
                                                    "audit.txt")))

    def test_input_model_validation_gates(self):
        import openstudio

        dir = tempfile.mkdtemp(prefix="osnecb-input-")
        # missing file, named
        with self.assertRaises(ValueError) as ctx:
            performance_compliance("/nope/missing.osm", vintage="2020",
                                   simulate="none", hdd=3890, run_dir=dir)
        self.assertIn("/nope/missing.osm", str(ctx.exception))

        # structurally empty model
        with self.assertRaises(ValueError) as ctx:
            performance_compliance(openstudio.model.Model(), vintage="2020",
                                   simulate="none", hdd=3890, run_dir=dir)
        self.assertIn("not simulate-able", str(ctx.exception))

        # no thermostat anywhere -> a run would free-float into a meaningless
        # determination
        bare = load_raw_fixture()
        for z in bare.getThermalZones():
            z.resetThermostatSetpointDualSetpoint()
        with self.assertRaises(ValueError) as ctx:
            performance_compliance(bare, vintage="2020", simulate="none",
                                   hdd=3890, run_dir=dir)
        self.assertIn("NO thermal zone carries a thermostat",
                      str(ctx.exception))

        # storeys undeterminable -> raise naming all three remedies; override
        # rescues
        no_storeys = load_raw_fixture()
        for st in no_storeys.getBuildingStorys():
            st.remove()
        no_storeys.getBuilding().resetStandardsNumberOfAboveGroundStories()
        with self.assertRaises(ValueError) as ctx:
            performance_compliance(no_storeys, vintage="2020", simulate="none",
                                   hdd=3890, run_dir=dir)
        self.assertIn("ABOVE-GROUND STOREY COUNT", str(ctx.exception))
        # the tagged variant with the override passes the pre-flight
        tagged = load_raw_fixture()
        for st in tagged.getBuildingStorys():
            st.remove()
        tagged.getBuilding().resetStandardsNumberOfAboveGroundStories()
        for st in tagged.getSpaceTypes():
            if st.spaces():
                st.setStandardsBuildingType("Space Function")
                st.setStandardsSpaceType("Office enclosed > 25 m2")
        result = performance_compliance(tagged, vintage="2020",
                                        simulate="none", hdd=3890,
                                        building={"storeys": 1}, run_dir=dir)
        info = next(e for e in result.audit.entries
                    if "structurally simulate-able" in e["action"])
        self.assertEqual("building: override",
                         info["inputs"]["storeys_source"])

    def test_next_sizing_factor_secant_and_fallback(self):
        # 8.4.1.2.(5) unit mechanics (no EnergyPlus): the secant step
        # extrapolates the next sizing factor from a zone's own (factor,
        # unmet-hours) history, clamped to stay incremental; without a usable
        # slope it falls back to the geometric step.
        call = _next_sizing_factor

        # First bump: no history -> geometric step.
        self.assertAlmostEqual(1.25, call([], 1.0, 400.0, 90.0, 1.25),
                               delta=1e-9)

        # Two observations with a real slope -> secant lands on target:
        # (1.0, 400 h) then (3.0, 150 h); slope -125 h/factor; target 90 h ->
        # 3.48.
        self.assertAlmostEqual(3.48, call([(1.0, 400.0)], 3.0, 150.0, 90.0,
                                          1.25), delta=1e-6)

        # A wild extrapolation is clamped to max(step, 2.0)x current.
        clamped = call([(1.0, 400.0)], 1.1, 399.0, 90.0, 1.25)
        self.assertAlmostEqual(1.1 * 2.0, clamped, delta=1e-9,
                               msg="per-round growth capped")
        clamped_step = call([(1.0, 400.0)], 1.1, 399.0, 90.0, 3.0)
        self.assertAlmostEqual(1.1 * 3.0, clamped_step, delta=1e-9,
                               msg="cap never undercuts the configured step")

        # Perverse slope (hours went UP as the factor rose) -> fallback.
        self.assertAlmostEqual(2.0 * 1.25,
                               call([(1.0, 100.0)], 2.0, 300.0, 90.0, 1.25),
                               delta=1e-9)

        # Flat history (no >= 1 h difference) cannot support a slope.
        self.assertAlmostEqual(2.0 * 1.25,
                               call([(1.0, 300.4)], 2.0, 300.0, 90.0, 1.25),
                               delta=1e-9)

    def test_bump_capacities_targets_failing_zones(self):
        # 8.4.1.2.(5) targeting (no EnergyPlus): with per-zone unmet hours
        # available, only the failing thermal blocks get Sizing:Zone factor
        # bumps; without them the bump falls back to the global
        # SizingParameters; a gate no single zone explains gets the global
        # fallback ALONGSIDE the zonal bumps (mixed).
        import openstudio

        model = openstudio.model.Model()
        z_bad = openstudio.model.ThermalZone(model)
        z_bad.setName("Zone Bad")
        z_ok = openstudio.model.ThermalZone(model)
        z_ok.setName("Zone Ok")

        report = {
            "proposed": {"zone_unmet_occupied_hours": {
                "ZONE BAD": {"heating": 400.0, "cooling": 300.0},
                "ZONE OK": {"heating": 50.0, "cooling": 100.0}}},
            "reference": {"zone_unmet_occupied_hours": {
                "ZONE BAD": {"heating": 10.0, "cooling": 100.0},
                "ZONE OK": {"heating": 10.0, "cooling": 100.0}}}}
        global_heating = model.getSizingParameters().heatingSizingFactor()
        global_cooling = model.getSizingParameters().coolingSizingFactor()
        trace = {}
        factors = _bump_capacities(model, "proposed", report,
                                   {"heating": True, "cooling": True}, "2020",
                                   step=1.4, trace=trace)

        self.assertEqual("zonal", factors["mode"])
        self.assertEqual(["ZONE BAD"], list(factors["zones"].keys()),
                         "only the failing thermal block is bumped (heating "
                         "> 100 h; cooling > reference +10%)")
        sz_bad = z_bad.sizingZone()
        self.assertTrue(sz_bad.zoneHeatingSizingFactor().is_initialized(),
                        "failing zone got a heating factor")
        self.assertAlmostEqual(global_heating * 1.4,
                               sz_bad.zoneHeatingSizingFactor().get(),
                               delta=1e-6,
                               msg="first bump = effective (global) x step")
        self.assertTrue(sz_bad.zoneCoolingSizingFactor().is_initialized(),
                        "failing zone got a cooling factor")
        self.assertAlmostEqual(global_cooling * 1.4,
                               sz_bad.zoneCoolingSizingFactor().get(),
                               delta=1e-6)
        self.assertFalse(
            z_ok.sizingZone().zoneHeatingSizingFactor().is_initialized(),
            "passing zone untouched")
        self.assertFalse(
            z_ok.sizingZone().zoneCoolingSizingFactor().is_initialized())
        self.assertAlmostEqual(
            global_heating, model.getSizingParameters().heatingSizingFactor(),
            delta=1e-6, msg="global factor untouched")
        self.assertEqual(
            [("proposed", "ZONE BAD", "heating")],
            [k for k in trace if k[2] == "heating"],
            "history recorded per zone/metric for the next-round secant")

        # No per-zone data at all -> global fallback, flagged as such.
        bare = openstudio.model.Model()
        openstudio.model.ThermalZone(bare)
        bare_global = bare.getSizingParameters().heatingSizingFactor()
        factors = _bump_capacities(bare, "proposed",
                                   {"proposed": {}, "reference": {}},
                                   {"heating": True, "cooling": False},
                                   "2020", step=1.4, trace={})
        self.assertEqual("global", factors["mode"])
        self.assertAlmostEqual(bare_global * 1.4,
                               bare.getSizingParameters().heatingSizingFactor(),
                               delta=1e-6)

        # Heating attributable to a zone, cooling gate failing with NO zone
        # over its per-zone allowance (facility union) -> mixed.
        mixed_model = openstudio.model.Model()
        mz = openstudio.model.ThermalZone(mixed_model)
        mz.setName("Zone Bad")
        mixed_report = {
            "proposed": {"zone_unmet_occupied_hours": {
                "ZONE BAD": {"heating": 400.0, "cooling": 105.0}}},
            "reference": {"zone_unmet_occupied_hours": {
                "ZONE BAD": {"heating": 10.0, "cooling": 100.0}}}}
        mixed_gc = mixed_model.getSizingParameters().coolingSizingFactor()
        mixed_gh = mixed_model.getSizingParameters().heatingSizingFactor()
        factors = _bump_capacities(mixed_model, "proposed", mixed_report,
                                   {"heating": True, "cooling": True}, "2020",
                                   step=1.4, trace={})
        self.assertEqual("mixed", factors["mode"])
        self.assertIn("ZONE BAD", factors["zones"])
        self.assertAlmostEqual(mixed_gc * 1.4,
                               factors["global"]["cooling_sizing_factor"],
                               delta=1e-3)
        self.assertAlmostEqual(
            mixed_gc * 1.4,
            mixed_model.getSizingParameters().coolingSizingFactor(),
            delta=1e-6)
        self.assertAlmostEqual(
            mixed_gh,
            mixed_model.getSizingParameters().heatingSizingFactor(),
            delta=1e-6, msg="heating stays zonal — global heating untouched")

    def test_caller_model_never_mutated(self):
        model = proposed_with_hvac()
        before = sorted(s.construction().get().nameString()
                        for s in model.getSurfaces())
        performance_compliance(
            model, vintage="2020", simulate="none", hdd=3890,
            building=building_for(model),
            run_dir=tempfile.mkdtemp(prefix="osnecb-mut-"))
        after = sorted(s.construction().get().nameString()
                       for s in model.getSurfaces())
        self.assertEqual(before, after, "the pipeline works on its own copy")


@needs_engine
class TestComplianceWithEngine(unittest.TestCase):
    def test_sizing_mode_with_costing(self):
        dir = tempfile.mkdtemp(prefix="osnecb-sizing-")
        result = performance_compliance(
            proposed_with_hvac(), vintage="2020", simulate="sizing",
            weather=weather(), building=building_for(load_raw_fixture()),
            costing=True, run_dir=dir)

        self.assertIsNone(result.compliant)
        for label in ("proposed", "reference"):
            cost = result.report[label]["cost"]
            self.assertGreater(cost["hvac"], 0,
                               f"{label} HVAC costed on sized model")
            self.assertGreater(cost["envelope"], 0, f"{label} envelope costed")
            self.assertAlmostEqual(cost["hvac"] + cost["envelope"],
                                   cost["total"], delta=0.02)
            self.assertEqual("TORONTO", cost["city"],
                             "cost location resolved from the EPW site")
        self.assertIn("incremental_cost_proposed_vs_reference", result.report)

        # ONE audit spans every domain of the pipeline
        steps = {e["step"] for e in result.audit.entries}
        for step in ("compliance", "selection", "build", "efficiency",
                     "coverage", "prescriptive", "reference",
                     "costing_envelope"):
            self.assertIn(step, steps)
        self.assertTrue(any(str(e["step"]).startswith("costing_")
                            and e["level"] == "decision"
                            for e in result.audit.entries))

    def test_annual_mode_week_run_full_determination(self):
        from btap.necb import decisions as Decisions

        dir = tempfile.mkdtemp(prefix="osnecb-annual-")
        result = performance_compliance(
            proposed_with_hvac(), vintage="2020", simulate="annual",
            weather=weather(), building=building_for(load_raw_fixture()),
            run_dir=dir, run_period=week())

        for label in ("proposed", "reference"):
            section = result.report[label]
            self.assertTrue(section["clean_run"],
                            f"{label} EnergyPlus run is clean")
            self.assertGreater(section["total_site_kwh"], 0,
                               f"{label} consumed energy")
            self.assertGreater(section["end_uses_kwh"]["heating"], 0,
                               f"{label} heated in a Toronto January week")
            self.assertIsNotNone(
                section["unmet_occupied_hours"]["heating"],
                f"{label} unmet-hours read from SQL")
            self.assertGreater(section["eui_kwh_per_m2"], 0)

        self.assertIsNotNone(result.compliant, "a determination was made")
        self.assertEqual([], result.report["capacity_iterations"],
                         "well-sized buildings need no 8.4.1.2.(5) capacity "
                         "increases")
        self.assertEqual(False, result.report["annual"],
                         "shortened run period flagged")
        self.assertTrue(any("SHORTENED" in w["action"]
                            for w in result.audit.warnings),
                        "week-long run loudly flagged as not code-compliant")

        target = next((e for e in result.audit.entries
                       if e.get("article") == "8.4.1.2.(2)"), None)
        self.assertIsNotNone(target, "building-energy-target decision cited")
        self.assertGreater(
            target["inputs"]["reference_building_energy_target_kwh"], 0)
        self.assertTrue(any(e.get("article") == "8.4.1.2.(3)"
                            for e in result.audit.entries))
        self.assertTrue(any(e.get("article") == "8.4.1.2.(4)"
                            for e in result.audit.entries))

        report = json.loads(Path(dir, "report.json").read_text(
            encoding="utf-8"))
        self.assertEqual(report["compliant"], result.compliant)
        audit_json = json.loads(Path(dir, "audit.json").read_text(
            encoding="utf-8"))
        self.assertGreater(len(audit_json), 80,
                           "the unified audit is substantial")

        # D-44: ruled code paths name the decision that governs them, in the
        # persisted audit and in the human-readable narrative. D-14
        # (reference air systems inherit the proposed operating schedule)
        # fires on every run that builds a reference air system.
        rulings = [e["ruling"] for e in audit_json if e.get("ruling")]
        self.assertTrue(rulings, "ruling tags reach audit.json")
        fired = {id for r in rulings for id in Decisions.ids_in(r)}
        self.assertIn("D-14", fired,
                      "D-14 (operating-schedule inheritance) fired")
        for id in fired:
            self.assertIsNotNone(Decisions.lookup(id),
                                 f"audited ruling {id} resolves")
        self.assertRegex(Path(dir, "audit.txt").read_text(encoding="utf-8"),
                         r"\| ruling D-\d{2}",
                         "audit.txt narrative carries the ruling segment")

    def test_hp_proposed_runs_the_2g_election_machinery(self):
        # D-52: an HP proposed drives the 8.4.4.13.(2)(g) machinery end to
        # end — the proposed annual runs BEFORE the reference build, the
        # per-equipment heating energy is extracted from its SQL, and the
        # election (or its audited fallback) decides the reference hp
        # variant's aux fuel.
        dir = tempfile.mkdtemp(prefix="osnecb-hp-election-")
        result = performance_compliance(
            proposed_with_hvac(
                "PSZ RTU ASHP with Gas and ASHP with Gas Supp. Heat Coils "
                "and Electric Baseboard"),
            vintage="2020", simulate="annual", weather=weather(),
            building=building_for(load_raw_fixture()), run_dir=dir,
            run_period=week())

        extraction = next(
            (e for e in result.audit.entries
             if "per-equipment heating energy extracted" in e["action"]), None)
        self.assertIsNotNone(extraction,
                             "the election data was extracted from the "
                             "proposed annual SQL")
        self.assertGreaterEqual(extraction["inputs"]["heat_pump_gj"], 0.0)
        self.assertGreaterEqual(extraction["inputs"]["air_loops"], 1,
                                "the ASHP loop was inventoried")

        election = [e for e in result.audit.entries
                    if "8.4.4.13.(2)(g)" in str(e.get("article") or "")]
        self.assertTrue(election,
                        "a (2)(g) determination fired — elected or fallback")
        self.assertTrue(all("D-52" in str(e.get("ruling") or "")
                            for e in election))
        # Whatever path elected, the reference hp system was actually built
        # with a concrete variant (the fixture ASHP redirects per Table
        # 8.4.4.13).
        self.assertTrue(any("air-source heat pump (Table 8.4.4.13)"
                            in e["action"] for e in result.audit.entries))
        self.assertTrue(result.report["proposed"]["clean_run"],
                        "proposed ran clean with the requested variables")
        self.assertTrue(result.report["reference"]["clean_run"])

    def test_capacity_iteration_converges_undersized_building(self):
        # 8.4.1.2.(5): a deliberately UNDERSIZED proposed building (global
        # heating sizing factor 0.25 — the reference inherits it through the
        # min(proposed, 1.3) oversizing rule, so BOTH buildings fail sentence
        # (3) initially) must converge through audited capacity increases
        # over a 4-week Toronto January run.
        dir = tempfile.mkdtemp(prefix="osnecb-iter-")
        proposed = proposed_with_hvac()
        proposed.getSizingParameters().setHeatingSizingFactor(0.25)

        result = performance_compliance(
            proposed, vintage="2020", simulate="annual", weather=weather(),
            building=building_for(proposed), run_dir=dir,
            max_capacity_iterations=3, capacity_step=3.0,
            run_period=week(end_day=28))

        history = result.report["capacity_iterations"]
        self.assertTrue(history,
                        "the undersized building required capacity increases")
        self.assertFalse(any(h.get("stalled") for h in history),
                         "autosized equipment responds to sizing factors")
        first = history[0]
        self.assertIn("proposed", first["bumped"],
                      "proposed heating capacity was increased")
        self.assertGreater(first["bumped"]["proposed"]["heating_sizing_factor"],
                           0.25)
        self.assertEqual("zonal", first["bumped"]["proposed"]["mode"],
                         "per-zone unmet hours attributed the failure to "
                         "specific thermal blocks")
        self.assertTrue(first["bumped"]["proposed"]["zones"],
                        "the failing zones are named in the history")
        self.assertTrue(
            any(z.sizingZone().zoneHeatingSizingFactor().is_initialized()
                for z in result.proposed_model.getThermalZones()),
            "Sizing:Zone heating factors set on the failing zones")

        final = result.report["proposed"]["unmet_occupied_hours"]["heating"]
        self.assertLessEqual(final, 100.0,
                             f"converged: {final} unmet heating hours")
        ref_final = result.report["reference"]["unmet_occupied_hours"]["heating"]
        self.assertLessEqual(ref_final, 100.0, "reference converged too")

        bump_decisions = [e for e in result.audit.entries
                          if e.get("article") == "8.4.1.2.(5)"
                          and e["level"] == "decision"]
        self.assertTrue(bump_decisions,
                        "every capacity increase is an audited decision")
        self.assertTrue(any("converged" in e["action"]
                            for e in result.audit.entries))
        self.assertTrue(os.path.isdir(os.path.join(dir,
                                                   "proposed_annual_iter1")),
                        "iteration run evidence kept")

    def test_bare_geometry_on_ramp(self):
        # The bare-geometry on-ramp: strip the fixture of loads AND HVAC,
        # hand the pipeline only geometry + a space-type map, and get a full
        # compliance run.
        bare = load_raw_fixture()
        for objs in (bare.getThermostatSetpointDualSetpoints(),
                     bare.getPeoples(), bare.getPeopleDefinitions(),
                     bare.getLightss(), bare.getLightsDefinitions(),
                     bare.getElectricEquipments(),
                     bare.getElectricEquipmentDefinitions(),
                     bare.getSpaceTypes()):
            for obj in list(objs):
                obj.remove()

        map_ = {s.nameString(): ["Space Function", "Office enclosed > 25 m2"]
                for s in bare.getSpaces()}
        dir = tempfile.mkdtemp(prefix="osnecb-onramp-")
        result = performance_compliance(
            bare, vintage="2020", simulate="sizing", weather=weather(),
            building=building_for(bare),
            necb_loads={"space_type_map": map_, "shw_fuel": "NaturalGas",
                        "hvac_system": "Baseboard gas boiler"},
            run_dir=dir)

        self.assertTrue(list(result.proposed_model.getPeoples()),
                        "loads applied")
        self.assertTrue(list(result.proposed_model.getLightss()),
                        "lighting applied")
        self.assertTrue(list(result.proposed_model.getWaterUseEquipments()),
                        "SHW applied")
        self.assertTrue(list(result.proposed_model.getPlantLoops()),
                        "HVAC built")
        steps = {e["step"] for e in result.audit.entries}
        for s in ("loads", "lighting", "shw", "selection"):
            self.assertIn(s, steps, "on-ramp steps in ONE audit")
        wall = next(s for s in result.reference_model.getSurfaces()
                    if s.outsideBoundaryCondition() == "Outdoors"
                    and s.surfaceType() == "Wall")
        self.assertIn("Lightweight", wall.construction().get().nameString(),
                      "reference generated from the on-ramped proposed")


if __name__ == "__main__":
    unittest.main()
