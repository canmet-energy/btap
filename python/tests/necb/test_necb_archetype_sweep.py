"""Deterministic tests for the native Python NECB archetype sweep."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests import support

SCRIPT = support.REPO_ROOT / "python" / "scripts" / "necb_archetype_sweep.py"
SPEC = importlib.util.spec_from_file_location("necb_archetype_sweep", SCRIPT)
sweep = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sweep
SPEC.loader.exec_module(sweep)


class FakeReference:
    def getThermalZones(self):
        return [object(), object()]

    def getAirLoopHVACs(self):
        return [object()]

    def getPlantLoops(self):
        return [object(), object(), object()]

    def getHeatExchangerAirToAirSensibleAndLatents(self):
        return [object()]


class RecordingPool:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.commands = []
        self.active = 0
        self.maximum = 0

    def popen(self, command, **kwargs):
        building_type = command[command.index("--one") + 1]
        child = FakeChild(self, self.outcomes[building_type])
        self.commands.append((command, kwargs))
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        return child


class FakeChild:
    def __init__(self, pool, outcome):
        self.pool = pool
        self.outcome = outcome
        self.returncode = None
        self.stdout = io.StringIO(json.dumps(outcome) + "\n")

    def poll(self):
        return self.returncode

    def wait(self):
        if self.returncode is None:
            self.returncode = 0 if self.outcome["verdict"] == "PASS" else 1
            self.pool.active -= 1
        return self.returncode


def outcome(building_type, verdict):
    return {
        "type": building_type,
        "verdict": verdict,
        "detail": "test",
        "mode": "annual",
        "vintage": "2025",
        "location": "toronto",
        "fuel": "Electricity",
        "ecm": "NECB_Default",
        "report": {},
    }


class TestSelectionAndScheduling(unittest.TestCase):
    def test_exact_sets_exclusions_and_longest_first_order(self):
        self.assertEqual(list(sweep.DEFAULT_TYPES), sweep.selected_types([]))
        self.assertEqual(list(sweep.FLEET), sweep.selected_types(["fleet"]))
        self.assertNotIn("Hospital", sweep.FLEET)
        self.assertNotIn("Outpatient", sweep.FLEET)
        self.assertEqual(
            ["Hospital", "LargeHotel", "PrimarySchool", "Warehouse"],
            sweep.ordered_types(
                ["Warehouse", "PrimarySchool", "Hospital", "LargeHotel"]
            ),
        )
        self.assertEqual(["Hospital"], sweep.selected_types(["Hospital"]))

    def test_worker_cap_command_arguments_and_mixed_outcomes(self):
        requested = ["Warehouse", "LargeHotel", "PrimarySchool"]
        outcomes = {
            "Warehouse": outcome("Warehouse", "PASS"),
            "LargeHotel": outcome("LargeHotel", "ERROR"),
            "PrimarySchool": outcome("PrimarySchool", "PASS"),
        }
        pool = RecordingPool(outcomes)
        with tempfile.TemporaryDirectory() as tmp:
            config = sweep.SweepConfig(
                mode="annual",
                vintage="2025",
                location="toronto",
                workers=2,
                cache_dir=Path(tmp),
            )
            with patch.object(sweep, "_recipe_key", return_value="recipe"):
                results = sweep.run_workers(requested, config, popen=pool.popen)

        launched = [command[command.index("--one") + 1]
                    for command, _kwargs in pool.commands]
        self.assertEqual(["LargeHotel", "PrimarySchool", "Warehouse"], launched)
        self.assertEqual(2, pool.maximum)
        first_command, first_kwargs = pool.commands[0]
        self.assertEqual(sys.executable, first_command[0])
        self.assertEqual(str(SCRIPT), first_command[1])
        self.assertEqual(
            ["--mode", "annual", "--vintage", "2025", "--location", "toronto"],
            first_command[4:10],
        )
        self.assertEqual(str(sweep.PYTHON_ROOT), first_kwargs["cwd"])
        self.assertEqual(requested, [result["type"] for result in results])
        summary = sweep.structured_summary(requested, results, config)
        self.assertEqual(2, summary["passed"])
        self.assertEqual(["LargeHotel"], summary["failed"])
        self.assertEqual("week", summary["tier"])

    def test_resume_reuses_matching_result_without_launching_worker(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = sweep.SweepConfig(
                mode="sizing",
                vintage="2020",
                location="toronto",
                workers=1,
                cache_dir=Path(tmp),
                resume=True,
            )
            outcome = {
                "type": "Warehouse",
                "verdict": "PASS",
                "detail": "cached",
                "mode": "sizing",
                "vintage": "2020",
                "location": "toronto",
                "fuel": "Electricity",
                "ecm": "NECB_Default",
                "report": {},
            }
            with patch.object(sweep, "_recipe_key", return_value="recipe"):
                sweep._write_json(sweep._result_path("Warehouse", config), outcome)
                results = sweep.run_workers(
                    ["Warehouse"], config,
                    popen=lambda *_args, **_kwargs: self.fail("worker launched"),
                )
        self.assertEqual([outcome], results)


class TestOracleAndPipeline(unittest.TestCase):
    def test_oracle_command_uses_pinned_generator_and_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = sweep.SweepConfig(
                mode="sizing",
                vintage="2020",
                location="toronto",
                workers=1,
                cache_dir=Path(tmp),
            )

            def fake_run(command, **kwargs):
                output = Path(command[4])
                output.write_text("osm", encoding="utf-8")
                output.with_suffix(".json").write_text(
                    json.dumps(sweep._oracle_attestation("Warehouse", config)),
                    encoding="utf-8",
                )
                fake_run.command = command
                fake_run.kwargs = kwargs
                return subprocess.CompletedProcess(command, 0, "OK\n", "")

            with patch.object(sweep.subprocess, "run", side_effect=fake_run) as run:
                first, first_hit = sweep.generate("Warehouse", config)
                second, second_hit = sweep.generate("Warehouse", config)

        self.assertEqual(first, second)
        self.assertFalse(first_hit)
        self.assertTrue(second_hit)
        self.assertEqual(1, run.call_count)
        self.assertEqual(
            ["bundle", "exec", "ruby", str(sweep.GEN_SCRIPT)],
            fake_run.command[:4],
        )
        self.assertEqual("NECB2020", fake_run.command[6])
        self.assertEqual("Warehouse", fake_run.command[7])
        self.assertEqual(sweep.LOCATIONS["toronto"]["epw"].name, fake_run.command[8])
        self.assertEqual("Electricity", fake_run.command[9])
        self.assertEqual("NECB_Default", fake_run.command[10])
        self.assertEqual(str(sweep.PIN_GEMFILE), fake_run.kwargs["env"]["BUNDLE_GEMFILE"])
        self.assertEqual(str(sweep.REPO_ROOT), fake_run.kwargs["cwd"])

    def test_pipeline_arguments_and_normalized_success_summary(self):
        model = object()
        captured = {}

        def performance_compliance(received_model, **kwargs):
            captured["model"] = received_model
            captured.update(kwargs)
            return SimpleNamespace(
                compliant=False,
                reference_model=FakeReference(),
                audit=SimpleNamespace(warnings=["warning"]),
                report={
                    "annual": False,
                    "tier": 2,
                    "percent_of_target": 87.4,
                    "proposed": {
                        "total_site_kwh": 874.4,
                        "eui_kwh_per_m2": 8.7,
                        "ignored": "unstable",
                    },
                    "reference": {
                        "total_site_kwh": 1000.0,
                        "clean_run": True,
                        "ignored": "unstable",
                    },
                    "ignored": "unstable",
                },
            )

        dependencies = (
            lambda _path: model,
            lambda received_model: 4 if received_model is model else self.fail(),
            performance_compliance,
            type("PreflightError", (ValueError,), {}),
        )
        with tempfile.TemporaryDirectory() as tmp:
            config = sweep.SweepConfig(
                mode="annual",
                vintage="2025",
                location="toronto",
                workers=1,
                cache_dir=Path(tmp),
            )
            osm = Path(tmp) / "cached.osm"
            osm.write_text("osm", encoding="utf-8")
            with (
                patch.object(sweep, "generate", return_value=(osm, True)),
                patch.object(sweep, "_pipeline_dependencies", return_value=dependencies),
                patch.object(sweep, "_recipe_key", return_value="recipe"),
            ):
                outcome = sweep.run_one("Warehouse", config)

        self.assertEqual("PASS", outcome["verdict"])
        self.assertIs(model, captured["model"])
        self.assertEqual("annual", captured["simulate"])
        self.assertEqual("2025", captured["vintage"])
        self.assertEqual(3890, captured["hdd"])
        self.assertEqual({"storeys": 4}, captured["building"])
        self.assertEqual(
            {"begin_month": 1, "begin_day": 1, "end_month": 1, "end_day": 7},
            captured["run_period"],
        )
        self.assertEqual(
            {
                "annual": False,
                "compliant": False,
                "tier": 2,
                "percent_of_target": 87.4,
                "proposed": {"total_site_kwh": 874.4, "eui_kwh_per_m2": 8.7},
                "reference": {"total_site_kwh": 1000.0, "clean_run": True},
            },
            outcome["report"],
        )

    def test_pipeline_failure_is_a_failed_archetype(self):
        def fail_pipeline(_model, **_kwargs):
            raise RuntimeError("sizing failed")

        dependencies = (
            lambda _path: object(),
            lambda _model: 1,
            fail_pipeline,
            type("PreflightError", (ValueError,), {}),
        )
        with tempfile.TemporaryDirectory() as tmp:
            config = sweep.SweepConfig(
                mode="sizing",
                vintage="2020",
                location="toronto",
                workers=1,
                cache_dir=Path(tmp),
            )
            with (
                patch.object(sweep, "generate", return_value=(Path(tmp) / "cached.osm", True)),
                patch.object(sweep, "_pipeline_dependencies", return_value=dependencies),
                patch.object(sweep, "_recipe_key", return_value="recipe"),
            ):
                result = sweep.run_one("Warehouse", config)

        self.assertEqual("ERROR", result["verdict"])
        self.assertEqual("RuntimeError: sizing failed", result["detail"])
        self.assertEqual({}, result["report"])

    def test_main_returns_nonzero_for_a_failed_archetype(self):
        results = [
            outcome("Warehouse", "PASS"),
            outcome("LargeHotel", "ERROR"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(sweep, "run_workers", return_value=results),
                patch.object(sweep, "_recipe_key", return_value="recipe"),
                patch("sys.stdout", new=io.StringIO()),
                patch("sys.stderr", new=io.StringIO()),
            ):
                code = sweep.main([
                    "Warehouse", "LargeHotel", "--workers", "2",
                    "--cache-dir", tmp,
                ])
        self.assertEqual(1, code)

    def test_generation_variants_change_recipe_and_worker_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = sweep.SweepConfig("sizing", "2020", "toronto", 1, Path(tmp))
            variant = sweep.SweepConfig(
                "sizing", "2020", "toronto", 1, Path(tmp),
                fuel="NaturalGas", ecm="hs08_ccashp_vrf",
            )
            self.assertNotEqual(sweep._recipe_key("Warehouse", base),
                                sweep._recipe_key("Warehouse", variant))
            command = sweep._worker_command("Warehouse", variant)
            self.assertEqual("NaturalGas", command[command.index("--fuel") + 1])
            self.assertEqual("hs08_ccashp_vrf", command[command.index("--ecm") + 1])


if __name__ == "__main__":
    unittest.main()