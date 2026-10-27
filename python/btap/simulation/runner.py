"""Simulation execution, backend-agnostic (port of btap-simulation's
runner.rb): attach weather, prepare the run directory (sizing flags, run
period, in.osm + in.osw), delegate the EnergyPlus invocation to a Backend,
and parse results from the attached SQL.

Port renames (D-79 protocol): run_energyplus! -> run_energyplus,
clean_run? -> is_clean_run, attach_weather! -> attach_weather,
request_run_period_variables! -> request_run_period_variables. The
openstudio_cli probe is gone — the Python Local backend runs the provisioned
engine, not the CLI.
"""

from __future__ import annotations

from pathlib import Path

from btap._compat import opt, ruby_round

_default_backend = None


def default_backend():
    """The process-wide default backend. The umbrella calls run_energyplus at
    ~8 sites without a backend argument — this is how a --backend flag
    reaches them all without threading a parameter through every phase. Set
    once at startup; a per-call backend= still wins. Not thread-safe by
    design; forked children set their own."""
    global _default_backend
    if _default_backend is None:
        from btap.simulation.backends import Local
        _default_backend = Local()
    return _default_backend


def set_default_backend(backend):
    global _default_backend
    _default_backend = backend


def attach_weather(model, *, epw, ddy, audit=None):
    """Attach an EPW + its design days (required before any sizing run).

    Design days are REPLACED, not appended (a model already carrying design
    days would otherwise size on duplicates), and filtered to the 99.6%
    heating / 0.4% cooling extremes — the legacy convention. A full DDY
    carries ~40 entries including monthly and shoulder-season cooling days;
    sizing plant equipment on those breaks E+'s cooling-tower UA autosizing.
    """
    import re

    import openstudio

    # Absolute path: the model's WeatherFile object stores this string and it
    # is later resolved from the RUN directory, not the caller's.
    epw_file = openstudio.EpwFile(openstudio.path(str(Path(epw).resolve())))
    openstudio.model.WeatherFile.setWeatherFile(model, epw_file)
    workspace = opt(openstudio.energyplus.loadAndTranslateIdf(str(ddy)))
    if workspace is None:
        raise ValueError(f"could not parse design days from {ddy}")

    discarded = 0
    for dd in model.getDesignDays():
        dd.remove()
        discarded += 1
    # The legacy default list, ANCHORED ON `Ann`. Without the anchor these
    # patterns match on the condition substring alone and never constrain the
    # Ann/JUN/JUL token, so a DDY that spells its monthly days the same way
    # after the period marker retained all of them — the precise hazard the
    # comment below was written to prevent. Measured over every `.ddy` on
    # disk: 16 CZ2010 files (vendored gem weather) kept 8 of 9 days, SIX of
    # them monthly; CWEC escaped only by a coincidence of spelling, since it
    # writes `.4%`+`DB=>MWB` while the `0.4%` and `MCWB` patterns each miss it
    # by one character. So the exclusion was an artefact of two naming
    # mismatches rather than an enforced property (Fable, PR #77).
    #
    # NOT a bare /.4%/, for the same reason: a January cooling day's ~2C
    # wet-bulb breaks the tower UA solve. Ruby's =~ is a SEARCH: re.search,
    # never match.
    keep = [r"\bAnn\b.*Htg 99.6. Condns DB",
            r"\bAnn\b.*Clg .4% Condns DB=>MWB",
            r"\bAnn\b.*Clg 0.4% Condns DB=>MCWB",
            r"\bAnn\b.*Clg .4. Condns WB=>MDB"]
    all_days = list(workspace.getDesignDays())
    extremes = [dd for dd in all_days
                if any(re.search(p, dd.nameString()) for p in keep)]
    fell_back = not extremes
    if fell_back:  # odd DDY: keep everything rather than none
        extremes = all_days
    # Classified AFTER the fallback substitution, so the counts describe what
    # was actually ATTACHED rather than what matched — on the fallback the
    # whole file is attached and may well carry both kinds. Computing them
    # before the substitution made every fallback look like a partial match,
    # which the existing fallback test caught.
    kept_heating = sum(1 for dd in extremes
                       if re.search(r"Htg", dd.nameString()))
    kept_cooling = sum(1 for dd in extremes
                       if re.search(r"Clg", dd.nameString()))
    for dd in extremes:
        model.addObject(dd.clone())
    if len(model.getDesignDays()) == 0:
        raise ValueError(f"no design days found in {ddy}")
    # D-25 is a modelling ASSUMPTION a reader of the report cannot otherwise
    # see: a modeller who supplied their own design days would reasonably
    # expect them to survive, and they do not. The entry states the inputs it
    # is evidenced by (how many were discarded, found and kept) and the
    # consequence (which conditions size the building), because a row in the
    # report's "Decisions and assumptions applied" that cannot be evidenced
    # from its own inputs is a narrative rather than a record.
    if audit is not None:
        # The action MUST branch on the fallback, because the fallback keeps the
        # whole DDY. An unconditional "filtered to the annual extremes" was
        # false exactly when `kept_all_as_fallback` is true — the entry carried
        # evidence that refuted its own claim, which is worse than saying
        # nothing, because it is an AHJ-facing modelling assumption (Sol, `084`:
        # reproduced with a DDY whose three extreme days were renamed, giving
        # 78 kept and the text still asserting 99.6%/0.4% only).
        # THREE states, not two. "replaced, not appended" leads every one of
        # them: it holds in all three and it is the single fact a modeller who
        # supplied their own design days is most likely to have wrong — in the
        # fallback especially, where "the FULL file was retained" otherwise
        # invites the reading that their days survived (Fable, PR #77 L3).
        # The THIRD state is a partial match of the FILTER — never the
        # fallback, which is its own state and keeps everything.
        partial = not fell_back and not (kept_heating and kept_cooling)
        if fell_back:
            action = ("design days replaced, not appended; no annual-extreme "
                      "design day matched this DDY, so the FULL file was "
                      "retained for sizing — the building is sized on every "
                      "design day in the file, not on the 99.6% heating and "
                      "0.4% cooling days alone")
        elif partial:
            missing = "cooling" if not kept_cooling else "heating"
            action = ("design days replaced, not appended, and filtered to the "
                      f"annual extremes, but NO {missing.upper()} design day "
                      "matched this DDY — the building is sized without an "
                      f"annual {missing} design condition, so {missing} "
                      "equipment autosizes against no design day of its kind")
        else:
            action = ("design days replaced, not appended, and filtered to the "
                      "annual extremes — the building is sized on the 99.6% "
                      "heating and 0.4% cooling days only")
        inputs = {"design_days_discarded": discarded,
                  "design_days_in_file": len(all_days),
                  "design_days_kept": len(extremes),
                  # Per-kind counts, so all three states are EVIDENCED rather
                  # than asserted: `design_days_kept` alone does not say of
                  # which kind, which is what let the partial state claim a
                  # cooling day it did not have.
                  "design_days_kept_heating": kept_heating,
                  "design_days_kept_cooling": kept_cooling,
                  "kept_all_as_fallback": fell_back}
        audit.decision(
            "climate", action, target=Path(ddy).name, inputs=inputs,
            value=", ".join(sorted(dd.nameString() for dd in extremes)),
            ruling="D-25")
        # A missing design condition of either kind is a WARNING, not merely a
        # recorded decision: the package contract says warnings are never
        # silent, and this one has a sizing consequence rather than only a
        # disclosure one.
        if partial:
            audit.warn(
                "climate",
                f"no annual {missing} design day matched {Path(ddy).name} — "
                f"{missing} equipment will autosize with no annual {missing} "
                "design condition",
                target=Path(ddy).name,
                inputs={"design_days_kept_heating": kept_heating,
                        "design_days_kept_cooling": kept_cooling},
                ruling="D-25")
    return model


def run_energyplus(model, run_dir, *, sizing_only=False, run_period=None, backend=None):
    """Prepare the run directory, run EnergyPlus via the chosen backend, and
    attach the result SQL to the model. Returns the run output directory
    (containing eplusout.err / eplusout.sql).

    run_period: {'begin_month':, 'begin_day':, 'end_month':, 'end_day':} —
    override for the weather run (tests use one week; compliance is annual).
    """
    import openstudio

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    sim = model.getSimulationControl()
    sim.setDoZoneSizingCalculation(True)
    sim.setDoSystemSizingCalculation(True)
    sim.setDoPlantSizingCalculation(True)
    sim.setRunSimulationforSizingPeriods(True)
    sim.setRunSimulationforWeatherFileRunPeriods(not sizing_only)
    if not sizing_only and run_period:
        rp = model.getRunPeriod()
        rp.setBeginMonth(run_period["begin_month"])
        rp.setBeginDayOfMonth(run_period["begin_day"])
        rp.setEndMonth(run_period["end_month"])
        rp.setEndDayOfMonth(run_period["end_day"])
    model.save(openstudio.path(str(run_dir / "in.osm")), True)
    # in.osw kept for run-dir artifact parity with the Ruby gem (side-by-side
    # debugging of Leg-B corpus runs); the Python Local backend itself reads
    # only in.osm.
    osw = openstudio.WorkflowJSON()
    osw.setSeedFile(openstudio.path(str((run_dir / "in.osm").resolve())))
    osw.saveAs(openstudio.path(str(run_dir / "in.osw")))

    (backend or default_backend()).execute(str(run_dir))

    model.setSqlFile(openstudio.SqlFile(openstudio.path(str(run_dir / "run" / "eplusout.sql"))))
    return str(run_dir / "run")


def is_clean_run(run_out_dir) -> bool:
    """Completed with no Fatal and no Severe errors."""
    import re

    err = (Path(run_out_dir) / "eplusout.err").read_text(encoding="utf-8", errors="replace")
    return ("EnergyPlus Completed Successfully" in err
            and not re.search(r"\*\*\s*Fatal\s*\*\*", err)
            and not re.search(r"\*\* Severe  \*\*", err))


GJ_TO_KWH = 277.777778


def energy_results(model) -> dict:
    """Annual (or run-period) site energy results from an attached SQL:
    kWh totals + end-use breakdown + floor area. Same keys, same rounding
    (ruby_round — these values land in report.json, which Leg B diffs)."""
    sql = opt(model.sqlFile())
    if sql is None:
        raise RuntimeError("no SQL attached — run run_energyplus first")

    total_gj = opt(sql.totalSiteEnergy())
    results = {
        "total_site_kwh": ruby_round(total_gj * GJ_TO_KWH, 1) if total_gj is not None else None,
        "electricity_kwh": _scaled(sql.electricityTotalEndUses()),
        "natural_gas_kwh": _scaled(sql.naturalGasTotalEndUses()),
        # Purchased heating in either medium: from OpenStudio 3.7 the combined
        # accessor is water PLUS steam (SqlFile_Impl::districtHeatingTotalEndUses,
        # addTwoOptionalDoubles), so it must stay first; the water-only one is
        # the fallback for an SDK that lacks it (D-89, sixth amendment).
        "district_heating_kwh": _district(sql, ["districtHeatingTotalEndUses",
                                                "districtHeatingWaterTotalEndUses"]),
        "district_cooling_kwh": _district(sql, ["districtCoolingTotalEndUses"]),
        "end_uses_kwh": {
            "heating": _end_use(sql, "Heating"),
            "cooling": _end_use(sql, "Cooling"),
            "fans": _end_use(sql, "Fans"),
            "pumps": _end_use(sql, "Pumps"),
            "interior_lighting": _end_use(sql, "InteriorLighting"),
            "interior_equipment": _end_use(sql, "InteriorEquipment"),
            "water_systems": _end_use(sql, "WaterSystems"),
        },
    }
    area = model.getBuilding().floorArea()
    results["floor_area_m2"] = ruby_round(area, 1)
    if results["total_site_kwh"] is not None and area > 0:
        results["eui_kwh_per_m2"] = ruby_round(results["total_site_kwh"] / area, 1)
    return results


def unmet_occupied_hours(model) -> dict:
    """Facility 'Time Setpoint Not Met During Occupied' hours (SystemSummary).
    Values are RAW SQL floats, never rounded (the Leg-B spec carries a
    tolerance for exactly this field)."""
    sql = opt(model.sqlFile())
    if sql is None:
        return {"heating": None, "cooling": None}

    def query(column):
        return opt(sql.execAndReturnFirstDouble(
            "SELECT Value FROM TabularDataWithStrings WHERE ReportName='SystemSummary' "
            f"AND TableName='Time Setpoint Not Met' AND RowName='Facility' AND ColumnName='{column}'"
        ))

    return {"heating": query("During Occupied Heating"),
            "cooling": query("During Occupied Cooling")}


def zone_unmet_occupied_hours(model) -> dict:
    """Per-zone 'Time Setpoint Not Met During Occupied' hours — the
    per-thermal-block resolution behind NECB 8.4.1.2.(3)/(4). Row names are
    EnergyPlus UPPER-CASED zone names; match case-insensitively. Empty dict
    when no SQL is attached."""
    sql = opt(model.sqlFile())
    if sql is None:
        return {}

    zones: dict = {}
    for metric, column in (("heating", "During Occupied Heating"),
                           ("cooling", "During Occupied Cooling")):
        rows = opt(sql.execAndReturnVectorOfString(
            "SELECT RowName || '|' || Value FROM TabularDataWithStrings "
            "WHERE ReportName='SystemSummary' AND TableName='Time Setpoint Not Met' "
            f"AND ColumnName='{column}' AND RowName <> 'Facility'"
        ))
        if rows is None:
            continue
        for line in rows:
            name, _, value = line.rpartition("|")
            if not name:
                continue
            zones.setdefault(name, {})[metric] = _to_f(value)
    return zones


def request_run_period_variables(model, names):
    """Request output variables at RunPeriod frequency (key '*'),
    idempotently — the NECB 8.4.4.13.(2)(g) auxiliary-fuel election (D-52)
    needs per-equipment heating energy from the proposed annual run."""
    import openstudio

    # The FREQUENCY is part of the identity. Keyed on name alone, this
    # skipped its request whenever an hourly one existed for the same
    # variable, so the RunPeriod sum the D-52 election needs was never
    # reported (Fable, `323` 5.2).
    existing = {(v.keyValue(), v.variableName(),
                 v.reportingFrequency().lower())
                for v in model.getOutputVariables()}
    for name in names:
        if ("*", name, "runperiod") in existing:
            continue
        variable = openstudio.model.OutputVariable(name, model)
        variable.setKeyValue("*")
        variable.setReportingFrequency("RunPeriod")


def run_period_sums(model, variable_name) -> dict:
    """Sum a reported variable per KeyValue over the WEATHER run period(s)
    only. EnvironmentType = 3 filters out design days — a shared DDY can
    carry dozens, and an unfiltered sum silently mixes them in (the D-56
    trap). Keys are EnergyPlus UPPER-CASED object names; values joules.

    `ReportingFrequency = 'Run Period'` (with the space, as this build writes
    it) is the SECOND filter and it was missing. Without it, a model that also
    carries an HOURLY request for the same variable name had its 8760 hourly
    rows added to the RunPeriod row: measured at exactly 2x — 152.62 MWh
    against a true 76.31 for `Boiler Heating Energy` (Fable, `323` 5.3).
    Nothing could trigger that before `request_hourly_meters` existed, which
    is why the reader survived; `_heating_election_data`
    (`codes/necb/path.py`) is the consumer, so a research caller who requested
    heating energy hourly and then ran `performance_compliance` would have
    doubled the D-52 auxiliary-fuel election's per-equipment sums.
    """
    sql = opt(model.sqlFile())
    if sql is None:
        return {}

    escaped = _sql_name(variable_name)
    rows = opt(sql.execAndReturnVectorOfString(
        "SELECT d.KeyValue || '|' || SUM(r.Value) FROM ReportData r "
        "JOIN ReportDataDictionary d ON r.ReportDataDictionaryIndex = d.ReportDataDictionaryIndex "
        "JOIN Time t ON r.TimeIndex = t.TimeIndex "
        f"WHERE d.Name = '{escaped}' "
        "AND d.ReportingFrequency = 'Run Period' "
        "AND t.EnvironmentPeriodIndex IN "
        "(SELECT EnvironmentPeriodIndex FROM EnvironmentPeriods WHERE EnvironmentType = 3) "
        "GROUP BY d.KeyValue"
    ))
    if rows is None:
        return {}
    result = {}
    for line in rows:
        name, _, value = line.rpartition("|")
        result[name] = _to_f(value)
    return result


#: TIER 1 of the hourly request — METERS only, and the cheap tier. Measured at
#: roughly 0.2 MiB of SQL per hourly series per year, so this whole list costs
#: about 5x a baseline run's SQL (3.39 MiB against 0.72 on the reference
#: fixture). It covers four distinct research questions and is the list to
#: reach for unless one of them is not being asked:
#:
#: - LOAD-REDUCTION measures read the per-end-use series (lights, fans, pumps,
#:   equipment) — a reduction has to be attributable to something;
#: - PEAK reduction and the load duration curve read `Electricity:Facility`;
#: - COGENERATION resilience reads heat AND power on one index, because a CHP
#:   unit is heat-led or electric-led and whether it carries critical load
#:   through an outage depends on the hour-by-hour ratio, not on either peak.
#:
#: DISTRICT ENERGY is deliberately NOT served from here — see
#: `hourly_hot_water_plant_heat`, because no meter in this list is the building's
#: heat load.
HOURLY_METERS = (
    "Electricity:Facility",
    "InteriorLights:Electricity",
    "ExteriorLights:Electricity",
    "InteriorEquipment:Electricity",
    "Heating:Electricity",
    "Cooling:Electricity",
    "Fans:Electricity",
    "Pumps:Electricity",
    "HeatRejection:Electricity",
    "WaterSystems:Electricity",
    "NaturalGas:Facility",
    "Heating:NaturalGas",
    "WaterSystems:NaturalGas",
)

#: TIER 2 — a few per-zone variables, for a free-float outage case and
#: unmet-hours. Per-zone, so the cost scales with zone count.
HOURLY_ZONE_VARIABLES = (
    "Zone Mean Air Temperature",
    "Zone Heating Setpoint Not Met Time",
    "Zone Cooling Setpoint Not Met Time",
    "Zone Heating Setpoint Not Met While Occupied Time",
    "Zone Cooling Setpoint Not Met While Occupied Time",
)

#: The plant-side heat variable. ONE series per boiler, and the right one for
#: district energy — see `hourly_hot_water_plant_heat`.
BOILER_HEAT_VARIABLE = "Boiler Heating Energy"

#: Its fuel counterpart, so ONE model read two ways answers both the
#: district-energy case and the on-site-boiler case.
BOILER_FUEL_VARIABLE = "Boiler NaturalGas Energy"


def request_hourly_meters(model, meters=HOURLY_METERS):
    """Request `Output:Meter` at hourly frequency, idempotently.

    Mirrors `request_run_period_variables`: existing requests for the same
    name are left alone, so calling this twice is harmless.

    HOURLY OUTPUT IS OFF BY DEFAULT and this is the opt-in. The cost is
    measured and tiered — see `HOURLY_METERS` for tier 1 and
    `request_hourly_zone_variables` for tier 2. The expensive tier is the zone
    air heat BALANCE decomposition (seven variables plus infiltration and
    latent terms), which costs about 63x a baseline run and answers why a load
    is what it is rather than what it is; nothing here requests it.
    """
    import openstudio

    # ONE METER PER NAME, UPGRADED IN PLACE. Two `OutputMeter` objects with
    # the same name at different frequencies are legal and translate to two
    # IDF lines, but which one is honoured is NOT deterministic: CI's `verify`
    # ran this class on two xdist workers (each re-runs `setUpClass`, so each
    # simulated), and one honoured the hourly request while `gw28` honoured a
    # MONTHLY sibling and read back ZERO HOURS. Adding alongside was the first
    # fix for `323` 5.1 and it only narrowed the window.
    #
    # So a coarser existing request is raised to hourly rather than duplicated.
    # Nothing is lost: an hourly series aggregates to monthly, and the caller's
    # name is still reported.
    #
    # `setMeterFileOnly(False)` is the other half, and it is why this failed on
    # CI and not locally. `OutputMeter` defaults to `meterFileOnly = True`,
    # which translates to `Output:Meter:MeterFileOnly` — the `.mtr` file — and
    # whether that also reaches the SQL `ReportData` the readers use is
    # build-dependent. `Output:Meter` always does.
    added = 0
    for name in meters:
        same = [m for m in model.getOutputMeters() if m.name() == name]
        if same:
            for meter in same:
                if meter.reportingFrequency().lower() != "hourly":
                    meter.setReportingFrequency("Hourly")
                    added += 1
                meter.setMeterFileOnly(False)
            continue
        meter = openstudio.model.OutputMeter(model)
        meter.setName(name)
        meter.setReportingFrequency("Hourly")
        meter.setMeterFileOnly(False)
        added += 1
    return added


def request_hourly_zone_variables(model, names=HOURLY_ZONE_VARIABLES):
    """Tier 2: per-zone hourly variables, idempotently, keyed `'*'`."""
    import openstudio

    existing = {(v.keyValue(), v.variableName(),
                 v.reportingFrequency().lower())
                for v in model.getOutputVariables()}
    added = 0
    for name in names:
        if ("*", name, "hourly") in existing:
            continue
        variable = openstudio.model.OutputVariable(name, model)
        variable.setKeyValue("*")
        variable.setReportingFrequency("Hourly")
        added += 1
    return added


def request_hourly_plant_variables(model,
                                  names=(BOILER_HEAT_VARIABLE,
                                         BOILER_FUEL_VARIABLE)):
    """Request the plant-side heat and fuel variables hourly, idempotently.

    Exists because `request_hourly_meters` cannot cover them — they are
    OutputVariables, not meters — and without this the documented recipe read
    a series nobody had asked for and got `{'index': [], 'values': []}` with
    no signal (Fable, `323` 7).
    """
    import openstudio

    existing = {(v.keyValue(), v.variableName(),
                 v.reportingFrequency().lower())
                for v in model.getOutputVariables()}
    added = 0
    for name in names:
        if ("*", name, "hourly") in existing:
            continue
        variable = openstudio.model.OutputVariable(name, model)
        variable.setKeyValue("*")
        variable.setReportingFrequency("Hourly")
        added += 1
    return added


def _sql_name(name):
    """Validate a reported name for interpolation — REFUSE, do not escape.

    These queries interpolate the name into a SQL literal. An earlier version
    doubled any quote, which is the correct SQLite escape and was also a false
    comfort: it cannot be tested through this API, because a malformed literal
    and a correct query for an absent name BOTH return empty. Dropping the
    escaping passed every test twice (Fable, `323` 1.2, then again after a
    test written specifically for it — the quote in that test was in a zone
    KEY, which arrives through the result rather than the query).

    No EnergyPlus meter or variable name contains a quote, so a quoted name is
    a caller error. Raising makes it visible and makes the guard testable,
    where escaping it returned an empty series indistinguishable from a
    misspelling — the silent-empty failure this whole layer is built to avoid.
    """
    text = str(name)
    # Only the apostrophe can actually break a single-quoted SQLite literal;
    # the double quote and semicolon are refused anyway, because a name
    # carrying either is a caller mistake worth surfacing and refusing costs
    # nothing (Fable, `323` addendum: over-refusing here is harmless).
    if "'" in text or '"' in text or ";" in text:
        raise ValueError(
            f"{name!r} contains a quote or semicolon; no EnergyPlus meter or "
            f"variable name does, and these readers interpolate the name into "
            f"a SQL literal")
    return text


def _requested_hourly(model, name):
    """Did THIS MODEL ask for `name` hourly? Meters and variables alike."""
    text = str(name)
    for meter in model.getOutputMeters():
        if meter.name() == text and meter.reportingFrequency().lower() == "hourly":
            return True
    for variable in model.getOutputVariables():
        if (variable.variableName() == text
                and variable.reportingFrequency().lower() == "hourly"):
            return True
    return False


def _absent(model, name):
    """Decide between a REAL absence and a request that had nothing to report.

    Three conditions used to be indistinguishable, and `energy_above([], t)`
    is a cheerful 0.0, so a misspelling propagated as a number. But the split
    is not simply "absent raises": a meter REQUESTED for an end use the
    building does not have is also absent, because EnergyPlus never creates
    it. `ExteriorLights:Electricity` is in tier 1 and a building with no
    exterior lights never reports it — raising there would make iterating the
    tier impossible.

    The model knows which it is, because it carries its own requests:

    - requested hourly, nothing reported -> an empty series, a real answer
      for a building without that end use;
    - never requested, or misspelt -> `KeyError` naming the catalogue.

    A series that exists and is all zeros never reaches here at all. Found by
    the test written for the boundary (`323` addendum Q2 proposed raising on
    every absence, which this refines).
    """
    if _requested_hourly(model, name):
        return None
    available = hourly_names(model)
    raise KeyError(
        f"{name!r} was never requested hourly on this model. Request it "
        f"before running — `request_hourly_meters`, "
        f"`request_hourly_zone_variables` or "
        f"`request_hourly_plant_variables` — or pick one of the "
        f"{len(available)} names that reported: {available[:12]}"
        + ("…" if len(available) > 12 else ""))


def hourly_names(model):
    """Every name reported HOURLY in the attached SQL, sorted.

    The catalogue an explorer wants, and what `hourly_series` names in its
    error when a name is absent.
    """
    sql = opt(model.sqlFile())
    if sql is None:
        return []
    rows = opt(sql.execAndReturnVectorOfString(
        "SELECT DISTINCT Name FROM ReportDataDictionary "
        "WHERE ReportingFrequency = 'Hourly' ORDER BY Name"))
    return list(rows) if rows else []


def _one_weather_period(sql):
    """Raise unless the run has exactly one weather period.

    The hourly index is `(month, day, hour)` with no year and no environment,
    so two `RunPeriod` objects or a multi-year period make coincident stamps
    collide: `hourly_series` would SUM them into 8760 doubled values and
    `hourly_series_by_key` would return 17520, neither signalling (Fable,
    `323` 1.3). One query is cheaper than a doubled series nobody notices.
    """
    found = opt(sql.execAndReturnFirstInt(
        "SELECT COUNT(*) FROM EnvironmentPeriods WHERE EnvironmentType = 3"))
    if found is not None and found > 1:
        raise RuntimeError(
            f"the hourly readers index on (month, day, hour) and this run has "
            f"{found} weather periods, whose hours would collide — read them "
            f"per period, or run one period at a time")


def _hourly_rows(sql, where):
    """`[(month, day, hour, key, value)]` over the WEATHER run period only.

    EnvironmentType = 3 excludes design days. An unfiltered read is the D-56
    trap and it is not subtle here: on the reference fixture three sizing
    periods inflated an annual total by 1.8%, and the filtered figure matches
    the tabular End Uses row exactly where the unfiltered one does not.
    """
    # FREQUENCY FILTER, and it is load-bearing twice over. The same variable
    # NAME can be reported at two frequencies in one run — the NECB
    # 8.4.4.13.(2)(g) election requests RunPeriod variables through
    # `request_run_period_variables`, so a model can legitimately carry both.
    # Without this clause such a query matched the RunPeriod series too, whose
    # Month/Day/Hour are NULL, and in SQLite `NULL || 'x'` is NULL — which did
    # not merely add junk rows, it returned NOTHING AT ALL. Measured: a boiler
    # series present as 8832 hourly rows read back as zero hours.
    # Every time column is COALESCEd for the same reason.
    rows = opt(sql.execAndReturnVectorOfString(
        "SELECT COALESCE(t.Month, 0) || '|' || COALESCE(t.Day, 0) || '|' || "
        "COALESCE(t.Hour, 0) || '|' || COALESCE(d.KeyValue, '') || '|' || "
        "COALESCE(r.Value, 0) "
        "FROM ReportData r "
        "JOIN ReportDataDictionary d "
        "  ON r.ReportDataDictionaryIndex = d.ReportDataDictionaryIndex "
        "JOIN Time t ON r.TimeIndex = t.TimeIndex "
        f"WHERE {where} AND d.ReportingFrequency = 'Hourly' "
        "AND t.EnvironmentPeriodIndex IN "
        "(SELECT EnvironmentPeriodIndex FROM EnvironmentPeriods "
        " WHERE EnvironmentType = 3) "
        "ORDER BY t.TimeIndex"
    ))
    if rows is None:
        return []
    out = []
    for line in rows:
        parts = line.split("|")
        if len(parts) < 5:
            continue
        # PARSE FROM BOTH ENDS. A `|` in an object name is legal in
        # OpenStudio and survives translation, so a zone called
        # "Thermal Zone 1|X" produced SIX parts: the key was truncated to
        # "THERMAL ZONE 1" and `_to_f('X')` turned the value into a plausible
        # 0.0 — 8760 hours of silent zeros, with the `< 5` guard never firing
        # because there were MORE parts, not fewer (Fable, `323` 1.1).
        month, day, hour = parts[0], parts[1], parts[2]
        key = "|".join(parts[3:-1])
        out.append((int(_to_f(month)), int(_to_f(day)), int(_to_f(hour)),
                    key, _to_f(parts[-1])))
    return out


def hourly_series(model, name):
    """One reported series, hourly, over the weather run period.

    Returns `{'index': [(month, day, hour)], 'values': [...]}`.

    REFUSES a name reported under more than one KeyValue, because there is no
    reduction that is right for all of them. An earlier version summed, and
    summing is wrong for every variable in `HOURLY_ZONE_VARIABLES`: on a
    5-zone model it returned 62.66 for `Zone Mean Air Temperature` at hour one
    (five temperatures added, where a mean is wanted) and 267 "hours" of
    setpoint-not-met time against a worst single zone of 70 — zone-hours,
    which is neither the per-zone figure nor the facility one that
    unmet-hours reporting means (Fable, `323` 2). A number that looks like a
    temperature and is five of them is worse than an error. Use
    `hourly_series_by_key` and reduce deliberately.

    PLAIN PYTHON ON PURPOSE. `btap` depends on `openstudio` and the
    EnergyPlus companion, nothing else, so this cannot hand back a DataFrame
    without making pandas a dependency of a package whose contract is to have
    almost none. A caller that wants one writes
    `pd.DataFrame(s['values'], index=s['index'])`.
    """
    sql = opt(model.sqlFile())
    if sql is None:
        return {"index": [], "values": []}

    _one_weather_period(sql)
    escaped = _sql_name(name)
    rows = _hourly_rows(sql, f"d.Name = '{escaped}'")
    if not rows:
        _absent(model, name)
        return {"index": [], "values": []}
    keys = {key for _m, _d, _h, key, _v in rows}
    if len(keys) > 1:
        raise ValueError(
            f"{name!r} is reported under {len(keys)} keys "
            f"({sorted(keys)[:4]}…) and no single reduction suits them all — "
            f"a sum is wrong for a temperature and a mean is wrong for an "
            f"energy. Use hourly_series_by_key and reduce deliberately")
    index = [(month, day, hour) for month, day, hour, _k, _v in rows]
    return {"index": index, "values": [value for *_x, value in rows]}


def hourly_series_by_key(model, name):
    """`{KeyValue: {'index': …, 'values': …}}` — per zone, per boiler, per loop.

    Keys are EnergyPlus UPPER-CASED object names, as in `run_period_sums`. A
    meter has no KeyValue and arrives under `''`.
    """
    sql = opt(model.sqlFile())
    if sql is None:
        return {}

    _one_weather_period(sql)
    escaped = _sql_name(name)
    if escaped not in hourly_names(model):
        _absent(model, name)
        return {}
    out = {}
    for month, day, hour, key, value in _hourly_rows(
            sql, f"d.Name = '{escaped}'"):
        bucket = out.setdefault(key, {"index": [], "values": []})
        bucket["index"].append((month, day, hour))
        bucket["values"].append(value)
    return out


def hourly_hot_water_plant_heat(model, variable=BOILER_HEAT_VARIABLE):
    """Hourly heat delivered by the HOT-WATER PLANT, summed over boilers.

    This is the series a hydronic district-energy connection must deliver, and
    the one to read when a district connection is MODELLED AS A BOILER so that
    one run answers both cases: this is the district system's obligation and
    `BOILER_FUEL_VARIABLE` is the same building read as an on-site boiler. No
    second model, so no chance of an unintended difference between variants.

    NOT "the building's heat load", which is what an earlier name and
    docstring claimed. On a catalogue system with ELECTRIC baseboards the
    boilers carried 41.63 MWh while the baseboards delivered another 35.83
    that no boiler sees; a model with heat pumps or electric heat would read
    this and get a fraction of its heating (Fable, `323` 3).

    WHY NOT `Heating:EnergyTransfer`, correctly this time. That meter is the
    facility sum of `Zone Air System Sensible Heating Energy` — the zone air
    balance's NET sensible heating — and it does NOT exclude hydronic
    baseboards: on a baseboard-only system meter, baseboard meter and summed
    variable are all 33.40 MWh. An earlier version of this docstring said it
    excluded them, which was simply false.

    The gap is real and the mechanism is different: a VAV with NO baseboards
    still shows 2.17x (35.07 zone-side against 76.13 at the plant), because
    simultaneous cooling-then-reheat and the heating of ventilation air to
    supply temperature are plant heat that offsets cooling or outdoor air and
    never arrives as net zone sensible heating. So a zone-side net term cannot
    see a hydronic plant's obligation — which is the reason to read the plant,
    and it holds without any baseboard story.

    Summed across boilers because a lead/lag pair reports the idle one as
    zero, so a reader taking the first boiler gets the whole load on one model
    and nothing on another.

    For a source-neutral plant reading — district water, a heat pump plant,
    anything that is not a boiler — use `hourly_series_by_key` on
    `"Plant Supply Side Heating Demand Rate"` and pick the loop; it agrees
    with the boilers to the second decimal, but it is a RATE in W.
    """
    # An empty plant series is a real answer where the model has no boiler:
    # five catalogue systems are district-hot-water, and three have ELECTRIC
    # boilers so the gas fuel variable never reports. `hourly_series_by_key`
    # distinguishes that from a name nobody requested.
    return sum_by_key(hourly_series_by_key(model, variable))


def sum_by_key(per_key):
    """Add every key's series hour by hour — a plant total from its parts.

    Separate from its caller so it is testable WITHOUT a model whose boilers
    both fire. On the obvious fixture a lead/lag pair leaves one boiler
    identically zero, which makes a sum indistinguishable from a maximum: a
    `+=` to `max()` mutation passed all ten tests precisely because the test's
    own precondition required an idle boiler (Fable, `323` M10).
    """
    if not per_key:
        return {"index": [], "values": []}
    items = sorted(per_key.items())
    index = items[0][1]["index"]
    # REFUSE a ragged set rather than clipping to the first key's length.
    # The clip could not misfire on a `'*'` variable in one run, but a silent
    # truncation is the thing this layer refuses everywhere else, and a reader
    # assembling series from two sources is exactly who would hit it
    # (Fable, `323` addendum).
    for key, series in items:
        if series["index"] != index:
            raise ValueError(
                f"{key!r} has a different hourly index from "
                f"{items[0][0]!r} ({len(series['index'])} vs {len(index)} "
                f"hours); these series cannot be added")
    totals = [0.0] * len(index)
    for _key, series in items:
        for i, value in enumerate(series["values"]):
            totals[i] += value
    return {"index": index, "values": totals}



def demand_from_energy(values, interval_hours=1.0):
    """Energy per interval -> average DEMAND over that interval, in watts.

    A meter reports joules PER INTERVAL, so `Electricity:Facility` hourly is
    J/h and not a demand. The load duration curve's y axis is demand, so the
    conversion belongs somewhere explicit rather than in a reader's head:
    `W = J / seconds`.
    """
    seconds = float(interval_hours) * 3600.0
    return [float(v) / seconds for v in values]


def load_duration_curve(values, interval_hours=1.0, percent=False):
    """The load duration curve: `[(duration, demand)]`, sloping DOWNWARD.

    phylroy's definition, which this implements literally:

        x  duration of load — hours, or percentage of time
        y  demand
        the curve slopes downward from peak load to minimum load

    `duration` is CUMULATIVE: the first point is the peak and the duration at
    which load is at or above it, the last is the minimum at 100% of the time.
    `interval_hours` scales the x axis, so a 15-minute series passes 0.25 and
    gets hours rather than a count of intervals; `percent=True` gives
    percentage of time instead, which is what makes two buildings of different
    size comparable on one chart.

    THE Y AXIS IS WHATEVER YOU PASS. For a demand curve pass a rate series, or
    convert an energy-per-interval series with `demand_from_energy` — a raw
    hourly meter is J/h, not W, and the two differ by 3600. An earlier version
    returned a 1-based RANK and called it "hours at or above", which is true
    only for hourly input and silently wrong for any other interval (Fable,
    `323` 6).

    Why this and not a peak value: a peak cannot distinguish a NEEDLE from a
    PLATEAU, and that is the whole question — how many hours sit near the peak
    decides whether shaving is cheap, the AREA above a threshold is the energy
    a store must hold, and the curve's knee is where chasing a demand charge
    stops paying. It cannot be built from `DemandEndUseComponentsSummary`,
    which gives one number and one timestamp.
    """
    ordered = sorted((float(v) for v in values), reverse=True)
    if not ordered:
        return []
    if percent:
        total = len(ordered)
        return [((i + 1) / total * 100.0, v) for i, v in enumerate(ordered)]
    step = float(interval_hours)
    return [((i + 1) * step, v) for i, v in enumerate(ordered)]


def energy_above(values, threshold, interval_hours=1.0):
    """Energy above `threshold` — the area over it on the duration curve.

    The quantity that sizes a store or a peak-shaving measure, which the
    height of the peak cannot give.

    `interval_hours` is what makes this correct for a RATE series: a demand in
    W above a threshold for one hour is Wh, so the excess is scaled by the
    interval. For an ENERGY-per-interval series (a raw meter in J) leave it at
    1.0, because those values already sum to energy — scaling them would be
    wrong (Fable, `323` 6).
    """
    limit = float(threshold)
    step = float(interval_hours)
    return sum((float(v) - limit) * step for v in values if float(v) > limit)


def _to_f(value: str) -> float:
    """Ruby String#to_f: best-effort parse, 0.0 on garbage — SQL join output
    is numeric-or-empty and Ruby's leniency is part of the ported contract."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _scaled(optional_gj):
    value = opt(optional_gj)
    return None if value is None else ruby_round(value * GJ_TO_KWH, 1)


def _district(sql, method_names):
    """District end-use SqlFile accessors were renamed across OpenStudio
    versions — probe with hasattr (the respond_to? port)."""
    for name in method_names:
        if hasattr(sql, name):
            return _scaled(getattr(sql, name)())
    return None


def _end_use(sql, category):
    """SqlFile end-use accessors are per-fuel — sum the category across every
    fuel from the tabular End Uses table."""
    row = {"Heating": "Heating", "Cooling": "Cooling", "Fans": "Fans", "Pumps": "Pumps",
           "InteriorLighting": "Interior Lighting", "InteriorEquipment": "Interior Equipment",
           "WaterSystems": "Water Systems"}[category]
    value = opt(sql.execAndReturnFirstDouble(
        "SELECT SUM(Value) FROM TabularDataWithStrings "
        "WHERE ReportName='AnnualBuildingUtilityPerformanceSummary' AND TableName='End Uses' "
        f"AND RowName='{row}' AND Units='GJ'"
    ))
    return None if value is None else ruby_round(value * GJ_TO_KWH, 1)
