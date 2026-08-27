# Ruby → Python port: status and handoff

**As of 2026-08-27.** Milestones M0–M5 are done (M0–M4 merged; M5 open as
PR #9). **M6 has not been started** and is the next step. The governing
decision is **D-79** (`btap-necb/docs/necb_decisions.md`); the verification
architecture it plugs into is **D-78**.

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

Current suite: **623 passed, 4 skipped**, ~2.5 min parallel. Import contracts:
3 kept. Ruff: clean (enforced in CI). The Ruby side is green throughout
(matrix + verify + the 12-gate parity job).

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
live pinned oracle (its Leg-C twin is named in the skip message). **There are
no stale exemptions** — when a milestone supplies a dependency, the tests
waiting on it are ported and enabled in that same milestone.

---

## M6 — the next milestone, not started

**Scope:** `compliance.rb` (the pipeline, capacity iteration, the EUI path),
`eui_archetypes.rb`, `tiers.rb`, the NECB report renderer (`report/` +
`report.rb`, ~1,240 lines), and `cli.rb` (496) — then the **Leg-B corpus
convergence**, which is the migration's decisive acceptance.

btap-modeling's diagram and plan renderers are **already ported** (M3:
`plan_query.py`, `plan_svg.py`, `plan.py`, `render.py`, `catalog_report.py`,
exposed as `model_hvac_diagrams`, `hvac_icon_defs` and `floor_plans`). M6
INTEGRATES those outputs into the NECB report — it does not port them
again. An earlier draft of this file said otherwise; it had been copied
from the pre-M3 plan.

Everything M6 builds on is ported and green.

M6 is qualitatively different from M0–M5: those were mostly mechanical
translation gated by values someone had already frozen. M6 is where the
judgement lives — the renderer is the one place where faithful porting and
idiomatic Python genuinely conflict, and Leg-B convergence is open-ended
debugging rather than porting.

### Hazards, each already paid for once

- **`--quick` must never print COMPLIANT.** `evaluate` returns a boolean
  regardless of run period; the CLI treats the flag as overriding it and
  exits 6. A week-long run passed off as a determination would be the worst
  bug this tool could have.
- **`report/model_query.rb` is the ONLY SDK-touching renderer file** — plain
  hashes out, never raises. Keep that boundary; it is what lets the rest of
  the renderer be tested without the SDK.
- **Renderer: direct port, not Jinja2.** Zero-dependency self-contained HTML
  is a family value. Byte-identical output is NOT required (Leg B gates
  `audit.json`/`report.json` only), but `Html.fmt` and the SVG layout want
  their own golden tests. Precedent: M3's catalog report came out
  byte-identical to Ruby's on a direct port.
- **CLI**: `argparse` with `exit_on_error=False`, reproducing the seven exit
  codes exactly (`0` compliant, `1` not compliant, `2` usage, `3` pre-flight,
  `4` simulation, `5` internal, `6` no determination). The Progress ticker is
  a daemon thread with a cooperative stop `Event` — `Thread#kill` has no
  Python equivalent and Ruby stops it in six places. `os._exit` mirrors
  `exit!`.
- **Leg B at annual tier** will likely surface three unsorted SDK iterations
  (`envelope/reference.rb:236`, `report/model_query.rb:28`,
  `hvac/reference.rb:378`). Fix them **Ruby-side first**, re-baseline, then
  continue — that keeps the comparison meaningful.
- **Backend SQL divergence** (found in M5, verified both ways): `openstudio
  run` writes `Time.WarmupFlag = 0`; the bare `energyplus` binary writes
  NULL. Test-only in both languages today, and `run_period_sums` filters on
  `EnvironmentType`, so Leg B and the D-52 election are unaffected — but no
  new hourly consumer may filter on WarmupFlag.

### After M6

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
