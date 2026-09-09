"""Direct unit tests for the NECB edition-delta generator's diffing logic.

Two reviewer findings against ``generate_necb_edition_delta.py``:

1. ``pair_files``/``diff_whole_files`` only compared rule keys and tables
   present in BOTH editions' manifests under the SAME relative path. An
   edition-only output (a 2025-only rule/table/singular file, a renamed
   rule file, a renamed table) vanished from the comparison silently
   instead of being reported as added/removed/renamed.
2. The cross-path ("moved key") renumbering pairing matched an old and a
   new leaf whose CANONICAL PATH was unique on both sides and reported the
   pair as a renumbering WITHOUT checking whether the two leaf VALUES were
   also equal after canonicalisation -- so a limit that changed value (not
   just citation number) while its key also moved would be misclassified
   as pure renumbering.

These fixtures are synthetic -- NOT the real necb2020/necb2025 data -- so
each scenario isolates exactly one classification. The real
docs/NECB_EDITION_DELTAS.md regeneration (and
python/tests/necb/test_edition_provenance.py's coverage-set assertions) is
the integration proof that the real manifests still produce the right
document.
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.support import REPO_ROOT

SCRIPT = REPO_ROOT / "python" / "scripts" / "generate_necb_edition_delta.py"
_SPEC = importlib.util.spec_from_file_location("generate_necb_edition_delta", SCRIPT)
gen = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gen)


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _build_fixture_tree(root: Path) -> None:
    """A synthetic two-edition NECB data tree exercising every
    classification the generator makes:

    - ``tables/only_old.json`` / ``tables/only_new.json`` / ``eui_targets``:
      an edition-only file on each side -- (a) added, (b) removed.
    - ``envelope``'s rule file is renamed (``envelope_rules.json`` ->
      ``envelope_rules_v2.json``) under the SAME manifest key -- (c) a
      whole-file rename, matched by key, not dropped.
    - ``tables/foo_2020.json`` -> ``tables/foo.json``: a table (no manifest
      key of its own) matched by canonical basename with the edition-year
      suffix stripped -- a second (c) rename, by a different mechanism.
    - Within the renamed envelope file, ``8.4.4.1_limit_a`` moves to
      ``8.4.5.1_limit_a`` with the SAME value (5 -> 5): (d) a moved leaf
      whose canonical value matches is a RENUMBERING.
    - ``8.4.4.2_limit_b`` moves to ``8.4.5.2_limit_b`` with a DIFFERENT
      value (1 -> 2): (e) a moved leaf whose value also changed is CHANGED,
      never folded into renumbering just because the key moved too.
    """
    data_root = root / "python" / "btap" / "codes" / "necb" / "data"

    _write_json(data_root / "necb2020" / "manifest.json", {
        "id": "necb2020",
        "family": "necb",
        "edition": "2020",
        "label": "NECB 2020 (fixture)",
        "rules": {"envelope": "envelope_rules.json"},
        "tables": ["tables/foo_2020.json", "tables/only_old.json"],
    })
    _write_json(data_root / "necb2020" / "envelope_rules.json", {
        "8.4.4.1_limit_a": 5,
        "8.4.4.2_limit_b": 1,
    })
    _write_json(data_root / "necb2020" / "tables" / "foo_2020.json", {"a": 1})
    _write_json(data_root / "necb2020" / "tables" / "only_old.json", {"x": 1})

    _write_json(data_root / "necb2025" / "manifest.json", {
        "id": "necb2025",
        "family": "necb",
        "edition": "2025",
        "label": "NECB 2025 (fixture)",
        "rules": {"envelope": "envelope_rules_v2.json"},
        "tables": ["tables/foo.json", "tables/only_new.json"],
        "eui_targets": "eui_targets.json",
    })
    _write_json(data_root / "necb2025" / "envelope_rules_v2.json", {
        "8.4.5.1_limit_a": 5,
        "8.4.5.2_limit_b": 2,
    })
    _write_json(data_root / "necb2025" / "tables" / "foo.json", {"a": 1})
    _write_json(data_root / "necb2025" / "tables" / "only_new.json", {"y": 1})
    _write_json(data_root / "necb2025" / "eui_targets.json", {"z": 1})


class TestWholeFileDiff(unittest.TestCase):
    """(a)-(c): whole-file added/removed/renamed over the union of
    manifest-declared outputs."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        _build_fixture_tree(self.root)
        manifests = gen.load_manifests(self.root)
        self.assertEqual(2, len(manifests))
        self.older, self.newer = manifests[0], manifests[1]
        self.assertEqual("necb2020", self.older["id"])
        self.assertEqual("necb2025", self.newer["id"])
        self.whole_file_delta, self.pairs = gen.diff_whole_files(self.older, self.newer)

    def test_edition_only_table_is_added(self):
        added = {path for _, path in self.whole_file_delta.added}
        self.assertIn("tables/only_new.json", added)

    def test_edition_only_singular_key_is_added(self):
        added = {path for _, path in self.whole_file_delta.added}
        self.assertIn("eui_targets.json", added)

    def test_removed_table_is_removed(self):
        removed = {path for _, path in self.whole_file_delta.removed}
        self.assertIn("tables/only_old.json", removed)
        # And it must NOT also show up as added or renamed.
        self.assertNotIn("tables/only_old.json", {p for _, p in self.whole_file_delta.added})
        renamed_olds = {old for _, old, _ in self.whole_file_delta.renamed}
        self.assertNotIn("tables/only_old.json", renamed_olds)

    def test_renamed_rules_file_matched_by_manifest_key(self):
        renamed = {(old, new) for _, old, new in self.whole_file_delta.renamed}
        self.assertIn(("envelope_rules.json", "envelope_rules_v2.json"), renamed)

    def test_renamed_table_matched_by_canonical_basename(self):
        renamed = {(old, new) for _, old, new in self.whole_file_delta.renamed}
        self.assertIn(("tables/foo_2020.json", "tables/foo.json"), renamed)

    def test_renamed_files_still_feed_the_leaf_diff(self):
        # A rename is not just noted at the whole-file level -- its content
        # is still compared, unlike an added/removed file (which has no
        # counterpart to compare against).
        matched = {(old, new) for _, old, new in self.pairs}
        self.assertIn(("envelope_rules.json", "envelope_rules_v2.json"), matched)
        self.assertIn(("tables/foo_2020.json", "tables/foo.json"), matched)

    def test_added_and_removed_files_never_appear_in_pairs(self):
        matched_old = {old for _, old, _ in self.pairs}
        matched_new = {new for _, _, new in self.pairs}
        self.assertNotIn("tables/only_old.json", matched_old)
        self.assertNotIn("tables/only_new.json", matched_new)
        self.assertNotIn("eui_targets.json", matched_new)


class TestMovedLeafClassification(unittest.TestCase):
    """(d)-(e): a leaf that moved to a different key is a RENUMBERING only
    when its canonical value also matches; otherwise it is CHANGED."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        _build_fixture_tree(self.root)
        manifests = gen.load_manifests(self.root)
        older, newer = manifests[0], manifests[1]
        _, pairs = gen.diff_whole_files(older, newer)
        deltas = gen.collect_pair_deltas(older, newer, pairs)
        self.envelope = next(d for d in deltas if d.domain == "envelope")

    def test_moved_leaf_with_equal_canonical_value_is_renumbered(self):
        renumbered_keys = {(old[0], new[0]) for old, _, new, _ in self.envelope.renumbered}
        self.assertIn(("8.4.4.1_limit_a", "8.4.5.1_limit_a"), renumbered_keys)

    def test_moved_leaf_with_changed_value_is_changed_not_renumbered(self):
        changed_keys = {(old[0], new[0]) for old, _, new, _ in self.envelope.changed}
        self.assertIn(("8.4.4.2_limit_b", "8.4.5.2_limit_b"), changed_keys)
        # The bug under test: this must NEVER also land in `renumbered`.
        renumbered_old_keys = {old[0] for old, _, _, _ in self.envelope.renumbered}
        self.assertNotIn("8.4.4.2_limit_b", renumbered_old_keys)

    def test_moved_and_changed_leaf_reports_old_and_new_value(self):
        old_path, old_value, new_path, new_value = next(
            row for row in self.envelope.changed if row[0][0] == "8.4.4.2_limit_b"
        )
        self.assertEqual("8.4.5.2_limit_b", new_path[0])
        self.assertEqual(1, old_value)
        self.assertEqual(2, new_value)

    def test_unmoved_pure_renumbering_is_unaffected(self):
        # Sanity check against the fix over-correcting: a moved leaf whose
        # value is untouched is still exactly one renumbering, not also a
        # change.
        matches = [row for row in self.envelope.renumbered if row[0][0] == "8.4.4.1_limit_a"]
        self.assertEqual(1, len(matches))
        self.assertEqual(0, len([r for r in self.envelope.changed if r[0][0] == "8.4.4.1_limit_a"]))


class TestCheckFlag(unittest.TestCase):
    """(f): --check passes against a freshly-regenerated document and fails
    the moment the committed document drifts by even one character."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        _build_fixture_tree(self.root)
        self.output = self.root / "NECB_EDITION_DELTAS.md"
        gen.generate(self.root, self.output)

    def test_check_passes_on_freshly_generated_document(self):
        result = gen.main(["--repo-root", str(self.root), "--output", str(self.output), "--check"])
        self.assertEqual(0, result)

    def test_check_fails_on_one_character_drift(self):
        text = self.output.read_text(encoding="utf-8")
        self.assertIn("NECB edition-to-edition deltas", text)
        mutated = text.replace("NECB edition-to-edition deltas", "NECB edition-to-edition deltaz")
        self.assertNotEqual(text, mutated)
        self.output.write_text(mutated, encoding="utf-8")
        result = gen.main(["--repo-root", str(self.root), "--output", str(self.output), "--check"])
        self.assertEqual(1, result)


class TestRepoRootIsolation(unittest.TestCase):
    """Every scenario above runs against a temp ``--repo-root`` tree, never
    the real repository's necb2020/necb2025 manifests."""

    def test_repo_root_flag_selects_the_fixture_tree(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _build_fixture_tree(root)
            manifests = gen.load_manifests(root)
            self.assertEqual({"necb2020", "necb2025"}, {m["id"] for m in manifests})
            for manifest in manifests:
                self.assertIn(root, manifest["_dir"].parents)


if __name__ == "__main__":
    unittest.main()
