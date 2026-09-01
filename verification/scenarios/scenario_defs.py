"""The AUTHORED R4 scenario definitions (D-80 R4, PR-1).

This file is the hand-maintained half of the frozen-scenario contract:
`freeze.py` executes these definitions to produce `manifest.json` (the
frozen half — definitions echoed plus baseline hashes, counts, and
provenance), and `runner.py` executes them against the frozen baselines.
`manifest.json` is generated — never hand-edit it; edit HERE and re-freeze
(an adjudicated act, see D-82 when it lands).

Path placeholders usable in argv/env values: <RUN_DIR>, <ROOT> (repo
root), <EPW> (the Python-owned Toronto EPW), <SEED> (the durable
verification-owned 5ZoneNoHVAC seed), <CORPUS> (the generated sample
corpus directory).

Lanes: python (every PR; engine-free), verify (sizing; container+engine),
parity (annual --quick; dispatch cadence).
"""

LAST_CROSS_LANGUAGE_COMMIT = "85ab14352677093e24038d933cf1071e5b03431a"
LAST_CROSS_LANGUAGE_RUN_ID = 33544573991
LAST_CROSS_LANGUAGE_RUN_URL = (
    "https://github.com/canmet-energy/btap/actions/runs/33544573991"
)
POST_HANDOFF_REASON = (
    "Ruby product retired by D-84 after the final Ruby/Leg A attestation"
)

# The corpus tiers mirror verification/run_corpus.rb's recipe exactly —
# same base args, same subsets — so the frozen baselines describe the
# same runs Leg B compared.
BASE_ARGS = ["--hdd", "3890", "--storeys", "1", "--no-report", "--quiet"]
FIXTURE_ARGS = BASE_ARGS + ["--space-type", "Space Function/Office enclosed > 25 m2"]
SIZING_SUBSET = ["01-baseboard-gas", "02-psz-gas-dx", "09-water-source-hp"]
ANNUAL_SUBSET = ["01-baseboard-gas", "02-psz-gas-dx"]

CORPUS_FILES = ["audit.json", "report.json"]
CORPUS_TEXT = {"audit.txt": "normalized"}


def _corpus(slug, tier, lane, extra=()):
    sim = (["--simulate", "annual", "--quick"] if tier == "annual"
           else ["--simulate", tier])
    epw = [] if tier == "none" else ["--epw", "<EPW>"]
    model = "<SEED>" if slug == "5zone-onramp" else f"<CORPUS>/{slug}.osm"
    args = FIXTURE_ARGS if slug == "5zone-onramp" else BASE_ARGS
    return {
        "id": f"corpus-{tier}-{slug}",
        "lane": lane, "kind": "cli",
        "replaces": ["B1", "B2"] if tier != "annual" else ["B3", "B4", "B7"],
        "argv": [model, *sim, *epw, *args, "-o", "<RUN_DIR>", *extra],
        "env": {},
        "expect_exit": 6,
        "files": CORPUS_FILES, "text_files": CORPUS_TEXT,
        "streams": {"stdout": "exact", "stderr": "exact"},
        "seal": "ruby",
    }


def corpus_scenarios(slugs):
    out = [_corpus(s, "none", "python") for s in [*slugs, "5zone-onramp"]]
    out += [_corpus(s, "sizing", "verify") for s in SIZING_SUBSET]
    out += [_corpus(s, "annual", "parity") for s in ANNUAL_SUBSET]
    return out


FAILURE_SCENARIOS = [
    # exit 2 — six representative trigger SITES (the 13 known triggers
    # funnel through one emitter; the rest stay covered by test_cli.py).
    {"id": "usage-unknown-flag", "lane": "python", "kind": "cli",
     "replaces": [], "argv": ["--nope"], "env": {}, "expect_exit": 2,
     "files": [], "text_files": {}, "no_run_dir": True,
     "streams": {"stdout": "exact", "stderr": "exact"}, "seal": "ruby"},
    {"id": "usage-no-model", "lane": "python", "kind": "cli",
     "replaces": [], "argv": ["--simulate", "none"], "env": {},
     "expect_exit": 2, "files": [], "text_files": {}, "no_run_dir": True,
     "streams": {"stdout": "exact", "stderr": "exact"}, "seal": "ruby"},
    {"id": "usage-missing-model-file", "lane": "python", "kind": "cli",
     "replaces": [], "argv": ["<ROOT>/nonexistent-model.osm", "--simulate", "none"],
     "env": {}, "expect_exit": 2, "files": [], "text_files": {},
     "no_run_dir": True,
     "streams": {"stdout": "exact", "stderr": "exact"}, "seal": "ruby"},
    {"id": "usage-missing-epw", "lane": "python", "kind": "cli",
     "replaces": [], "argv": ["<SEED>", "--simulate", "sizing", *FIXTURE_ARGS],
     "env": {}, "expect_exit": 2, "files": [], "text_files": {},
     "no_run_dir": True,
     "streams": {"stdout": "exact", "stderr": "exact"}, "seal": "ruby"},
    {"id": "usage-missing-ddy", "lane": "python", "kind": "cli",
     "replaces": [], "argv": ["<SEED>", "--simulate", "sizing",
                              "--epw", "<LONE_EPW>", *FIXTURE_ARGS],
     "env": {}, "expect_exit": 2, "files": [], "text_files": {},
     "no_run_dir": True,
     "streams": {"stdout": "exact", "stderr": "exact"}, "seal": "ruby"},
    {"id": "usage-unknown-city", "lane": "python", "kind": "cli",
     "replaces": [], "argv": ["<SEED>", "--simulate", "none",
                              "--city", "atlantis", *FIXTURE_ARGS],
     "env": {}, "expect_exit": 2, "files": [], "text_files": {},
     "no_run_dir": True,
     "streams": {"stdout": "exact", "stderr": "exact"}, "seal": "ruby"},

    # exit 3 — preflight rejection with the failure-flush artifacts.
    {"id": "preflight-untagged-model", "lane": "python", "kind": "cli",
     "replaces": [], "argv": ["<SEED>", "--simulate", "none",
                              "--hdd", "3890", "--storeys", "1",
                              "--no-report", "--quiet", "-o", "<RUN_DIR>"],
     "env": {}, "expect_exit": 3,
     "files": [], "text_files": {"audit.txt": "normalized"},
     "expected_run_files": ["audit.json", "audit.txt", "report.json"],
     "byte_asserts": [{"file": "report.json", "equals": "{}"}],
     "fragments": {"stderr": {"required": ["REJECTED before any simulation",
                                           "A partial audit trail was written to"],
                              "forbidden": []},
                   "audit.txt": {"required": ["ABORTED"], "forbidden": []}},
     "streams": {"stdout": "exact", "stderr": "exact"}, "seal": "ruby"},

    # exit 4 — simulation failure, deliberately engine-free.
    {"id": "simulation-bad-engine", "lane": "python", "kind": "cli",
     "replaces": [], "argv": ["<SEED>", "--simulate", "sizing",
                              "--epw", "<EPW>", *FIXTURE_ARGS,
                              "-o", "<RUN_DIR>"],
     "env": {"BTAP_ENERGYPLUS": "/nonexistent-energyplus"},
     "expect_exit": 4,
     "files": [], "text_files": {},
     "expected_run_files": ["audit.json", "audit.txt", "report.json"],
     "fragments": {"stderr": {"required": ["EnergyPlus"], "forbidden": []}},
     "streams": {"stdout": "exact", "stderr": "exact"},
     "seal": "python-only:the Ruby CLI runs EnergyPlus through the "
             "openstudio CLI and does not honour BTAP_ENERGYPLUS, so no "
             "mirrored argv reproduces this trigger"},

    # exit 5 — internal error via the dead remote backend. FRAGMENTS
    # (errno text varies); ~15s retry ladder accepted, 30s wall clock.
    {"id": "internal-dead-remote", "lane": "python", "kind": "cli",
     "replaces": [], "argv": ["<SEED>", "--simulate", "sizing",
                              "--epw", "<EPW>", "--backend", "remote",
                              *FIXTURE_ARGS, "-o", "<RUN_DIR>"],
     "env": {"HBIX_SIM_ENDPOINT": "http://127.0.0.1:1",
             "HBIX_API_KEY": "scenario-dummy"},
     "expect_exit": 5, "timeout_s": 30,
     "files": [], "text_files": {},
     "fragments": {"stderr": {"required": ["ERROR:"],
                              "forbidden": ["EnergyPlus"]}},
     "streams": {"stdout": "fragments", "stderr": "fragments"},
     "seal": "python-only:the Ruby remote backend's failure text and "
             "retry behaviour are environment-shaped; the exit-CODE "
             "classification parity is pinned by both exit maps being "
             "byte-comparable"},
]

API_SCENARIOS = [
    # Replaces B9 — the only thermal-bridging pipeline coverage; neither
    # CLI exposes thermal_bridging. Ruby API seal via ruby_tbd_compliance.rb.
    {"id": "api-thermal-bridging", "lane": "python", "kind": "api",
     "replaces": ["B9"],
     "api_call": {"vintage": "2020", "simulate": "none", "hdd": 3890,
                  "building": {"storeys": 1},
                  "thermal_bridging": "efficient (BETBG)"},
     "env": {}, "expect_exit": None,
     "files": ["audit.json", "report.json"],
     "text_files": {"audit.txt": "normalized"},
     "streams": {}, "seal": "ruby-api:ruby_tbd_compliance.rb"},

    # Replaces B5/B6 — the scripted audit scenario, audit.txt BYTE-exact.
    {"id": "audit-unit", "lane": "python", "kind": "audit-unit",
     "replaces": ["B5", "B6"], "env": {}, "expect_exit": None,
     "files": ["audit.json"], "text_files": {"audit.txt": "exact"},
     "streams": {}, "seal": "ruby-api:audit ruby_reference.rb"},
]

VERDICT_SCENARIOS = [
    # Exits 0 and 1 — the CLI's two determination statuses, frozen at the
    # verdict/emit unit level (live Leg B never covered them end-to-end
    # either; the full-year e2e is declared uncovered).
    {"id": "verdict-compliant", "lane": "python", "kind": "verdict-unit",
     "replaces": [], "compliant": True, "env": {}, "expect_exit": 0,
     "files": [], "text_files": {},
     "streams": {"stdout": "exact"},
     "seal": "python-only:synthetic result construction is "
             "implementation-internal; rendering equivalence was held by "
             "Leg B at the freeze commit"},
    {"id": "verdict-not-compliant", "lane": "python", "kind": "verdict-unit",
     "replaces": [], "compliant": False, "env": {}, "expect_exit": 1,
     "files": [], "text_files": {},
     "streams": {"stdout": "exact"},
     "seal": "python-only:synthetic result construction is "
             "implementation-internal; rendering equivalence was held by "
             "Leg B at the freeze commit"},
]

UNCOVERED = [
    {"branch": "8.4.1.2.(5) capacity-iteration FAILURE path",
     "why": "nothing of it is frozen: the failure sub-branches (failed "
            "bump, stall detection, post-bump nonconvergence, cap "
            "exhaustion) AND the zero-iteration warning all require a "
            "real annual run engineered to fail unmet hours; no CLI flag "
            "exposes max_capacity_iterations",
     "witness": "the converged/empty path only — the annual scenarios "
                "freeze capacity_iterations: []; the failure branches "
                "remain covered ONLY by existing unit tests",
     "option": "a future API-level scenario (parity lane) is a named "
               "OPTION, not a witness; nothing is frozen unless it "
               "appears in this manifest"},
    {"branch": "full-year end-to-end determination (exits 0/1 through a "
               "real annual run)",
     "why": "a 40-90 minute scenario; live Leg B's annual tier only ever "
            "ran --quick (exit 6), so this matches Leg B's own scope",
     "witness": "the verdict-unit scenarios freeze both determination "
                "renderings and exit codes at unit level",
     "option": "a dispatch-only full-year scenario remains possible if a "
               "later phase demands it"},
]


def all_scenarios(slugs):
    scenarios = corpus_scenarios(slugs) + API_SCENARIOS + FAILURE_SCENARIOS + VERDICT_SCENARIOS
    for scenario in scenarios:
        seal = scenario["seal"]
        if seal == "ruby" or seal.startswith("ruby-api:"):
            scenario.update({
                "seal": "python-only:post-handoff",
                "retired_seal": seal,
                "last_cross_language_commit": LAST_CROSS_LANGUAGE_COMMIT,
                "last_cross_language_run_id": LAST_CROSS_LANGUAGE_RUN_ID,
                "last_cross_language_run_url": LAST_CROSS_LANGUAGE_RUN_URL,
                "seal_transition_reason": POST_HANDOFF_REASON,
            })
    return scenarios
