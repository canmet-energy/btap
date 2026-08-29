"""Fixture drift gate (D-80 R2.1).

The Python verification stack owns its test data: ``tests/fixtures/`` holds
COPIES of the shared fixtures that used to be read straight out of
``btap-modeling/test/fixtures``. Owning a copy is what makes the Python side
self-contained; this test is what stops the copy from silently diverging while
both trees are alive.

Policy, stated once and repeated in every assertion message:

    Ruby tree is authoritative until R6 (D-80): a legitimate change updates
    both copies; at R6 this cross-tree assertion is removed and the Python
    hashes become authoritative.

So a failure here is never "the checksum is wrong" — it is "somebody changed
one copy of a fixture". Fix it by making both copies identical (Ruby first,
per the family's Ruby-is-the-baseline rule), not by re-hashing.

The gem-tree original going MISSING is also a failure, deliberately: it means
the gems retired without this test being deleted, and a vacuously-passing
drift gate is exactly the green-but-vacuous gate the family forbids.
"""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from tests.support import FIXTURES, REPO_ROOT

#: The Ruby originals' home. Named here and NOWHERE else on the Python side —
#: tests/support.py is deliberately free of gem-tree paths now, and this
#: module is the one allowlisted cross-tree reference (see
#: tests/test_self_containment.py, entry retires at R6).
GEM_FIXTURES = REPO_ROOT / "btap-modeling" / "test" / "fixtures"

POLICY = (
    "Ruby tree is authoritative until R6 (D-80): a legitimate change updates "
    "both copies; at R6 this cross-tree assertion is removed and the Python "
    "hashes become authoritative.")

#: Every fixture the Python tree owns a copy of, as a path RELATIVE to both
#: fixture roots. The first five are the R2.1 set; footprint_ottawa_tower.json
#: came with them because ``tests.support.FIXTURES`` is a single directory
#: constant — repointing it moved every consumer at once.
COPIES = (
    "weather/CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw",
    "weather/CAN_ON_Toronto.Intl.AP.716240_CWEC2020.ddy",
    "weather/CAN_ON_Toronto.Intl.AP.716240_CWEC2020.stat",
    "system_simulation_status.json",
    "reference_selection_matrix.json",
    "footprint_ottawa_tower.json",
)

#: Copies whose Ruby original lives OUTSIDE btap-modeling's fixture root,
#: mapped {relative-under-tests/fixtures: absolute Ruby original}.
#: paired_bars.svg joined in D-80 R2 when test_report_units.py stopped
#: reading btap-necb's golden directly.
OTHER_ORIGINALS = {
    "paired_bars.svg": REPO_ROOT / "btap-necb" / "test" / "goldens"
    / "paired_bars.svg",
}

#: The DURABLE verification-owned oracle inputs (D-80: live Leg C must
#: outlive the gem trees, so the exporter reads verification/oracle/fixtures
#: — these copies become authoritative at R6). {absolute copy: absolute
#: gem-tree original}, drift-gated like everything else until then.
_ORACLE_FIXTURES = REPO_ROOT / "verification" / "oracle" / "fixtures"
_GEM_HVAC_DATA = (REPO_ROOT / "btap-modeling" / "lib" / "btap_modeling"
                  / "hvac" / "data")
VERIFICATION_COPIES = {
    _ORACLE_FIXTURES / "5ZoneNoHVAC.osm": _GEM_HVAC_DATA / "5ZoneNoHVAC.osm",
    _ORACLE_FIXTURES / "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw":
        GEM_FIXTURES / "weather" / "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw",
    _ORACLE_FIXTURES / "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.ddy":
        GEM_FIXTURES / "weather" / "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.ddy",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class TestFixtureDrift(unittest.TestCase):
    """One subtest per copy — a single drifted fixture must not mask the rest."""

    def _check(self, relative: str):
        mine = FIXTURES / relative
        theirs = OTHER_ORIGINALS.get(relative, GEM_FIXTURES / relative)

        self.assertTrue(
            mine.is_file(),
            f"the Python-owned fixture copy is missing: {mine}\n{POLICY}")

        # A missing ORIGINAL is not "nothing to compare" — it is a retirement
        # that forgot this file.
        self.assertTrue(
            theirs.is_file(),
            f"the Ruby original is gone: {theirs}\n"
            "If the gems have retired (D-80 R6), this whole test file should "
            "have been REMOVED with them and the Python copies made "
            "authoritative — a drift gate with nothing to compare against is "
            "a green-but-vacuous gate. If the gems have NOT retired, the "
            "original was deleted or moved by mistake.")

        self.assertEqual(
            sha256(theirs), sha256(mine),
            f"fixture drift: {relative}\n"
            f"  ruby   : {theirs}\n"
            f"  python : {mine}\n"
            f"{POLICY}")

    def test_weather_epw(self):
        self._check(COPIES[0])

    def test_weather_ddy(self):
        self._check(COPIES[1])

    def test_weather_stat(self):
        self._check(COPIES[2])

    def test_system_simulation_status_json(self):
        self._check(COPIES[3])

    def test_reference_selection_matrix_json(self):
        self._check(COPIES[4])

    def test_footprint_ottawa_tower_json(self):
        self._check(COPIES[5])

    def test_paired_bars_svg(self):
        self._check("paired_bars.svg")

    def _check_absolute(self, mine: Path, theirs: Path):
        self.assertTrue(mine.is_file(),
                        f"the verification-owned copy is missing: {mine}\n{POLICY}")
        self.assertTrue(
            theirs.is_file(),
            f"the Ruby original is gone: {theirs}\n"
            "If the gems have retired (D-80 R6), remove this assertion and "
            "promote the verification copies to authoritative.")
        self.assertEqual(sha256(theirs), sha256(mine),
                         f"fixture drift: {mine.name}\n  ruby   : {theirs}\n"
                         f"  verification: {mine}\n{POLICY}")

    def test_oracle_fixture_seed(self):
        mine = next(k for k in VERIFICATION_COPIES if k.suffix == ".osm")
        self._check_absolute(mine, VERIFICATION_COPIES[mine])
        # The PACKAGE copy must match too — three copies, one content.
        from importlib import resources
        pkg = resources.files("btap.modeling.hvac") / "data" / "5ZoneNoHVAC.osm"
        self.assertEqual(sha256(mine), sha256(Path(str(pkg))),
                         "the packaged seed diverged from the verification copy")

    def test_oracle_fixture_epw(self):
        mine = next(k for k in VERIFICATION_COPIES if k.suffix == ".epw")
        self._check_absolute(mine, VERIFICATION_COPIES[mine])

    def test_oracle_fixture_ddy(self):
        mine = next(k for k in VERIFICATION_COPIES if k.suffix == ".ddy")
        self._check_absolute(mine, VERIFICATION_COPIES[mine])


if __name__ == "__main__":
    unittest.main()
