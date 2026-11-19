"""A RELATIVE `run_dir` runs (#236).

The local backend runs EnergyPlus with its cwd in the run's own output
directory (concurrent runs must not share ExpandObjects' intermediates), so a
relative `run_dir` handed on unresolved made `-d` and the IDF path point at the
wrong place: "input_file: File does not exist: my_first_run/in.idf", no
eplusout.err, and a RuntimeError. Every example that passed an absolute path —
all of them — hid it; a user's first `run_dir="my_first_run"` hit it at once.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tests.support import DDY, EPW, needs_engine


@needs_engine
class TestARelativeRunDirRuns(unittest.TestCase):

    def test_sizing_with_a_relative_run_dir(self):
        import openstudio

        from btap import modeling, simulation
        from btap.modeling.hvac.catalog_report import FIXTURE

        model = openstudio.osversion.VersionTranslator().loadModel(
            openstudio.toPath(str(FIXTURE))).get()
        modeling.build_system(model, "PSZ-AC with gas coil", list(model.getThermalZones()))
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory(prefix="relative-run-") as tmp:
            os.chdir(tmp)
            try:
                result = simulation.run(model, run_dir="relative_run",
                                        weather={"epw": str(EPW), "ddy": str(DDY)},
                                        sizing_only=True)
                self.assertTrue(Path(result.run_dir).is_absolute(), result.run_dir)
                self.assertTrue(Path(result.run_dir).is_relative_to(Path(tmp).resolve()))
                self.assertTrue((Path(result.run_dir) / "eplusout.err").is_file())
                self.assertTrue(result.clean)
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
