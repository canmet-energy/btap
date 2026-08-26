"""Real end-to-end LOCAL EnergyPlus runs through the Python Local backend
(in-process ForwardTranslator + the provisioned engine) — the port of
test_local_run.rb, plus the M2 decisive gate: the same model run by the RUBY
gem (via the openstudio CLI) and by this port must produce equivalent
results under the Leg-B differ rules.

The Ruby annual test built an HVAC system via btap-modeling; that gem is not
ported yet (M3), so the annual runs here use the bare fixture (thermostats,
no systems — EnergyPlus free-floats the zones and the parse surface is
identical). The HVAC-carrying annual comparison arrives with M3."""

import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support import DDY, EPW, REPO_ROOT, load_fixture, needs_engine

from btap.simulation import run, runner

RUBY_SCRIPT = Path(__file__).parent / "cross_language" / "ruby_reference.rb"
COMPARE_RUNS = REPO_ROOT / "verification" / "compare_runs.py"


def week():
    return {"begin_month": 1, "begin_day": 1, "end_month": 1, "end_day": 7}


@needs_engine
class TestLocalRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_sizing_only_run_of_bare_fixture(self):
        # Sizing needs no HVAC: attach weather, run a design-day-only pass on
        # the bare fixture (which carries thermostats), confirm a clean SQL.
        target = str(Path(self.tmp.name) / "sizing")
        result = run(load_fixture(), run_dir=target,
                     weather={"epw": str(EPW), "ddy": str(DDY)}, sizing_only=True)

        self.assertTrue(result.is_clean(), "sizing run should complete cleanly")
        self.assertTrue((Path(target) / "run" / "eplusout.sql").is_file())
        self.assertEqual(str(Path(target) / "run"), result.run_dir)
        self.assertIsNone(result.energy, "sizing_only run reports no energy")
        self.assertIsNone(result.unmet_hours, "sizing_only run reports no unmet hours")

    def test_short_annual_run_parses_results(self):
        target = str(Path(self.tmp.name) / "annual")
        result = run(load_fixture(), run_dir=target,
                     weather={"epw": str(EPW), "ddy": str(DDY)}, run_period=week())

        self.assertTrue(result.is_clean(), "annual run should complete cleanly")
        energy = result.energy
        self.assertIsInstance(energy, dict)
        for key in ("total_site_kwh", "electricity_kwh", "natural_gas_kwh",
                    "floor_area_m2", "end_uses_kwh"):
            self.assertIn(key, energy)
        for key in ("heating", "cooling", "fans", "pumps", "interior_lighting",
                    "interior_equipment", "water_systems"):
            self.assertIn(key, energy["end_uses_kwh"])
        self.assertGreater(energy["floor_area_m2"], 0)

        unmet = result.unmet_hours
        self.assertIsInstance(unmet, dict)
        self.assertIn("heating", unmet)
        self.assertIn("cooling", unmet)

        zones = runner.zone_unmet_occupied_hours(
            # the SQL is attached to the model run() used internally; re-run
            # the parse through the public seam on a fresh handle
            self._model_with_sql(target))
        self.assertIsInstance(zones, dict)

    def _model_with_sql(self, target):
        import openstudio
        model = load_fixture()
        model.setSqlFile(openstudio.SqlFile(
            openstudio.path(str(Path(target) / "run" / "eplusout.sql"))))
        return model

    def test_run_directory_containing_a_space_still_simulates(self):
        # THE quoting regression the Ruby gem paid for: ARGV-form execution
        # means a path with spaces (the Windows norm) cannot split.
        target = str(Path(self.tmp.name) / "a directory with spaces" / "run")
        model = load_fixture()
        runner.attach_weather(model, epw=str(EPW), ddy=str(DDY))
        out_dir = runner.run_energyplus(model, target, sizing_only=True)

        self.assertTrue((Path(out_dir) / "eplusout.sql").is_file(), "no SQL — the path split")
        self.assertTrue(runner.is_clean_run(out_dir))
        self.assertTrue((Path(target) / "cli.log").is_file(), "cli.log landed outside the run dir")


@needs_engine
@unittest.skipUnless(shutil.which("ruby") and shutil.which("openstudio"),
                     "the cross-language gate needs ruby + the openstudio CLI "
                     "(the Ruby gem's backend)")
class TestCrossLanguageSimulation(unittest.TestCase):
    """The M2 acceptance: Ruby CLI pipeline vs Python engine pipeline on the
    same model — energies equal (both pre-round with the same semantics),
    unmet hours within the Leg-B spec tolerance."""

    def test_ruby_and_python_results_are_equivalent(self):
        from btap._compat import ruby_str  # noqa: F401  (import proves _compat loads SDK-free)

        with tempfile.TemporaryDirectory() as tmp:
            ruby_dir = Path(tmp) / "ruby"
            proc = subprocess.run(["ruby", str(RUBY_SCRIPT), str(ruby_dir)],
                                  capture_output=True, text=True)
            self.assertEqual(0, proc.returncode, f"ruby reference failed: {proc.stderr[-2000:]}")
            ruby_results = json.loads((ruby_dir / "results.json").read_text())

            sizing = run(load_fixture(), run_dir=str(Path(tmp) / "py" / "sizing"),
                         weather={"epw": str(EPW), "ddy": str(DDY)}, sizing_only=True)
            # The annual leg carries a real HVAC system, built by EACH
            # language's own btap-modeling port — MUST mirror the ruby
            # reference script's system and zone ordering.
            import btap.modeling as modeling
            from btap._compat import sorted_by_name
            annual_model = load_fixture()
            modeling.build_system(annual_model, "Baseboard gas boiler",
                                  sorted_by_name(annual_model.getThermalZones()))
            annual = run(annual_model, run_dir=str(Path(tmp) / "py" / "annual"),
                         weather={"epw": str(EPW), "ddy": str(DDY)}, run_period=week())
            py_results = {"sizing": {"clean": sizing.is_clean()},
                          "annual": {"clean": annual.is_clean(), "energy": annual.energy,
                                     "unmet_occupied_hours": annual.unmet_hours}}

            spec_module = self._load_compare_runs()
            spec = spec_module.load_spec(REPO_ROOT / "verification" / "spec.json")
            diffs = []
            spec_module.diff(ruby_results, json.loads(json.dumps(py_results)), spec,
                             "results", diffs)
            self.assertEqual([], diffs,
                             "Ruby-vs-Python simulation results differ under the Leg-B rules:\n"
                             + "\n".join(diffs))
            # non-vacuous: both ran cleanly, and the gas-heated January week
            # produced real heating energy for the equality to bite on
            self.assertTrue(ruby_results["annual"]["clean"])
            self.assertGreater(ruby_results["annual"]["energy"]["total_site_kwh"], 0)
            self.assertGreater(ruby_results["annual"]["energy"]["end_uses_kwh"]["heating"], 0)

    @staticmethod
    def _load_compare_runs():
        spec = importlib.util.spec_from_file_location("compare_runs", COMPARE_RUNS)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


if __name__ == "__main__":
    unittest.main()
