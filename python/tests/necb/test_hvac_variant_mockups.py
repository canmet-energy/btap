"""D-33 full-pipeline gates for reference-system routes missed by the fleet."""

import json
import shutil
import tempfile
import unittest

from tests import support

FIXTURES = support.FIXTURES / "variant_mockups"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


@support.needs_sdk
class TestVariantMockups(unittest.TestCase):
    def run_mockup(self, name):
        from btap.necb.compliance import performance_compliance

        spec = MANIFEST[name]
        mode = "sizing" if support.engine_available() else "none"
        run_dir = tempfile.mkdtemp(prefix=f"mockup_{name}_")
        self.addCleanup(shutil.rmtree, run_dir, True)
        result = performance_compliance(
            str(FIXTURES / spec["osm"]), vintage="2020", simulate=mode,
            hdd=3890, weather={"epw": str(support.EPW), "ddy": str(support.DDY)},
            building=spec.get("building"), run_dir=run_dir,
        )
        return result, spec["expect"], mode

    def assert_expectations(self, result, expected, name):
        entries = result.audit.entries
        if selected := expected.get("selected"):
            values = [str(entry.get("value", "")) for entry in entries
                      if entry["action"] == "reference system selected"]
            self.assertTrue(any(selected in value for value in values),
                            f"{name}: expected selection {selected!r}, got {values!r}")
        if built := expected.get("built"):
            values = [str(entry.get("value", "")) for entry in entries
                      if entry["action"] == "reference system built"]
            self.assertTrue(any(built in value for value in values),
                            f"{name}: expected build {built!r}, got {values!r}")
        for key in ("decision", "decision2"):
            if decision := expected.get(key):
                self.assertTrue(any(decision in str(entry["action"])
                                    for entry in entries),
                                f"{name}: expected audit decision {decision!r}")
        if article := expected.get("article"):
            self.assertTrue(any(
                article in str(entry.get("article", ""))
                or article in str(entry["action"])
                for entry in entries
            ), f"{name}: expected article citation {article!r}")

    def exercise_mockup(self, name):
        result, expected, mode = self.run_mockup(name)
        self.assert_expectations(result, expected, name)
        if mode == "sizing":
            self.assertIsNotNone(result.reference_model,
                                 f"{name}: reference model present")
            errors = [entry for entry in result.audit.entries
                      if entry["level"] == "error"]
            self.assertEqual([], errors,
                             f"{name}: no error-level audit entries after sizing")

    def test_sys5_is_a_first_build_not_just_a_selection(self):
        result, _, _ = self.run_mockup("sys5_refrigerated")
        reference = result.reference_model
        zone_units = (
            len(reference.getZoneHVACFourPipeFanCoils())
            + len(reference.getZoneHVACUnitVentilators())
            + len(reference.getZoneHVACTerminalUnitVariableRefrigerantFlows())
            + len(reference.getZoneHVACBaseboardConvectiveWaters())
        )
        self.assertGreaterEqual(len(reference.getChillerElectricEIRs()), 1,
                                "System 5 reference carries a chiller plant")
        self.assertGreaterEqual(zone_units, 1,
                                "System 5 reference carries zone hydronic equipment")


def _mockup_test(name):
    def test(self):
        self.exercise_mockup(name)

    return test


for _name in MANIFEST:
    setattr(TestVariantMockups, f"test_{_name}", _mockup_test(_name))


if __name__ == "__main__":
    unittest.main()