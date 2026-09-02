# btap.necb

The **umbrella** of the NECB Part 8 performance path. It composes the
SDK-only domains —

- `hvac/` — reference system selection (Table 8.4.4.7.-A), topology builds,
  capacity-binned efficiencies, ERV, fan rules
- `envelope/` — prescriptive Section 3.2, thermal bridging (3.1.1.7 via TBD),
  the reference-envelope transform (8.4.4.3/.4)
- `loads/` — NECB space-type assignment and space-use loads (occupancy,
  receptacles, ventilation, schedules)
- `lighting/` — Part 4 LPD allowances, daylighting controls, the
  reference-lighting transform (8.4.4.5)
- `shw/` — Part 6 service-water-heating demand and minimum efficiencies, the
  reference-SHW transform (8.4.4.20)

— plus `btap.modeling` (authoring), `btap.costing` and `btap.simulation`
(the EnergyPlus runner) into the full proposed-vs-reference determination of
**Article 8.4.1.2** (Division B; wording stable across 2020/2025).

The 8.4.1.2 determination:

- **(2)** annual energy consumption of the proposed ≤ the building energy
  target of the reference
- **(3)** unmet heating hours ≤ 100 h/year for both buildings
- **(4)** unmet cooling hours: proposed within +10% of reference (2025: +10%
  or 20 h, whichever is greater, on the 8.4.5 path). The clause applies to
  thermal blocks *"for which mechanical cooling is provided"* — a proposed
  building with no mechanical cooling passes (4) vacuously, with the
  determination audited.
- **(5)** where (3)/(4) fail: capacities are **incrementally increased until
  the loads are met** — sizing factors bumped by `capacity_step` (default
  1.25, per failing thermal block where the data supports it), the building
  re-sized and re-run, up to `max_capacity_iterations`. Every bump is an
  audited decision; the history lands in `report['capacity_iterations']`. A
  bump that yields no improvement (hard-sized equipment does not respond to
  sizing factors) stalls the loop with a loud warning instead of burning
  iterations.

This is the ONE place simulation execution lives. The domains never simulate.
One clone carries all the reference transforms; ONE AuditLog spans system
selection, efficiencies, envelope decisions, article coverage, the 8.4.1.2
verdicts, and optionally costing of both models.

## Quick start

```python
import openstudio
from btap.necb.compliance import performance_compliance

model = openstudio.model.Model.load(openstudio.path('5ZoneNoHVAC.osm')).get()
space_map = {s.nameString(): ('Space Function', 'Office enclosed > 25 m2')
             for s in model.getSpaces()}

result = performance_compliance(
    model, vintage='2020',
    weather={'epw': 'toronto.epw', 'ddy': 'toronto.ddy'},
    building={'storeys': 1},
    necb_loads={'space_type_map': space_map, 'shw_fuel': 'NaturalGas',
                'hvac_system': 'Baseboard gas boiler'},
    simulate='annual', report_html=True,
    run_dir='runs/quick_start')

result.compliant        # True / False (None unless simulate='annual')
result.report           # also written to run_dir/report.json
result.audit            # ONE audit — run_dir/audit.json + audit.txt
result.reference_model  # the fully-transformed reference building
```

**Before your first run on your own model**, know the two hard gates:

1. **Space types must carry NECB tags.** Every space type with floor area
   must resolve against the NECB catalog. Unmatched types would silently keep
   the proposed's lighting and loads in the reference — comparing the
   building against itself — so the pipeline refuses instead, with
   did-you-mean suggestions. For untagged bare geometry, use the
   `necb_loads` on-ramp as above.
2. **The storey count must be knowable.** Reference-system selection (Table
   8.4.4.7.-A) depends on storeys; pass `building={'storeys': N}` or model
   `BuildingStory` objects. An unknowable storey count raises rather than
   silently assuming 1.

Older `.osm` files are version-translated in memory on load (the file on disk
is never modified; the translation is recorded in the audit).

## What the pipeline does

The step numbers match the `# N.` markers in `compliance.py` — that list is
canonical.

1. Load + validate the input model — on-ramp for bare geometry, simulate-ability
   gates, the NECB space-type pre-flight.
2. Attach weather (EPW + DDY design days); resolve heating degree-days
   (explicit `hdd` → Table C-1 from the EPW site → `.stat`).
3. **Sizing run of the proposed** (selection kW thresholds, capacity-binned
   efficiencies and costing all need capacities).
4. **Annual run of the proposed — before the reference is built.** It depends
   on nothing downstream, and when the proposed carries a heat pump its
   annual heating-energy split feeds the 8.4.4.13.(2)(g) auxiliary-fuel
   election in the reference build (D-52).
5. **Reference build** on ONE clone, same audit: HVAC → envelope → lighting
   (Part 4 allowance LPDs, dwelling units to 5 W/m²) + daylighting
   photocontrols (ON by default, D-51) → SHW (Part 6 minimum efficiencies).
   Schedules and occupancy/receptacle loads stay identical-by-clone per
   8.4.3.2; lighting power and SHW efficiency do NOT.
6. Sizing run of the reference, then **efficiencies re-applied** on the sized
   capacities, plus the post-sizing determinations (5.2.10.1 energy recovery
   on sized flows, 5.2.2.7 economizer thresholds).
7. **Annual run of the reference**, the 8.4.1.2 (2)–(4) verdicts, and the
   sentence-(5) capacity iteration loop.
8. NECB 2025 + `province_state` — the Part 11 operational-GHG level.
9. `costing=True` — HVAC + envelope costing of BOTH models into the same
   audit, with the incremental cost in the report.
10. `eui_supplement` (2025) — the 8.4.4 archetype-EUI verdict alongside the
    reference-path verdict.
11. Article coverage emitted; `report.json`, `audit.json`, `audit.txt` (and
    `compliance_report.html` with `report_html=True`) written to `run_dir`.

A shortened `run_period` computes the same arithmetic but is flagged in the
report and audit as NOT a code-compliant determination.

Every audit entry is stamped with **which model it is about** (`building`:
`'input model'` | `'proposed building'` | `'reference building'`; absent =
cross-building comparison or verdict), so a warning is always traceable to
the model it belongs to.

## Modes

| `simulate` | What runs | `compliant` |
|---|---|---|
| `'annual'` | sizing + annual for both models | True/False |
| `'sizing'` | sizing only (models generated, sized, costable) | None |
| `'none'` | model transforms only — proposed stays UNSIZED (loud warning: kW thresholds and capacity bins fall back) | None |

## The two compliance paths

**`path='reference'`** (default, 2020 + 2025) — everything above: build a
reference building, compare annual energy.

**`path='eui'`** (NECB 2025 only) — the 8.4.4 archetype-EUI path. No
reference building is generated or simulated; the target is
`BET = Σ(Aᵢ × EUIᵢ) + PL` from Table 8.4.4.1.

```python
result = performance_compliance(
    model, vintage='2025', path='eui',
    archetypes={'Office': 'all'},          # archetype -> 'all' | [space names]
    process_loads_kwh=0,
    weather={'epw': ..., 'ddy': ...}, run_dir='runs/eui')
```

Floor areas are COMPUTED from the model per 8.4.4.1.(3) (unmapped area
distributes pro-rata per (4)); <90% archetype coverage or HDD ≥ 9000
hard-refuses. The proposed is checked against Table 8.4.4.2 (values + hourly
schedule profiles) and, when non-conformant, NORMALIZED to the table before
its annual run per 8.4.4.2.(1).

**`eui_supplement`** on a 2025 reference-path run computes BOTH verdicts. The
two paths simulate different proposed buildings (as-specified vs
Table-8.4.4.2-normalized), so the shared-run shortcut is only lawful when the
conformance check passes; otherwise `report['eui_path']` reports
`computed: False` with the mismatch list — unless `run_normalized=True`
authorizes the extra normalized run.

## Command line

`btap-compliance` wraps `performance_compliance` for people who would rather
not write Python. One model in; EUIs, a verdict, and the HTML report out.

```bash
btap-compliance model.osm --epw toronto.epw
btap-compliance model.osm --city toronto --quick
btap-compliance --list-cities
btap-compliance --help
```

Output is deliberately **ASCII-only** (the Windows console is CP437/CP1252),
and the margin is reported on **total site energy**, because that is what the
verdict compares — not EUI, which is shown alongside it.

**Exit codes** carry the diagnosis, so a script can branch on them:

| Code | Meaning |
|---|---|
| `0` | compliant |
| `1` | not compliant — a VERDICT, not an error |
| `2` | usage (bad flag, missing file, unresolvable HDD) |
| `3` | pre-flight refusal — the model was rejected before any simulation |
| `4` | simulation (EnergyPlus severe/fatal, or no engine) |
| `5` | internal |
| `6` | no determination (`--quick`, `--simulate sizing|none`) |

## Packaged reference data

`btap.necb.coverage` reads the NECB 2020/2025 Section 8.4 article caches that
ship with the wheel, offline; `btap-necb-coverage` is its console entry
point. The Crown NECB text is attributed in `data/coverage/ATTRIBUTION.md`
and is explicitly outside the LGPL that covers the code.

## Tests

```bash
cd python && .venv/bin/python -m pytest -q tests/necb/
```
