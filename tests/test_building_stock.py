"""Deterministic tests for the HBIX building-stock maintainer adapter."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests import support

SCRIPT_PATH = support.REPO_ROOT / "python" / "scripts" / "building_stock.py"
SPEC = importlib.util.spec_from_file_location("building_stock_script", SCRIPT_PATH)
building_stock = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(building_stock)

RECORD = {
    "feature_id": "test-building",
    "building_area_m2": 1200.0,
    "height_max_m": 10.5,
    "building_class": "Commercial",
    "fsa": "K1P",
    "geometry_geojson": {
        "type": "Polygon",
        "coordinates": [[
            [-75.6972, 45.4215],
            [-75.6968, 45.4215],
            [-75.6968, 45.4212],
            [-75.6972, 45.4212],
            [-75.6972, 45.4215],
        ]],
    },
}


class RecordingClient:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {"buildings": [RECORD]}

    def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        return self.result


class TestBuildingStockData(unittest.TestCase):
    def test_rejection_and_height_match_the_adapter_contract(self):
        self.assertEqual((10.5, "height_max_m"), building_stock.height_of(RECORD))
        self.assertIsNone(building_stock.rejection(RECORD))
        self.assertIn("no geometry", building_stock.rejection({}))
        self.assertEqual("no usable height", building_stock.rejection({
            "geometry_geojson": RECORD["geometry_geojson"],
            "building_area_m2": 1200.0,
        }))

    def test_provenance_is_allowlisted_and_never_carries_credentials(self):
        record = {**RECORD, "HBIX_API_KEY": "secret", "untrusted": "value"}
        provenance = building_stock.provenance(record, "height_max_m")
        self.assertEqual("nrcan-buildings", provenance["dataset"])
        self.assertEqual("test-building", provenance["feature_id"])
        self.assertNotIn("HBIX_API_KEY", provenance)
        self.assertNotIn("untrusted", provenance)

    def test_all_query_modes_send_the_ruby_argument_shape(self):
        cases = {
            "fsa": ({"limit": 7, "fsa": "K1P"}, "query_buildings_fsa",
                    {"fsa": "K1P"}),
            "point": ({"limit": 7, "lat": 45.42, "lon": -75.69,
                       "radius": 300}, "query_buildings_point",
                      {"lat": 45.42, "lon": -75.69, "radius_m": 300}),
            "bbox": ({"limit": 7, "west": -75.70, "south": 45.41,
                      "east": -75.69, "north": 45.43},
                     "query_buildings_bbox",
                     {"west": -75.70, "south": 45.41,
                      "east": -75.69, "north": 45.43}),
        }
        common = {"dataset_id": "nrcan-buildings",
                  "include_geometry": True, "limit": 7}
        for mode, (options, tool, specific) in cases.items():
            with self.subTest(mode=mode):
                client = RecordingClient()
                self.assertEqual([RECORD], building_stock.query_buildings(
                    client, mode, options))
                self.assertEqual([(tool, {**common, **specific})], client.calls)

    def test_from_cache_dry_run_needs_no_hbix_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "records.json"
            cache.write_text(json.dumps([RECORD]), encoding="utf-8")
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith("HBIX_")}
            result = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), "--from-cache", str(cache),
                 "--dry-run"], env=env, capture_output=True, text=True,
                timeout=30,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("fetched 1 record(s)", result.stderr)


@support.needs_sdk
class TestBuildingStockModel(unittest.TestCase):
    def test_record_builds_and_is_stamped(self):
        result = building_stock.to_model(RECORD, zoning="single", multiplier="none")
        self.assertIsNotNone(result["model"])
        model = result["model"]
        self.assertTrue(model.getSpaces())
        self.assertEqual("NRCan test-building", model.getBuilding().nameString())
        properties = model.getBuilding().additionalProperties()
        self.assertTrue(properties.hasFeature("nrcan_feature_id"))


if __name__ == "__main__":
    unittest.main()