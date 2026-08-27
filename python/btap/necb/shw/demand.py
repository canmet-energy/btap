"""SHW demand + plant — port of legacy model_add_swh / auto_size_shw_capacity:
per-space peak flows from the NECB space-type records (US gal/hr/ft2 x area x
scale), the weekly hourly demand profile from the NECB-<letter> SWH schedules
(Default|Wkdy / Sat / Sun|Hol rows), the peak-hour + next-hour tank sizing
rule, and a WaterHeaterMixed loop with per-space WaterUseEquipment.

DEVIATION (audited): pump head uses the legacy DEFAULT (179532 Pa, the
OpenStudio constant-speed default) — the legacy geometric mech-room piping-run
head calculation is a documented future.
"""

from __future__ import annotations

import math
import re

import openstudio

from btap._compat import NullAudit, ruby_round, ruby_str, sorted_by_name
from btap.audit import AuditLog
from btap.necb import loads as necb_loads
from btap.necb import shw as SHW
from btap.necb.loads import schedules as loads_schedules
from btap.necb.loads import space_types as loads_space_types

DAY_KEYS = ("Default|Wkdy", "Sat", "Sun|Hol")
NEXT_DAY = {"Default|Wkdy": "Sat", "Sat": "Sun|Hol", "Sun|Hol": "Default|Wkdy"}

_NUMERIC_PREFIX = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _to_f(value) -> float:
    """Ruby ``to_f``: nil -> 0.0, numerics pass, strings parse their leading
    float (unparseable -> 0.0)."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    m = _NUMERIC_PREFIX.match(str(value).strip())
    return float(m.group(0)) if m else 0.0


def _auto_size(model, *, vintage="2020", shw_scale=1.0, audit=None):
    """Auto-size the SHW tank/plant from the space-type demand (legacy-exact).

    :return: dict of tank volume/capacity (SI), max temp, loop peak flow,
        parasitic loss, spaces_w_dhw
    """
    audit = audit if audit is not None else NullAudit()
    rules = SHW.rules(vintage)["autosize"]
    data_vintage = necb_loads.data_vintage(vintage)
    schedules = necb_loads.table(data_vintage, "schedules")
    if shw_scale is None or shw_scale == "none" or shw_scale == "NECB_Default":
        shw_scale = 1.0
    if isinstance(shw_scale, str):
        shw_scale = _to_f(str(shw_scale).strip())

    weekly = {k: [0.0] * 24 for k in DAY_KEYS}
    total_peak = 0.0
    peak_sched = 0.0
    spaces = []

    for space in sorted_by_name(model.getSpaces()):
        space_type = space.spaceType()
        if space_type.empty():
            continue
        space_type = space_type.get()
        if (space_type.standardsSpaceType().empty()
                or space_type.standardsBuildingType().empty()):
            continue

        record = loads_space_types.find(
            building_type=space_type.standardsBuildingType().get(),
            space_type=space_type.standardsSpaceType().get(), vintage=data_vintage)
        if record is None or loads_space_types.is_undefined(record):
            continue
        if (_to_f(record.get("service_water_heating_peak_flow_per_area")) == 0
                and _to_f(record.get("service_water_heating_peak_flow_rate")) == 0):
            continue
        if record.get("service_water_heating_schedule") is None:
            continue

        area_ft2 = openstudio.convert(space.floorArea(), "m^2", "ft^2").get()
        peak_ind = (_to_f(record.get("service_water_heating_peak_flow_per_area"))
                    * area_ft2 * shw_scale)
        peak = peak_ind * space.multiplier()
        total_peak += peak

        temperature = record.get("service_water_heating_target_temperature")
        if temperature is None or _to_f(temperature) <= 16:
            temperature = 60
        spaces.append({
            "space": space,
            "peak_flow_si": openstudio.convert(peak, "gal/hr", "m^3/s").get(),
            "peak_flow_ind_si": openstudio.convert(peak_ind, "gal/hr", "m^3/s").get(),
            "temperature_c": _to_f(temperature),
            "schedule": record.get("service_water_heating_schedule")})

        for day in DAY_KEYS:
            row = next((r for r in schedules
                        if r["name"] == record.get("service_water_heating_schedule")
                        and r["day_types"] == day), None)
            if row is None or len(row["values"]) != 24:
                raise ValueError(
                    f"SWH schedule {record.get('service_water_heating_schedule')} "
                    f"lacks a '{day}' row")

            for hour, fraction in enumerate(row["values"]):
                weekly[day][hour] += _to_f(fraction) * peak
                if weekly[day][hour] > peak_sched:
                    peak_sched = weekly[day][hour]

    if not spaces:
        return {"tank_volume_si": 0, "tank_capacity_si": 0, "max_temp_c": 60,
                "loop_peak_flow_si": 0, "parasitic_loss_w": 0, "spaces_w_dhw": []}

    # the hour AFTER the peak hour(s) with the highest demand — LEGACY-EXACT.
    # Hours are iterated in HOUR ORDER (true adjacency). Legacy history: the
    # original auto_size_shw_capacity iterated the SORTED hourly array while
    # indexing the UNSORTED one for "next hour" (an arbitrary hour, smaller
    # tanks); upstream PR #2119 (merged 2026-07-15) fixed it to hour order,
    # and this gem flipped with it (D-68) — the parity gate compares live.
    next_hour_flow = 0.0
    for day in DAY_KEYS:
        for hour_index, flow in enumerate(weekly[day]):
            if flow != peak_sched:
                continue

            next_day = NEXT_DAY[day] if hour_index == 23 else day
            next_hour = 0 if hour_index == 23 else hour_index + 1
            candidate = weekly[next_day][next_hour]
            if candidate > next_hour_flow:
                next_hour_flow = candidate

    tank_volume_gal = peak_sched
    peak_time_fraction = 1 - (peak_sched / total_peak)
    if peak_time_fraction <= 0.2:
        tank_volume_gal += next_hour_flow
        peak_time_fraction = 1
    tank_volume_si = openstudio.convert(tank_volume_gal, "gal", "m^3").get()
    max_temp = max(s["temperature_c"] for s in spaces)
    tank_capacity_si = (tank_volume_si * 1000 * 4180
                        * (max_temp - rules["cold_water_inlet_c"])
                        / (3600 * peak_time_fraction))
    radius = (tank_volume_si / (rules["tank_height_to_radius"] * math.pi)) ** (1.0 / 3)
    area = 2 * (1 + rules["tank_height_to_radius"]) * math.pi * radius ** 2
    room_c = openstudio.convert(rules["ambient_f"], "F", "C").get()
    parasitic = rules["tank_u_w_per_m2k"] * area * (max_temp - room_c)

    audit.decision("shw",
                   "SHW plant auto-sized from space-type demand (legacy tank rule: peak hour "
                   "+ next hour when recovery time is short)",
                   inputs={"spaces_with_dhw": len(spaces),
                           "total_peak_gal_hr": ruby_round(total_peak, 2),
                           "peak_hour_gal": ruby_round(peak_sched, 2),
                           "tank_volume_l": ruby_round(tank_volume_si * 1000, 1),
                           "tank_capacity_kw": ruby_round(tank_capacity_si / 1000, 2),
                           "supply_c": max_temp,
                           "parasitic_w": ruby_round(parasitic, 1)},
                   article="8.4.3.2. (SWH loads); 6.2.2.1.")
    return {"tank_volume_si": tank_volume_si, "tank_capacity_si": tank_capacity_si,
            "max_temp_c": max_temp,
            "loop_peak_flow_si": openstudio.convert(total_peak, "gal/hr", "m^3/s").get(),
            "parasitic_loss_w": parasitic, "spaces_w_dhw": spaces}


def apply_shw(model, *, vintage="2020", fuel="NaturalGas", shw_scale=1.0, audit=None):
    """Build the full SHW system: auto-size, create the loop + water heater +
    pump, one WaterUseConnections/WaterUseEquipment per demanding space, apply
    Part 6 efficiency on the sized heater.

    :param fuel: 'NaturalGas', 'Electricity', 'FuelOilNo2' or 'HeatPump' —
        'HeatPump' builds an air-source WaterHeaterHeatPump (pumped condenser)
        around the tank, with the code EF/UEF floor as the coil's rated COP
    """
    from btap.necb.shw import efficiency as Efficiency
    from btap.necb.shw import prescriptive as Prescriptive

    audit = audit if audit is not None else AuditLog()
    sizing = _auto_size(model, vintage=vintage, shw_scale=shw_scale, audit=audit)
    if sizing["loop_peak_flow_si"] == 0:
        audit.info("shw", "no space calls for service hot water — no SHW loop added "
                          "(legacy behavior)")
        return None

    rules = SHW.rules(vintage)["autosize"]
    data_vintage = necb_loads.data_vintage(vintage)
    heat_pump = str(fuel) == "HeatPump"
    loop = _build_loop(model, sizing, "Electricity" if heat_pump else fuel, rules, audit)

    for entry in sizing["spaces_w_dhw"]:
        _add_water_use(model, loop, entry, data_vintage, audit)

    tank = [c.to_WaterHeaterMixed().get() for c in loop.supplyComponents(
        openstudio.model.WaterHeaterMixed.iddObjectType())][0]
    if heat_pump:
        hpwh = _wrap_heat_pump(model, tank, sizing, audit)
        Efficiency.apply_heat_pump_efficiency(hpwh, vintage=vintage, audit=audit)
    else:
        Efficiency.apply_efficiency(tank, vintage=vintage, audit=audit)
    audit.decision("shw", "service water heating added",
                   inputs={"fuel": fuel, "spaces": len(sizing["spaces_w_dhw"])},
                   article="8.4.3.2. (SWH loads)")

    # Section 6.2 prescriptive rules. The booster-heater trigger is keyed on
    # the same demand this pass just sized, so it is checked here where the
    # per-space temperatures still exist — auto_size collapses them to one
    # max_temp_c and the information is gone.
    Prescriptive.check_booster_heaters(sizing, model, audit)
    Prescriptive.declare_field_verified(audit)
    return loop


def _wrap_heat_pump(model, tank, sizing, audit):
    """Air-source heat-pump water heater (8.4.4.20.(2) energy type): a pumped-
    condenser WaterHeaterHeatPump wrapping the loop tank, placed in the zone
    of the largest demanding space (the compressor draws from and rejects to
    that zone's air). The legacy family only ever COSTED HPWH tanks; the
    detailed stratified-tank/EMS recipe upstream is deliberately not ported —
    this is the bounded SDK construction, audited."""
    hpwh = openstudio.model.WaterHeaterHeatPump(model)
    hpwh.setName(f"{ruby_round(sizing['tank_volume_si'] * 1000)}L HPWH")
    default_tank = hpwh.tank()
    hpwh.setTank(tank)
    default_tank.remove()

    zone_space = max(sizing["spaces_w_dhw"],
                     key=lambda e: e["space"].floorArea())["space"]
    if zone_space.thermalZone().is_initialized():
        hpwh.addToThermalZone(zone_space.thermalZone().get())
        audit.info("shw", "HPWH compressor placed in the largest demanding space's zone",
                   target=zone_space.thermalZone().get().nameString())
    else:
        audit.warn("shw", "HPWH has no zone (largest demanding space is unzoned) — "
                          "ambient defaults apply")
    return hpwh


def _build_loop(model, sizing, fuel, rules, audit):
    loop = openstudio.model.PlantLoop(model)
    loop.setName("Main Service Water Loop")
    loop.setMaximumLoopTemperature(60.0)
    sizing_plant = loop.sizingPlant()
    sizing_plant.setLoopType("Heating")
    sizing_plant.setDesignLoopExitTemperature(sizing["max_temp_c"])
    sizing_plant.setLoopDesignTemperatureDifference(5.0)

    setpoint = _constant_schedule(
        model, f"SHW Temp {ruby_str(sizing['max_temp_c'])}C", sizing["max_temp_c"])
    manager = openstudio.model.SetpointManagerScheduled(model, setpoint)
    manager.setName("Main Service Water Loop Setpoint Manager")
    manager.addToNode(loop.supplyOutletNode())

    pump = openstudio.model.PumpConstantSpeed(model)
    pump.setName("Main Service Water Loop Pump")
    pump.setRatedPumpHead(rules["pump_head_pa"])
    pump.setMotorEfficiency(rules["pump_motor_efficiency"])
    pump.setPumpControlType("Intermittent")
    pump.addToNode(loop.supplyInletNode())
    audit.info("shw", f"pump head set to the OpenStudio constant-speed default "
                      f"{ruby_str(rules['pump_head_pa'])} Pa "
                      "(the legacy geometric piping-run head calculation is a documented future)")

    heater = openstudio.model.WaterHeaterMixed(model)
    heater.setName(f"{ruby_str(ruby_round(sizing['tank_volume_si'], 3))}m3 {fuel} Water Heater")
    heater.setTankVolume(sizing["tank_volume_si"])
    heater.setHeaterMaximumCapacity(sizing["tank_capacity_si"])
    heater.setHeaterFuelType(fuel)
    heater.setSetpointTemperatureSchedule(setpoint)
    heater.setDeadbandTemperatureDifference(2.0)
    heater.setHeaterControlType("Cycle")
    heater.setOnCycleParasiticFuelConsumptionRate(sizing["parasitic_loss_w"])
    heater.setOffCycleParasiticFuelConsumptionRate(sizing["parasitic_loss_w"])
    ambient = _constant_schedule(model, "SHW Ambient Temp 22C", 22.0)
    heater.setAmbientTemperatureIndicator("Schedule")
    heater.setAmbientTemperatureSchedule(ambient)
    loop.addSupplyBranchForComponent(heater)
    return loop


def _add_water_use(model, loop, entry, data_vintage, audit):
    space = entry["space"]
    definition = openstudio.model.WaterUseEquipmentDefinition(model)
    definition.setName(f"{space.nameString().capitalize()} Water Use Def")
    definition.setPeakFlowRate(entry["peak_flow_ind_si"])
    target = _constant_schedule(
        model, f"SHW Target {ruby_str(entry['temperature_c'])}C", entry["temperature_c"])
    definition.setTargetTemperatureSchedule(target)

    equipment = openstudio.model.WaterUseEquipment(definition)
    equipment.setName(str(space.nameString().capitalize()))
    equipment.setSpace(space)
    schedule = loads_schedules.add(model, entry["schedule"], vintage=data_vintage, audit=audit)
    equipment.setFlowRateFractionSchedule(schedule)

    connections = openstudio.model.WaterUseConnections(model)
    connections.setName(f"{space.nameString().capitalize()} WUC")
    connections.addWaterUseEquipment(equipment)
    loop.addDemandBranchForComponent(connections)
    audit.info("shw", "water use equipment added",
               target=space.nameString(),
               inputs={"peak_flow_m3_s": ruby_round(entry["peak_flow_ind_si"], 9),
                       "temperature_c": entry["temperature_c"],
                       "schedule": entry["schedule"]},
               article="8.4.3.2. (SWH loads)")


def _constant_schedule(model, name, value):
    existing = model.getScheduleRulesetByName(name)
    if existing.is_initialized():
        return existing.get()

    schedule = openstudio.model.ScheduleRuleset(model)
    schedule.setName(name)
    schedule.defaultDaySchedule().setName(f"{name} Default")
    schedule.defaultDaySchedule().addValue(openstudio.Time(0, 24, 0, 0), value)
    return schedule
