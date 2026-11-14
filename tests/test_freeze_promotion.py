"""Publication and atomic promotion of baselines and their manifest.

`freeze.publish_freeze()` stages the manifest beside the baseline tree and
hands both to `freeze.promote()`. Promotion makes four moves when an old pair
exists: old baselines and manifest to backups, then staged baselines and
manifest into place. A failure must leave the previous pair intact, or leave
neither destination on a first freeze. The final move is the dangerous case:
new baselines have already landed while the old manifest is in backup, so
rollback must remove the newcomer before restoring the old pair.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FREEZE = REPO_ROOT / "verification" / "scenarios" / "freeze.py"


def _load_freeze():
    spec = importlib.util.spec_from_file_location(
        "freeze_promotion_under_test", FREEZE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["freeze_promotion_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _tree_bytes(root):
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class InjectedMoveFailure(RuntimeError):
    pass


class TestFreezePromotionRollback(unittest.TestCase):
    OLD_BASELINES = {
        "scenario-a/report.json": b'{"version": "old-a"}\n',
        "scenario-b/nested/audit.json": b'{"version": "old-b"}\n',
    }
    NEW_BASELINES = {
        "scenario-a/report.json": b'{"version": "new-a"}\n',
        "scenario-c/report.json": b'{"version": "new-c"}\n',
    }
    OLD_MANIFEST = b'{"version": "old-manifest"}\n'
    NEW_MANIFEST = b'{"version": "new-manifest"}\n'

    def setUp(self):
        self.freeze = _load_freeze()

    def _write_tree(self, root, files):
        root.mkdir()
        for relative, payload in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)

    def _fixture(self, work):
        staged_baselines = work / "staged-baselines"
        staged_manifest = work / "staged-manifest.json"
        dest_baselines = work / "baselines"
        dest_manifest = work / "manifest.json"
        self._write_tree(staged_baselines, self.NEW_BASELINES)
        self._write_tree(dest_baselines, self.OLD_BASELINES)
        staged_manifest.write_bytes(self.NEW_MANIFEST)
        dest_manifest.write_bytes(self.OLD_MANIFEST)
        return (staged_baselines, staged_manifest,
                dest_baselines, dest_manifest)

    def _assert_previous_pair(self, work, dest_baselines, dest_manifest):
        self.assertEqual(self.OLD_BASELINES, _tree_bytes(dest_baselines))
        self.assertEqual(self.OLD_MANIFEST, dest_manifest.read_bytes())
        self.assertEqual(
            [], list(work.glob("*.backup.*")),
            "rollback must not leave a backup that can be mistaken for "
            "another recoverable state")

    def _fail_at(self, fail_at, observe=None):
        with tempfile.TemporaryDirectory(
                prefix=f"freeze-promote-fail-{fail_at}-") as tmp:
            work = pathlib.Path(tmp)
            paths = self._fixture(work)
            calls = []

            def mover(source, destination):
                calls.append((source, destination))
                if len(calls) == fail_at:
                    if observe is not None:
                        observe(*paths)
                    raise InjectedMoveFailure(f"move {fail_at}")
                return shutil.move(source, destination)

            with self.assertRaisesRegex(
                    InjectedMoveFailure, f"move {fail_at}"):
                self.freeze.promote(*paths, mover=mover)

            self.assertEqual(
                fail_at, len(calls),
                "the injected failure must occur at the named promotion "
                "move, not in setup or rollback")
            self._assert_previous_pair(work, paths[2], paths[3])

    def _assert_previous_state(self, work, dest_baselines, dest_manifest,
                               prior_baselines, prior_manifest):
        if prior_baselines:
            self.assertEqual(
                self.OLD_BASELINES, _tree_bytes(dest_baselines))
        else:
            self.assertFalse(dest_baselines.exists())
        if prior_manifest:
            self.assertEqual(self.OLD_MANIFEST, dest_manifest.read_bytes())
        else:
            self.assertFalse(dest_manifest.exists())
        self.assertEqual(
            [], list(work.glob("*.backup.*")),
            "rollback must restore the prior occupancy without nesting or "
            "leaving a second recoverable state")

    def _fail_after_publication_started(
            self, target, shape, prior_baselines, prior_manifest):
        with tempfile.TemporaryDirectory(
                prefix=f"freeze-promote-{target}-{shape}-") as tmp:
            work = pathlib.Path(tmp)
            staged_baselines = work / "staged-baselines"
            staged_manifest = work / "staged-manifest.json"
            dest_baselines = work / "baselines"
            dest_manifest = work / "manifest.json"
            self._write_tree(staged_baselines, self.NEW_BASELINES)
            staged_manifest.write_bytes(self.NEW_MANIFEST)
            if prior_baselines:
                self._write_tree(dest_baselines, self.OLD_BASELINES)
            if prior_manifest:
                dest_manifest.write_bytes(self.OLD_MANIFEST)

            failed_source = (staged_baselines if target == "baselines"
                             else staged_manifest)
            injected = []

            def mover(source, destination):
                source = pathlib.Path(source)
                destination = pathlib.Path(destination)
                if source != failed_source:
                    return shutil.move(source, destination)

                if shape == "complete":
                    shutil.move(source, destination)
                elif source.is_dir():
                    first = next(
                        path for path in sorted(source.rglob("*"))
                        if path.is_file())
                    partial = destination / first.relative_to(source)
                    partial.parent.mkdir(parents=True)
                    shutil.copy2(first, partial)
                else:
                    payload = source.read_bytes()
                    destination.write_bytes(payload[:len(payload) // 2])
                injected.append((target, shape))
                raise InjectedMoveFailure(
                    f"{shape} {target} publication")

            with self.assertRaisesRegex(
                    InjectedMoveFailure,
                    f"{shape} {target} publication"):
                self.freeze.promote(
                    staged_baselines, staged_manifest,
                    dest_baselines, dest_manifest, mover=mover)

            self.assertEqual(
                [(target, shape)], injected,
                "the failure must occur after occupying the named "
                "publication destination")
            self._assert_previous_state(
                work, dest_baselines, dest_manifest,
                prior_baselines, prior_manifest)

    def test_EACH_of_the_four_move_failures_restores_the_previous_pair(self):
        for fail_at in range(1, 5):
            with self.subTest(failed_move=fail_at):
                self._fail_at(fail_at)

    def test_FOURTH_move_failure_rolls_back_new_baselines_already_in_place(self):
        observed = {}

        def observe(_staged_baselines, _staged_manifest,
                    dest_baselines, dest_manifest):
            observed["baselines"] = _tree_bytes(dest_baselines)
            observed["manifest_absent"] = not dest_manifest.exists()

        self._fail_at(4, observe=observe)
        self.assertEqual(
            self.NEW_BASELINES, observed["baselines"],
            "the fourth-step control must reach the torn-state window: the "
            "new baselines have landed before the manifest move fails")
        self.assertTrue(
            observed["manifest_absent"],
            "the old manifest must be in backup when the fourth move fails; "
            "the assertion after rollback proves it was restored")

    def test_PARTIAL_or_complete_publication_then_failure_restores_occupancy(
            self):
        """Cross-device moves can raise after creating their destination."""
        for prior_baselines in (False, True):
            for prior_manifest in (False, True):
                for target in ("baselines", "manifest"):
                    for shape in ("partial", "complete"):
                        with self.subTest(
                                prior_baselines=prior_baselines,
                                prior_manifest=prior_manifest,
                                target=target, shape=shape):
                            self._fail_after_publication_started(
                                target, shape, prior_baselines,
                                prior_manifest)

    def test_manifest_failure_removes_new_baselines_without_an_old_tree(self):
        """A first freeze must not leave half of a new pair standing."""
        for prior_manifest in (True, False):
            with self.subTest(prior_manifest=prior_manifest), \
                    tempfile.TemporaryDirectory(
                        prefix="freeze-promote-first-") as tmp:
                work = pathlib.Path(tmp)
                staged_baselines = work / "staged-baselines"
                staged_manifest = work / "staged-manifest.json"
                dest_baselines = work / "baselines"
                dest_manifest = work / "manifest.json"
                self._write_tree(staged_baselines, self.NEW_BASELINES)
                staged_manifest.write_bytes(self.NEW_MANIFEST)
                if prior_manifest:
                    dest_manifest.write_bytes(self.OLD_MANIFEST)
                observed = {}

                def mover(source, destination, *,
                          expected_manifest=staged_manifest,
                          landed=observed,
                          destination_baselines=dest_baselines):
                    if pathlib.Path(source) == expected_manifest:
                        landed["landed"] = _tree_bytes(
                            destination_baselines)
                        raise InjectedMoveFailure("manifest publication")
                    return shutil.move(source, destination)

                with self.assertRaisesRegex(
                        InjectedMoveFailure, "manifest publication"):
                    self.freeze.promote(
                        staged_baselines, staged_manifest,
                        dest_baselines, dest_manifest, mover=mover)

                self.assertEqual(
                    self.NEW_BASELINES, observed["landed"],
                    "the control must reach the first-freeze torn-state "
                    "window before injecting the manifest failure")
                self.assertFalse(
                    dest_baselines.exists(),
                    "new baselines must not survive without their manifest")
                if prior_manifest:
                    self.assertEqual(
                        self.OLD_MANIFEST, dest_manifest.read_bytes())
                else:
                    self.assertFalse(dest_manifest.exists())
                self.assertEqual([], list(work.glob("*.backup.*")))


class TestPublishFreezeLandsAtTheDestination(unittest.TestCase):
    """Exercise the production bridge from staged output to `promote()`."""

    def setUp(self):
        self.freeze = _load_freeze()

    def _publish(self, staged):
        with tempfile.TemporaryDirectory(prefix="freeze-publish-") as tmp:
            work = pathlib.Path(tmp)
            destination = work / "dest"
            dest_baselines = destination / "baselines"
            dest_manifest = destination / "manifest.json"
            (dest_baselines / "old").mkdir(parents=True)
            (dest_baselines / "old" / "report.json").write_bytes(b"OLD")
            dest_manifest.write_bytes(b"OLD-M")

            staging = work / "staging"
            staging.mkdir()
            baselines = None
            if staged:
                baselines = staging / "baselines"
                (baselines / "sc-a").mkdir(parents=True)
                (baselines / "sc-a" / "report.json").write_bytes(b"NEW")
            manifest = {"version": 2, "scenarios": []}

            with mock.patch.object(
                    self.freeze.tempfile, "mkdtemp",
                    return_value=str(staging)), \
                    mock.patch.object(
                        self.freeze.runner, "BASELINES", dest_baselines), \
                    mock.patch.object(
                        self.freeze.runner, "MANIFEST", dest_manifest):
                self.freeze.publish_freeze(manifest, baselines)

            expected = {"sc-a/report.json": b"NEW"} if staged else {}
            self.assertEqual(expected, _tree_bytes(dest_baselines))
            self.assertEqual(
                manifest,
                json.loads(dest_manifest.read_text(encoding="utf-8")))
            self.assertEqual(
                [], list(destination.glob("*.backup.*")),
                "a successful promotion must clean both backups")

    def test_a_staged_tree_and_manifest_are_promoted(self):
        self._publish(staged=True)

    def test_the_empty_corpus_branch_publishes_an_empty_tree(self):
        self._publish(staged=False)

    def test_the_loaded_environment_wires_the_production_seams(self):
        with tempfile.TemporaryDirectory(
                prefix="freeze-environment-") as tmp:
            work = pathlib.Path(tmp)
            scripts = work / "scripts"
            scripts.mkdir()
            (scripts / "sample_manifest.json").write_text(
                '{"samples": ["sample-a"]}\n', encoding="utf-8")

            def fake_git(*args):
                return "" if args[0] == "status" else "c" * 40

            with mock.patch.object(
                    self.freeze.runner, "PYTHON_ROOT", work), \
                    mock.patch.object(
                        self.freeze.runner, "MANIFEST",
                        work / "absent-manifest.json"), \
                    mock.patch.object(
                        self.freeze.runner, "sha256",
                        side_effect=("spec-hash", "samples-hash")), \
                    mock.patch.object(
                        self.freeze, "git", side_effect=fake_git):
                environment = self.freeze.load_freeze_environment()

        self.assertIs(
            self.freeze.publish_freeze, environment["publish"],
            "main must receive the real publisher, not a no-op seam")
        self.assertIs(
            self.freeze.invocation_producer, environment["producer"],
            "main must receive the real producer probe")
        self.assertEqual(["sample-a"], environment["slugs"])
        self.assertEqual("c" * 40, environment["commit"])


if __name__ == "__main__":
    unittest.main()
