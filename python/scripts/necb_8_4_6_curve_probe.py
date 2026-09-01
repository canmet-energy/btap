#!/usr/bin/env python3
"""Verify model-applied NECB 8.4.6 curves against the 2025 coefficients.

This is the native Python counterpart of ``btap-necb/scripts/
necb_8_4_6_curve_probe.rb``. It builds real OpenStudio components, runs the
Python efficiency appliers, reads the curves back from the model, and compares
the applied functions under the same unit/form transforms as the Ruby probe.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import openstudio  # noqa: E402

from btap.audit import AuditLog  # noqa: E402
from btap.modeling.hvac.systems import plant_loops  # noqa: E402
from btap.necb import shw  # noqa: E402
from btap.necb.hvac import efficiency as hvac_efficiency  # noqa: E402

TOL_SAMPLED = 0.03
TOL_SURFACE = 0.005
PLR_GRID = [percent / 100.0 for percent in range(25, 101, 5)]
SURFACE_GRID_F = [
    (float(wet_bulb), float(dry_bulb))
    for wet_bulb in range(57, 73, 3)
    for dry_bulb in range(65, 116, 10)
]
CHILLER_SURFACE_GRID_F = [
    (float(chilled_water), float(condenser_water))
    for chilled_water in range(41, 50, 2)
    for condenser_water in range(75, 96, 5)
]
ASHP_ODB_GRID_F = [float(temperature) for temperature in range(-4, 69, 8)]

BOILER_FHEATPLC = {
    "Non-condensing": [0.082597, 0.996764, -0.079361],
    "Modulating": [0.01798667, 0.96742420, 0.01545455],
}
FURNACE_FHEATPLC = {
    "Atmospheric": [0.0186100, 1.0942090, -0.1128190],
    "Condensing": [0.00533, 0.904, 0.09066],
    "Modulating": [0.01798667, 0.96742420, 0.01545455],
}
SWH_FHEATPLC = [0.021826, 0.977630, 0.000543]
DX_CAP_FT_F = [0.8740302, -0.0011416, 0.0001711, -0.0029570, 0.0000102, -0.0000592]
DX_EIR_FT_F = [-1.0639310, 0.0306584, -0.0001269, 0.0154213, 0.0000497, -0.0002096]
DX_EIR_FPLR = [0.2012301, -0.0312175, 1.9504979, -1.1205105]
RATING_F = [67.0, 95.0]

CHILLER_CAP_FT_EC_F = {
    "Scroll": [0.36131454, 0.01855477, 0.00003011, 0.00093592, -0.00001518, -0.00005481],
    "Reciprocating": [0.58531422, 0.01539593, 0.00007296, -0.00212462, -0.00000715, -0.00004597],
    "Rotary Screw": [0.332669598, 0.00729116, -0.00049938, 0.01598983, -0.00028254, 0.00052346],
    "Centrifugal": [-0.29861975, 0.02996076, -0.00080125, 0.01736268, -0.00032606, 0.00063139],
}
CHILLER_CAP_FT_RATING_EXPECTED = {"Rotary Screw": 0.9622, "Centrifugal": 0.9499}
CHILLER_EIR_FPLR = {
    "Scroll": [0.04411957, 0.64036703, 0.31955532],
    "Reciprocating": [0.08144133, 0.41927141, 0.49939604],
    "Rotary Screw": [0.33018833, 0.23554291, 0.46070828],
    "Centrifugal": [0.17149273, 0.58820208, 0.23737257],
}
CHILLER_EIR_FT_EC_F_ERRATUM = {
    "Scroll": [1.00121431, -0.01026981, 0.00016703, -0.00128136, 0.00014613, -0.00021959],
    "Reciprocating": [0.46140041, -0.00882156, 0.00008223, 0.00926607, 0.00005722, -0.00011594],
}
CHILLER_EIR_FT_EC_F_PRINTED = {
    "Rotary Screw": [0.66625406, 0.00068584, 0.00028496, -0.00341677, 0.00025484, -0.00048195],
    "Centrifugal": [0.51777196, -0.00400363, 0.00002026, 0.00698793, 0.0000829, -0.00015467],
}
CHILLER_RATING_F = [44.0, 85.0]
CHILLER_FPLR_RATING_EXPECTED = {"Rotary Screw": 1.0264}

TOWER_FWB_F = [0.60531402, -0.03554536, 0.00804083, -0.02860259, 0.00024972, 0.00490857]
TOWER_FRA_F = [-2.22888899, 0.16679543, -0.01410247, 0.03222333, 0.18560214, 0.24251871]
TOWER_RATING_F = [78.0, 10.0, 7.0]
TOWER_CTI_C = {
    "twb": (78.0 - 32.0) / 1.8,
    "tw_in": (95.0 - 32.0) / 1.8,
    "tw_out": (85.0 - 32.0) / 1.8,
}
TOWER_LG = 1.25
TOWER_GATE_GRID_F = [
    (78.0, tower_range, approach)
    for tower_range in (6.0, 10.0, 14.0)
    for approach in (5.0, 7.0, 10.0, 14.0)
]
TOWER_FULL_GRID_F = [
    (wet_bulb, tower_range, approach)
    for wet_bulb in (50.0, 60.0, 68.0, 78.0)
    for tower_range in (6.0, 10.0, 14.0)
    for approach in (5.0, 7.0, 10.0, 14.0)
]
TOL_TOWER_ANCHOR = 0.15

ASHP_CAP_FT_EAS_F = [0.2536714, 0.0104351, 0.0001861, -0.0000015]
ASHP_EIR_FT_F = [2.4600298, -0.0622539, 0.0008800, -0.0000046]
ASHP_EIR_FPLR = [0.0856522, 0.9388137, -0.1834361, 0.1589702]
ASHP_RATING_F = 47.0

HONEST_GAP = (
    "NOT YET COMPARED (still honest gaps): Table 8.4.6.2 condensing-boiler 6-term row "
    "(bivariate in PLR + water temp; no reference build selects the condensing curve). "
    "8.4.6.8 has an explicit NOT APPLICABLE line above, not silence. "
    "8.4.6.6 is a numeric NTU cross-check (no curve field exists), gated on the "
    "CTI-anchored slice."
)


def poly(coefficients: list[float], value: float) -> float:
    return sum(coefficient * value**index for index, coefficient in enumerate(coefficients))


def biquad(coefficients: list[float], first: float, second: float) -> float:
    return (
        coefficients[0]
        + coefficients[1] * first
        + coefficients[2] * first**2
        + coefficients[3] * second
        + coefficients[4] * second**2
        + coefficients[5] * first * second
    )


def f_to_c_biquad(coefficients: list[float]) -> list[float]:
    constant, first, first_squared, second, second_squared, cross = coefficients
    return [
        constant + 32 * first + 1024 * first_squared + 32 * second
        + 1024 * second_squared + 1024 * cross,
        1.8 * first + 115.2 * first_squared + 57.6 * cross,
        3.24 * first_squared,
        1.8 * second + 115.2 * second_squared + 57.6 * cross,
        3.24 * second_squared,
        3.24 * cross,
    ]


def f_to_c_cubic(coefficients: list[float]) -> list[float]:
    constant, linear, squared, cubic = coefficients
    return [
        constant + 32 * linear + 1024 * squared + 32_768 * cubic,
        1.8 * linear + 115.2 * squared + 5529.6 * cubic,
        3.24 * squared + 311.04 * cubic,
        5.832 * cubic,
    ]


def tower_fra(tower_range: float, approach: float) -> float | None:
    constant, range_linear, range_squared, flow_linear, flow_squared, cross = TOWER_FRA_F
    linear = flow_linear + cross * tower_range
    discriminant = linear**2 - 4.0 * flow_squared * (
        constant + range_linear * tower_range + range_squared * tower_range**2 - approach
    )
    if discriminant < 0:
        return None
    return (-linear + math.sqrt(discriminant)) / (2.0 * flow_squared)


def tower_fwb(wet_bulb: float, tower_range: float, approach: float) -> float | None:
    flow_ratio = tower_fra(tower_range, approach)
    if flow_ratio is None:
        return None
    constant, flow_linear, flow_squared, wb_linear, wb_squared, cross = TOWER_FWB_F
    return (
        constant
        + flow_linear * flow_ratio
        + flow_squared * flow_ratio**2
        + wb_linear * wet_bulb
        + wb_squared * wet_bulb**2
        + cross * flow_ratio * wet_bulb
    )


def coefficient_registry() -> dict[str, Any]:
    return {
        "BOILER_FHEATPLC": BOILER_FHEATPLC,
        "FURNACE_FHEATPLC": FURNACE_FHEATPLC,
        "SWH_FHEATPLC": SWH_FHEATPLC,
        "DX_CAP_FT_F": DX_CAP_FT_F,
        "DX_EIR_FT_F": DX_EIR_FT_F,
        "DX_EIR_FPLR": DX_EIR_FPLR,
        "CHILLER_CAP_FT_EC_F": CHILLER_CAP_FT_EC_F,
        "CHILLER_EIR_FPLR": CHILLER_EIR_FPLR,
        "CHILLER_EIR_FT_EC_F_ERRATUM": CHILLER_EIR_FT_EC_F_ERRATUM,
        "CHILLER_EIR_FT_EC_F_PRINTED": CHILLER_EIR_FT_EC_F_PRINTED,
        "TOWER_FWB_F": TOWER_FWB_F,
        "TOWER_FRA_F": TOWER_FRA_F,
        "ASHP_CAP_FT_EAS_F": ASHP_CAP_FT_EAS_F,
        "ASHP_EIR_FT_F": ASHP_EIR_FT_F,
        "ASHP_EIR_FPLR": ASHP_EIR_FPLR,
    }


def run_self_checks() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def check(label: str, value: float, expected: float = 1.0) -> None:
        deviation = abs(value / expected - 1.0)
        passed = deviation < 0.005
        checks.append({
            "label": label,
            "value": value,
            "expected": expected,
            "relative_deviation": deviation,
            "tolerance": 0.005,
            "passed": passed,
        })
        if not passed:
            raise RuntimeError(
                f"PROBE TRANSCRIPTION SUSPECT: {label} evaluates to {value:.4f} at its rating "
                "point (expected ~1.0) - refusing to compare against possibly mis-transcribed "
                "code coefficients"
            )

    check("8.4.6.4 CAP_FT", biquad(DX_CAP_FT_F, *RATING_F))
    check("8.4.6.4 EIR_FT", biquad(DX_EIR_FT_F, *RATING_F))
    check("8.4.6.4 EIR_FPLR", poly(DX_EIR_FPLR, 1.0))
    combined_fheatplc = BOILER_FHEATPLC | FURNACE_FHEATPLC
    for equipment_type, coefficients in combined_fheatplc.items():
        check(f"FHeatPLC {equipment_type}", poly(coefficients, 1.0))
    check("8.4.6.9 SWH FHeatPLC", poly(SWH_FHEATPLC, 1.0))
    for equipment_type, coefficients in CHILLER_CAP_FT_EC_F.items():
        expected = CHILLER_CAP_FT_RATING_EXPECTED.get(equipment_type, 1.0)
        check(f"8.4.6.5 CAP_FT {equipment_type}", biquad(coefficients, *CHILLER_RATING_F), expected)
    for equipment_type, coefficients in CHILLER_EIR_FPLR.items():
        expected = CHILLER_FPLR_RATING_EXPECTED.get(equipment_type, 1.0)
        check(f"8.4.6.5 EIR_FPLR {equipment_type}", poly(coefficients, 1.0), expected)
    for equipment_type, coefficients in CHILLER_EIR_FT_EC_F_ERRATUM.items():
        check(f"8.4.6.5 EIR_FT (erratum) {equipment_type}",
              biquad(coefficients, *CHILLER_RATING_F))
    for equipment_type, coefficients in CHILLER_EIR_FT_EC_F_PRINTED.items():
        check(f"8.4.6.5 EIR_FT (printed) {equipment_type}",
              biquad(coefficients, *CHILLER_RATING_F))
    check("8.4.6.6 Tower FWB", tower_fwb(*TOWER_RATING_F))
    check("8.4.6.7 CAP_FTEAS", poly(ASHP_CAP_FT_EAS_F, ASHP_RATING_F))
    check("8.4.6.7 EIR_FT", poly(ASHP_EIR_FT_F, ASHP_RATING_F))
    check("8.4.6.7 EIR_FPLR", poly(ASHP_EIR_FPLR, 1.0))
    return checks


def curve_coeffs(curve: Any) -> list[float] | None:
    cubic = curve.to_CurveCubic()
    if cubic.is_initialized():
        value = cubic.get()
        return [
            value.coefficient1Constant(), value.coefficient2x(),
            value.coefficient3xPOW2(), value.coefficient4xPOW3(),
        ]
    quadratic = curve.to_CurveQuadratic()
    if quadratic.is_initialized():
        value = quadratic.get()
        return [
            value.coefficient1Constant(), value.coefficient2x(), value.coefficient3xPOW2(),
        ]
    biquadratic = curve.to_CurveBiquadratic()
    if biquadratic.is_initialized():
        value = biquadratic.get()
        return [
            value.coefficient1Constant(), value.coefficient2x(), value.coefficient3xPOW2(),
            value.coefficient4y(), value.coefficient5yPOW2(), value.coefficient6xTIMESY(),
        ]
    return None


def optional_curve_coeffs(optional_curve: Any) -> list[float] | None:
    return curve_coeffs(optional_curve.get()) if optional_curve.is_initialized() else None


def missing_result(article: str, label: str) -> dict[str, Any]:
    return {
        "article": article,
        "label": label,
        "verdict": "MISSING",
        "detail": "no curve attached",
        "metrics": {},
        "applied_coefficients": None,
    }


def compare_fheatplc(
    article: str,
    label: str,
    applied: list[float] | None,
    code_rows: dict[str, list[float]],
) -> dict[str, Any]:
    if applied is None:
        return missing_result(article, label)
    candidates = []
    for equipment_type, target in code_rows.items():
        deviations = []
        for part_load_ratio in PLR_GRID:
            efficiency = poly(applied, part_load_ratio)
            if efficiency <= 0:
                deviations.append(999.0)
            else:
                code_value = poly(target, part_load_ratio)
                deviations.append(abs(part_load_ratio / efficiency - code_value) / code_value)
        candidates.append((equipment_type, max(deviations)))
    matched_row, max_deviation = min(candidates, key=lambda candidate: candidate[1])
    verdict = "EQUIVALENT" if max_deviation <= TOL_SAMPLED else "DEVIATES"
    return {
        "article": article,
        "label": label,
        "verdict": verdict,
        "detail": (
            f"vs {matched_row} row: max dev {max_deviation * 100:.2f}% over PLR "
            f"{PLR_GRID[0]:.2f}-1.0 (tol {TOL_SAMPLED * 100:.0f}%)"
        ),
        "metrics": {
            "max_relative_deviation": max_deviation,
            "plr_min": PLR_GRID[0],
            "plr_max": PLR_GRID[-1],
            "sample_count": len(PLR_GRID),
            "tolerance": TOL_SAMPLED,
        },
        "matched_row": matched_row,
        "applied_coefficients": applied,
        "target_coefficients": code_rows[matched_row],
    }


def compare_biquad_transform(
    article: str,
    label: str,
    applied: list[float] | None,
    code_f: list[float],
    grid: list[tuple[float, float]] = SURFACE_GRID_F,
    axis_labels: tuple[str, str] = ("wb", "odb"),
) -> dict[str, Any]:
    if applied is None:
        return missing_result(article, label)
    worst_deviation = 0.0
    worst_at: tuple[float, float] | None = None
    compared = 0
    for first_f, second_f in grid:
        code_value = biquad(code_f, first_f, second_f)
        applied_value = biquad(applied, (first_f - 32.0) / 1.8, (second_f - 32.0) / 1.8)
        if abs(code_value) < 0.05:
            continue
        compared += 1
        deviation = abs(applied_value - code_value) / abs(code_value)
        if deviation > worst_deviation:
            worst_deviation = deviation
            worst_at = (first_f, second_f)
    verdict = "EQUIVALENT (surface)" if worst_deviation <= TOL_SURFACE else "DEVIATES"
    first_at = worst_at[0] if worst_at else None
    second_at = worst_at[1] if worst_at else None
    return {
        "article": article,
        "label": label,
        "verdict": verdict,
        "detail": (
            f"max surface dev {worst_deviation * 100:.2f}% (at {first_at}{axis_labels[0]}/"
            f"{second_at}{axis_labels[1]}F; tol {TOL_SURFACE * 100:.1f}%)"
        ),
        "metrics": {
            "max_relative_deviation": worst_deviation,
            "worst_at_f": list(worst_at) if worst_at else None,
            "sample_count": compared,
            "tolerance": TOL_SURFACE,
        },
        "axis_labels": list(axis_labels),
        "applied_coefficients": applied,
        "target_coefficients_f": code_f,
        "target_coefficients_c": f_to_c_biquad(code_f),
    }


def compare_cubic_transform(
    article: str,
    label: str,
    applied: list[float] | None,
    code_f: list[float],
    grid: list[float],
) -> dict[str, Any]:
    if applied is None:
        return missing_result(article, label)
    worst_deviation = 0.0
    worst_at = None
    compared = 0
    for temperature_f in grid:
        code_value = poly(code_f, temperature_f)
        applied_value = poly(applied, (temperature_f - 32.0) / 1.8)
        if abs(code_value) < 0.05:
            continue
        compared += 1
        deviation = abs(applied_value - code_value) / abs(code_value)
        if deviation > worst_deviation:
            worst_deviation = deviation
            worst_at = temperature_f
    verdict = "EQUIVALENT (surface)" if worst_deviation <= TOL_SURFACE else "DEVIATES"
    return {
        "article": article,
        "label": label,
        "verdict": verdict,
        "detail": (
            f"max surface dev {worst_deviation * 100:.2f}% (at {worst_at}F odb; "
            f"tol {TOL_SURFACE * 100:.1f}%)"
        ),
        "metrics": {
            "max_relative_deviation": worst_deviation,
            "worst_at_f": worst_at,
            "sample_count": compared,
            "tolerance": TOL_SURFACE,
        },
        "applied_coefficients": applied,
        "target_coefficients_f": code_f,
        "target_coefficients_c": f_to_c_cubic(code_f),
    }


def compare_direct_poly(
    article: str,
    label: str,
    applied: list[float] | None,
    code_rows: dict[str, list[float]],
) -> dict[str, Any]:
    if applied is None:
        return missing_result(article, label)
    candidates = []
    for equipment_type, target in code_rows.items():
        deviations = [
            abs(poly(applied, part_load_ratio) - poly(target, part_load_ratio))
            / poly(target, part_load_ratio)
            for part_load_ratio in PLR_GRID
        ]
        candidates.append((equipment_type, max(deviations)))
    matched_row, max_deviation = min(candidates, key=lambda candidate: candidate[1])
    verdict = "EQUIVALENT" if max_deviation <= TOL_SAMPLED else "DEVIATES"
    return {
        "article": article,
        "label": label,
        "verdict": verdict,
        "detail": (
            f"vs {matched_row} row: max dev {max_deviation * 100:.2f}% over PLR "
            f"{PLR_GRID[0]:.2f}-1.0 (tol {TOL_SAMPLED * 100:.0f}%)"
        ),
        "metrics": {
            "max_relative_deviation": max_deviation,
            "plr_min": PLR_GRID[0],
            "plr_max": PLR_GRID[-1],
            "sample_count": len(PLR_GRID),
            "tolerance": TOL_SAMPLED,
        },
        "matched_row": matched_row,
        "applied_coefficients": applied,
        "target_coefficients": code_rows[matched_row],
    }


def tower_cross_check() -> dict[str, Any]:
    def saturation_pressure(temperature: float) -> float:
        return 0.61121 * math.exp(
            (18.678 - temperature / 234.5) * temperature / (257.14 + temperature)
        )

    def saturated_enthalpy(temperature: float) -> float:
        pressure = saturation_pressure(temperature)
        humidity_ratio = 0.621945 * pressure / (101.325 - pressure)
        return 1.006 * temperature + humidity_ratio * (2501.0 + 1.86 * temperature)

    water_specific_heat = 4.186

    def tower_heat(ua: float, water_flow: float, air_flow: float,
                   water_in: float, wet_bulb_in: float) -> float:
        saturated_air_specific_heat = 4.0
        heat = 0.0
        for _iteration in range(40):
            air_capacity = air_flow * saturated_air_specific_heat
            water_capacity = water_flow * water_specific_heat
            minimum_capacity = min(air_capacity, water_capacity)
            maximum_capacity = max(air_capacity, water_capacity)
            capacity_ratio = minimum_capacity / maximum_capacity
            ntu = ua / minimum_capacity
            if abs(capacity_ratio - 1.0) < 1e-6:
                effectiveness = ntu / (1.0 + ntu)
            else:
                exponent = math.exp(-ntu * (1.0 - capacity_ratio))
                effectiveness = (1.0 - exponent) / (1.0 - capacity_ratio * exponent)
            heat = effectiveness * minimum_capacity * (water_in - wet_bulb_in)
            wet_bulb_out = wet_bulb_in + heat / air_capacity
            new_specific_heat = (
                (saturated_enthalpy(wet_bulb_out) - saturated_enthalpy(wet_bulb_in))
                / (wet_bulb_out - wet_bulb_in)
            )
            if abs(new_specific_heat - saturated_air_specific_heat) < 1e-6:
                break
            saturated_air_specific_heat = new_specific_heat
        return heat

    rated_heat = 100.0
    rated_water_flow = rated_heat / (
        water_specific_heat * (TOWER_CTI_C["tw_in"] - TOWER_CTI_C["tw_out"])
    )
    rated_air_flow = rated_water_flow / TOWER_LG
    lower, upper = 0.1, 10_000.0
    for _iteration in range(60):
        middle = math.sqrt(lower * upper)
        heat = tower_heat(
            middle, rated_water_flow, rated_air_flow, TOWER_CTI_C["tw_in"], TOWER_CTI_C["twb"]
        )
        if heat < rated_heat:
            lower = middle
        else:
            upper = middle
    ua = math.sqrt(lower * upper)

    def ntu_flow_ratio(wet_bulb_f: float, tower_range_f: float, approach_f: float) -> float:
        wet_bulb = (wet_bulb_f - 32.0) / 1.8
        water_out = (wet_bulb_f + approach_f - 32.0) / 1.8
        water_in = (wet_bulb_f + approach_f + tower_range_f - 32.0) / 1.8
        lower_flow, upper_flow = 0.01, 8.0
        for _iteration in range(50):
            middle_flow = math.sqrt(lower_flow * upper_flow)
            heat = tower_heat(
                ua, middle_flow * rated_water_flow, rated_air_flow, water_in, wet_bulb
            )
            calculated_out = water_in - heat / (
                middle_flow * rated_water_flow * water_specific_heat
            )
            if calculated_out <= water_out:
                lower_flow = middle_flow
            else:
                upper_flow = middle_flow
        return math.sqrt(lower_flow * upper_flow)

    def deviations(grid: list[tuple[float, float, float]]) -> list[float]:
        values = []
        for wet_bulb_f, tower_range_f, approach_f in grid:
            code_value = tower_fwb(wet_bulb_f, tower_range_f, approach_f)
            if code_value is None or code_value < 0.2 or code_value > 3.0:
                continue
            values.append(
                (ntu_flow_ratio(wet_bulb_f, tower_range_f, approach_f) - code_value)
                / code_value
            )
        return values

    anchor_deviations = deviations(TOWER_GATE_GRID_F)
    full_deviations = deviations(TOWER_FULL_GRID_F)
    anchor_max = max(abs(value) for value in anchor_deviations)
    full_absolute = [abs(value) for value in full_deviations]
    full_mean = sum(full_absolute) / len(full_absolute)
    full_max = max(full_absolute)
    verdict = "ENGINE-EQUIVALENT (NTU)" if anchor_max <= TOL_TOWER_ANCHOR else "DEVIATES"
    return {
        "article": "8.4.6.6",
        "label": "Cooling Tower FWB vs E+ effectiveness-NTU",
        "verdict": verdict,
        "detail": (
            f"CTI-anchored slice (78F wb): max dev {anchor_max * 100:.1f}% "
            f"(tol {TOL_TOWER_ANCHOR * 100:.0f}%); full envelope "
            f"(50-78F wb, n={len(full_absolute)}): mean {full_mean * 100:.0f}%, "
            f"max {full_max * 100:.0f}% - code fit is conservative at cold wet-bulb "
            f"where capacity never binds; L/G={TOWER_LG:.2f}"
        ),
        "metrics": {
            "anchor_max_relative_deviation": anchor_max,
            "anchor_sample_count": len(anchor_deviations),
            "anchor_tolerance": TOL_TOWER_ANCHOR,
            "full_mean_absolute_relative_deviation": full_mean,
            "full_max_absolute_relative_deviation": full_max,
            "full_sample_count": len(full_absolute),
            "liquid_gas_mass_flow_ratio": TOWER_LG,
            "rated_heat_kw": rated_heat,
            "rated_water_flow_kg_s": rated_water_flow,
            "rated_air_flow_kg_s": rated_air_flow,
            "sized_ua_kw_k": ua,
        },
        "applied_coefficients": None,
        "target_coefficients_f": TOWER_FWB_F,
        "fra_coefficients_f": TOWER_FRA_F,
    }


def build_and_apply() -> dict[str, Any]:
    model = openstudio.model.Model()
    audit = AuditLog()

    boiler = openstudio.model.BoilerHotWater(model)
    boiler.setName("Probe Boiler")
    boiler.setFuelType("NaturalGas")
    boiler.setNominalCapacity(100_000)

    gas_coil = openstudio.model.CoilHeatingGas(model)
    gas_coil.setName("Probe Furnace Coil")
    gas_coil.setNominalCapacity(50_000)

    dx_coil = openstudio.model.CoilCoolingDXSingleSpeed(model)
    dx_coil.setName("Probe DX Coil")
    dx_coil.setRatedTotalCoolingCapacity(20_000)
    dx_coil.setRatedAirFlowRate(1.0)

    chillers = {}
    for chiller_type in CHILLER_CAP_FT_EC_F:
        chilled_water_loop = plant_loops.chilled_water(
            model, chiller_type=chiller_type, reuse=False, source="water_cooled"
        )
        loop_chillers = []
        for component in chilled_water_loop.supplyComponents():
            optional_chiller = component.to_ChillerElectricEIR()
            if optional_chiller.is_initialized():
                chiller = optional_chiller.get()
                chiller.setReferenceCapacity(200_000)
                loop_chillers.append(chiller)
        chillers[chiller_type] = next(
            chiller for chiller in loop_chillers if "Primary" in chiller.nameString()
        )

    ashp_heat = openstudio.model.CoilHeatingDXSingleSpeed(model)
    ashp_heat.setName("Probe ASHP Heating Coil")
    ashp_heat.setRatedTotalHeatingCapacity(15_000)

    hvac_efficiency.apply_efficiencies(model, vintage="2020", audit=audit)

    swh_model = openstudio.model.Model()
    heater = openstudio.model.WaterHeaterMixed(swh_model)
    heater.setHeaterFuelType("NaturalGas")
    heater.setHeaterMaximumCapacity(30_000)
    heater.setTankVolume(0.3)
    shw.apply_water_heater_efficiency(heater, vintage="2020", audit=AuditLog())

    return {
        "model": model,
        "swh_model": swh_model,
        "boiler": boiler,
        "gas_coil": gas_coil,
        "dx_coil": dx_coil,
        "chillers": chillers,
        "ashp_heat": ashp_heat,
        "heater": heater,
        "model_application": {
            "hvac": "btap.necb.hvac.efficiency.apply_efficiencies",
            "shw": "btap.necb.shw.apply_water_heater_efficiency",
            "chiller_topology": "btap.modeling.hvac.systems.plant_loops.chilled_water",
            "vintage": "2020",
            "model_level": True,
        },
    }


def run_probe() -> dict[str, Any]:
    self_checks = run_self_checks()
    applied = build_and_apply()
    boiler = applied["boiler"]
    gas_coil = applied["gas_coil"]
    dx_coil = applied["dx_coil"]
    heater = applied["heater"]
    ashp_heat = applied["ashp_heat"]
    results: list[dict[str, Any]] = []

    results.append(compare_fheatplc(
        "8.4.6.2", "Boiler FHeatPLC (via normalized efficiency curve)",
        optional_curve_coeffs(boiler.normalizedBoilerEfficiencyCurve()), BOILER_FHEATPLC,
    ))
    results.append(compare_fheatplc(
        "8.4.6.3", "Furnace FHeatPLC (via PLF curve on gas coil)",
        optional_curve_coeffs(gas_coil.partLoadFractionCorrelationCurve()), FURNACE_FHEATPLC,
    ))
    results.append(compare_biquad_transform(
        "8.4.6.4", "DX CAP_FT",
        curve_coeffs(dx_coil.totalCoolingCapacityFunctionOfTemperatureCurve()), DX_CAP_FT_F,
    ))
    results.append(compare_biquad_transform(
        "8.4.6.4", "DX EIR_FT",
        curve_coeffs(dx_coil.energyInputRatioFunctionOfTemperatureCurve()), DX_EIR_FT_F,
    ))
    results.append(compare_fheatplc(
        "8.4.6.4", "DX EIR_FPLR (via PLF cycling curve)",
        curve_coeffs(dx_coil.partLoadFractionCorrelationCurve()), {"EIR_FPLR": DX_EIR_FPLR},
    ))
    results.append(compare_fheatplc(
        "8.4.6.9", "SWH FHeatPLC (via part-load factor curve)",
        optional_curve_coeffs(heater.partLoadFactorCurve()), {"SWH": SWH_FHEATPLC},
    ))

    for chiller_type, chiller in applied["chillers"].items():
        results.append(compare_biquad_transform(
            "8.4.6.5", f"Chiller CAP_FT ({chiller_type})",
            curve_coeffs(chiller.coolingCapacityFunctionOfTemperature()),
            CHILLER_CAP_FT_EC_F[chiller_type], CHILLER_SURFACE_GRID_F, ("chws", "cws"),
        ))
        results.append(compare_direct_poly(
            "8.4.6.5", f"Chiller EIR_FPLR ({chiller_type}, direct PLR multiplier)",
            curve_coeffs(chiller.electricInputToCoolingOutputRatioFunctionOfPLR()),
            {chiller_type: CHILLER_EIR_FPLR[chiller_type]},
        ))
        if chiller_type in CHILLER_EIR_FT_EC_F_ERRATUM:
            target = CHILLER_EIR_FT_EC_F_ERRATUM[chiller_type]
            target_label = "vs proposed erratum"
        else:
            target = CHILLER_EIR_FT_EC_F_PRINTED[chiller_type]
            target_label = "printed rows"
        results.append(compare_biquad_transform(
            "8.4.6.5", f"Chiller EIR_FT ({chiller_type}, {target_label})",
            curve_coeffs(chiller.electricInputToCoolingOutputRatioFunctionOfTemperature()),
            target, CHILLER_SURFACE_GRID_F, ("chws", "cws"),
        ))

    results.append(tower_cross_check())
    results.append(compare_cubic_transform(
        "8.4.6.7", "ASHP CAP_FTEAS",
        curve_coeffs(ashp_heat.totalHeatingCapacityFunctionofTemperatureCurve()),
        ASHP_CAP_FT_EAS_F, ASHP_ODB_GRID_F,
    ))
    results.append(compare_cubic_transform(
        "8.4.6.7", "ASHP EIR_FT",
        curve_coeffs(ashp_heat.energyInputRatioFunctionofTemperatureCurve()),
        ASHP_EIR_FT_F, ASHP_ODB_GRID_F,
    ))
    results.append(compare_fheatplc(
        "8.4.6.7", "ASHP EIR_FPLR (via PLF cycling curve)",
        curve_coeffs(ashp_heat.partLoadFractionCorrelationCurve()),
        {"EIR_FPLR": ASHP_EIR_FPLR},
    ))
    results.append({
        "article": "8.4.6.8",
        "label": "Absorption Chiller CAP_FT/FIR_FPLR/FIR_FT",
        "verdict": "NOT APPLICABLE",
        "detail": (
            "no absorption row in tables['chillers'], no absorption curves vendored, "
            "apply_chiller never selects an absorption compressor type"
        ),
        "metrics": {},
        "applied_coefficients": None,
    })

    failures = sum(result["verdict"] in {"MISSING", "DEVIATES"} for result in results)
    return {
        "probe": "necb_8_4_6_curve_probe",
        "title": "NECB 8.4.6 part-load curve probe - as-applied model curves vs NECB 2025 coefficients",
        "status": "OK" if failures == 0 else "FAILED",
        "failure_count": failures,
        "exit_code": 0 if failures == 0 else 1,
        "tolerances": {
            "sampled_relative": TOL_SAMPLED,
            "temperature_surface_relative": TOL_SURFACE,
            "tower_anchor_relative": TOL_TOWER_ANCHOR,
            "self_check_relative": 0.005,
        },
        "coefficients": coefficient_registry(),
        "self_checks": self_checks,
        "model_application": applied["model_application"],
        "results": results,
        "honest_gap": HONEST_GAP,
    }


def print_text(report: dict[str, Any]) -> None:
    print(report["title"])
    print()
    for result in report["results"]:
        print(
            f"  {result['article']:<9} {result['label']:<48} "
            f"{result['verdict']:<28} {result['detail']}"
        )
    print()
    print(f"  {report['honest_gap']}")
    print()
    if report["failure_count"] == 0:
        print("necb_8_4_6_curve_probe: OK - every compared curve is applied and equivalent")
    else:
        print(
            f"necb_8_4_6_curve_probe: {report['failure_count']} curve(s) missing or deviating"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit structured JSON")
    args = parser.parse_args(argv)
    if args.json:
        openstudio.Logger.instance().standardOutLogger().setLogLevel(openstudio.Fatal)
    try:
        report = run_probe()
    except RuntimeError as error:
        if args.json:
            print(json.dumps({
                "probe": "necb_8_4_6_curve_probe",
                "status": "TRANSCRIPTION SUSPECT",
                "failure_count": 1,
                "exit_code": 1,
                "error": str(error),
            }, indent=2, sort_keys=True))
        else:
            print(error, file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_text(report)
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())