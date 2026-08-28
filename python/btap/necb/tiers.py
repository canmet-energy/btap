"""Post-comparison scoring (port of btap-necb's tiers.rb): Section 10 energy
performance tiers (Table 10.1.2.1, verified IDENTICAL in 2020 and 2025), the
NECB 2025 Part 11 operational-GHG performance levels (A-F, provincial
emission factors), and the NECB 2025 8.4.4 archetype-EUI building energy
target."""

from __future__ import annotations

import json
from pathlib import Path

from btap._compat import NullAudit, ruby_div, ruby_round

DATA_DIR = Path(__file__).parent / "data"

_eui_data: dict | None = None
_ghg_data: dict | None = None


def eui_data() -> dict:
    global _eui_data
    if _eui_data is None:
        with open(DATA_DIR / "eui_targets_2025.json", encoding="utf-8") as handle:
            _eui_data = json.load(handle)
    return _eui_data


def ghg_data() -> dict:
    global _ghg_data
    if _ghg_data is None:
        with open(DATA_DIR / "ghg_factors_2025.json", encoding="utf-8") as handle:
            _ghg_data = json.load(handle)
    return _ghg_data


def energy_tier(proposed_kwh, target_kwh, audit=None):
    """Table 10.1.2.1: Tier 1 <= 100%, Tier 2 <= 75%, Tier 3 <= 50%,
    Tier 4 < 40% of the building energy target.
    :return: {'percent_of_target':, 'tier': int|None}"""
    audit = audit or NullAudit()
    percent = ruby_div(100.0 * proposed_kwh, target_kwh)
    if percent < 40.0:
        tier = 4
    elif percent <= 50.0:
        tier = 3
    elif percent <= 75.0:
        tier = 2
    elif percent <= 100.0:
        tier = 1
    else:
        tier = None
    audit.decision(
        "compliance",
        f"energy performance Tier {tier} achieved" if tier
        else "no energy performance tier achieved (over the target)",
        inputs={"percent_of_target": ruby_round(percent, 1),
                "improvement_percent": ruby_round(100.0 - percent, 1)},
        article="10.1.2.1. (Table verified identical 2020/2025)")
    return {"percent_of_target": ruby_round(percent, 1), "tier": tier}


def eui_building_energy_target(archetype_areas, total_floor_area_m2, *, hdd,
                               process_loads_kwh=0.0, audit=None):
    """NECB 2025 8.4.4: BET = sum(A_i x EUI_i) + PL from the archetype table.

    :param archetype_areas: {archetype name: gross interior floor area m2 or
        None} — None = remainder of total_floor_area; 8.4.4.1.(4) distributes
        unlisted functions proportionally, so a single archetype covering the
        whole area is the common case.
    :return: {'bet_kwh':, 'lines': [...]}"""
    audit = audit or NullAudit()
    table = eui_data()["archetype_eui_kwh_per_m2"]
    applicability = eui_data()["applicability"]
    lines = []
    assigned = sum(a for a in archetype_areas.values() if a is not None)
    remainder = max(total_floor_area_m2 - assigned, 0.0)

    bet = float(process_loads_kwh)
    for archetype, area in archetype_areas.items():
        eui = table.get(archetype)
        if eui is None:
            raise ValueError(
                f"unknown 2025 EUI archetype '{archetype}' ({'; '.join(table.keys())})")

        area = remainder if area is None else float(area)
        bet += area * eui
        lines.append({"archetype": archetype, "area_m2": ruby_round(area, 1),
                      "eui": eui, "kwh": ruby_round(area * eui, 1)})

    if hdd is not None and hdd >= applicability["max_hdd"]:
        audit.warn(
            "compliance",
            f"8.4.4 EUI path is NOT applicable at HDD {hdd} (Table 8.4.4.1 "
            f"note: HDD < {applicability['max_hdd']})",
            article="8.4.4.1.")
    covered = ruby_div(sum(line["area_m2"] for line in lines), total_floor_area_m2)
    if covered < applicability["min_archetype_floor_fraction"] - 1e-6:
        audit.warn(
            "compliance",
            f"only {ruby_round(covered * 100, 1)}% of floor area is assigned to "
            "archetypes — 8.4.4.1.(1) requires >= 90% "
            "(8.4.4.1.(4) permits distributing unlisted space functions "
            "proportionally among the listed archetypes)",
            article="8.4.4.1.(1); 8.4.4.1.(4)")
    audit.decision(
        "compliance",
        "building energy target computed from archetype EUIs (2025 8.4.4 path)",
        inputs={"lines": lines,
                "process_loads_kwh": ruby_round(float(process_loads_kwh), 1)},
        value=f"BET = {ruby_round(bet, 1)} kWh/year",
        article="8.4.4.1.(2); Table 8.4.4.1.")
    return {"bet_kwh": ruby_round(bet, 1), "lines": lines}


def operational_ghg_kg(energy, province_state):
    """NECB 2025 Part 11: operational GHG from the annual fuel totals.

    :param energy: a runner.energy_results dict (kWh by fuel)
    :return: kg CO2e/yr, or None when the province has no factors"""
    province = str(province_state).upper()
    elec = ghg_data()["electricity_g_per_kwh"].get(province)
    gas = ghg_data()["utility_gas_g_per_kwh"].get(province)
    if elec is None or gas is None:
        return None

    grams = ((energy.get("electricity_kwh") or 0) * elec
             + (energy.get("natural_gas_kwh") or 0) * gas)
    return ruby_round(grams / 1000.0, 1)


def ghg_level(proposed_kg, reference_kg, audit=None):
    """The A-F performance level from the proposed/reference GHG ratio."""
    audit = audit or NullAudit()
    percent = ruby_div(100.0 * proposed_kg, reference_kg)
    level = next((name for name, cap in ghg_data()["levels"] if percent <= cap), None)
    audit.decision(
        "compliance",
        f"operational GHG performance level {level}" if level
        else "no GHG performance level (over the reference GHG target)",
        inputs={"proposed_kg_co2e": proposed_kg, "reference_kg_co2e": reference_kg,
                "percent_of_ghg_target": ruby_round(percent, 1)},
        article="11.4.1.1.; 11.4.2.1. (NECB 2025)")
    return {"percent_of_ghg_target": ruby_round(percent, 1), "level": level}
