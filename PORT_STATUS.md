# Ruby → Python port: status and handoff

**As of 2026-08-28.** Milestones M0–M7 are done (M0–M6 merged; M7 on branch
`python-m7-tbd`). **Only M8 (closeout) remains.** The governing decision is
**D-79** (`btap-necb/docs/necb_decisions.md`); the verification architecture
it plugs into is **D-78**.

This file is the durable record. If you are an agent picking this up with no
prior context, read this, then D-79, then D-78, then `python/README.md`.

---

## The premise

The port is gated on verification that **already existed before the port
started**, never on gates written to fit it. Three legs (D-78):

- **Leg A** — the Ruby gems vs the pinned openstudio-standards oracle: the
  eleven in-process parity gates, unchanged and still green.
- **Leg B** — Python vs Ruby, by diffing both CLIs' `audit.json`/
  `report.json` on the same models (`verification/compare_runs.py`).
- **Leg C** — Python vs **the oracle directly**, against goldens frozen from
  the pin (`btap-necb/test/goldens/oracle/`). This is the one that matters
  most: a bug faithfully ported from Ruby passes Leg A *and* Leg B, because
  both sides agree. Only comparing against the oracle's own values catches it.

Every Leg-C consumption test asserts **key-set equality in both directions**,
so a comparison that silently shrinks fails loudly instead of passing
vacuously. Two domains additionally carry **negative controls** — deliberately
perturbing an input and confirming the gate fails.

**Leg C covers NECB 2020 only, and cannot cover 2025.** This is a structural
boundary, not missing test work: the pinned oracle predates the 2025 edition
(its probes sweep `NECB2020`; NECB 2025 is this project's own
implementation), so there are no 2025 values in existence to freeze. Do not
try to close this by exporting more goldens — there is nothing to export
from. 2025 correctness rests on the adjudicated decision record plus the
data-integrity and cross-edition tests, which is the only available basis.

---

## What has landed

| Milestone | Scope | What proves it |
|---|---|---|
| **M0** | `btap` distribution, `_compat` contracts, CI job | `ruby_round` fuzz-verified vs Ruby on 19,154 cases, zero mismatches |
| **M1** | `btap.audit` | Cross-language gate: `audit.json` equivalent under the real Leg-B rules; `audit.txt` **byte-identical** to the gem's |
| **M2** | `btap.simulation` + the EnergyPlus provisioner | Ruby-CLI vs Python-engine runs agree on a gas-heated week (energies exact, unmet hours in tolerance) |
| **M3** | `btap.modeling` (11.8k lines) | 97-system EnergyPlus battery agrees with the Ruby sweep **97/97**; the 97-system catalog HTML is **byte-identical** between languages |
| **M4** | `btap.costing` | **134** oracle-frozen values reproduced (39 interpolations, 92 construction costs, 3 TB quantities) |
| **M5** | the five `btap.necb` rule domains (8.5k lines) | ~630 oracle-frozen values across five domains; the D-58 reference matrix run across the **full 97-system catalog** (both naming passes × 4 scenarios) as a CI gate, not a manual run |
| **M6** | the umbrella (`compliance`, `eui_archetypes`, `tiers`, the renderer, the CLI) | **The Leg-B corpus convergence**: Ruby CLI vs Python CLI over the whole corpus, every pair EQUIVALENT under the Leg-B rules — 18/18 at tier `none`, 3/3 at `sizing`, 2/2 at `annual --quick`. Plus: the renderer's chart primitive reproduces the Ruby suite's `paired_bars.svg` golden **byte-identically** (now consumed as a cross-language gate) |
| **M7** | thermal bridging (NECB 3.1.1.7) via **native py-tbd**, Option A | Direct Ruby-vs-Python `TBD.process` parity on the fixture (surfaces/edges/**warnings byte-identical**, numerics 1e-9); the frozen `tbd_rsi` Leg-C golden (1e-6, key-set both ways); the uprate/derate gate incl. the infeasible-wall refusal; the post-reference-rebuild target-retention gate; an assembled Leg-B compliance case with `efficient (BETBG)` EQUIVALENT cross-language; engine identity asserted; wheel installs and processes from the `[tbd]` extra |

Current suite: **715 passed, 2 skipped**, ~6 min parallel (the M6
engine-backed suites run real EnergyPlus; the M7 gates run both TBD
engines). Import contracts: 3 kept. Ruff: clean (enforced in CI). The Ruby
side is green throughout (matrix + verify + the 12-gate parity job).

Three gates make the claims above continuously enforced rather than
manually observed — a review found that gap and it is now closed:

- **Installed-wheel smoke** (`python/scripts/wheel_smoke.py`, run in CI):
  builds the wheel, installs it into a clean venv, and exercises it from
  OUTSIDE the checkout so the source tree cannot shadow the install. It
  exists because `catalog_html()` used to resolve its seed model outside the
  package and degrade silently from a wheel — 97 'diagram unavailable' cards
  in a 1 MB document that looked like a report.
- **`FULL_MATRIX=1` in the container `verify` job**: the D-58 matrix defaults
  to a 22-system subset for PR speed; the full 97 now run on every
  main/dispatch build, so the M5 acceptance claim tracks a gate.
- **Ruff**, enforced with a ruleset this codebase can honestly hold (see
  `pyproject.toml` for why `UP` and `E501` are deliberately out).

The two remaining skips each name a real reason: one needs an SVG
rasterizer on PATH, one is a Leg-A gate needing the live pinned oracle (its
Leg-C twin is named in the skip message). The formerly-M7 TBD skips are
ENABLED (M7 landed); the M6 sample-dependent tests and the M7
cross-language TBD gates skip only where their dependency is absent, and
CI's `verify` job supplies every one of them (samples generated, both tbd
engines installed, `BTAP_TBD_REQUIRED=1`). **There are
no stale exemptions** — when a milestone supplies a dependency, the tests
waiting on it are ported and enabled in that same milestone.

---

## M6 — the umbrella, DONE (2026-08-28)

**What landed:** `btap/necb/compliance.py` (the eleven-phase pipeline,
capacity iteration, the EUI path), `eui_archetypes.py`, `tiers.py`,
`decisions.py`, the renderer (`btap/necb/report/` — html, svg, charts,
checklist, model_query, sections + the assembler), and `cli.py` with the
`btap-compliance` console script (`[project.scripts]` in pyproject). The
eight Ruby test suites are ported (`test_compliance`, `test_archetypes`,
`test_tiers_eui`, `test_report_units`, `test_report_model_query`,
`test_report_html`, `test_cli`, `test_reference_rules`).

**The decisive acceptance held on the first convergence run, essentially.**
`verification/run_corpus.rb` gained `--cli python` (drives
`python -m btap.necb.cli` over the same models/args) and `selftest.sh`
gained `CLI_B=python`; the whole cross-language corpus came back EQUIVALENT
with exactly ONE diff in total across 18 none-tier runs — Ruby's
`simulate: :none` symbol-inspect literal vs Python's `simulate: none` in one
warning string. After carrying the literal verbatim: 18/18 `none`, 3/3
`sizing`, 2/2 `annual --quick`, all EQUIVALENT. The renderer reproduced the
Ruby suite's `paired_bars.svg` golden byte-identically on the first render;
the Python unit suite now consumes that Ruby golden file directly.

### What the hazards list predicted vs what happened

- **`--quick` never prints COMPLIANT** — ported as specified; `verdict_exit`
  returns 6 whenever `report['annual']` is False, pinned by the CLI e2e test.
- **`model_query` stays the only SDK renderer file** (with the assembler) —
  boundary kept; the rest of `report/` runs SDK-free (18 unit tests).
- **Renderer: direct port** — held, and over-delivered (the byte-identical
  golden above).
- **CLI mechanics** — as planned: argparse subclass raising instead of
  exiting, seven exit codes, Progress as a daemon thread + stop `Event`
  (stopped on every path `run` can take), `os._exit` in `main`.
- **The three unsorted SDK iterations did NOT trip** at any tier on this
  corpus — energies are pre-rounded and equal, and audit order matched. They
  remain latent (`envelope/reference.rb:236`, `report/model_query.rb:28`,
  `hvac/reference.rb:378`); if a future corpus model diverges on entry
  order, fix Ruby-side first and re-baseline, as planned.
- **New find: the corpus runner's `sizing` tier had never run.** It passed
  no `--epw`, so the Ruby CLI exited 2 (usage) before any simulation — the
  committed harness had only ever been exercised at tier `none`. Fixed in
  `verification/` (the harness, not gem code): simulating tiers now pass the
  fixture weather trio explicitly.
- Two small Python-side seams found by the ported suites: the loads
  appliers index `gas_equipment_per_area`/`gas_equipment_schedule` that
  Ruby's synthetic archetype record simply omitted (nil semantics) — the
  Python `synthetic_record` carries them as explicit `None`; and
  `AuditLog.warnings` is a property in Python where Ruby has a method.

### CI wiring (landed with M6)

- **`verify`** now also: generates the sample corpus (Ruby SDK — so the
  sample-dependent `test_reference_rules` tests run instead of skipping)
  and runs the **Leg-B cross-language corpus** at tiers `none` and `sizing`
  on every main/dispatch build.
- **`parity`** (dispatch-only) gains the **`annual --quick` tier** of the
  same gate — each side runs four EnergyPlus simulations per model, priced
  like everything else in that job.
- **`wheel_smoke`** now also asserts the `btap-compliance` console script is
  installed and answers `--help`.

### Residual risk, stated plainly

The annual-tier Leg-B gate runs `--quick` (a one-week period): it exercises
the full determination arithmetic, the unmet-hours logic, the report and
exit 6 — but **no gate compares a real full-year determination returning
exit 0 or 1 across the two languages**. That is a runtime-cost decision
(each side is 40–90 minutes per model), not a confidence claim: the
arithmetic between a week and a year is identical code, but the year is the
shipping code path and it has only ever been run one language at a time.
Named by review (2026-08-28) as the principal residual M6 risk; a
deliberate one-off full-year convergence run is the cheapest way to retire
it when someone wants to.

### What remains

**M8** — closeout: the docs/README sweep and any final CI polish. (D-79 was
originally assigned to M8 but was written early, in M5's documentation
pass; the M6 and M7 records were appended to it as they landed.)

Concrete M8 items, from the post-M7 postponed-work sweep (2026-08-28):

1. **Retire the Leg-A lighting-costing skip.** The one test that has never
   run anywhere: `tests/necb/test_lighting_costing.py`'s Leg-A gate needs
   the LIVE pinned oracle (`BUNDLE_GEMFILE=legacy_pin/Gemfile`), which only
   the `parity` job bundles — and parity does not run pytest. Wire one
   targeted pytest invocation into the parity job so the skip retires (its
   Leg-C twin already covers the value, so this closes redundancy, not a
   coverage hole).
2. **Retire the SVG-rasterizer skip.** `tests/modeling/test_floor_plan.py`
   skips without a rasterizer on PATH; `rsvg-convert` is one apt install in
   the container jobs.
3. **Sweep the stale milestone-tense comments.** Three found:
   `tests/modeling/test_bar.py` still says "skipped until M5 lands" above a
   test that runs; `tests/simulation/test_local_run.py` and
   `tests/costing/test_lighting_costing_smoke.py` carry pre-M5 phrasing in
   their docstrings. Doc rot only — no behavior.

### M7, as it actually went (2026-08-28)

The planned Ruby bridge (`openstudio execute_ruby_script`) was never
built: the M6/M7 review found `canmet-energy/py-tbd` — a native Python port
of rd2/tbd — and reframed M7 as a dependency integration with ONE blocking
decision: the baseline. py-tbd main ports upstream TBD **3.6.0**; the
family's oracle is frozen on Ruby TBD **3.5.2** / OSut 0.8.2 / Topolys
0.6.2, and the two land ~43% apart on exactly the kind of infeasible-uprate
wall the btap fixture has (3.5.2 refuses; 3.6.0 partially uprates).
**Option A** was chosen and executed:

- **py-tbd gained a `tbd-3.5.2-compat` branch** (pinned by btap at its
  SHA): `uo`/`uprate` backported to the v3.5.2 algorithms (hard refusal;
  largest-area/lowest-film merge), boundary strings keep SDK casing, the
  3.6.0 interzone-film override removed — and EVERY py-tbd golden
  regenerated from the Ruby 3.5.2 + OSut 0.8.2 gems, its whole suite green
  against them (156 tests). Empirics before semantics: the fixture probe
  came back with byte-identical warnings and zero numeric diffs vs the
  Ruby gem before any test was written.
- **btap's adapter is thin**: `_bridge_available` imports `tbd`,
  `_process` is `tbd.oslg.clean()` → `tbd.process(model, argh)` → THAT
  call's logs, returned call-locally (no module-level "last logs" state).
  The three behaviour states are preserved exactly: not-requested warns,
  unavailable returns False with the loud NOT-accounted warning, and an
  available-but-failing engine ABORTS (a negative control pins that it can
  never be relabeled as unavailability).
- **The pin is falsifiable, not aspirational**: pyproject's `[tbd]` extra
  pins py-tbd by commit SHA (py-topolys pinned transitively inside
  py-tbd's own pyproject — neither project has a tagged release yet); the
  suite asserts `tbd.VERSION`/`UPSTREAM_VERSION`/`UPSTREAM_SHA`;
  `BTAP_TBD_REQUIRED=1` turns absence into failure (set in the python job
  and in verify, which also installs the RUBY triplet so the
  cross-language TBD gates run rather than skip); wheel smoke installs the
  extra and runs a real `tbd.process` outside the checkout.
- **Both formerly-M7 skips are enabled** (the uprate/derate gate and the
  frozen `tbd_rsi` Leg-C golden — 1e-6 with key-set equality both ways),
  plus the new gates: direct `TBD.process` parity Ruby-vs-Python
  (surfaces, edges, warning texts; 1e-9), the post-reference-rebuild
  assertion (nothing downstream may erase the uprate), and a dedicated
  assembled Leg-B case running the FULL compliance pipeline with
  `thermal_bridging='efficient (BETBG)'` on both sides — the corpus never
  requests thermal bridging, so that case, not a corpus re-run, is the M7
  evidence.

**The M7 review (Sol, 2026-08-28) found six issues; all dispositioned in
`dbcf74e`.** The one that mattered most existed identically in Ruby and was
fixed RUBY-FIRST: TBD reports invalid input by LOGGING fatal/error and
returning a PARTIAL result, and both languages' `apply` narrated that as
'assemblies uprated' (reproduced both sides: invalid PSI set → status 5,
30 surfaces returned, decision emitted). Both now check fatal/error after
capturing logs and RAISE before any decision can be recorded, pinned by
real-engine invalid-PSI tests on both sides. Also from the review: a broken
py-tbd install (failed transitive import) now propagates instead of taking
the benign 'not available' branch (Ruby's bare `rescue LoadError` had the
same relabeling — fixed first, on `LoadError#path`); osut/oslg are pinned
EXACTLY in the compat branch's metadata (pin `bfb23e68`) and asserted in
the engine-identity test; engine operations run under a module lock
(process-safe AND thread-safe); the assembled Leg-B test uses production
`compare_file` so `strip_keys` applies; and the two-flags split
(`BTAP_TBD_REQUIRED` = Python engine, `TBD_REQUIRED` = Ruby gem — the
family's existing flag, not a new name) had already landed when CI caught
the conflation on the first dispatch.

**Parked deliberately:** the family-wide rebaseline onto TBD 3.6.x is its
own future adjudication — bump the Ruby triplet first, re-run Leg A,
re-export the goldens, retire the compat branch — and pairs naturally with
the pending `legacy_pin/REF` bump.

## Working agreements that produced this

These are not style preferences; each was learned by something breaking.

1. **Port faithfully, including bugs.** Ruby defects are flagged and ported
   as-is, never quietly corrected — a fix that lands only on the Python side
   makes Leg B lie. Two such defects are flagged in D-79. The one exception
   was adjudicated explicitly and deleted from *both* sides.
2. **Ruby stays frozen except bugfixes.** It is the shipping product and the
   Leg-B baseline, so behaviour changes land Ruby-first or not at all.
3. **Use the `_compat` helpers.** `ruby_round`, `ruby_div`, `opt`/`opt_or`,
   `sorted_by_name`, `NullAudit`, `esc`/`ruby_str`, and `_sdk`'s
   `ensure_sdk_hashable`. Each exists because the naive Python translation
   silently changes results. Do not re-derive them locally.
4. **A skipped gate is a green-but-vacuous gate.** Every skip names the
   milestone or dependency that unblocks it, and is enabled the moment that
   arrives.
5. **Verify empirically rather than reasoning about semantics.** Every parity
   contract here was pinned by running actual Ruby and comparing — that is
   how the half-away rounding, the non-raising division, the signed-zero
   behaviour, and the WarmupFlag divergence were all established.
6. **Citations are data.** Every `article:` and `ruling:` string is carried
   across verbatim and mechanically diffed in both directions. Audit action
   text keeps its exact casing — violations SHOUTED, passes lowercase — since
   the report's checklist classifier is case-sensitive.

## Where things live

```
python/btap/{audit,simulation,modeling,costing,necb}/   the port
python/btap/_compat.py, _sdk.py                         the parity contracts
python/tests/                                           ported suites + Leg-C gates
python/scripts/simulate_all_systems.py                  the 97-system E+ battery
verification/                                           the Leg-B differ, spec, corpus
btap-necb/test/goldens/oracle/                          the Leg-C goldens (pinned)
btap-necb/test/support/oracle_probes.rb                 the recipe behind every golden
btap-necb/docs/necb_decisions.md                        D-79 (this port), D-78 (verification)
```
