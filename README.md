# NECB compliance for OpenStudio models

Check a building against the **National Energy Code of Canada for Buildings
(NECB) 2020 or 2025, Part 8 performance path** — Article 8.4.1.2, the
proposed-versus-reference determination.

You give it an OpenStudio model. It builds the reference building for you,
simulates both in EnergyPlus, applies the Part 8 rules, and writes a
self-contained HTML report you can hand to an authority having jurisdiction,
plus a complete audit trail of every decision it made and the code article
behind each one.

```
btap-compliance my-building.osm --city toronto
```

```
------------------------------------------------------------------
                   site kWh      kWh/m2/yr      area m2
Proposed              2,725            3.4        800.0
Reference             3,025            3.8        800.0
Margin                300.0   9.9% under target   Tier 1
Unmet hours  heating 0.8 / 24.8 h    cooling 13.5 / 0.0 h
------------------------------------------------------------------

  VERDICT: COMPLIANT   (NECB 2020, Division B, Article 8.4.1.2)
------------------------------------------------------------------
```

**This is a compliance-checking tool, not a design tool.** It tells you whether a
model passes and shows its work. It does not make a non-compliant building
compliant, and it does not repair a model that is not ready to be checked.

Licensed **LGPL-3.0-or-later** — see [LICENSE](LICENSE).

---

## Contents

| If you want to… | Go to |
|---|---|
| install it on Windows | [Installing](#installing-on-windows) |
| run your first check | [Running a check](#running-a-check) |
| understand what it decided and why | [Reading the results](#reading-the-results) |
| know which code articles are covered | [What is implemented](#what-is-implemented) |
| know where it makes a judgement call | [Decisions and assumptions](#decisions-and-assumptions) |
| know what it does **not** do | [Known limits](#known-limits) |
| work on the code itself | [docs/DEVELOPERS.md](docs/DEVELOPERS.md) |

---

## Installing on Windows

Download `btap-compliance-setup-<version>.exe` and run it.

That is the whole prerequisite list. The installer carries its own copy of
**OpenStudio 3.11.0 and EnergyPlus 25.2.0**, so you do not need to install
either, and it will not disturb any OpenStudio you already have.

- It installs **per user** and needs **no administrator rights**, so there is no
  UAC prompt and it works on a locked-down machine.
- It writes nothing to system folders or the registry, and nothing to `PATH`
  unless you ask.
- Everything lives in one directory you can delete.

Then open **NECB Compliance (console)** from the Start menu and type
`btap-compliance --help`, or double-click `samples\run-demo.cmd` for a worked
example.

Building the installer yourself is covered in
[packaging/windows/README.md](packaging/windows/README.md).

### Not on Windows?

The tool is plain Ruby and runs anywhere OpenStudio 3.11 does. See
[docs/DEVELOPERS.md](docs/DEVELOPERS.md) for a source checkout.

---

## Running a check

```bat
btap-compliance MODEL.osm --city toronto
```

`--city` uses the weather files that ship with the installer;
`btap-compliance --list-cities` shows them. To use your own weather, pass
`--epw path\to\file.epw` — a matching `.ddy` must sit beside it, because the
sizing runs need design days.

**Expect it to take 40–90 minutes.** A determination is four EnergyPlus
simulations — proposed sizing, proposed annual, reference sizing, reference
annual — plus up to three more if Article 8.4.1.2.(5) has to increase capacities
to meet the unmet-hours limits. Progress is printed as each phase starts.

`--quick` shortens the run to a single week so you can watch the pipeline work in
a few minutes. **It is not a code determination** and the tool refuses to report
a verdict for it — 8.4.1.2 requires a simulated year.

### The exit code is the answer

Useful if you are scripting this over many models:

| | |
|---|---|
| `0` | compliant |
| `1` | **not** compliant — a verdict, not an error |
| `2` | bad input (missing file, bad option) |
| `3` | the model was rejected before any simulation ran — see below |
| `4` | the simulation failed |
| `5` | internal error |
| `6` | no determination made (`--quick`, or `--simulate sizing`/`none`) |

### If you get exit 3: space types

The reference building can only be generated when every space type resolves
against the NECB catalog, so the tool checks that **before** spending an hour
simulating, and names every type it could not match along with the closest
catalog entries.

Models from BTAP or openstudio-standards already carry the right tags. Models
built by hand in the OpenStudio Application usually do not. Two ways forward:

- tag the model — set `standardsBuildingType` and `standardsSpaceType` on each
  space type to NECB catalog names; or
- let the tool apply NECB space-use loads for you:
  `--space-type "Space Function/Office enclosed > 25 m2"` for a uniform
  building, or `--space-type-map mymap.json` for a per-space mapping.

---

## Reading the results

Every run writes four things to the output directory:

| File | What it is |
|---|---|
| `compliance_report.html` | the AHJ-facing report — verdict, both buildings side by side, an article-by-article checklist, floor plans, HVAC schematics. One self-contained file. |
| `audit.txt` | every decision in order, each tagged with the code article behind it |
| `audit.json` | the same, machine-readable |
| `report.json` | the energy results and the determination |

**Read `audit.txt` when you want to know *why*.** Each line carries the article
it applied and, where the code needed interpreting, the decision id (`D-XX`)
that records how we read it. Warnings are never silent, and violations are
SHOUTED so they are greppable.

Both files survive a crash: if a simulation fails, the audit trail up to that
point is still written.

---

## What is implemented

Coverage is generated from the code, not hand-maintained:

- **[NECB_GEM_COVERAGE.md](btap-necb/docs/NECB_GEM_COVERAGE.md)** — every
  article each gem declares, with its status and its gaps.
- **[NECB_8_4_COVERAGE.html](btap-necb/docs/NECB_8_4_COVERAGE.html)** —
  Section 8.4 article by article, down to sentence and clause text, showing
  where each is applied in the code. One collapsible part per edition, each in
  its own article numbering — 2020's 8.4.4 is the reference building where
  2025's is the EUI path, so nothing is renumbered across editions.

As generated today, the rollup reports (the coverage document itself opens
with this table, then a collapsible section per vintage in that edition's own
article numbering):

| | NECB 2020 | NECB 2025 |
|---|---|---|
| Implemented | 63 | 65 |
| Partial (warns every run) | 27 | 28 |
| Not implemented (warns every run) | 4 | 4 |
| Satisfied by construction (clone) | 3 | 3 |
| Host / other-gem scope | 12 | 12 |
| Field / document verification (modeller scope, does not warn) | 10 | 10 |
| **Total entries** | **119** | **122** |

Counts are per-vintage rows, and coverage is declared **per sentence** where
the underlying work distinguishes sentences — so one article can contribute
several rows. The not-implemented rows are individual *sentences* — the
multi-energy capacity ratios (heating (5), cooling (4)) and two supply-air fan
clauses (8.4.4.18.(5)-(6)) — not whole articles; every article is at least
partially implemented.

Every partial and not-implemented entry **warns on every run** and appears in the
audit, so nothing in this list is hidden from a reviewer. These counts come from
the coverage document itself — follow the link for the current figures and, more
usefully, for each partial article's specific gap.

---

## Decisions and assumptions

Where the code needs interpreting, the interpretation is written down rather than
buried in the source. **75 decisions** are recorded in
**[necb_decisions.md](btap-necb/docs/necb_decisions.md)** — 40 of them
active at runtime, tagging the audit entries they govern.

A decision records what the code says, how we read it, what we rejected, and why.
They cover things such as which reference system a given proposed system maps to,
how the auxiliary-fuel election is decided for a heat pump, and how purchased
energy is represented.

The HTML report's **"Decisions and assumptions applied"** appendix lists the ones
that actually fired in *your* run — so a reviewer sees the judgement calls that
affected this building, not all 75.

---

## Known limits

Stated plainly, because a compliance tool that hides these is worse than useless:

- **It does not make a model compliant.** It checks and explains.
- **A model must be simulate-able and NECB-tagged** before it can be checked —
  see exit 3 above.
- **`--quick` is never a determination.** Article 8.4.1.2 requires a simulated
  year.
- **Multi-energy capacity ratios (8.4.4.9.(5) / 8.4.4.10.(4)) are not
  modelled.** A plant drawing on more than one energy source passes into the
  reference unchanged rather than being apportioned.
- **No article is wholly unimplemented.** Four individual *sentences* are —
  the multi-energy capacity ratios (8.4.4.9.(5) and 8.4.4.10.(4)) and two
  supply-air fan clauses (8.4.4.18.(5)-(6)) — and each is named as its own row
  in the coverage document and warns on every run.
- **Seven requirements are verified outside the model**, not by it — the
  whole-building air-leakage test (3.2.4.1, 3.2.4.2), service-water piping
  insulation and heat trace (6.2.3.1, 6.2.4.3), fixture flow limits (6.2.6),
  radiant space-temperature control, and the choice of climatic data set. These
  are code requirements on the *building*; an energy model has nothing to
  inspect. They are declared on every run so a reviewer sees them accounted for
  rather than absent.
- **Vintages 2020 and 2025 only.** 2011–2017 are not supported.
- **Costing is off unless you supply priced data.** The installer ships no
  priced cost tables; `--costs-csv` takes your own.

The full, current list — including every partial article's specific gap — is in
the coverage documents linked above. They are regenerated from the code and
checked in CI, so they cannot drift from what the software actually does.

---

## Sample models

The installer includes worked examples in `samples\`: one building with ten
different HVAC systems, plus six cases chosen to show the reference-building
rules doing something visible — purchased heating becoming a gas-fired boiler,
the storey count changing which reference system is selected, a staged
mixed-fuel plant, and the heat-pump auxiliary-fuel election.

Each is described in `samples\README.txt` with the article it exercises.

---

## The nine gems

The tool is assembled from nine standalone Ruby gems. Most users never need to
know this; it matters if you want to use one part on its own — say, NECB space
types without the compliance run.

| Gem | One line |
|---|---|
| [btap-audit](btap-audit) | the shared AuditLog + article-coverage emitter every other gem writes to |
| [btap-modeling](btap-modeling) | model AUTHORING, no NECB anywhere: seven shape wizards, the bar-by-shape engine, measured footprints, the 97-system HVAC topology catalog and builders, constructions, the surface census |
| [btap-costing](btap-costing) | capital costing (HVAC, envelope, lighting, SHW) and the licensed-data seam — placeholder tables vendored, real RS-Means values injected at runtime, never redistributed |
| [btap-necb](btap-necb) | **the code-compliance layer**: every NECB rule (loads, lighting, SHW, HVAC selection + efficiencies, envelope), the coverage manifests, the 8.4.1.2 determination, one audit, the AHJ report, and the `btap-compliance` CLI |
| [btap-simulation](btap-simulation) | the EnergyPlus runner (local, or the HBIX remote backend) |

Each gem's README is its API guide.
[btap-necb/docs/README.md](btap-necb/docs/README.md) explains the
decision registers.

---

## Working on the code

See **[docs/DEVELOPERS.md](docs/DEVELOPERS.md)** — the family contract,
requirements, the devcontainer, MCP configuration, the test suites, and the
legacy-parity gates.
