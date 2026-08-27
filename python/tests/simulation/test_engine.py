"""The engine provisioner's contracts (M2, D-79): resolution order, the
version lock, and the remedy-naming errors. Nothing here downloads — the
download path's sha256/refusal logic is shared with the archive path, which
is tested with local files."""

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from btap.simulation import engine
from tests.support import CONTAINER_ENERGYPLUS


class EngineTestCase(unittest.TestCase):
    def setUp(self):
        engine._reset_memo()
        self.addCleanup(engine._reset_memo)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def fake_binary(self, version_line):
        """A shim that answers --version like an EnergyPlus would."""
        path = Path(self.tmp.name) / "energyplus"
        path.write_text(f"#!/bin/sh\necho '{version_line}'\n")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path


class TestOverrideResolution(EngineTestCase):
    @unittest.skipUnless(CONTAINER_ENERGYPLUS.is_file(),
                         "needs the container's bundled EnergyPlus")
    def test_btap_energyplus_override_resolves_and_verifies(self):
        with mock.patch.dict(os.environ, {"BTAP_ENERGYPLUS": str(CONTAINER_ENERGYPLUS)}):
            binary = engine.ensure_energyplus()
        self.assertEqual(CONTAINER_ENERGYPLUS, binary)

    @unittest.skipUnless(CONTAINER_ENERGYPLUS.is_file(),
                         "needs the container's bundled EnergyPlus")
    def test_override_accepts_the_install_directory_too(self):
        with mock.patch.dict(os.environ,
                             {"BTAP_ENERGYPLUS": str(CONTAINER_ENERGYPLUS.parent)}):
            binary = engine.ensure_energyplus()
        self.assertEqual(CONTAINER_ENERGYPLUS, binary)

    def test_nonexistent_override_names_the_remedy(self):
        with mock.patch.dict(os.environ, {"BTAP_ENERGYPLUS": "/nonexistent/energyplus"}):
            with self.assertRaises(engine.EngineError) as ctx:
                engine.ensure_energyplus()
        message = str(ctx.exception)
        self.assertIn("/nonexistent/energyplus", message, "must name what it tried")
        self.assertIn("BTAP_ENERGYPLUS", message, "must name the escape hatch")

    def test_version_skew_is_refused_with_both_versions_named(self):
        # The version lock: an engine that disagrees with the wheel's IDD
        # generation fails opaquely mid-run, so it is refused up front.
        shim = self.fake_binary("EnergyPlus, Version 9.1.0-abc0123456")
        with mock.patch.dict(os.environ, {"BTAP_ENERGYPLUS": str(shim)}):
            with self.assertRaises(engine.EngineError) as ctx:
                engine.ensure_energyplus()
        message = str(ctx.exception)
        self.assertIn("9.1.0", message)
        self.assertIn(engine.PINNED_VERSION, message)
        self.assertIn("refused", message)

    def test_non_energyplus_binary_is_reported(self):
        shim = self.fake_binary("definitely not an engine")
        with mock.patch.dict(os.environ, {"BTAP_ENERGYPLUS": str(shim)}):
            with self.assertRaises(engine.EngineError) as ctx:
                engine.ensure_energyplus()
        self.assertIn("did not identify itself as EnergyPlus", str(ctx.exception))

    @unittest.skipUnless(CONTAINER_ENERGYPLUS.is_file(),
                         "needs the container's bundled EnergyPlus")
    def test_resolution_is_memoized_per_process(self):
        with mock.patch.dict(os.environ, {"BTAP_ENERGYPLUS": str(CONTAINER_ENERGYPLUS)}):
            first = engine.ensure_energyplus()
        # memo survives the env var disappearing — set once at startup.
        with mock.patch.dict(os.environ, {"BTAP_ENERGYPLUS": ""}):
            second = engine.ensure_energyplus()
        self.assertEqual(first, second)


class TestArchiveSideLoad(EngineTestCase):
    def test_wrong_sha256_is_refused_and_names_the_official_asset(self):
        archive = Path(self.tmp.name) / "EnergyPlus-fake.tar.gz"
        archive.write_bytes(b"not the real archive")
        env = {"BTAP_ENERGYPLUS": "", "BTAP_ENERGYPLUS_ARCHIVE": str(archive)}
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(engine, "cache_dir",
                               return_value=Path(self.tmp.name) / "cache"):
            with self.assertRaises(engine.EngineError) as ctx:
                engine.ensure_energyplus()
        message = str(ctx.exception)
        self.assertIn("sha256", message)
        self.assertIn("EnergyPlus-25.2.0", message, "must name the official asset to fetch")

    def test_missing_archive_is_reported(self):
        env = {"BTAP_ENERGYPLUS": "", "BTAP_ENERGYPLUS_ARCHIVE": "/nonexistent.tar.gz"}
        with mock.patch.dict(os.environ, env), \
             mock.patch.object(engine, "cache_dir",
                               return_value=Path(self.tmp.name) / "cache"):
            with self.assertRaises(engine.EngineError) as ctx:
                engine.ensure_energyplus()
        self.assertIn("does not exist", str(ctx.exception))


class TestPins(EngineTestCase):
    def test_wheel_version_matches_the_pin_when_sdk_present(self):
        # openstudio~=3.11.0 <=> EnergyPlus 25.2 — the whole version-lock
        # premise. If this fails, the wheel and the pin table have diverged.
        self.assertEqual(engine.PINNED_VERSION, engine.wheel_energyplus_version())

    def test_every_pinned_asset_names_the_pinned_version(self):
        for (system, machine), (asset, sha256) in engine._ASSETS.items():
            self.assertIn(engine.PINNED_VERSION, asset, (system, machine))
            self.assertEqual(64, len(sha256), f"{asset}: sha256 must be complete")

    def test_cache_dir_is_versioned(self):
        self.assertTrue(str(engine.cache_dir("25.2.0")).endswith("25.2.0"))


if __name__ == "__main__":
    unittest.main()
