# CLAUDE.md — btap.necb (the umbrella)

The code-compliance layer: every NECB rule as internal domains
(`envelope/ hvac/ loads/ lighting/ shw/`), composed with `btap.modeling`'s
authoring machinery and `btap.costing` into the full NECB Part 8
determination. **This is the ONLY subpackage allowed to run EnergyPlus**
(pure SDK — no measures, no openstudio-standards). One clone carries both
reference transforms; ONE AuditLog spans everything.

[README.md](README.md) is the API guide. This file is the traps.

## Pipeline (`compliance.performance_compliance`)

clone → on-ramp → **space-type pre-flight** (every floor-area space type must
resolve against the NECB catalog; hard `PreflightError` with did-you-mean
suggestions — BREAKING for untagged models BY DESIGN, since unmatched types
silently keep the proposed's lighting/loads in the reference clone; the raise
lands inside the diagnostics block so the audit still flushes) → weather
attach → HDD (explicit → Table C-1 → `.stat`) → proposed sizing →
**proposed ANNUAL (D-52: runs BEFORE the reference build — it depends on
nothing downstream; when the proposed carries a heat pump, per-equipment
delivered-heat variables are requested first and joined with the heating
election inventory for the 8.4.4.13.(2)(g) aux-fuel election)** →
reference_hvac + reference_envelope + reference_lighting (Part 4 allowance
LPDs, always) + reference_shw (Part 6 minimum efficiencies, always) +
reference_daylighting (ON by default, D-51) on ONE clone/audit → reference
sizing → efficiencies RE-applied on sized capacities (with `proposed=` for
the 8.4.4.14 pump W/(L/s) transfer) + 5.2.10.1 energy-recovery determination
on sized flows → reference annual → 8.4.1.2.(2)–(4) verdicts → sentence-(5)
capacity auto-iteration → Section 10 tier → 2025 Part 11 GHG → optional
costing of both models → `report.json` / `audit.json` / `audit.txt` →
optional `compliance_report.html`.

**The second efficiency pass is a real trap.** `apply_efficiencies` runs
again after reference sizing, so anything set once during
`reference_hvac` and not re-derivable from the model is silently overwritten
before the annual run. A purchased-cooling chiller COP shipped that way and
reverted to the generic value in every simulated run while its unit test —
which asserted right after the build — stayed green. Persist such identity
ON the object (`additionalProperties`) and have the applier read it, or the
fix does not survive to the simulation.

All reference transforms run inside `audit.with_building('reference
building')` so their entries and coverage are stamped and reconcilable. Only
schedules and occupancy/receptacle loads stay identical-by-clone (8.4.3.2);
lighting power and SHW efficiencies ARE regenerated to code on the reference.

- Modes `simulate='annual' | 'sizing' | 'none'` — only `'annual'` determines.
- `path='eui'` (2025 only) — the 8.4.4 archetype-EUI path via
  `eui_archetypes.py`. Areas are COMPUTED from the model per 8.4.4.1.(3),
  unmapped area pro-rata per (4); <90% coverage or HDD ≥ 9000 HARD-REFUSE.
  The proposed is CHECKED against Table 8.4.4.2 and, when non-conformant,
  NORMALIZED to it before the annual run — normalization REPLACES the run, no
  extra cost. NO reference building.
- `eui_supplement` on a 2025 reference-path run: the two paths simulate
  DIFFERENT proposeds (as-specified vs Table-8.4.4.2-normalized), so the
  shared-run shortcut is only lawful when the conformance check passes;
  otherwise the EUI path reports NOT COMPUTED with the mismatch list rather
  than silently doubling EnergyPlus cost.
- `necb_loads=` — bare-geometry on-ramp before the pipeline.

## Audit building-stamp (load-bearing)

The pipeline stamps EVERY phase boundary: `'input model'` (load + on-ramp),
`'proposed building'`, `'reference building'`, `None` for cross-building
verdicts. Keep new phases stamped — the report's "Applies to" chips and
issue-traceability depend on it. Audit text convention: violations SHOUTED,
passes lowercase; the checklist classifier parses this CASE-SENSITIVELY.

## Decision rulings (`ruling=`, D-44)

Audit entries carry a second citation axis next to `article=`: `ruling=`
names the adjudicated decision(s) governing the code path, so a report reader
learns *why* we read the article that way.

- TOP-LEVEL keyword, never inside `inputs=`; a string LITERAL; several ids as
  one space-separated string (`ruling='D-19 D-21'`), scanned as
  `\bD-\d{2}\b`.
- **`data/decisions.json` is CANONICAL — edit it directly.** This inverted at
  R6: the Ruby mirror and `sync_decisions_registry.py` are both gone. Edit
  this file plus the `## D-XX` section in `docs/necb_decisions.md`, then run
  `python3 python/scripts/generate_decisions_toc.py` for the TOC.
- **Adding a `## D-XX` heading means adding a registry entry**, and a
  `kind: runtime` entry must be cited by ≥1 `ruling=` tag.
  `tests/necb/test_decisions_registry.py` enforces both directions with an
  **AST walker** — a name, an f-string, or a `**{'ruling': …}` expansion on an
  audit-surface call is refused, not ignored, and docstring examples and
  `ruling=None` defaults are excluded so documenting the rule cannot satisfy
  it.
- The report's rulings appendix renders the decisions that FIRED in the run
  and is ALWAYS rendered; a test asserts every href resolves.
- `step='coverage'` entries are deliberately untagged (manifest boilerplate
  would swamp the appendix fire counts — why D-09 is `runtime_unwired`).

## Two directories named `data` — the rule INVERTED at R6

- **`btap/necb/data/`** ships in the wheel: rules manifests,
  `decisions.json`, EUI targets, GHG factors.
- **`btap/necb/data/coverage/`** ALSO ships now — the NECB 8.4 article-text
  caches plus `ATTRIBUTION.md`. Before R6 this material sat outside the
  packaged files and was script-only input. It is now versioned, offline
  reference data with a packaged read API (`btap.necb.coverage`) and a
  console entry point (`btap-necb-coverage`). The Crown NECB text is
  attributed and explicitly outside the LGPL that covers the code — keep
  `ATTRIBUTION.md` beside it.
- The HBIX fetch that refreshes those caches stays an explicit **maintainer**
  operation. Ordinary runtime is offline.

## Key facts / traps

- **The CLI logic is `cli.py`; the console script is
  `btap-compliance = btap.necb.cli:main`.** `run(argv, out=, err=)` returns
  an int and never exits, so a 40-minute pipeline is testable in-process
  against `io.StringIO` rather than as a subprocess.
- **`main` uses `os._exit`, and must flush first.** It sets the status
  without unwinding — but it skips `atexit` and does NOT flush, so both
  streams are flushed before the call. Removing the flush loses the verdict
  line on a perfectly normal exit.
- **`--quick` must never print COMPLIANT.** `evaluate` returns a boolean
  regardless of run period and only sets `report['annual'] = False` plus a
  warning, so the CLI treats that flag as overriding the boolean and exits 6.
  A week-long run passed off as a determination would be the worst bug this
  tool could have.
- **The verdict is decided on `total_site_kwh`, not EUI.** The CLI prints
  both but phrases the margin on total site energy — labelling an EUI
  comparison as the verdict diverges the moment floor areas differ.
- **`PreflightError` subclasses `ValueError`** and distinguishes "repair the
  MODEL" from "repair the CALL" (bad weather path, unresolvable HDD).
  Subclassing keeps existing `except ValueError` working — so catch
  `PreflightError` FIRST, or the parent swallows it.
- **Exit codes are the diagnosis**, and the `EXIT` dict in `cli.py` is their
  single definition: `0` compliant, `1` not compliant (a VERDICT, not an
  error), `2` usage, `3` pre-flight refusal, `4` simulation, `5` internal,
  `6` no determination.
- Sentence (4) unmet cooling is VACUOUS when the proposed has no mechanical
  cooling (passive overheating ≠ capacity shortfall) — audited determination.
- **Capacity iteration (D-43) is per THERMAL BLOCK**: failing zones get
  `Sizing:Zone` factor bumps, first by `capacity_step`, then
  secant-extrapolated from that zone's own (factor, hours) history, growth
  clamped per round. Zone factors OVERRIDE the global sizing factor. Falls
  back to global bumps when per-zone data is missing or a gate fails with no
  single zone failing (facility hours are a union over zones, not a sum →
  'mixed' mode). Hard-sized equipment responds to neither, so stall detection
  stops the loop with a loud warning.
- **Cloning a SpaceType for load overrides? Clone its DefaultScheduleSet
  too** — a fresh set severs Lights schedule inheritance and EnergyPlus
  FATALS on schedule-less Lights. Found by the E+ battery, invisible to
  SDK-only tests.
- Schedule-PROFILE comparison across models must clone the candidate into the
  target's model first: differing assumed years shift day-of-week rules, so
  weekday profiles get compared against weekends.
- SpaceType density getters may return an optional — unwrap them.
- **`report/model_query.py` is the ONLY SDK-touching renderer file** (plain
  dicts out, never raises); html/svg/charts/checklist/diagrams/sections are
  SDK-free. The report is a single self-contained file: inline SVG/CSS, no
  scripts (native `<details>` only), no external references — tests enforce
  this.
- Licensing: `costs_csv=` runtime injection only; the report embeds cost
  TOTALS, never line-item licensed prices. NEVER stage `.mcp.json`.
- The legacy-parity ORACLE is pinned: `legacy_pin/REF` names the exact
  openstudio-standards fork revision the remaining gates compare against.
  Bump it deliberately — see `legacy_pin/README.md`.

## Tests

```bash
cd python && .venv/bin/python -m pytest -q tests/necb/
```

EnergyPlus tests skip without an engine; annual tests use week runs.
`BTAP_SDK_REQUIRED=1` / `BTAP_ENGINE_REQUIRED=1` turn those skips into
failures, which is what CI sets so a missing dependency cannot pass
vacuously.

`tests/necb/test_legacy_archetype_e2e.py` generates and caches one pinned
NECB2020 SmallOffice whole-building gate against the ORACLE — the only gate
fed a model built by the legacy prototype generator, which is why it is the
only place Kiva foundations are exercised. It runs under
`BUNDLE_GEMFILE=legacy_pin/Gemfile`; `LEGACY_PIN_REQUIRED=1` turns a missing
bundle into a failure instead of a skip. Its cache key includes
`legacy_pin/REF`, the generator digest and the EPW, so a pin bump cannot
silently reuse a stale model. The 17-building fleet lives in
`python/scripts/necb_archetype_sweep.py`.
