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


def attach_weather(model, *, epw, ddy):
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

    for dd in model.getDesignDays():
        dd.remove()
    # the legacy default list — NOT a bare /.4%/, which would also pull the
    # MONTHLY .4% days (a January cooling day's ~2C wet-bulb breaks the
    # tower UA solve). Ruby's =~ is a SEARCH: re.search, never match.
    keep = [r"Htg 99.6. Condns DB", r"Clg .4% Condns DB=>MWB",
            r"Clg 0.4% Condns DB=>MCWB", r"Clg .4. Condns WB=>MDB"]
    all_days = list(workspace.getDesignDays())
    extremes = [dd for dd in all_days
                if any(re.search(p, dd.nameString()) for p in keep)]
    if not extremes:  # odd DDY: keep everything rather than none
        extremes = all_days
    for dd in extremes:
        model.addObject(dd.clone())
    if len(model.getDesignDays()) == 0:
        raise ValueError(f"no design days found in {ddy}")
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

    existing = [(v.keyValue(), v.variableName()) for v in model.getOutputVariables()]
    for name in names:
        if ("*", name) in existing:
            continue
        variable = openstudio.model.OutputVariable(name, model)
        variable.setKeyValue("*")
        variable.setReportingFrequency("RunPeriod")


def run_period_sums(model, variable_name) -> dict:
    """Sum a reported variable per KeyValue over the WEATHER run period(s)
    only. EnvironmentType = 3 filters out design days — a shared DDY can
    carry dozens, and an unfiltered sum silently mixes them in (the D-56
    trap). Keys are EnergyPlus UPPER-CASED object names; values joules."""
    sql = opt(model.sqlFile())
    if sql is None:
        return {}

    rows = opt(sql.execAndReturnVectorOfString(
        "SELECT d.KeyValue || '|' || SUM(r.Value) FROM ReportData r "
        "JOIN ReportDataDictionary d ON r.ReportDataDictionaryIndex = d.ReportDataDictionaryIndex "
        "JOIN Time t ON r.TimeIndex = t.TimeIndex "
        f"WHERE d.Name = '{variable_name}' AND t.EnvironmentPeriodIndex IN "
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
