"""The committed Leg-C goldens are internally consistent and current with the pin.

The Python successor to btap-necb/test/test_oracle_goldens_current.rb, ported
for R6 (D-80). Four duties and no more: REF equality, file existence,
checksums, and request-manifest inventory consistency.

Deliberately NOT a freshness check. Comparing the frozen values against the
LIVE oracle is compare_goldens.py's job inside live_leg_c.sh, so there are
never two overlapping freshness implementations. The division matters: this
file needs no oracle and no bundle, so it runs in the ordinary Python job on
every push — which is the point. It catches a hand-edited golden, a REF bump
without a re-export, or a stale group, WITHOUT waiting for the parity job,
which is workflow_dispatch-only.
"""

from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_DIR = REPO_ROOT / "verification" / "oracle" / "goldens"
REQUEST = REPO_ROOT / "verification" / "oracle" / "request_manifest.json"
PIN_REF = REPO_ROOT / "legacy_pin" / "REF"

sys.path.insert(0, str(REPO_ROOT / "verification" / "oracle"))
from inventory import validate  # noqa: E402

REMEDY = ("regenerate under the pin: python/scripts/oracle_prep.py then "
          "verification/oracle/export_goldens.rb (or dispatch the goldens "
          "workflow)")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class TestOracleGoldensCurrent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = GOLDEN_DIR / "manifest.json"
        if not manifest.is_file():
            raise AssertionError(f"goldens manifest missing — {REMEDY}")
        cls.manifest = _load(manifest)
        cls.request = _load(REQUEST)

    def test_manifest_ref_equals_the_pin(self):
        """Duty 1: the goldens describe THE pinned oracle revision."""
        ref = PIN_REF.read_text(encoding="utf-8").strip()
        self.assertEqual(
            ref, self.manifest["legacy_ref"],
            f"goldens were exported from a DIFFERENT oracle revision — {REMEDY}")

    def test_files_exist_and_match_checksums(self):
        """Duties 2 and 3: every listed file exists and matches its checksum,
        and the directory holds NOTHING beyond the listed files — an obsolete
        group with a valid checksum and no consumer is a failure, not an
        extra."""
        listed = self.manifest["files"]
        self.assertTrue(listed, "the manifest lists no files")
        for name, sha in listed.items():
            path = GOLDEN_DIR / name
            self.assertTrue(path.is_file(),
                            f"manifest lists {name} but it is missing — {REMEDY}")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(
                sha, digest,
                f"{name} does not match its manifest checksum — hand-edited? {REMEDY}")
        on_disk = sorted(p.name for p in GOLDEN_DIR.glob("*.json")
                         if p.name != "manifest.json")
        self.assertEqual(
            sorted(listed), on_disk,
            f"goldens directory does not hold exactly the manifest's file set — {REMEDY}")

    def test_request_manifest_inventory_consistency(self):
        """Duty 4: every golden matches the request manifest's recursive
        inventory — the implementation-independent statement of what the
        oracle was asked for."""
        groups = self.request["golden_groups"]
        self.assertEqual(
            sorted(groups),
            sorted(name[:-len(".json")] for name in self.manifest["files"]),
            "the goldens file set and the request manifest golden_groups disagree")
        for group in groups:
            data = _load(GOLDEN_DIR / f"{group}.json")
            violations = list(validate(data, self.request["golden_inventory"][group]))
            self.assertEqual(
                [], violations[:10],
                f"{group} violates the request-manifest inventory — {REMEDY}")


if __name__ == "__main__":
    unittest.main()
