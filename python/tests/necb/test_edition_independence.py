"""Stage 3 removability gate (docs/NECB_MULTI_EDITION_PLAN.md, Stage 3
"Verify. Removability gate"; removal mechanics are Stage 4's "The removal
operation"): for every registered NECB code id, prove nothing at runtime
depends on another edition's files.

Written against the Stage 3 spec, AHEAD of the sibling agent's
implementation: ``btap.codes.necb._data_root``/``_set_data_root`` don't
exist on this tree yet, so every test here is EXPECTED TO FAIL until that
lands. Each check copies ONE edition's snapshot into a temp tree and runs a
FRESH SUBPROCESS against it (several loaders here cache at import scope --
Table C-1, the 4.2.1.6. matrix, the manifest registry -- so a subprocess
defeats memoisation and the temp tree makes it xdist-safe).

SDK gating: the plan says only ``performance_compliance`` needs the SDK, but
here EVERY domain package (loads/lighting/envelope/hvac/shw) imports
``openstudio`` at module scope via its own submodules, so just IMPORTING one
already needs it. ``test_full_edition_independence`` therefore gates the
whole 7-step script on the SDK (the literal removability gate);
``test_registry_and_coverage_independence`` re-runs the SDK-free subset
(steps 1, 2, 5) so those assertions run on an SDK-less runner too.

Stage 4 extends the SDK-free subprocess script with one more call:
``tests.necb.test_edition_provenance.check_provenance`` on the one-edition
temp tree, so the checked-provenance contract (manifest ``provenance``
blocks) is proven to hold with only one edition present too -- the same
removability property this whole module exists to check. That test file is
EXPECTED TO FAIL alongside ``test_edition_provenance.py`` until the sibling
provenance data lands.

Stage 5 extends the same SDK-free script once more: with only one edition
present, ``Ruleset.behaviour`` must still answer ``None`` for a behaviour the
ABSENT edition owns rather than raising -- otherwise a one-edition install
could not run. (The behaviour vocabulary is therefore code-side, not derived
from the manifests on disk; ``tests/necb/test_behaviour_binding.py`` is what
keeps it tied to them.)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import btap.codes as codes
from tests.necb.support import needs_sdk

REPO_PYTHON = Path(__file__).resolve().parents[2]
NECB_DATA = REPO_PYTHON / "btap" / "codes" / "necb" / "data"
CODE_IDS = codes.code_ids()  # the REAL tree's registry


def _env():
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(REPO_PYTHON) + (os.pathsep + existing if existing else "")
    return env


def _run(script, timeout):
    proc = subprocess.run([sys.executable, "-c", script], cwd=str(REPO_PYTHON),
                          env=_env(), capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


def _isolated_tree(tmp, *ids):
    """Populate ``tmp`` with ONLY the named editions' snapshot directories."""
    for code_id in ids:
        shutil.copytree(NECB_DATA / code_id, tmp / code_id)


def _summary(out):
    return json.loads(out.strip().splitlines()[-1])


# All 7 plan steps, one edition present, SDK required.
_FULL_SCRIPT = """
import json
from pathlib import Path
import btap.codes.necb as necb_pkg
necb_pkg._set_data_root(Path({tmp!r}), _testing=True)
import btap.codes as codes
result = {{"code_ids": codes.code_ids(), "editions": codes.editions("necb")}}
from btap.audit import AuditLog
from btap.codes.necb import loads, lighting, envelope, hvac, shw
from btap.codes import compliance, coverage, pipeline
edition = {edition!r}
result["loads_rules"] = bool(loads.rules(edition))
result["lighting_rules"] = bool(lighting.rules(edition))
result["envelope_rules"] = bool(envelope.rules(edition))
result["hvac_rules"] = bool(hvac.rules(edition))
result["shw_rules"] = bool(shw.rules(edition))
audit = AuditLog()
before = len(audit.entries)
pipeline._emit_article_coverage(codes.resolve(f"necb{{edition}}"), audit)
result["umbrella_rules_emitted"] = len(audit.entries) > before
# Both loaders are edition-aware (Stage 3): each reads its own snapshot.
result["climate_table_c1"] = bool(envelope.climate.table_c1(edition))
result["daylight_table"] = bool(lighting.DaylightControlRequirement.table(edition))
article = coverage.get_article(edition, "8.4.1.1")
result["coverage_article_has_text"] = bool(article.get("raw"))
result["coverage_editions"] = list(coverage.editions())
from tests.necb.support import compliance_fixture, zone_types_for
model = compliance_fixture()
run_dir = Path({tmp!r}) / "run"
run_dir.mkdir(exist_ok=True)
building = {{"storeys": 1, "zone_types": zone_types_for(model), "winter_design_temp_c": -20}}
cr = compliance.performance_compliance(model, code=f"necb{{edition}}", simulate="none", hdd=3890,
                                       building=building, run_dir=str(run_dir))
result["compliance_result_type"] = type(cr).__name__
result["compliance_report_present"] = bool(cr.report)
print(json.dumps(result))
"""

# Steps 1, 2, 5 only -- no domain package import, SDK-free.
_DATA_ONLY_SCRIPT = """
import json
from pathlib import Path
import btap.codes.necb as necb_pkg
necb_pkg._set_data_root(Path({tmp!r}), _testing=True)
import btap.codes as codes
result = {{"code_ids": codes.code_ids(), "editions": codes.editions("necb")}}
from btap.codes import coverage
article = coverage.get_article({edition!r}, "8.4.1.1")
result["coverage_article_has_text"] = bool(article.get("raw"))
result["coverage_editions"] = list(coverage.editions())
from tests.necb.test_edition_provenance import check_provenance
result["provenance_problems"] = check_provenance(Path({tmp!r}))
# Stage 5: the edition-bound behaviours answer correctly with only THIS
# edition present -- the absent edition's binding must be an honest None,
# not a crash, or a one-edition install could not run at all.
ruleset = codes.resolve({code_id!r})
result["behaviours"] = {{
    name: (None if ruleset.behaviour(name) is None else ruleset.behaviour(name).__name__)
    for name in sorted(codes.BEHAVIOURS)
}}
print(json.dumps(result))
"""

_NEGATIVE_SCRIPT = """
import json
from pathlib import Path
import btap.codes.necb as necb_pkg
necb_pkg._set_data_root(Path({tmp!r}), _testing=True)
import btap.codes as codes
try:
    codes.resolve("necb2020")
    print(json.dumps({{"raised": False}}))
except Exception as exc:
    print(json.dumps({{"raised": True, "message": str(exc)}}))
"""

_GUARD_SCRIPT = """
import json
from pathlib import Path
import btap.codes.necb as necb_pkg
outcome = {{}}
try:
    necb_pkg._set_data_root(Path("/tmp/not-allowed-without-testing-flag"))
    outcome["unguarded_raised"] = False
except RuntimeError:
    outcome["unguarded_raised"] = True
except Exception as exc:
    outcome["unguarded_raised"] = "wrong-type:" + type(exc).__name__
default_before = necb_pkg._data_root()
necb_pkg._set_data_root(Path({tmp!r}), _testing=True)
outcome["overridden"] = str(necb_pkg._data_root()) == {tmp!r}
necb_pkg._set_data_root(None, _testing=True)
outcome["restored"] = necb_pkg._data_root() == default_before
print(json.dumps(outcome))
"""


class TestEditionIndependence(unittest.TestCase):
    @needs_sdk
    def test_full_edition_independence(self):
        """The literal removability gate: all 7 steps, one edition present."""
        for code_id in CODE_IDS:
            with self.subTest(code_id=code_id):
                ruleset = codes.resolve(code_id)
                with tempfile.TemporaryDirectory(prefix="edition-full-") as tmp:
                    tmp_path = Path(tmp)
                    _isolated_tree(tmp_path, code_id)
                    script = _FULL_SCRIPT.format(tmp=str(tmp_path), edition=ruleset.edition)
                    rc, out, err = _run(script, timeout=300)
                    self.assertEqual(0, rc, f"{code_id}: subprocess failed:\n{err}")
                    summary = _summary(out)
                    self.assertEqual([code_id], summary["code_ids"])
                    self.assertEqual([ruleset.edition], summary["editions"])
                    for key in ("loads_rules", "lighting_rules", "envelope_rules",
                               "hvac_rules", "shw_rules", "umbrella_rules_emitted",
                               "climate_table_c1", "daylight_table",
                               "coverage_article_has_text", "compliance_report_present"):
                        self.assertTrue(summary[key], f"{code_id}: {key} falsy: {summary}")
                    self.assertEqual([ruleset.edition], summary["coverage_editions"])
                    self.assertEqual("ComplianceResult", summary["compliance_result_type"])

    def test_registry_and_coverage_independence(self):
        """SDK-free subset (steps 1, 2, 5) -- runs on every runner."""
        for code_id in CODE_IDS:
            with self.subTest(code_id=code_id):
                ruleset = codes.resolve(code_id)
                with tempfile.TemporaryDirectory(prefix="edition-data-") as tmp:
                    tmp_path = Path(tmp)
                    _isolated_tree(tmp_path, code_id)
                    script = _DATA_ONLY_SCRIPT.format(tmp=str(tmp_path),
                                                      edition=ruleset.edition,
                                                      code_id=code_id)
                    rc, out, err = _run(script, timeout=60)
                    self.assertEqual(0, rc, f"{code_id}: subprocess failed:\n{err}")
                    summary = _summary(out)
                    self.assertEqual([code_id], summary["code_ids"])
                    self.assertEqual([ruleset.edition], summary["editions"])
                    self.assertTrue(summary["coverage_article_has_text"])
                    self.assertEqual([ruleset.edition], summary["coverage_editions"])
                    # Stage 4: the provenance contract holds with only this one
                    # edition present -- no cross-edition dependency in validation.
                    self.assertEqual([], summary["provenance_problems"],
                                     f"{code_id}: {summary['provenance_problems']}")
                    # Stage 5 behaviour binding, per edition: a 2020-only tree
                    # answers None for both (2020 owns no edition-specific
                    # code); a 2025-only tree resolves both modules.
                    expected = {
                        "necb2020": {"archetype_eui_path": None,
                                     "part11_ghg": None},
                        "necb2025": {
                            "archetype_eui_path":
                                "btap.codes.necb.editions.necb2025.eui_archetypes",
                            "part11_ghg":
                                "btap.codes.necb.editions.necb2025.part11_ghg"},
                    }[code_id]
                    self.assertEqual(expected, summary["behaviours"],
                                     f"{code_id}: {summary['behaviours']}")

    def test_missing_edition_raises_naming_edition_and_path(self):
        """Only necb2025 present: resolving necb2020 must name both."""
        with tempfile.TemporaryDirectory(prefix="edition-neg-") as tmp:
            tmp_path = Path(tmp)
            _isolated_tree(tmp_path, "necb2025")
            rc, out, err = _run(_NEGATIVE_SCRIPT.format(tmp=str(tmp_path)), timeout=60)
            self.assertEqual(0, rc, f"subprocess failed:\n{err}")
            summary = _summary(out)
            self.assertTrue(summary["raised"], "resolving an absent edition must raise")
            message = summary["message"]
            self.assertIn("2020", message, "message must name the missing edition")
            self.assertTrue(
                any(needle in message for needle in ("necb2020", ".json", "/", "path")),
                f"message must name a path: {message!r}")

    def test_set_data_root_guard(self):
        """No ``_testing=True`` -> RuntimeError; ``_set_data_root(None,
        _testing=True)`` restores the default root."""
        with tempfile.TemporaryDirectory(prefix="edition-guard-") as tmp:
            tmp_path = Path(tmp)
            _isolated_tree(tmp_path, "necb2020")
            rc, out, err = _run(_GUARD_SCRIPT.format(tmp=str(tmp_path)), timeout=30)
            self.assertEqual(0, rc, f"subprocess failed:\n{err}")
            summary = _summary(out)
            self.assertTrue(summary["unguarded_raised"], summary)
            self.assertTrue(summary["overridden"], summary)
            self.assertTrue(summary["restored"], summary)


if __name__ == "__main__":
    unittest.main()
