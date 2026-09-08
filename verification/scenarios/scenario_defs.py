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

import re

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


#: The default code id. Every scenario frozen before the multi-edition work
#: is a ``necb2020`` scenario, and for that id ``_corpus`` must stay
#: byte-identical to its pre-Stage-0 self — same id, same argv, same seal.
DEFAULT_CODE = "necb2020"

#: A first-edition seal. NO cross-language attestation exists for an edition
#: whose scenarios were authored after the Ruby product retired (D-84), so
#: ``all_scenarios()`` must leave these untouched — no ``retired_seal``, no
#: 85ab143. The seal-attestation gate in test_frozen_scenarios.py asserts it.
FIRST_FREEZE_SEAL = (
    "python-only:first frozen post-R6 for NECB {edition} — no "
    "cross-language attestation exists for this edition"
)

#: The annual tier's non-vacuity contract, in the serialisable assertion
#: schema ``runner.check_assertions`` interprets. This is the same guarantee
#: freeze.py used to hard-code for ids starting ``corpus-annual``; carrying
#: it on the scenario means the NORMAL comparator enforces it on every run,
#: not only at freeze time.
ANNUAL_ASSERTS = [
    {"op": "json_gt", "file": "report.json",
     "path": "proposed.total_site_kwh", "value": 0},
    {"op": "json_exists", "file": "report.json",
     "path": "proposed.unmet_occupied_hours"},
]


def edition_of(code):
    """The 4-digit edition a code id ends with (``necb2025`` -> ``2025``)."""
    match = re.search(r"(\d{4})$", code)
    if not match:
        raise ValueError(
            f"code id {code!r} does not end in a 4-digit edition")
    return match.group(1)


def _corpus(slug, tier, lane, *, code=DEFAULT_CODE, extra=()):
    sim = (["--simulate", "annual", "--quick"] if tier == "annual"
           else ["--simulate", tier])
    epw = [] if tier == "none" else ["--epw", "<EPW>"]
    model = "<SEED>" if slug == "5zone-onramp" else f"<CORPUS>/{slug}.osm"
    args = FIXTURE_ARGS if slug == "5zone-onramp" else BASE_ARGS
    # The CLI selects an edition by CODE ID (Stage 7); the default is
    # implicit, so only a non-default edition appears in argv.
    selector = [] if code == DEFAULT_CODE else ["--code", code]
    scenario = {
        "id": (f"corpus-{tier}-{slug}" if code == DEFAULT_CODE
               else f"corpus-{tier}-{slug}-{code}"),
        "lane": lane, "kind": "cli",
        "replaces": ["B1", "B2"] if tier != "annual" else ["B3", "B4", "B7"],
        "argv": [model, *sim, *epw, *args, *selector, "-o", "<RUN_DIR>", *extra],
        "env": {},
        "expect_exit": 6,
        "files": CORPUS_FILES, "text_files": CORPUS_TEXT,
        "streams": {"stdout": "exact", "stderr": "exact"},
        "seal": ("ruby" if code == DEFAULT_CODE
                 else FIRST_FREEZE_SEAL.format(edition=edition_of(code))),
    }
    if tier == "annual":
        scenario["asserts"] = [dict(a) for a in ANNUAL_ASSERTS]
    return scenario


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
     "api_call": {"code": "necb2020", "simulate": "none", "hdd": 3890,
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
]

#: Branches this suite USED to declare uncovered and now covers. The record
#: stays here — beside UNCOVERED, in the same authored file — so a reader
#: sees what closed a gap and, precisely, what the closure does and does not
#: claim.
NEWLY_COVERED = [
    {"branch": "full-year determination (exits 0/1 through a real annual "
               "run)",
     "covered_by": "API pipeline execution of a full-year determination, "
                   "classified by the SHARED cli.verdict_exit — NOT a "
                   "literal CLI end-to-end run. The scenario calls "
                   "performance_compliance in an isolated worker "
                   "subprocess and maps the ComplianceResult to an exit "
                   "code through the very function the CLI uses, so the "
                   "classification is the product's, not the harness's; "
                   "the CLI's own argument parsing and process wiring are "
                   "outside what this freezes",
     "scenario": "determination-01-baseboard-gas-necb2025",
     "cost": "about 3 minutes on the corpus model (189 s, three reference "
             "capacity iterations, when authored on 2026-09-08) — the 40-90 "
             "minute figure that kept it uncovered was the oracle archetypes' "
             "cost, not the corpus's; it stays parity-lane by policy (a real "
             "EnergyPlus annual run), not by cost",
     "still_unit_level": "CLI RENDERING of both determinations stays "
                         "covered by the verdict-unit scenarios "
                         "(verdict-compliant / verdict-not-compliant); "
                         "the API scenario does not exercise cli.emit"},
]


# ------------------------------------------------------------ NECB 2025
#: The first frozen evidence for a second edition (multi-edition plan,
#: Stage 0 / R-A). Four scenarios: two no-simulation corpus runs in the
#: python lane, and two real annual API runs in the parity lane — the
#: first full-year determination this suite has ever frozen, and the only
#: frozen witness of the 2025 archetype-EUI path. Every value pinned below
#: (expect_exit, compliant, ghg.level, tier) was read off an authoring run
#: of the unmodified product on 2026-09-08 and is asserted, not assumed:
#: a baseline that fails its own asserts does not freeze.
NECB2025_EDITION = "necb2025"

_WEATHER_2025 = {"epw": "<EPW>", "ddy": "<DDY>"}

EDITION_SCENARIOS = [
    # Reference build audited at 2025: the envelope prescriptive decision
    # cites 8.4.5.1.(2) (8.4.4.1.(2) at 2020), and every emitter that
    # records the edition records 2025.
    {**_corpus("01-baseboard-gas", "none", "python", code=NECB2025_EDITION),
     "replaces": [],
     "asserts": [
         {"op": "json_equals", "file": "report.json", "path": "edition",
          "value": "2025"},
         {"op": "audit_entry", "article": "8.4.5.1.(2)", "count": 1},
         {"op": "audit_entry", "inputs": {"code": "necb2025"}, "count": 4},
     ]},
    # D-85 at 2025: the proposed VRF outdoor unit that serves no reference
    # zone is purged, audited once, at info.
    {**_corpus("08-vrf", "none", "python", code=NECB2025_EDITION),
     "replaces": [],
     "asserts": [
         {"op": "json_equals", "file": "report.json", "path": "edition",
          "value": "2025"},
         {"op": "audit_entry", "step": "build", "level": "info",
          "action": "proposed VRF outdoor unit serves no reference zone — "
                    "removed",
          "ruling": "D-85", "inputs": {"terminals": 0}, "count": 1},
     ]},
    # The full-year determination, as an API scenario: the CLI has no
    # province argument, and the Part 11 GHG binding (Stage 5) is only
    # frozen if the run scores GHG against a reference. Authoring run:
    # exit 1 / not compliant because the REFERENCE building's unmet
    # heating hours (801 h) exceed the 8.4.1.2.(3) 100 h limit after three
    # capacity increases (8.4.1.2.(5)); the energy verdict itself passes
    # (76.0 % of target, tier 1); GHG level "F" at 95.3 % of the GHG
    # target. The asserts tie the pinned exit to that reason.
    {"id": f"determination-01-baseboard-gas-{NECB2025_EDITION}",
     "lane": "parity", "kind": "api", "replaces": [],
     "api_call": {"code": NECB2025_EDITION, "simulate": "annual",
                  "province_state": "ONTARIO",
                  "model": "<CORPUS>/01-baseboard-gas.osm",
                  "weather": _WEATHER_2025, "building": {"storeys": 1}},
     "env": {}, "expect_exit": 1, "timeout_s": 5400,
     "files": CORPUS_FILES, "text_files": CORPUS_TEXT, "streams": {},
     "seal": FIRST_FREEZE_SEAL.format(edition="2025"),
     "asserts": [
         {"op": "json_gt", "file": "report.json",
          "path": "proposed.total_site_kwh", "value": 0},
         {"op": "json_gt", "file": "report.json",
          "path": "reference.total_site_kwh", "value": 0},
         {"op": "json_exists", "file": "report.json",
          "path": "proposed.unmet_occupied_hours"},
         {"op": "json_exists", "file": "report.json",
          "path": "reference.unmet_occupied_hours"},
         {"op": "json_equals", "file": "report.json", "path": "annual",
          "value": True},
         {"op": "json_equals", "file": "report.json", "path": "edition",
          "value": "2025"},
         {"op": "json_equals", "file": "report.json", "path": "tier",
          "value": 1},
         {"op": "json_exists", "file": "report.json", "path": "ghg"},
         {"op": "json_equals", "file": "report.json", "path": "ghg.level",
          "value": "F"},
         {"op": "audit_entry", "step": "compliance", "level": "decision",
          "action": "proposed does not exceed the building energy target",
          "article": "8.4.1.2.(2)", "count": 1},
         {"op": "audit_entry", "step": "compliance", "level": "decision",
          "action": "unmet heating hours EXCEED 100 h",
          "article": "8.4.1.2.(3)", "count": 1},
         {"op": "audit_entry", "level": "warning", "article": "8.4.1.2.(5)",
          "count": 1},
         {"op": "observation_equals", "key": "compliant", "value": False},
         {"op": "observation_equals", "key": "reference_model_present",
          "value": True},
     ]},
    # The 2025 archetype-EUI path: no reference building is built, so no
    # reference_sizing/ or reference_annual/ appears, the target comes from
    # Table 8.4.4.1 (140 000 kWh for 800 m2 of Office at 175 kWh/m2), and
    # the proposed's own GHG mass is reported without a comparative level.
    # Authoring run: exit 0 / compliant, 93.1 % of target, tier 1, 37 s.
    {"id": f"api-eui-path-{NECB2025_EDITION}",
     "lane": "parity", "kind": "api", "replaces": [],
     "api_call": {"code": NECB2025_EDITION, "path": "eui",
                  "archetypes_map": {"Office": "all"},
                  "simulate": "annual", "province_state": "ONTARIO",
                  "model": "<CORPUS>/01-baseboard-gas.osm",
                  "weather": _WEATHER_2025, "building": {"storeys": 1}},
     "env": {}, "expect_exit": 0, "timeout_s": 5400,
     "files": CORPUS_FILES, "text_files": CORPUS_TEXT, "streams": {},
     "seal": FIRST_FREEZE_SEAL.format(edition="2025"),
     "asserts": [
         {"op": "json_gt", "file": "report.json",
          "path": "proposed.total_site_kwh", "value": 0},
         {"op": "json_gt", "file": "report.json",
          "path": "reference.building_energy_target_kwh", "value": 0},
         {"op": "json_gt", "file": "report.json", "path": "percent_of_target",
          "value": 0},
         {"op": "json_equals", "file": "report.json", "path": "tier",
          "value": 1},
         {"op": "json_equals", "file": "report.json", "path": "annual",
          "value": True},
         {"op": "json_equals", "file": "report.json", "path": "edition",
          "value": "2025"},
         {"op": "json_gt", "file": "report.json",
          "path": "proposed.ghg_kg_co2e", "value": 0},
         {"op": "path_absent", "relative": "reference_sizing"},
         {"op": "path_absent", "relative": "reference_annual"},
         {"op": "observation_equals", "key": "reference_model_present",
          "value": False},
         {"op": "observation_equals", "key": "compliant", "value": True},
     ]},
]


def all_scenarios(slugs):
    scenarios = (corpus_scenarios(slugs) + API_SCENARIOS + FAILURE_SCENARIOS
                 + VERDICT_SCENARIOS + EDITION_SCENARIOS)
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
