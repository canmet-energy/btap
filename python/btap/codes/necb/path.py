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
from btap.codes import ahj as _ahj
from btap.codes import compliance, pipeline, resolve
from btap.codes.necb import tiers
from btap.codes.pipeline import Verdict
from btap.simulation import runner

HEATING_UNMET_LIMIT_H = 100.0    # 8.4.1.2.(3)
#: 8.4.1.2.(4)(a). On the Subsection 8.4.4 path the cooling criterion
#: is an ABSOLUTE limit on the proposed building, not a comparison
#: with a reference that this path never builds. (4)(b)'s +10%/20 h
#: allowance is the 8.4.5 branch and does not apply here, which is
#: why this is a separate constant rather than a reuse.
COOLING_UNMET_LIMIT_H_8_4_4 = 100.0
SECANT_TARGET_FRACTION = 0.9     # aim below the limit so noise can't strand the last hour
SECANT_MAX_STEP = 2.0            # per-round growth cap (never below the configured `step`)
SECANT_MIN_IMPROVEMENT_H = 1.0   # observations closer than this can't support a slope


_COOLING_PATTERN = re.compile(
    r"Coil_Cooling|CoilSystem_Cooling|Chiller|EvaporativeCooler|DistrictCooling|"
    r"IdealLoadsAirSystem")

#: Cooling objects that sit UPSTREAM of whatever serves a thermal block. A
#: chiller or a district-cooling node cools a plant loop, and the coil drawing
#: on that loop is itself matched by `_COOLING_PATTERN` and resolves to its own
#: blocks — so attributing the plant as well would mark every block on the
#: loop's demand side as cooled, including blocks served only for process or
#: service-water demand.
_UPSTREAM_COOLING_PATTERN = re.compile(r"Chiller|DistrictCooling")


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
    if run.opts["simulate"] == "none":
        # The pipeline skipped the proposed sizing run; what that costs is
        # NECB's own statement, not the lifecycle's. Emitted here because
        # `determine` is the first hook the pipeline calls after the skipped
        # sizing phase and nothing audits in between, so the entry keeps its
        # position in the trail.
        run.audit.warn(
            "compliance",
            "proposed is UNSIZED (simulate: :none) — data-centre kW "
            "thresholds and capacity-binned efficiencies fall back with "
            "warnings; the 5.2.10.1 energy-recovery determination needs "
            "sized flows and is SKIPPED")
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


def abort(audit, error):
    """The failure-flush entry, in NECB's terms: 8.4.2.1 makes compliance a
    matter of MODELING, so a run that ended before it could model both
    buildings made no determination at all. The pipeline calls this from
    :func:`btap.codes.pipeline._flush_on_failure` just before it writes the
    trail, on both NECB paths (the reference lifecycle and the archetype-EUI
    :func:`alternate_path`), so every aborted NECB run cites the same
    article."""
    audit.warn("compliance",
               f"run ABORTED before completion: {type(error).__name__}: "
               f"{error}",
               inputs={"error_class": type(error).__name__},
               article="8.4.2.1.")


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
        embedded_floor_inventory = (
            envelope.prescriptive._embedded_floor_inventory(proposed))
        reference_result = hvac.reference._reference_hvac(
            proposed, ruleset, building=opts["building"], audit=audit,
            proposed_annual=run.proposed_annual_data,
            # `_size_reference` sizes and re-runs the efficiency pass for every
            # mode but `none`, so only `none` makes that pass's capacity
            # warnings the final word.
            sizing_follows=opts["simulate"] != "none")
        reference = reference_result.model
        envelope.reference._apply(
            reference, ruleset, hdd=run.hdd,
            actual_roof_absorptance_used=opts["actual_roof_absorptance_used"],
            thermal_bridging=opts["thermal_bridging"], audit=audit,
            embedded_floor_inventory=embedded_floor_inventory)
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
    # The reference-subsection prefix, for the two article numbers quoted in
    # the text below. They were 2020 literals on every 2025 run (Fable's
    # `133` G3), in the `compliance` step every frozen 2025 run carries.
    _sub = run.ruleset.article('reference_subsection')
    audit.info(
        "compliance",
        "8.4.3.2 operating schedules and occupancy/receptacle loads are "
        "identical between proposed and reference by construction (the "
        "reference is a clone; neither reset touches schedules or those "
        "loads); interior lighting power is reset to the Part 4 allowance per "
        f"{_sub}.5.(1) (reference_lighting); service water heating efficiencies "
        f"are reset to the Part 6 minimums per {_sub}.20 (reference_shw). "
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
        hvac.prepare_for_resizing(reference, audit=audit, code=run.ruleset.id)
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
        hvac.apply_economizer_thresholds(reference, audit=audit,
                                         code=run.ruleset.id)
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
        # D-90: name any capacity sizing-factor increases cannot reach, for the
        # 8.4.1.2.(5) warnings (recorded only when something is found)
        for label, built in (("proposed", run.proposed), ("reference", run.reference)):
            hard = _hard_sized_capacities(built)
            if hard:
                run.report[label]["hard_sized_capacities"] = hard
        _iterate_capacities(run.proposed, run.reference, run.report,
                            ruleset=run.ruleset, run_dir=opts["run_dir"],
                            run_period=opts["run_period"],
                            max_iterations=opts["max_capacity_iterations"],
                            step=opts["capacity_step"], audit=audit)
        run.compliant = compliance._evaluate(run.report, run.ruleset,
                                             opts["run_period"], audit)
        _resolve_ahj_conditions(run, audit)
    elif opts["simulate"] == "sizing":
        audit.info("compliance",
                   "simulate: :sizing — both models generated and sized; no "
                   "energy comparison performed (compliance undetermined)")


def _resolve_ahj_conditions(run, audit):
    """Collect the AHJ dispositions the rule sites CITED, and set the
    determination from their registry statuses.

    Ownership, per Sol's `127`: the deciding rule site owns APPLICABILITY,
    because it has the selected system, topology, equipment and branch
    outcome. This function owns POLICY only — resolve the cited ids, keep the
    ones whose status requires approval, and make an annual determination
    conditional when that set is non-empty.

    It therefore does NOT: inspect the proposed model, re-characterize HVAC,
    parse audit action text, infer anything from `level`, or know any
    individual question's predicate. The previous
    `_mark_informational_if_multi_energy` recomputed
    a `multi_energy_serving_systems` helper here to decide whether AHJ-1 and
    AHJ-3 had
    fired, which was a second source of truth beside the branch that already
    knew — the drift this design removes.

    All four statuses are collected for traceability. Only `referral` and
    `alternative-solution` change the verdict: a `tool-gap` stays a defect and
    a `ruled` question stays settled, and neither may be described as
    something an authority must accept.
    """
    code = getattr(run.ruleset, "code", None) or run.report.get("code")
    # SUPERSESSION FIRST. A later pass that re-makes the same choice must
    # replace the earlier record even when it cites NOTHING — Fable's `131` F3:
    # dedup kept the last CITING entry, so a 400 kW boiler whose class the Code
    # elected on the second pass still carried AHJ-14 from the first, and the
    # authority was told its class was an unresolved local default while the
    # final audit entry said `modulating, reference selection`.
    #
    # "The same choice" is identified structurally, never from action text:
    # same step, same target, and the same INPUT FIELDS recorded. One
    # `_apply_boiler` pass emits one decision per boiler carrying
    # `part_load_curve_class` and `class_source`, so a second pass over the
    # same boiler matches and supersedes it, while an unrelated entry about the
    # same target records different fields and does not.
    latest_by_choice = {}
    for index, entry in enumerate(audit.entries):
        fields = frozenset((entry.get("inputs") or {}).keys())
        if not fields:
            # NEVER supersede an entry that records no inputs. Fable's `133`
            # G1: AHJ-11's System 5 decision records none, so its identity
            # collapsed to (step, target) and the purchased-cooling decision
            # emitted after it on the same zones — also input-less — "re-made
            # the choice" and retired the referral. A heated refrigerated block
            # on district cooling reported `code` with no conditions at all,
            # which is the silent-drop this whole axis exists to prevent, and
            # my own supersession fix introduced it.
            #
            # An empty field set is not an identity. It is the ABSENCE of one,
            # and treating absence as a match is what let two unrelated
            # decisions collide. AHJ-16's five input-less warns had the same
            # fragility without colliding yet.
            continue
        key = (entry.get("step"), entry.get("target"), fields,
               # `ruling` too: non-prose and site-specific, so two genuinely
               # different decisions that happen to record the same field
               # names stay distinct.
               entry.get("ruling"))
        latest_by_choice[key] = index
    superseded = set()
    for index, entry in enumerate(audit.entries):
        fields = frozenset((entry.get("inputs") or {}).keys())
        if not fields:
            continue
        key = (entry.get("step"), entry.get("target"), fields,
               entry.get("ruling"))
        if latest_by_choice.get(key) != index:
            superseded.add(index)

    fired, conditions = [], []
    for index, entry in enumerate(audit.entries):
        citation = entry.get("ahj")
        if not citation:
            continue
        if index in superseded:
            # A later entry re-made this exact choice, recording the same
            # fields under the same ruling.
            continue
        malformed = _ahj.malformed_ids_in(citation)
        if malformed:
            raise _ahj.UnknownAHJ(
                "audit entry {} cites {!r}, which is not a well-formed AHJ "
                "citation; expected space-separated ids like "
                "'AHJ-1 AHJ-5'".format(index, malformed))
        for record in _ahj.resolve(citation, code=code):
            fired.append(record["id"])
            conditions.append({
                "id": record["id"],
                "status": record["status"],
                "title": record["title"],
                "article": entry.get("article"),
                "target": entry.get("target"),
                # The firing entry's own words, QUOTED not parsed. Sol's `127`
                # forbids inferring POLICY from action text, and this infers
                # nothing — it carries the site's substance to the reader.
                # Without it the report would lose the disclosure wording eight
                # review rounds produced, including that what the reference's
                # final equipment carries is NOT established by this tool.
                "detail": entry.get("action"),
                "entry_index": index,
            })
    # ONE QUESTION PER FINAL CHOICE. The efficiency pass runs twice — once
    # against the proposed's sizing, once against the reference's — so the same
    # boiler's same class decision was recorded as two conditions, and the
    # full-year baseline showed four where there was one live choice (Sol,
    # `128`.3). Deduped by (id, target) keeping the LAST occurrence. The
    # supersession filter above is what makes that safe: on its own, keeping
    # the last CITING entry left a stale condition whenever the final pass
    # cited nothing (Fable, `131` F3). The audit history is untouched; only the
    # derived condition set collapses.
    latest = {}
    for record in conditions:
        latest[(record["id"], record.get("target"))] = record
    conditions = list(latest.values())
    fired = [record["id"] for record in conditions]

    if not fired:
        # Sol's `127`: "no approval-required id -> compliance_determination:
        # 'code'". The POSITIVE statement matters — a reader must be able to
        # tell an unqualified determination from a run where the question was
        # never asked, and a missing key cannot say that. Only an ANNUAL run
        # has a determination to state.
        if run.report.get("annual"):
            run.report["compliance_determination"] = "code"
        return

    order = {record["id"]: position for position, record
             in enumerate(_ahj.registry()["entries"])}
    unique = sorted(set(fired), key=lambda ident: order.get(ident, 10**6))
    run.report["ahj_applied"] = [
        {"id": ident,
         "status": _ahj.by_id()[ident]["status"],
         "title": _ahj.by_id()[ident]["title"],
         # UNIQUE final choices, not audit entries: two efficiency passes over
         # one boiler are one question.
         "count": fired.count(ident)}
        for ident in unique]
    run.report["ahj_register"] = "docs/NECB_AHJ_QUESTIONS.md"

    approval = tuple(_ahj.approval_required_statuses())
    required = [ident for ident in unique
                if _ahj.by_id()[ident]["status"] in approval]
    if not required:
        # Citations still travel as provenance, and the determination is
        # UNQUALIFIED: a `ruled` or `tool-gap` citation does not qualify a
        # verdict, so saying "code" here is the honest positive statement.
        if run.report.get("annual"):
            run.report["compliance_determination"] = "code"
        return
    if not run.report.get("annual"):
        # A `none`, `sizing` or shortened run has no determination to qualify.
        # Turning "no determination" into a conditional verdict would invent a
        # determination the run never reached.
        return
    _set_conditional(run, audit, required, conditions, approval)


def _set_conditional(run, audit, required, conditions, approval):
    """Write the conditional determination from the FIRED condition records.

    Generic by construction: the condition text is built from each record's
    status, title, article and target, so an AHJ-11 System-5 condition is not
    rendered as a boiler-capacity condition (Sol, `127`).
    """
    active = [record for record in conditions
              if record["id"] in set(required)]
    run.report["compliance_determination"] = "conditional"
    # ONE APPROVAL LINE PER REGISTER ID, with its equipment listed inside it
    # (Sol's `128`.3: "the approval banner itself remains once per AHJ id").
    # The CONDITIONS still enumerate every unique final choice — six gas coils
    # each making the same unresolved class choice are six choices — but an
    # authority reads ONE statement of the question, not six copies of it.
    by_id = {}
    for record in active:
        by_id.setdefault(record["id"], []).append(record)

    deduped = []
    for ident in sorted(by_id, key=lambda value: int(value.split("-")[1])):
        group = by_id[ident]
        first = group[0]
        if first["status"] == "alternative-solution":
            kind = ("an ALTERNATIVE SOLUTION, which the text DECIDES and this "
                    "tool does not meet — accepting it means accepting an "
                    "explicitly identified non-conforming substitution")
        else:
            kind = ("an INTERPRETATION the acceptable-solution text does not "
                    "settle")
        seen_targets, targets = set(), []
        for record in group:
            target = record.get("target")
            if target and target not in seen_targets:
                seen_targets.add(target)
                targets.append(str(target))
        where = " Applies to: {}".format(", ".join(targets)) if targets else ""
        # QUOTE ONE SITE'S ACCOUNT ONLY WHEN IT IS THE ONLY SITE.
        #
        # This took `details[0]` for the whole id group, so AHJ-14's frozen
        # line described five gas furnace coils as "boiler efficiency applied"
        # (Fable's `131` F8). One equipment's account is not the group's
        # account, and the id that fires most is the one it misdescribed.
        #
        # With several sites the line states the QUESTION and lets the
        # `conditions` list carry each site's own `detail`. The question is
        # what an authority rules on; the per-site accounts are the evidence
        # under it, and they are already in the report.
        #
        # " — " not " ": without a separator the quoted detail ran straight
        # into "Applies to: Hot Water Loop", which an authority has to read.
        details = [str(r["detail"]) for r in group if r.get("detail")]
        if len(group) == 1 and details:
            detail = " — " + details[0]
        elif details:
            # KEYED ON STATUS, like the `kind` clause before it. The one
            # sentence said "this same unresolved election" for every status,
            # so an AHJ-1 line read "which the text DECIDES ... this same
            # unresolved election" in a single breath (Fable's `133` G5). An
            # alternative solution is not an unresolved question; it is a
            # requirement the text settles and this tool does not meet.
            shared = ("departure" if first["status"] == "alternative-solution"
                      else "unresolved election")
            detail = (" — each of the {} choices above makes this same {}; "
                      "the conditions list carries what was established at "
                      "each one".format(len(group), shared))
        else:
            detail = ""
        deduped.append("{} ({}): {} — {}.{}{}".format(
            ident, first["status"], first["title"], kind, where, detail))
    run.report["compliance_determination_reason"] = {
        "why": ("{} register question(s) requiring approval were raised by "
                "this run's modelling choices, so the comparison is "
                "INFORMATIONAL and is NOT a Code-compliance determination. "
                "Each condition below names the question, its register status "
                "and the deciding entry's own account of what was and was not "
                "established.".format(len(set(required)))),
        "condition": "approval by the authority having jurisdiction",
        "if_not_approved": (
            "the comparison does not establish compliance and no verdict "
            "from it may be submitted as a determination"),
        "ahj_ids": list(required),
        "ahj_register": "docs/NECB_AHJ_QUESTIONS.md",
        "ahj_must_approve": deduped,
        "conditions": active,
    }
    # Warnings are never silent (the AuditLog contract), and the determination
    # must be visible in the audit as well as the report. Generic by
    # construction: it enumerates the resolved ids and statuses rather than
    # naming any one question, so an AHJ-11 condition does not arrive wearing
    # multi-energy wording.
    audit.warn(
        'compliance',
        'INFORMATIONAL AND CONDITIONAL: {} register question(s) requiring '
        'approval by the authority having jurisdiction were raised by this '
        "run's modelling choices, so the verdict below is NOT a "
        'Code-compliance determination. {}'.format(
            len(set(required)),
            '; '.join('{} ({})'.format(record['id'], record['status'])
                      for record in active[:8])),
        target=', '.join(sorted({str(record['target']) for record in active
                                 if record.get('target')})) or None,
        inputs={'ahj_ids': list(required),
                'ahj_register': 'docs/NECB_AHJ_QUESTIONS.md'},
        article=', '.join(sorted({str(record['article']) for record in active
                                  if record.get('article')})) or None,
        ruling='D-99 D-100')


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
                                  ddy=weather["ddy"], audit=audit)
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
            # (4)'s vacuity rule needs this, and this path never gets it from
            # `prepare_annual`: that runs inside `pipeline._proposed_annual`,
            # the REFERENCE flow, while this path calls `_run_annual` directly
            # and only rejoins the pipeline at `_finalize`. Without it the
            # lookup returns None rather than False, the clause stops being
            # vacuous, and an uncooled building is judged on its
            # passive-overheating hours — the exact false positive the
            # reference path's vacuity rule exists to prevent.
            report["proposed"]["mechanical_cooling"] = _mechanical_cooling(
                proposed)
            # And PER BLOCK, because (4) is scoped to each block "for which
            # mechanical cooling is provided" — one building-wide flag marks a
            # mixed building's uncooled blocks as cooled.
            cooling_map, unplaceable = _zone_mechanical_cooling(proposed)
            # TWO OPPOSITE-DIRECTION WALKS, COMPARED IN EVERY RUN. They are
            # independent for object-to-block traversal, but both deliberately
            # share `_has_downstream_relief_exchanger`; dedicated topology
            # tests, not this comparison, guard that one direction judgement.
            # A block they disagree about is one whose cooling status this
            # tool does not know, not a block that is uncooled.
            #
            # Sol's `227 §G` asked for this in product rather than in a
            # test, "because every real run benefits from it". It earns that
            # immediately: the DOAS defect Fable found in `228` — a cooling
            # coil with a fan inboard of it, reported detached and passing
            # (4)(a) vacuously over 900 unmet hours — shows up here as
            # `{Z1: (False, True)}`. A run that consulted the comparison
            # would have gone indeterminate instead of passing.
            disagreement = cooling_attribution_disagreement(proposed)
            for block, (outward, inward) in sorted(disagreement.items()):
                if block not in unplaceable:
                    unplaceable.append(block)
                audit.warn(
                    "proposed cooling attribution",
                    "COOLING ATTRIBUTION DISAGREES BETWEEN THE OUTWARD AND "
                    "INWARD WALKS, so this block's cooling status is UNKNOWN "
                    "and sentence (4) cannot be scoped to it",
                    target=block,
                    inputs={"outward_from_cooling_objects": outward,
                            "inward_from_the_block": inward},
                    article="8.4.1.2.(4)")
            unplaceable = sorted(unplaceable)
            report["proposed"]["zone_mechanical_cooling"] = cooling_map
            report["proposed"]["unplaceable_cooling"] = unplaceable
            report["proposed"]["cooling_attribution_disagreement"] = {
                block: list(pair) for block, pair in disagreement.items()}
            proposed_kwh = report["proposed"]["total_site_kwh"]
            energy_ok = proposed_kwh <= target["bet_kwh"]
            audit.decision(
                "compliance",
                "proposed does not exceed the archetype-EUI building energy "
                "target" if energy_ok
                else "proposed EXCEEDS the archetype-EUI building energy target",
                inputs={"proposed_kwh": proposed_kwh,
                        "bet_kwh": target["bet_kwh"]},
                article="8.4.4.1.(2)")
            # 8.4.1.2.(3) and (4)(a). The energy comparison is NOT the whole
            # determination, and until 2026-10-11 it was the whole of it on
            # this path: a model could be declared compliant with any number
            # of unmet thermal-block hours, and (4)(a) is the branch of (4)
            # written FOR a building complying under Subsection 8.4.4 (AHJ-21,
            # Sol's `189`). Composed the same way the reference path composes
            # `energy_ok and unmet_ok`.
            unmet_ok = evaluate_unmet_8_4_4(report, audit)
            compliant = energy_ok and unmet_ok
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
        # `ruleset.path()` is this very module — reached the way the pipeline
        # reaches it, through the registry, rather than by naming ourselves.
        pipeline._flush_on_failure(str(run_dir), report, audit, e,
                                   ruleset.path())
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
        hard = sorted({name for label in ("proposed", "reference")
                       for name in (report[label].get("hard_sized_capacities") or [])})
        cause = ("hard-sized capacities do not respond to sizing-factor increases: "
                 + _hard_sized_phrase(hard)) if hard else (
                 "no hard-sized capacity was detected among " + _HARD_SIZED_SCOPE)
        audit.warn(
            "compliance",
            f"8.4.1.2.(5): unmet-hours limits still not met after "
            f"{iterations} capacity increase(s) — the building remains "
            "non-compliant; raise max_capacity_iterations, increase "
            f"capacity_step, or fix the design ({cause}).", article="8.4.1.2.(5)")
    return status["all_ok"]


def _unmet_status_8_4_4(report):
    """(3) and (4)(a) PER THERMAL BLOCK, each decided on its OWN evidence.

    The archetype-EUI path builds NO reference model, so (3)'s "and, where
    applicable, for the reference building" has nothing to apply to and (4)'s
    reference comparison is unavailable by construction. 2025 writes the
    branch for exactly this case: (4)(a) is an absolute 100 h on the proposed
    building "when complying with Subsection 8.4.4.", against (4)(b)'s
    reference comparison "when complying with Subsection 8.4.5."

    Both sentences are written per thermal block, and the FACILITY row cannot
    stand in for them. Facility time is a union over blocks, so disjoint
    unmet periods sum past 100 h with no single block anywhere near it: Sol's
    `212` gave the facility-reading version 150 h with two blocks at 75 h each
    and it returned not-compliant on a building where every block conformed.

    **The two criteria are tracked separately**, which is Sol's `220`. A
    single combined flag reported BOTH unknown when only (4)(a)'s
    applicability was unresolved: given a block with heating 1.0 h, cooling
    900.0 h and no resolvable cooled block, it warned that "(3) and (4)(a)
    cannot be determined" — but (3) CAN be determined from 1.0 h and passes.
    The final verdict was right and its AHJ-facing evidence was false, citing
    the wrong operative sentence.

    **And an unresolved object is not the same as no cooled block.** A
    building whose cooling serves only process or service-water demand
    genuinely has no thermal block "for which mechanical cooling is
    provided", so (4) is VACUOUS there. Only a cooling object the model walk
    cannot place leaves applicability unknown (Fable, `219`).
    """
    section = report["proposed"]
    blocks = section.get("zone_unmet_occupied_hours") or {}
    cooled_map = {str(k).upper(): bool(v) for k, v in
                  (section.get("zone_mechanical_cooling") or {}).items()}
    unplaceable = list(section.get("unplaceable_cooling") or [])

    # ---- sentence (3): heating, every block -------------------------------
    heating_failures, heating_unreadable = {}, set()
    for name, hours in blocks.items():
        value = (hours or {}).get("heating")
        if value is None:
            # A block with absent hours is not a conforming block. Skipping
            # it would make silence a pass, one block at a time.
            heating_unreadable.add(name)
            continue
        if float(value) > HEATING_UNMET_LIMIT_H:
            heating_failures[name] = float(value)
    heating_known = bool(blocks) and not heating_unreadable
    heating_ok = heating_known and not heating_failures

    # ---- sentence (4)(a): cooling, every MECHANICALLY COOLED block --------
    #
    # The cooled set comes from the APPLICABILITY MAP, not from the result
    # rows. Counting it while iterating rows meant a block the model says is
    # cooled but EnergyPlus produced no row for was never seen at all:
    # `cooled_blocks` reached 0, the sentence went vacuous, and the run
    # PASSED (Sol, `224`). That is the same silence-as-pass defect already
    # fixed for a present row with an absent value, one level earlier.
    #
    # The two maps are compared in BOTH directions, because each gap is a
    # different kind of unknown and neither is vacuity: a result block absent
    # from the applicability map has unknown applicability, and a cooled
    # applicability block absent from the results has no measurement.
    building_has_cooling = section.get("mechanical_cooling") is not False
    rows = {str(name).upper(): name for name in blocks}
    cooled_names = sorted(name for name, is_cooled in cooled_map.items()
                          if is_cooled)
    cooled_blocks = len(cooled_names)

    cooling_failures, cooling_unreadable, unattributed = {}, set(), set()
    unmeasured = set()
    for name in rows:
        if name not in cooled_map:
            unattributed.add(rows[name])
    for upper in cooled_names:
        original = rows.get(upper)
        if original is None:
            unmeasured.add(upper)
            continue
        value = (blocks[original] or {}).get("cooling")
        if value is None:
            cooling_unreadable.add(original)
            continue
        if float(value) > COOLING_UNMET_LIMIT_H_8_4_4:
            cooling_failures[original] = float(value)

    # Vacuous where the sentence reaches no block, and that is a DECIDED
    # outcome: either the building has no mechanical cooling at all, or every
    # cooling object was placed and none of them reaches a thermal block.
    cooling_vacuous = (not building_has_cooling
                       or (not unplaceable and cooled_blocks == 0
                           and not unattributed))
    cooling_known = cooling_vacuous or (
        bool(blocks) and bool(cooled_map) and not unplaceable
        and not unattributed and not cooling_unreadable
        and not unmeasured)
    cooling_ok = cooling_vacuous or (cooling_known and not cooling_failures)

    return {"blocks": len(blocks),
            "cooled_blocks": cooled_blocks,
            "heating_failures": heating_failures,
            "cooling_failures": cooling_failures,
            "heating_unreadable": sorted(heating_unreadable),
            "cooling_unreadable": sorted(cooling_unreadable),
            "unattributed_blocks": sorted(unattributed),
            "unmeasured_cooled_blocks": sorted(unmeasured),
            "unplaceable_cooling": sorted(unplaceable),
            "worst_heating_h": max(
                (float((h or {}).get("heating") or 0.0)
                 for h in blocks.values()), default=None),
            "cooling_vacuous": cooling_vacuous,
            "heating_known": heating_known,
            "cooling_known": cooling_known,
            "heating_ok": heating_ok,
            "cooling_ok": cooling_ok,
            "all_ok": heating_ok and cooling_ok}


def evaluate_unmet_8_4_4(report, audit):
    """Audit (3) and (4)(a) per thermal block on the archetype-EUI path and
    return the verdict. Each sentence is reported on its OWN evidence: one
    being undeterminable does not make the other unknown (Sol, `220`)."""
    status = _unmet_status_8_4_4(report)

    # ---- sentence (3) -----------------------------------------------------
    if not status["heating_known"]:
        audit.warn(
            "compliance",
            "per-thermal-block unmet HEATING hours are UNAVAILABLE for the "
            "proposed building, so 8.4.1.2.(3) cannot be determined — the "
            "Facility row is a union over blocks and is NOT substituted for "
            "them",
            inputs={"blocks": status["blocks"],
                    "unreadable_blocks": status["heating_unreadable"] or None},
            article="8.4.1.2.(3)", ahj="AHJ-21")
    else:
        audit.decision(
            "compliance",
            f"unmet heating hours within 100 h for every one of "
            f"{status['blocks']} thermal block(s) with reported hours"
            if status["heating_ok"]
            else "unmet heating hours EXCEED 100 h for "
                 f"{len(status['heating_failures'])} of {status['blocks']} "
                 "thermal block(s) with reported hours",
            inputs={"blocks": status["blocks"],
                    "worst_block_h": status["worst_heating_h"],
                    "failing_blocks": status["heating_failures"] or None,
                    "limit_h": HEATING_UNMET_LIMIT_H},
            value=("the reference building is not applicable on this path — "
                   "8.4.4 derives the target from Table 8.4.4.1 and builds no "
                   "reference, which is what (3)'s \"where applicable\" admits"),
            article="8.4.1.2.(3)", ahj="AHJ-21")

    # ---- sentence (4)(a) --------------------------------------------------
    if status["cooling_vacuous"]:
        audit.decision(
            "compliance",
            "sentence (4)(a) is vacuous — the proposed building has no "
            "thermal block \"for which mechanical cooling is provided\"",
            inputs={"blocks": status["blocks"], "cooled_blocks": 0,
                    "building_has_cooling":
                        report["proposed"].get("mechanical_cooling")},
            article="8.4.1.2.(4)(a)", ahj="AHJ-21")
    elif not status["cooling_known"]:
        # A KNOWN failure is reported as a failure, even while the sentence's
        # full scope is unresolved. Both facts are true and an authority
        # needs both: "block A exceeds 100 h" and "some other object could
        # not be placed". Reporting only the second hid the first — a block
        # measured at 900 unmet hours and KNOWN to be mechanically cooled
        # disappeared behind "cannot be established" because an unrelated
        # stray coil was unplaceable (Fable, `229` NB-3). The verdict was
        # right either way; the evidence cited the wrong thing, which is the
        # same defect Sol's `220` found when one warning spoke for two
        # sentences.
        if status["cooling_failures"]:
            # A DECISION, not a warning. The exceedance is established on
            # its own evidence, and the report checklist keys its glyph on
            # `level` ALONE: as a warning this rendered the same block with
            # the same verdict as a warning row when a stray coil existed
            # and as a fail row when it did not (Fable, `236`). The audit
            # text being SHOUTED does not reach the renderer; the level
            # does.
            audit.decision(
                "compliance",
                "unmet cooling hours EXCEED 100 h for "
                f"{len(status['cooling_failures'])} thermal block(s) KNOWN "
                "to be mechanically cooled, AND the sentence's full scope "
                "could not be established — the exceedance is established "
                "on its own and does not depend on the unresolved part",
                inputs={"failing_blocks": status["cooling_failures"],
                        "limit_h": COOLING_UNMET_LIMIT_H_8_4_4,
                        "unplaceable_cooling":
                            status["unplaceable_cooling"] or None,
                        "unattributed_blocks":
                            status["unattributed_blocks"] or None},
                article="8.4.1.2.(4)(a)", ahj="AHJ-21")
        audit.warn(
            "compliance",
            "which thermal blocks (4)(a) APPLIES to cannot be established "
            "for the proposed building, so the sentence cannot be determined "
            "— cooling equipment is present and at least one object or block "
            "could not be placed",
            inputs={"blocks": status["blocks"],
                    "cooled_blocks": status["cooled_blocks"],
                    "unplaceable_cooling":
                        status["unplaceable_cooling"] or None,
                    "unattributed_blocks":
                        status["unattributed_blocks"] or None,
                    "unmeasured_cooled_blocks":
                        status["unmeasured_cooled_blocks"] or None,
                    "unreadable_blocks":
                        status["cooling_unreadable"] or None},
            article="8.4.1.2.(4)(a)", ahj="AHJ-21")
    else:
        audit.decision(
            "compliance",
            f"unmet cooling hours within 100 h for every one of "
            f"{status['cooled_blocks']} mechanically cooled thermal block(s)"
            if status["cooling_ok"]
            else "unmet cooling hours EXCEED 100 h for "
                 f"{len(status['cooling_failures'])} of "
                 f"{status['cooled_blocks']} mechanically cooled thermal "
                 "block(s)",
            inputs={"cooled_blocks": status["cooled_blocks"],
                    "blocks": status["blocks"],
                    "failing_blocks": status["cooling_failures"] or None,
                    "limit_h": COOLING_UNMET_LIMIT_H_8_4_4},
            value=("8.4.1.2.(4)(a), the branch for a building complying under "
                   "Subsection 8.4.4 — an absolute limit per mechanically "
                   "cooled thermal block, not (4)(b)'s allowance over a "
                   "reference. Uncooled blocks are OUTSIDE the sentence: "
                   "their passive-overheating hours are not a capacity "
                   "shortfall"),
            article="8.4.1.2.(4)(a)", ahj="AHJ-21")

    # Sentence (5) applies to loads that are NOT MET. Reaching it on
    # `not all_ok` conflated a block known to be over its limit with missing
    # evidence, so a run with heating at 1 h and unresolved cooling
    # applicability was told to increase capacities that nothing had shown to
    # be short (Sol, `224`). The indeterminate verdict stands on its own; it
    # does not imply a required capacity increase.
    if status["heating_failures"] or status["cooling_failures"]:
        audit.warn(
            "compliance",
            "8.4.1.2.(5) requires the proposed building's capacities to be "
            "incrementally increased until these loads are met. That is NOT "
            "done on this path: raising the capacities of the user's own "
            "design is a different act from raising a reference's, and its "
            "mechanics are unadjudicated (AHJ-21). The verdict below is "
            "therefore NOT COMPLIANT rather than remediated.",
            article="8.4.1.2.(5)", ahj="AHJ-21")
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


def _hard_sized_capacities(model):
    """D-90: heating and cooling equipment whose capacity is a hard value the
    reference pipeline does not own — equipment 8.4.1.2.(5) sizing-factor
    increases cannot reach. Plant capacities the efficiency pass derived from
    sizing (capacity source 'autosized') are excluded: they are released before
    every re-sizing run. Staged multispeed coils are not listed; their stage
    capacities follow the autosized top stage."""
    from btap.codes.necb.hvac import efficiency

    def owned(component):
        source = component.additionalProperties().getFeatureAsString(
            efficiency.CAPACITY_SOURCE_FEATURE)
        return source.is_initialized() and source.get() == "autosized"

    found = []
    for boiler in model.getBoilerHotWaters():
        if not boiler.isNominalCapacityAutosized() and not owned(boiler):
            found.append(boiler.nameString())
    for chiller in model.getChillerElectricEIRs():
        if not chiller.isReferenceCapacityAutosized() and not owned(chiller):
            found.append(chiller.nameString())
    for unit in model.getZoneHVACBaseboardConvectiveWaters():
        coil = unit.heatingCoil().to_CoilHeatingWaterBaseboard()
        if (coil.is_initialized()
                and coil.get().heatingDesignCapacityMethod() == "HeatingDesignCapacity"
                and not coil.get().isHeatingDesignCapacityAutosized()):
            found.append(unit.nameString())
    for group in (model.getZoneHVACBaseboardConvectiveElectrics(),
                  model.getCoilHeatingGass(), model.getCoilHeatingElectrics()):
        for component in group:
            if not component.isNominalCapacityAutosized():
                found.append(component.nameString())
    for coil in model.getCoilCoolingDXSingleSpeeds():
        if not coil.isRatedTotalCoolingCapacityAutosized():
            found.append(coil.nameString())
    return sorted(found)


#: What _hard_sized_capacities inspects — stated in the warnings so an empty result
#: is never read as "no hard capacity anywhere" (staged coils are not inspected).
_HARD_SIZED_SCOPE = ("boilers, chillers, baseboards, gas and electric coils and "
                     "single-speed DX cooling coils (hydronic coils, DX heating "
                     "coils and staged coils are not checked)")


def _hard_sized_phrase(names):
    shown = ", ".join(names[:5])
    if len(names) > 5:
        shown += f" and {len(names) - 5} more"
    return shown


#: Objects that place a cooling coil in a topology. Reaching one of these
#: means the coil IS connected to something, so failing to attribute it is an
#: unresolved question rather than a stray object.
#: Type-name stems that mean "this object is part of HVAC topology", matched
#: by SUBSTRING. Used only by `_reaches_no_topology`, to tell a DETACHED
#: object — which serves no block, a known answer — from one that reaches
#: real topology and could not be attributed, which is unknown.
#:
#: Substring matching reaches 137 of the SDK's 1429 IDD type names, and
#: Fable's `229` NB-5 is right that `AirLoopHVAC` also matches
#: `AirLoopHVAC_ZoneSplitter`, `_ZoneMixer`, `_ReturnPlenum`,
#: `_SupplyPlenum` and `_UnitarySystem`, and `ZoneHVAC` matches
#: `ZoneHVAC_EquipmentList`. Every one of those IS topology, so the accident
#: gives the right answer — but an accident is not a reason, and the
#: direction of error is what makes it safe to keep: a type matched in error
#: makes an object UNRESOLVED instead of detached, and unresolved is the
#: conservative answer. The reverse — failing to match real topology —
#: would assert that a coil cools nothing, which is the defect `224` found.
#:
#: `test_the_substring_matches_are_all_real_topology` drives the shapes
#: rather than pinning 137 names that move with the SDK.
#: An air-to-air exchanger, which couples the relief stream to the OA
#: stream. `HeatExchangerAirToAirSensibleAndLatent` is the one the SDK
#: builds; the prefix covers the family.
#:
#: `iddObjectType().valueName()` SEPARATES the words —
#: `OS_HeatExchanger_AirToAir_SensibleAndLatent` — and my first version
#: wrote the class name as it appears in Python, `HeatExchangerAirToAir`,
#: which matched nothing. The relief fix silently did not fire. Written from
#: the actual string this time, with the separator optional so both spellings
#: match.
_EXCHANGER_PATTERN = re.compile(r"HeatExchanger_?AirToAir")

_TOPOLOGY_TYPES = re.compile(
    r"AirLoopHVAC|PlantLoop|ThermalZone|ZoneHVAC|AirTerminal|"
    r"OutdoorAirSystem")


def _as_doas(obj):
    """The dedicated outdoor-air system this object IS, or None."""
    caster = getattr(obj, "to_AirLoopHVACDedicatedOutdoorAirSystem", None)
    if caster is None:
        return None
    got = caster()
    return got.get() if got.is_initialized() else None


def _as_oa_system(obj):
    """The outdoor-air system this object IS, or None."""
    caster = getattr(obj, "to_AirLoopHVACOutdoorAirSystem", None)
    if caster is None:
        return None
    got = caster()
    return got.get() if got.is_initialized() else None


def _has_downstream_relief_exchanger(relief, position):
    """Whether a later relief-air component transfers this one's effect."""
    return any(
        _EXCHANGER_PATTERN.search(component.iddObjectType().valueName())
        for component in relief[position + 1:])


def _oa_system_holding(obj):
    """The outdoor-air system whose OA or relief stream HOLDS this object.

    Returns `(oa_system, stream)` where `stream` is `'oa'` or `'relief'`,
    because the two mean OPPOSITE things for attribution and treating them
    alike attributed an exhaust-side coil to every block (Fable, `229`
    NB-1).

    MEMBERSHIP, not distance. The source walk below bounds its depth, and a
    bound is a guess about how far away a container sits: an
    `AirLoopHVACOutdoorAirSystem` references only its controller and two port
    Connections, so every component on the OA stream costs four hops. A
    cooling coil ALONE on that stream resolved at depth four; put the
    textbook fan and heating coil inboard of it and the same coil sits at
    twelve, so the walk reported it DETACHED and 8.4.1.2.(4)(a) passed
    vacuously over 900 unmet hours (Fable, `228`).

    Raising the bound would only move the wall. `oaComponents()` answers the
    question exactly: either the object is in that stream or it is not.
    """
    handle = obj.handle()
    for oa_system in obj.model().getAirLoopHVACOutdoorAirSystems():
        for component in oa_system.oaComponents():
            if component.handle() == handle:
                return oa_system, "oa"
        relief = list(oa_system.reliefComponents())
        for position, component in enumerate(relief):
            if component.handle() == handle:
                # A RELIEF COMPONENT WITH AN EXCHANGER DOWNSTREAM IS NOT
                # EXHAUST-ONLY. `reliefComponents()` follows relief airflow
                # from `reliefAirModelObject()` to `outboardReliefNode()`.
                # An air-to-air exchanger later in the list therefore
                # transfers what this object did to the exhaust INTO the
                # outdoor-air stream, which is indirect evaporative cooling.
                #
                # Fable's `236`: an `EvaporativeCoolerDirectResearchSpecial`
                # on relief, upstream of a straddling
                # `HeatExchangerAirToAirSensibleAndLatent`, cooled the
                # supply air while BOTH walks said "cools no block" — so
                # (4)(a) went vacuous and 900 unmet hours passed on a model
                # EnergyPlus accepts with zero severe errors. My rule
                # "relief air is exhausted" was true in isolation and false
                # once an exchanger couples the streams.
                #
                # A component after the exchanger is exhaust-only. Treating
                # any exchanger anywhere in the stream as sufficient falsely
                # put that component's blocks inside (4)(a)'s scope.
                if _has_downstream_relief_exchanger(relief, position):
                    return oa_system, "relief_through_exchanger"
                return oa_system, "relief"
    return None, None


def _reaches_no_topology(obj, depth=6) -> bool:
    """Is this object connected to no HVAC topology whatever?

    Walks the reference graph outward and looks for anything that could place
    a coil. A detached object's graph holds only its own connections and
    nodes, and that is what distinguishes "serves no block" — a known answer
    — from "could not be attributed" — an unknown one.
    """
    seen = set()
    frontier = [(obj, 0)]
    while frontier:
        current, level = frontier.pop()
        if level > depth or current.handle() in seen:
            continue
        seen.add(current.handle())
        if level and _TOPOLOGY_TYPES.search(current.iddObjectType().valueName()):
            return False
        for source in current.sources():
            as_model_object = source.to_ModelObject()
            if as_model_object.is_initialized():
                frontier.append((as_model_object.get(), level + 1))
    return True


def _relief_reaching_supply(oa_system):
    """Relief-stream components an exchanger couples back to the OA stream.

    `reliefComponents()` follows airflow from `reliefAirModelObject()` toward
    `outboardReliefNode()`, so only a component with an air-to-air exchanger
    LATER in the list has what it did to the exhaust transferred into the
    outdoor air. Those objects condition the supply and serve whatever the
    OA system serves.

    The inward walk needs this for the same reason the outward walk does,
    and for a sharper one: if only the outward walk learned it, the two
    would disagree on every such model and the oracle would report a
    disagreement instead of an answer. Seeding ALL relief components was the
    original blind spot (`229` NB-1); seeding the ones that reach the supply
    is the narrow version of the same idea.
    """
    relief = list(oa_system.reliefComponents())
    return [
        component for position, component in enumerate(relief)
        if not _EXCHANGER_PATTERN.search(
            component.iddObjectType().valueName())
        and _has_downstream_relief_exchanger(relief, position)]


def _zone_cooling_inward(model) -> dict:
    """Which blocks have cooling, walked INWARD from each block.

    The opposite-direction half of the attribution invariant. `_zone_
    mechanical_cooling` starts at every cooling object and resolves OUTWARD
    to the blocks it serves; this starts at every block and asks what serves
    IT. The two use opposite edges of the same object graph — outward follows
    `sources()` and the containment accessors, inward follows `targets()` from
    a block's own equipment, terminal and air loop — so a bug in either
    traversal usually surfaces as a DISAGREEMENT rather than as a quiet wrong
    answer. Both traversals share `_has_downstream_relief_exchanger`, however,
    so only the dedicated relief-topology tests can detect a direction error
    in that helper.

    That is the point. Every cooling-attribution defect in this file was
    found by a reviewer hand-building one topology at a time: a VRF coil the
    3.11 SDK does not link to its terminal unit, a unitary system on an air
    loop whose `thermalZone()` is empty, an air terminal carrying its own
    coil. Each was one shape, each passed the nine-model corpus, and each
    cost a review round. A second opinion catches the class instead of the
    instance (Sol's `227`, Fable's `226`).
    """
    cooled = {}
    for zone in model.getThermalZones():
        seeds = list(zone.equipment())
        terminal = zone.airLoopHVACTerminal()
        if terminal.is_initialized():
            seeds.append(terminal.get())
        try:
            loops = list(zone.airLoopHVACs())
        except (AttributeError, TypeError):      # older SDK: one loop only
            single = zone.airLoopHVAC()
            loops = [single.get()] if single.is_initialized() else []
        for loop in loops:
            seeds.extend(loop.supplyComponents())
            # The loop's OWN outdoor-air system, when it has one.
            own_oa = loop.airLoopHVACOutdoorAirSystem()
            if own_oa.is_initialized():
                seeds.extend(own_oa.get().oaComponents())
                # Not every relief component: exhaust-side equipment cools
                # no block, and seeding all of it is what made the two walks
                # agree about a relief coil they were both wrong about
                # (`229` NB-1). Only the ones an exchanger couples back into
                # the supply, which is the case that made them agree in the
                # OTHER direction (`236`).
                seeds.extend(_relief_reaching_supply(own_oa.get()))
            # And a DEDICATED system shared with other loops: a cooling coil
            # in there serves this block as much as one on the loop itself.
            # A DOAS is not the loop's own OA system — the loop reaches it
            # through `airLoopHVACDedicatedOutdoorAirSystem()`, and my first
            # attempt here looked for it in the wrong place. The invariant
            # reported the two halves disagreeing both times, which is what
            # it is for.
            shared = getattr(
                loop, "airLoopHVACDedicatedOutdoorAirSystem", None)
            if shared is not None:
                shared = shared()
                if shared.is_initialized():
                    inner = shared.get().airLoopHVACOutdoorAirSystem()
                    seeds.extend(inner.oaComponents())
                    seeds.extend(_relief_reaching_supply(inner))

        found = False
        seen = set()
        queue = [(seed, 0) for seed in seeds]
        while queue and not found:
            obj, depth = queue.pop()
            if depth > 4 or obj.handle() in seen:
                continue
            seen.add(obj.handle())
            name = obj.iddObjectType().valueName()
            if (_COOLING_PATTERN.search(name)
                    and not _UPSTREAM_COOLING_PATTERN.search(name)):
                found = True
                break
            for target in obj.targets():
                as_object = target.to_ModelObject()
                if as_object.is_initialized():
                    queue.append((as_object.get(), depth + 1))
        cooled[zone.nameString().upper()] = (
            found or bool(zone.useIdealAirLoads()))
    return cooled


def cooling_attribution_disagreement(model) -> dict:
    """Blocks the two traversals disagree about: `{BLOCK: (outward, inward)}`.

    Empty is the expected answer. A non-empty result means one direction has
    a bug for this topology, and a caller must SAY so rather than pick a
    side: which side is wrong is exactly what is not known. This is not an
    oracle for their shared relief/exchanger direction helper; dedicated
    topology tests guard that common dependency.
    """
    outward, _unplaceable = _zone_mechanical_cooling(model)
    inward = _zone_cooling_inward(model)
    return {block: (outward.get(block), inward.get(block))
            for block in sorted(set(outward) | set(inward))
            if outward.get(block) != inward.get(block)}


def _zone_mechanical_cooling(model) -> tuple:
    """`({BLOCK: cooled}, [unresolved cooling object, ...])`.

    8.4.1.2.(4) is scoped to "each thermal block ... for which mechanical
    cooling is provided", and `_mechanical_cooling` answers only whether the
    MODEL contains any. Once one block is cooled that flag is true for the
    whole building, so passive-overheating hours from an uncooled block enter
    the determination and can fail a sentence that never reached them (Sol,
    `212`).

    Cooling is resolved TO blocks rather than asked OF them, because a block's
    equipment list carries the PTAC and not the DX coil inside it: matching
    equipment types reported `05-ptac-electric`, a fully cooled building, as
    having no cooled block at all — the direction that makes (4)(a) wrongly
    vacuous.

    Resolution is ordered NARROWEST FIRST: a zone component with a zone, then
    an air terminal's own block, then a containing component, then the air
    loop, then the plant. A coil's scope is the smallest thing that holds it.

    Two corrections are worth naming, because I got each wrong once. A zone
    component counts only when `thermalZone()` is actually set —
    `AirLoopHVACUnitarySystem` and a VRF terminal unit are
    `ZoneHVACComponent` subclasses that sit on AIR LOOPS, and treating those
    as "placed with nothing attributed" made a fully cooled PSZ building
    report no cooled block, so (4)(a) went vacuous over 500 h of unmet
    cooling per block. And an air TERMINAL is not a `ZoneHVACComponent` at
    all, so reordering the rungs could not reach the cooled-beam case I said
    it had fixed; terminals are placed through `thermalZone.airLoopHVACTerminal()`,
    which is the only direction the SDK offers (Fable, `223`).

    The second return value is the cooling objects the walk could NOT place.
    That distinction is what keeps a resolution failure from looking like an
    answer: a building whose cooling serves only process or service-water
    demand genuinely has NO cooled thermal block, and (4) is vacuous there,
    while a coil nobody can place means applicability is unknown and the
    determination must say so rather than pass over an empty set. Treating
    both as indeterminate failed buildings the Code does not reach (Fable,
    `219`).
    """
    cooled = set()
    unresolved = []

    # An air TERMINAL serves exactly one block, and the SDK gives that
    # relationship only in this direction. Without it, a terminal's own
    # cooling coil falls through to `airLoopHVAC()` and claims every block on
    # the loop — so a four-pipe induction unit or cooled beam in ONE zone of
    # an otherwise heating-only loop marked all of them cooled (Fable, `219`
    # and `223`; my narrowest-first reorder did NOT fix this, because an air
    # terminal is not a `ZoneHVACComponent`, and I wrongly said it had).
    terminal_zone = {}
    for zone in model.getThermalZones():
        terminal = zone.airLoopHVACTerminal()
        if terminal.is_initialized():
            terminal_zone[terminal.get().handle()] = zone.nameString().upper()

    def zone_of(obj, depth=0):
        """Did this object's blocks get attributed? Narrowest scope first."""
        if depth > 6:                # these chains are shallow; this bounds a cycle
            return False
        # OA-SYSTEM MEMBERSHIP FIRST, before any rung that places this
        # object by proximity or by its water side. Two defects made this
        # the right position, both found by running it:
        #
        # On a PLAIN loop a relief-stream coil answers
        # `component.airLoopHVAC()` with that loop — it IS on the loop — so
        # the loop rung attributed it to every zone the loop serves before
        # the stream was consulted (Fable, `229` NB-1).
        #
        # And a CHILLED-WATER DOAS coil answers `plantLoop()`, which sat
        # above the containment rung and won: the outward walk returned
        # False, the inward True, and the oracle had to rescue the run. So
        # the containment fix did not reach the coil type a running DOAS
        # actually uses, and my own test fixture used a PLANT-LESS water
        # coil — the single shape that skips the rung (Fable, `236`).
        holder, stream = _oa_system_holding(obj)
        if holder is not None:
            if stream == "relief":
                # EXHAUST-ONLY relief. `relief_through_exchanger` is NOT
                # handled here: it falls through to the OA attribution
                # below, which is precisely "attribute it as an OA-stream
                # component" (Fable, `236`).
                # See `relief_through_exchanger` above
                # for the case where an exchanger makes this false.
                #
                # RELIEF AIR IS EXHAUSTED. A cooling coil on the relief
                # stream conditions air leaving the building, so it cools no
                # thermal block — PLACED, with nothing to attribute, like a
                # plant loop carrying only process demand.
                #
                # Both walks used to attribute it to every zone of the loop
                # and AGREE, because the inward walk seeded
                # `reliefComponents()` too: independence had been traded for
                # agreement in exactly one place (Fable, `229` NB-1).
                return True
            loop = holder.airLoopHVAC()
            if loop.is_initialized():
                for zone in loop.get().thermalZones():
                    cooled.add(zone.nameString().upper())
                return True
            dedicated = holder.airLoopHVACDedicatedOutdoorAirSystem()
            if dedicated.is_initialized():
                for served in dedicated.get().airLoops():
                    for zone in served.thermalZones():
                        cooled.add(zone.nameString().upper())
                return True
            # In an OA stream that feeds no loop: PLACED, with nothing to
            # attribute — not the same as unresolved.
            return True

        # A zone component, but ONLY if it actually has a zone.
        # `AirLoopHVACUnitarySystem` and a VRF terminal unit are
        # `ZoneHVACComponent` subclasses that can sit on an AIR LOOP, where
        # `thermalZone()` is empty. Returning "placed" for those made a
        # fully cooled PSZ building — which `modeling/hvac/psz.py` builds —
        # report no cooled block at all, so (4)(a) went vacuous and 500 h of
        # unmet cooling per block passed (Fable, `223`). That is a regression
        # I introduced; the previous ordering got it right.
        zone_component = obj.to_ZoneHVACComponent()
        if zone_component.is_initialized():
            zone = zone_component.get().thermalZone()
            if zone.is_initialized():
                cooled.add(zone.get().nameString().upper())
                return True
            # else fall through: it is on a loop, not in a zone.
        if obj.handle() in terminal_zone:
            cooled.add(terminal_zone[obj.handle()])
            return True
        component = obj.to_HVACComponent()
        if component.is_initialized():
            component = component.get()
            held_by = component.containingZoneHVACComponent()
            if held_by.is_initialized():
                zone = held_by.get().thermalZone()
                if zone.is_initialized():
                    cooled.add(zone.get().nameString().upper())
                    return True
            containing = component.containingHVACComponent()
            if containing.is_initialized():
                return zone_of(containing.get(), depth + 1)
            loop = component.airLoopHVAC()
            if loop.is_initialized():
                for zone in loop.get().thermalZones():
                    cooled.add(zone.nameString().upper())
                return True          # a loop serving no zone is still placed
            if component.plantLoop().is_initialized():
                # A plant-side coil: the demand it serves is on that loop, and
                # a loop carrying only process or service-water demand reaches
                # no thermal block. Placed, with nothing to attribute.
                return True
        # A DEDICATED OUTDOOR-AIR SYSTEM serves every block of every air loop
        # it feeds, and its coil reaches none of the rungs above: a DOAS
        # cooling coil answered `airLoopHVAC`, `containingZoneHVACComponent`,
        # `containingHVACComponent` AND `plantLoop` all empty, so it came back
        # unplaceable while genuinely cooling both blocks (Sol, `224`).
        doas = _as_doas(obj)
        if doas is not None:
            for loop in doas.airLoops():
                for zone in loop.thermalZones():
                    cooled.add(zone.nameString().upper())
            return True
        # A plain outdoor-air system belongs to one loop, or sits inside a
        # DOAS, which its own sources reach.
        oa_system = _as_oa_system(obj)
        if oa_system is not None:
            loop = oa_system.airLoopHVAC()
            if loop.is_initialized():
                for zone in loop.get().thermalZones():
                    cooled.add(zone.nameString().upper())
                return True

        # An OA-STREAM component, by membership. This runs before the
        # bounded walk below because it does not depend on distance: a
        # cooling coil with a fan and a heating coil inboard of it sits
        # twelve hops from its own outdoor-air system (Fable, `228`).
        # Containment is silent: ask what POINTS AT this object.
        for source in obj.sources():
            as_model_object = source.to_ModelObject()
            if not as_model_object.is_initialized():
                continue
            if zone_of(as_model_object.get(), depth + 1):
                return True
        return False

    for obj in model.modelObjects():
        type_name = obj.iddObjectType().valueName()
        if not _COOLING_PATTERN.search(type_name):
            continue
        # A chiller or district-cooling node is UPSTREAM of whatever serves a
        # block: the coil drawing on that loop is itself matched here and
        # resolves to its own blocks, so attributing the plant as well would
        # mark every block on the loop's demand side as cooled, including
        # blocks served only for process or service-water demand.
        if _UPSTREAM_COOLING_PATTERN.search(type_name):
            continue
        if zone_of(obj):
            continue
        # DETACHED is not UNRESOLVED. An object connected to no HVAC
        # topology at all provides cooling to no thermal block, so (4)(a)'s
        # scope is known: this object is not in it. Calling it unplaceable
        # made the sentence's applicability unknown for a model whose only
        # fault is a stray object (Sol, `224`) — it may deserve an
        # input-model warning, which is a different concern from this one.
        #
        # The test is whether the object's reference graph reaches any
        # topology at all. A detached coil's graph holds nothing but its own
        # connections and nodes; a DOAS coil's reaches the outdoor-air
        # system at depth four and the DOAS at depth five.
        if _reaches_no_topology(obj):
            continue
        unresolved.append(obj.nameString())

    # An ideal-loads block is cooled by definition, and the flag lives on the
    # zone rather than on any object the walk above would reach.
    for zone in model.getThermalZones():
        if zone.useIdealAirLoads():
            cooled.add(zone.nameString().upper())

    return ({zone.nameString().upper():
             zone.nameString().upper() in cooled
             for zone in model.getThermalZones()},
            sorted(unresolved))


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
                    hvac.prepare_for_resizing(model, audit=audit, code=ruleset.id)
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

        hard = set()
        if bumps["proposed"]["heating"] or bumps["proposed"]["cooling"]:
            hard.update(_hard_sized_capacities(proposed))
        if bumps["reference"]["heating"]:
            hard.update(_hard_sized_capacities(reference))
        cause = ("hard-sized capacities sizing factors cannot reach: "
                 + _hard_sized_phrase(sorted(hard))) if hard else (
                 "no hard-sized capacity was detected among " + _HARD_SIZED_SCOPE
                 + ", so a hard-sized staged coil, equipment the building "
                 "does not have, or a limit sizing factors do not move")
        audit.warn(
            "compliance",
            f"capacity iteration {iteration} produced no unmet-hours "
            "improvement — the failing equipment is not responding to "
            f"sizing-factor increases ({cause}); stopping",
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
            target=", ".join(spaces), article="4.2.1.6.(1)(b)",
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
