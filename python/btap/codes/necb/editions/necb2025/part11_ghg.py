"""NECB 2025 Part 11 operational-GHG performance levels (A-F, provincial
emission factors) — the 2025-only third of the former ``tiers.py`` (port of
btap-necb's tiers.rb), moved to ``editions/necb2025/`` under D-86 with no
change to its arithmetic."""

from __future__ import annotations

import json

from btap._compat import NullAudit, ruby_div, ruby_round
from btap.codes.necb import _data_root, edition_file

#: Cached per data root; this module IS the 2025 edition.
_ghg_data: dict[object, dict] = {}


def ghg_data() -> dict:
    root = _data_root()
    if root not in _ghg_data:
        with open(edition_file("2025", "ghg_factors.json"), encoding="utf-8") as handle:
            _ghg_data[root] = json.load(handle)
    return _ghg_data[root]


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
