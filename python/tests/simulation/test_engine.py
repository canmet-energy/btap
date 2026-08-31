"""The engine provisioner's contracts (M2, D-79): resolution order, the
version lock, and the remedy-naming errors. Nothing here downloads — the
download path's sha256/refusal logic is shared with the archive path, which
is tested with local files."""

import os
import stat
import sys
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
    def test_canmet_energyplus_override_resolves_and_verifies(self):
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


class FakeCompanion:
    """A stand-in canmet_energyplus module injected via sys.modules."""

    def __init__(self, version, binary):
        self.ENERGYPLUS_VERSION = version
        self.BUILD_SHA = "fake"
        self._binary = binary

    def binary_path(self):
        if isinstance(self._binary, Exception):
            raise self._binary
        return self._binary


class TestCompanionResolution(EngineTestCase):
    """The R5 companion rung (D-83): fail-closed once the package imports;
    only genuine ABSENCE falls through. Each control mirrors one way a
    corrupted or mismatched companion could otherwise hide behind the
    stale cache or a network download."""

    def install_fake(self, module):
        sys.modules["canmet_energyplus"] = module
        self.addCleanup(sys.modules.pop, "canmet_energyplus", None)

    def test_companion_resolves_before_the_cache(self):
        # H-1: a stale/wrong cache must LOSE to the shipped companion.
        cache = engine.cache_dir(engine.PINNED_VERSION)
        cache.mkdir(parents=True, exist_ok=True)
        stale = cache / "energyplus"
        if not stale.exists():
            stale.write_text("#!/bin/sh\necho 'EnergyPlus, Version 9.9.9'\n")
            stale.chmod(0o755)
            self.addCleanup(stale.unlink)
        good = self.fake_binary(f"EnergyPlus, Version {engine.PINNED_VERSION}-abc")
        self.install_fake(FakeCompanion(engine.PINNED_VERSION, good))
        self.assertEqual(good, engine.ensure_energyplus())

    def test_bad_override_raises_even_with_companion_present(self):
        # H-2: the frozen exit-4 scenario's premise — BTAP_ENERGYPLUS
        # set-but-bad NEVER falls through, companion or no companion.
        good = self.fake_binary(f"EnergyPlus, Version {engine.PINNED_VERSION}-abc")
        self.install_fake(FakeCompanion(engine.PINNED_VERSION, good))
        os.environ["BTAP_ENERGYPLUS"] = "/nonexistent-energyplus"
        self.addCleanup(os.environ.pop, "BTAP_ENERGYPLUS", None)
        with self.assertRaises(engine.EngineError) as ctx:
            engine.ensure_energyplus()
        self.assertIn("BTAP_ENERGYPLUS", str(ctx.exception))

    def test_absent_companion_falls_through(self):
        # Genuine absence (optional platforms) is the ONLY fall-through.
        self.assertIsNone(engine._companion_binary(engine.PINNED_VERSION))

    def test_broken_import_raises(self):
        class Exploding:
            @property
            def ENERGYPLUS_VERSION(self):
                raise RuntimeError("data file missing")
        self.install_fake(Exploding())
        with self.assertRaises(engine.EngineError) as ctx:
            engine._companion_binary(engine.PINNED_VERSION)
        self.assertIn("broken", str(ctx.exception))

    def test_wrong_metadata_raises(self):
        good = self.fake_binary("EnergyPlus, Version 9.1.0-xyz")
        self.install_fake(FakeCompanion("9.1.0", good))
        with self.assertRaises(engine.EngineError) as ctx:
            engine._companion_binary(engine.PINNED_VERSION)
        self.assertIn("9.1.0", str(ctx.exception))

    def test_missing_binary_raises(self):
        self.install_fake(FakeCompanion(engine.PINNED_VERSION,
                                        Path(self.tmp.name) / "nope"))
        with self.assertRaises(engine.EngineError) as ctx:
            engine._companion_binary(engine.PINNED_VERSION)
        self.assertIn("no such", str(ctx.exception))

    def test_unrunnable_companion_binary_raises(self):
        # A lying binary is caught by _verify_version at the
        # ensure_energyplus level — never a silent fall-through.
        liar = self.fake_binary("EnergyPlus, Version 9.1.0-xyz")
        self.install_fake(FakeCompanion(engine.PINNED_VERSION, liar))
        with self.assertRaises(engine.EngineError) as ctx:
            engine.ensure_energyplus()
        self.assertIn("canmet-energyplus companion", str(ctx.exception))

    def test_broken_submodule_import_raises_not_absent(self):
        # Sol's PR-1 follow-up control: a companion whose __init__ fails
        # importing its own submodule is INSTALLED AND BROKEN — the broad
        # except ImportError used to misread it as absent and fall through.
        pkg = Path(self.tmp.name) / "site" / "canmet_energyplus"
        pkg.mkdir(parents=True)
        (pkg / "__init__.py").write_text(
            "import canmet_energyplus.payload\n", encoding="utf-8")
        sys.path.insert(0, str(pkg.parent))
        self.addCleanup(sys.path.remove, str(pkg.parent))
        self.addCleanup(sys.modules.pop, "canmet_energyplus", None)
        with self.assertRaises(engine.EngineError) as ctx:
            engine._companion_binary(engine.PINNED_VERSION)
        self.assertIn("canmet_energyplus.payload", str(ctx.exception))
