# The NECB gem family

Standalone, SDK-only Ruby gems implementing the **National Energy Code of Canada
for Buildings (NECB) 2020/2025 Part 8 performance path** — from authoring a model
out of nothing, through space-use loads, lighting, service water heating, HVAC and
envelope, to the full proposed-vs-reference determination and an AHJ-ready report.

Licensed **LGPL-3.0-or-later** (see [LICENSE](LICENSE)).

## The family

Dependency flow: `audit` ← everything; `geometry` → `loads` → (`lighting`, `shw`);
`hvac` and `envelope` stand alone; the umbrella composes the domain gems and runs
EnergyPlus via `simulation`.

| Gem | One line |
|---|---|
| [openstudio-audit](openstudio-audit) | the shared AuditLog + article-coverage emitter every other gem writes to |
| [openstudio-geometry](openstudio-geometry) | model creation: seven shape wizards, the bar-by-shape engine, measured-footprint massing, a 3D viewer |
| [openstudio-loads](openstudio-loads) | NECB space types, space-use loads, schedules, thermostats (the bare-geometry on-ramp) |
| [openstudio-lighting](openstudio-lighting) | Part 4 LPD allowances, daylighting controls, exterior lighting, fixture costing |
| [openstudio-shw](openstudio-shw) | Part 6 service-water-heating demand, Table 6.2.2.1 efficiencies, costing |
| [openstudio-hvac](openstudio-hvac) | 97-system topology catalog, Table 8.4.4.7.-A reference systems, efficiencies, HVAC costing |
| [openstudio-envelope](openstudio-envelope) | prescriptive Section 3.2, thermal bridging (TBD), reference envelope, costing |
| [openstudio-simulation](openstudio-simulation) | the EnergyPlus runner (local CLI backend + remote seam) |
| [openstudio-necb](openstudio-necb) | **the umbrella**: the full 8.4.1.2 proposed-vs-reference determination, one audit, the AHJ HTML report |

Each gem's README is its API guide.
[openstudio-necb/docs/README.md](openstudio-necb/docs/README.md) carries the family
glossary and the decision-register guide.

## The family contract

Every gem in this repository obeys the same rules:

- **Pure OpenStudio SDK.** No `openstudio-standards`, no measures, no BTAP.
- **Never simulates.** Only the umbrella (`openstudio-necb`) runs EnergyPlus.
- **One AuditLog schema** —
  `{step, target, action, inputs, value, article, ruling, evidence, building, level}`,
  levels `:decision | :info | :warning`. **Warnings are never silent.** The class
  lives in `openstudio-audit`; every other gem's `audit_log.rb` is a three-line
  alias of it.
- **Two citation axes.** `article:` cites the code that mandates a value;
  `ruling:` cites the adjudicated decision that says how we read it. Every id
  must exist in
  [openstudio-necb/docs/necb_decisions.md](openstudio-necb/docs/necb_decisions.md)
  and its machine-readable mirror; a drift test enforces both directions.
- **Audit text convention:** violations are SHOUTED, passes are lowercase — the
  report's checklist classifier is deliberately case-sensitive about this.
- **Article-coverage manifests.** Each vintage ruleset JSON declares what it
  implements; partial and not-implemented entries warn on every run.
- **Vintages 2020 and 2025 only.** 2011–2017 backfills are deferred.

## Requirements

- Ruby 3.2.2
- OpenStudio SDK 3.11.0 (`require 'openstudio'` must succeed; the SDK is
  deliberately not declared as a gem dependency)
- The `openstudio` CLI, for the tests that run EnergyPlus

## Testing

Each gem is self-contained:

```bash
cd openstudio-hvac && ruby test/test_catalog.rb
```

Cross-gem rule verification runs from the repository root:

```bash
rake necb:verify        # orphan-key lint + 8.4.6 curve probe + hostile-outcome tests
rake necb:coverage_doc  # regenerate the coverage documents
```

### Legacy-parity gates

The parity suites compare against a **pinned revision** of the NECB/BTAP
implementation in the `NatLabRockies/openstudio-standards` fork. See
[legacy_pin/README.md](legacy_pin/README.md) for the pinning mechanism and the
bump workflow.

```bash
LEGACY_PIN_REQUIRED=1 \
LEGACY_PIN_REMOTE=https://github.com/NatLabRockies/openstudio-standards.git \
BUNDLE_GEMFILE=$PWD/legacy_pin/Gemfile \
  bundle exec ruby test/test_apply_parity.rb
```

`LEGACY_PIN_REQUIRED=1` turns "oracle not bundled" from a skip into a failure —
CI and verification runs should always set it, because a skipped parity gate is a
green-but-vacuous gate.

## History

These gems were developed inside a fork of
[openstudio-standards](https://github.com/NatLabRockies/openstudio-standards)
between July and August 2026 and extracted here with their full history intact.
The fork remains the source of the pinned parity oracle.
