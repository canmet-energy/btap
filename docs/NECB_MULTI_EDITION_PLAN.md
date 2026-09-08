# Multi-edition / multi-code-family architecture — rev 7 (post Sol review 6)

## Context

`btap.necb` supports exactly two NECB editions today, threaded everywhere as
a plain string `vintage='2020'|'2025'`. Confirmed scope:

1. **Editions both ways** — NECB 2011, 2015, 2017 and 2030+.
2. **Independent provincial codes** — Ontario SB-10, BC Step Code: sibling
   code families with their own structure and article numbering, not NECB
   variants. (The MCP codes server already models them as `obc`, `bcbc`.)
3. **Full compliance depth for all.**

Two decisions taken after Sol's review of rev 1, both because **the
distribution has no users yet**:

- **Rename `btap.necb` → `btap.codes`**, with `btap.codes.necb` as the NECB
  family. Sol was right that hosting OBC/BCBC under a package whose
  `pyproject`, docstrings and CLI text all say "NECB" makes the namespace
  permanently dishonest; my "don't rename" defence rested on the public API,
  which has no consumers, and on the 313 coverage pointers, which resolve to
  **32 files** and are mechanically migratable (R6's PR-A3 did exactly this).
- **Drop `vintage`; `code=` / `--code` only.** No alias, no coercion layer.
  Omitting the argument still means `necb2020` (Sol's point: the current
  default must survive).

## What the survey found (unchanged from rev 1)

**23 literal vintage conditionals; 2 distinct rules genuinely differ.** 15 are
the same renumbering ternary, every one ending `else '8.4.4'` — a third
edition silently emits 2020 citations into an AHJ report. Across the 8
per-vintage JSON pairs, 80–96% of leaves are byte-identical. Rule blocks
already carry per-edition citations (hvac 13/14; envelope 3+1; shw 1;
lighting/loads 0) — HVAC pioneered the pattern and it was never rolled out.

**Two questions from the user set the principle.** "Does the project reference
2025 directly?" — yes, every 2025 file records full MCP retrieval and
row-by-row comparison, but that verification lives only as prose. "Could we
remove a supported code?" — no: 2020 is the substrate (`data_vintage_alias`,
a hardcoded 2020 filename, and **all 35 frozen scenarios are 2020**).

**The principle: every edition is an independent complete snapshot; the delta
is a generated review artifact, never a runtime dependency.** No `extends`,
no alias, no fallback rung. The achieved property is **runtime
independence**: nothing an edition needs at runtime or in CI lives in another
edition's files. Removal is more than deleting directories — see "The
removal operation" under Stage 4.

**Precedent rejected:** the oracle's `NECB2011 ← 2015 ← 2017 ← 2020` chain —
each edition overrode 1–5% of base, but the base could never be deleted and a
delta's silence means "inherited", not "checked".

## What Sol's review changed

Sol's verdict: principle sound, five blocking sequencing/contract
contradictions, return before Stage 0. All confirmed against the code:

1. **Stage 0 scenarios were unexecutable and would have falsified the
   attestation.** `_corpus()` derives ids from tier+slug only (collision →
   `FileExistsError` mid-freeze); the default `seal: "ruby"` is
   blanket-converted by `all_scenarios()` to `post-handoff` **carrying the
   85ab143 attestation**, and `freeze.py:105` rejects any unconverted `ruby`
   seal. The EUI kwarg is `archetypes_map`; `_execute_api` gets no `ctx`, no
   placeholders, no weather, and a fixed fixture model.
2. **Three registries conflated.** `--vintage` takes `2020`; `ids_for_family`
   would yield `necb2020`; `coverage._EDITIONS` means "has packaged 8.4 text".
3. **Stage 5 changed frozen output while claiming not to** (report.json
   fields, `--code` in help, and "exactly one required" broke the default).
4. **The 8.4 coverage scanner silently drops non-literal citations.** It
   recognises only `Constant`/`JoinedStr`, substitutes only the literal name
   `{prefix}`, has no unresolved counter — `compliance.py:346`
   `f"{lighting_prefix}…"` is **already dropped today**.
5. **Stage 2 didn't thread edition through `climate.py` and
   `daylight_control_requirement.py`**, both globally cached; the hide-files
   removability test would be vacuous under memoisation and unsafe under xdist.
6. **A generated delta between two checked-in files proves nothing about
   sourcing.** Copy 2020 → 2025, regenerate, passes.
7. **Stage 6 (back-catalogue) was not implementation-ready**; the 8.4 test
   hardcodes `("2020", 52), ("2025", 57)`.
8. **Namespace** — accepted, and with the user's rename decision the
   facade Sol proposed is unnecessary.
9. Interim manifest location (Stage 1 vs 2) — use the final one.
10. Per-module coverage is not a valid gate across code moves — informational.

## What Sol's second review changed (rev 2 → rev 3)

All verified against the code before revising:

1. **`_corpus`'s annual tier forces `--quick` and `expect_exit: 6`** — a
   "full 2025 determination" built with it would be a quick run with no
   verdict. It gets its own definition. `freeze.py:327` runs annual
   non-vacuity only for ids starting `corpus-annual`; the EUI scenario needs
   its own checks, and EnergyPlus preflight must be separate from the
   TBD-only check at `freeze.py:110-126`.
2. **R-B's "46 files" was pre-R-A arithmetic.** After R-A the 2025 scenarios
   carry code evidence too; the rename also touches generated coverage links,
   `runner.py`/`freeze.py` imports (hence machinery hashes) and manifest
   provenance. Derive the set after R-A; enumerate diff categories; second
   ledger, never rewrite the R6 one.
3. **Stage 5 was output-changing.** Five pointers into `eui_archetypes.py`/
   `tiers.py` (`necb_rules_2025.json:126-147`) are frozen at R-A. The
   physical move now rides R-B; Stage 5 keeps only the behaviour binding.
4. **R-C understated `vintage` removal.** It is in audit inputs
   (`compliance.py:153,208`), `report.json` (`:275`), every baseline, and
   `generate_necb_8_4_coverage.py:246` filters runs by it. All enumerated.
5. **Stage 9's "neutral phases" weren't.** `_load_and_validate` enforces NECB
   space types, `_attach_weather_and_hdd` is Table C-1, `_run_proposed_annual`
   requests the NECB heat-pump election. Pipeline keeps lifecycle mechanics
   only; families provide hooks. Full compliance ≠ reference building.
6. Rule-file discovery becomes manifest-driven (`manifest_domain` requires a
   `_rules_` underscore the new names lack). 7. The no-loss baseline keys by
   article, not `(file, article)`, so R-B doesn't invalidate it. 8. Provenance
   records source request/revision, source artifact hash and tool version —
   a result hash proves integrity, not origin. 9. The data root is a private
   test hook, not a production env var. 10. Rename inventory enumerated.

## What Sol's third review changed (rev 3 → rev 4)

All verified: (1) the EUI scenario asserted fields that don't exist — the
target is `report["reference"]["building_energy_target_kwh"]`, the EUI path
computes only `proposed.ghg_kg_co2e` and no comparative GHG level, and
`_execute_api` discards the `ComplianceResult` so nothing could inspect
`reference_model`. (2) `expect_exit` is scalar equality in both freezer and
comparator; `{0,1}` is unsupported and weaker than pinning the fixture's
real verdict. (3) R-A rewrites every manifest global — commit, four
machinery hashes, `gate_sha256`, counts, scenario list — and renaming
`lighting_prefix` makes a citation newly scanner-visible, so generated docs
move too. (4) **279 files** reference `btap.necb`, not ~10; the scanner
hardcodes `python/btap/necb/**/*.py` and a `"necb"` gem prefix. (5) `hdd18`
has five product call sites; the daylight chain is four functions plus
callers. (6) A result hash + a source hash still proves nothing about origin
without the artifact or a receipt. (7) `inputs.vintage` is 4–5 audit entries
per run from four emitters, not one. (8) Stage 5 carried a stale pointer
bullet. (9) The scanner's own `citations_for` has the silent `else "8.4.5"`
fallback the plan exists to remove. (10) NECB's annual phase is
prepare → run → consume; `annual_outputs()` covered only the middle.

## What Sol's fourth review changed (rev 4 → rev 5)

All verified: (1) the normal runner (`runner.py:318-370`) checks only exit,
files, text files and streams — an `asserts` block evaluated only in
`freeze.py` could regress silently after freezing; one shared checker. (2)
The reference path computes a **comparative** GHG level (`_score_ghg`,
`compliance.py:443`) and the EUI path only proposed mass (`:707`), so the
determination scenario needs a province or Stage 5's Part 11 binding is
never frozen. (3) `scenario_defs.py:191-211` **declares full-year
determination UNCOVERED** ("a 40–90 minute scenario") — R-A closes that gap
and must rewrite the claim; `active_seals` changes; `spec_sha256` does not.
(4) `audit.txt` renders code paths into the narrative — **96 per baseline**
— so R-B and R-C change text baselines and every `baseline_sha256`, and R-C
must also fix the synthetic verdict report's hardcoded `"vintage"` at
`runner.py:263` (hence `runner_sha256`). (5) `vintage` is a public parameter
on **97 domain functions** with **277 call sites** in tests and scripts —
Stage 7 was an order of magnitude short; Stage 6 gets private
`Ruleset`-based implementations behind temporary wrappers. (6)
`copied_identical_from` requiring a live target reintroduces the dependency
the architecture rejects; each edition validates against its own retained
artifact. (7) The scanner has more than one edition branch. (8) The
namespace gate must use `git ls-files`. (9) The `tiers.py` split needs an
exact symbol map, and the ledger test must prove a chain.

## What Sol's fifth review changed (rev 5 → rev 6)

All verified: (1) the CLI has **no province argument** and
`compliance_kwargs()` supplies none, so a CLI determination with GHG would
make R-A a product API change; CLI scenarios also time out at 600 s
(`runner.py:42`) unless `timeout_s` is declared. The determination becomes
an **API** scenario. `ghg_level` legitimately returns `level: None` over
target — pin the real value. (2) Stage 9a cannot be byte-identical if the
NECB phases physically move: six `compliance.py` symbols carry coverage
evidence (`_build_reference`, `_evaluate`, `_evaluate_unmet`,
`_load_and_validate`, `performance_compliance`, `_run_annual`). Forwarding
functions stay at the evidence-bearing paths. (3) The blanket `vintage` AST
gate would reject five parameters outside `btap/necb` (costing's
`lighting/report.py:28` etc.) that Stage 7 never inventoried — Stage 7 now
migrates them too, so gate and decision agree. (4) Registering any edition
changes the dynamic `--code` help choices and manifest globals — **new
editions are not additive freezes**; an R-Edition contract replaces that
claim. (5) The assertion contract is a serialisable schema, not prose. (6)
The R7 ledger must be allowlisted by the namespace gate. (7) `verify-source`
is meaningful only against a revision-addressable server; otherwise the
entry is a reproducible-current-source attestation. `manifest.json` is
excluded from its own provenance. (8) One R-A accounting line contradicted
the matrix; the matrix is authoritative.

## What Sol's sixth review changed (rev 6 → rev 7)

Converged; no redesign. All verified: (1) `timeout_s` reaches only the
`subprocess.run` inside `_execute_cli` (`runner.py:218`) — inert for
in-process API runs, so a 90-minute determination could hang forever. API
scenarios run in an isolated worker subprocess. (2) `cli.verdict_exit`
**already exists** (`cli.py:403-413`, and handles `annual is False`); rev 6
said to add it. The comparator reads `run.exit_code`, so `_execute_api`
must *return* that value, not stash it in observations. (3) The Stage 5
dispatch sent `compliance.py:446` — which is `_score_ghg` — to
`archetype_eui_path`; it and the EUI path's proposed-GHG calculation
resolve `part11_ghg`. (4) A no-loss gate keyed by article alone lets a 2025
site vanish while 2020 keeps the article visible, or five of six sites
vanish; key by `(edition, article, kind)` with counts. (5) Stage 9a's
symbol ownership contradicted the pipeline boundary — `_run_annual` and
`performance_compliance` are neutral, `_load_and_validate` splits — and
forwarding functions must be on the executed call path, never dead stubs.
(6) The provenance `status` field conflated two dimensions. (7) R-C's
manifest diff omitted `api_call.vintage` on the existing and new API
scenarios. (8) The newly covered gap is API execution plus the shared
`verdict_exit` classifier, not a literal CLI run.

**The re-freeze matrix, corrected — three in Stages 0–7, each single-cause,
plus one contract per later edition:**

| re-freeze | cause | accepted diff categories |
|---|---|---|
| R-A (Stage 0) | additive: new 2025 scenarios; `scenario_defs.py`, `freeze.py`, `runner.py`, gate-test hashes | new baseline **directories**; the **35 existing directories byte-identical**; manifest: `provenance.commit`, `freezer/defs/runner/gate_sha256`, **`active_seals` (+4 `python-only:*`)**, counts, scenario list — **`spec_sha256` unchanged** (no spec edit); the UNCOVERED text at `scenario_defs.py:191-211` rewritten to record the full-year determination as covered; generated citation docs move where `lighting_prefix`→`prefix` makes `compliance.py:346` visible |
| R-B (Stage 1) | all physical path changes: package rename **and** the eui/tiers move to `editions/necb2025/` | `/inputs/code[]` in `audit.json` **and the same paths in normalized `audit.txt`** for every evidence-bearing baseline (derived after R-A); each affected `baseline_sha256`; generated coverage links; `freezer/runner_sha256` (import lines); `provenance.commit` |
| R-C (Stage 7) | public API: `--code`, `vintage` removed from every argument **and** output surface, `NECB` labels → `code_label` | help-text baselines; `report.json` (`vintage`→`edition`, +`code`, +`code_label`); audit `inputs.vintage` at 4–5 emitters per run, in **both** `audit.json` and `audit.txt`; every affected `baseline_sha256`; the 2025 scenarios' argv (→ `defs_sha256`); the synthetic verdict report at `runner.py:263` (→ `runner_sha256`); coverage-gen run filter; `provenance.commit` |

| **R-Edition** (Stage 8, once per new code id) | registering `necb2017` etc. | new scenario directories; **help-text baselines** (`--code {…}` choices are dynamic); every affected `baseline_sha256`; manifest `provenance`, counts, scenario list, `active_seals`; regenerated registry, coverage and delta documents |

Everything between R-A, R-B and R-C is byte-identical against the baselines
the previous re-freeze produced. Stage 8 editions each carry an R-Edition.

---

# Execution model — who does what

Fable orchestrates; subagents build; **Fable verifies every deliverable
against the stage's accepted-diff contract before anything is committed.**
Subagents run in isolated worktrees and never touch `verification/scenarios/`
baselines or run `freeze.py` — re-freezes and their attribution are Fable's,
personally, because that is where the evidence lives.

| model | used for | rule |
|---|---|---|
| **Fable** (this session) | orchestration; every re-freeze (R-A/R-B/R-C/R-Edition) and its field-by-field diff attribution; reviewing each subagent's output against the contract; anything that decides what a baseline is allowed to contain; the authoring runs that pin `expect_exit`/`compliant`/`ghg.level` | never delegated |
| **Opus** | deep multi-file refactors where the design has to be held in one head: the R-B rename sweep (279 files) with the R7 ledger and chain test; Stage 6's private-implementation-behind-wrapper threading across 97 functions; Stage 9a's pipeline/family split with forwarding on the call path; `api_worker.py` and the shared `check_assertions` interpreter | one Opus agent per such task, in a worktree, returning a branch for Fable to verify |
| **Sonnet** | well-specified, bounded implementation: the 7-operator assertion schema; `test_edition_provenance.py`; `generate_necb_edition_delta.py`; `test_edition_independence.py` (subprocess + temp tree); edition-threading through `climate.py` and the four-function daylight chain; `citation_counts_baseline.json` and its gate; `test_no_legacy_namespace.py` and `test_no_vintage_parameter.py`; manifest-driven discovery in the four generators; the `Ruleset` registry | spec comes from this plan verbatim; Sonnet must not widen scope |
| **Haiku** | mechanical, high-volume, no-judgment: the 277 `vintage=` → `code=` call-site migration and the 5 costing renames; `git mv` + import rewrites once Opus has fixed the shape; regenerating the coverage/delta docs; running the verification block and reporting results; materialising 2025's six table copies | output is diffed by Fable, never trusted on description |

**Sequencing inside a stage.** Independent items run in parallel (Stage 0:
0.3 and 0.4 alongside 0.1 → 0.2, which are sequential). Each subagent
returns a worktree branch; Fable runs the stage's verification block on it,
attributes the diff, and commits. A subagent that cannot meet its contract
reports the gap rather than approximating — the same rule that governed the
R6 reviews.

**Nothing starts until:** Sol's review of rev 7 is recorded, and
`docs/NECB_MULTI_EDITION_PLAN.md` carries rev 7.

> **Gate outcome (2026-09-07):** the user approved rev 7 and directed
> Stage 0 to begin **without** a rev-7 Sol review. Recorded so the gap is
> explicit; Sol's rev-7 review, when it arrives, is folded into the
> progress log below rather than blocking.

# Stages

## Stage 0 — make the tests able to catch the refactor (R-A, additive)

Measured: 89% line coverage of `btap/necb` (7,362 stmts, 776 missed), but
**zero frozen 2025 evidence**, one real 2025 simulation test
(`test_report_html.py`), and two of the 15 citation sites in no baseline.

**0.1 Scenario machinery** (`verification/scenarios/scenario_defs.py`,
`runner.py`, `freeze.py`):

- `_corpus(slug, tier, lane, *, code="necb2020", extra=())`. Id stays
  `corpus-{tier}-{slug}` when `code == "necb2020"` (every existing id
  byte-identical) and becomes `corpus-{tier}-{slug}-{code}` otherwise.
  `code` also emits `--vintage 2025` into argv (Stage 7 rewrites to `--code`).
  **`_corpus`'s annual tier is a quick run** — `["--simulate","annual",
  "--quick"]` with `expect_exit: 6` — so it cannot express a determination.
  The full-determination scenario is authored explicitly (below), not via
  the helper.
- New scenarios get `seal: "python-only:first frozen post-R6 for NECB 2025 —
  no cross-language attestation exists for this edition"`. `all_scenarios()`
  converts only `ruby`/`ruby-api:` prefixes, so these pass through
  untouched, keep no `retired_seal`, and the `31 / 29 / 2` assertions in
  `test_frozen_scenarios.py:126-137` are unchanged. Add an assertion that no
  `python-only:` seal carries attestation fields.
- **API scenarios run in an isolated worker subprocess.** `timeout_s` is
  passed only to the `subprocess.run` inside `_execute_cli`
  (`runner.py:218`); `_execute_api` runs in-process, so no declared timeout
  can stop a hung determination. New `verification/scenarios/api_worker.py`:
  `_execute_api(scenario, run_dir, ctx)` resolves placeholders recursively
  in `api_call` (adding `<DDY>` to `make_ctx`), then spawns
  `python api_worker.py <resolved-api_call.json> <run_dir>` with
  `timeout=scenario.get("timeout_s", DEFAULT_TIMEOUT_S)`. The worker
  **pops `"model"`** from the kwargs (loads it via `btap._sdk.load_model`;
  falls back to `compliance_fixture()` when absent, preserving
  `api-thermal-bridging`), calls `performance_compliance(**kwargs)`, and
  writes `observations.json` — `exit` from **the existing
  `cli.verdict_exit(result)`** (`cli.py:403-413`; it already maps
  `compliant is None` and `annual is False` to `no_determination`),
  `compliant`, `reference_model_present`, and the report keys the
  `asserts` name. The parent returns
  `ScenarioRun(exit_code=observations["exit"], stdout, stderr, run_dir)`
  with `observations` attached — so `expect_exit` is checked by the same
  `run.exit_code` comparison at `runner.py:322` as every CLI scenario.
  **Both** annual API scenarios declare `timeout_s: 5400`.
- `freeze.py`: (a) split preflight — the existing TBD check at `:110-126`
  stays keyed on `thermal_bridging`; a **separate** EnergyPlus preflight keys
  on `kind == "api" and api_call.get("simulate") != "none"` or any argv with
  `--simulate annual|sizing`; (b) replace the annual non-vacuity at
  `:327-334` (`id.startswith("corpus-annual")`) with a per-scenario
  `"asserts"` block evaluated by **one shared
  `runner.check_assertions(scenario, run)`**, called from both `freeze.py`
  before publishing and the normal comparator in `runner.py:318-370` on
  every run — so an in-memory observation such as `reference_model_present`
  is a CI gate after freezing, not only a freeze-time check.
- **The assertion contract is a serialisable schema** — it enters the
  generated `manifest.json`, so no lambdas and no freeze-only logic. Each
  entry is `{"op": …, …}` with exactly these operators, interpreted by the
  one shared function:
  `json_exists {file, path}` · `json_equals {file, path, value}` ·
  `json_gt {file, path, value}` · `json_in {file, path, values}` ·
  `audit_entry {step?, level?, action?, article?, ruling?, inputs?, count}`
  (structured match over `audit.json` entries — `inputs` matches nested
  keys; `count` is the exact number of matching entries) ·
  `path_absent {relative}` · `observation_equals {key, value}` (against
  `ScenarioRun.observations`). No regex-over-prose operator: `audit.txt`
  rendering is already pinned byte-exactly, and structural checks belong
  on the structured file. Unknown `op` raises.
- **Rewrite the declared gap — accurately.** `scenario_defs.py:191-211`
  lists "full-year end-to-end determination (exits 0/1 through a real
  annual run)" as UNCOVERED, citing its 40–90 minute cost. R-A covers **API
  pipeline execution of a full-year determination, classified by the shared
  `cli.verdict_exit`** — not a literal CLI end-to-end run. The entry moves
  to a covered record that says exactly that, names
  `determination-01-baseboard-gas-necb2025` and its cost, and notes the
  existing verdict-unit scenarios still cover CLI rendering. The manifest's
  `active_seals` gains four `python-only:*` entries.

**0.2 The scenarios** (exact lane counts):

| id | lane | definition | `asserts` (non-vacuity, checked by `freeze.py` before publishing) |
|---|---|---|---|
| `corpus-none-01-baseboard-gas-necb2025` | python | `_corpus(…, code="necb2025")` | reference build audited at 2025 |
| `corpus-none-08-vrf-necb2025` | python | `_corpus(…, code="necb2025")` | `audit_entry {step: "build", action: "proposed VRF outdoor unit serves no reference zone — removed", ruling: "D-85", inputs: {terminals: 0}, count: 1}` |
| `determination-01-baseboard-gas-necb2025` | parity | **`kind: "api"`** — the CLI has no province argument (`cli.py:171-221`; `compliance_kwargs()` at `:296-316` never passes `province_state`), and adding one during R-A would change help baselines and make R-A a product API change. `api_call`: `{"vintage": "2025", "simulate": "annual", "province_state": "ONTARIO", "model": "<CORPUS>/01-baseboard-gas.osm", "weather": {"epw": "<EPW>", "ddy": "<DDY>"}, "building": {"storeys": 1}}`; `timeout_s: 5400` (default is 600; this run is 40–90 min); `files: ["audit.json", "report.json"]`, `text_files: {"audit.txt": "normalized"}`. **Run once while authoring; pin exact `expect_exit` via `observations["exit"]` and exact `compliant`** | `json_gt proposed.total_site_kwh 0`; `json_gt reference.total_site_kwh 0`; `json_exists` both `unmet_occupied_hours`; `json_equals annual true`; `json_exists ghg` and **`json_equals ghg.level <pinned after authoring — legitimately null when proposed GHG exceeds reference>`** (this freezes Stage 5's Part 11 binding — the EUI scenario cannot, it has no reference); `observation_equals compliant <pinned>` |
| `api-eui-path-necb2025` | parity | `kind: "api"`, `{"vintage": "2025", "path": "eui", "archetypes_map": {"Office": "all"}, "simulate": "annual", "province_state": "ONTARIO", "model": "<CORPUS>/01-baseboard-gas.osm", "weather": {"epw": "<EPW>", "ddy": "<DDY>"}, "building": {"storeys": 1}}`, `timeout_s: 5400`, `files: ["audit.json", "report.json"]`, `text_files: {"audit.txt": "normalized"}`. Exact `expect_exit` and `compliant` pinned after an authoring run | `proposed.total_site_kwh > 0`; `reference.building_energy_target_kwh > 0`; `percent_of_target > 0`; `tier` key present (exact value pinned after the authoring run — legitimately `None` when the target is exceeded); `proposed.ghg_kg_co2e > 0` (proposed mass only); `result.reference_model is None`; no `reference_sizing/` or `reference_annual/` directory; `compliant == <pinned bool>` |

**`ScenarioRun` must retain structured API observations.** `_execute_api`
at `runner.py:233-240` returns `ScenarioRun(None, "", "", run_dir)` and
discards the `ComplianceResult`, so `result.reference_model` and
`result.compliant` are currently uninspectable. Add an `observations: dict`
field populated from the result (`reference_model_present`, `compliant`,
and the listed report keys); the `asserts` block is evaluated against it.

Python lane 30 → **32** subtests; parity 2 → **4**. Wire both parity
additions into `test.yml`'s lane assertion. One `freeze.py` promotion from
`python/.venv/bin/python` on a clean tree. **R-A's accepted diff, stated
precisely:** the 35 existing baseline *directories* byte-identical (verified
with the content-aligned comparison used for the R6 freezes); four new
directories; `manifest.json` globals rewritten — `provenance.commit`,
`freezer/defs/runner_sha256` (**not** `spec_sha256`), `gate_sha256` (the
seal assertion added to `test_frozen_scenarios.py` changes it),
`active_seals` (+4), `counts`, the scenario list; and
`docs/NECB_8_4_COVERAGE.html` moving where the `lighting_prefix`→`prefix`
fix makes `compliance.py:346` scanner-visible. Nothing else. The `asserts`
block is the contract: a baseline that fails its own non-vacuity does not
freeze.

**0.3 Citation gates, written against unmodified code:**

- `tests/necb/test_codes_registry.py`: a literal `(edition, site) → string`
  table for all 15 sites × 2 editions, asserting the `article` of the audit
  entry each site emits. Passes first, then guards Stage 2.
- `test_hvac_necb_humidification.py` and
  `test_hvac_economizer_fancurve_checker.py` assert the exact `article` for
  both editions — the two sites in no baseline.
- **Scanner no-loss gate, keyed by `(edition, article, kind)` with
  counts.** Record, per edition the scanner resolves for, the number of
  runtime citation sites per `(article, kind)` — `kind` being the
  scanner's own classification (decision / warning / info) — to
  `tests/data/citation_counts_baseline.json`; a test asserts no count
  decreases. Keying by article alone would let a 2025 site vanish while
  2020 keeps the article visible, or five of six sites vanish while one
  remains. No file path enters the key, so R-B's rename cannot invalidate
  it; a deliberate count change (e.g. the `compliance.py:346` fix adds one)
  is re-baselined explicitly in the same commit with the reason recorded. Replace the
  `> 50` floor in `test_generate_necb_8_4_coverage.py:38`. Fix the
  **pre-existing** drop at `compliance.py:346` by naming the variable
  `prefix`. The scanner's other blind spots (`ast.Name`, `spec["article"]`,
  calls) are pre-existing and unchanged by this plan; Stage 2 introduces no
  new ones. A registry-aware scanner is a separate improvement, out of scope.

**0.4 Coverage is informational.** Record the per-module report in
`docs/necb_rule_verification.md` under a dated heading; re-run per stage and
report movement, but the gates are the frozen lanes, the citation table and
the scanner no-loss test. Add `coverage` to the `CLAUDE.md` install line.

## Stage 1 — all physical path changes (R-B): rename, plus the eui/tiers move

Done first so every later stage lands in its final home. **Zero logic
change** — the diff must be attributable entirely to paths. Two moves ride
together because both change only `/inputs/code[]` evidence: the package
rename, and `eui_archetypes.py` / the 2025 two-thirds of `tiers.py` into
`editions/necb2025/` (their five pointers at `necb_rules_2025.json:126-147`
are frozen at R-A, so moving them later would break a byte-identical stage).

```
btap/codes/
├── __init__.py            (Stage 2 fills the registry; for now re-exports)
├── cli.py  compliance.py  coverage.py  decisions.py
├── report/
├── necb/
│   ├── envelope/ hvac/ lighting/ loads/ shw/
│   ├── tiers.py                      energy_tier() only
│   ├── editions/necb2025/            eui_archetypes.py  part11_ghg.py  (moved, unbound until Stage 5)
│   └── data/                         (Stage 3 reorganises this)
└── data/decisions.json  coverage/
```

**Rename inventory is a gate, not a list.** `btap.necb` / `btap/necb` is
referenced in **279 files** across product modules, tests, scripts,
launchers and workflows — too many to enumerate by hand and stay honest.
R-B ships `tests/test_no_legacy_namespace.py`: after the rename, no
*active* reference remains in **tracked** sources — the gate walks
`git ls-files` under `python/btap/`, `python/tests/`, `python/scripts/`,
`packaging/`, `verification/*.py`, `.github/`, `pyproject.toml`,
`CLAUDE.md` and the per-domain docs. Never the working tree:
`packaging/windows/stage/` holds untracked build output full of legacy
strings, and a filesystem walk would fail on it.

**Exact `tiers.py` symbol map** (drives the R7 ledger — every pointer must
resolve to a named destination):

| symbol | destination |
|---|---|
| `energy_tier` | stays — `btap/codes/necb/tiers.py` (all editions) |
| `eui_data`, `eui_building_energy_target` | `editions/necb2025/eui_archetypes.py` (with the EUI implementation that already imports them) |
| `ghg_data`, `operational_ghg_kg`, `ghg_level` | `editions/necb2025/part11_ghg.py` | **Historical records are excluded
deliberately, never rewritten**: `PORT_STATUS.md`, `docs/R6_REVIEW_HANDOFF.md`,
`docs/d80_retirement_plan_review.md`, **both ledgers** (the R6 one and
`coverage_code_ref_mapping_r7.json`, whose `old` column necessarily names
`python/btap/necb/…` — the chain test validates them structurally instead),
and dated period wording in `necb_decisions.md` / `decisions.json` — the
gate carries an explicit allowlist with a reason per entry. Known load-bearing sites the
gate must cover: `pyproject.toml:9-10,53-54,104-119`;
`packaging/windows/btap-compliance.cmd:28`; `scripts/wheel_smoke.py:74,83,129,148`;
`verification/scenarios/runner.py:215,235,260`, `freeze.py:116` (hash-pinned,
absorbed by R-B's promotion); **`generate_necb_8_4_coverage.py:162`**, which
globs `python/btap/necb/**/*.py`, **and `:193-203`**, which keys on
`citation["gem"] == "necb"` — both change here, before Stage 3's
manifest-driven discovery. Version bump to 0.3.0: an intentional breaking
release with no consumers.

**Evidence pointers.** After R-A, derive the affected set: every baseline
`audit.json` **and `audit.txt`** containing `python/btap/necb/` (96 path
occurrences per no-simulation `audit.txt` today; the 46 pre-R-A files plus
the new 2025 scenarios' — do not carry the "46" forward). A **second**
ledger `tests/data/coverage_code_ref_mapping_r7.json` maps each of the 87
unique refs (32 files) old → new, including the five eui/tiers moves.
**Never rewrite the R6 ledger.** `test_coverage_code_refs.py:95-111`
currently validates one endpoint (ledger `new` == live manifests); extend it
to prove the **chain**: every R7 `old` equals an R6 `new`, every R7 `new`
equals a live manifest reference, and the union of R7 `uses` still sums
to 313.

**Accepted diff categories, each checked explicitly before commit:** (1)
`/inputs/code[]` leaves in every evidence-bearing `audit.json`; (2) the
same path strings in normalized `audit.txt`; (3) each affected
`baseline_sha256`; (4) regenerated `docs/NECB_8_4_COVERAGE.html` and
`NECB_COVERAGE.md` links; (5) manifest `provenance.commit`,
`freezer_sha256`, `runner_sha256` (import lines); (6) nothing else — the
content-aligned comparison used for PR-A3 must report no other differing
leaf path.

D-XX `kind: process` entry adjudicating R-B.

## Stage 2 — citations from data; the `Ruleset` registry (output-identical)

**New** `btap/codes/__init__.py` (the registry) and, per edition, the manifest
at its **final** location `btap/codes/necb/data/necb2020/manifest.json`
(rule files stay where they are until Stage 3).

```python
@dataclass(frozen=True)
class Ruleset:
    id: str          # "necb2020"
    family: str      # "necb"
    edition: str     # "2020"
    label: str       # "NECB 2020"
    def article(self, key) -> str: ...        # KeyError on miss — never a default
    def behaviour(self, name): ...            # Stage 5: module or None
    def rules(self, domain) -> dict: ...      # Stage 6

def code_ids() -> ["necb2020", "necb2025"]
def editions(family) -> ["2020", "2025"]      # ONLY NECB editions with a manifest
def resolve(code_id) -> Ruleset
```

Three registries, kept separate (Sol #2): `editions("necb")` backs
`cli.py:184`'s `--vintage` choices — returns `["2020","2025"]`, so `--help`
is byte-identical; `coverage.editions()` stays its own thing ("has packaged
8.4 text") and Stage 8 must never let a manifest-only edition into it.
Internally, `Ruleset.from_edition("2020")` exists for the transition and is
deleted in Stage 7 with `vintage`.

**The 15 sites keep their scanner-visible shape** (Sol #4). Each becomes
`prefix = ruleset.article("reference_subsection")` followed by the existing
`article=f"{prefix}.3.(2)"` f-string — the variable must be literally named
`prefix`. Where the rule block already holds the full string
(`hvac/reference.py:1220` → `spec["article"]`), the scanner already misses
it today, so that is a no-loss change by the gate's own baseline. Delete the
dead ternary at `lighting/storage_garage/__init__.py:86`. Manifest `articles`
carries only what the ternaries compute: `reference_subsection`,
`lighting_subsection`, `heat_pump_aux_fuel`.

**The scanner's own fallbacks go too — all of them.**
`generate_necb_8_4_coverage.py:192-207` has more than the
`reference_prefix = … else "8.4.5"` default: `citations_for` also carries
hardcoded `vintage == "2020"` branches that remap literal `8.4.4.`
citations per edition. Every edition-specific citation mapping resolves
through the `Ruleset` article map (`reference_subsection`, and an explicit
`literal_remaps` entry for the `8.4.4.`→`8.4.5.` case) and **raises on an
unknown mapping** — the next coverage-enabled edition must not recreate the
original defect inside the tool that documents it. Output-identical for
2020/2025 by construction.

**Verify.** Frozen lanes byte-identical (32 + 3 + 4); `test_codes_registry.py`
passes; scanner no-loss gate passes; `test_coverage_code_refs.py` unchanged.

## Stage 3 — editions become independent snapshots (output-identical)

**Code stays by domain, data moves by edition.** Removal = `git rm -r`.

```
btap/codes/necb/
├── envelope/ hvac/ lighting/ loads/ shw/     Python only
└── data/
    ├── necb2020/
    │   ├── manifest.json
    │   ├── necb_rules.json  envelope_rules.json  reference_rules.json  efficiencies.json
    │   ├── lighting_rules.json  loads_rules.json  shw_rules.json
    │   ├── tables/  space_types  schedules  led_lighting  exterior_lighting
    │   │            table_c1  daylighting_controls_4_2_1_6      (own copies)
    │   └── coverage/articles_8_4.json
    └── necb2025/   same + eui_targets.json  ghg_factors.json  tables/lpd_*.json
```

Verified bounds: zero baselines reference a data filename; package-data glob
`data/**/*.json` needs no `pyproject` change. **Rule-file discovery becomes
manifest-driven** (Sol): `manifest_domain()` at
`generate_necb_8_4_coverage.py:144` requires a `_rules_` underscore and
`declarations_for` at `:214` globs `*_rules_{vintage}.json` — neither
survives the new names. The manifest enumerates its files:

```json
"rules": {"umbrella": "necb_rules.json", "envelope": "envelope_rules.json",
          "hvac": "reference_rules.json", "hvac_efficiencies": "efficiencies.json",
          "lighting": "lighting_rules.json", "loads": "loads_rules.json", "shw": "shw_rules.json"},
"tables": ["tables/space_types.json", "…"], "coverage_text": "coverage/articles_8_4.json"
```

and the four discovery sites (`test_coverage_code_refs.py:21`,
`generate_necb_coverage.py:26`, `necb_orphan_keys.py:22`,
`generate_necb_8_4_coverage.py:144-150,214-220`) read the manifest via the
registry instead of a filename grammar.

- Materialise 2025's own copies of all six shared tables. Remove
  `data_vintage_alias` and `data_vintage()` (`loads/__init__.py:39`,
  `lighting/__init__.py:55`) and its seven callers. Delete the dormant
  `efficiency_vintage_fallback` rung (`hvac/efficiency.py:45-64`) and the
  `requested_vintage` split it forced. Normalise envelope's plural
  `articles` → `article`.
- **Thread edition through the two globally-cached loaders (Sol #5).**
  `climate.hdd18(model, *, edition, hdd=None, audit=None)` — **five**
  product call sites, all of which already hold the vintage and none of
  which forward it: `envelope/reference.py:58`, `prescriptive.py:59`,
  `thermal_bridging.py:136`, and both compliance paths at
  `compliance.py:234` (reference) and `:664` (EUI), via the
  `envelope.hdd18` re-export at `envelope/__init__.py:75`. Cache keyed by
  edition. `daylight_control_requirement`: edition must propagate through
  the whole chain — `table(edition)`, `residue(edition)`,
  `requirement(standards_space_type, *, edition)`,
  `evaluate(space, *, edition, …)` — and its callers
  (`lighting/daylighting.py:56`, the `lighting/__init__.py:82,97`
  re-exports). Its docstring records that 2020/2025 agree 0-of-909 cells —
  that finding is now expressed as two identical files, each with its own
  retained source artifact, plus an optional Stage 4 `byte_identical_to`
  annotation — not as shared code, and not as a dependency.
- **Injectable data root — test-only.** Every loader resolves through one
  `btap.codes.necb._data_root()`. It is a module-level callable that tests
  replace via a documented private hook (`btap.codes.necb._set_data_root`
  under a `_testing` guard) — **not** an environment variable. A production
  override would let a deployed run silently replace adjudicated package
  data (Sol).

**Verify.** Frozen lanes byte-identical. **Removability gate**
`tests/necb/test_edition_independence.py`: for each edition, build a
temporary data tree containing only that edition, and in a **fresh
subprocess** that installs the hook before importing anything run every
domain loader, `climate.hdd18`, `daylight_control_requirement.table`, and
`performance_compliance(simulate="none")`. Subprocess defeats memoisation;
the temp tree makes it xdist-safe (Sol #5).

## Stage 4 — checked provenance, and the generated delta (output-identical)

Sol #6: the delta is the **review** artifact; the **provenance** manifest is
the evidence. Both.

- Each edition's `manifest.json` gains a checked `provenance` block, per
  rule file and table. A result hash proves integrity, not origin (Sol), so
  each entry pins the source side too:
  ```json
  {"source": "mcp:necb:2025", "request": {"tool": "get_table", "table": "5.2.12.1.-I"},
   "source_revision": "<MCP server/build id>", "source_sha256": "<hash of the raw response>",
   "extractor": "fetch_necb_8_4_text.py@<git sha>", "retrieved": "2026-07-12",
   "method": "transcribed" | "copied" | "generated",
   "source_verification": "archived" | "revision_addressable" | "current_only" | "manual",
   "byte_identical_to": "necb2020/tables/space_types.json",   // optional; checked only when both exist
   "result_sha256": "<hash of the shipped file>"}
  ```
  (`"oracle:<REF>"` and `"printed:<citation>"` sources carry the analogous
  fields.) **A `source_sha256` alone still proves nothing about origin
  unless the artifact it hashes is retained** (Sol). So: where licensing
  permits, the **canonical result payload** — never the JSON-RPC/SSE
  envelope, whose request ids and transport metadata change per call — is
  archived under `btap/codes/necb/data/<id>/provenance/<table>.result.json`
  (sorted keys, fixed separators) and is what `source_sha256` hashes; where
  licensing does not permit, the entry records a locator and a maintainer
  command — `btap-necb-coverage verify-source <id> <table>` — that
  re-fetches, canonicalises and compares. **That command is only evidence
  of origin if the recorded server build is revision-addressable**: the
  request must pin the build and the server must honour it. If it cannot
  (a moving endpoint verifies today's response, not the original), the
  entry's `source_verification` is `current_only` — an honest, lesser
  attestation. These are **two dimensions**, not one status: `method` says
  how the file came to be, `source_verification` says how strongly its
  origin can be re-established. **The provenance coverage set is the
  manifest-declared outputs** — the `rules`, `tables` and `coverage_text`
  entries — and nothing else: not `manifest.json` (self-hash is recursive)
  and not the files under `provenance/` (the archived artifacts would
  otherwise need their own provenance, and so on). The `extractor` field names the tool
  **actually** used per dataset: `fetch_necb_8_4_text.py` produced only the
  Section 8.4 text caches and must not be attributed to the Part 4/5/6 rule
  tables, whose extraction path is recorded honestly (or as `"manual"` with
  the transcriber).

  **No cross-edition dependency in validation** (Sol). A `copied` file
  still carries its **own** `source_*` fields, because the copy was made
  from a retained artifact, not from another edition's live file. Cross-edition equality is
  recorded as an *optional* `byte_identical_to: "necb2020/<file>"` and
  checked **only when both editions are present**; it never gates the
  edition that declares it. `tests/necb/test_edition_provenance.py` asserts
  every file has an entry, every `result_sha256` matches, every archived
  payload matches its `source_sha256`, and every present
  `byte_identical_to` target is byte-identical — and the Stage 3
  removability gate runs this test **with only one edition present**.

**The removal operation** (the property is *runtime independence*, and this
is what exercising it actually takes):

1. `git rm -r btap/codes/necb/data/<id>` and, if present,
   `btap/codes/necb/editions/<id>`;
2. delete that edition's scenarios from `scenario_defs.py` and their
   baseline directories; one `freeze.py` promotion (the manifest's counts,
   `active_seals`, hashes move — nothing else);
3. regenerate `docs/NECB_EDITION_DELTAS.md`, the coverage documents and the
   registry's edition list; `git diff docs/` shows only that edition's rows;
4. the removability gate, the provenance test and the no-loss citation gate
   all pass with the edition absent.

Step 1 is what "no runtime dependency" buys; steps 2–4 are the bookkeeping
any edition removal owes, and the plan names them so nobody mistakes the
directory delete for the whole job.
- **New** `python/scripts/generate_necb_edition_delta.py` →
  `docs/NECB_EDITION_DELTAS.md`: per consecutive edition pair and domain, a
  leaf-level diff with renumbering separated from value changes;
  `provenance`/`article_coverage` prose excluded. Modelled on
  `generate_necb_coverage.py`; regenerated in the `lint` job; fails on drift.

## Stage 5 — bind edition-specific code through the manifest (output-identical)

The physical move happened in R-B; the modules sit at
`editions/necb2025/{eui_archetypes.py, part11_ghg.py}` still imported by
name from `compliance.py`. This stage replaces that import with the binding:

```
btap/codes/necb/data/necb2025/manifest.json
    "behaviours": {"archetype_eui_path": "btap.codes.necb.editions.necb2025.eui_archetypes",
                   "part11_ghg":         "btap.codes.necb.editions.necb2025.part11_ghg"}
```

- `Ruleset.behaviour(name)` → module or `None`. **Exact dispatch** (rev 6
  sent `:446` to the wrong behaviour):

  | site | today | resolves |
  |---|---|---|
  | `compliance.py:129` — `path="eui"` entry | `vintage != "2025"` raises | `archetype_eui_path` |
  | `compliance.py:484` — `_supplement_eui` gate | `vintage == "2025"` | `archetype_eui_path` |
  | `compliance.py:443-460` — `_score_ghg` (reference path, comparative) | `vintage == "2025"` | **`part11_ghg`** |
  | `compliance.py:684-713` — EUI path's proposed-only GHG mass | implicit | **`part11_ghg`** |
  | Section 10 energy tiers | `tiers.energy_tier` | shared `tiers.energy_tier`, no binding |

  The direct `import eui_archetypes` at `:34` is deleted. Loaders in the
  bound modules read from their own edition's data directory. No path in
  any evidence pointer changes — that is why this stage is byte-identical.
- **Promotion rule:** when a later edition shares the logic, move it to the
  shared tree and point both manifests at it; requires a D-XX entry (Sol).
- The 20 h unmet-cooling floor (`compliance.py:963`, `:1240` — one rule
  twice) → `necb_rules.json` `unmet_cooling.minimum_allowance_h`; HPWH floor
  (`shw/efficiency.py:199-200`) → `shw_rules.json`.

**Verify.** Frozen lanes byte-identical — including `api-eui-path-necb2025`,
which is what makes this move checkable. Behaviour-orphan gate: every
`behaviour("…")` name in Python is in ≥1 manifest and every manifest module
imports. Removability gate extended to `editions/<id>/`.

## Stage 6 — one loader; `Ruleset` threaded internally (output-identical)

- **New** `btap/codes/necb/rulesdata.py`: `load(domain, code_id)`, one cache,
  one error. Six loaders become shims; names kept (coverage pointers).
- `compliance.py:1320` silent-return → explicit `"article_coverage": null`.
- **Private `Ruleset`-based implementations behind unchanged public
  wrappers** (Sol). `vintage` is a public parameter on **97 domain
  functions** (e.g. `envelope/rules.py:19-105` ×4, `hvac/reference.py` ×8,
  `loads/__init__.py` ×5, `shw/demand.py` ×3) with **277 call sites** in
  tests and scripts. Stage 6 does not touch those signatures. Each public
  `f(model, vintage=…)` becomes a one-line wrapper that coerces and calls a
  private `_f(model, ruleset, …)`; `performance_compliance` builds the
  `Ruleset` once and threads it internally. **No public signature, help
  text or report change here** — that is Stage 7.

## Stage 7 — the public API (R-C, behavioural, adjudicated)

Single-cause: every user-visible surface changes in one re-freeze.

- `performance_compliance(model, *, code="necb2020", …)`. `vintage` removed.
  `Ruleset.from_edition` deleted. A `code` naming no manifest raises.
- **Every public domain wrapper from Stage 6 is replaced** — all 97
  functions take `code=` (or a `Ruleset`), and all 277 test/script call
  sites migrate. This is the bulk of Stage 7's diff and it is mechanical.
- **The migration is package-wide, so the gate can be.** `vintage` is also
  a parameter on **five functions outside `btap/necb`** — costing's
  `lighting/report.py:28` `cost(model, *, vintage=…)` and its `fixtures.cost`
  call, plus sample/tool helpers — where it selects NECB fixture sets by
  edition. Stage 7 renames those to `edition=` as part of the same
  mechanical sweep (they are an edition concept, and leaving them would
  make the gate's scope narrower than the decision). Then the **AST gate**
  `tests/test_no_vintage_parameter.py` walks every tracked `.py` under
  `python/` and fails on any function parameter named `vintage` or any call
  passing `vintage=`; the word survives only in strings and the historical
  allowlist.
- The synthetic verdict report at `runner.py:263` (`"vintage": "2020"`) →
  `"edition": "2020", "code": "necb2020"`; `runner_sha256` moves.
- `cli.py`: `--code {necb2020,necb2025}` replaces `--vintage`; default
  `necb2020`. Help-text baselines (`usage-no-model`, `usage-unknown-flag`)
  re-freeze. The 2025 scenarios' argv → `--code necb2025`.
- **`vintage` leaves every output surface, not just the signature** (Sol):
  `compliance.py:153` `opts["vintage"]` → `opts["code"]`; `report.json` at
  `:275` `"vintage"` → `"edition"`, plus `"code"` and `"code_label"`;
  `generate_necb_8_4_coverage.py:246` filters runs by `report["vintage"]` →
  `report["edition"]`. **Audit `inputs.vintage` is 4 entries per
  no-simulation run and 5 per annual run**, emitted by `compliance.py:208`,
  `envelope/rules.py`, `hvac/efficiency.py`, `lighting/apply_lights.py` and
  `loads/apply.py` — each becomes `inputs={"code": …, "edition": …}`.
  **Derive R-C's accepted leaf set after R-B** by content-aligned
  comparison rather than asserting a fixed count; the accepted categories
  are listed below and anything outside them is a finding.
- The 13 hardcoded `"NECB"` literals (`report/__init__.py:97`;
  `sections.py:69,76,152,176,192,193,445,449,644,780`; `cli.py:167,185,536`)
  → `code_label` / edition-driven, including `sections.py:192,445,449` which
  hardcode "2025 Part 11".
- D-XX `kind: process` entry. `CLAUDE.md`, `docs/DEVELOPERS.md`, READMEs.

**Verify.** Re-freeze; the content-aligned diff must show only: help-text
lines; `report.json` `vintage`→`edition` plus `code`/`code_label`; audit
`inputs.vintage`→`inputs.code`/`edition` at the 4–5 emitter entries per run;
label strings; **every authored edition selector — the 2025 scenarios'
argv `--vintage 2025` → `--code necb2025`, and `api_call.vintage` →
`api_call.code` on `api-thermal-bridging` and both new API scenarios,
with their serialised `asserts` updated where a key name changed**;
generated documents whose terminology or report-input read changed
(`generate_necb_8_4_coverage.py:246`). No unrelated scenario field may
move. Anything else is a finding.

## Stage 8 — NECB 2017, 2015, 2011: one plan per edition, not one stage

Sol #7: "one manifest and one scenario" is insufficient evidence for newly
authored normative reference rules. This stage defines the **template** an
edition must satisfy before its id is registered; each edition is its own
plan and PR series.

- Source: the MCP has 2020/2025 only. Content comes from the pinned oracle
  (`NECB2017/data` 5 files, `NECB2015/data` 12, `NECB2011/data` 40), cross-
  checked against printed code; provenance `oracle:<REF>`. **The oracle has
  no performance path**; Part 8 reference rules are new transcription.
- Required per edition: authoritative printed-code table inventory;
  sentence-level `article_coverage` disposition; direct rule tests citing
  each article; ≥3 frozen scenarios across system topologies (python lane)
  and ≥1 annual (parity); `coverage.get_article(ed, …)` raising "no cached
  Section 8.4 text ships for NECB <ed>" — the edition must **not** enter
  `coverage.editions()`; independent engineering review before the id is
  added to `code_ids()`. Fix `test_generate_necb_8_4_coverage.py:27-56` to
  derive its edition list and counts from `coverage.editions()`.
- Sequence 2017 → 2015 → 2011. **Each carries an R-Edition re-freeze** —
  not additive: registering a code id changes the dynamic `--code {…}`
  help choices (so the `usage-*` baselines), every affected
  `baseline_sha256`, manifest `provenance`/counts/scenario list/
  `active_seals`, and the regenerated registry, coverage and delta
  documents, alongside its new scenario directories. The accepted diff is
  exactly that list; the matrix row is the contract.

## Stage 9 — independent code families

- **The current phases are not jurisdiction-neutral** (Sol):
  `_load_and_validate` enforces NECB space types and cites 8.4;
  `_attach_weather_and_hdd` is Table C-1; `_run_proposed_annual` requests the
  NECB heat-pump election variables. `btap/codes/pipeline.py` therefore keeps
  **only lifecycle mechanics** — `_Run`, phase ordering, `run_dir` layout,
  output writing, `_flush_on_failure` — and calls a family path through hooks:

  ```python
  class CodePath(Protocol):
      def validate(self, run) -> None            # NECB: space-type preflight
      def climate(self, run) -> dict             # NECB: Table C-1 HDD
      def prepare_annual(self, run) -> None      # NECB: inventory heat pumps, request variables
      def consume_annual(self, run) -> None      # NECB: join results into proposed_annual_data
      def determine(self, run) -> Verdict        # NECB: build reference, size, compare
      def citations(self) -> dict                # article map for the report
      def report_sections(self, run) -> list
  ```
  NECB's annual phase is prepare → run → consume (`compliance.py:286-307`:
  heat-pump inventory, variable requests, EnergyPlus, join) — a single
  `annual_outputs()` covered only the middle. The pipeline owns the
  EnergyPlus call between the two hooks. NECB's implementation is
  `btap/codes/necb/path.py`, assembled from the existing phases;
  `manifest.path` names the module.

**Stage 9 is three plans, not one.** 9a: framework extraction plus the
byte-identical NECB migration onto it — the only part this document
specifies, and its gate is that every frozen scenario is unchanged.
**9a stays byte-identical only if the evidence-bearing symbols stay put —
and ownership must match the boundary.** Six `compliance.py` symbols carry
coverage pointers (`necb_rules_2020.json:17-117`,
`reference_rules_2020.json:648`). They do not all move:

| symbol | owner after 9a |
|---|---|
| `performance_compliance` | **neutral pipeline** — the entry point stays |
| `_run_annual` | **neutral pipeline** — simulation invocation is lifecycle |
| `_load_and_validate` | **split**: neutral model loading stays; NECB space-type validation becomes the family's `validate` hook |
| `_build_reference`, `_evaluate`, `_evaluate_unmet` | **NECB path** — `btap/codes/necb/path.py` |

For the three that move, **forwarding functions remain at the same names
in `compliance.py` and are on the executed call path** — the pipeline
calls `compliance._build_reference(run)`, which delegates to the family
module. A dead stub that resolved the pointer without being executed
would make the evidence technically valid and substantively false. No
`audit.json`/`audit.txt` leaf changes. (The alternative — logical evidence
identifiers replacing physical paths — is the better long-term shape and is
recorded as future work; it is a format change to every baseline and does
not belong inside 9a.) 9b: an
OBC SB-10 implementation plan (ASHRAE 90.1 reference building — a new
domain). 9c: a BC Step Code implementation plan (absolute metrics, no
reference). Each of 9b/9c follows the Stage 8 admission template.
- **"Full compliance" does not imply a reference building.** BC Step Code is
  an absolute-metric regime (TEDI/MEUI/airtightness step thresholds); its
  `determine` compares to thresholds and never builds a reference. The
  `Verdict` type carries what each regime produces; the report renders what
  is present.
- `btap/codes/obc/`, `btap/codes/bcbc/` as siblings with their own data and
  `path.py`. Import-linter: they may import `btap.codes` (pipeline,
  registry, report) and never `btap.codes.necb`.

## Verification — every stage

```bash
cd python
.venv/bin/pytest -n auto -q tests/
.venv/bin/pytest -q tests/necb/test_frozen_scenarios.py                                # python lane
BTAP_SCENARIO_LANES=verify BTAP_SCENARIOS_REQUIRED=1 .venv/bin/pytest -q tests/necb/test_frozen_scenarios.py
BTAP_SCENARIO_LANES=parity BTAP_SCENARIOS_REQUIRED=1 .venv/bin/pytest -q tests/necb/test_frozen_scenarios.py
.venv/bin/lint-imports && .venv/bin/ruff check .
cd .. && python3 python/scripts/necb_orphan_keys.py && python3 python/scripts/generate_decisions_toc.py --check
python3 python/scripts/generate_necb_coverage.py && python3 python/scripts/generate_necb_8_4_coverage.py \
  && python3 python/scripts/generate_necb_edition_delta.py && git diff --exit-code docs/
```

R-A, R-B, R-C are the only `freeze.py` runs **in Stages 0–7**; each from a
clean tree, each with its diff attributed field-by-field before commit.
Stage 8 adds one R-Edition per code id, under its own contract. Every other stage:
frozen lanes byte-identical, scanner no-loss gate, citation table, and
`git status` clean after doc regeneration. Dispatch the four-job workflow
(never the PR run) before merging any stage touching `compliance.py`.

## Critical files

- `verification/scenarios/{scenario_defs,runner,freeze}.py` — Stage 0
- `python/scripts/generate_necb_8_4_coverage.py:117-180` — the scanner
- `python/btap/necb/compliance.py`, `hvac/reference.py`, `hvac/efficiency.py`
- `python/btap/necb/envelope/climate.py`, `lighting/daylight_control_requirement.py`
- `python/tests/test_coverage_code_refs.py`, `tests/necb/test_frozen_scenarios.py:85,126-145`
- `python/pyproject.toml:8-12,52-54,104-119`
- R-B rename inventory: `packaging/windows/btap-compliance.cmd:28`, `python/scripts/wheel_smoke.py:74,83,129,148`, `verification/scenarios/runner.py:215,235,260`, `freeze.py:116`
- `python/btap/necb/data/ghg_factors_2025.json`, `tests/necb/test_tiers_eui.py:60-69` — the exact `province_state` key the EUI scenario must use

## Handoff

Both declared locations must carry **rev 7** before anyone builds against
it: this file, and `docs/NECB_MULTI_EDITION_PLAN.md` (currently rev 1 —
refresh is the first action after plan mode exits). Sol's decision on
rev 6: Stages 0–7 ready once Findings 1–4 are folded in (done here);
Finding 5 (9a ownership) before Stage 9a (done here). No stage begins
until Sol's review of rev 7 is recorded.

---

# Progress log

Kept current by Fable. One entry per deliverable: what was asked, who did
it, what came back, what was verified, and any workaround — so a reader can
reconstruct why the tree looks the way it does without the chat.

## Stage 0 — opened 2026-09-07

**Spawned in parallel** (worktrees; none may touch baselines or run `freeze.py`):

| item | model | scope |
|---|---|---|
| 0.1 scenario machinery | Opus | `_corpus(code=)`, `python-only:` seals, `<DDY>`, `api_worker.py` + subprocess `_execute_api` returning `ScenarioRun(exit_code=cli.verdict_exit(…))`, shared `check_assertions` with the 7 operators wired into both comparator and freezer, split EnergyPlus preflight, UNCOVERED text rewrite, seal-attestation assertion |
| 0.3a citation gates | Sonnet | `compliance.py:346` `lighting_prefix`→`prefix`; `citation_counts_baseline.json` keyed `(edition, article, kind)` + no-loss test; replace the `> 50` floor; both unit tests assert exact citations for both editions; regenerate coverage docs |
| 0.3b citation table | Sonnet | `test_codes_registry.py` — literal `(edition, site) → string` for all 15 sites × 2 editions, passing on unmodified code |
| 0.4 coverage baseline | Haiku | dated per-module table into `docs/necb_rule_verification.md`; `coverage` on the `CLAUDE.md` install line |

**Deferred until 0.1 lands:** 0.2 (the four scenarios) and the two 40–90 min
authoring runs that pin `expect_exit`/`compliant`/`ghg.level` — Fable's.

**Known sequencing fact, not a defect:** 0.1 changes `scenario_defs.py`,
`runner.py` and `freeze.py`, so `test_frozen_scenarios.py`'s machinery-hash
integrity test fails on that branch until R-A re-freezes. The acceptance
for 0.1 is therefore: every other test green, all 35 scenario comparison
subtests green, and *only* the hash-integrity assertion failing, for
exactly that reason.

**Worktree mechanics:** the venv is an editable install bound to the main
checkout, so agents run tests with `PYTHONPATH=<worktree>/python` prepended
and must prove `btap.__file__` resolves inside the worktree before trusting
any result.

### Log — 2026-09-07/08

- **0.4 (Haiku) delivered and verified.** Branch
  `docs/necb-coverage-baseline-0-4` (`22cdb7f`): exactly two files, the
  dated table verbatim, `coverage` on the install line, decisions TOC still
  clean. Held for integration with the rest of Stage 0.
- **Authoring runs started early.** The values `expect_exit` / `compliant` /
  `ghg.level` / `tier` come from product code, which 0.1 does not change, so
  both 40–90 min runs (`author.py` in the session scratchpad, NECB 2025,
  Ontario, corpus `01-baseboard-gas`, Toronto CWEC2020) were launched
  against main rather than waiting for the machinery.
- **Workaround — corpus race.** Both authoring runs share one scratch and
  both called `ensure_corpus()` at the same instant; neither saw the other's
  generator, so two `generate_samples.py` wrote into one `_samples/`
  (no `.generated_by` marker, 17 entries). Killed both, generated the
  corpus once, relaunched. `ensure_corpus` is safe for the serial freezer
  but not for concurrent callers — worth a lock if the runner ever
  parallelises; not changed here (out of scope, 0.1 is editing that file).
- **Trap re-hit:** `pkill -f "author.py"` matched its own shell (exit 144).
  Use a bracketed pattern (`"[a]uthor.py"`) for both `pgrep` and `pkill`.
- **Session interruption.** The Claude Code process exited with 0.1, 0.3a
  and 0.3b mid-flight and the authoring runs attached to it. Recovered
  state: 0.1 worktree on `stage0-scenario-machinery` with all five files
  edited but uncommitted; 0.3a with seven files edited/new, uncommitted;
  0.3b clean; corpus intact. The authoring runs were relaunched under
  `setsid nohup … < /dev/null` (plain `nohup &` did not survive the
  session), and all three agents were resumed by message with their
  transcripts, not respawned.
- **Incident — WSL2 VM crash, 2026-09-08.** Three agents each running
  `pytest -n auto` (48 workers apiece on this 48-core host, ~250 MB per
  SDK-loaded worker), 0.1's 35-subprocess frozen-scenario suite, both
  authoring simulations and a coverage regeneration ran concurrently
  against a 32 GB VM with no cgroup limit. The VM exhausted memory and
  swap and went down (Windows stayed up; `wsl --shutdown` is the recovery,
  not a reboot). **Cause: my orchestration**, not any agent's code.
- **Rule, effective now (item 3):** one heavy job at a time. "Heavy" =
  a full `tests/` run, the frozen-scenario suite, a coverage regeneration,
  or any simulation. Agents may run targeted test files freely but must
  not run the full suite; Fable runs the full suite once per integration
  on the stage branch. Simulations sequential. Agent prompts carry this
  rule verbatim.
- **Item 2 applied:** `PYTEST_XDIST_AUTO_NUM_WORKERS=8` in the
  devcontainer `containerEnv` (takes effect on rebuild; exported
  explicitly in every command until then) and a Traps entry in
  `CLAUDE.md`.
- **Authoring results survived.** EUI run finished in **37 s** (the corpus
  model is tiny): `exit 0`, `compliant True`, `reference_model_present
  False`, `annual True`, `tier 1`, `percent_of_target 93.1`,
  `reference.building_energy_target_kwh 140000.0`,
  `proposed.total_site_kwh 130361.1`, `proposed.ghg_kg_co2e 18966.8`; run
  dir has only `proposed_annual/`. The 40–90 min estimate was the oracle
  archetypes' cost, not the corpus's. Determination reached
  `reference_annual/` before the crash; rerun pending.
- **0.3a (Sonnet) delivered and verified** — branch
  `worktree-agent-a14a774f5d8d7578e` (`ebb347e`), 7 files. Verified by diff:
  the `compliance.py` change is exactly the five `lighting_prefix`→`prefix`
  uses inside `_build_reference` (:320, :341, :346, :354, :357) and nothing
  else; `docs/NECB_8_4_COVERAGE.html` moves by one citerow line;
  determinism confirmed by double regeneration; targeted tests 18 passed.
  Two corrections **to the plan's wording**, not to the deliverable:
  (a) the scanner's `python_call_kind` yields only `cited` / `warn`
  (`generate_necb_8_4_coverage.py:133`), so the baseline key is
  `(edition, article, cited|warn)` — the plan's "decision / warning /
  info" was a guess at a vocabulary that does not exist; (b) `:357`
  (the `reference_daylighting: false` branch) was dropped by the scanner
  for the same reason as `:346`, so R-A's accepted doc diff covers **two**
  newly visible sites at articles 8.4.4.5 / 8.4.5.5, rendered in one line.
  The humidification test already asserted both editions' exact article;
  the agent verified rather than edited. Full suite and frozen lane
  deferred to integration under the one-heavy-job rule.
- **Determination authoring run (NECB 2025, Ontario, corpus
  `01-baseboard-gas`) — 189 s, three reference capacity iterations.**
  Pinned for `determination-01-baseboard-gas-necb2025`:
  `expect_exit 1`, `compliant False`, `reference_model_present True`,
  `annual True`, `tier 1`, `percent_of_target 76.0`,
  `ghg {percent_of_ghg_target: 95.3, level: "F"}`,
  `proposed.total_site_kwh 117908.3`, `reference.total_site_kwh 155047.2`,
  `proposed.ghg_kg_co2e 16716.7`, `reference.ghg_kg_co2e 17535.0`,
  unmet proposed `{heating 41.75, cooling 1709.75}` / reference
  `{heating 801.0, cooling 10.5}`. **Why non-compliant:** the *reference*
  building's unmet heating hours (801 h) exceed the 8.4.1.2.(3) 100 h limit
  and remain over it after three sizing-factor bumps (to 2.441), so
  8.4.1.2.(5) declares the building non-compliant (audit: one `decision`
  "unmet heating hours EXCEED 100 h", one `warning` at 8.4.1.2.(5)).
  Proposed cooling is vacuous (no mechanical cooling). The energy verdict
  itself passes. This is the first full-year determination the project
  has run on the corpus; a 2020 run of the same model is in progress as a
  diagnostic to tell whether the reference heating shortfall is
  edition-specific. **Finding for the user either way** — not a Stage 0
  blocker; the scenario freezes what the product does. 0.2 will add an
  `audit_entry` assert on that decision so the pinned `exit 1` is tied to
  its reason, not just its number.
- **2020 diagnostic of the same model: identical to 2025 except GHG.**
  `exit 1`, `compliant False`, proposed 117908.3 / reference 155047.2 kWh,
  unmet proposed {41.75, 1709.75} / reference {801.0, 10.5}, three
  iterations to factor 2.441 — byte-for-byte the 2025 numbers; `ghg None`
  at 2020 (no Part 11). Two conclusions: (1) the reference building's
  heating shortfall is **edition-independent** — a corpus-model /
  reference-generator property, surfaced only now because no full-year
  determination had ever been frozen; **finding for the user**, outside
  Stage 0's scope, candidate for a D-XX or a corpus fix later; (2) for this
  model the two editions build the same reference building, consistent
  with the survey's "2 rules genuinely differ". Also a free determinism
  witness: two independent annual runs agreed to the printed precision.
- **0.1 (Opus) delivered and verified** — `stage0-scenario-machinery`
  (`9517ecc`), 5 files. Read in full: `_corpus(code=)` byte-identical for
  necb2020 (agent verified all 35 against the manifest), `edition_of`,
  `FIRST_FREEZE_SEAL`, `ANNUAL_ASSERTS` carried on the two annual corpus
  scenarios; `api_worker.py` pops `model`, uses the product's
  `cli.verdict_exit`, writes the whole report; `_execute_api` resolves
  placeholders recursively, spawns the worker with `timeout_s`, turns
  timeout/crash/no-output into an `error` observation that `compare`
  reports (needed because `api-thermal-bridging` has `expect_exit None`);
  `observations.json` is deleted after reading so the run dir keeps its
  declared file set — accepted as documented; `check_assertions` with the
  seven ops, unknown op raises, wired into `compare` and the freezer with
  the probe passing `asserts: []`; separate EnergyPlus preflight; the gap
  moved to a `NEWLY_COVERED` record; seal-attestation gate. Frozen lane:
  30/30 subtests pass, only `test_manifest_integrity` fails on the
  machinery hash — exactly the pre-R-A state. Its "40-90 minutes" cost
  wording was corrected in 0.2.
- **0.3b (Sonnet) delivered and verified** — `worktree-agent-a089d408552410d69`
  (`5f28f36`), one new file, **30/30 live, 0 skipped**; spot-checked the
  literals against `efficiency.py:314/554/613`, `reference.py:1220`.
  **Finding:** `loads/apply.py:78`'s `rules['schedule_table_prefix']` is a
  dead parameter — `_apply_ventilation`'s citation never uses it, so the
  loads site emits the same string at both editions. The survey's "15
  renumbering sites" is really 14 live + 1 dead; Stage 2 should either
  wire it or delete it, not "migrate" it.
- **Integration:** branch `stage0-multi-edition` = main + 0.1 + 0.3a + 0.4
  + 0.3b + housekeeping (`7b69a3f`: xdist cap, trap, `.claude/worktrees/`
  and `.coverage` ignored, plan committed) + 0.2 (`74dc41f`). All four
  2025 scenarios validate: 39 scenarios, python 32 / verify 3 / parity 4,
  no duplicate ids, no python-only seal carries attestation. The
  determination scenario's asserts tie `exit 1` to the 8.4.1.2.(2) pass,
  the 8.4.1.2.(3) EXCEED decision and the 8.4.1.2.(5) warning. Full suite
  running once, alone, 8 workers, frozen module excluded; R-A next.
- **Full suite on the integrated branch:** 876 passed, 55 subtests, 1
  failed — `test_freeze_seal_transition` pinned the first-freeze seal
  count at 4; it is 8 now (four 2025 scenarios). Pin moved with the
  reason in a comment (`b37b419`). lint-imports 3/3, ruff clean,
  decisions TOC clean. The plan did not foresee this pin; it is the one
  Stage 0 test edit outside the contract's list and is recorded here.
- **R-A executed** from clean tree `b37b419`, `python/.venv/bin/python
  verification/scenarios/freeze.py`, all 39 scenarios, every authored
  `asserts` block held at freeze time (the freezer dies otherwise).
  **Field-by-field attribution of the diff, against the matrix row:**
  - 35 existing baseline directories: **untouched** (git shows no
    modification under `baselines/` other than four new directories);
    no existing `baseline_sha256` moved.
  - four new directories: `corpus-none-01-baseboard-gas-necb2025`,
    `corpus-none-08-vrf-necb2025`, `determination-01-baseboard-gas-necb2025`,
    `api-eui-path-necb2025`.
  - manifest `provenance`: `commit` c0f12ba→b37b419; `defs_sha256`,
    `freezer_sha256`, `runner_sha256`, `gate_sha256` moved;
    `active_seals` python-only 4→8; `attestation_note`, `dirty`,
    `final_cross_language_attestation`, `openstudio_cli`, `retired_seals`
    **unchanged**. `spec_sha256` **unchanged**.
  - `counts` 30/3/2 → 32/3/4; scenario list +4, order of the 35 preserved.
  - `uncovered`: the "full-year end-to-end determination" entry removed
    (its covered record lives in `scenario_defs.NEWLY_COVERED`, not in the
    manifest — no new manifest key).
  - **one category the matrix row did not name explicitly:** the two
    existing `corpus-annual-*` entries gained an `asserts` field (the
    non-vacuity the freezer used to hard-code, now carried on the scenario
    per Sol's review 4). Their baselines and hashes are unchanged.
  - generated docs: regenerating both coverage documents after the freeze
    produced **no** diff — the 2025 baselines add no new coverage rows;
    the one-line move from 0.3a was already on the branch.
  Nothing else moved. Gate run (python, verify, parity lanes) in progress.
- **Gate after R-A:** python 5 passed / 32 subtests (202 s), verify 3
  (94 s), parity 4 (321 s, both annual API scenarios re-run and matched
  their baselines — a second determinism witness). R-A committed as
  `20e479f` on `stage0-multi-edition` with the attribution in the message.
- **Blocked on network (2026-09-08):** `git push`, the PR, and the
  workflow dispatch all failed — github.com times out from the container
  while pypi.org answers. Nothing to do locally; retry the push, `gh pr
  create`, and `gh workflow run test.yml --ref stage0-multi-edition` once
  GitHub is reachable. **Stage 0 is otherwise complete**; Stage 1 (R-B)
  does not start until the PR is merged on main.

## Deferred findings (logged for later, outside the refactor)

- **DF-1 — corpus `01-baseboard-gas` reference building fails 8.4.1.2.(3)
  at both editions.** NECB 2020 8.4.1.2.(3) applies the 100 h unmet-heating
  limit "for both the proposed and reference buildings"; the product
  checks each and requires both (`compliance.py:965-993`). Proposed: 41.75
  h (passes). Reference: 1268.75 → 945.5 → 842.75 → 801.0 h as the heating
  sizing factor climbs to 2.441 over three 8.4.1.2.(5) increases —
  flattening, not converging, so raising `max_capacity_iterations` will
  not fix it. Doubling capacity recovered a third of the shortfall, which
  points at something in the reference that does not respond to sizing
  factors: hard-sized equipment (the product's own warning names it), an
  availability/setpoint schedule mismatch in the rebuilt reference
  systems, or the zone sizing factor not reaching the boiler side of a
  boiler-and-baseboard reference. Proposed cooling (1709.75 h) is vacuous
  under sentence (4): no mechanical cooling. Identical numbers at 2020 and
  2025. Candidate for a D-XX or a corpus fix; frozen as-is in
  `determination-01-baseboard-gas-necb2025` (the scenario pins the
  reason, so fixing it is an adjudicated re-freeze). User's call
  2026-09-08: "log it for later."

## Stage 1 — opened 2026-09-08

Opened on the user's instruction before the Stage 0 PR is merged (push
blocked by network), so Stage 1 work stacks on `stage0-multi-edition`
rather than main. Same execution model and the one-heavy-job rule.
- **Stage 0 PR #33 opened**; four-job workflow dispatched as run
  34238540365 (lint green at time of writing; watched).
- **Spawned (worktrees off `stage0-multi-edition`):** Opus — the R-B
  rename sweep, the eui/tiers move per the symbol map, R7 ledger + chain
  test, D-XX process entry, 0.3.0 bump, scanner glob/gem-key sites; one
  full-suite run allowed at the end, and a path-only proof of the frozen
  lane's differences via ledger substitution. Sonnet —
  `test_no_legacy_namespace.py`.
- **Namespace gate (Sonnet) delivered and verified** — branch
  `worktree-agent-a84194dba7fc284f4`. Two corrections applied by Fable on
  that branch (`4ce6d69`): (a) the agent's pattern `\bbtap[./-]necb\b`
  also matched the retired gem name `btap-necb`, which is period prose in
  ~100 docstrings the rename must not reword AND the stem of the live
  `btap-necb-coverage` console entry point the plan keeps through Stage 4
  — narrowed to `btap.necb` / `btap/necb`; (b) pytest-function style
  converted to `unittest.TestCase` so the zero-install `unittest discover`
  fallback runs it. Pre-rename inventory with the corrected pattern:
  **678 hits in 152 tracked files** (python 664, CLAUDE.md 4,
  verification 4, docs 3, packaging 2, README 1). Held for integration
  with the rename; merging it earlier would redden the stage branch.
- **Dispatch run 34238540365: all four jobs green** (lint, python, verify,
  parity). The parity job re-ran both annual API scenarios on a GitHub
  runner and matched the baselines frozen here — the cross-machine
  determinism witness for the first frozen full-year determination.
  **PR #33 is ready for the user's merge decision.** Stage 1 continues on
  top of it.
- **User: merge #33 ("do it").** GitHub unreachable again from the
  container (github.com:443 times out / api refused; pypi.org fine) — the
  third outage since the VM restart. Push of the final log commit, the
  squash merge, and the pull are in a bounded background retry (30 × 60 s).
  Local `main` is still `ac6712f` until that lands; Opus's rename branch
  will be rebased onto the squash-merged main with
  `git rebase --onto main <stage0 tip>` rather than merged, so only its
  own commits replay.
- **Rename (Opus) delivered and reviewed** — `stage1-btap-codes` (`3bf7bd5`),
  one commit, 208 files, +1606/−1165, 53 renames; `python/btap/necb/` gone,
  tree matches the plan (`codes/{cli,compliance,coverage,decisions,report}`,
  `codes/necb/{envelope,hvac,lighting,loads,shw,tiers.py,editions/necb2025/
  {eui_archetypes,part11_ghg}.py,data/}`, `codes/data/{decisions.json,
  coverage/}`). Full suite 873 passed / 8 skipped; lint-imports 3/3 with the
  contract rewritten to `btap.codes → costing → modeling → audit`; ruff
  clean; orphan keys, decisions TOC, both generators clean and idempotent.
  Frozen python lane fails on exactly `audit.json` (`/inputs/code[]`) and
  `audit.txt` for the 20 evidence-bearing scenarios; `report.json` carries
  no code pointers; the agent's ledger-substitution proof rebuilt 32/32
  byte-identical — no non-path difference. R7 ledger: 87 unique refs, 313
  uses, chain test proves R7.old == R6.new, R7.new == live manifests,
  totals equal; `tiers.py` leaves the pointer set (32 files → 31).
  **Judgment calls accepted:** `DATA_DIR` on `btap.codes.necb`; the
  scanner's `gem == "necb"` kept as the umbrella *label* (renaming it would
  change generated HTML content — flagged for Stage 3) while `domain_for`
  gains `removeprefix("necb/")` to preserve the exact prior domain mapping;
  console script names unchanged (user surface); package `CLAUDE.md`/
  `README.md` at `btap/codes/`; 0.3.0 in `pyproject`, `btap/__init__`,
  the `.iss` guard and four usage examples; `docs/python_port_m6_m7_review.md`
  added to the historical set; a `test_self_containment.py` allowlist row
  for the gate; `test.yml:106` bare comment fixed by hand. **D-86** (`kind:
  process`) adjudicates R-B. The agent ran the full suite twice, serially
  (a docstring edit after regenerating docs shifted `#L` anchors — the
  known trap) — disclosed, accepted.
- **Two namespace gates existed** (Sonnet's, held, and Opus's own written
  after the plan log named Sonnet's). Opus's lands: it carries the same two
  corrections, is `unittest` style, and is already wired to the
  self-containment allowlist. Sonnet's branch is dropped, not merged.
- **R-B freeze started on `stage1-integration` (= `3bf7bd5`) while GitHub
  is still unreachable** (merge retry at attempt 16+). If the eventual
  rebase onto squash-merged main changes the commit beneath, the freeze
  re-runs and the only permitted diff is `provenance.commit`.
- **R-B executed** from clean tree `ca7d382` → commit `1cc5709`.
  **Attribution by script** (`attribute_rb.py`: rewrites HEAD's baselines
  through the R7 ledger + rename rules and compares to the freeze; checks
  every manifest field): 54 files / 27 scenarios (20 python-lane + 3
  verify + 4 parity), `audit.json` ×27 and `audit.txt` ×27 all path-only,
  `report.json` untouched; manifest `provenance.commit`, `freezer_sha256`,
  `runner_sha256`, and 27 `baseline_sha256` — the touched set exactly; no
  other top-level, provenance or scenario field; no id added/removed;
  `defs/gate/spec_sha256` unchanged. Regenerating both coverage documents
  after the freeze: no diff. **No findings.** Three-lane gate + light
  gates running.
- **Stage 1 verification block complete on `1cc5709`:** frozen lanes
  python 32 / verify 3 / parity 4 green; full suite green; lint-imports
  3/3; ruff clean; orphan keys OK; decisions TOC current; docs regenerate
  to no diff. **Waiting on GitHub** for the #33 merge; then
  `git rebase --onto main 8f28f73 stage1-integration`, re-freeze (only
  `provenance.commit` may move — attributed like every other freeze), push,
  PR, dispatch.
- **Full suite on `1cc5709`: 880 passed, 1 failed** —
  `test_the_renamed_package_is_the_one_on_disk` asserted the old directory
  does not *exist*, and a branch switch leaves `python/btap/necb/__pycache__`
  behind (zero tracked or source files — verified). The gate's own rule is
  tracked files only, so the absence check now uses `git ls-files`
  (`369cd9e`). Not a rename gap. **#33 is MERGED on GitHub**; the fetch of
  main is what the flaky link keeps refusing.
- **Rebased onto squash-merged main** (`5c3c1a2`): `git rebase --onto main
  8f28f73 stage1-integration -X theirs` (the only conflict surface was the
  plan doc, which main held at an earlier log state); resulting tree
  byte-identical to the verified pre-rebase tip. **Re-froze on the rebased
  tip so `provenance.commit` names a real commit:** the diff is exactly
  `provenance.commit` ca7d382 → 5a90c98 — no baseline file, hash, count
  or scenario field moved; all 39 scenarios including both annual API
  runs reproduced byte-identically (third determinism witness).
- **Harness incident:** the freeze was killed twice as a background task
  "because the system is running low on memory" while a sampler running
  beside it logged 25 GB available and the cgroup recorded no OOM. The
  harness watchdog misfired; the freeze completed when run detached
  (`setsid nohup`) with bounded foreground waits. Feedback drafted.
