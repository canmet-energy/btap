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
necb-compliance my-building.osm --city toronto
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

Download `necb-compliance-setup-<version>.exe` and run it.

That is the whole prerequisite list. The installer carries its own copy of
**OpenStudio 3.11.0 and EnergyPlus 25.2.0**, so you do not need to install
either, and it will not disturb any OpenStudio you already have.

- It installs **per user** and needs **no administrator rights**, so there is no
  UAC prompt and it works on a locked-down machine.
- It writes nothing to system folders or the registry, and nothing to `PATH`
  unless you ask.
- Everything lives in one directory you can delete.

Then open **NECB Compliance (console)** from the Start menu and type
`necb-compliance --help`, or double-click `samples\run-demo.cmd` for a worked
example.

Building the installer yourself is covered in
[packaging/windows/README.md](packaging/windows/README.md).

### Not on Windows?

The tool is plain Ruby and runs anywhere OpenStudio 3.11 does. See
[docs/DEVELOPERS.md](docs/DEVELOPERS.md) for a source checkout.

---

## Running a check

```bat
necb-compliance MODEL.osm --city toronto
```

`--city` uses the weather files that ship with the installer;
`necb-compliance --list-cities` shows them. To use your own weather, pass
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

- **[NECB_GEM_COVERAGE.md](openstudio-necb/docs/NECB_GEM_COVERAGE.md)** — every
  article each gem declares, with its status and its gaps.
- **[NECB_8_4_COVERAGE.html](openstudio-necb/docs/NECB_8_4_COVERAGE.html)** —
  Section 8.4 article by article, down to sentence and clause text, showing
  where each is applied in the code.

As generated today, the rollup reports:

| | |
|---|---|
| implemented | **59** |
| partial — implemented with a declared gap | **23** |
| not implemented | **0** |
| field / document verification — no model can answer these | **7** |
| satisfied by construction (the reference is a clone of the proposed) | 5 |
| host or other-gem scope | 13 |
| cross-gem delegations | 13 |

Every partial and not-implemented entry **warns on every run** and appears in the
audit, so nothing in this list is hidden from a reviewer. These counts come from
the coverage document itself — follow the link for the current figures and, more
usefully, for each partial article's specific gap.

---

## Decisions and assumptions

Where the code needs interpreting, the interpretation is written down rather than
buried in the source. **75 decisions** are recorded in
**[necb_decisions.md](openstudio-necb/docs/necb_decisions.md)** — 40 of them
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
- **No article is wholly unimplemented.** 23 are partial — implemented with a
  declared gap; each gap is spelled out in the coverage document and warns on
  every run.
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
| [openstudio-audit](openstudio-audit) | the shared AuditLog + article-coverage emitter every other gem writes to |
| [openstudio-geometry](openstudio-geometry) | model creation: seven shape wizards, the bar-by-shape engine, measured-footprint massing, a 3D viewer |
| [openstudio-loads](openstudio-loads) | NECB space types, space-use loads, schedules, thermostats |
| [openstudio-lighting](openstudio-lighting) | Part 4 LPD allowances, daylighting controls, exterior lighting, fixture costing |
| [openstudio-shw](openstudio-shw) | Part 6 service-water-heating demand, Table 6.2.2.1 efficiencies, costing |
| [openstudio-hvac](openstudio-hvac) | 97-system topology catalog, Table 8.4.4.7.-A reference systems, efficiencies, HVAC costing |
| [openstudio-envelope](openstudio-envelope) | prescriptive Section 3.2, thermal bridging (TBD), reference envelope, costing |
| [openstudio-simulation](openstudio-simulation) | the EnergyPlus runner |
| [openstudio-necb](openstudio-necb) | **the umbrella**: the 8.4.1.2 determination, one audit, the AHJ report |

Each gem's README is its API guide.
[openstudio-necb/docs/README.md](openstudio-necb/docs/README.md) explains the
decision registers.

---

## Working on the code

See **[docs/DEVELOPERS.md](docs/DEVELOPERS.md)** — the family contract,
requirements, the devcontainer, MCP configuration, the test suites, and the
legacy-parity gates.
