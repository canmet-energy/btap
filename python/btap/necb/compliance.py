"""The NECB Part 8 performance path (port of btap-necb's compliance.rb;
Division B, 8.4.1.2, identical intent in 2020 and 2025):

  (2) annual energy consumption of the PROPOSED building shall not exceed the
      building energy target of the REFERENCE building
  (3) unmet heating hours <= 100 h/year for both buildings
  (4) unmet cooling hours: proposed within +10% of reference (2025 8.4.4
      path: proposed <= 100 h; 8.4.5 path: within +10% or 20 h, whichever is
      greater)
  (5) where (3)/(4) fail, capacities of the primary and secondary systems
      shall be incrementally increased until the loads are met — implemented
      per THERMAL BLOCK (the resolution sentences (3)/(4) are written at):
      each failing zone's Sizing:Zone factors are raised, secant-targeted
      from that zone's own (factor, unmet-hours) history, with a global
      SizingParameters fallback when per-zone data cannot attribute the
      failure; bounded by max_capacity_iterations; a still-failing result
      after the cap is a loud warning + non-compliance.

One clone, one audit: reference_hvac, reference_envelope (envelope),
reference_lighting (lighting — Part 4 allowance LPDs) and reference_shw
(shw — Part 6 minimum efficiencies) transform a single reference model, and
optional costing of both models lands in the same AuditLog."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from btap._compat import opt, ruby_div, ruby_round, ruby_str
from btap.audit import AuditLog, emit_coverage
from btap.necb import eui_archetypes as archetypes
from btap.necb import tiers
from btap.simulation import runner

DATA_DIR = Path(__file__).parent / "data"


class PreflightError(ValueError):
    """Raised when the INPUT MODEL is rejected before any simulation runs:
    space types that do not resolve against the NECB catalog, an
    undeterminable above-ground storey count, no thermostats, no geometry.
    Distinct from every other ValueError the pipeline raises (bad weather
    paths, unresolvable HDD) because the fix is different — the caller must
    repair the MODEL, not the call. Subclasses ValueError (Ruby: a subclass
    of ArgumentError) so existing handlers keep working unchanged."""


@dataclass
class ComplianceResult:
    proposed_model: object = None
    reference_model: object = None
    report: dict = None
    audit: object = None
    compliant: bool | None = None
    run_dir: str = None


@dataclass
class _Run:
    """One performance-path run's context: the option dict plus the mutable
    state the eleven pipeline phases hand each other (internal — phases read
    run.opts and write the five stateful slots)."""
    opts: dict = None
    proposed: object = None
    reference: object = None
    report: dict = None
    audit: object = None
    hdd: object = None
    proposed_annual_data: dict = None
    compliant: bool | None = None


HEATING_UNMET_LIMIT_H = 100.0    # 8.4.1.2.(3)
SECANT_TARGET_FRACTION = 0.9     # aim below the limit so noise can't strand the last hour
SECANT_MAX_STEP = 2.0            # per-round growth cap (never below the configured `step`)
SECANT_MIN_IMPROVEMENT_H = 1.0   # observations closer than this can't support a slope

_COOLING_PATTERN = re.compile(
    r"Coil_Cooling|CoilSystem_Cooling|Chiller|EvaporativeCooler|DistrictCooling|"
    r"IdealLoadsAirSystem")


def performance_compliance(model, *, vintage="2020", weather=None, building=None,
                           hdd=None, run_dir, simulate="annual", run_period=None,
                           costing=False, city=None, province_state=None,
                           costs_csv=None, thermal_bridging=None,
                           actual_roof_absorptance_used=False,
                           max_capacity_iterations=3, capacity_step=1.25,
                           necb_loads=None, reference_daylighting=True,
                           path="reference", archetypes_map=None,
                           process_loads_kwh=0.0, eui_supplement=None,
                           report_html=False, report_options=None, audit=None):
    """Run the NECB Part 8 performance path (or, with path='eui', the NECB
    2025 8.4.4 archetype-EUI path — no reference building).

    :param model: openstudio.model.Model or a .osm path (the proposed building)
    :param vintage: '2020' or '2025'
    :param weather: {'epw':, 'ddy':, 'stat':} — epw+ddy required unless
        simulate='none'
    :param building: facts for reference-system selection ({'storeys':,
        'zone_types':, 'winter_design_temp_c':, ...})
    :param hdd: heating degree-days; None resolves via the envelope domain
        (explicit > Table C-1 nearest city > .stat)
    :param run_dir: working directory (simulations, report.json, audit.json)
    :param simulate: 'annual' = full compliance determination; 'sizing' =
        generate + size both models, no energy comparison; 'none' = model
        transforms only (loud warning: selection kW thresholds stay unresolved)
    :param run_period: shortened weather run for TESTS — a non-annual period
        cannot determine code compliance and is flagged in the report
    :param costing: cost BOTH models (HVAC + envelope via btap.costing)
    :param necb_loads: bare-geometry on-ramp — {'space_type_map': {space name:
        [building_type, space_type]} (required), 'lights_type':, 'shw_fuel':,
        'hvac_system':}
    :param path: 'reference' = the 8.4.4 (2025: 8.4.5) reference-building
        comparison; 'eui' = the NECB 2025 8.4.4 archetype-EUI target
    :param archetypes_map: 'eui' path only — {archetype: 'all' | [space names]}
    :param eui_supplement: 2025 reference-path runs only — {'archetypes':
        (required), 'run_normalized': bool, 'process_loads_kwh': float}
    :param report_html: write run_dir/compliance_report.html
    :return: ComplianceResult; .compliant is None unless simulate='annual'
        with a full-year run period"""
    weather = weather or {}
    report_options = report_options or {}
    simulate = str(simulate)
    if str(path) == "eui":
        if str(vintage) != "2025":
            raise ValueError(
                "the archetype-EUI path is a NECB 2025 feature (vintage: 2025)")
        if archetypes_map is None:
            raise ValueError(
                "the 'eui' path requires archetypes_map={archetype: 'all' | "
                "[space names]}")

        return _eui_compliance(model, vintage=vintage, weather=weather, hdd=hdd,
                               run_dir=run_dir, simulate=simulate,
                               run_period=run_period,
                               archetypes_map=archetypes_map,
                               process_loads_kwh=process_loads_kwh,
                               costing=costing, city=city,
                               province_state=province_state,
                               costs_csv=costs_csv, necb_loads=necb_loads,
                               report_html=report_html,
                               report_options=report_options, audit=audit)
    audit = audit if audit is not None else AuditLog()
    os.makedirs(run_dir, exist_ok=True)
    # The run context: options + the mutable state the phases hand each
    # other. `report` starts EMPTY and is rebound after the proposed sizing
    # (below) — a failure flush before that point deliberately writes the
    # empty dict (pinned by test_failed_run_still_writes_audit_trail).
    opts = {"model": model, "vintage": str(vintage), "weather": weather,
            "building": building, "run_dir": str(run_dir), "simulate": simulate,
            "run_period": run_period, "costing": costing, "city": city,
            "province_state": province_state, "costs_csv": costs_csv,
            "thermal_bridging": thermal_bridging,
            "actual_roof_absorptance_used": actual_roof_absorptance_used,
            "max_capacity_iterations": max_capacity_iterations,
            "capacity_step": capacity_step, "necb_loads": necb_loads,
            "reference_daylighting": reference_daylighting,
            "eui_supplement": eui_supplement, "report_html": report_html,
            "report_options": report_options}
    run = _Run(opts=opts, report={}, audit=audit, hdd=hdd)
    try:
        _load_and_validate(run)        # 1. input model in, gates passed
        _attach_weather_and_hdd(run)   # 2. weather + heating degree-days
        _size_proposed(run)            # 3. proposed sizing run
        run.report = _base_report(run)  # (the report rebinding — see above)
        _run_proposed_annual(run)      # 4. proposed annual (D-52: BEFORE the reference)
        _build_reference(run)          # 5. reference transforms on one clone
        _size_reference(run)           # 6. reference sizing + post-sizing passes
        _compare_and_iterate(run)      # 7. 8.4.1.2.(2)-(4) verdicts + sentence-(5) loop
        _score_ghg(run)                # 8. 2025 Part 11 GHG (needs province_state)
        _cost_both(run)                # 9. optional costing of both models
        _supplement_eui(run)           # 10. optional 2025 archetype-EUI verdict
        return _finalize(run)          # 11. coverage + outputs -> ComplianceResult
    except Exception as e:
        _flush_on_failure(str(run_dir), run.report, audit, e)
        raise


# 1. load + validate the input model (on-ramp for bare geometry, then the
#    simulate-ability gates and the NECB space-type pre-flight)
def _load_and_validate(run):
    opts = run.opts
    audit = run.audit
    vintage = opts["vintage"]
    with audit.with_building("input model"):
        proposed = _load_model(opts["model"], audit=audit)
        if opts["necb_loads"]:
            _apply_necb_loads(proposed, vintage, opts["necb_loads"], audit)
        # After the on-ramp (it may have added thermostats to bare geometry):
        # the input must be a simulate-able building before any transform.
        _validate_input_model(proposed, audit, building=opts["building"])
        # PRE-FLIGHT: every floor-area space type must resolve against the
        # NECB catalog BEFORE any transform runs. The reference is a clone of
        # the proposed, and the per-space-type transforms (lighting LPD,
        # loads, SHW demand) silently skip unmatched types — so an
        # unresolvable space type yields a reference identical to the
        # proposed for exactly that space: the allowance is waived and the
        # proposed is compared against itself. You cannot certify a building
        # whose reference silently failed to build; fail here, loudly, with
        # the full list (the raise lands inside the pipeline except, so the
        # audit trail is still flushed to run_dir).
        _validate_space_types(proposed, vintage, audit)
    audit.decision("compliance", "performance-path run started",
                   inputs={"vintage": vintage, "simulate": opts["simulate"],
                           "costing": opts["costing"]},
                   article="8.4.1.2.(1)")
    run.proposed = proposed


# 2. attach weather, resolve heating degree-days
def _attach_weather_and_hdd(run):
    from btap.necb import envelope

    opts = run.opts
    audit = run.audit
    weather = opts["weather"]
    audit.building = "proposed building"
    if opts["simulate"] != "none":
        for key in ("epw", "ddy"):
            if not weather.get(key):
                raise ValueError(
                    f"weather['{key}'] is required when simulate: "
                    f"{opts['simulate']}")
        runner.attach_weather(run.proposed, epw=weather["epw"],
                              ddy=weather["ddy"])

    # HDD for the envelope rules (explicit > Table C-1 from the EPW site >
    # .stat)
    if run.hdd is None:
        run.hdd = envelope.hdd18(run.proposed, audit=audit)
    if run.hdd is None:
        raise ValueError(
            "HDD unresolvable: pass hdd= or weather with a recognized site")


# 3. size the PROPOSED building (selection thresholds + efficiencies + costing
#    all need capacities; the domain packages never simulate)
def _size_proposed(run):
    opts = run.opts
    audit = run.audit
    if opts["simulate"] == "none":
        audit.warn("compliance",
                   "proposed is UNSIZED (simulate: :none) — data-centre kW "
                   "thresholds and capacity-binned efficiencies fall back with "
                   "warnings; the 5.2.10.1 energy-recovery determination needs "
                   "sized flows and is SKIPPED")
        return

    try:
        runner.run_energyplus(run.proposed,
                              os.path.join(opts["run_dir"], "proposed_sizing"),
                              sizing_only=True)
    except RuntimeError as e:
        # An E+ failure BEFORE any transform is the INPUT model's fault —
        # frame it that way (SHOUTED, flushed with the audit) instead of
        # letting it read as a pipeline failure.
        audit.warn("compliance",
                   "THE PROPOSED (INPUT) MODEL FAILED ITS SIZING SIMULATION — "
                   "the input file is not simulate-able as given; the "
                   "EnergyPlus severes below are defects in the input model, "
                   "not in the compliance pipeline", target="proposed")
        raise RuntimeError(
            "the PROPOSED (input) model failed its sizing simulation — the "
            f"input file is not simulate-able as given. {e}") from e
    audit.info("compliance", "proposed sizing run complete", target="proposed")


def _base_report(run):
    """The determination report skeleton (rebound over the pre-flight {} once
    the proposed is sized — the flush-before-this-point contract above)."""
    return {"vintage": run.opts["vintage"], "hdd": run.hdd,
            "simulate": run.opts["simulate"], "proposed": {}, "reference": {}}


# 4. the proposed ANNUAL run — BEFORE the reference build (D-52). The
# proposed annual depends on nothing downstream (the reference is a clone;
# every later use of the proposed is read-only), so running it here costs
# zero extra simulations and hands the reference builder the annual data the
# 8.4.4.13.(2)(g) auxiliary-fuel election needs. When the proposed carries a
# heat pump, its per-equipment heating energy is requested first and joined
# with the SDK inventory after the run.
def _run_proposed_annual(run):
    from btap.modeling.hvac import classify

    opts = run.opts
    audit = run.audit
    proposed = run.proposed
    if opts["simulate"] != "annual":
        return

    run.report["proposed"]["mechanical_cooling"] = _mechanical_cooling(proposed)
    inventory = classify.heating_election_inventory(proposed)
    hp_present = (any(e["hp"] for e in inventory["loops"].values())
                  or any(any(e["role"] == "hp" for e in entries)
                         for entries in inventory["zones"].values()))
    if hp_present:
        runner.request_run_period_variables(
            proposed,
            ["Heating Coil Heating Energy", "Baseboard Total Heating Energy"])
    _run_annual(proposed, os.path.join(opts["run_dir"], "proposed_annual"),
                opts["run_period"], run.report["proposed"], audit=audit)
    if hp_present:
        run.proposed_annual_data = _heating_election_data(proposed, inventory,
                                                          audit)


# 5. reference building: HVAC, envelope, lighting (+ photocontrols) and SHW
#    transforms on ONE clone, same audit
def _build_reference(run):
    from btap.necb import envelope, hvac, lighting, shw

    opts = run.opts
    audit = run.audit
    proposed = run.proposed
    vintage = opts["vintage"]
    lighting_prefix = "8.4.5" if vintage == "2025" else "8.4.4"
    with audit.with_building("reference building"):
        reference_result = hvac.reference_hvac(
            proposed, vintage=vintage, building=opts["building"], audit=audit,
            proposed_annual=run.proposed_annual_data)
        reference = reference_result.model
        envelope.reference_envelope(
            reference, vintage=vintage, hdd=run.hdd,
            actual_roof_absorptance_used=opts["actual_roof_absorptance_used"],
            thermal_bridging=opts["thermal_bridging"], audit=audit)
        # daylighting: tells reference_lighting whether (5)-(12) are covered
        # by the separate daylighting transform below — it shouts the gap only
        # when they are not.
        lighting.reference_lighting(reference, vintage=vintage,
                                    daylighting=opts["reference_daylighting"],
                                    audit=audit)
        if opts["reference_daylighting"]:
            audit.decision(
                "compliance",
                "reference photocontrols BUILT by default: 4.2.2 requires "
                "photocontrols, and "
                f"{lighting_prefix}.5.(9)-(12) requires their effect to be "
                "evaluated in the reference — a reference generated without "
                "them is non-conformant, so correctness outranks the "
                "detailed-daylighting runtime cost (pass "
                "reference_daylighting: false to opt out)",
                article=f"{lighting_prefix}.5.(9)-(12)", ruling="D-51")
            lighting.reference_daylighting(reference, vintage=vintage,
                                           proposed=proposed, audit=audit)
        else:
            audit.warn(
                "compliance",
                "reference photocontrols SUPPRESSED by the caller "
                "(reference_daylighting: false): "
                f"{lighting_prefix}.5.(9)-(12) photocontrol effect is NOT "
                "evaluated in this reference, so the target it sets is more "
                "lenient than the code requires",
                article=f"{lighting_prefix}.5.(9)-(12)", ruling="D-51")
        shw.reference_shw(reference, vintage=vintage, audit=audit)
    audit.building = None
    audit.info(
        "compliance",
        "8.4.3.2 operating schedules and occupancy/receptacle loads are "
        "identical between proposed and reference by construction (the "
        "reference is a clone; neither reset touches schedules or those "
        "loads); interior lighting power is reset to the Part 4 allowance per "
        "8.4.4.5.(1) (reference_lighting); service water heating efficiencies "
        "are reset to the Part 6 minimums per 8.4.4.20 (reference_shw). "
        "Representativeness of the loads for the building type remains the "
        "modeller's input (see the loads domain for NECB space-use data).",
        article="8.4.3.2.(1)-(2)")
    run.reference = reference


# 6. size the reference, then re-apply efficiencies on sized equipment (the
#    hvac-domain contract: efficiency rows are capacity-binned), plus the
#    post-sizing determinations (5.2.10.1 ERV, 5.2.2.7 economizers)
def _size_reference(run):
    from btap.necb import hvac

    opts = run.opts
    audit = run.audit
    vintage = opts["vintage"]
    reference = run.reference
    if opts["simulate"] == "none":
        return

    with audit.with_building("reference building"):
        # Loops COPIED from the proposed (the Table -A residential identity,
        # D-58) arrive with the legacy's hard-set pump power; the reference
        # sizing run re-derives flow against the frozen power/head and
        # EnergyPlus FATALS on 'Calculated Pump Efficiency > 100%' (found by
        # the SmallHotel gas variant). Release to autosize first — a no-op on
        # clean references, and the 8.4.4.14 transfer below re-establishes the
        # proposed-equivalent W/(L/s) on the sized flows (D-27 machinery).
        hvac.prepare_for_resizing(reference, audit=audit)
        runner.run_energyplus(reference,
                              os.path.join(opts["run_dir"], "reference_sizing"),
                              sizing_only=True)
        # proposed: enables the 8.4.4.14.(1)-(3) pump power transfer (the
        # proposed was sized in step 1, so its pump flows/powers are readable)
        hvac.apply_efficiencies(reference, vintage=vintage, audit=audit,
                                proposed=run.proposed)
        # 5.2.10.1 energy recovery is a POST-SIZING determination (Table
        # 5.2.10.1.-A/-B thresholds need the sized supply/OA flows).
        hvac.apply_energy_recovery(reference, vintage=vintage, hdd=run.hdd,
                                   audit=audit)
        # T3: 5.2.2.7 economizer trigger is likewise a post-sizing determination
        hvac.apply_economizer_thresholds(reference, audit=audit)
        audit.info("compliance",
                   "reference sized; efficiencies re-applied and the 5.2.10.1 "
                   "energy-recovery determination evaluated on sized flows",
                   target="reference")


# 7. the reference ANNUAL run, then the energy comparison (8.4.1.2.(2)-(4))
#    with the sentence-(5) capacity iteration loop. The PROPOSED annual
#    already ran in step 4 (D-52); only the reference's annual is new here.
def _compare_and_iterate(run):
    opts = run.opts
    audit = run.audit
    vintage = opts["vintage"]
    run.compliant = None
    if opts["simulate"] == "annual":
        # Stamp the reference's first annual — step 4 sits outside the earlier
        # with_building blocks and its run entry was landing unattributed.
        with audit.with_building("reference building"):
            _run_annual(run.reference,
                        os.path.join(opts["run_dir"], "reference_annual"),
                        opts["run_period"], run.report["reference"], audit=audit)
        _iterate_capacities(run.proposed, run.reference, run.report,
                            vintage=vintage, run_dir=opts["run_dir"],
                            run_period=opts["run_period"],
                            max_iterations=opts["max_capacity_iterations"],
                            step=opts["capacity_step"], audit=audit)
        run.compliant = _evaluate(run.report, vintage, opts["run_period"], audit)
    elif opts["simulate"] == "sizing":
        audit.info("compliance",
                   "simulate: :sizing — both models generated and sized; no "
                   "energy comparison performed (compliance undetermined)")


# 8. NECB 2025 Part 11: operational GHG performance level (needs a province)
def _score_ghg(run):
    opts = run.opts
    report = run.report
    if not (opts["vintage"] == "2025" and opts["simulate"] == "annual"
            and opts["province_state"]):
        return

    proposed_ghg = tiers.operational_ghg_kg(report["proposed"],
                                            opts["province_state"])
    reference_ghg = tiers.operational_ghg_kg(report["reference"],
                                             opts["province_state"])
    if not (proposed_ghg is not None and reference_ghg is not None
            and reference_ghg > 0):
        return

    report["proposed"]["ghg_kg_co2e"] = proposed_ghg
    report["reference"]["ghg_kg_co2e"] = reference_ghg
    report["ghg"] = tiers.ghg_level(proposed_ghg, reference_ghg, audit=run.audit)


# 9. optional: unified costing of BOTH models (same audit)
def _cost_both(run):
    opts = run.opts
    if not opts["costing"]:
        return

    _cost_models(run.proposed, run.reference, run.report, city=opts["city"],
                 province_state=opts["province_state"],
                 costs_csv=opts["costs_csv"], audit=run.audit)


# 10. optional (2025): the 8.4.4 archetype-EUI verdict alongside the
# reference-path run. The two paths simulate DIFFERENT proposed buildings —
# as-specified (8.4.3.2) vs normalized to Table 8.4.4.2 (8.4.4.2.(1)) — so
# the reference-path annual result serves the EUI verdict ONLY when the
# proposed already conforms to the Table. When it does not: report
# not-computed with the mismatch list (default — never silently double the
# simulation cost), or, with run_normalized: true, clone-normalize-rerun and
# compute the verdict from that run.
def _supplement_eui(run):
    opts = run.opts
    if not (opts["eui_supplement"] and opts["vintage"] == "2025"
            and run.report["proposed"].get("total_site_kwh") is not None):
        return

    run.report["eui_path"] = eui_supplement_verdict(
        run.proposed, opts["eui_supplement"], run.hdd, run.report,
        opts["run_dir"], opts["run_period"], opts["vintage"], run.audit)


# 11. emit article coverage; write report.json / audit.json / audit.txt
#     (+ the optional HTML compliance report). Shared by both compliance
#     paths (the EUI path has no reference model).
def _finalize(run):
    from btap.necb import report as report_renderer

    opts = run.opts
    report = run.report
    audit = run.audit
    _emit_article_coverage(opts["vintage"], audit)
    report["compliant"] = run.compliant
    report["warnings"] = [w["action"] for w in audit.warnings]
    _write_outputs(opts["run_dir"], report, audit)
    result = ComplianceResult(proposed_model=run.proposed,
                              reference_model=run.reference, report=report,
                              audit=audit, compliant=run.compliant,
                              run_dir=opts["run_dir"])
    if opts["report_html"]:
        report_renderer.write_html(
            result, os.path.join(opts["run_dir"], "compliance_report.html"),
            opts["report_options"])
    return result


def _load_model(model, audit=None):
    import openstudio

    if isinstance(model, (str, Path)):
        path = str(model)
        if not os.path.exists(path):
            raise ValueError(f"input model file not found: {path}")

        # VersionTranslator, not Model.load: an OSM saved by an older
        # OpenStudio must be translated forward, and a corrupt file must fail
        # with the file named — not with an empty-optional crash.
        translator = openstudio.osversion.VersionTranslator()
        loaded = opt(translator.loadModel(openstudio.path(path)))
        if loaded is None:
            issues = "; ".join(m.logMessage()
                               for m in list(translator.errors())[:3])
            raise ValueError(
                f"input model could not be loaded: {path}"
                + (f" — {issues}" if issues else ""))
        original = translator.originalVersion().str()
        current = loaded.version().str()
        if original != current and audit is not None:
            # A version translation IS a model change — the ledger records it.
            # The working copy is upgraded; the file on disk is never
            # rewritten.
            audit.info("compliance",
                       f"input file version-translated from OpenStudio "
                       f"{original} to {current} (in-memory working copy only "
                       "— the original file is not modified)",
                       inputs={"from": original, "to": current,
                               "file": os.path.basename(path)})
        return loaded

    # never mutate the caller's model — the pipeline sizes/simulates its own
    # copy
    clone = model.clone(True)
    return clone.to_Model() if hasattr(clone, "to_Model") else clone


def _validate_input_model(proposed, audit, building=None, require_storeys=True):
    """Input-validity gate: the file must describe a SIMULATE-ABLE building
    before any transform runs. Structural absences (no spaces / zones /
    surfaces, or no thermostat anywhere) raise — a thermostat-less model is
    the dangerous case, because it RUNS: every zone free-floats, equipment
    sizes to nothing, and the determination is numerically valid and
    physically meaningless. Partial thermostat coverage only warns (storage
    and plenum zones legitimately float)."""
    counts = {"spaces": len(proposed.getSpaces()),
              "thermal_zones": len(proposed.getThermalZones()),
              "surfaces": len(proposed.getSurfaces())}
    empty = [k for k, v in counts.items() if v == 0]
    if empty:
        raise PreflightError(
            f"input model is not simulate-able: it has no {', '.join(empty)}")

    # COMPLIANCE inputs the model must carry: the above-ground storey count
    # drives the Table 8.4.4.7.-A System 3-vs-6 splits, and the downstream
    # derivation silently CLAMPS an undeterminable count to 1 storey — a tower
    # would select System 3 everywhere. Determinable means: declared on the
    # Building object, derivable from BuildingStorys with above-grade spaces,
    # or supplied via building={'storeys':}.
    declared = proposed.getBuilding().standardsNumberOfAboveGroundStories()
    derivable = any(
        any(float(s.zOrigin()) >= -0.01 for s in st.spaces())
        for st in proposed.getBuildingStorys())
    overridden = bool(building) and "storeys" in building
    if require_storeys and not (declared.is_initialized() or derivable
                                or overridden):
        raise PreflightError(
            "input model cannot determine its ABOVE-GROUND STOREY COUNT — no "
            "Building.standardsNumberOfAboveGroundStories, no BuildingStory "
            "objects with above-grade spaces, and no building={'storeys':} "
            "override. Table 8.4.4.7.-A reference-system selection depends on "
            "it (System 3 vs 6), and the fallback would silently treat the "
            "building as ONE storey. Declare it in the model or pass the "
            "override")
    if overridden:
        counts["storeys_source"] = "building: override"
    elif declared.is_initialized():
        counts["storeys_source"] = "declared on Building"
    elif derivable:
        counts["storeys_source"] = "derived from BuildingStorys"
    else:
        counts["storeys_source"] = "not required (EUI path)"

    with_stat = sum(
        1 for z in proposed.getThermalZones()
        if z.thermostatSetpointDualSetpoint().is_initialized())
    if with_stat == 0:
        raise PreflightError(
            "input model is not simulate-able as a building: NO thermal zone "
            "carries a thermostat — every zone would free-float and the "
            "8.4.1.2 determination would be meaningless (attach thermostats, "
            "or use the necb_loads on-ramp)")
    if with_stat < counts["thermal_zones"]:
        audit.warn("compliance",
                   f"{counts['thermal_zones'] - with_stat} of "
                   f"{counts['thermal_zones']} thermal zones carry NO "
                   "thermostat and will free-float — legitimate for "
                   "storage/plenum zones; verify none of them is meant to be "
                   "conditioned")
    audit.info("compliance",
               "input model loaded and structurally simulate-able",
               inputs={**counts, "zones_with_thermostats": with_stat,
                       "openstudio_version": proposed.version().str()})


def _eui_compliance(model, *, vintage, weather, hdd, run_dir, simulate,
                    run_period, archetypes_map, process_loads_kwh, costing,
                    city, province_state, costs_csv, necb_loads,
                    report_html=False, report_options=None, audit=None):
    """The NECB 2025 8.4.4 archetype-EUI path: the building energy target
    comes from Table 8.4.4.1 (BET = sum(A_i x EUI_i) + PL) — NO reference
    building is generated or simulated. The proposed is CHECKED against the
    Table 8.4.4.2 standardized operating inputs and, when it does not already
    conform, NORMALIZED to them before the annual run (8.4.4.2.(1)): the EUI
    targets were derived assuming those inputs, so an as-modeled comparison
    would be apples-to-oranges. Compliance: proposed annual consumption <=
    BET; the Section 10 tier is computed against the same BET."""
    from btap.necb import envelope

    audit = audit if audit is not None else AuditLog()
    report_options = report_options or {}
    os.makedirs(run_dir, exist_ok=True)
    report = {}
    try:
        with audit.with_building("input model"):
            proposed = _load_model(model, audit=audit)
            if necb_loads:
                _apply_necb_loads(proposed, vintage, necb_loads, audit)
            _validate_input_model(proposed, audit, building=None,
                                  require_storeys=False)
        audit.decision("compliance",
                       "ARCHETYPE-EUI compliance path (NECB 2025 8.4.4) — no "
                       "reference building",
                       inputs={"vintage": vintage,
                               "archetypes": list(archetypes_map.keys())},
                       article="8.4.4.1.")

        audit.building = "proposed building"
        if simulate != "none":
            for k in ("epw", "ddy"):
                if not weather.get(k):
                    raise ValueError(f"weather['{k}'] required")
            runner.attach_weather(proposed, epw=weather["epw"],
                                  ddy=weather["ddy"])
        if hdd is None:
            hdd = envelope.hdd18(proposed, audit=audit)

        # Mapping -> model-derived areas -> HARD applicability (refuse outside
        # 8.4.4.1.(1)/HDD bounds: a verdict outside applicability is not a
        # determination) -> Table 8.4.4.2 conformance -> normalize if needed.
        resolved = archetypes.resolve(proposed, archetypes_map, audit=audit)
        archetypes.verify_applicability(resolved, hdd=hdd, audit=audit)
        check = archetypes.conformance(proposed, resolved, vintage=vintage,
                                       audit=audit)
        if not check["conformant"]:
            archetypes.normalize(proposed, resolved, vintage=vintage,
                                 audit=audit)
        audit.building = None  # BET derivation + verdicts are comparisons,
        # not model work

        report = {"vintage": vintage, "hdd": hdd, "simulate": simulate,
                  "path": "eui", "proposed": {}, "reference": {},
                  "eui": {"conformant_to_8_4_4_2": check["conformant"],
                          "normalized": not check["conformant"],
                          "mismatches": check["mismatches"][:50]}}
        target = tiers.eui_building_energy_target(
            archetypes.bet_areas(resolved, audit=audit),
            resolved["total_area_m2"], hdd=hdd,
            process_loads_kwh=process_loads_kwh, audit=audit)
        report["reference"] = {
            "method": "archetype EUI (Table 8.4.4.1)",
            "building_energy_target_kwh": target["bet_kwh"],
            "lines": target["lines"]}

        compliant = None
        if simulate == "annual":
            _run_annual(proposed, os.path.join(run_dir, "proposed_annual"),
                        run_period, report["proposed"], audit=audit)
            proposed_kwh = report["proposed"]["total_site_kwh"]
            compliant = proposed_kwh <= target["bet_kwh"]
            audit.decision(
                "compliance",
                "proposed does not exceed the archetype-EUI building energy "
                "target" if compliant
                else "proposed EXCEEDS the archetype-EUI building energy target",
                inputs={"proposed_kwh": proposed_kwh,
                        "bet_kwh": target["bet_kwh"]},
                article="8.4.4.1.(2)")
            report.update(tiers.energy_tier(proposed_kwh, target["bet_kwh"],
                                            audit=audit))
            if province_state:
                ghg = tiers.operational_ghg_kg(report["proposed"],
                                               province_state)
                if ghg is not None:
                    report["proposed"]["ghg_kg_co2e"] = ghg
            if run_period:
                audit.warn("compliance",
                           "run period is SHORTENED — not a code-compliant "
                           "annual determination")
                report["annual"] = False
            else:
                report["annual"] = True
        elif simulate == "sizing":
            runner.run_energyplus(proposed,
                                  os.path.join(run_dir, "proposed_sizing"),
                                  sizing_only=True)

        if costing:
            with audit.with_building("proposed building"):
                hvac_cost, envelope_cost = _cost_single_model(
                    proposed, city=city, province_state=province_state,
                    costs_csv=costs_csv, audit=audit)
                report["proposed"]["cost"] = {
                    "hvac": hvac_cost.total, "envelope": envelope_cost.total,
                    "total": ruby_round(hvac_cost.total + envelope_cost.total,
                                        2)}

        # shared epilogue (coverage + outputs + optional HTML) — no reference
        # model on this path.
        return _finalize(_Run(
            opts={"vintage": vintage, "run_dir": str(run_dir),
                  "report_html": report_html,
                  "report_options": report_options},
            proposed=proposed, reference=None, report=report, audit=audit,
            compliant=compliant))
    except Exception as e:
        _flush_on_failure(str(run_dir), report, audit, e)
        raise


def _apply_necb_loads(proposed, vintage, options, audit):
    """The bare-geometry on-ramp: NECB space types -> loads -> lighting ->
    SHW -> (optionally) an HVAC system, all on the proposed clone with the
    shared audit."""
    import btap.modeling as modeling
    from btap._compat import sorted_by_name
    from btap.necb import lighting, loads, shw

    map_ = options.get("space_type_map")
    if map_ is None:
        raise ValueError("necb_loads requires space_type_map: "
                         "{space name: [building_type, space_type]}")

    loads.assign_space_types(proposed, map_, vintage=vintage, audit=audit)
    loads.apply_loads(proposed, vintage=vintage, audit=audit)
    lighting.apply_lights(proposed, vintage=vintage,
                          lights_type=options.get("lights_type")
                          or "NECB_Default", audit=audit)
    shw_fuel = options.get("shw_fuel")
    if shw_fuel:
        shw.apply_shw(proposed, vintage=vintage, fuel=shw_fuel, audit=audit)
    hvac_system = options.get("hvac_system")
    if hvac_system:
        result = modeling.build_system(
            proposed, hvac_system, sorted_by_name(proposed.getThermalZones()))
        # build_system takes no audit — record the built topology here so the
        # on-ramp HVAC generation is visible in the narrative, not just an
        # input on the summary line.
        air_loops = (len(list(result.air_loops))
                     if hasattr(result, "air_loops") else None)
        inputs = {"air_loops": air_loops,
                  "plant_loops": len(proposed.getPlantLoops()),
                  "zones": len(proposed.getThermalZones())}
        audit.info("hvac",
                   f"proposed HVAC built from the catalog: '{hvac_system}'",
                   inputs={k: v for k, v in inputs.items() if v is not None})
    audit.decision(
        "compliance",
        "NECB space-use gems applied to the proposed (bare-geometry on-ramp)",
        inputs={"spaces_mapped": len(map_),
                "lights_type": options.get("lights_type") or "NECB_Default",
                "shw_fuel": shw_fuel or "none",
                "hvac_system": hvac_system or "model as given"},
        article="8.4.3.2.")


def _run_annual(model, dir, run_period, section, audit=None):
    run_dir = runner.run_energyplus(model, dir, sizing_only=False,
                                    run_period=run_period)
    section["clean_run"] = runner.is_clean_run(run_dir)
    section.update(runner.energy_results(model))
    section["unmet_occupied_hours"] = runner.unmet_occupied_hours(model)
    section["zone_unmet_occupied_hours"] = runner.zone_unmet_occupied_hours(model)
    section["run_dir"] = run_dir
    # The audit narrative must show every simulation, not just the reference
    # transforms — before this, the proposed annual left NO trace and a report
    # reader could not see it ran, over what period, or how it ended.
    if run_period:
        period = (f"{run_period['begin_month']}/{run_period['begin_day']}-"
                  f"{run_period['end_month']}/{run_period['end_day']} "
                  "(SHORTENED)")
    else:
        period = "full year"
    unmet = section.get("unmet_occupied_hours") or {}
    total = section.get("total_site_kwh")
    if audit is not None:
        audit.info(
            "compliance",
            "annual EnergyPlus run complete"
            + ("" if section["clean_run"] else " — NOT CLEAN (see eplusout.err)"),
            target=os.path.basename(str(dir)),
            inputs={"run_period": period, "clean_run": section["clean_run"],
                    "total_site_kwh": (ruby_round(total, 0)
                                       if total is not None else None),
                    "unmet_heating_h": unmet.get("heating"),
                    "unmet_cooling_h": unmet.get("cooling")})


def _heating_election_data(proposed, inventory, audit):
    """D-52: join the SDK heating-equipment inventory (names + fuels, from
    btap.modeling classify) with the proposed annual run's per-equipment
    delivered-heat sums — the data the 8.4.4.13.(2)(g) auxiliary-fuel
    election consumes inside reference_hvac. SQL keys are upper-cased."""
    from btap.modeling.hvac import classify

    coil = runner.run_period_sums(proposed, "Heating Coil Heating Energy")
    baseboard = runner.run_period_sums(proposed,
                                       "Baseboard Total Heating Energy")

    def lookup(name, variable):
        source = (baseboard if variable == classify.BASEBOARD_VARIABLE
                  else coil)
        return source.get(name.upper(), 0.0)

    loops = {
        loop_name: {
            "hp_j": sum(lookup(n, classify.COIL_VARIABLE)
                        for n in entry["hp"]),
            "aux": [{"fuel": a["fuel"],
                     "j": lookup(a["name"], classify.COIL_VARIABLE)}
                    for a in entry["aux"]],
        }
        for loop_name, entry in inventory["loops"].items()}
    zones = {
        zone_name: [{"fuel": e["fuel"],
                     "j": lookup(e["name"], e["variable"]),
                     "role": e["role"]} for e in entries]
        for zone_name, entries in inventory["zones"].items()}
    hp_gj = (sum(e["hp_j"] for e in loops.values())
             + sum(e["j"] for entries in zones.values() for e in entries
                   if e["role"] == "hp"))
    audit.info(
        "compliance",
        "proposed per-equipment heating energy extracted for the "
        "8.4.4.13.(2)(g) auxiliary-fuel election (delivered heat, weather run "
        "period only)",
        target="proposed",
        inputs={"air_loops": len(loops), "zones_with_heating": len(zones),
                "heat_pump_gj": ruby_round(hp_gj / 1e9, 2)},
        ruling="D-52")
    return {"loops": loops, "zones": zones}


def _evaluate(report, vintage, run_period, audit):
    """8.4.1.2 sentences (2)-(4). A shortened run period reports the same
    arithmetic but flags that it is NOT a code-compliant determination."""
    proposed_kwh = report["proposed"].get("total_site_kwh")
    reference_kwh = report["reference"].get("total_site_kwh")
    if proposed_kwh is None or reference_kwh is None:
        raise RuntimeError("annual runs missing energy results")

    energy_ok = proposed_kwh <= reference_kwh
    margin_pct = ruby_round(
        ruby_div(100.0 * (reference_kwh - proposed_kwh), reference_kwh), 1)
    audit.decision(
        "compliance",
        "proposed does not exceed the building energy target" if energy_ok
        else "proposed EXCEEDS the building energy target",
        inputs={"proposed_kwh": proposed_kwh,
                "reference_building_energy_target_kwh": reference_kwh},
        value=f"margin {ruby_str(ruby_round(reference_kwh - proposed_kwh, 1))} "
              f"kWh ({ruby_str(margin_pct)}%)",
        article="8.4.1.2.(2)")
    report.update(tiers.energy_tier(proposed_kwh, reference_kwh, audit=audit))

    unmet_ok = _evaluate_unmet(report, vintage, audit)

    if run_period:
        audit.warn("compliance",
                   "run period is SHORTENED — the energy comparison above is "
                   "not a code-compliant annual determination (8.4.1.2 "
                   "requires a simulated year)")
        report["annual"] = False
    else:
        report["annual"] = True
    return energy_ok and unmet_ok


def _evaluate_unmet(report, vintage, audit):
    status = _unmet_status(report, vintage)
    audit.decision(
        "compliance",
        "unmet heating hours within 100 h for both buildings"
        if status["heating_ok"] else "unmet heating hours EXCEED 100 h",
        inputs={"proposed_h": status["proposed_heating_h"],
                "reference_h": status["reference_heating_h"], "limit_h": 100},
        article="8.4.1.2.(3)")
    if status["cooling_vacuous"]:
        audit.decision(
            "compliance",
            "sentence (4) is vacuous — the proposed building has no "
            "mechanical cooling (the clause applies to thermal blocks \"for "
            "which mechanical cooling is provided\"; explicit in the 2025 "
            "wording, applied consistently for 2020)",
            inputs={"proposed_h": status["proposed_cooling_h"],
                    "reference_h": status["reference_cooling_h"]},
            article="8.4.1.2.(4)")
    else:
        audit.decision(
            "compliance",
            "unmet cooling hours within the allowance over reference"
            if status["cooling_ok"]
            else "unmet cooling hours EXCEED the allowance",
            inputs={"proposed_h": status["proposed_cooling_h"],
                    "reference_h": status["reference_cooling_h"],
                    "allowance_h": ruby_round(status["allowance"], 1)},
            article="8.4.1.2.(4)")

    if not status["all_ok"]:
        iterations = len(report.get("capacity_iterations") or [])
        audit.warn(
            "compliance",
            f"8.4.1.2.(5): unmet-hours limits still not met after "
            f"{iterations} capacity increase(s) — the building remains "
            "non-compliant; raise max_capacity_iterations, increase "
            "capacity_step, or fix the design (hard-sized equipment does not "
            "respond to sizing-factor increases).", article="8.4.1.2.(5)")
    return status["all_ok"]


def _unmet_status(report, vintage):
    """The (3)/(4) arithmetic without audit side effects — shared by the
    formal verdicts and the capacity-iteration loop.
    (4): 2020 wording is +10% of reference; 2025's 8.4.5 path allows +10% or
    20 h, whichever is greater."""
    def dig(section, key):
        return (report[section].get("unmet_occupied_hours") or {}).get(key)

    proposed_heating_h = dig("proposed", "heating")
    reference_heating_h = dig("reference", "heating")
    proposed_cooling_h = dig("proposed", "cooling")
    reference_cooling_h = dig("reference", "cooling")

    allowance = float(reference_cooling_h or 0.0) * 0.10
    if str(vintage) == "2025":
        allowance = max(allowance, 20.0)
    proposed_heating_ok = (proposed_heating_h is not None
                           and proposed_heating_h <= HEATING_UNMET_LIMIT_H)
    reference_heating_ok = (reference_heating_h is not None
                            and reference_heating_h <= HEATING_UNMET_LIMIT_H)

    # Sentence (4) applies to thermal blocks "for which mechanical cooling is
    # provided" (explicit in the 2025 wording; applied consistently for 2020)
    # — a proposed building without mechanical cooling accrues
    # passive-overheating "unmet cooling" hours that are NOT a
    # cooling-capacity shortfall.
    cooling_vacuous = report["proposed"].get("mechanical_cooling") is False
    cooling_ok = cooling_vacuous or (
        proposed_cooling_h is not None and reference_cooling_h is not None
        and proposed_cooling_h <= reference_cooling_h + allowance)
    indeterminate = (
        proposed_heating_h is None or reference_heating_h is None
        or (not cooling_vacuous
            and (proposed_cooling_h is None or reference_cooling_h is None)))

    return {"proposed_heating_h": proposed_heating_h,
            "reference_heating_h": reference_heating_h,
            "proposed_cooling_h": proposed_cooling_h,
            "reference_cooling_h": reference_cooling_h,
            "allowance": allowance, "indeterminate": indeterminate,
            "proposed_heating_ok": proposed_heating_ok,
            "reference_heating_ok": reference_heating_ok,
            "heating_ok": proposed_heating_ok and reference_heating_ok,
            "cooling_ok": cooling_ok, "cooling_vacuous": cooling_vacuous,
            "all_ok": (proposed_heating_ok and reference_heating_ok
                       and cooling_ok)}


def _mechanical_cooling(model):
    """Any mechanical cooling in the model? (cooling coils, chillers,
    evaporative coolers, district cooling, ideal-loads air systems)"""
    return any(_COOLING_PATTERN.search(o.iddObjectType().valueName())
               for o in model.modelObjects())


def _iterate_capacities(proposed, reference, report, *, vintage, run_dir,
                        run_period, max_iterations, step, audit):
    """8.4.1.2.(5): "the capacities of the primary and secondary systems of
    the proposed building or the reference building, where applicable, shall
    be incrementally increased until those loads are met." Sentences (3)/(4)
    are written per THERMAL BLOCK, so the increase is targeted: each failing
    building's failing ZONES (per-zone SystemSummary unmet hours from the
    previous run) get their Sizing:Zone heating/cooling sizing factors raised
    — the first bump by `step`, later bumps by secant extrapolation from that
    zone's own (factor, unmet-hours) history, clamped per round so the
    increase stays incremental. Zone factors override the global
    SizingParameters factor and propagate into central equipment through the
    coincident zone sums. When per-zone data is unavailable — or the building
    gate fails without any single zone failing (facility hours are a union
    over zones, not a sum) — the bump falls back to the global sizing
    factors. The reference additionally gets its capacity-binned efficiencies
    re-applied on the new sizes before its energy run. Bounded by
    max_iterations; every bump is an audited decision and the history lands
    in report['capacity_iterations']."""
    from btap.necb import hvac

    history = []
    report["capacity_iterations"] = history
    if int(max_iterations) <= 0:
        return

    zone_trace = {}  # (label, zone, metric) => [(factor, unmet_hours), ...]
    for index in range(max_iterations):
        status = _unmet_status(report, vintage)
        if status["all_ok"]:
            break

        if status["indeterminate"]:
            audit.warn("compliance",
                       "unmet-hours data missing from SQL (no occupied "
                       "hours?) — capacity iteration cannot assess "
                       "convergence; stopping",
                       article="8.4.1.2.(5)")
            break

        iteration = index + 1
        bumps = {
            "proposed": {"heating": not status["proposed_heating_ok"],
                         "cooling": not status["cooling_ok"]},
            "reference": {"heating": not status["reference_heating_ok"],
                          "cooling": False}}
        record = {"iteration": iteration, "bumped": {}}

        for label, model in (("proposed", proposed), ("reference", reference)):
            bump = bumps[label]
            if not (bump["heating"] or bump["cooling"]):
                continue

            with audit.with_building(f"{label} building"):
                factors = _bump_capacities(model, label, report, bump, vintage,
                                           step=step, trace=zone_trace)
                record["bumped"][label] = factors
                if factors["mode"] == "zonal":
                    summary = (
                        f"capacity increase {iteration}: {label} — sizing "
                        f"factor(s) raised on {len(factors['zones'])} failing "
                        "thermal block(s), secant-targeted from the previous "
                        "run(s) — building re-sized and re-run")
                elif factors["mode"] == "mixed":
                    summary = (
                        f"capacity increase {iteration}: {label} — sizing "
                        f"factor(s) raised on {len(factors['zones'])} failing "
                        "thermal block(s), plus a global bump for the gate no "
                        "single zone explains — building re-sized and re-run")
                else:
                    metrics = "+".join(k for k, v in bump.items() if v)
                    summary = (
                        f"capacity increase {iteration}: {label} {metrics} "
                        "GLOBAL sizing factor(s) raised (per-zone attribution "
                        "unavailable) — building re-sized and re-run")
                inputs = {"building": label, "step": step,
                          "iteration": iteration, "mode": factors["mode"]}
                for key in ("heating_sizing_factor", "cooling_sizing_factor"):
                    if key in factors:
                        inputs[key] = factors[key]
                if factors.get("zones"):
                    inputs["zones_bumped"] = len(factors["zones"])
                    inputs["zones"] = dict(list(factors["zones"].items())[:8])
                if factors.get("global"):
                    inputs["global"] = factors["global"]
                audit.decision("compliance", summary, inputs=inputs,
                               article="8.4.1.2.(5)", ruling="D-43")

                dir = os.path.join(run_dir, f"{label}_annual_iter{iteration}")
                if label == "reference":
                    # size on the new factors FIRST so efficiencies re-bin on
                    # the new capacities, then run the energy simulation.
                    # Release the values the previous efficiency pass hard-set
                    # against the OLD sizes first — a frozen pump power
                    # against a freshly grown autosized flow is an EnergyPlus
                    # input FATAL, not a modeling nuance.
                    hvac.prepare_for_resizing(model, audit=audit)
                    runner.run_energyplus(model, f"{dir}_sizing",
                                          sizing_only=True)
                    hvac.apply_efficiencies(model, vintage=vintage,
                                            audit=audit, proposed=proposed)
                _run_annual(model, dir, run_period, report[label], audit=audit)

        record["unmet_after"] = {
            "proposed": report["proposed"].get("unmet_occupied_hours"),
            "reference": report["reference"].get("unmet_occupied_hours")}
        history.append(record)

        # Stall detection: a bump that produced no improvement (>= 1 h) means
        # the equipment is not responding to sizing factors (hard-sized, or
        # the gate fails for equipment that does not exist) — iterating
        # further is futile.
        after = _unmet_status(report, vintage)
        improvements = []
        if bumps["proposed"]["heating"]:
            improvements.append(float(status["proposed_heating_h"] or 0.0)
                                - float(after["proposed_heating_h"] or 0.0))
        if bumps["proposed"]["cooling"]:
            improvements.append(float(status["proposed_cooling_h"] or 0.0)
                                - float(after["proposed_cooling_h"] or 0.0))
        if bumps["reference"]["heating"]:
            improvements.append(float(status["reference_heating_h"] or 0.0)
                                - float(after["reference_heating_h"] or 0.0))
        if after["all_ok"] or any(i >= 1.0 for i in improvements):
            continue

        audit.warn(
            "compliance",
            f"capacity iteration {iteration} produced no unmet-hours "
            "improvement — the failing equipment is not responding to "
            "sizing-factor increases (hard-sized capacity, or the gate "
            "concerns equipment the building does not have); stopping",
            article="8.4.1.2.(5)", ruling="D-43")
        record["stalled"] = True
        break

    final = _unmet_status(report, vintage)
    if not (history and final["all_ok"]):
        return

    audit.info("compliance",
               f"capacity iteration converged after {len(history)} "
               "increase(s) — unmet-hours loads are met",
               inputs={"iterations": len(history)}, article="8.4.1.2.(5)")


def _bump_capacities(model, label, report, bump, vintage, *, step, trace):
    """One building's sentence-(5) increase for one round: per-zone
    Sizing:Zone factors on the failing thermal blocks when the previous run's
    per-zone unmet hours can attribute the failure, global SizingParameters
    otherwise. Returns the history record ('mode', headline factors, per-zone
    factors)."""
    targets = _failing_zone_targets(label, report, bump, vintage)
    zone_hours = report[label].get("zone_unmet_occupied_hours") or {}
    sizing = model.getSizingParameters()
    by_name = {z.nameString().upper(): z for z in model.getThermalZones()}

    zones_record = {}
    for zone_key, metrics in targets.items():
        zone = by_name.get(zone_key.upper())
        if zone is None:
            continue

        sizing_zone = zone.sizingZone()
        for metric, target_h in metrics.items():
            if metric == "heating":
                existing = sizing_zone.zoneHeatingSizingFactor()
                global_f = sizing.heatingSizingFactor()
            else:
                existing = sizing_zone.zoneCoolingSizingFactor()
                global_f = sizing.coolingSizingFactor()
            current_f = existing.get() if existing.is_initialized() else global_f
            current_h = float((zone_hours.get(zone_key) or {}).get(metric)
                              or 0.0)
            key = (label, zone_key, metric)
            history = trace.setdefault(key, [])
            new_f = _next_sizing_factor(history, current_f, current_h,
                                        target_h, step)
            history.append((current_f, current_h))
            if metric == "heating":
                sizing_zone.setZoneHeatingSizingFactor(new_f)
            else:
                sizing_zone.setZoneCoolingSizingFactor(new_f)
            zones_record.setdefault(zone_key, {})[
                f"{metric}_sizing_factor"] = ruby_round(new_f, 3)

    if not zones_record:
        result = _bump_sizing_factors(model, step, heating=bump["heating"],
                                      cooling=bump["cooling"])
        result["mode"] = "global"
        return result

    result = {"mode": "zonal", "zones": zones_record}
    for metric in ("heating", "cooling"):
        values = [v[f"{metric}_sizing_factor"] for v in zones_record.values()
                  if f"{metric}_sizing_factor" in v]
        if values:
            result[f"{metric}_sizing_factor"] = max(values)

    # A gate can fail with no single zone failing (facility hours are a union
    # over zones) — that gate still needs its increase, globally. Zone factors
    # OVERRIDE the global one, so already-bumped zones are unaffected.
    covered = [k for v in zones_record.values() for k in v]
    global_heating = bump["heating"] and "heating_sizing_factor" not in covered
    global_cooling = bump["cooling"] and "cooling_sizing_factor" not in covered
    if global_heating or global_cooling:
        result["mode"] = "mixed"
        result["global"] = _bump_sizing_factors(model, step,
                                                heating=global_heating,
                                                cooling=global_cooling)
    return result


def _failing_zone_targets(label, report, bump, vintage):
    """Which zones does the previous run blame, and what unmet-hours value
    should the next run steer each one toward? Heating (sentence (3)): any
    zone over 100 h in a building whose heating gate failed. Cooling
    (sentence (4), proposed only): any zone whose unmet cooling exceeds the
    SAME zone of the reference (a clone — zone names match) plus the vintage
    allowance. Targets sit at SECANT_TARGET_FRACTION of the applicable limit
    so the extrapolation lands safely inside it, not on its edge."""
    zones = report[label].get("zone_unmet_occupied_hours") or {}
    if not zones:
        return {}

    ref_zones = report["reference"].get("zone_unmet_occupied_hours") or {}
    targets = {}
    for zone, hours in zones.items():
        if bump["heating"] and float(hours.get("heating") or 0.0) > HEATING_UNMET_LIMIT_H:
            targets.setdefault(zone, {})["heating"] = (
                HEATING_UNMET_LIMIT_H * SECANT_TARGET_FRACTION)
        if not bump["cooling"]:
            continue

        ref_h = float((ref_zones.get(zone) or {}).get("cooling") or 0.0)
        allowance = ref_h * 0.10
        if str(vintage) == "2025":
            allowance = max(allowance, 20.0)
        if float(hours.get("cooling") or 0.0) > ref_h + allowance:
            targets.setdefault(zone, {})["cooling"] = (
                (ref_h + allowance) * SECANT_TARGET_FRACTION)
    return targets


def _next_sizing_factor(history, current_f, current_h, target_h, step):
    """Secant step on this zone/metric's own (factor, unmet-hours) history:
    once a previous observation with a real slope exists, extrapolate the
    factor that lands the hours on the target; otherwise (first bump, or a
    flat / perverse slope) fall back to the geometric `step`. The result is
    clamped per round — growth capped at max(step, SECANT_MAX_STEP)x — so the
    increase stays incremental, as sentence (5) is worded."""
    previous = next(
        ((f, h) for f, h in reversed(history)
         if abs(current_f - f) > 1e-6
         and abs(h - current_h) >= SECANT_MIN_IMPROVEMENT_H), None)
    if previous:
        slope = (current_h - previous[1]) / (current_f - previous[0])
        if slope < 0:
            candidate = current_f + (target_h - current_h) / slope
            upper = current_f * max(step, SECANT_MAX_STEP)
            return min(max(candidate, current_f), upper)
    return current_f * step


def _bump_sizing_factors(model, step, *, heating, cooling):
    sizing = model.getSizingParameters()
    result = {}
    if heating:
        sizing.setHeatingSizingFactor(sizing.heatingSizingFactor() * step)
        result["heating_sizing_factor"] = ruby_round(
            sizing.heatingSizingFactor(), 3)
    if cooling:
        sizing.setCoolingSizingFactor(sizing.coolingSizingFactor() * step)
        result["cooling_sizing_factor"] = ruby_round(
            sizing.coolingSizingFactor(), 3)
    return result


def _cost_single_model(model, *, city, province_state, costs_csv, audit):
    """Cost ONE model (HVAC + envelope, same audit) — the shared computation
    behind both compliance paths' costing blocks (each path formats its own
    report dict; the eui path deliberately omits the location keys)."""
    from btap.costing import envelope as costing_envelope
    from btap.costing.hvac import report as costing_hvac

    hvac = costing_hvac.cost(model, city=city, province_state=province_state,
                             costs_csv=costs_csv, audit=audit)
    envelope = costing_envelope.cost(model, city=hvac.city,
                                     province_state=hvac.province_state,
                                     costs_csv=costs_csv, audit=audit)
    return hvac, envelope


def _cost_models(proposed, reference, report, *, city, province_state,
                 costs_csv, audit):
    for label, model in (("proposed", proposed), ("reference", reference)):
        with audit.with_building(f"{label} building"):
            hvac, envelope = _cost_single_model(
                model, city=city, province_state=province_state,
                costs_csv=costs_csv, audit=audit)
            report[label]["cost"] = {
                "hvac": hvac.total, "envelope": envelope.total,
                "total": ruby_round(hvac.total + envelope.total, 2),
                "city": hvac.city, "province_state": hvac.province_state}
    delta = (report["proposed"]["cost"]["total"]
             - report["reference"]["cost"]["total"])
    report["incremental_cost_proposed_vs_reference"] = ruby_round(delta, 2)
    audit.decision(
        "compliance",
        "both models costed (HVAC + envelope) in the shared audit",
        inputs={"proposed_total": report["proposed"]["cost"]["total"],
                "reference_total": report["reference"]["cost"]["total"]},
        value=f"incremental (proposed - reference) "
              f"${ruby_str(ruby_round(delta, 2))}")


def _emit_article_coverage(vintage, audit):
    """Completeness accounting for the umbrella's OWN manifest. Resolution is
    ours (a data file next to this package); the emission is the family's
    shared one (btap.audit emit_coverage, the same call the five domain
    packages make): every declared article lands in the audit with its
    status, partial/not_implemented warn — EXCEPT entries flagged gap_owner:
    "modeller", which emit as info scope notes (D-09). Emitted at the end of
    the happy path only — a crash flush must not assert coverage."""
    path = DATA_DIR / f"necb_rules_{vintage}.json"
    if not path.exists():
        return

    with open(path, encoding="utf-8") as handle:
        emit_coverage(json.load(handle)["article_coverage"], audit)


def _write_outputs(run_dir, report, audit):
    with open(os.path.join(run_dir, "report.json"), "w",
              encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    with open(os.path.join(run_dir, "audit.json"), "w",
              encoding="utf-8") as handle:
        handle.write(audit.to_json())
    with open(os.path.join(run_dir, "audit.txt"), "w",
              encoding="utf-8") as handle:
        handle.write(str(audit))


def _flush_on_failure(run_dir, report, audit, error):
    """On any failure mid-run, record the abort in the audit and flush the
    audit trail + whatever partial report exists to run_dir, so a broken
    proposed (which aborts before the reference is even built) still leaves
    diagnostics behind. The caller re-raises the original error
    afterwards."""
    try:
        audit.warn("compliance",
                   f"run ABORTED before completion: {type(error).__name__}: "
                   f"{error}",
                   inputs={"error_class": type(error).__name__},
                   article="8.4.2.1.")
        _write_outputs(run_dir, report, audit)
    except Exception:
        # never let a write failure mask the original error
        pass


def eui_supplement_verdict(proposed, options, hdd, report, run_dir, run_period,
                           vintage, audit):
    """The 8.4.4 supplement verdict on a reference-path run. Returns the
    report['eui_path'] dict — 'computed': False with 'reason'/'mismatches',
    or 'computed': True with 'bet_kwh', 'compliant', 'basis', 'lines' and the
    energy-tier fields. See the call site for the check-first contract."""
    mapping = options.get("archetypes")
    if mapping is None:
        raise ValueError("eui_supplement requires archetypes: "
                         "{archetype: 'all' | [space names]}")
    resolved = archetypes.resolve(proposed, mapping, audit=audit)
    problems = archetypes.applicability_problems(resolved, hdd=hdd, audit=audit)
    if problems:
        audit.warn("compliance",
                   "EUI supplement NOT COMPUTED — outside 8.4.4 applicability",
                   article="8.4.4.1.(1)", ruling="D-04")
        return {"computed": False,
                "reason": f"outside 8.4.4 applicability: {'; '.join(problems)}"}

    target = tiers.eui_building_energy_target(
        archetypes.bet_areas(resolved, audit=audit),
        resolved["total_area_m2"], hdd=hdd,
        process_loads_kwh=options.get("process_loads_kwh") or 0.0, audit=audit)
    check = archetypes.conformance(proposed, resolved, vintage=vintage,
                                   audit=audit)
    if check["conformant"]:
        proposed_kwh = report["proposed"]["total_site_kwh"]
        source = ("as-specified annual run (proposed conforms to Table "
                  "8.4.4.2 — one run serves both paths)")
    elif options.get("run_normalized"):
        clone = proposed.clone(True)
        normalized = clone.to_Model() if hasattr(clone, "to_Model") else clone
        with audit.with_building("proposed building (EUI-normalized)"):
            archetypes.normalize(
                normalized, archetypes.resolve(normalized, mapping, audit=audit),
                vintage=vintage, audit=audit)
        eui_results = {}
        _run_annual(normalized, os.path.join(run_dir, "proposed_eui_annual"),
                    run_period, eui_results, audit=audit)
        proposed_kwh = eui_results["total_site_kwh"]
        report["proposed_eui_normalized"] = eui_results
        source = "separate annual run of the Table-8.4.4.2-normalized proposed"
    else:
        audit.warn(
            "compliance",
            "EUI supplement NOT COMPUTED — the proposed does not conform to "
            "Table 8.4.4.2, so the reference-path annual result cannot "
            "lawfully serve the 8.4.4 verdict (pass eui_supplement: "
            "{run_normalized: true} to run the normalized proposed)",
            article="8.4.4.2.(1)", ruling="D-04")
        return {"computed": False,
                "reason": "proposed does not conform to Table 8.4.4.2 "
                          "(run_normalized not requested)",
                "mismatches": check["mismatches"][:50]}

    eui_ok = proposed_kwh <= target["bet_kwh"]
    audit.decision(
        "compliance",
        "proposed ALSO meets the archetype-EUI building energy target "
        "(8.4.4 path)" if eui_ok
        else "proposed does NOT meet the archetype-EUI target (8.4.4 path)",
        inputs={"proposed_kwh": proposed_kwh, "bet_kwh": target["bet_kwh"],
                "basis": source},
        article="8.4.4.1.(2); 8.4.4.2.(1)", ruling="D-04")
    return {"computed": True, "bet_kwh": target["bet_kwh"],
            "compliant": eui_ok, "basis": source, "lines": target["lines"],
            **tiers.energy_tier(proposed_kwh, target["bet_kwh"])}


def _validate_space_types(proposed, vintage, audit):
    """Pre-flight gate for the reference path: every space that counts toward
    floor area (and is not a plenum) must carry standards tags that resolve
    against the NECB space-type catalog. Warns per unresolvable type, then
    raises with the full list and nearest-name suggestions. Runs BEFORE any
    simulation or transform, so a mistagged model fails in milliseconds with
    actionable names instead of producing a silently-wrong determination."""
    from btap._compat import sorted_by_name
    from btap.necb import loads

    data_vintage = loads.data_vintage(vintage)
    problems: dict[tuple, list] = {}
    checked = 0
    for space in sorted_by_name(proposed.getSpaces()):
        if not space.partofTotalFloorArea():
            continue

        space_type = opt(space.spaceType())
        name = space_type.nameString() if space_type else "(no space type)"
        if "plenum" in name.lower():
            continue

        checked += 1
        bt = opt(space_type.standardsBuildingType()) if space_type else None
        st = opt(space_type.standardsSpaceType()) if space_type else None
        if st is not None and "plenum" in st.lower():
            st = None
        record = (loads.SpaceTypes.find(building_type=bt, space_type=st,
                                        vintage=data_vintage)
                  if bt and st else None)
        if record is not None and not loads.SpaceTypes.is_undefined(record):
            continue

        problems.setdefault((name, bt, st), []).append(space.nameString())
    if not problems:
        # A silent pass left the 'input model' phase invisible in the audit —
        # the narrative must show the gate ran and what it covered.
        audit.info("compliance",
                   "space-type pre-flight passed — every floor-area space "
                   "type resolves against the NECB catalog",
                   inputs={"floor_area_spaces_checked": checked,
                           "vintage": vintage})
        return

    catalog = loads.table(data_vintage, "space_types")
    lines = []
    for (name, bt, st), spaces in problems.items():
        audit.warn(
            "compliance",
            f"space type '{name}' [{_inspect(bt)}, {_inspect(st)}] is "
            f"UNRESOLVABLE against the NECB {data_vintage} catalog — "
            "lighting/loads/SHW rules cannot be established for "
            f"{len(spaces)} space(s)",
            target=", ".join(spaces), article="8.4.3.1.(2); 4.2.1.6.",
            ruling="D-02")
        if st:
            suggestions = suggest_space_types(st, catalog)
            hint = (f" — did you mean: {' | '.join(suggestions)}?"
                    if suggestions else "")
        else:
            hint = (" — untagged: run the loads on-ramp "
                    "(necb_loads/assign_space_types) or set "
                    "standardsBuildingType + standardsSpaceType to NECB "
                    "catalog names")
        lines.append(f"'{name}' [{_inspect(bt)}, {_inspect(st)}] "
                     f"({len(spaces)} space(s)){hint}")
    joined = "\n  ".join(lines)
    raise PreflightError(
        f"pre-flight FAILED: {len(problems)} space type(s) do not resolve "
        f"against the NECB {data_vintage} space-type catalog, so the "
        "reference building cannot be generated correctly (unmatched types "
        "silently keep the proposed's lighting/loads, waiving the "
        f"allowances):\n  {joined}")


def suggest_space_types(name, catalog):
    """Deterministic nearest-name hints: token overlap against catalog space
    types, best three. Suggestion ONLY — auto-resolution was rejected because
    12 catalog pairs differ solely by a size threshold no string metric can
    choose between.
    :return: up to three catalog names, each single-quoted"""
    tokens = [t for t in re.findall(r"[a-z0-9]+", str(name).lower())
              if t not in ("m2", "sch")]
    if not tokens:
        return []

    seen = []
    for row in catalog:
        candidate = str(row["space_type"])
        if candidate not in seen:
            seen.append(candidate)
    scored = []
    for candidate in seen:
        candidate_tokens = re.findall(r"[a-z0-9]+", candidate.lower())
        score = len(set(tokens) & set(candidate_tokens))
        if score > 0:
            scored.append((candidate, score))
    best = sorted(scored, key=lambda cs: (-cs[1], len(cs[0]), cs[0]))[:3]
    return [f"'{candidate}'" for candidate, _score in best]


def _inspect(value):
    """Ruby ``#inspect`` for the pre-flight message: nil / "quoted"."""
    return "nil" if value is None else f'"{value}"'
