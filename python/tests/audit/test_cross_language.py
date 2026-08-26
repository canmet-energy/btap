"""The M1 cross-language gate (D-79): the Python AuditLog and the Ruby
btap-audit gem build the SAME scripted scenario; the outputs must agree.

- audit.json: compared with verification/compare_runs.py's own machinery —
  the exact rules Leg B will apply to full pipeline runs.
- audit.txt: byte-identical (stricter than Leg B requires; the narrative
  format is parsed by the umbrella's checklist classifier, so it is a
  contract, not cosmetics).

Skips when ruby or the sibling Ruby gem is absent (e.g. an installed wheel
outside the monorepo); in this repo and in CI both are present, so the gate
runs everywhere it matters.
"""

import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from btap.audit import AuditLog, emit_coverage

REPO_ROOT = Path(__file__).resolve().parents[3]
RUBY_SCRIPT = Path(__file__).parent / "cross_language" / "ruby_reference.rb"
RUBY_GEM = REPO_ROOT / "btap-audit" / "lib" / "btap_audit.rb"
COMPARE_RUNS = REPO_ROOT / "verification" / "compare_runs.py"


def build_python_scenario():
    """MUST mirror cross_language/ruby_reference.rb line for line — drift
    between the two copies is exactly what the comparison then fails on."""
    audit = AuditLog()

    with audit.with_building("input model"):
        audit.info("load", "model loaded — 1,000 m² floor area, climate 4200 HDD·°C",
                   inputs={"path": "model.osm", "spaces": 5})

    with audit.with_building("proposed building"):
        audit.decision("characterize", "zones grouped into one thermal block",
                       target="Thermal Zone 1",
                       inputs={"zones": ["Zone A", "Zone B"], "floor_area_m2": 123.456,
                               "conditioned": True},
                       value="System 6", article="8.4.4.8.(1)", ruling="D-14")
        audit.warn("efficiency", "boiler efficiency UNKNOWN",
                   inputs={"kw": 25.0, "fuel": "gas"}, evidence="OS:Boiler 'B1'")
        with audit.with_building("reference building"):
            audit.decision("build", "reference system operates on the proposed operating schedule",
                           article="8.4.4.7.(1)", ruling="D-14 D-21")
        audit.info("rules", "infiltration sentinel", value=1.5e-05)

    audit.decision("verdict", "proposed does not exceed the reference", value=True)
    audit.info("verdict", "margin below threshold", value=0)
    audit.info("verdict", "eui supplement computed", value=False)

    coverage = {
        "articles": [
            {"article": "8.4.4.7.", "title": "System selection", "status": "implemented",
             "how": "Table 8.4.4.7.-A", "code": "hvac/reference.rb#assign"},
            {"article": "8.4.4.9.", "title": "Staged heating", "status": "partial",
             "how": "two stages", "gaps": "modulating burners"},
            {"article": "8.4.1.1. (HVAC)", "title": "Modeller inputs", "status": "partial",
             "gap_owner": "modeller", "how": "schedules read from the model",
             "gaps": "occupancy assumptions"},
        ]
    }
    emit_coverage(coverage, audit)
    return audit


def load_compare_runs():
    spec = importlib.util.spec_from_file_location("compare_runs", COMPARE_RUNS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(shutil.which("ruby") and RUBY_GEM.exists() and COMPARE_RUNS.exists(),
                     "needs ruby + the sibling btap-audit gem + the Leg-B differ (monorepo layout)")
class TestCrossLanguageAudit(unittest.TestCase):
    def test_python_and_ruby_outputs_are_equivalent(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruby_dir = Path(tmp) / "ruby"
            py_dir = Path(tmp) / "python"
            ruby_dir.mkdir()
            py_dir.mkdir()

            result = subprocess.run(["ruby", str(RUBY_SCRIPT), str(ruby_dir)],
                                    capture_output=True, text=True)
            self.assertEqual(0, result.returncode, f"ruby reference failed: {result.stderr}")

            audit = build_python_scenario()
            (py_dir / "audit.json").write_text(audit.to_json(), encoding="utf-8")
            (py_dir / "audit.txt").write_text(str(audit), encoding="utf-8")

            # Leg-B machinery on audit.json — the real spec, the real differ.
            cr = load_compare_runs()
            spec = cr.load_spec(REPO_ROOT / "verification" / "spec.json")
            diffs = []
            cr.compare_file(ruby_dir, py_dir, "audit.json", spec, diffs)
            self.assertEqual([], diffs, "audit.json differs under the Leg-B rules:\n"
                             + "\n".join(diffs))

            # The narrative is byte-identical, not merely equivalent.
            ruby_txt = (ruby_dir / "audit.txt").read_text(encoding="utf-8")
            py_txt = (py_dir / "audit.txt").read_text(encoding="utf-8")
            self.assertEqual(ruby_txt, py_txt)

            # And the gate is not vacuous: the scenario exercised every level,
            # unicode, floats, nesting, and the coverage emitter.
            self.assertEqual(11, len(audit.entries))
            self.assertEqual(2, len(audit.warnings))


if __name__ == "__main__":
    unittest.main()
