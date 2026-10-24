"""Post-handoff seal accounting retains and validates the final attestation."""

import importlib.util
import json
import sys
import unittest
from copy import deepcopy
from unittest.mock import patch

from tests.support import REPO_ROOT

SCENARIOS = REPO_ROOT / "verification" / "scenarios"
sys.path.insert(0, str(SCENARIOS))

DEFS_SPEC = importlib.util.spec_from_file_location(
    "scenario_defs_transition_test", SCENARIOS / "scenario_defs.py")
scenario_defs = importlib.util.module_from_spec(DEFS_SPEC)
DEFS_SPEC.loader.exec_module(scenario_defs)

FREEZE_SPEC = importlib.util.spec_from_file_location(
    "freeze_transition_test", SCENARIOS / "freeze.py")
freeze = importlib.util.module_from_spec(FREEZE_SPEC)
FREEZE_SPEC.loader.exec_module(freeze)


def scenarios():
    slugs = json.loads(
        (REPO_ROOT / "python" / "scripts" / "sample_manifest.json")
        .read_text(encoding="utf-8"))["samples"]
    return scenario_defs.all_scenarios(slugs)


class TestFreezeSealTransition(unittest.TestCase):
    def test_all_scenarios_are_accounted_without_active_ruby(self):
        active, retired, attestation = freeze.seal_accounting(scenarios())
        # 31 converted at R6, plus the python-only seals authored after the
        # retirement, none of which has cross-language history to convert
        # from. The tally, which must add up:
        #
        #   4  from R6 itself (the two environment-shaped CLI/remote cases and
        #      the two synthetic-result-construction cases)
        #   4  "first frozen post-R6 for NECB 2025", since multi-edition
        #      Stage 0 (R-A)
        #   2  purchased-heating, since D-89 step 3 (R-O-a)
        #   4  hydronic-VAV, since DF-17
        #   2  the 8.4.x.9.(5) conditional determination: sample 11 for AHJ-1
        #      (Sol's `122`.5 — the determination had focused tests and zero
        #      frozen coverage) and sample 09 for AHJ-5 (Sol's `126` — the
        #      WSHP shape had the same hole once its predicate was fixed)
        #   1  the first guard-7 witness: determination-02, sample 11 run
        #      FULL-YEAR for AHJ-1 and AHJ-3 (Sol's `127` — both fired only in
        #      tiers that cannot reach a determination, so nothing proved they
        #      survive a real year)
        #   1  guard 7 for AHJ-16: determination-03, sample 18 run FULL-YEAR
        #      under D-101 (Sol's `139` item 7 held the guard unmet while that
        #      run's reference could not hold setpoint — 932.25 unmet heating
        #      hours against the 100 h limit — and `143` required the corrected
        #      run frozen once it did)
        #   1  guard 7 for AHJ-2: determination-04, sample 16 run FULL-YEAR.
        #      AHJ-2 fired in NO frozen audit at all, because its branch reads
        #      the ANNUAL per-zone heating energy and under `--simulate none`
        #      the structural 8.4.x.9.(4) proxy answers instead
        #   2  guard 7 for AHJ-10 and AHJ-12: determination-05 and -06, the
        #      two new samples run FULL-YEAR. Adding the samples was NOT the
        #      same as witnessing the ids — their corpus-none scenarios exit 6
        #      with no `annual` and no determination, and `127` is explicit
        #      that none/sizing artifacts do not prove verdict wiring
        #      (Sol, `181`)
        #   2  the guard-7 CORPUS additions, which are samples rather than
        #      scenarios: 19-corner-block-5storey for AHJ-10 (the only block
        #      exposed on two facades, and the only sample above four storeys
        #      — grouping evidence is recorded only above four, and the shared
        #      fixture's perimeter zones each face exactly one way) and
        #      20-humidified-psz for AHJ-12 (the only sample carrying
        #      humidification at all; `btap.modeling` builds none)
        #   2  reference System 2/5, which the corpus never selected at all:
        #      the baselines carry `reference_system` 3 (310 entries) and 6
        #      (6) and never 2 or 5, which is why issue #113 survived 54
        #      frozen scenarios, the live oracle at 23/23 and the archetype
        #      gate simultaneously. `corpus-sizing-5zone-data-processing-`
        #      `system2` covers the SELECTION path; `api-sizing-system2-`
        #      `heating-dominated` covers the FAILURE, and needs the api kind
        #      because the CLI's one-space-type-for-every-space flag cannot
        #      make the loads and the classification disagree
        #   2  the whole-foundation METHOD branch, which the corpus never
        #      selected either: every sample carried simple `Ground`, so no
        #      frozen scenario reached the path where BTAP has no validated
        #      NECB reference applier. TWO silent-verdict defects shipped
        #      through that hole in one day — `method_limits` built from the
        #      ordinary floors only, and `if not floors: return` dropping the
        #      limitation for a model with no ordinary ground floor — each
        #      with a green suite and a green full dispatch behind it.
        #      It takes BOTH samples, and 21 alone would have been a false
        #      reassurance: `21-ground-f-factor` has an ORDINARY factor floor
        #      and covers the branch SELECTION and the refusal — breaking the
        #      `GroundFCfactorMethod` detection by one tuple entry fails it
        #      alone — but it stays GREEN under both defect reverts, because
        #      its factor floor is in the ordinary list and the seed's other
        #      four keep that list non-empty (Fable, `303`).
        #      `22-ground-f-factor-all-non-ordinary` is the shape that does
        #      catch them: the factor floor `unresolved` and the other four
        #      `embedded`, so the ordinary list is EMPTY and the early return
        #      is reached. A factor floor can never BE embedded — no layers,
        #      so no internal-source construction — which is why 22 is a
        #      pipeline-level shape rather than a slab anyone pours
        #   2  the two tiers on which the refusal's own fields are
        #      load-bearing and the `none` tier is blind. `corpus-annual-21-`
        #      `ground-f-factor` is the only scenario where
        #      `run.compliant = None` does anything: under `none` nothing
        #      computes a verdict either way, so the field and the refusal
        #      COINCIDE and removing it is invisible, while on a full year the
        #      8.4.1.2 comparison runs regardless and reports
        #      `compliant: true` beside `no_determination` — 2916.7 kWh
        #      proposed against a 3280.6 kWh reference. `corpus-none-21-`
        #      `ground-f-factor-hdd7200` takes the FULL-AREA early return,
        #      which records the limitation too and which HDD 3890 never
        #      reaches. Sample 21 carries both because sample 22 cannot
        #      simulate when these were authored — its radiant unit held the
        #      FIRST equipment priority, and the translator drops a
        #      surface-less unit, so the surviving baseboard pointed past the
        #      end of the list and E+ refused. That was a defect in the
        #      sample, not an inevitability: it now sizes and runs a full year
        #      cleanly, so an annual scenario on 22 is available and would
        #      cover the embedded routes too (Fable, `303` F3 and `304` F1)
        #   = 29
        #
        # This enumeration was ALREADY one behind before sample 09: it listed
        # 4+4+2+4 = 14 beside an assertion of 15, having never recorded sample
        # 11. A provenance narrative that does not add up is not provenance.
        self.assertEqual({"python-only:post-handoff": 31, "python-only": 29}, active)
        self.assertEqual({"ruby": 29, "ruby-api": 2}, retired)
        self.assertEqual({
            "commit": "85ab14352677093e24038d933cf1071e5b03431a",
            "run_id": 33544573991,
            "run_url": "https://github.com/canmet-energy/btap/actions/runs/33544573991",
        }, attestation)

    def test_every_post_handoff_slug_predates_the_attestation(self):
        """Structural, not by count. A slug added after 85ab143 was run must
        appear in `POST_R6_PYTHON_LANE_SEALS`, or `_corpus`'s default "ruby"
        seal is converted by `all_scenarios()` into `python-only:post-handoff`
        and the scenario claims a cross-language run that was never made for
        it. The counts pinned above would catch that only if someone noticed
        the number moved; this names the rule instead (Fable, PR #54)."""
        attested = set(scenario_defs.R6_CORPUS_SLUGS)
        exempt = set(scenario_defs.POST_R6_PYTHON_LANE_SEALS)
        slugs = json.loads(
            (REPO_ROOT / "python" / "scripts" / "sample_manifest.json")
            .read_text(encoding="utf-8"))["samples"]
        unclaimed = [s for s in slugs if s not in attested and s not in exempt]
        self.assertEqual(
            [], unclaimed,
            "slugs added after the final cross-language attestation must carry "
            "their own python-only seal in POST_R6_PYTHON_LANE_SEALS, or they "
            "inherit an attestation never run for them: " + ", ".join(unclaimed))

    def test_missing_transition_metadata_is_rejected(self):
        sample = deepcopy(scenarios())
        transitioned = next(item for item in sample
                            if item["seal"] == "python-only:post-handoff")
        del transitioned["last_cross_language_run_id"]
        with self.assertRaisesRegex(ValueError, "transition metadata missing"):
            freeze.seal_accounting(sample)

    def test_inconsistent_attestation_is_rejected(self):
        sample = deepcopy(scenarios())
        transitioned = [item for item in sample
                        if item["seal"] == "python-only:post-handoff"]
        transitioned[-1]["last_cross_language_run_id"] += 1
        with self.assertRaisesRegex(ValueError, "disagree on final attestation"):
            freeze.seal_accounting(sample)

    def test_active_or_retired_unknown_seals_are_rejected(self):
        sample = deepcopy(scenarios())
        sample[0]["seal"] = "ruby"
        with self.assertRaisesRegex(ValueError, "active product-Ruby seal"):
            freeze.seal_accounting(sample)

        sample = deepcopy(scenarios())
        transitioned = next(item for item in sample
                            if item["seal"] == "python-only:post-handoff")
        transitioned["retired_seal"] = "unknown"
        with self.assertRaisesRegex(ValueError, "invalid retired_seal"):
            freeze.seal_accounting(sample)

    def test_thermal_bridging_requires_the_pinned_engine(self):
        sample = [{"api_call": {"thermal_bridging": "efficient (BETBG)"}}]
        with patch.dict("sys.modules", {"tbd": None}):
            with self.assertRaisesRegex(ValueError, "FREEZER interpreter"):
                freeze.check_required_python_engines(sample)

        freeze.check_required_python_engines(sample)


if __name__ == "__main__":
    unittest.main()