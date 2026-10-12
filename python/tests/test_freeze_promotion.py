"""Atomic promotion of frozen baselines and their manifest.

`freeze.promote()` makes four moves: old baselines and manifest to backups,
then staged baselines and manifest into place. A failure at any one must
leave the previous pair intact. The fourth move is the dangerous case: new
baselines have already landed while the old manifest is in backup, so
rollback must remove the newcomer before restoring the old pair.
"""

from __future__ import annotations

import importlib.util
import pathlib
import shutil
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
