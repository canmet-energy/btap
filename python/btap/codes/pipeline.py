"""btap.codes.pipeline — the code-family-NEUTRAL determination lifecycle
(multi-edition plan, Stage 9a).

This module owns the mechanics every performance-path determination shares
whatever code it is run against: the run context (:class:`_Run`), phase
ordering, the ``run_dir`` layout, the neutral input gate, coverage emission,
``report.json``/``audit.json``/``audit.txt`` and the failure flush.

Everything a CODE says — which space types are admissible, where the heating
degree-days come from, what a reference building is, whether there IS a
reference building — belongs to a code family behind :class:`CodePath`. The
family is resolved from the edition's manifest (``"path"``) through
``Ruleset.path()``; this module never imports one, and an import contract
keeps it that way, so a second family (OBC SB-10, BC Step Code) arrives as a
new package plus a manifest line rather than as a branch here.

The evidence-bearing names live in :mod:`btap.codes.compliance` (the
article-coverage pointers cite them); this module calls them, so the
pointers name code that runs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Protocol

from btap.audit import AuditLog, emit_coverage
from btap.codes import compliance, resolve
from btap.simulation import runner


@dataclass
class Verdict:
    """What a code family's :meth:`CodePath.determine` produces.

    Deliberately small and regime-agnostic: ``compliant`` is the determination
    itself (``None`` when the run cannot determine — a sizing-only or
    shortened run), and ``report`` is the report dict the regime filled in.
    A reference-building regime (NECB Part 8) fills in ``proposed`` and
    ``reference`` sections; an absolute-metric regime (a step code's
    TEDI/MEUI/airtightness thresholds) fills in whatever its thresholds
    produce and never builds a reference at all. The report renders what is
    present rather than what a reference-building regime happens to emit."""

    compliant: bool | None = None
    report: dict | None = None


class CodePath(Protocol):
    """One code family's implementation of the determination lifecycle.

    The pipeline calls these hooks in phase order and owns everything between
    them (the EnergyPlus calls, the run directory, the outputs). An
    implementation is a MODULE — the same shape as the edition-bound
    behaviour modules the manifests already name — resolved by
    ``Ruleset.path()``; the hooks therefore take the run (which carries the
    :class:`btap.codes.Ruleset`) instead of ``self``, and
    :meth:`citations` takes the ruleset explicitly for the same reason.

    NECB's implementation is :mod:`btap.codes.necb.path`."""

    def validate(self, run) -> None:
        """Everything this code requires of an input model before any
        transform runs (NECB: the bare-geometry on-ramp, the simulate-ability
        gate and the space-type pre-flight)."""

    def climate(self, run) -> dict:
        """The climate facts the rules need, ``{'hdd': ...}`` (NECB: Table
        C-1 by nearest city, or the ``.stat`` file)."""

    def prepare_annual(self, run) -> None:
        """Anything that must be set up BEFORE the proposed's annual run —
        output variables the determination will read back (NECB: the
        per-equipment heating variables the 8.4.4.13.(2)(g) auxiliary-fuel
        election consumes)."""

    def consume_annual(self, run) -> None:
        """Join the proposed annual results into the run's own state (NECB:
        the heating-election inventory)."""

    def determine(self, run) -> Verdict:
        """The determination itself (NECB: build the reference, size it,
        compare; or, on the archetype-EUI path, compare against the target).
        Full compliance does NOT imply a reference building."""

    def citations(self, ruleset) -> dict:
        """This edition's article map, by the stable keys the rules cite —
        the article numbers a report renders next to each finding."""

    def report_sections(self, run) -> list:
        """The report sections this regime produced, in render order."""

    def alternate_path(self, model, name, **options):
        """Run a compliance path that is NOT the standard lifecycle above.

        Some regimes offer a second path whose phase sequence genuinely
        differs (NECB 2025's 8.4.4 archetype-EUI path builds and simulates no
        reference building and validates a different set of inputs). The
        pipeline does not know the vocabulary of paths a family offers: it
        hands over any ``path=`` other than ``'reference'`` and the family
        refuses a name it does not implement."""


@dataclass
class _Run:
    """One determination's context: the option dict plus the mutable state the
    pipeline phases and the code family's hooks hand each other (internal —
    phases read run.opts and write the stateful slots)."""
    opts: dict = None
    proposed: object = None
    reference: object = None
    report: dict = None
    audit: object = None
    hdd: object = None
    proposed_annual_data: dict = None
    compliant: bool | None = None
    #: The edition this run is determined against — built ONCE here and reused
    #: by every phase that asks it for an edition-specific behaviour.
    ruleset: object = None
    #: The code family's :class:`CodePath`, resolved from the edition's
    #: manifest. The pipeline calls it; it never imports one.
    path: object = None
    #: Scratch space for the family's own hooks to hand each other state
    #: across the phases the pipeline owns in between (NECB: the heat-pump
    #: inventory taken before the proposed's annual run and joined after it).
    #: Deliberately the family's, never read by the pipeline.
    state: dict = field(default_factory=dict)


def run(model, *, code="necb2020", weather=None, building=None,
        hdd=None, run_dir, simulate="annual", run_period=None,
        costing=False, city=None, province_state=None,
        costs_csv=None, thermal_bridging=None,
        actual_roof_absorptance_used=False,
        max_capacity_iterations=3, capacity_step=1.25,
        necb_loads=None, reference_daylighting=True,
        path="reference", archetypes_map=None,
        process_loads_kwh=0.0, eui_supplement=None,
        report_html=False, report_options=None, audit=None):
    """The determination lifecycle. The public entry point (with the
    documented signature) is
    :func:`btap.codes.compliance.performance_compliance`; the phases below
    are the neutral mechanics, and every code-specific step is a
    :class:`CodePath` hook on the family the edition's manifest names."""
    weather = weather or {}
    report_options = report_options or {}
    simulate = str(simulate)
    ruleset = resolve(code)
    code_path = ruleset.path()
    if str(path) != "reference":
        # A path whose phase sequence is not this one belongs to the family
        # (NECB 2025's archetype-EUI path: no reference building, a different
        # input gate, its own report skeleton). Handed over BEFORE the audit
        # or the run directory exists, so a refusal costs nothing.
        return code_path.alternate_path(
            model, str(path), ruleset=ruleset, weather=weather, hdd=hdd,
            run_dir=run_dir, simulate=simulate, run_period=run_period,
            archetypes_map=archetypes_map,
            process_loads_kwh=process_loads_kwh, costing=costing, city=city,
            province_state=province_state, costs_csv=costs_csv,
            necb_loads=necb_loads, report_html=report_html,
            report_options=report_options, audit=audit)
    audit = audit if audit is not None else AuditLog()
    os.makedirs(run_dir, exist_ok=True)
    # The run context: options + the mutable state the phases hand each
    # other. `report` starts EMPTY and is rebound after the proposed sizing
    # (below) — a failure flush before that point deliberately writes the
    # empty dict (pinned by test_failed_run_still_writes_audit_trail).
    opts = {"model": model, "code": ruleset.id, "weather": weather,
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
    state = _Run(opts=opts, report={}, audit=audit, hdd=hdd, ruleset=ruleset,
                 path=code_path)
    try:
        compliance._load_and_validate(state)  # 1. input model in, gates passed
        _attach_weather_and_hdd(state)   # 2. weather + the family's climate
        _size_proposed(state)            # 3. proposed sizing run
        state.report = _base_report(state)  # (the report rebinding — see above)
        _proposed_annual(state)          # 4. proposed annual (D-52: BEFORE the determination)
        verdict = state.path.determine(state)  # 5. the family's determination
        state.compliant = verdict.compliant
        state.report = verdict.report
        return _finalize(state)          # 6. coverage + outputs -> ComplianceResult
    except Exception as e:
        _flush_on_failure(str(run_dir), state.report, audit, e)
        raise


# 2. attach weather, then ask the code family for the climate the rules need
def _attach_weather_and_hdd(run):
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

    # An explicit hdd= always wins; otherwise the CODE says where the
    # heating degree-days come from (NECB: Table C-1 from the EPW site, then
    # the .stat file).
    if run.hdd is None:
        run.hdd = run.path.climate(run).get("hdd")
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
    return {"edition": run.ruleset.edition, "code": run.ruleset.id,
            "code_label": run.ruleset.label, "hdd": run.hdd,
            "simulate": run.opts["simulate"], "proposed": {}, "reference": {}}


# 4. the proposed ANNUAL run — BEFORE the determination (D-52). The proposed
# annual depends on nothing downstream (the reference, where a regime builds
# one, is a clone; every later use of the proposed is read-only), so running
# it here costs zero extra simulations and hands the determination the annual
# data it needs. The EnergyPlus call is the pipeline's; what has to be
# requested before it and joined after it is the family's (NECB: the
# per-equipment heating variables for the 8.4.4.13.(2)(g) auxiliary-fuel
# election).
def _proposed_annual(run):
    opts = run.opts
    if opts["simulate"] != "annual":
        return

    run.path.prepare_annual(run)
    compliance._run_annual(run.proposed,
                           os.path.join(opts["run_dir"], "proposed_annual"),
                           opts["run_period"], run.report["proposed"],
                           audit=run.audit)
    run.path.consume_annual(run)


# 11. emit article coverage; write report.json / audit.json / audit.txt
#     (+ the optional HTML compliance report). Shared by both compliance
#     paths (the EUI path has no reference model).
def _finalize(run):
    from btap.codes import report as report_renderer

    opts = run.opts
    report = run.report
    audit = run.audit
    _emit_article_coverage(run.ruleset, audit)
    report["compliant"] = run.compliant
    report["warnings"] = [w["action"] for w in audit.warnings]
    _write_outputs(opts["run_dir"], report, audit)
    result = compliance.ComplianceResult(proposed_model=run.proposed,
                              reference_model=run.reference, report=report,
                              audit=audit, compliant=run.compliant,
                              run_dir=opts["run_dir"])
    if opts["report_html"]:
        report_renderer.write_html(
            result, os.path.join(opts["run_dir"], "compliance_report.html"),
            opts["report_options"])
    return result


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
        raise compliance.PreflightError(
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
        raise compliance.PreflightError(
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
        raise compliance.PreflightError(
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


def _emit_article_coverage(ruleset, audit):
    """Completeness accounting for the umbrella's OWN manifest. Resolution is
    the edition's (its manifest names the umbrella rule file); the emission is
    the family's shared one (btap.audit emit_coverage, the same call the five
    domain packages make): every declared article lands in the audit with its
    status, partial/not_implemented warn — EXCEPT entries flagged gap_owner:
    "modeller", which emit as info scope notes (D-09). Emitted at the end of
    the happy path only — a crash flush must not assert coverage."""
    emit_coverage(ruleset.rules("umbrella")["article_coverage"], audit)


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
