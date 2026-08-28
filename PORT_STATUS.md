# Ruby → Python port: status and handoff

**As of 2026-08-28.** Milestones M0–M6 are done (M0–M5 merged; M6 on branch
`python-m6-umbrella`). **M7 (the TBD bridge) and M8 (CI/docs closeout) are
what remain.** The governing decision is **D-79**
(`btap-necb/docs/necb_decisions.md`); the verification architecture it plugs
into is **D-78**.

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

Current suite: **703 passed, 4 skipped**, ~6 min parallel (the M6
engine-backed suites run real EnergyPlus). Import contracts: 3 kept. Ruff:
clean (enforced in CI). The Ruby side is green throughout (matrix + verify +
the 12-gate parity job).

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

The four remaining skips each name a real reason: two await the M7 TBD
bridge, one needs an SVG rasterizer on PATH, one is a Leg-A gate needing the
live pinned oracle (its Leg-C twin is named in the skip message). The M6
sample-dependent tests skip only where the sample corpus is not generated;
CI's `verify` job generates it, so they run there. **There are
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

### What remains

**M7** — thermal bridging. `tbd` has no Python equivalent; the plan is a
small Ruby bridge invoked via `openstudio execute_ruby_script`, degrading to
the existing audited warning when absent. The Python side already raises a
`RuntimeError` naming this bridge rather than pretending, and two tests skip
with that exact reason. **M8** — CI completion and docs. (D-79 was originally
assigned to M8 but was written early, in M5's documentation pass, because 31
citations already pointed at it.)

---

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
