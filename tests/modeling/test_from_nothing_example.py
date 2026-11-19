"""The README's "From nothing to a simulation" example RUNS, and runs CLEAN (#236).

#236 built a building from nothing as a user would, and found a trap and four
rough edges that no test saw, because no test walked the documented workflow
end to end with only public calls. This one does — and it runs the README's
OWN code block rather than a copy of it, so documentation and test cannot
drift apart. Only the two weather paths are substituted, and the run happens
in a temporary directory.

It holds the example to what CLAUDE.md asks of an artifact we ship: an
EnergyPlus run with no Severe error, a sane comfort result, and the whole
build in one audit trail.
"""

from __future__ import annotations

import contextlib
import io
import os
import re
import tempfile
import unittest
import warnings
from pathlib import Path

from tests.support import DDY, EPW, needs_engine

README = Path(__file__).resolve().parents[2] / "src" / "btap" / "modeling" / "README.md"
SECTION = "## From nothing to a simulation"


def example_source() -> str:
    """The python block under the README's section heading."""
    text = README.read_text(encoding="utf-8")
    section = text[text.index(SECTION):]
    match = re.search(r"```python\n(.*?)```", section, re.S)
    assert match, "the README section lost its python block"
    return match.group(1)


def runnable(source: str) -> str:
    """Point the two weather assignments at the test fixtures — and ONLY those."""
    out, count = re.subn(r'^epw = "[^"]*"', f"epw = {str(EPW)!r}", source, flags=re.M)
    out, more = re.subn(r'^ddy = "[^"]*"', f"ddy = {str(DDY)!r}", out, flags=re.M)
    assert (count, more) == (1, 1), "the example's weather assignments moved"
    return out


class TestTheExampleIsStillTheDocumentedOne(unittest.TestCase):
    """SDK-free: the block exists and uses only public entry points."""

    def test_it_uses_only_public_calls(self):
        source = example_source()
        self.assertNotRegex(source, r"\._[a-z]", "the example reaches a private name")
        for call in ("modeling.bar(", "modeling.seed_constructions(", "loads.apply_loads(",
                     "lighting.apply_lights(", "shw.apply_shw(", "modeling.build_system(",
                     "simulation.run("):
            with self.subTest(call=call):
                self.assertIn(call, source)

    def test_every_step_shares_one_audit(self):
        source = example_source()
        for call in ("bar(", "seed_constructions(", "apply_loads(", "apply_lights(",
                     "apply_shw(", "build_system("):
            with self.subTest(call=call):
                start = source.index(call)
                self.assertIn("audit=audit", source[start:source.index(")\n", start) + 1])


@needs_engine
class TestTheExampleRuns(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.namespace = {}
        cls.caught = []
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory(prefix="from-nothing-") as tmp:
            os.chdir(tmp)
            try:
                with warnings.catch_warnings(record=True) as caught, \
                        contextlib.redirect_stdout(io.StringIO()):
                    warnings.simplefilter("always")
                    exec(compile(runnable(example_source()), str(README), "exec"),
                         cls.namespace)
                cls.caught = [str(w.message) for w in caught]
                err = Path(cls.namespace["result"].run_dir) / "eplusout.err"
                cls.err = err.read_text(errors="replace") if err.exists() else ""
            finally:
                os.chdir(cwd)

    def test_it_runs_clean(self):
        result = self.namespace["result"]
        self.assertTrue(result.clean, "the documented example must not report a Severe")
        self.assertIn("EnergyPlus Completed Successfully", self.err)
        self.assertEqual(0, self.err.count("** Severe"))

    def test_the_result_is_sane(self):
        result = self.namespace["result"]
        self.assertGreater(result.energy["total_site_kwh"], 1000)
        # A documented example must not teach a building that cannot hold
        # its setpoints: under 10 unmet hours each way in the week.
        self.assertLess(result.unmet_hours["heating"], 10, result.unmet_hours)
        self.assertLess(result.unmet_hours["cooling"], 10, result.unmet_hours)

    def test_the_build_is_complete(self):
        model = self.namespace["model"]
        zones = list(model.getThermalZones())
        self.assertEqual(24, len(zones))
        self.assertTrue(all(not z.thermostatSetpointDualSetpoint().empty() for z in zones))
        self.assertTrue(all(not s.construction().empty() for s in model.getSurfaces()))
        self.assertEqual(1, len(model.getAirLoopHVACs()))

    def test_one_audit_records_every_step_including_hvac(self):
        steps = {e["step"] for e in self.namespace["audit"].entries}
        self.assertIn("hvac", steps)
        self.assertIn("envelope", steps)

    def test_no_single_zone_warning_fires(self):
        self.assertEqual([], [w for w in self.caught if "#236" in w])


if __name__ == "__main__":
    unittest.main()
