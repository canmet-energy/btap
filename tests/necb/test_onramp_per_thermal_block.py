"""The on-ramp builds a single-zone system one unit per thermal block (D-101).

When the TOOL generates the proposed's HVAC (`--hvac-system`), a catalogue
row shared only by DEFAULT was built as ONE unit over every zone — one
thermostat for the whole building. On a five-zone office the zone holding it
was met and the others were not, whichever zone it was, and 8.4.1.2 failed
on the proposed for a reason no capacity increase or control rule could
reach. A row that states `per_zone`, either way, is built as catalogued.
"""

from __future__ import annotations

import tempfile
import unittest
import warnings

from tests.support import needs_sdk

DEFAULT_SHARED = "PSZ RTU Gas and DX Coils and Hot Water Baseboard"
EXPLICITLY_SHARED = "Shared PSZ with gas boiler coils and hot water baseboard"
PER_ZONE = "PSZ-AC with gas coil"
MULTI_ZONE = "MZ BU RTU Electric Heating Coil Scroll Chiller and Electric Baseboard"


@needs_sdk
class TestTheRule(unittest.TestCase):

    def test_only_a_row_shared_by_default_is_split(self):
        from btap.codes.necb.path import onramp_hvac_config
        self.assertEqual({"per_zone": True}, onramp_hvac_config(DEFAULT_SHARED))
        for name in (EXPLICITLY_SHARED, PER_ZONE, MULTI_ZONE):
            with self.subTest(row=name):
                self.assertIsNone(onramp_hvac_config(name))


@needs_sdk
class TestTheOnRamp(unittest.TestCase):
    """The CALL SITE: a compliance run's on-ramp builds per zone and says so."""

    def _run(self, hvac_system):
        from btap._compat import sorted_by_name
        from btap._sdk import load_model
        from btap.codes import performance_compliance
        from btap.modeling.hvac import catalog_report
        model = load_model(str(catalog_report.FIXTURE))
        spaces = {s.nameString(): ["Space Function", "Office enclosed > 25 m2"]
                  for s in sorted_by_name(model.getSpaces())}
        with tempfile.TemporaryDirectory() as run_dir, warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = performance_compliance(
                model, code="necb2020", simulate="none", hdd=3890, run_dir=run_dir,
                building={"storeys": 1},
                necb_loads={"space_type_map": spaces, "hvac_system": hvac_system})
        built = next(e for e in result.audit.entries
                     if e["action"].startswith("proposed HVAC built from the catalog"))
        split = [e for e in result.audit.entries if e.get("ruling") == "D-101"
                 and e["action"].startswith("single-zone system built one unit")]
        return built["inputs"], split

    def test_a_row_shared_by_default_gets_one_unit_per_zone(self):
        inputs, split = self._run(DEFAULT_SHARED)
        self.assertEqual(inputs["zones"], inputs["air_loops"])
        self.assertEqual(1, len(split))

    def test_an_explicitly_shared_row_stays_shared(self):
        inputs, split = self._run(EXPLICITLY_SHARED)
        self.assertEqual(1, inputs["air_loops"])
        self.assertEqual([], split)


if __name__ == "__main__":
    unittest.main()
