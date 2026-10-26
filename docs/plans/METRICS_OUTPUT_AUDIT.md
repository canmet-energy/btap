# Metrics and output audit — what a run already produces, and what we read

Companion to [ARTICULATION_API_AUDIT.md](ARTICULATION_API_AUDIT.md), which
measured what a user can AUTHOR. This one measures what a finished simulation
makes AVAILABLE and what the package actually reads back. It was prompted by
phylroy's statement that the next stage of NECB research may include
electrification, peak reduction and operational resilience — two of which
need output axes the articulation audit never looked at.

Every number below was measured on one real run: the `proposed_with_hvac`
fixture, Toronto CWEC2020, run period 1–7 July, through `simulation.run`.

## The headline: peak and resilience data are ALREADY in every SQL we write

The articulation audit's companion claim — that "peak reduction has nothing" —
was **wrong**, and wrong in the same shape as the segfault claim it sits
beside: it measured what we COLLECT and reported it as what EXISTS.

`backends.py` requests `Output:SQLite, SimpleAndTabular` and
`Output:Table:SummaryReports, AllSummary`. That produces **29 tabular
reports**, of which three matter here and none is read:

| report | rows | carries |
|---|---|---|
| `DemandEndUseComponentsSummary` | 448 | coincident PEAK demand per end use per fuel, **plus the time of peak** |
| `AnnualThermalResilienceSummary` | 486 | Hours of Safety for Cold/Heat Events, Heat Index, Humidex, Unmet Degree-Hours, Discomfort-weighted Exceedance |
| `CO2ResilienceSummary` / `VisualResilienceSummary` | 9 / 12 | CO2 and illuminance level hours |

Measured samples from that one week:

```text
DemandEndUseComponentsSummary / End Uses
  Time of Peak        Electricity   03-JUL-07:30
  Interior Lighting   Electricity   6975.02 W
  Interior Equipment  Electricity   4185.01 W

AnnualThermalResilienceSummary
  Hours of Safety for Cold Events   168.00
```

"Hours of Safety for Cold/Heat Events" is the operational-resilience metric a
passive-survivability study asks for, and it costs nothing to produce because
we already produce it.

## How to read it: the escape hatch already exists

`SqlFile` has **no tabular accessor** — this is why the data looked absent.
Its typed readers cover annual energy and end uses only, and
`peakEnergyDemandByMonth`, the one peak-shaped method, returns EMPTY on our
SQL because it reads monthly meter tables that `AllSummary` does not populate.

But `SqlFile` does expose arbitrary SQL:

```text
execAndReturnFirstDouble / FirstInt / FirstString
execAndReturnVectorOfDouble / OfInt / OfString
execute
```

Measured on the existing attached `SqlFile` object, no new dependency:

```python
sql.execAndReturnFirstDouble(
    "SELECT Value FROM TabularDataWithStrings WHERE "
    "ReportName='DemandEndUseComponentsSummary' AND TableName='End Uses' "
    "AND RowName='Interior Lighting' AND ColumnName='Electricity'")
# -> 6975.02
```

**No new output request, no re-run, no new dependency, and no change to the
simulation lane.** A peak reader and a resilience reader are new FUNCTIONS
beside `energy_results`, not new infrastructure.

One caveat, and it is a real one: `btap` has no precedent for querying the SQL
directly. `runner.py` uses only typed accessors
(`totalSiteEnergy`, `electricityTotalEndUses`, `_end_use`, `_district`). Hand
-written SQL against table and column NAMES is positional access by another
route — the same class of fragility as `setDouble(7, …)` for the BIPVT PV
coverage fraction — so each query wants a named wrapper and a test that fails
when the report, table or column name moves. `_district`'s own comment records
that OpenStudio renamed district accessors across versions; tabular report
names can move the same way.

## Timeseries: OFF by default, and a solved problem next door

An earlier version of this section called timeseries "genuinely absent" and
proposed designing the request list. Both were wrong, and phylroy corrected
both: hourly output has to be TURNED ON, the `.rdd`/`.mdd` files say what is
available, and `canmet-energy/campus` already does all of it by default.

**I audited availability without reading the files that declare it.** Every
run already writes them:

```text
eplusout.rdd   540 lines — every output VARIABLE this model can report
eplusout.mdd   198 lines — every METER, including:
                 Output:Meter,Electricity:Facility,hourly;      [J]
                 Output:Meter,ElectricityNet:Facility,hourly;   [J]
                 Output:Meter,ElectricityNet:Plant,hourly;      [J]
```

`ElectricityNet:Facility` matters beyond this section: EnergyPlus already
distinguishes net from gross, so M4's generation axis has a meter waiting for
it rather than a calculation to invent.

### The reference implementation is `canmet-energy/campus`

`src/resources/buildings/measures/AddReportingOutputs/measure.py` is a
117-line measure that requests, by default:

- **13 hourly METERS** — `Electricity:Facility`, then per end use
  (`InteriorLights`, `ExteriorLights`, `InteriorEquipment`, `Heating`,
  `Cooling`, `Fans`, `Pumps`, `HeatRejection`, `WaterSystems`), plus
  `NaturalGas:Facility`, `Heating:NaturalGas`, `WaterSystems:NaturalGas`;
- **28 hourly VARIABLES** — zone sensible heating/cooling energy and rate, the
  four setpoint-not-met variables, the full zone air heat balance
  decomposition (surface convection, outdoor air transfer, internal
  convective, interzone, system air, system convective, air energy storage),
  the infiltration sensible and latent splits, OA mass flow, site drybulb and
  humidity ratio, windows transmitted solar, internal total and latent gains;
- `Output:SQLite` SimpleAndTabular and `OutputControl:ReportingTolerances`.

`src/buildings/sim/extract_timeseries.py` (566 lines) is the consumer, and it
settles the destination question this audit had left open. It reads the SQL
with **`sqlite3` in read-only URI mode** — `sqlite3.connect(f"file:{p}?mode=ro",
uri=True)` — into pandas, and writes
`output/database/timeseries/model=<name>/data.parquet`: wide, float32, zstd,
hourly `DatetimeIndex`, one column per series as `"<KeyValue>|<Name> [<Units>]"`.

It then layers DERIVED building-level loads under a `BUILDING` key —
`Space Heating Thermal Load [W]`, `Service Water Heating Load [W]`,
`Total Heating Thermal Load [W]`, **`Total Electricity Demand [W]`**,
`Total Site Energy [W]` — plus `[W/m2]` intensities normalised by Net
Conditioned Building Area, which makes them archetype-portable, with the
electricity and gas end-use breakdowns that drive its stacked charts.

So two corrections to this audit's own claims:

- **"`btap` has no precedent for querying the SQL directly" is wrong at the
  toolchain level.** The precedent is `sqlite3` + pandas in campus, not the
  SDK accessors. The named-wrapper caution below still holds for column names,
  but the approach is established rather than novel.
- **`BUILDING|Total Electricity Demand [W]` hourly IS peak information**, and a
  better route for research than `DemandEndUseComponentsSummary`: a profile
  gives the peak, the time, the duration, the shape and the shed, while the
  tabular report gives one number and one timestamp.

### What that leaves for this package

A real question rather than a task: **should `canmet-btap` produce hourly
output at all, or does campus remain the hourly consumer with this package
supplying the model?** Campus is derived from `bluesky` and carries the CFB
Gagetown archetypes, so it already owns an hourly pipeline end to end. The
answer determines whether M3 below is a feature here or a pointer to there.

## What a bare `simulation.run` does today

```text
ReportData            0 rows
ReportDataDictionary  0 rows
Time                  0 rows
availableTimeSeries   0 names
```

Nothing in THIS package requests an `Output:Variable` or `Output:Meter` at any
sub-annual frequency, which is why the measurement above is empty.
`runner.request_run_period_variables` sets `setReportingFrequency("RunPeriod")`
— a single summed value per variable, by design, for the rule-verification
lane. The only hourly request in product code is
`hvac/systems/hp_plant_fancoils.py`'s `District Heating/Cooling Water Rate`,
for downstream GLHX sizing.

### The cost, MEASURED

The one number nobody had. Annual runs of the `proposed_with_hvac` fixture
(5 zones), Toronto CWEC2020, identical model, `eplusout.sql` size:

| request | meters | MiB | vs baseline |
|---|---:|---:|---:|
| baseline (what we ship today) | 0 | 0.72 | 1.00x |
| `Electricity:Facility` only | 1 | 1.36 | **1.89x** |
| all 13 campus meters | 13 | 3.39 | **4.70x** |
| + campus's 28 zone variables | 13 | 45.43 | **62.86x** |

**The 28 zone variables are 42.04 of the 45.43 MiB — 93% of the total.**

That splits the cost by the ASK, and the split is the design:

- **an hourly electricity profile is nearly free.** +0.64 MiB buys the whole
  LDC, the peak, its time, its duration and the shed. Across the 56-scenario
  frozen corpus, all 13 meters would be roughly 190 MiB of generated SQL
  against about 40 MiB today — a real but ordinary increase;
- **the zone-level heat balance is what costs.** Those 28 variables are
  per-zone, so they scale with zone count, and at 2.5 GiB across the corpus
  they cannot be a default. They also serve campus's
  envelope-vs-infiltration-vs-internal decomposition, which is a different
  analysis from anything peak or resilience asks for.

So M3 wants TIERS, not a switch. An earlier version of this section said
hourly output "cannot be on by default" on the strength of the 62.86x number
alone, which attributed the zone variables' cost to the electricity profile.

### The tiers, by REQUIREMENT

phylroy's stated needs (2026-10-26) determine the split. Grouping the request
list by what each requirement reads, rather than by which repo asked for it:

**Tier 1 — meters only. ~5x baseline, and it covers four of the five needs.**

    Electricity:Facility
    InteriorLights / ExteriorLights / InteriorEquipment  (:Electricity)
    Heating / Cooling / Fans / Pumps / HeatRejection / WaterSystems
    NaturalGas:Facility, Heating:NaturalGas, WaterSystems:NaturalGas
    Boiler Heating Energy (variable, one series per boiler)

| requirement | what it reads |
|---|---|
| load-reduction measures | per-end-use hourly — lights, fans, pumps, equipment |
| peak reduction, load duration curve | `Electricity:Facility` hourly |
| district energy | `Boiler Heating Energy` hourly — see below, and NOT `Heating:EnergyTransfer` |
| cogeneration resilience | heat AND power on one index — the coincidence is the measured quantity, since a CHP unit is heat-led or electric-led and whether it carries critical load through an outage depends on the hour-by-hour ratio |

**Tier 2 — a few per-zone variables.** `Zone Mean Air Temperature` and the four
setpoint-not-met variables: what a free-float outage case reads, and what
unmet-hours needs. Five variables times zone count. Not yet measured.

**Tier 3 — the heat-balance decomposition. The 62.86x case, 93% of the cost.**
The seven `Zone Air Heat Balance *` variables plus the infiltration splits,
latent terms and humidity ratios. These answer WHY a load is what it is —
envelope versus infiltration versus internal versus interzone — which none of
the five requirements above asks. Load-reduction analysis needs the end-use
profile to measure a reduction, not the attribution of the underlying load.

### District energy: model it as a BOILER, and read the BOILER

phylroy's modelling call (2026-10-26): represent the district-energy
connection as a boiler, so one model serves both the DE case and the
on-site-boiler case rather than modelling the building twice. The building-side
load is identical either way, and the comparison becomes two READINGS of one
run instead of a difference between two runs — which also removes the chance
of an unintended geometry or load difference between variants.

One object then gives both answers:

    Boiler Heating Energy       the DE's hourly delivery obligation
    Boiler NaturalGas Energy    the same building as an on-site boiler

**`Heating:EnergyTransfer` IS NOT THE BUILDING'S HEAT LOAD, and an earlier
version of this section recommended it for district energy.** It would have
undersized by about half. Measured on the built-up VAV with hot-water coil,
scroll chiller and hot-water baseboards:

| series | MWh | what it is |
|---|---:|---|
| `Heating:EnergyTransfer` | 37.1 | air-system heating as delivered to zones |
| `Baseboard:EnergyTransfer` | 36.6 | the hydronic baseboards — a SEPARATE meter |
| `HeatingCoils:EnergyTransfer` | 44.1 | coil output, before zone delivery |
| **`Boilers:EnergyTransfer`** | **77.7** | the plant |
| **`Boiler Heating Energy`** | **77.7** | agrees, per boiler |
| **`Plant Supply Side Heating Demand Rate`** (HW loop) | **77.7** | agrees, per loop |

Three independent plant-side series agree at 77.7 MWh. The zone-side figure
misses the baseboards entirely, and `37.1 + 36.6 = 73.7` leaves about 4 MWh
(5%) of pump heat and loop losses up to the plant total — which a district
system must also deliver.

**How the wrong recommendation survived a check.** I had verified that
`Heating:EnergyTransfer` equals the sum of the per-zone
`Zone Air System Sensible Heating Energy` variables exactly, on two systems
(34.3 vs 34.3, and 37.1 vs 37.1), and concluded the single cheap meter was
sufficient. Both series are air-system-only, so they agree with each other and
NEITHER is the heat load. An equivalence between two quantities says nothing
about whether either answers the question — the same shape as this document's
other corrected claims.

The cost conclusion is unchanged and the series is still cheap: one variable
per boiler, measured at 4.15 MiB for the whole probe. Two caveats remain:

- a model with several boilers needs them summed, and a lead/lag pair reports
  the idle one as zero (`SECONDARY BOILER` was 0.0 here), so a reader must
  aggregate rather than take the first;
- the multipliers earlier in this section were measured on the baseboard
  fixture. A more complex system writes bigger tabular reports at baseline, so
  the portable figure is roughly **0.2 MiB per hourly series per year** rather
  than the ratio.

One more place hourly data may already be arriving and being discarded:
`backends.py:331` records that a completed REMOTE job returns **17 artifacts**,
and line 632 downloads exactly `("eplusout.sql", "eplusout.err")`. The 17
names are not recorded anywhere — only their keys — so whether a CSV or meter
file is among them is unknown and worth one look.

## What we read today

`runner.energy_results` returns annual-or-run-period site energy: `total_site_kwh`,
`electricity_kwh`, `natural_gas_kwh`, `district_heating_kwh`,
`district_cooling_kwh`, an `end_uses_kwh` breakdown of seven categories,
`floor_area_m2` and `eui_kwh_per_m2`. Plus `unmet_occupied_hours` and
`zone_unmet_occupied_hours`, which `compliance.py` already puts in each report
section.

That set is shaped by exactly one question — the 8.4.1.2 annual energy
comparison — which is correct for compliance and insufficient for all three
research themes.

## By theme

**Electrification** is the best served. Per-fuel annual totals and the end-use
breakdown already exist, so a fuel-switching comparison is reportable today.
What is missing is a GENERATION axis: no `GeneratorPhotovoltaic`,
`ElectricLoadCenter*` or solar-collector object is authored by this package, so
there is nothing on-site to report, and `energy_results` has no net-vs-gross
distinction. That is the same adjudication the articulation audit flagged for
P3 — whether generation is reported separately from consumption — and it is
sharper for a solar wall, which produces electricity AND preheated air from
one device.

**Peak reduction** splits into two things that this audit first conflated.

A peak VALUE and its time need no new output: read
`DemandEndUseComponentsSummary`. That is enough for a compliance-style report
line and almost nothing else.

Peak reduction RESEARCH needs the profile, and the reason is the **load
duration curve** — hourly load sorted descending against hours, which phylroy
named as the way to understand peaks. A peak number cannot distinguish a
needle from a plateau, and that distinction is the whole question:

- how many hours sit near the peak decides whether shaving is cheap or
  expensive;
- the AREA above a threshold is the energy a battery must hold, so storage
  sizing reads off the curve rather than off the peak;
- the curve's knee is where a demand charge stops being worth chasing.

An LDC is pure post-processing on hourly data — one sort, no new simulation
output — and it **cannot be built from `DemandEndUseComponentsSummary` at
all**, which gives one number and one timestamp.

Campus has the input and not the curve. `extract_timeseries` produces
`BUILDING|Total Electricity Demand [W]` hourly, and `reports/base_energy.py`
scales each archetype's `W/m2` intensity by real building areas to roll up a
whole-base hourly load — which is an LDC's input at campus scale. No load
duration curve exists in that repo (searched by content and by filename), so
it is a genuine gap in the toolchain rather than something to reuse.

So the instrument still comes before the experiment — a battery whose peak
reduction cannot be measured is untestable — but the instrument is the hourly
profile and a curve over it, not the tabular peak.

**Operational resilience** is further along than expected. The three
resilience reports are already produced, and `unmet_occupied_hours` is already
read and reported. A resilience study can start from existing data. What it
cannot do yet is model the EVENT — an outage is a schedule and availability
problem (equipment unavailable for a window), which is authoring work in
`btap.modeling`, not an output gap.

## Where this code belongs

phylroy's direction is that this is a research tool that will eventually
support new codes. The existing layering already carries that without
amendment:

- technologies — PV, battery, thermal storage, natural ventilation, solar
  wall — are generic authoring, so `btap.modeling`;
- metrics — peak, resilience readers — are generic result reading, so
  `btap.simulation`;
- when a code edition or family adopts any of it, a `btap.codes.<family>`
  layer cites it from above.

That is D-77 as written. The research work is not throwaway and not a parallel
stack: it is the substrate a future code layer reads. Which raises the bar,
because code written for research that a code layer will later cite needs the
same discipline as the compliance path even though it carries no AuditLog or
citations of its own.

## Proposed order

**M1 — a peak reader.** `DemandEndUseComponentsSummary` through
`execAndReturnFirstDouble`, named wrappers per metric, a test pinning each
report/table/column name so a rename fails loudly. Peak W and time of peak per
fuel per end use. No simulation-lane change.

Worth stating plainly: **M1 is cheap and is a dead end for the research.** It
gives a reportable number from data already on disk, which is worth having,
but it supports no load duration curve, no shed estimate and no storage
sizing. If peak REDUCTION is the goal rather than peak reporting, M3 is the
item that matters and M1 is a by-product of having the hourly data anyway.

**M2 — a resilience reader.** The same mechanism over
`AnnualThermalResilienceSummary`: hours of safety for cold and heat events
first, since those answer the survivability question directly.

**M3 — sub-annual meters, IF this package should own them.** Not a design
task: campus's `AddReportingOutputs` is the request list and
`extract_timeseries` is the reader, both working. The work is deciding
ownership, then measuring the SQL-size cost against the frozen corpus — which
is the one number nobody has.

**M4 — the generation axis and its adjudication.** Net versus gross in the
report; needed by PV, solar wall and battery alike, and an adjudication before
it is a coding question.

M1 and M2 are small, need no new dependency and no re-run, and give
reportable numbers for two of the three themes. But M1 answers "what was the
peak", not "how much of it can be removed" — so if the research question is
reduction, the order inverts and M3 leads, with M1 falling out of the same
data for free.

## What this audit did not establish

Whether the research themes want a report at all is now ANSWERED, and not by
this audit: campus writes partitioned Parquet with derived building-level
loads and `W/m2` intensities, which is what a researcher uses. The open
question is narrower — whether a compliance artifact and a research dataset
should come from one pipeline at all, given `report.json` carries
`compliance_determination`, three citation axes and the preflight gates, none
of which a research run wants.

Nor whether an outage event can be expressed with the authoring API as it
stands. That needs the schedules work the articulation audit lists as P2, and
was not probed here.
