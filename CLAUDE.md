# CLAUDE.md — canmet-btap repository guide

This repository contains one product implementation: the Python distribution
`canmet-btap` (import `btap`), licensed **GPL-3.0-or-later**. It has five
subpackages: `btap.audit`, `btap.simulation`, `btap.modeling`, `btap.costing`,
and `btap.codes`. `btap.codes` is the code-compliance layer, with the NECB
family under `btap.codes.necb` (D-86 renamed and re-shaped that package at
Stage 1 of the multi-edition plan; the old namespace is gone, and
`python/tests/test_no_legacy_namespace.py` keeps it gone). The former
`btap-*` Ruby gems retired at R6 under D-84.

Ruby still has one deliberate role. `legacy_pin/` bundles the pinned
`openstudio-standards` revision, and the Ruby files in `verification/oracle/`
probe that external oracle. They are verification infrastructure, not product
code. Do not translate their Ruby mechanically or delete them as "leftover"
product Ruby.

[README.md](README.md) is for building engineers. Contributor setup and test
lanes live in [docs/DEVELOPERS.md](docs/DEVELOPERS.md). `PORT_STATUS.md` and the
audit/decision documents are historical records; keep their period wording
unless a moved link itself is wrong.

## Package contract

- **Pure OpenStudio SDK.** Product code does not depend on
  `openstudio-standards`, measures, or legacy BTAP.
- **One distribution, five subpackages.** Dependency direction is
  `btap.codes` → `btap.costing` → `btap.modeling` → `btap.audit`, with
  `btap.simulation` beside and depending only on audit. Import-linter enforces
  this D-77 contract.
- **Code families live under `btap.codes`; data lives by EDITION.**
  `btap.codes.necb` holds the five NECB rule domains and
  `btap/codes/necb/editions/necb2025/` for what exists in one edition only.
  Every edition is an independent, complete snapshot under
  `btap/codes/necb/data/<code id>/` (rule files, `tables/`,
  `coverage/articles_8_4.json`, the bounded structural
  `coverage/provisions.json`, and the `manifest.json` that drives discovery).
  Authorized raw provision payloads stay in that edition's `provenance/`;
  runtime citation validation is offline. Nothing at runtime reads another
  edition's files — no `extends`, no alias, no fallback. Loaders resolve through
  `btap.codes.necb._data_root()`; `_set_data_root(..., _testing=True)` is a
  test-only hook, never an environment variable. Code-family-neutral data —
  `decisions.json`, the Section 8.4 disposition and `ATTRIBUTION.md` — stays
  in `btap/codes/data/`.
- **One AuditLog schema:**
  `{step, target, action, inputs, value, article, ruling, ahj, evidence, building, level}`.
  Levels are `decision`, `info`, and `warning`; warnings are never silent.
- **THREE citation axes** (D-100). `article` cites the code requirement;
  `ruling` cites the adjudicated D-XX interpretation; `ahj` cites the
  `docs/NECB_AHJ_QUESTIONS.md` disposition that applies to THIS runtime
  choice. Keep all three top-level, never nested in `inputs`.
  `ahj` means "this disposition applies here", NOT "approval is required":
  all four register statuses may be cited, and only `referral` and
  `alternative-solution` make a run conditional. `btap.audit` stores and
  renders the field and decides nothing about it — the status mapping lives in
  `btap.codes.ahj`, generated from the authored register. A static
  coverage-manifest entry may never carry `ahj`.
- **Audit text is case-sensitive.** Violations are SHOUTED and passes are
  lowercase because the report checklist classifier relies on that distinction.
- **One public selector: the code id.** `performance_compliance(model, *,
  code="necb2020", …)` and `btap-compliance --code necb2020` (D-87). Every
  public function takes `code=`; only the per-edition DATA accessors take
  `edition=` (`'2020'`). `vintage` is retired everywhere — argument,
  `report.json` (`edition` + `code` + `code_label`) and audit `inputs`
  (`code` + `edition`). An unregistered id raises `UnknownRuleset`.
- **NECB 2020 and 2025 only.** Do not imply support for 2011–2017.
- **Python is authoritative.** Behaviour changes are Python-only and require a
  clean-tree frozen-scenario re-freeze in the same change when outputs move.

## The input model is GATED, and the gate is fatal

A proposed model that lacks what NECB requires to build a reference is
REFUSED before simulation. It does not warn and continue. Three phase-1 gates
in `btap/codes/necb/path.py#validate` run before any transform; a fourth,
climate-dependent gate runs in phase 2b after HDD resolution but before model
preparation or sizing. All raise `compliance.PreflightError`, which the CLI
maps to `EXIT["preflight"] = 3`, and all stamp
`audit.with_building("input model")` so the trail shows the gate ran:

- **Structural absence** (`pipeline._validate_input_model`): no spaces, zones
  or surfaces. And **no thermostat anywhere**, which is the dangerous case
  precisely because it RUNS — every zone free-floats, equipment sizes to
  nothing, and the determination comes out numerically valid and physically
  meaningless. PARTIAL thermostat coverage only warns: storage and plenum
  zones legitimately float.
- **An undeterminable above-ground STOREY COUNT** (`require_storeys=True`).
  Determinable means declared on `Building`, derivable from `BuildingStorys`
  with above-grade spaces, or passed as `building={'storeys':}`. It is fatal
  because Table 8.4.4.7.-A's System 3-vs-6 split depends on it and the
  fallback would silently treat a tower as ONE storey.
- **Any floor-area SPACE TYPE that does not resolve** against the edition's
  catalog (`_validate_space_types`), reported with every offending type, its
  space count and the fix. It is fatal because the per-space-type transforms
  (lighting LPD, loads, SHW demand) skip unmatched types SILENTLY, so an
  unresolvable type yields a reference identical to the proposed for that
  space: the allowance is waived and the proposed is compared against itself.
  You cannot certify a building whose reference silently failed to build.
- **Any required exposed GROUND STRIP that cannot be represented**
  (`path.prepare_model`): after HDD selects the ordinary perimeter-strip
  branch, every applicable reference-envelope floor is inventoried before any
  floor is changed. A positive, missing or non-finite exposed perimeter
  without a usable Kiva representation is fatal because 8.4.1.1.(1)'s target
  would omit 3.2.3.3.(3)'s required strip. A finite measured zero is the only
  waiver. `--ground-model simple` is rejected on the same branch; full-area
  climates and floors outside the reference envelope are not.

**Do not plan around this gate as though it were missing.** A draft of
`docs/plans/PROPOSED_CHARACTERIZATION_PLAN.md` proposed adding the three
phase-1 checks and asked whether the tool should flag bad proposed inputs — a
question the architecture had already answered. Run an untagged archetype
through `btap-compliance` and read the exit code before concluding anything
about input validation.

The architecture that follows from it: **required inputs are fatal; everything
past the gate is DISCLOSURE.** The performance path does not check a proposed
assembly against a prescriptive maximum, because its verdict is the 8.4.1.2
energy comparison and assembly-by-assembly pass/fail is the prescriptive
path's job. So a characterization of the proposed records values and citations
and emits no verdict — but the tool still refuses to run without what it needs.

Relaxing any gate into a warning is an adjudicated change, not a convenience:
each exists because the silent-success path it replaces produced a
determination that looked valid.

## A proposed FATAL stops the run; a proposed SEVERE does not

phylroy's ruling (2026-10-21): **we cannot babysit people who have not done
their due diligence on the proposed building.** Reference creation is
responsible for creating a reference building, NOT for whether every aspect of
the proposed model is correct. A proposed model may fail in many ways, and
some Severe errors are acceptable. The reference code builds from what is
available. It stops only when the preflight gates above refuse, or when the
proposed does not simulate without a FATAL.

That is what the code already does, and the asymmetry is deliberate:

- a FATAL raises `RuntimeError` from the backend, which
  `pipeline._size_proposed` catches, SHOUTS as the input model's defect, and
  re-raises — `EXIT["simulation"] = 4`. Verified on
  `models/gagetown_coldlake_Barracks_pre-1960.osm`, whose surfaces carry no
  construction: *"the PROPOSED (input) model failed its sizing simulation —
  the input file is not simulate-able as given"*;
- a SEVERE does not stop anything, and nothing GATES on it.
  `runner.is_clean_run` IS called — `compliance.py#_run_annual` records its
  result as the `clean_run` field of each report section — but only on the
  ANNUAL path, and only as a reported fact. No sizing path calls it, a sizing
  report's `proposed`/`reference` sections are empty, and no code anywhere
  turns a Severe into a refusal.

**Do not read that as a defect to close.** It was raised as one in this
session — "`is_clean_run` has no caller in the pipeline", and separately
"arguably more valuable than either coil fix". The first is simply wrong, and
the second mistakes the policy for an oversight. Nor extend a reference-side
correction to the proposed model to silence a Severe there: D-106 marks fan
coils built FOR the reference, and marking the user's own coils would re-size
their submission, which is the babysitting this rule forbids.

The corollary for OUR OWN artifacts is the opposite. A sample we author and
ship should be clean, because shipping one with a known Severe teaches the
wrong thing. `scripts/simulate_all_systems.py` enforces exactly that for the
catalogue — `SEVERE_RE`, `is_clean()`, status `simulation_error`, and 102 of
102 systems currently `ok` with `severe: 0`. It gates the CATALOGUE on the
shared fixture, so a shipped sample model is a separate artifact and is NOT
covered by it: `packaging/windows/samples/04-fancoil-chiller.osm` and
`13-district-heating.osm` each carry one `Coil:Cooling:Water` UA Severe
(issue #68) that the catalogue gate never sees.

## Commands

```bash
cd python
python3 -m venv .venv
.venv/bin/pip install -e '.[tbd]' pytest pytest-xdist import-linter ruff build coverage pytest-cov
.venv/bin/pytest -n auto -q tests/
.venv/bin/lint-imports
.venv/bin/ruff check .

# Repository tools, from the repository root
python3 python/scripts/necb_orphan_keys.py
python3 python/scripts/generate_necb_coverage.py
python3 python/scripts/generate_necb_8_4_coverage.py
python3 python/scripts/generate_necb_edition_delta.py --check
python3 python/scripts/generate_necb_vintage_match.py --check
python3 python/scripts/generate_decisions.py --check
python3 python/scripts/legacy_whatsnew.py

# Authenticated maintainer refreshes; ordinary runtime and CI stay offline
python3 python/scripts/fetch_necb_provisions.py

# The HVAC catalogue sizing sweep (needs the SDK and EnergyPlus). It writes
# python/tests/fixtures/system_simulation_status.json, which GATES which
# catalogue systems ship as samples; --check re-derives it without writing.
python3 python/scripts/simulate_all_systems.py --check
```

The zero-install serial fallback is `cd python && python3 -m unittest discover
tests`. Full SDK, EnergyPlus, rasterizer, sample, and thermal-bridging coverage
runs in the `verify` CI job. Live oracle checks run only in `parity`.

## Decisions and coverage

One decision is one file: `docs/decisions/D-NN.md`, TOML front matter
(`id`, `title`, `kind`, `articles`, `editions`, `summary`) plus the authored
Markdown body,
whose first line is its own `## D-NN —` heading. That file is CANONICAL.
Three outputs are GENERATED from the sources by `generate_decisions.py` and are
never hand-edited: `docs/necb_decisions.md` and
`python/btap/codes/data/decisions.json`, in numeric id order, and
`docs/CODE_DECISIONS_BY_PROVISION.md`, the Codes Committee view by code,
edition and provision. Anchors and the index are inserted by the generator; by
convention a body does not declare its own `d-NN` anchor. The front-matter
`title` is the
compact index title and the body's heading is authored prose, which differ on
purpose. A `kind: runtime` entry must be cited by product Python source.

`editions` lists the CODE IDS a decision governs — `necb2020`, `necb2025`,
both comma-separated — or the single literal `unverified`. It is validated
against the editions DISCOVERED under `btap/codes/necb/data/`, so registering a
new edition does not leave the check stale, and it never takes a collective
word: "both" stops meaning anything once a third edition exists, and `vintage`
is retired vocabulary. `unverified` may not be mixed with a code id — either a
decision has been checked against that edition or it has not. Of the 106
decisions, 15 are `unverified`: they were authored before the field existed,
mostly against one edition's text, and asserting a list for them would be a
guess. That is a DECLARED gap where it used to be a silent one; establishing
them is open work, and the remaining count moves as decisions are checked —
re-read the registry rather than trusting this number.

`articles` groups citations by an AUTHORED REQUIREMENT IDENTITY, then by code
id inside it. A flat list was ambiguous — the same number can name a DIFFERENT
requirement in each edition (`8.4.5.9` is Heating System in NECB 2025 and
Fuel-Fired Service Water Heater in NECB 2020) — but per-edition nesting alone
was necessary and insufficient: it left correspondence to be INFERRED, and
inferring it from shared title vocabulary accepted "Service Water Heating
Systems" as 2025's counterpart to "Heating System" because both contain
"heating" (Sol, clearance review of `be2118d`). Semantic matching on
vocabulary cannot be made safe, so correspondence is authored:

```toml
[articles.multi_energy_heating]
label = "Multi-energy heating capacity allocation and operating priority"
necb2020 = ["8.4.4.9.(4)", "8.4.4.9.(5)", "8.4.4.9.(6)"]
necb2025 = ["8.4.5.9.(4)", "8.4.5.9.(5)", "8.4.5.9.(6)"]
```

The requirement key and its `label` ARE the cross-edition equivalence
assertion, so the generator checks structure instead of guessing meaning, and
PER REQUIREMENT rather than across the file — a global coverage check let one
requirement's missing edition hide behind another that listed it. Four rules:
a non-empty requirement KEY and label; every edition in `editions` present in
EVERY requirement; a citation that FULLMATCHES the grammar, so nothing rides
along before or after it; and that citation validated against the edition's
own snapshot to the depth the snapshot carries — the article, the sentence,
the clause scoped to ITS sentence, and a table's suffix. The `unverified`
holding key may not be mixed with authored requirements, `editions` may not
repeat a code id, and one requirement may not mix Section 8.4 citations with
uncheckable ones, within an edition or across them.

**Correspondence is NOT checked by numbering, deliberately.** An equal-suffix
rule was tried and refused a correct mapping: D-89's modulating-boiler
part-load requirement is `8.4.5.2.(3)` in NECB 2020 and `8.4.6.2.(2)` in NECB
2025, because the 2020 article has three sentences and the 2025 article has
two. Whether two citations are the same requirement is an authored assertion
carried by the key and label; a second correct citation and a wrong existing
one are not structurally distinguishable, and Sol ruled that case out of
scope rather than admitting another heuristic.

**The structured source form** is the migration target of
`docs/plans/DECISION_APPLICABILITY_PLAN.md`. The generator accepts it beside the
legacy form. Phase C converted all 23 decisions that carried an established
per-code-id mapping, and Phase D's seven batches established 42 held
decisions directly in this form (D-02, D-03, D-04, D-05, D-06, D-07, D-09,
D-11, D-12, D-13, D-14, D-15, D-17, D-18, D-19, D-21, D-22, D-23, D-24,
D-26, D-28, D-31, D-32, D-34, D-35, D-37, D-41, D-42, D-43, D-45, D-53,
D-55, D-58, D-59, D-60, D-61, D-62, D-63, D-65, D-74, D-76 and D-85; 68
structured in all), so no committed
decision still uses the
per-code-id lists above: every other decision holds `unverified` or
`not_applicable`.
`python/tests/necb/test_decisions_registry_sync.py` pins the converted ids and
each converted mapping, and fails if any other decision takes a per-code-id
mapping. A requirement keeps its
key and `label`, adds a committee-facing `decided` paraphrase, and carries one
`[[articles.<key>.sources]]` record per `code` family, `edition` STRING and
`role`:

```toml
[articles.heat_pump_reference_by_source]
label = "Reference system for a proposed heat pump, by heat source"
decided = "Water-loop and other heat pumps follow different reference-system selection branches."

[[articles.heat_pump_reference_by_source.sources]]
code = "necb"
edition = "2020"
role = "governing"
references = [
  "8.4.4.13.(1)",
  "Note A-8.4.4.13",
]
```

Only `governing` records establish applicability. Each one must name a
registered runtime edition, and every requirement of the decision must govern
the same editions; a decision that differs by edition is split, as in the
legacy form. The decision's `editions` is DERIVED from those records. Either
omit `editions`, or, during the transition, author exactly the derived list.

`incorporated-reference` and `related` records may name future editions and
other standards, but they never establish an edition.

NECB references in a registered edition must meet three conditions:

- they use the CANONICAL spelling, such as `Note A-8.4.4.13` or
  `Division A 1.1.1.1.(1)`;
- that edition's `coverage/provisions.json` records the provision as present;
- the recorded provision is of the cited kind.

An unregistered NECB edition is held to the citation grammar only. Any other
standard is carried as authored and is named on a `decisions: note` line.

A decision is converted whole: no structured requirement may sit beside a
legacy one or beside the reserved `unverified` or `not_applicable` key. A
requirement key shared by several decisions names ONE requirement in either
form, so it carries one label and the same governing citations everywhere.
Converting it means converting it in every decision that uses it, together.

`decisions.json` is schema 2. Its root `decisions` array keeps every entry's
`id`, `title`, `kind` and `summary`, which are all that `btap.codes.decisions`
and the report's rulings appendix read. A structured entry carries
`requirements` (`id`, `label`, `decided`, `sources`) instead of `articles`.
The loader refuses any other schema number.

**The Codes Committee view** is `docs/CODE_DECISIONS_BY_PROVISION.md`, the third
generated output. It answers a committee member who starts from a code, an
edition and a provision. A decision appears in it only if it cites a provision:
`not_applicable` and an empty `unverified` list are omitted and counted, never
listed. Its rows come from the decision's own requirements:

- a structured requirement makes one row per `governing` record, with its
  `decided` text. Same-family governing records of other editions appear under
  Other editions, and `incorporated-reference` and `related` records appear
  under Other sources. Neither ever makes a row;
- a legacy requirement with a citation list per code id makes one row per
  edition. It has no `decided` text yet, so the decision-wide `summary` stands
  in, marked **Transitional** and printed once per decision rather than on
  every row. No committed decision has taken this form since Phase C;
- a non-empty legacy `unverified` list appears only in the last section,
  "Edition not yet attributed", with its recorded citations. It is never placed
  under an edition.

Rows sort by code, edition, the row's first provision (division, then the
number read numerically, then Article before Table before Appendix note),
decision number and requirement key. The counts are computed from the sources
and never hardcoded, so a conversion moves a decision between sections without
a code change.

**The id grammar is `^D-\d+$`, unbounded.** `^D-\d{2}$` allowed exactly 100
ids and D-01 through D-99 all existed, so the registry had run out (D-100
through D-103 exist today); a fixed three
digits would only move the wall, and thousands are expected as other code
families arrive. Widening means FOUR patterns, and the one that matters most is
`btap/codes/decisions.py`'s `ID_PATTERN`: `\bD-\d{2}\b` does not match
`D-100`, so widening only the generator produces a decision whose citations are
invisible — no audit ruling resolves and it never reaches the report appendix.
The test files `test_decisions_registry*.py` carry the same grammar and must
move with it.

```bash
python3 python/scripts/generate_decisions.py        # regenerate all three outputs
python3 python/scripts/generate_decisions.py --check
cd python && python3 -m unittest \
  tests.necb.test_decisions_registry_sync \
  tests.necb.test_decisions_registry \
  tests.necb.test_decisions_generator
```

Coverage is declared at the depth the evidence supports. Match article ids by
prefix when a whole article can be split into sentence-level entries. Do not
split a uniformly implemented article merely to inflate coverage. Use
`gap_owner: "modeller"` only when no model change can satisfy the requirement.
Generated coverage documents live in `docs/`; regenerate both and review their
diffs rather than hand-editing them.

The Section 8.4 article caches live in each edition's snapshot at
`python/btap/codes/necb/data/necb<edition>/coverage/articles_8_4.json` and ship
in the wheel. Refresh them with `python3 python/scripts/fetch_necb_8_4_text.py`;
ordinary runtime remains offline.

The first decision-by-provision evidence slice lives beside them at
`coverage/provisions.json`. It is a normalized structural index only:
Articles, Sentences, Clauses, Tables, table notes, Appendix notes, and
explicitly qualified Division A provisions. Exact authorized hbix results are
retained at `provenance/provisions.result.json`; the index pins both that
archive and the reused Section 8.4 cache by hash. Refresh both editions with
`python3 python/scripts/fetch_necb_provisions.py`. An absent record is positive
authority evidence; a citation missing from the bounded cache is merely
`not-indexed`, and a source-hash mismatch is `stale`.

## Two references for any NECB behaviour

Implementing or verifying an NECB rule uses both of these, and they answer
different questions:

- **The hbix codes MCP is the normative text.** It answers what the Code
  requires: the article, a table's exact form, coefficients, thresholds,
  Appendix A notes, and the server's own errata (`known_issue` in a
  payload). In a session it is the `mcp__codes__*` tools; from a script it
  is `btap._mcp.MCPClient("codes")` with `HBIX_API_KEY` exported from `.env`
  (`set -a && source .env && set +a`; never print the key). It carries NECB
  2020 and 2025 only and exposes no revision id, so an archived canonical
  payload under an edition's `provenance/` is the retained artifact.
- **The pinned openstudio-standards gem is the legacy realisation.** It
  answers how the previous implementation put a requirement into
  EnergyPlus: curve conversions, reference-system construction, schedule
  sets, and what the oracle goldens were built from. `legacy_pin/REF` is
  the revision; `BUNDLE_GEMFILE=legacy_pin/Gemfile bundle install` checks
  it out under `vendor/bundle/`, and `bundle show openstudio-standards`
  locates it. **It may be wrong, and it is still useful.** It has already
  been caught shipping NECB 2015's Table C-1 as 2020's, the NECB 2011
  performance curves for every edition, stale BC heating-degree values, a
  zeroed Schedule I fan column, and the non-condensing part-load curve on
  every boiler row. Treat it as evidence of an approach, never as an
  authority.

Before designing or verifying a rule, fetch the governing article or
table from the MCP and read the gem's corresponding Ruby and data. Cite
both in the decision and the provenance entry. When they disagree, the
Code wins and the gem's version is recorded as a finding, not adopted;
`docs/NECB_VINTAGE_MATCH.md` is the pattern.

## Questions referred to an authority

`docs/NECB_AHJ_QUESTIONS.md` is the AUTHORED register of questions this tool
does not decide. NOT all of them are ambiguities, which is why the heading no
longer says "interpretations": two of the four statuses need no authority at
all. It is tracked, unlike `.reviews/`,
which is gitignored and so was never a record of them. Entries are `AHJ-NN`,
each stating the ambiguity, who established it, what the tool does meanwhile,
and where a reader meets it at runtime.

Entries carry one of FOUR statuses, and only `referral` means the text does
not decide the question. `alternative-solution` is for a requirement the text
DOES decide and we do not meet — an authority can accept it only as an
explicitly identified non-conforming substitution, which is what AHJ-1 is.
`ruled` is settled and needs no authority. `tool-gap` is implementable and is
a defect to close, not an interpretation. Calling a tool gap a referral would
launder a defect as an ambiguity, and Sol's `122` lists twelve decisions that
are tool or data gaps for that reason.

Adding an entry means picking a status and saying whether it sets a run
conditional. The register's own status table is the contract, and the first
version of this section stated a one-status rule that two of its own six
entries already broke.

Where Claude, Sol and Fable cannot resolve a question after real effort,
phylroy's direction (2026-10-07) is to emit a CONDITIONAL result naming the
approval required rather than stall. That is
`report['compliance_determination'] = 'conditional'`, set in
`btap/codes/necb/path.py`, with a reason block carrying `conditions` — one
record per unique final choice, each with its id, status, title, article,
target and the deciding entry's own account — plus `ahj_must_approve` (ONE
line per register id, not per choice), `if_not_approved` and `ahj_ids`. There
is no `serving_systems` key: that was the pre-D-100 shape. The CLI prints it inside the verdict string — not beside it —
and the HTML report badges it beside the pass/fail badge, because the report
is the AHJ-facing artifact. The exit code is deliberately unchanged, pinned by
`test_the_exit_code_is_UNCHANGED_by_the_label`.

`python/tests/necb/test_ahj_register.py` keeps the register honest: it fails
if the runtime cites an id with no entry, if the file becomes gitignored, or
if an entry omits its article, who established it, or its interim behaviour.
Add the entry in the same change as the condition that cites it.

## Verification

The post-R6 verification model has two independent parts:

- `verification/scenarios/` holds 56 frozen Python pipeline scenarios across
  `python` (36), `verify` (8), and `parity` (12) lanes. Intentional output changes use
  `verification/scenarios/freeze.py` on a clean tree and commit the baseline
  changes with the code.
- `legacy_pin/` plus `verification/oracle/` compare Python against the live,
  pinned legacy oracle. Leg C uses Python-prepared models and Ruby probes;
  committed goldens remain under `verification/oracle/goldens/`.

`legacy_pin/REF` is the sole oracle revision. A pin bump requires a complete
golden re-export and attribution of every changed comparison. Never hand-edit a
golden. `LEGACY_PIN_REQUIRED=1` is mandatory for local parity work so a missing
bundle fails instead of skipping. See [legacy_pin/README.md](legacy_pin/README.md).

The final cross-language attestation is immutable: commit
`85ab14352677093e24038d933cf1071e5b03431a`, GitHub Actions run
`33544573991`. It recorded 45 Ruby parity runs / 629 assertions, the Ruby
SmallOffice gate at 3 runs / 62 assertions, 4 Python successor tests, live Leg C
23/23, frozen parity scenarios, all four current CI jobs and every then-existing
gem matrix job, with zero parity skips. D-84 is the authority for the retirement
boundary; post-R6 freezes do not recreate cross-language evidence.

## CI

`.github/workflows/test.yml` has six jobs, and
`.github/workflows/decisions.yml` is a separate PATH-UNFILTERED gate beside it:

- **`lint`**: stdlib-oriented Python checks, coverage pointers/doc drift, and
  the decisions registry.
- **`python`**: import contracts, Ruff, the Python suite, and installed-wheel
  smoke on a bare runner.
- **`verify`**: the full SDK/EnergyPlus Python suite, rule verification, and
  sizing-lane frozen scenarios, in one parallel pytest run. It measures line
  coverage of `btap` (summary on the job page, HTML/XML artifact) and fails
  below `--cov-fail-under=84`; the baseline is in
  `docs/necb_rule_verification.md`. It also re-runs the HVAC catalogue
  sizing sweep SERIALLY and diffs it against the committed verdict, so a
  system that stops sizing cleanly fails the job instead of shipping as a
  sample.
- **`parity`**: dispatch-only live-oracle checks and the whole-building
  archetype gate. It is also where oracle goldens are exported.
- **`parity-scenarios`**: dispatch-only annual frozen scenarios, beside `parity`.
- **`main-red`**: an incident lifecycle for `main`. A failed push run opens or
  updates an issue assigned to `vars.MAIN_RED_ASSIGNEE` (else the pusher),
  naming the run and which lane failed; a green push run closes it. D-94's
  stop condition requires that run to be green, and a failed-run email had
  already proved insufficient. It no longer points at D-95's provenance
  recovery: D-103 retired the ancestry gate, so a stale pointer is not among
  the ways `main` can go red.

`verify`, `parity` and `parity-scenarios` run in the CI image
`ghcr.io/canmet-energy/btap-ci` (`infra/ci-image/Dockerfile`: the OpenStudio
3.11.0 image plus the test dependencies). Its tag is content-addressed and
`python/tests/test_ci_image_pin.py` fails until `test.yml` names the tag of the
current Dockerfile. With the repository variable `CI_RUNNER=necb-ci`, every job
but `lint` runs on a 36-vCPU CodeBuild runner (`infra/aws-ci/README.md`);
deleting the variable falls back to `ubuntu-latest`.

`.github/workflows/decisions.yml` is a SEPARATE workflow, not a seventh job,
and carries **no `paths` or `paths-ignore`** deliberately. The property it
enforces is exactly: **path-unfiltered and reachable on pushes to main/develop, pull requests, merge groups and manual dispatch**. It is not
"unskippable" — `[skip ci]` or `[ci skip]` in a head commit message skips it,
like any push- or PR-triggered workflow — and it is not merge-blocking. It runs
`generate_decisions.py --check` plus the three decision test modules on every
push and pull request, stdlib-only with no dependency install. It exists because
`docs/decisions/D-NN.md` is the canonical source of the RUNTIME registry while
`test.yml` path-ignores `docs/**`: a source edit WITHOUT a regenerate touches
only ignored paths, so `test.yml` would not run at all, and `main` has no branch
protection to require it. `python/tests/test_decisions_gate_is_path_unfiltered.py`
asserts the filter stays absent.

There is no scheduled parity trigger. Dispatch parity whenever `legacy_pin/REF`
moves. Documentation-only pushes are path-ignored by **`test.yml`**, so run local
doc checks before merging documentation changes — but the decisions gate still
runs, so a forgotten `generate_decisions.py` shows up as a RED run rather than
no run at all. It does not block the merge: `main` has no branch protection and
no rulesets, and `main-red` is a job inside `test.yml`, so a docs-only push to
`main` with stale outputs turns `decisions` red while `test.yml` never runs and
no incident is opened. The gate makes that failure visible, not impossible.

## Traps

**`-n auto` is sized for CI, not this host.** The devcontainer sees every
host core (48 on the reference machine) and every xdist worker imports the
OpenStudio SDK, so one `-n auto` run is ~50 SDK-loaded processes. Three of
those plus two EnergyPlus runs exhausted the 32 GB WSL2 VM on 2026-09-08 and
took the VM down. The devcontainer sets `PYTEST_XDIST_AUTO_NUM_WORKERS=8`;
keep it, never run two full suites concurrently, and run simulations one at
a time.

**The locale is load-bearing.** Generated documents contain UTF-8. CI and the
devcontainer force a UTF-8 locale; preserve it and use explicit UTF-8 when a
tool reads generated text.

**The Bundler remote is part of the lock.** If `LEGACY_PIN_REMOTE` points to a
local checkout, run `bundle install` with that value and keep using it. A
different remote makes `bundle check` report the source as not checked out.

**Thermal bridging has two distinct pins.** Product Python uses
`canmet-tbd==3.5.2`. The oracle bundle retains its Ruby tbd/osut/topolys triplet.
Upstream 3.6.x changes the physics by roughly 43% on the same wall, so upgrading
either side is an adjudicated rebaseline, never routine dependency maintenance.

**One MCP key, exported.** `HBIX_API_KEY` covers all six NRCan MCP servers and
the two Python maintainers' scripts, `python/scripts/building_stock.py` and
`python/scripts/fetch_necb_8_4_text.py`. `HBIX_MCP_BASE_URL` repoints all six.
Use `set -a && source .env && set +a`; plain `source` does not export variables
for child processes such as Claude Code.

**Corporate CAs come from the host.** The devcontainer stages trusted host CAs
before network downloads. Do not replace that with a network bootstrap that
needs working TLS in order to establish working TLS.

## History

The code was extracted from the `NatLabRockies/openstudio-standards` fork on
2026-08-16 and ported to Python under D-79. D-82 made Python the only changing
implementation; D-84 retired the five product Ruby gems at R6 while retaining
the external-oracle bridge. `PORT_STATUS.md` is the completed port record, not
the current architecture guide.
