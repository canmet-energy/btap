"""The sweep's exit status, which is how every caller learns the result.

Sol's `234`: the documented smoke command
(`simulate_all_systems.py --name "VRF"`) printed its failure and exited
**0**. A shell, a CI step and a `&&` chain all read the status and not the
text, so a broken system reported as FAIL looked like a success to every
automated caller — which is every way the command is actually used.

The cause was a bare `return` on the partial-sweep path while only the full
path called `sys.exit`. Not writing the verdict file is a statement about
the FILE; it says nothing about whether what ran was healthy, and the first
version conflated the two.

No engine here. `simulate_one` is replaced, because the property under test
is what `main()` does with a verdict rather than how a verdict is reached.
"""
import importlib.util
import io
import json
import pathlib
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

from tests.support import REPO_ROOT

SCRIPT = REPO_ROOT / "python" / "scripts" / "simulate_all_systems.py"


def _load():
    spec = importlib.util.spec_from_file_location("sweep_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["sweep_under_test"] = module
    spec.loader.exec_module(module)
    return module


class TestTheSweepsExitStatus(unittest.TestCase):
    def setUp(self):
        self.sweep = _load()

    def _run(self, argv, verdicts):
        """Run `main()` with `simulate_one` stubbed. Returns the exit code."""
        def fake(row, keep_dir=None, annual=False):
            status = verdicts.get(row["name"], "ok")
            return {"name": row["name"], "family": row["family"],
                    "status": status, "severe": 0 if status == "ok" else 1,
                    "fatal": 0, "completed": status == "ok", "seconds": 0.1}

        with mock.patch.object(self.sweep, "simulate_one", fake), \
                mock.patch.object(sys, "argv", ["simulate_all_systems.py",
                                                *argv]):
            with redirect_stdout(io.StringIO()) as out:
                try:
                    self.sweep.main()
                except SystemExit as exit_code:
                    return (exit_code.code if isinstance(exit_code.code, int)
                            else 1), out.getvalue()
            return 0, out.getvalue()

    def _a_real_name(self):
        return self.sweep.catalogue_rows()[0]["name"]

    def test_a_PARTIAL_sweep_that_finds_a_failure_exits_NONZERO(self):
        """The exact defect: the documented smoke command exited 0."""
        name = self._a_real_name()
        code, text = self._run(["--name", name], {name: "build_error"})
        self.assertIn("NOT writing the verdict file", text,
                      "a subset must still refuse to write the verdict")
        self.assertNotEqual(
            0, code,
            "a smoke run that found a broken system must not exit 0 — a "
            "shell, a CI step and a `&&` chain read the status, not the text")

    def test_a_PARTIAL_sweep_that_finds_nothing_wrong_exits_ZERO(self):
        """The control. Without it, "always exit 1" passes the test above."""
        name = self._a_real_name()
        code, text = self._run(["--name", name], {})
        self.assertIn("NOT writing the verdict file", text)
        self.assertEqual(0, code,
                         "a clean smoke run must exit 0, or the status "
                         "carries no information")

    def test_a_LIMITED_sweep_follows_the_same_rule(self):
        rows = self.sweep.catalogue_rows()
        code, _text = self._run(["--limit", "2"],
                                {rows[1]["name"]: "simulation_error"})
        self.assertNotEqual(0, code)
        code, _text = self._run(["--limit", "2"], {})
        self.assertEqual(0, code)

    def test_a_partial_sweep_NEVER_writes_the_verdict(self):
        """A verdict is a claim about every row; a subset cannot make it."""
        before = SCRIPT.parent.parent / "tests" / "fixtures" / \
            "system_simulation_status.json"
        original = before.read_bytes()
        name = self._a_real_name()
        for argv in (["--name", name], ["--limit", "1"]):
            with self.subTest(argv=argv):
                self._run(argv, {})
                self.assertEqual(
                    original, before.read_bytes(),
                    f"{argv} rewrote the verdict file; a partial sweep must "
                    "leave it alone whatever it found")

    def test_CHECK_reports_a_verdict_that_MOVED(self):
        """The ordinary `--check` case: a recorded `ok` that now fails."""
        committed = json.loads(
            pathlib.Path(self.sweep.STATUS).read_text(encoding="utf-8"))
        already_ok = next(row["name"] for row in committed["systems"]
                          if row["status"] == "ok")
        code, text = self._run(["--check", "--name", already_ok],
                               {already_ok: "simulation_error"})
        self.assertNotEqual(0, code)
        self.assertIn("MOVED", text)

    def test_CHECK_exits_nonzero_for_a_failure_whose_status_did_NOT_move(self):
        """The case the ordinary one cannot reach, and it needed building.

        `--check` reports verdicts that MOVED. A system already recorded as
        failing that fails again moves nothing — so reporting only movement
        exits 0 while a system is broken. Every committed row is currently
        `ok`, so this condition does not exist in the data and the test has
        to construct it by pointing `STATUS` at a verdict that records the
        failure.

        My first version of this test used a recorded `ok` that now fails,
        which MOVES, so it exited by the movement branch and left this path
        unwitnessed: restoring a bare `return` here kept all six tests
        green.
        """
        rows = self.sweep.catalogue_rows()
        name = rows[0]["name"]
        verdict = {
            "produced_by": {"openstudio_cli": "x", "openstudio_sdk": "x",
                            "fixture": "x", "weather": "x", "mode": "x"},
            "systems": [{"name": row["name"], "family": row["family"],
                         "status": "build_error" if row["name"] == name
                                   else "ok",
                         "severe": 0, "fatal": 0, "completed": True,
                         "seconds": 0.1}
                        for row in rows],
        }
        scratch = pathlib.Path(self.enterContext(
            __import__("tempfile").TemporaryDirectory(prefix="sweep-check-")))
        stored = scratch / "status.json"
        stored.write_text(json.dumps(verdict), encoding="utf-8")

        with mock.patch.object(self.sweep, "STATUS", stored):
            code, text = self._run(["--check", "--name", name],
                                   {name: "build_error"})
        self.assertIn("no verdict moved", text,
                      "the recorded status already said build_error, so "
                      "nothing moved — that is the condition under test")
        self.assertNotEqual(
            0, code,
            "a system that FAILED this run is a failure whether or not its "
            "recorded status moved; exiting 0 here reports a broken system "
            "as healthy")

    def test_the_verdict_fixture_is_the_one_the_script_writes(self):
        """A smaller claim, worth pinning: both point at the same file."""
        self.assertEqual(
            (REPO_ROOT / "python" / "tests" / "fixtures"
             / "system_simulation_status.json").resolve(),
            pathlib.Path(self.sweep.STATUS).resolve(),
            "the producer and the test must name the same verdict file")


if __name__ == "__main__":
    unittest.main()


class TestTheVerdictsEvidenceIsActuallyProduced(unittest.TestCase):
    """The counts and the completion flag, on the path that needs them.

    Sol's `234` found two defects in the producer, both of which made the
    advertised diagnostic unavailable for the exact defect class the script
    exists to catch:

    1. EnergyPlus pads its markers differently — `** Severe  **` has one
       leading space and `**  Fatal  **` has two — and both were written as
       literals with one, so the fatal count was structurally always 0.
    2. The local backend RAISES on a failed run, so `simulate_one` read
       `eplusout.err` only after a SUCCESSFUL run. A system that failed in
       EnergyPlus returned `sweep_error` with no severe count, no fatal
       count and no completion flag.

    The text below is EnergyPlus output captured from this repository on
    2026-10-12, not invented.
    """

    #: Verbatim from a failed `AirLoopHVAC:DedicatedOutdoorAirSystem` run.
    REAL_ERR = (
        "   ** Severe  ** When AirLoopHVAC:OutdoorAirSystem:EquipmentList = "
        "DOAS SUPPLY FAN is used in AirLoopHVAC:DedicatedOutdoorAirSystem\n"
        "   **   ~~~   **  the FAN:CONSTANTVOLUME can not be used as a "
        "component. Please remove it\n"
        "   ** Severe  ** getAirLoopMixer: Node Connection Error in "
        "AirLoopHVAC:DedicatedOutdoorAirSystem = CENTRAL DOAS.\n"
        "   **  Fatal  ** getAirLoopHVACDOAS: Previous errors cause "
        "termination.\n")

    def setUp(self):
        self.sweep = _load()

    def test_the_markers_match_the_padding_EnergyPlus_actually_uses(self):
        self.assertEqual(
            2, len(self.sweep.SEVERE_RE.findall(self.REAL_ERR)),
            "two Severe lines in this captured output")
        self.assertEqual(
            1, len(self.sweep.FATAL_RE.findall(self.REAL_ERR)),
            "one Fatal line — and a literal `** Fatal  **` with ONE leading "
            "space finds zero of it, which is what the first version did")

    def test_a_single_space_literal_would_MISS_the_fatal(self):
        """The control that makes the test above mean something."""
        self.assertEqual(
            0, self.REAL_ERR.count("** Fatal  **"),
            "if this ever becomes non-zero EnergyPlus changed its padding "
            "and the regexes should be re-read, not this test relaxed")
        self.assertEqual(1, self.REAL_ERR.count("**  Fatal  **"))

    def test_a_run_that_RAISES_still_reports_its_evidence(self):
        """The second defect: the backend raises, and the counts must survive.

        `simulate_one` is driven with a `simulation.run` that raises the way
        the local backend does, and a run directory holding the captured
        error text. The verdict must carry the counts, not just a status.
        """
        import tempfile

        work = pathlib.Path(self.enterContext(
            tempfile.TemporaryDirectory(prefix="sweep-raise-")))
        run_dir = work / "run" / "run"
        run_dir.mkdir(parents=True)
        (run_dir / "eplusout.err").write_text(self.REAL_ERR,
                                              encoding="utf-8")

        row = self.sweep.catalogue_rows()[0]

        # Patch `btap.simulation.run` ITSELF, not the `sys.modules` entry.
        # `simulate_one` does `import btap.simulation as simulation`, and
        # for a submodule that binds through the PARENT PACKAGE's attribute
        # — so replacing the `sys.modules` entry left the real module bound
        # whenever `btap.simulation` had already been imported. My first
        # version did that and was ORDER-DEPENDENT: it passed run alone and
        # failed in the full suite, where an earlier test had imported the
        # package and the real EnergyPlus ran on an unbuilt model, which
        # simulates fine and returned `ok`.
        import btap.modeling as modeling
        import btap.simulation as simulation

        def raising(*_args, **_kwargs):
            raise RuntimeError("EnergyPlus run failed in " + str(run_dir))

        with mock.patch.object(simulation, "run", raising), \
                mock.patch.object(modeling, "build_system",
                                  lambda *a, **k: None):
            verdict = self.sweep.simulate_one(row, keep_dir=str(work))

        self.assertNotEqual("ok", verdict["status"])
        for field in ("severe", "fatal", "completed"):
            with self.subTest(field=field):
                self.assertIn(
                    field, verdict,
                    f"a failed run must still report `{field}` — the "
                    "diagnostic exists for exactly this case")
        self.assertEqual((2, 1), (verdict["severe"], verdict["fatal"]))
        self.assertFalse(verdict["completed"])
        self.assertIn("Severe", verdict["detail"],
                      "and the first severity line, so a reader need not go "
                      "back to a directory this script deleted")
