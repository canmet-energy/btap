"""Focused non-vacuity and conformance gate for the native 8.4.6 probe."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parents[2]
PROBE = PYTHON_ROOT / "scripts" / "necb_8_4_6_curve_probe.py"


def test_curve_probe_json_is_complete_and_current() -> None:
    completed = subprocess.run(
        [sys.executable, str(PROBE), "--json"],
        cwd=PYTHON_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    report = json.loads(completed.stdout)

    assert report["exit_code"] == 0
    assert report["failure_count"] == 0
    assert report["status"] == "OK"
    assert len(report["self_checks"]) == 24
    assert all(check["passed"] for check in report["self_checks"])

    expected_labels = {
        "Boiler FHeatPLC (via normalized efficiency curve)",
        "Furnace FHeatPLC (via PLF curve on gas coil)",
        "DX CAP_FT",
        "DX EIR_FT",
        "DX EIR_FPLR (via PLF cycling curve)",
        "SWH FHeatPLC (via part-load factor curve)",
        "Chiller CAP_FT (Scroll)",
        "Chiller EIR_FPLR (Scroll, direct PLR multiplier)",
        "Chiller EIR_FT (Scroll, vs proposed erratum)",
        "Chiller CAP_FT (Reciprocating)",
        "Chiller EIR_FPLR (Reciprocating, direct PLR multiplier)",
        "Chiller EIR_FT (Reciprocating, vs proposed erratum)",
        "Chiller CAP_FT (Rotary Screw)",
        "Chiller EIR_FPLR (Rotary Screw, direct PLR multiplier)",
        "Chiller EIR_FT (Rotary Screw, printed rows)",
        "Chiller CAP_FT (Centrifugal)",
        "Chiller EIR_FPLR (Centrifugal, direct PLR multiplier)",
        "Chiller EIR_FT (Centrifugal, printed rows)",
        "Cooling Tower FWB vs E+ effectiveness-NTU",
        "ASHP CAP_FTEAS",
        "ASHP EIR_FT",
        "ASHP EIR_FPLR (via PLF cycling curve)",
        "Absorption Chiller CAP_FT/FIR_FPLR/FIR_FT",
    }
    results = report["results"]
    assert len(results) == len(expected_labels) == 23
    assert {result["label"] for result in results} == expected_labels
    assert not {result["verdict"] for result in results} & {"MISSING", "DEVIATES"}

    absorption = next(result for result in results if result["article"] == "8.4.6.8")
    assert absorption["verdict"] == "NOT APPLICABLE"
    assert "no absorption row" in absorption["detail"]

    tower = next(result for result in results if result["article"] == "8.4.6.6")
    assert tower["verdict"] == "ENGINE-EQUIVALENT (NTU)"
    assert tower["metrics"]["anchor_sample_count"] > 0
    assert tower["metrics"]["full_sample_count"] > tower["metrics"]["anchor_sample_count"]
    assert tower["metrics"]["anchor_max_relative_deviation"] <= tower["metrics"]["anchor_tolerance"]

    comparable = [result for result in results if result["verdict"] != "NOT APPLICABLE"]
    assert comparable
    assert all(result["metrics"] for result in comparable)
    assert all(result["metrics"]["sample_count"] > 0
               for result in comparable if "sample_count" in result["metrics"])
    assert len(report["coefficients"]) == 15
    assert report["model_application"]["model_level"] is True
    assert "NOT YET COMPARED (still honest gaps)" in report["honest_gap"]
    assert "condensing-boiler 6-term row" in report["honest_gap"]