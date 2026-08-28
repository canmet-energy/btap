"""Port of btap-necb/test/test_cli.rb: the CLI exercised IN-PROCESS (cli.run
returns an int and never exits), so these are real tests rather than
subprocess smoke checks. Only one test simulates; everything else is a
parse/pre-flight assertion and runs in seconds.

Parser-specific stderr wording differs from Ruby's optparse (argparse says
"invalid option: --nope" via our own funnel) — the exit codes and the
semantics are what is pinned."""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from btap.necb import cli
from tests.necb.support import DDY, EPW, FIXTURE_OSM, needs_engine, needs_sdk

FIXTURE = str(FIXTURE_OSM)


class CLICase(unittest.TestCase):
    def setUp(self):
        self.out = io.StringIO()
        self.err = io.StringIO()

    def run_cli(self, *argv):
        return cli.run(list(argv), out=self.out, err=self.err)

    def weather_args(self):
        return ["--epw", str(EPW), "--ddy", str(DDY)]


class TestCLIUsage(CLICase):
    def test_help_exits_zero_and_documents_the_required_arguments(self):
        self.assertEqual(0, self.run_cli("--help"))
        self.assertRegex(self.out.getvalue(),
                         r"btap-compliance MODEL\.osm --epw FILE")
        self.assertRegex(self.out.getvalue(), r"--space-type")

    def test_no_model_is_a_usage_error(self):
        self.assertEqual(2, self.run_cli())
        self.assertRegex(self.err.getvalue(), r"no model given")

    def test_missing_model_file_is_a_usage_error(self):
        self.assertEqual(2, self.run_cli("/nonexistent/model.osm",
                                         "--epw", str(EPW)))
        self.assertRegex(self.err.getvalue(),
                         r"model not found: /nonexistent/model\.osm")

    def test_missing_epw_is_a_usage_error(self):
        self.assertEqual(2, self.run_cli(FIXTURE))
        self.assertRegex(self.err.getvalue(), r"no --epw given")

    def test_missing_ddy_sibling_is_caught_before_the_model_loads(self):
        # The pipeline's weather guard would also raise for this, but only
        # after the model load — a fat-fingered path must not cost that wait.
        with tempfile.TemporaryDirectory() as dir:
            lonely = os.path.join(dir, "weather.epw")
            shutil.copy(str(EPW), lonely)
            self.assertEqual(2, self.run_cli(FIXTURE, "--epw", lonely))
            self.assertRegex(self.err.getvalue(), r"ddy not found")
            self.assertRegex(self.err.getvalue(), r"pass --ddy explicitly")

    def test_unknown_flag_is_a_usage_error(self):
        self.assertEqual(2, self.run_cli(FIXTURE, "--epw", str(EPW), "--nope"))
        self.assertRegex(self.err.getvalue(), r"invalid option")

    def test_bad_vintage_is_rejected_by_the_parser(self):
        self.assertEqual(2, self.run_cli(FIXTURE, *self.weather_args(),
                                         "--vintage", "2011"))


@needs_sdk
class TestCLIPreflight(CLICase):
    def test_untagged_model_is_refused_with_exit_3_and_actionable_advice(self):
        # The shared fixture is ASHRAE-tagged with no standardsSpaceType, so
        # this is a fast, simulation-free assertion that the refusal is
        # reported as its OWN exit code rather than collapsed into a generic
        # error.
        with tempfile.TemporaryDirectory() as dir:
            code = self.run_cli(FIXTURE, *self.weather_args(),
                                "--simulate", "none", "--hdd", "3890",
                                "--storeys", "1", "-o",
                                os.path.join(dir, "run"))
            self.assertEqual(3, code)
            self.assertRegex(self.err.getvalue(),
                             r"REJECTED before any simulation ran")
            self.assertRegex(self.err.getvalue(), r"pre-flight FAILED")
            self.assertRegex(self.err.getvalue(), r"--space-type",
                             "must name the on-ramp that fixes it")

    def test_preflight_error_is_a_value_error_so_existing_handlers_work(self):
        from btap.necb.compliance import PreflightError

        self.assertTrue(issubclass(PreflightError, ValueError))

    def test_simulate_none_reports_no_determination_not_a_verdict(self):
        with tempfile.TemporaryDirectory() as dir:
            code = self.run_cli(
                FIXTURE, *self.weather_args(), "--simulate", "none",
                "--hdd", "3890", "--storeys", "1", "--no-report", "--quiet",
                "--space-type", "Space Function/Office enclosed > 25 m2",
                "-o", os.path.join(dir, "run"))
            self.assertEqual(6, code)
            self.assertRegex(self.out.getvalue(), r"NO DETERMINATION")
            self.assertNotRegex(self.out.getvalue(), r"VERDICT: COMPLIANT")

    def test_stdout_is_pure_ascii(self):
        # The Windows console is CP437/CP1252; a superscript or an em dash on
        # stdout would be the tool breaking rather than the tool reporting.
        with tempfile.TemporaryDirectory() as dir:
            self.run_cli(
                FIXTURE, *self.weather_args(), "--simulate", "none",
                "--hdd", "3890", "--storeys", "1", "--no-report", "--quiet",
                "--space-type", "Space Function/Office enclosed > 25 m2",
                "-o", os.path.join(dir, "run"))
            text = self.out.getvalue()
            bad = sorted({c for c in text if not c.isascii()})
            self.assertTrue(text.isascii(), f"stdout carried non-ASCII: {bad}")

    def test_compliance_runs_without_the_priced_costing_tables(self):
        # The installer ships everything EXCEPT the two priced
        # RS-Means-derived tables; costing still works when the user points
        # --costs-csv at their own. This pins that the COMPLIANCE path never
        # touches them, so a future eager read breaks CI here rather than
        # shipping a distribution that dies at run time.
        #
        # PROBE MECHANICS (learned the hard way): Ruby's version renamed the
        # shared CSVs on disk and restored them after — safe there because
        # its runner forks per GEM, so nothing else could read them in the
        # window. Under pytest-xdist the costing suites run CONCURRENTLY in
        # sibling workers, and hiding the real files crashed five of them in
        # CI. The probe is now PROCESS-LOCAL and stronger: a subprocess runs
        # the CLI with builtins.open guarded so ANY read of either priced
        # filename raises — nothing on disk moves, and eager reads through
        # any resolution layer are caught, not just the vendored copies.
        costing = Path(cli.__file__).parents[1] / "costing" / "data"
        # NOT a skip: this checkout vendors both, and a silently-skipping
        # packaging gate is exactly the green-but-vacuous failure this repo
        # already documents.
        for name in ("costs.csv", "costs_local_factors.csv"):
            self.assertTrue((costing / name).exists(),
                            f"expected the priced table {name} in {costing}")

        wrapper = (
            "import builtins, os.path, sys\n"
            "_real = builtins.open\n"
            "def guarded(file, *a, **k):\n"
            "    if os.path.basename(str(file)) in ('costs.csv',"
            " 'costs_local_factors.csv'):\n"
            "        raise AssertionError('the compliance path read a priced"
            " table: %s' % file)\n"
            "    return _real(file, *a, **k)\n"
            "builtins.open = guarded\n"
            "from btap.necb import cli\n"
            "sys.exit(cli.run(sys.argv[1:]))\n")
        with tempfile.TemporaryDirectory() as dir:
            script = os.path.join(dir, "guarded_cli.py")
            Path(script).write_text(wrapper, encoding="utf-8")
            env = dict(os.environ)
            python_root = str(Path(cli.__file__).parents[2])
            env["PYTHONPATH"] = os.pathsep.join(
                p for p in (python_root, env.get("PYTHONPATH")) if p)
            proc = subprocess.run(
                [sys.executable, script,
                 FIXTURE, *self.weather_args(), "--simulate", "none",
                 "--hdd", "3890", "--storeys", "1", "--no-report",
                 "--quiet", "--space-type",
                 "Space Function/Office enclosed > 25 m2",
                 "-o", os.path.join(dir, "run")],
                capture_output=True, text=True, env=env, timeout=600)
            self.assertEqual(6, proc.returncode,
                             "the compliance path must not need the priced "
                             f"tables: {proc.stderr[-2000:]}")
            self.assertNotIn("priced table", proc.stderr,
                             "a priced table WAS read")


class TestCLIOutput(CLICase):
    def test_help_output_is_pure_ascii(self):
        self.run_cli("--help")
        self.assertTrue(self.out.getvalue().isascii())


class TestCLIWeather(CLICase):
    def test_list_cities_needs_no_model(self):
        self.assertEqual(0, self.run_cli("--list-cities"))
        self.assertRegex(self.out.getvalue(), r"toronto")

    def test_unknown_city_lists_what_is_available(self):
        self.assertEqual(2, self.run_cli(FIXTURE, "--city", "atlantis"))
        self.assertRegex(self.err.getvalue(), r"unknown city: atlantis")
        self.assertRegex(self.err.getvalue(), r"known: ")

    def test_city_and_epw_are_mutually_exclusive(self):
        self.assertEqual(2, self.run_cli(FIXTURE, "--city", "toronto",
                                         "--epw", str(EPW)))
        self.assertRegex(self.err.getvalue(), r"mutually exclusive")

    def test_city_resolves_to_a_file_whose_ddy_and_stat_sit_beside_it(self):
        # --city must supply the DDY too — attach_weather hard-requires it,
        # and the .stat beside it is what the climate resolver reads before
        # falling back to Table C-1.
        epw = cli.Weather.available().get("toronto")
        self.assertIsNotNone(
            epw, 'the fixture weather should be discoverable as "toronto"')
        self.assertTrue(os.path.exists(epw[:-4] + ".ddy"),
                        "no .ddy beside the resolved EPW")
        self.assertTrue(os.path.exists(epw[:-4] + ".stat"),
                        "no .stat beside the resolved EPW")

    def test_btap_home_takes_precedence(self):
        # BTAP_HOME is what a launcher actually sets, so it must win over any
        # checkout path that happens to exist on the same machine.
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, "weather"))
            shutil.copy(str(EPW), os.path.join(
                home, "weather", "CAN_XX_Somewhere.123456_CWEC2020.epw"))
            os.environ["BTAP_HOME"] = home
            try:
                self.assertEqual(os.path.join(home, "weather"),
                                 cli.Weather.search()[0])
                self.assertEqual(
                    os.path.join(home, "weather",
                                 "CAN_XX_Somewhere.123456_CWEC2020.epw"),
                    cli.Weather.available()["somewhere"])
            finally:
                del os.environ["BTAP_HOME"]


@needs_engine
class TestCLIEndToEnd(CLICase):
    def test_quick_annual_run_refuses_to_call_itself_a_determination(self):
        # The one test that simulates. A shortened run period must NEVER be
        # reported as compliant: the pipeline's evaluate still returns a
        # boolean and only sets report['annual'] = False, so the CLI has to
        # override it.
        with tempfile.TemporaryDirectory() as dir:
            run_dir = os.path.join(dir, "run")
            code = self.run_cli(
                FIXTURE, *self.weather_args(), "--simulate", "annual",
                "--quick", "--hdd", "3890", "--storeys", "1", "--quiet",
                "--space-type", "Space Function/Office enclosed > 25 m2",
                "--shw-fuel", "NaturalGas",
                "--hvac-system", "Baseboard gas boiler",
                "-o", run_dir)

            self.assertEqual(6, code,
                             "a shortened run is NOT a code determination: "
                             + self.err.getvalue()[-2000:])
            self.assertRegex(self.out.getvalue(),
                             r"NOT A CODE-COMPLIANT DETERMINATION")
            self.assertNotRegex(self.out.getvalue(), r"VERDICT: COMPLIANT")

            html_path = os.path.join(run_dir, "compliance_report.html")
            self.assertTrue(os.path.getsize(html_path),
                            "HTML report must be written")
            report = json.loads(Path(run_dir, "report.json").read_text(
                encoding="utf-8"))
            self.assertEqual(False, report["annual"])
            self.assertGreater(report["proposed"]["total_site_kwh"], 0)
            self.assertGreater(report["reference"]["total_site_kwh"], 0)
            self.assertGreater(report["proposed"]["eui_kwh_per_m2"], 0)
            self.assertGreater(report["reference"]["eui_kwh_per_m2"], 0)


if __name__ == "__main__":
    unittest.main()
