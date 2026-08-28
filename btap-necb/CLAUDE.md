# CLAUDE.md — btap-necb (the umbrella)

The code-compliance layer: every NECB rule as internal domains
(`envelope/ hvac/ loads/ lighting/ shw/` under `lib/btap_necb/`), composed
with btap-modeling's authoring machinery and btap-costing into the full
NECB Part 8 determination. **This is the ONLY gem
allowed to run EnergyPlus** (pure SDK + `openstudio` CLI — no measures, no
openstudio-standards). One clone carries both reference transforms; ONE
AuditLog spans everything.

## The Python twin (btap.necb)

This gem is fully mirrored by `python/btap/necb/` (the port is complete —
D-79; `PORT_STATUS.md` at the repo root is the record). **A behaviour change
here is a change to BOTH implementations**: land it Ruby-first, port it, and
keep the Leg-B gates green — audit `action`/`article`/`ruling` strings are
compared VERBATIM cross-language, so even wording is load-bearing. A defect
found on either side is fixed on both or flagged in D-79, never silently on
one.

## Pipeline (`Compliance.performance_compliance`)

clone → on-ramp → **space-type pre-flight** (`validate_space_types!`: every
floor-area space type must resolve against the NECB catalog; hard
`ArgumentError` with did-you-mean suggestions — BREAKING for untagged models
BY DESIGN, since unmatched types silently keep the proposed's lighting/loads
in the reference clone; the raise lands inside the diagnostics begin so the
audit still flushes) → weather attach → HDD (explicit → Table C-1 → .stat) →
proposed sizing → **proposed ANNUAL (D-52: runs BEFORE the reference build —
it depends on nothing downstream; when the proposed carries a heat pump,
per-equipment delivered-heat variables are requested first and joined with
`Classify.heating_election_inventory` into `proposed_annual:` for the
8.4.4.13.(2)(g) aux-fuel election)**
→ reference_hvac + reference_envelope + reference_lighting (Part 4 allowance
LPDs, always) + reference_shw (Part 6 minimum efficiencies, always) +
reference_daylighting (ON by default, D-51) on ONE clone/audit → reference sizing →
efficiencies RE-applied on sized capacities (with `proposed:` for the
8.4.4.14 pump W/(L/s) transfer) + 5.2.10.1 energy-recovery
determination on sized flows (Table 5.2.10.1.-A/-B) → reference annual → 8.4.1.2.(2)–(4)
verdicts → sentence-(5) capacity auto-iteration (per-thermal-block
Sizing:Zone factor bumps, secant-targeted; global fallback; stall
detection; iterations may RE-run either building's annual, but the (2)(g)
election is made once from the FIRST proposed annual and never re-litigated)
→ Section 10 tier → 2025 Part 11 GHG → optional costing of both
models → report.json / audit.json / audit.txt → optional compliance_report.html.

All reference transforms run inside `audit.with_building('reference building')`
so their entries and coverage are stamped and reconcilable. Only schedules and
occupancy/receptacle loads stay identical-by-clone (8.4.3.2); lighting power
and SHW efficiencies ARE regenerated to code on the reference.

- Modes `simulate: :annual | :sizing | :none` (only `:annual` determines).
- `path: :eui` (2025 only) — the 8.4.4 archetype-EUI path via
  `eui_archetypes.rb`: `archetypes: {'Office' => :all | [space names]}` (a SPACE
  mapping — `archetype_areas` is gone); areas COMPUTED from the model per
  8.4.4.1.(3), unmapped area pro-rata per (4); <90% coverage or HDD ≥ 9000
  HARD-REFUSE. The proposed is CHECKED against Table 8.4.4.2 (values +
  hourly schedule profiles) and, when non-conformant, NORMALIZED to it before
  the annual run (8.4.4.2.(1)) — normalization REPLACES the run, no extra
  cost. NO reference building.
- `eui_supplement: {archetypes:, run_normalized:}` on a 2025 REFERENCE-path
  run: the two paths simulate DIFFERENT proposeds (as-specified vs
  Table-8.4.4.2-normalized), so the shared-run shortcut is only lawful when
  the conformance check passes; otherwise `report['eui_path']` is
  `computed: false` with the mismatch list (default — never silently double
  E+ cost) unless `run_normalized: true` runs the normalized clone into
  `proposed_eui_annual/`. The report renders NOT COMPUTED as its own state.
- `necb_loads:` — bare-geometry on-ramp (loads → lighting → optional shw →
  optional hvac) before the pipeline.
- Returns `ComplianceResult` Struct
  `(proposed_model, reference_model, report, audit, compliant, run_dir)`.

## Audit building-stamp (load-bearing)

The pipeline sets `audit.building=` / `audit.with_building` at EVERY phase
boundary: `'input model'` (load + on-ramp), `'proposed building'`,
`'reference building'`, nil for cross-building verdicts. Keep new phases
stamped — the HTML report's "Applies to" chips and issue-traceability depend
on it. Audit text convention: violations SHOUTED, passes lowercase — the
checklist classifier in `report/checklist.rb` parses this CASE-SENSITIVELY.

## Decision rulings (`ruling:`, D-44)

Audit entries carry a second citation axis next to `article:`: `ruling:` names
the adjudicated decision(s) governing the code path, so a report reader learns
*why* we read the article that way without needing `docs/necb_decisions.md`.

- TOP-LEVEL kwarg, never inside `inputs:`; single-quoted literal on ONE line;
  several ids as one space-separated string (`ruling: 'D-19 D-21'`), parsed
  everywhere by `Decisions.ids_in` (`/\bD-\d{2}\b/`).
- `decisions.rb` + `data/decisions.json` are the machine-readable mirror of
  `docs/necb_decisions.md` (`{id, title, kind, summary, articles}`; `kind` =
  runtime / runtime_unwired / data / process). Summaries are PARAPHRASE and
  self-contained — the report links to nothing, so the summary IS the
  explanation.
- **Adding a `## D-XX` heading means adding a registry entry**, and a
  `kind: runtime` entry must be cited by ≥1 `ruling:` tag.
  `test/test_decisions_registry.rb` enforces both directions (and that every
  family gem's `AuditLog` resolves to the shared `BtapAudit::AuditLog`).
- `report/sections.rb#rulings_appendix` renders the decisions that FIRED in the
  run (id, title, summary, fire count, anchor to the first audit entry). It is
  ALWAYS rendered — the TOC link is unconditional and `test_report_html.rb`
  asserts every href resolves.
- `step: :coverage` entries are deliberately untagged (manifest boilerplate
  would swamp the appendix fire counts — this is why D-09 is `runtime_unwired`).
- Live registers are D (decisions) and L (legacy findings) — see
  `docs/README.md`; the A/T registers of the 2026-07-25 audit are archived.

## Modules

- `compliance.rb` — the pipeline + eui path + capacity iteration + costing.
- `Runner` is an ALIAS of `BtapSimulation::Runner` (the runner was
  extracted to the btap-simulation gem): weather attach,
  `run_energyplus!`, `energy_results` (End Uses via TabularData GJ rows —
  SqlFile has NO fuel-agnostic end-use methods), unmet hours, `clean_run?`.
  District accessors renamed across SDK versions — `respond_to?` probe.
- `eui_archetypes.rb` — the 8.4.4 machinery: mapping/areas/applicability +
  Table 8.4.4.2 conformance check + normalization (built THROUGH
  btap-necb (loads)' record machinery with synthetic archetype records). Named
  for the 8.4.4 *building* archetypes — NOT the 17-building legacy validation
  fleet (see the glossary in `docs/README.md`).
- `lib/btap_necb/data/necb_rules_{2020,2025}.json` — the umbrella's own
  `article_coverage` manifests (8.4.1.2 determination, 8.4.2.x methods,
  8.4.4.x EUI). Emitted at runtime by `Compliance.emit_article_coverage` at
  the end of every successful run (happy path only — never on crash flush).
  Split semantics (D-09, all six gems' emitters): partial/not_implemented
  warn, EXCEPT entries flagged `"gap_owner": "modeller"` (gaps wholly the
  modeller's responsibility) which emit as info scope notes — rendered ⓘ
  "modeller scope" in the report, off the checklist. 8.4.2.2, 8.4.2.3 and
  8.4.4.2 are declared PER SENTENCE (15 entries in the 2025 manifest, 12 in
  2020, which has no 8.4.4.2): the real pipeline limitation 8.4.2.2.(1)
  (elevators/escalators) warns on its own, while the modeller decisions —
  (5)/(6) equipment exclusions and the 8.4.2.3.(2) urban-dataset choice — are
  individual scope notes. test_compliance pins the per-sentence entries; match
  coverage articles by PREFIX.
- `tiers.rb` + `lib/btap_necb/data/eui_targets_2025.json` /
  `ghg_factors_2025.json` — Section 10 tiers (≤100/75/50/<40% → 1–4, identical 2020/2025), 8.4.4 BET
  arithmetic, Part 11 GHG levels A–F (provincial factors: ON elec 57.9 g/kWh,
  gas 185).
- `report.rb` + `report/` — the AHJ HTML report.
  **`report/model_query.rb` is the ONLY SDK-touching renderer file** (plain
  hashes out, never raises); html/svg/charts/checklist/diagrams/sections are
  SDK-free. Single self-contained file: inline SVG/CSS, no scripts (native
  `<details>` only), no external references — tests enforce this. Goldens in
  `test/goldens/` (`UPDATE_GOLDEN=1` to regenerate).

## Two directories named `data` — the rule

- **`lib/btap_necb/data/`** SHIPS in the gem (`spec.files` is `lib/**/*`):
  the rules manifests, `decisions.json`, EUI targets, GHG factors — anything
  the running gem reads.
- **Gem-root `btap-necb/data/`** is deliberately OUTSIDE `spec.files` and
  never ships: the MCP-fetched NECB 8.4 article-text caches
  (`necb_8_4_articles_{2020,2025}.json`), consumed only by the coverage-doc
  generator scripts. New data goes in the first unless it is script-only
  input that must never reach a user's install.

## Key facts / traps

- **The CLI is `exe/btap-compliance.rb`; the logic is `lib/btap_necb/cli.rb`.**
  Logic lives in `lib/` so it is testable in-process — `CLI.run(argv, out:, err:)`
  returns an Integer and never calls exit. The `.rb` extension on the entry point
  is **mandatory, not stylistic**: the Windows launcher runs it through
  `openstudio execute_ruby_script`, which loads the file with `require`, and
  `require` will not load an extensionless path.
- **The shim must `exit!`, not `exit`.** Under `execute_ruby_script` the file is
  `require`d, so a `SystemExit` from `exit` unwinds through the CLI's rescue and
  is reported as a crash-with-backtrace on a perfectly normal exit 6. `exit!`
  skips at_exit and does not flush, so flush both streams first.
- **`--quick` must never print COMPLIANT.** `evaluate` returns a boolean
  regardless of run period and only sets `report['annual'] = false` plus a
  warning, so the CLI treats that flag as overriding the boolean and exits 6.
  A week-long run passed off as a determination would be the worst bug this tool
  could have.
- **The verdict is decided on `total_site_kwh`, not EUI** (`Compliance.evaluate`).
  The CLI prints both, but phrases the margin on total site energy — labelling an
  EUI comparison as the verdict diverges the moment floor areas differ.
- **`PreflightError < ArgumentError`** distinguishes "repair the MODEL" from
  "repair the CALL" (bad weather path, unresolvable HDD). Subclassing keeps every
  existing `rescue ArgumentError` working; it replaced message-matching on the
  string `'pre-flight'`, which two call sites were doing. Rescue it BEFORE
  `ArgumentError` or the parent swallows it.
- Exit codes are the diagnosis: `0` compliant, `1` not compliant (a verdict, not
  an error), `2` usage, `3` pre-flight refusal, `4` simulation, `5` internal,
  `6` no determination.

- Sentence (4) unmet cooling is VACUOUS when the proposed has no mechanical
  cooling (passive overheating ≠ capacity shortfall) — audited determination.
- Capacity iteration (D-43) is per THERMAL BLOCK: failing zones (per-zone
  SystemSummary unmet hours) get Sizing:Zone factor bumps — first by
  `capacity_step`, then secant-extrapolated from that zone's own
  (factor, hours) history, growth clamped at max(step, 2)× per round. Zone
  factors OVERRIDE the global SizingParameters factor. Fallback to global
  bumps when per-zone data is missing or a gate fails with no single zone
  failing (facility hours are a union over zones, not a sum → 'mixed' mode).
  Hard-sized equipment responds to neither → stall detection stops the loop
  with a loud warning.
- A shortened `run_period:` computes the same arithmetic but flags NOT
  code-compliant (`report['annual'] = false` + warning + report strip).
- `AuditLog` here is an alias of `BtapAudit::AuditLog` (as every family
  gem's is — the class lives in the btap-audit gem).
- **Cloning a SpaceType for load overrides? Clone its DefaultScheduleSet
  too** — a fresh set severs Lights schedule inheritance and EnergyPlus
  FATALS on schedule-less Lights (found by the E+ battery, invisible to
  SDK-only tests).
- Schedule-PROFILE comparison across models must clone the candidate into the
  target's model first: differing assumed years shift day-of-week rules
  (weekday profiles get compared against weekends).
- SpaceType density getters may return OptionalDouble — unwrap (see
  `ModelQuery.unwrap`).
- Licensing: `costs_csv:` runtime injection only; the report embeds cost
  TOTALS only, never line-item licensed prices. NEVER stage `.mcp.json`.
- The legacy-parity ORACLE is pinned: `legacy_pin/REF` names the exact
  openstudio-standards fork revision the parity gates compare against; bump
  it deliberately (see `legacy_pin/README.md`).

## Tests

```bash
cd btap-necb
ruby test/test_compliance.rb          # pipeline modes + capacity iteration + pre-flight
ruby test/test_archetypes.rb          # 8.4.4 mapping/check/normalize (round-trip pinned)
ruby test/test_tiers_eui.rb           # tiers, 8.4.4 EUI path, GHG
ruby test/test_report_units.rb        # SDK-free renderer units + goldens
ruby test/test_decisions_registry.rb  # D-XX registry drift + AuditLog alias resolution
ruby test/test_report_model_query.rb  # SDK extraction
ruby test/test_report_html.rb         # whole-document renders + 2025 E2E
```

E+ tests skip without the CLI; annual tests use week runs (~1 min each).
Fixtures shared from `../btap-modeling/test/fixtures`.

`test_legacy_archetype_e2e.rb` generates/caches the 17-building legacy
archetype fleet against the legacy NECB implementation. It now runs under the
PINNED oracle (`BUNDLE_GEMFILE=../legacy_pin/Gemfile`), like every sibling
`*_parity.rb` suite — the gated "move it onto legacy_pin" phase was forced by
the gem extraction, since the in-tree `lib/openstudio-standards` it used to
require is no longer in this repository. Its cache key is `legacy_pin/REF`
rather than the host repo's `HEAD:lib/openstudio-standards` subtree SHA (that
command returns EMPTY outside the host checkout, which would have degraded the
key silently). See `legacy_pin/README.md` for the pinning philosophy.
