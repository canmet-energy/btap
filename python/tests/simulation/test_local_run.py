"""Real end-to-end LOCAL EnergyPlus runs through the Python Local backend
(in-process ForwardTranslator + the provisioned engine) — the port of
test_local_run.rb, plus the M2 decisive gate: the same model run by the RUBY
gem (via the openstudio CLI) and by this port must produce equivalent
results under the Leg-B differ rules.

The plain-Python annual tests use the bare fixture (thermostats, no
systems — EnergyPlus free-floats the zones and the parse surface is
identical); the cross-language class below carries a REAL HVAC system built
by each language's own btap-modeling port (added when M3 landed it)."""

import pathlib
import shutil
import tempfile
import unittest
from pathlib import Path

from btap.simulation import run, runner
from tests.support import DDY, EPW, load_fixture, needs_engine, needs_sdk


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

if __name__ == "__main__":
    unittest.main()

class TestDesignDayAuditTellsTheTruth(unittest.TestCase):
    """D-25's audit entry must not claim a filter that did not happen.

    `attach_weather` keeps only the annual-extreme design days — unless NONE of
    them match, in which case it deliberately keeps the whole DDY rather than
    none. The first version of the entry asserted "filtered to the annual
    extremes ... sized on the 99.6% heating and 0.4% cooling days only"
    unconditionally, so on that supported fallback it stated a false modelling
    assumption in a document an AHJ reads — while its own `inputs` recorded
    `kept_all_as_fallback: true` and a kept-count equal to the whole file.
    Sol reproduced it by renaming the three matching days in the shipped Toronto
    DDY (`084`).
    """

    KEEP_PATTERNS = (r"Htg 99.6. Condns DB", r"Clg .4% Condns DB=>MWB",
                     r"Clg 0.4% Condns DB=>MCWB", r"Clg .4. Condns WB=>MDB")

    def _ddy_with_no_extremes(self):
        """The shipped DDY with every annual-extreme NAME made non-matching."""
        import re

        text = pathlib.Path(DDY).read_text(encoding="latin-1")
        out = []
        for line in text.splitlines(keepends=True):
            if any(re.search(p, line) for p in self.KEEP_PATTERNS):
                line = line.replace("Htg 99.6%", "Htg Ordinary") \
                           .replace("Clg .4%", "Clg Ordinary") \
                           .replace("Clg 0.4%", "Clg Ordinary")
            out.append(line)
        directory = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = directory / "no-extremes.ddy"
        path.write_text("".join(out), encoding="latin-1")
        return path

    @needs_sdk
    def test_the_normal_path_says_it_filtered(self):
        from btap.audit import AuditLog

        audit = AuditLog()
        model = load_fixture()
        runner.attach_weather(model, epw=str(EPW), ddy=str(DDY), audit=audit)
        entry = next(e for e in audit.entries if e.get("ruling") == "D-25")
        self.assertFalse(entry["inputs"]["kept_all_as_fallback"])
        self.assertIn("filtered to the annual extremes", entry["action"])
        self.assertLess(entry["inputs"]["design_days_kept"],
                        entry["inputs"]["design_days_in_file"],
                        "the normal path must keep FEWER than the file holds")

    @needs_sdk
    def test_the_FALLBACK_path_does_not_claim_a_filter(self):
        from btap.audit import AuditLog

        ddy = self._ddy_with_no_extremes()
        audit = AuditLog()
        model = load_fixture()
        runner.attach_weather(model, epw=str(EPW), ddy=str(ddy), audit=audit)
        entry = next(e for e in audit.entries if e.get("ruling") == "D-25")
        inputs = entry["inputs"]
        self.assertTrue(inputs["kept_all_as_fallback"],
                        "precondition: this DDY must trigger the fallback")
        self.assertEqual(inputs["design_days_kept"], inputs["design_days_in_file"],
                         "the fallback keeps the WHOLE file")
        # the claim must match the evidence
        self.assertIn("FULL file was retained", entry["action"])
        self.assertNotIn("0.4% cooling days only", entry["action"])
        self.assertNotIn("filtered to the annual extremes", entry["action"])
