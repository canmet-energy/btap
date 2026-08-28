"""NECB 2025 8.4.4 (EUI path) archetype machinery (port of
eui_archetypes.rb): space->archetype mapping, floor areas computed FROM the
model (8.4.4.1.(3)), pro-rata distribution of unmapped space functions
(8.4.4.1.(4)), hard applicability guards (8.4.4.1.(1) coverage, Table note
HDD), the Table 8.4.4.2 CONFORMANCE CHECK, and the Table 8.4.4.2
NORMALIZATION transform.

Why check-then-normalize: the Table 8.4.4.1 EUI targets were derived assuming
the standardized Table 8.4.4.2 operating inputs, so comparing a proposed
simulated with arbitrary schedules/loads against them is apples-to-oranges
(and gameable). 8.4.4.2.(1) therefore REWRITES the proposed's occupancy,
receptacle, SWH loads and operating schedules to the archetype defaults
before the EUI-path run. When the model already matches (the check), the
as-specified run legitimately serves both compliance paths and the second
simulation is skipped.

Scope (manifest: 8.4.4.2 partial), all audited:
- lighting POWER is the design being evaluated and is never touched.
  Lighting OPERATION schedules ARE normalized to the archetype letter
  (interpretation ADOPTED, project decision 2026-07-22).
- outdoor air IS normalized (interpretation ADOPTED, same decision):
  8.4.3.6.(1)(a) read as the ventilation-standard rates applied AT the
  Table's occupant density (ASHRAE 62.1-2016 Table 6.2.2.1 rates per
  archetype, ARCHETYPE_OA_62_1).
- unmapped spaces keep their modeled loads: Table 8.4.4.2 applies "for the
  applicable building archetype", and unmapped space functions have none —
  only their AREA is distributed per 8.4.4.1.(4).

"Archetype" here is the CODE's word: the Table 8.4.4.1 BUILDING ARCHETYPES
of the 8.4.4 EUI path (hence the module name eui_archetypes). The project's
other sense — the 17 legacy NECB prototype buildings used as the validation
"fleet" — is a DIFFERENT thing entirely.

Mapping specs accept the string ``'all'`` where Ruby took ``:all``."""

from __future__ import annotations

from btap._compat import opt, ruby_round, sorted_by_name
from btap.audit import AuditLog
from btap.necb import tiers

VALUE_TOL = 0.01          # 1% on densities/powers/flows
SCHEDULE_TOL = 0.005      # 0.5% absolute on hourly schedule values
PEOPLE_PER_1000FT2_PER_M2_PER_PERSON = 92.90304  # 1000 ft2 in m2
#: ASHRAE 62.1-2016 Table 6.2.2.1 rates (retrieved via the codes server
#: ashrae_outdoor_air_rate 2026-07-22). Applied at the Table 8.4.4.2 occupant
#: density per the adopted 8.4.3.6.(1)(a) reading.
ARCHETYPE_OA_62_1 = {
    "School (K-12)": {"category": "classroom (age 9 plus)",
                      "rp_l_s_person": 5.0, "ra_l_s_m2": 0.6},
    "Multi-unit residential building": {"category": "dwelling unit",
                                        "rp_l_s_person": 2.5, "ra_l_s_m2": 0.3},
    "Office": {"category": "office space",
               "rp_l_s_person": 2.5, "ra_l_s_m2": 0.3},
}


def _is_all(spec):
    return spec == "all" or spec == ":all"


# ---- mapping / areas ---------------------------------------------------

def resolve(model, mapping, *, audit):
    """mapping: {archetype_name: 'all' | [space names]}. At most one archetype
    may map 'all' (every counted space not claimed by an explicit list).

    :return: the resolved mapping —
        {'archetypes': {name: {'spaces': [Space], 'area_m2': float}},
         'unmapped': {'spaces': [Space], 'area_m2': float},
         'total_area_m2': float}
    :raises ValueError: on unknown archetypes, unknown space names,
        double-mapped spaces, or more than one 'all' archetype"""
    table = tiers.eui_data()["archetype_eui_kwh_per_m2"]
    unknown = [str(k) for k in mapping if str(k) not in table]
    if unknown:
        raise ValueError(f"unknown 2025 EUI archetype(s) {'; '.join(unknown)} "
                         f"({'; '.join(table.keys())})")

    alls = [k for k, v in mapping.items() if _is_all(v)]
    if len(alls) > 1:
        raise ValueError(f"only one archetype may map 'all' (got {', '.join(alls)})")

    counted = counted_spaces(model)
    by_name = {s.nameString(): s for s in counted}
    claimed: dict[str, str] = {}
    resolved: dict[str, list] = {}
    for archetype, spec in mapping.items():
        if _is_all(spec):
            continue

        names = [str(n) for n in ([spec] if isinstance(spec, str) else spec)]
        missing = [n for n in names if n not in by_name]
        if missing:
            raise ValueError(
                f"archetype '{archetype}': space(s) not found or not counted "
                f"toward floor area: {'; '.join(missing)} "
                f"(counted spaces: {'; '.join(by_name.keys())})")
        for n in names:
            if n in claimed:
                raise ValueError(f"space '{n}' mapped to both '{claimed[n]}' "
                                 f"and '{archetype}'")

            claimed[n] = str(archetype)
        resolved[str(archetype)] = [by_name[n] for n in names]
    if alls:
        rest = [s for s in counted if s.nameString() not in claimed]
        resolved[str(alls[0])] = rest
        for s in rest:
            claimed[s.nameString()] = str(alls[0])

    unmapped = [s for s in counted if s.nameString() not in claimed]
    out = {
        "archetypes": {name: {"spaces": spaces, "area_m2": area_of(spaces)}
                       for name, spaces in resolved.items()},
        "unmapped": {"spaces": unmapped, "area_m2": area_of(unmapped)},
        "total_area_m2": area_of(counted),
    }
    audit.decision(
        "eui",
        "spaces mapped to Table 8.4.4.1 archetypes; areas computed from the model",
        inputs={"areas_m2": {name: ruby_round(v["area_m2"], 1)
                             for name, v in out["archetypes"].items()},
                "unmapped_m2": ruby_round(out["unmapped"]["area_m2"], 1),
                "floor_area_basis": "partofTotalFloorArea, non-plenum, x space "
                                    "multiplier (proxy for conditioned per "
                                    "8.4.4.1.(3))"},
        article="8.4.4.1.(3)", ruling="D-04")
    return out


def bet_areas(resolved, *, audit):
    """8.4.4.1.(4): unmapped ("not associated") floor area distributed
    proportionally among the listed archetypes so the BET areas sum to the
    model's total. Over-assignment is impossible by construction (areas come
    from disjoint space sets).
    :return: {archetype name: BET floor area in m2}"""
    base = {name: v["area_m2"] for name, v in resolved["archetypes"].items()}
    mapped = sum(base.values())
    extra = resolved["unmapped"]["area_m2"]
    if extra > 0 and mapped > 0:
        base = {name: a + (extra * a / mapped) for name, a in base.items()}
        audit.decision(
            "eui",
            "unlisted space functions distributed proportionally among the "
            "listed archetypes",
            inputs={"distributed_m2": ruby_round(extra, 1)}, article="8.4.4.1.(4)")
    return base


def verify_applicability(resolved, *, hdd, audit):
    """Hard applicability guards. 8.4.4.1.(1) says the Subsection "shall only
    be used" at >=90% coverage; the Table note bounds HDD < 9000. On the pure
    'eui' path these REFUSE (a verdict outside applicability is not a
    determination); the supplement instead reports not-computed.
    :raises ValueError: when the 8.4.4 EUI path is not applicable"""
    problems = applicability_problems(resolved, hdd=hdd, audit=audit)
    if problems:
        raise ValueError(
            f"the 8.4.4 EUI path is NOT applicable: {'; '.join(problems)}")


def applicability_problems(resolved, *, hdd, audit):
    """Non-raising form of verify_applicability.
    :return: human-readable problems (empty when applicable)"""
    rules = tiers.eui_data()["applicability"]
    problems = []
    mapped = sum(v["area_m2"] for v in resolved["archetypes"].values())
    coverage = (mapped / resolved["total_area_m2"]
                if resolved["total_area_m2"] > 0 else 0.0)
    if coverage < rules["min_archetype_floor_fraction"] - 1e-6:
        problems.append(
            "only %.1f%% of floor area maps to listed archetypes "
            "(8.4.4.1.(1) requires >= %.0f%%)"
            % (coverage * 100, rules["min_archetype_floor_fraction"] * 100))
        audit.warn("eui",
                   "archetype floor coverage BELOW the 8.4.4.1.(1) threshold "
                   f"({ruby_round(coverage * 100, 1)}%)",
                   article="8.4.4.1.(1)", ruling="D-04")
    if hdd is not None and hdd >= rules["max_hdd"]:
        problems.append(f"HDD {hdd} >= {rules['max_hdd']} (Table 8.4.4.1 note (1))")
        audit.warn("eui",
                   f"HDD {hdd} is outside the 8.4.4 applicability bound "
                   f"(< {rules['max_hdd']})",
                   article="Table 8.4.4.1.", ruling="D-04")
    return problems


# ---- Table 8.4.4.2 defaults -------------------------------------------

def defaults_for(archetype):
    """The defaults table keys MURB once; both storey-height archetypes share
    it."""
    table = tiers.eui_data()["archetype_defaults_table_8_4_4_2"]
    key = next((k for k in table if archetype.startswith(k)), None)
    if key is None:
        key = next((k for k in table
                    if "residential" in archetype and "residential" in k), None)
    if key is None:
        raise ValueError(f"no Table 8.4.4.2 defaults for archetype '{archetype}'")
    return table[key]


def synthetic_record(archetype):
    """A loads-catalog-shaped record carrying the Table 8.4.4.2 values, so the
    loads package's own application machinery (apply_people/apply_equipment/
    apply_schedule_set/apply_thermostat) does the model work. Fractions are
    the NECB standard set the catalog uses throughout."""
    d = defaults_for(archetype)
    letter = d["schedule"]
    oa_key = next((k for k in ARCHETYPE_OA_62_1 if archetype.startswith(k)), None)
    if oa_key is None:
        oa_key = ("Multi-unit residential building"
                  if "residential" in archetype else archetype)
    oa = ARCHETYPE_OA_62_1[oa_key]
    return {
        "necb_schedule_type": letter,
        "lighting_schedule": f"NECB-{letter}-Lighting",
        "oa_category_62_1": oa["category"],
        "oa_l_s_per_person": oa["rp_l_s_person"],
        "oa_l_s_per_m2": oa["ra_l_s_m2"],
        "occupancy_per_area": (PEOPLE_PER_1000FT2_PER_M2_PER_PERSON
                               / d["occupant_density_m2_per_person"]),
        "occupancy_schedule": f"NECB-{letter}-Occupancy",
        "occupancy_activity_schedule": "NECB-Activity",
        "electric_equipment_per_area": d["receptacle_w_per_m2"] / 10.7639104,
        # Ruby's record hash simply had no gas keys (nil -> to_f -> 0.0 /
        # schedule skipped); the Python appliers index them, so carry the
        # nils explicitly.
        "gas_equipment_per_area": None,
        "gas_equipment_schedule": None,
        "electric_equipment_fraction_latent": 0.0,
        "electric_equipment_fraction_radiant": 0.5,
        "electric_equipment_fraction_lost": 0.0,
        "electric_equipment_schedule": f"NECB-{letter}-Electric-Equipment",
        "heating_setpoint_schedule": f"NECB-{letter}-Thermostat Setpoint-Heating",
        "cooling_setpoint_schedule": f"NECB-{letter}-Thermostat Setpoint-Cooling",
        "service_water_heating_schedule": f"NECB-{letter}-Service Water Heating",
        "swh_l_per_h_per_occupant": d["swh_l_per_h_per_occupant"],
        "occupant_density_m2_per_person": d["occupant_density_m2_per_person"],
    }


# ---- conformance check -------------------------------------------------

def conformance(model, resolved, *, vintage, audit):
    """Does the model ALREADY carry the Table 8.4.4.2 values, so one
    as-specified annual run can lawfully serve both compliance paths?
    Compares, per mapped space: occupant density, receptacle power, SWH peak
    flow (values, VALUE_TOL) and the occupancy/equipment/setpoint schedule
    PROFILES hourly over the year (SCHEDULE_TOL) against the archetype
    letter's NECB schedules. Conservative: anything not comparable is a
    mismatch (worst case is an unnecessary second run, never a wrong verdict).
    :return: {'conformant': bool, 'mismatches': [str]}"""
    import openstudio

    mismatches: list[str] = []
    scratch = openstudio.model.Model()
    for archetype, info in resolved["archetypes"].items():
        record = synthetic_record(archetype)
        targets = target_schedules(scratch, record, vintage)
        for space in info["spaces"]:
            check_space_values(space, archetype, record, mismatches)
            check_space_schedules(space, archetype, targets, mismatches)
    conformant = not mismatches
    audit.decision(
        "eui",
        "proposed already conforms to Table 8.4.4.2 — the as-specified annual "
        "run serves the EUI path" if conformant
        else f"proposed does NOT conform to Table 8.4.4.2 "
             f"({len(mismatches)} mismatch(es))",
        inputs={"mismatches": mismatches[:20]}, article="8.4.4.2.(1)")
    return {"conformant": conformant, "mismatches": mismatches}


# ---- normalization -----------------------------------------------------

def normalize(model, resolved, *, vintage, audit):
    """Rewrites the (already-cloned) model to Table 8.4.4.2 for every mapped
    space: occupancy + receptacle loads and operating schedules via a cloned
    space type per (original type x archetype), SWH flows per occupant, and
    zone thermostats from the archetype letter. Lighting power, lighting
    operation, OA and unmapped spaces are left as modeled (see module doc).

    :param model: an already-cloned model (rewritten in place)
    :param resolved: resolve output FOR THIS model (space objects must belong
        to it)
    :return: the normalized model"""
    import openstudio

    from btap.necb import loads

    apply = loads.Apply
    clones: dict[tuple, object] = {}
    for archetype, info in resolved["archetypes"].items():
        record = synthetic_record(archetype)
        for space in info["spaces"]:
            original = opt(space.spaceType())
            key = (original.nameString() if original else None, archetype)
            clone = clones.get(key)
            if clone is None:
                if original:
                    st = opt(original.clone(model).to_SpaceType())
                else:
                    st = openstudio.model.SpaceType(model)
                st.setName(
                    f"{original.nameString() if original else 'EUI'} "
                    f"[EUI {archetype}]")
                for p in st.people():
                    p.remove()
                for e in st.electricEquipment():
                    e.remove()
                for g in st.gasEquipment():
                    g.remove()
                # a cloned space type still POINTS AT the original's schedule
                # set — wiring into it would mutate the original. Clone the
                # original set (not a bare fresh one): the archetype wiring
                # overwrites the occupancy/equipment entries, while LIGHTING
                # and other schedules keep inheriting as modeled — severing
                # them fatals EnergyPlus on schedule-less Lights and would
                # silently change scope.
                original_set = opt(original.defaultScheduleSet()) if original else None
                if original_set is not None:
                    fresh = opt(original_set.clone(model).to_DefaultScheduleSet())
                else:
                    fresh = openstudio.model.DefaultScheduleSet(model)
                fresh.setName(f"{st.nameString()} Schedule Set")
                st.setDefaultScheduleSet(fresh)
                apply.apply_people(st, record, audit)
                apply.apply_equipment(st, record, audit)
                apply.apply_schedule_set(model, st, record, vintage, audit)
                apply.apply_thermostat(model, st, record, vintage, audit)
                # lighting OPERATION follows the letter (adopted
                # interpretation; POWER untouched — the loads package's wiring
                # deliberately excludes lighting, so it is wired here) and
                # per-instance overrides on the clone's Lights are cleared so
                # the set governs.
                fresh.setLightingSchedule(loads.Schedules.add(
                    model, record["lighting_schedule"], vintage=vintage,
                    audit=audit))
                for light in st.lights():
                    light.resetSchedule()
                clones[key] = st
                clone = st
            space.setSpaceType(clone)
            for light in space.lights():  # space-level instances inherit the set too
                light.resetSchedule()
            space.setDesignSpecificationOutdoorAir(
                archetype_dsoa(model, archetype, record))
            normalize_swh(model, space, record, vintage, audit)
        audit.decision(
            "eui", f"spaces normalized to Table 8.4.4.2 ({archetype})",
            inputs={"spaces": len(info["spaces"]),
                    "occupant_density_m2_per_person":
                        record["occupant_density_m2_per_person"],
                    "receptacle_w_per_m2": ruby_round(
                        record["electric_equipment_per_area"] * 10.7639104, 2),
                    "schedule_letter": record["necb_schedule_type"]},
            article="8.4.4.2.(1)", ruling="D-05")
    force_zone_thermostats(model, resolved, audit)
    audit.info(
        "eui",
        "lighting POWER (the design under evaluation) and unmapped spaces are "
        "left as modeled; lighting OPERATION follows the archetype letter and "
        "outdoor air is set to the ASHRAE 62.1 rates at the Table 8.4.4.2 "
        "occupant density (adopted interpretations, 2026-07-22)",
        article="8.4.4.2.(1); 8.4.3.6.(1)(a)", ruling="D-05")
    return model


# -- internals -----------------------------------------------------------

def counted_spaces(model):
    out = []
    for s in sorted_by_name(model.getSpaces()):
        if not s.partofTotalFloorArea():
            continue

        space_type = opt(s.spaceType())
        type_name = space_type.nameString() if space_type else ""
        if "plenum" in type_name.lower() or "plenum" in s.nameString().lower():
            continue
        out.append(s)
    return out


def area_of(spaces):
    return sum(s.floorArea() * s.multiplier() for s in spaces)


def check_space_values(space, archetype, record, mismatches):
    area = space.floorArea()
    if area == 0:
        return

    expect_people = 1.0 / record["occupant_density_m2_per_person"]
    got_people = space.numberOfPeople() / area
    if not within(got_people, expect_people, VALUE_TOL):
        mismatches.append(
            f"{space.nameString()} ({archetype}): occupant density "
            f"{_fmt(got_people)} people/m2, Table 8.4.4.2 requires "
            f"{_fmt(expect_people)}")

    expect_w = record["electric_equipment_per_area"] * 10.7639104
    got_w = space.electricEquipmentPowerPerFloorArea()
    if not within(got_w, expect_w, VALUE_TOL):
        mismatches.append(
            f"{space.nameString()} ({archetype}): receptacle {_fmt(got_w)} W/m2, "
            f"requires {_fmt(expect_w)}")

    expect_flow = swh_target_m3s(space, record)
    got_flow = space_swh_flow_m3s(space)
    if not within(got_flow, expect_flow, VALUE_TOL):
        mismatches.append(
            f"{space.nameString()} ({archetype}): SWH peak flow "
            f"{_fmt(got_flow, 9)} m3/s, requires {_fmt(expect_flow, 9)}")

    check_outdoor_air(space, archetype, record, mismatches)


def check_outdoor_air(space, archetype, record, mismatches):
    """Adopted 8.4.3.6.(1)(a) reading: DSOA must carry the 62.1 rates (Sum
    method) at the Table density. Absent or differing DSOA is a mismatch."""
    dsoa = opt(space.designSpecificationOutdoorAir())
    if dsoa is None:
        mismatches.append(
            f"{space.nameString()} ({archetype}): no "
            "DesignSpecificationOutdoorAir (62.1 rates at Table density required)")
        return
    expect_pp = record["oa_l_s_per_person"] / 1000.0
    expect_pa = record["oa_l_s_per_m2"] / 1000.0
    if not (dsoa.outdoorAirMethod().lower() == "sum"
            and within(dsoa.outdoorAirFlowperPerson(), expect_pp, VALUE_TOL)
            and within(dsoa.outdoorAirFlowperFloorArea(), expect_pa, VALUE_TOL)):
        mismatches.append(
            f"{space.nameString()} ({archetype}): OA {dsoa.outdoorAirMethod()} "
            f"{_fmt(dsoa.outdoorAirFlowperPerson(), 6)}/person + "
            f"{_fmt(dsoa.outdoorAirFlowperFloorArea(), 6)}/m2, requires Sum "
            f"{_fmt(expect_pp, 6)} + {_fmt(expect_pa, 6)} "
            f"(62.1 {record['oa_category_62_1']})")


def check_space_schedules(space, archetype, targets, mismatches):
    space_type = opt(space.spaceType())
    groups = {
        "occupancy": (list(space_type.people()) if space_type else [],
                      "numberofPeopleSchedule"),
        "electric equipment": (list(space_type.electricEquipment())
                               if space_type else [], "schedule"),
        "lighting": ((list(space_type.lights()) if space_type else [])
                     + list(space.lights()), "schedule"),
    }
    for label, (instances, getter) in groups.items():
        target = targets.get(label)
        if target is None:
            continue

        for inst in instances:
            sched = getattr(inst, getter)()
            # not set on the instance -> inherited via the default schedule set
            if hasattr(sched, "is_initialized") and not sched.is_initialized():
                sched = inherited_schedule(inst, label)
            verdict = schedules_equivalent(sched, target)
            if verdict is True:
                continue

            mismatches.append(
                f"{space.nameString()} ({archetype}): {label} schedule {verdict}")
    check_zone_setpoints(space, archetype, targets, mismatches)


def check_zone_setpoints(space, archetype, targets, mismatches):
    zone = opt(space.thermalZone())
    if zone is None:
        return

    thermostat = opt(zone.thermostatSetpointDualSetpoint())
    if thermostat is None:
        mismatches.append(
            f"{space.nameString()} ({archetype}): zone has no thermostat "
            "(letter setpoint schedules required)")
        return
    pairs = {"heating setpoint": thermostat.heatingSetpointTemperatureSchedule(),
             "cooling setpoint": thermostat.coolingSetpointTemperatureSchedule()}
    for label, sched in pairs.items():
        target = targets.get(label)
        if target is None:
            continue

        if hasattr(sched, "is_initialized") and not sched.is_initialized():
            verdict = "absent"
        else:
            verdict = schedules_equivalent(sched, target)
        if verdict is True:
            continue

        mismatches.append(
            f"{space.nameString()} ({archetype}): {label} schedule {verdict}")


def inherited_schedule(instance, label):
    import openstudio

    space_type = opt(instance.spaceType())
    if space_type is None:
        return openstudio.model.OptionalSchedule()

    schedule_set = opt(space_type.defaultScheduleSet())
    if schedule_set is None:
        return openstudio.model.OptionalSchedule()

    if label == "occupancy":
        return schedule_set.numberofPeopleSchedule()
    if label == "electric equipment":
        return schedule_set.electricEquipmentSchedule()
    if label == "lighting":
        return schedule_set.lightingSchedule()
    return openstudio.model.OptionalSchedule()


def target_schedules(scratch, record, vintage):
    from btap.necb import loads

    quiet = AuditLog()
    return {
        "occupancy": loads.Schedules.add(scratch, record["occupancy_schedule"],
                                         vintage=vintage, audit=quiet),
        "lighting": loads.Schedules.add(scratch, record["lighting_schedule"],
                                        vintage=vintage, audit=quiet),
        "electric equipment": loads.Schedules.add(
            scratch, record["electric_equipment_schedule"], vintage=vintage,
            audit=quiet),
        "heating setpoint": loads.Schedules.add(
            scratch, record["heating_setpoint_schedule"], vintage=vintage,
            audit=quiet),
        "cooling setpoint": loads.Schedules.add(
            scratch, record["cooling_setpoint_schedule"], vintage=vintage,
            audit=quiet),
        "SWH": loads.Schedules.add(
            scratch, record["service_water_heating_schedule"], vintage=vintage,
            audit=quiet),
    }


def schedules_equivalent(schedule, target):
    """Hourly profile comparison across the full year. True, or a short
    reason string. Only ScheduleRulesets are comparable — anything else is a
    (conservative) mismatch."""
    import openstudio

    if hasattr(schedule, "is_initialized"):
        if not schedule.is_initialized():
            return "absent"
        schedule = schedule.get()

    ruleset = opt(schedule.to_ScheduleRuleset())
    if ruleset is None:
        return (f"type {schedule.iddObjectType().valueName()} not comparable "
                "(only ScheduleRuleset)")

    # Clone into the TARGET's model before expanding to days: the two models
    # can assume different calendar years (the fixture carries a
    # YearDescription), and a year mismatch shifts day-of-week rules so a
    # weekday profile gets compared against a weekend one.
    candidate = opt(ruleset.clone(target.model()).to_ScheduleRuleset())
    a_days = year_days(candidate)
    b_days = year_days(target)
    for i, (a, b) in enumerate(zip(a_days, b_days)):
        for h in range(1, 25):
            t = openstudio.Time(0, h, 0, 0)
            if abs(a.getValue(t) - b.getValue(t)) > SCHEDULE_TOL:
                return ("differs on day %d hour %d (%.3f vs %.3f)"
                        % (i + 1, h, a.getValue(t), b.getValue(t)))
    return True


def year_days(ruleset):
    import openstudio

    y = ruleset.model().getYearDescription().assumedYear()
    return ruleset.getDaySchedules(
        openstudio.Date(openstudio.MonthOfYear(1), 1, y),
        openstudio.Date(openstudio.MonthOfYear(12), 31, y))


def archetype_dsoa(model, archetype, record):
    """One shared DSOA per archetype: 62.1 rates at the Table density (the
    per-person term therefore rides the NORMALIZED occupancy)."""
    import openstudio

    name = f"EUI OA {archetype} (62.1 {record['oa_category_62_1']})"
    existing = next((d for d in model.getDesignSpecificationOutdoorAirs()
                     if d.nameString() == name), None)
    if existing is not None:
        return existing

    dsoa = openstudio.model.DesignSpecificationOutdoorAir(model)
    dsoa.setName(name)
    dsoa.setOutdoorAirMethod("Sum")
    dsoa.setOutdoorAirFlowperPerson(record["oa_l_s_per_person"] / 1000.0)
    dsoa.setOutdoorAirFlowperFloorArea(record["oa_l_s_per_m2"] / 1000.0)
    return dsoa


def swh_target_m3s(space, record):
    occupants = space.floorArea() / record["occupant_density_m2_per_person"]
    return (occupants * record["swh_l_per_h_per_occupant"]
            / 3_600_000.0)  # L/h -> m3/s


def space_swh_flow_m3s(space):
    return sum(e.waterUseEquipmentDefinition().peakFlowRate()
               for e in space.waterUseEquipment())


def normalize_swh(model, space, record, vintage, audit):
    from btap.necb import loads

    target = swh_target_m3s(space, record)
    equipment = list(space.waterUseEquipment())
    if not equipment:
        if target == 0:
            return

        audit.warn(
            "eui",
            f"space '{space.nameString()}' has NO water-use equipment — Table "
            f"8.4.4.2 SWH load ({record['swh_l_per_h_per_occupant']} "
            "L/h/occupant) cannot be applied; the EUI targets assume it, so "
            "the proposed under-reports SWH energy",
            article="8.4.4.2.(1)")
        return
    share = target / len(equipment)
    quiet_sched = loads.Schedules.add(
        model, record["service_water_heating_schedule"], vintage=vintage,
        audit=audit)
    for e in equipment:
        # definitions may be shared across spaces — give this instance its own
        definition = opt(e.waterUseEquipmentDefinition().clone(model)
                         .to_WaterUseEquipmentDefinition())
        definition.setName(f"{e.nameString()} [EUI] Definition")
        definition.setPeakFlowRate(share)
        e.setWaterUseEquipmentDefinition(definition)
        e.setFlowRateFractionSchedule(quiet_sched)


def force_zone_thermostats(model, resolved, audit):
    space_to_arch = {}
    for archetype, info in resolved["archetypes"].items():
        for s in info["spaces"]:
            space_to_arch[s.nameString()] = archetype
    for zone in sorted_by_name(model.getThermalZones()):
        archs = []
        for s in zone.spaces():
            arch = space_to_arch.get(s.nameString())
            if arch not in archs:
                archs.append(arch)
        if not archs or archs == [None]:
            continue

        if len(archs) > 1 or None in archs:
            audit.warn(
                "eui",
                f"zone '{zone.nameString()}' mixes archetypes/unmapped spaces "
                f"({', '.join(a for a in archs if a is not None)}) — thermostat "
                "left as modeled",
                article="8.4.4.2.(1)")
            continue
        space = next((s for s in zone.spaces() if opt(s.spaceType()) is not None),
                     None)
        if space is None:
            continue

        name = f"{opt(space.spaceType()).nameString()} Thermostat"
        thermostat = next(
            (t for t in model.getThermostatSetpointDualSetpoints()
             if t.nameString() == name), None)
        if thermostat is not None:
            zone.setThermostatSetpointDualSetpoint(thermostat)


def within(got, expect, tol):
    if abs(expect) < 1e-12:
        return abs(got) < 1e-12

    return abs(got - expect) / abs(expect) <= tol


def _fmt(value, precision=4):
    return f"%.{precision}f" % value
