"""The neutral entry point and the evidence-bearing phase functions of the
code-compliance determination (multi-edition plan, Stage 9a).

Three modules make up what used to be one file:

* **this module** — the public entry point ``performance_compliance`` and the
  phase functions the article-coverage pointers name
  (``necb_rules.json``/``reference_rules.json`` cite
  ``compliance.py#performance_compliance``, ``#_load_and_validate``,
  ``#_run_annual``, ``#_build_reference``, ``#_evaluate``,
  ``#_evaluate_unmet``). Every one of them is on the EXECUTED call path: the
  three that delegate to a code family do so through the registry-resolved
  :class:`btap.codes.pipeline.CodePath`, never as a stub that resolves the
  pointer without running.
* :mod:`btap.codes.pipeline` — the code-family-NEUTRAL lifecycle: the run
  context, phase ordering, ``run_dir`` layout, output writing and the
  failure flush.
* :mod:`btap.codes.necb.path` — the NECB Part 8 implementation of the
  ``CodePath`` hooks (space-type pre-flight, Table C-1 HDD, the heat-pump
  election, the reference building and the 8.4.1.2 verdicts).

Nothing here imports a code family: the family is reached only through
``Ruleset.path()``, which is what lets a second family (OBC SB-10, BC Step
Code) arrive without touching this file."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from btap._compat import opt, ruby_round
from btap.codes import resolve
from btap.simulation import runner


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


def performance_compliance(model, *, code="necb2020", weather=None, building=None,
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
    :param code: the code id — 'necb2020' (default) or 'necb2025'
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
    # The lifecycle is btap.codes.pipeline's; this module keeps the public
    # name and the phase functions the coverage pointers cite. Imported
    # lazily (as btap.codes.performance_compliance does) so importing this
    # module stays cheap and the two-way relationship between the facade and
    # the pipeline never runs at import time.
    from btap.codes import pipeline

    return pipeline.run(
        model, code=code, weather=weather, building=building, hdd=hdd,
        run_dir=run_dir, simulate=simulate, run_period=run_period,
        costing=costing, city=city, province_state=province_state,
        costs_csv=costs_csv, thermal_bridging=thermal_bridging,
        actual_roof_absorptance_used=actual_roof_absorptance_used,
        max_capacity_iterations=max_capacity_iterations,
        capacity_step=capacity_step, necb_loads=necb_loads,
        reference_daylighting=reference_daylighting, path=path,
        archetypes_map=archetypes_map, process_loads_kwh=process_loads_kwh,
        eui_supplement=eui_supplement, report_html=report_html,
        report_options=report_options, audit=audit)


# 1. load the input model, then run the code family's own input gates
def _load_and_validate(run):
    """Phase 1 — the neutral half: read (or clone) the caller's model under
    the 'input model' stamp. Everything a CODE FAMILY requires of an input
    before any transform runs — for NECB the bare-geometry on-ramp, the
    simulate-ability gate and the space-type pre-flight — is the family's
    ``validate`` hook, run here so 8.4.3.1's "the proposed is simulated as
    supplied" evidence still points at this function."""
    with run.audit.with_building("input model"):
        run.proposed = _load_model(run.opts["model"], audit=run.audit)
    run.path.validate(run)


# 5. the reference building — the code family builds it (a regime with no
#    reference building, e.g. an absolute-metric step code, builds none)
def _build_reference(run):
    """Phase 5 — the reference-building transforms, delegated to the family.

    A FORWARDING function, deliberately: the article-coverage pointers cite
    ``compliance.py#_build_reference`` and this is the function the
    determination actually calls (``btap.codes.necb.path.determine``), so the
    evidence keeps naming code that runs. The transforms themselves are the
    family's — NECB's are ``btap/codes/necb/path.py#build_reference``."""
    return run.path.build_reference(run)


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


def _evaluate(report, ruleset, run_period, audit):
    """The energy and unmet-hours verdicts, delegated to the code family.

    Forwarding function on the executed call path (see ``_build_reference``):
    NECB 8.4.1.2.(2)-(4) is ``btap/codes/necb/path.py#evaluate``."""
    return ruleset.path().evaluate(report, ruleset, run_period, audit)


def _evaluate_unmet(report, ruleset, audit):
    """The unmet-hours verdicts, delegated to the code family.

    Forwarding function on the executed call path (see ``_build_reference``):
    NECB 8.4.1.2.(3)-(5) is ``btap/codes/necb/path.py#evaluate_unmet``."""
    return ruleset.path().evaluate_unmet(report, ruleset, audit)


def eui_supplement_verdict(proposed, options, hdd, report, run_dir, run_period,
                           code, audit):
    """The 8.4.4 supplement verdict on a reference-path run. Returns the
    report['eui_path'] dict — 'computed': False with 'reason'/'mismatches',
    or 'computed': True with 'bet_kwh', 'compliant', 'basis', 'lines' and the
    energy-tier fields. See the call site for the check-first contract."""
    ruleset = resolve(code)
    return ruleset.path().eui_supplement_verdict(
        proposed, options, hdd, report, run_dir, run_period, ruleset, audit)


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
