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

## What is genuinely absent: timeseries

```text
ReportData            0 rows
ReportDataDictionary  0 rows
Time                  0 rows
availableTimeSeries   0 names
```

Nothing requests an `Output:Variable` or `Output:Meter` at any sub-annual
frequency. `runner.request_run_period_variables` exists but sets
`setReportingFrequency("RunPeriod")` — a single summed value per variable, by
design, for the rule-verification lane.

So anything needing a PROFILE rather than a peak — load shifting against a
tariff window, battery dispatch, hour-by-hour islanding — needs hourly or
timestep meters requested before the run. That is the only part of the three
research themes that requires new simulation-lane work, and it has a cost:
hourly meters on a large model inflate the SQL, which the frozen-scenario
corpus and the CI artifact budget both feel.

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

**Peak reduction** needs no new EnergyPlus output for a peak VALUE and time:
read `DemandEndUseComponentsSummary`. It needs timeseries for anything
dispatch-shaped. A peak metric should be added BEFORE any storage object,
because a battery whose peak reduction cannot be measured is untestable —
the instrument before the experiment.

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

**M2 — a resilience reader.** The same mechanism over
`AnnualThermalResilienceSummary`: hours of safety for cold and heat events
first, since those answer the survivability question directly.

**M3 — sub-annual meters, scoped.** `Output:Meter` at hourly frequency,
requested explicitly and off by default, with the SQL-size cost measured
before it goes anywhere near the frozen corpus.

**M4 — the generation axis and its adjudication.** Net versus gross in the
report; needed by PV, solar wall and battery alike, and an adjudication before
it is a coding question.

M1 and M2 are small, need no new dependency and no re-run, and unblock
measurement for two of the three themes. M3 is the only item with a cost worth
arguing about.

## What this audit did not establish

Whether the research themes need a report at all, or whether a researcher
would rather have a dataframe. Everything above assumes the existing
`report.json` is the destination, which is a compliance artifact with a
compliance shape; `compliance_determination`, the citation axes and the
preflight gates may all be wrong for a research run. That is a product
question, not a measurement.

Nor whether an outage event can be expressed with the authoring API as it
stands. That needs the schedules work the articulation audit lists as P2, and
was not probed here.
