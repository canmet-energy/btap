"""btap.codes.necb.path — NECB's implementation of the determination
lifecycle (multi-edition plan, Stage 9a).

This is the NECB :class:`btap.codes.pipeline.CodePath`: everything in the
Part 8 performance path that is NECB rather than lifecycle. The edition
manifests name this module (``"path": "btap.codes.necb.path"``) and
``Ruleset.path()`` resolves it, exactly as ``behaviours`` are resolved — so
the neutral pipeline reaches NECB only through the registry, and removing
this family is removing a package and a manifest line.

Division B, 8.4.1.2 (identical intent in 2020 and 2025):

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
optional costing of both models lands in the same AuditLog.

The hooks below call back into :mod:`btap.codes.compliance` for the
evidence-bearing phase functions (``_build_reference``, ``_evaluate``,
``_evaluate_unmet``, ``_run_annual``): those forwarding functions are what
the article-coverage pointers name, and routing through them keeps the
pointers attached to code that actually runs."""

from __future__ import annotations

import os
import re

from btap._compat import opt, ruby_div, ruby_round, ruby_str
from btap.audit import AuditLog
from btap.codes import compliance, pipeline, resolve
from btap.codes.necb import tiers
from btap.codes.pipeline import Verdict
from btap.simulation import runner

HEATING_UNMET_LIMIT_H = 100.0    # 8.4.1.2.(3)
SECANT_TARGET_FRACTION = 0.9     # aim below the limit so noise can't strand the last hour
SECANT_MAX_STEP = 2.0            # per-round growth cap (never below the configured `step`)
SECANT_MIN_IMPROVEMENT_H = 1.0   # observations closer than this can't support a slope


_COOLING_PATTERN = re.compile(
    r"Coil_Cooling|CoilSystem_Cooling|Chiller|EvaporativeCooler|DistrictCooling|"
    r"IdealLoadsAirSystem")


# --------------------------------------------------------------------------
# The CodePath hooks. The pipeline calls these in phase order and owns
# everything in between; each one delegates to the implementation below.
# --------------------------------------------------------------------------


def validate(run):
    """Phase 1 (family half): the bare-geometry on-ramp, the simulate-ability
    gate and the NECB space-type pre-flight, then the run's opening
    decision. The model itself was loaded by the pipeline."""
    opts = run.opts
    audit = run.audit
    ruleset = run.ruleset
    proposed = run.proposed
    with audit.with_building("input model"):
        if opts["necb_loads"]:
            _apply_necb_loads(proposed, ruleset, opts["necb_loads"], audit)
        # After the on-ramp (it may have added thermostats to bare geometry):
        # the input must be a simulate-able building before any transform.
        pipeline._validate_input_model(proposed, audit, building=opts["building"])
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
        _validate_space_types(proposed, ruleset, audit)
    audit.decision("compliance", "performance-path run started",
                   inputs={"code": ruleset.id, "edition": ruleset.edition,
                           "simulate": opts["simulate"],
                           "costing": opts["costing"]},
                   article="8.4.1.2.(1)")


def climate(run):
    """Phase 2 (family half): heating degree-days for the envelope rules —
    Table C-1 from the EPW site, then the .stat file."""
    from btap.codes.necb import envelope

    return {"hdd": envelope.hdd18(run.proposed, edition=run.ruleset.edition,
                                  audit=run.audit)}


def prepare_annual(run):
    """Phase 4 (before the pipeline's EnergyPlus call): when the proposed
    carries a heat pump, request the per-equipment delivered-heat variables
    the 8.4.4.13.(2)(g) auxiliary-fuel election reads back."""
    from btap.modeling.hvac import classify

    proposed = run.proposed
    run.report["proposed"]["mechanical_cooling"] = _mechanical_cooling(proposed)
    inventory = classify.heating_election_inventory(proposed)
    hp_present = (any(e["hp"] for e in inventory["loops"].values())
                  or any(any(e["role"] == "hp" for e in entries)
                         for entries in inventory["zones"].values()))
    if hp_present:
        runner.request_run_period_variables(
            proposed,
            ["Heating Coil Heating Energy", "Baseboard Total Heating Energy"])
    run.state["heating_election_inventory"] = inventory if hp_present else None


def consume_annual(run):
    """Phase 4 (after the pipeline's EnergyPlus call): join the SDK inventory
    with the run's per-equipment heating energy (D-52)."""
    inventory = run.state.get("heating_election_inventory")
    if inventory is not None:
        run.proposed_annual_data = _heating_election_data(
            run.proposed, inventory, run.audit)


def determine(run):
    """Phase 5: the NECB Part 8 determination — build the reference building
    on one clone, size it, re-apply the capacity-binned efficiencies, run its
    annual, then the 8.4.1.2.(2)-(4) verdicts with the sentence-(5) capacity
    iteration; then the Part 11 GHG level, optional costing of both models
    and the optional 8.4.4 archetype-EUI supplement.

    ``compliance._build_reference`` is called rather than the implementation
    directly: it is the function the article-coverage pointers name, and a
    pointer must name code that runs."""
    compliance._build_reference(run)  # 5. reference transforms on one clone
    _size_reference(run)              # 6. reference sizing + post-sizing passes
    _compare_and_iterate(run)         # 7. 8.4.1.2.(2)-(4) + sentence-(5) loop
    _score_ghg(run)                   # 8. 2025 Part 11 GHG (needs province_state)
    _cost_both(run)                   # 9. optional costing of both models
    _supplement_eui(run)              # 10. optional 2025 archetype-EUI verdict
    return Verdict(compliant=run.compliant, report=run.report)


def citations(ruleset):
    """This edition's article numbers by the stable keys the rules cite.

    The numbers themselves are exactly what moves between editions (2020's
    reference subsection is 8.4.4, 2025's is 8.4.5), so a renderer that wants
    to print the article behind a finding asks the edition rather than a
    literal."""
    return dict(ruleset.articles)


def report_sections(run):
    """The report sections this run produced, in render order.

    A reference-path determination has a reference building; the
    archetype-EUI path has an ``eui`` block and a target instead, and a
    regime with neither would list neither — the report renders what is
    present."""
    report = run.report or {}
    order = ("proposed", "reference", "eui", "eui_path", "ghg", "tier",
             "capacity_iterations")
    return [name for name in order if report.get(name) not in (None, {}, [])]


def alternate_path(model, name, *, ruleset, weather, hdd, run_dir, simulate,
                   run_period, archetypes_map, process_loads_kwh, costing,
                   city, province_state, costs_csv, necb_loads, report_html,
                   report_options, audit):
    """The NECB 2025 8.4.4 archetype-EUI path — the one NECB compliance path
    whose phase sequence is not the reference-building lifecycle (no
    reference is generated or simulated, and the input gate differs)."""
    if name != "eui":
        raise ValueError(
            f"unknown compliance path {name!r} — NECB offers 'reference' (the "
            "8.4.4/8.4.5 reference-building comparison) and 'eui' (the NECB "
            "2025 8.4.4 archetype-EUI target)")
    # The archetype-EUI path EXISTS only where an edition binds an
    # implementation for it (Stage 5): no edition literal here, so an
    # edition that never adopts 8.4.4 simply has no such path.
    if ruleset.behaviour("archetype_eui_path") is None:
        raise ValueError(
            "the archetype-EUI path is a NECB 2025 feature (code: necb2025)")
    if archetypes_map is None:
        raise ValueError(
            "the 'eui' path requires archetypes_map={archetype: 'all' | "
            "[space names]}")

    return _eui_compliance(model, ruleset=ruleset,
                           weather=weather, hdd=hdd,
                           run_dir=run_dir, simulate=simulate,
                           run_period=run_period,
                           archetypes_map=archetypes_map,
                           process_loads_kwh=process_loads_kwh,
                           costing=costing, city=city,
                           province_state=province_state,
                           costs_csv=costs_csv, necb_loads=necb_loads,
                           report_html=report_html,
                           report_options=report_options, audit=audit)


# 5. reference building: HVAC, envelope, lighting (+ photocontrols) and SHW
#    transforms on ONE clone, same audit
def build_reference(run):
    from btap.codes.necb import envelope, hvac, lighting
    from btap.codes.necb.shw import reference as shw_reference

    opts = run.opts
    audit = run.audit
    proposed = run.proposed
    ruleset = run.ruleset
    prefix = ruleset.article("lighting_subsection")
    with audit.with_building("reference building"):
        reference_result = hvac.reference._reference_hvac(
            proposed, ruleset, building=opts["building"], audit=audit,
            proposed_annual=run.proposed_annual_data)
        reference = reference_result.model
        envelope.reference._apply(
            reference, ruleset, hdd=run.hdd,
            actual_roof_absorptance_used=opts["actual_roof_absorptance_used"],
            thermal_bridging=opts["thermal_bridging"], audit=audit)
        # daylighting: tells reference_lighting whether (5)-(12) are covered
        # by the separate daylighting transform below — it shouts the gap only
        # when they are not.
        lighting.Reference._reference_lighting(
            reference, ruleset, daylighting=opts["reference_daylighting"],
            audit=audit)
        if opts["reference_daylighting"]:
            audit.decision(
                "compliance",
                "reference photocontrols BUILT by default: 4.2.2 requires "
                "photocontrols, and "
                f"{prefix}.5.(9)-(12) requires their effect to be "
                "evaluated in the reference — a reference generated without "
                "them is non-conformant, so correctness outranks the "
                "detailed-daylighting runtime cost (pass "
                "reference_daylighting: false to opt out)",
                article=f"{prefix}.5.(9)-(12)", ruling="D-51")
            lighting.ReferenceDaylighting._apply(reference, ruleset,
                                                proposed=proposed, audit=audit)
        else:
            audit.warn(
                "compliance",
                "reference photocontrols SUPPRESSED by the caller "
                "(reference_daylighting: false): "
                f"{prefix}.5.(9)-(12) photocontrol effect is NOT "
                "evaluated in this reference, so the target it sets is more "
                "lenient than the code requires",
                article=f"{prefix}.5.(9)-(12)", ruling="D-51")
        shw_reference._reference_shw(reference, ruleset, audit=audit)
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
    from btap.codes.necb import hvac

    opts = run.opts
    audit = run.audit
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
        hvac.efficiency._apply(reference, run.ruleset, audit=audit,
                               proposed=run.proposed)
        # 5.2.10.1 energy recovery is a POST-SIZING determination (Table
        # 5.2.10.1.-A/-B thresholds need the sized supply/OA flows).
        hvac.energy_recovery._apply_energy_recovery(reference, run.ruleset,
                                                    hdd=run.hdd, audit=audit)
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
    run.compliant = None
    if opts["simulate"] == "annual":
        # Stamp the reference's first annual — step 4 sits outside the earlier
        # with_building blocks and its run entry was landing unattributed.
        with audit.with_building("reference building"):
            compliance._run_annual(run.reference,
                                   os.path.join(opts["run_dir"],
                                                "reference_annual"),
                                   opts["run_period"],
                                   run.report["reference"], audit=audit)
        _iterate_capacities(run.proposed, run.reference, run.report,
                            ruleset=run.ruleset, run_dir=opts["run_dir"],
                            run_period=opts["run_period"],
                            max_iterations=opts["max_capacity_iterations"],
                            step=opts["capacity_step"], audit=audit)
        run.compliant = compliance._evaluate(run.report, run.ruleset,
                                             opts["run_period"], audit)
    elif opts["simulate"] == "sizing":
        audit.info("compliance",
                   "simulate: :sizing — both models generated and sized; no "
                   "energy comparison performed (compliance undetermined)")


# 8. Part 11 operational GHG performance level, for the editions that have
#    one (NECB 2025 today) — needs a province
def _score_ghg(run):
    opts = run.opts
    report = run.report
    part11_ghg = run.ruleset.behaviour("part11_ghg")
    if not (part11_ghg is not None and opts["simulate"] == "annual"
            and opts["province_state"]):
        return

    proposed_ghg = part11_ghg.operational_ghg_kg(report["proposed"],
                                                 opts["province_state"])
    reference_ghg = part11_ghg.operational_ghg_kg(report["reference"],
                                                  opts["province_state"])
    if not (proposed_ghg is not None and reference_ghg is not None
            and reference_ghg > 0):
        return

    report["proposed"]["ghg_kg_co2e"] = proposed_ghg
    report["reference"]["ghg_kg_co2e"] = reference_ghg
    report["ghg"] = part11_ghg.ghg_level(proposed_ghg, reference_ghg, audit=run.audit)


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
    if not (opts["eui_supplement"]
            and run.ruleset.behaviour("archetype_eui_path") is not None
            and run.report["proposed"].get("total_site_kwh") is not None):
        return

    run.report["eui_path"] = eui_supplement_verdict(
        run.proposed, opts["eui_supplement"], run.hdd, run.report,
        opts["run_dir"], opts["run_period"], run.ruleset, run.audit)


def _eui_compliance(model, *, ruleset, weather, hdd, run_dir, simulate,
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
    from btap.codes.necb import envelope

    # Both edition-bound: the caller has already refused the path when this
    # edition binds no archetype-EUI implementation.
    archetypes = ruleset.behaviour("archetype_eui_path")
    part11_ghg = ruleset.behaviour("part11_ghg")
    audit = audit if audit is not None else AuditLog()
    report_options = report_options or {}
    os.makedirs(run_dir, exist_ok=True)
    report = {}
    try:
        with audit.with_building("input model"):
            proposed = compliance._load_model(model, audit=audit)
            if necb_loads:
                _apply_necb_loads(proposed, ruleset, necb_loads, audit)
            pipeline._validate_input_model(proposed, audit,
                                           building=None,
                                           require_storeys=False)
        audit.decision("compliance",
                       "ARCHETYPE-EUI compliance path (NECB 2025 8.4.4) — no "
                       "reference building",
                       inputs={"code": ruleset.id, "edition": ruleset.edition,
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
            hdd = envelope.hdd18(proposed, edition=ruleset.edition, audit=audit)

        # Mapping -> model-derived areas -> HARD applicability (refuse outside
        # 8.4.4.1.(1)/HDD bounds: a verdict outside applicability is not a
        # determination) -> Table 8.4.4.2 conformance -> normalize if needed.
        resolved = archetypes.resolve(proposed, archetypes_map, audit=audit)
        archetypes.verify_applicability(resolved, hdd=hdd, audit=audit)
        check = archetypes.conformance(proposed, resolved, code=ruleset.id,
                                       audit=audit)
        if not check["conformant"]:
            archetypes.normalize(proposed, resolved, code=ruleset.id,
                                 audit=audit)
        audit.building = None  # BET derivation + verdicts are comparisons,
        # not model work

        report = {"edition": ruleset.edition, "code": ruleset.id,
                  "code_label": ruleset.label, "hdd": hdd,
                  "simulate": simulate,
                  "path": "eui", "proposed": {}, "reference": {},
                  "eui": {"conformant_to_8_4_4_2": check["conformant"],
                          "normalized": not check["conformant"],
                          "mismatches": check["mismatches"][:50]}}
        target = archetypes.eui_building_energy_target(
            archetypes.bet_areas(resolved, audit=audit),
            resolved["total_area_m2"], hdd=hdd,
            process_loads_kwh=process_loads_kwh, audit=audit)
        report["reference"] = {
            "method": "archetype EUI (Table 8.4.4.1)",
            "building_energy_target_kwh": target["bet_kwh"],
            "lines": target["lines"]}

        compliant = None
        if simulate == "annual":
            compliance._run_annual(
                proposed, os.path.join(run_dir, "proposed_annual"),
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
            if province_state and part11_ghg is not None:
                ghg = part11_ghg.operational_ghg_kg(report["proposed"],
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
        return pipeline._finalize(pipeline._Run(
            opts={"code": ruleset.id, "run_dir": str(run_dir),
                  "report_html": report_html,
                  "report_options": report_options},
            ruleset=ruleset,
            proposed=proposed, reference=None, report=report, audit=audit,
            compliant=compliant))
    except Exception as e:
        pipeline._flush_on_failure(str(run_dir), report, audit, e)
        raise


def _apply_necb_loads(proposed, ruleset, options, audit):
    """The bare-geometry on-ramp: NECB space types -> loads -> lighting ->
    SHW -> (optionally) an HVAC system, all on the proposed clone with the
    shared audit."""
    import btap.modeling as modeling
    from btap._compat import sorted_by_name
    from btap.codes.necb import lighting, loads
    from btap.codes.necb.shw import demand as shw_demand

    map_ = options.get("space_type_map")
    if map_ is None:
        raise ValueError("necb_loads requires space_type_map: "
                         "{space name: [building_type, space_type]}")

    loads.Apply._assign_space_types(proposed, map_, ruleset, audit=audit)
    loads.Apply._apply_loads(proposed, ruleset, audit=audit)
    lighting.ApplyLights._apply_lights(proposed, ruleset,
                          lights_type=options.get("lights_type")
                          or "NECB_Default", audit=audit)
    shw_fuel = options.get("shw_fuel")
    if shw_fuel:
        shw_demand._apply_shw(proposed, ruleset, fuel=shw_fuel, audit=audit)
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


def evaluate(report, ruleset, run_period, audit):
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

    unmet_ok = compliance._evaluate_unmet(report, ruleset, audit)

    if run_period:
        audit.warn("compliance",
                   "run period is SHORTENED — the energy comparison above is "
                   "not a code-compliant annual determination (8.4.1.2 "
                   "requires a simulated year)")
        report["annual"] = False
    else:
        report["annual"] = True
    return energy_ok and unmet_ok


def evaluate_unmet(report, ruleset, audit):
    status = _unmet_status(report, ruleset)
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


def _minimum_cooling_allowance_h(ruleset):
    """The absolute floor, in hours, under 8.4.1.2.(4)'s cooling allowance.

    Every edition DECLARES this: 2025 allows +10% of the reference or 20 h,
    whichever is greater; 2020's wording has no floor and declares 0.0. A
    missing key raises rather than defaulting — a silent 0.0 for an edition
    that meant 20 h is exactly the cross-edition leak the snapshots remove.
    """
    return float(ruleset.rules("umbrella")["unmet_cooling"]["minimum_allowance_h"])


def _unmet_status(report, ruleset):
    """The (3)/(4) arithmetic without audit side effects — shared by the
    formal verdicts and the capacity-iteration loop.
    (4): the allowance is +10% of the reference, or this edition's declared
    minimum (necb_rules.json `unmet_cooling.minimum_allowance_h`: 2020 has no
    floor, 2025's 8.4.5 path allows 20 h), whichever is greater."""
    def dig(section, key):
        return (report[section].get("unmet_occupied_hours") or {}).get(key)

    proposed_heating_h = dig("proposed", "heating")
    reference_heating_h = dig("reference", "heating")
    proposed_cooling_h = dig("proposed", "cooling")
    reference_cooling_h = dig("reference", "cooling")

    allowance = max(float(reference_cooling_h or 0.0) * 0.10,
                    _minimum_cooling_allowance_h(ruleset))
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


def _iterate_capacities(proposed, reference, report, *, ruleset, run_dir,
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
    from btap.codes.necb import hvac

    history = []
    report["capacity_iterations"] = history
    if int(max_iterations) <= 0:
        return

    zone_trace = {}  # (label, zone, metric) => [(factor, unmet_hours), ...]
    for index in range(max_iterations):
        status = _unmet_status(report, ruleset)
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
                factors = _bump_capacities(model, label, report, bump,
                                           ruleset.id,
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
                    hvac.efficiency._apply(model, ruleset,
                                            audit=audit, proposed=proposed)
                compliance._run_annual(model, dir, run_period,
                                       report[label], audit=audit)

        record["unmet_after"] = {
            "proposed": report["proposed"].get("unmet_occupied_hours"),
            "reference": report["reference"].get("unmet_occupied_hours")}
        history.append(record)

        # Stall detection: a bump that produced no improvement (>= 1 h) means
        # the equipment is not responding to sizing factors (hard-sized, or
        # the gate fails for equipment that does not exist) — iterating
        # further is futile.
        after = _unmet_status(report, ruleset)
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

    final = _unmet_status(report, ruleset)
    if not (history and final["all_ok"]):
        return

    audit.info("compliance",
               f"capacity iteration converged after {len(history)} "
               "increase(s) — unmet-hours loads are met",
               inputs={"iterations": len(history)}, article="8.4.1.2.(5)")


def _bump_capacities(model, label, report, bump, code, *, step, trace):
    """One building's sentence-(5) increase for one round: per-zone
    Sizing:Zone factors on the failing thermal blocks when the previous run's
    per-zone unmet hours can attribute the failure, global SizingParameters
    otherwise. Returns the history record ('mode', headline factors, per-zone
    factors)."""
    targets = _failing_zone_targets(label, report, bump,
                                    resolve(code))
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


def _failing_zone_targets(label, report, bump, ruleset):
    """Which zones does the previous run blame, and what unmet-hours value
    should the next run steer each one toward? Heating (sentence (3)): any
    zone over 100 h in a building whose heating gate failed. Cooling
    (sentence (4), proposed only): any zone whose unmet cooling exceeds the
    SAME zone of the reference (a clone — zone names match) plus the edition
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
        allowance = max(ref_h * 0.10, _minimum_cooling_allowance_h(ruleset))
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


def eui_supplement_verdict(proposed, options, hdd, report, run_dir,
                           run_period, ruleset, audit):
    mapping = options.get("archetypes")
    if mapping is None:
        raise ValueError("eui_supplement requires archetypes: "
                         "{archetype: 'all' | [space names]}")
    # Reached only from `_supplement_eui`, which has already established that
    # this edition binds the behaviour.
    archetypes = ruleset.behaviour("archetype_eui_path")
    resolved = archetypes.resolve(proposed, mapping, audit=audit)
    problems = archetypes.applicability_problems(resolved, hdd=hdd, audit=audit)
    if problems:
        audit.warn("compliance",
                   "EUI supplement NOT COMPUTED — outside 8.4.4 applicability",
                   article="8.4.4.1.(1)", ruling="D-04")
        return {"computed": False,
                "reason": f"outside 8.4.4 applicability: {'; '.join(problems)}"}

    target = archetypes.eui_building_energy_target(
        archetypes.bet_areas(resolved, audit=audit),
        resolved["total_area_m2"], hdd=hdd,
        process_loads_kwh=options.get("process_loads_kwh") or 0.0, audit=audit)
    check = archetypes.conformance(proposed, resolved, code=ruleset.id,
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
                code=ruleset.id, audit=audit)
        eui_results = {}
        compliance._run_annual(
            normalized, os.path.join(run_dir, "proposed_eui_annual"),
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


def _validate_space_types(proposed, ruleset, audit):
    """Pre-flight gate for the reference path: every space that counts toward
    floor area (and is not a plenum) must carry standards tags that resolve
    against the NECB space-type catalog. Warns per unresolvable type, then
    raises with the full list and nearest-name suggestions. Runs BEFORE any
    simulation or transform, so a mistagged model fails in milliseconds with
    actionable names instead of producing a silently-wrong determination."""
    from btap._compat import sorted_by_name
    from btap.codes.necb import loads

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
                                        edition=ruleset.edition)
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
                           "code": ruleset.id, "edition": ruleset.edition})
        return

    catalog = loads.table(ruleset.edition, "space_types")
    lines = []
    for (name, bt, st), spaces in problems.items():
        audit.warn(
            "compliance",
            f"space type '{name}' [{_inspect(bt)}, {_inspect(st)}] is "
            f"UNRESOLVABLE against the NECB {ruleset.edition} catalog — "
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
    raise compliance.PreflightError(
        f"pre-flight FAILED: {len(problems)} space type(s) do not resolve "
        f"against the NECB {ruleset.edition} space-type catalog, so the "
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
