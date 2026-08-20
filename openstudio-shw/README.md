# openstudio-shw

NECB Part 6 service water heating — the sixth domain gem in the family. Depends
on **openstudio-loads** (SHW peak flows, target temperatures and the
`NECB-<letter>-Service Water Heating` schedules live in the space-type records)
and reuses the **openstudio-hvac** costing engine. SDK-only; vendored
article-tagged data verified via the codes MCP; shared AuditLog schema.

Vintages: **2020 and 2025.** The 2025 Table 6.2.2.1 was retrieved in full and
compared: every formula this gem implements is identical; the only substantive
change is heat-pump storage water heaters (EF ≥ 2.1 → UEF ≥ 2.23), a class
legacy never modeled (recorded in the rules data).

## Usage

```ruby
require_relative 'openstudio-shw/lib/openstudio_shw'  # pulls openstudio-loads

# demand + plant on a space-type-tagged model (after OpenStudioLoads apply_loads)
OpenStudioSHW.apply_shw(model, vintage: '2020', fuel: 'NaturalGas',
                        shw_scale: 1.0, audit: audit)
# -> per-space WaterUseEquipment/Connections + auto-sized WaterHeaterMixed loop
#    with the Table 6.2.2.1 performance already applied on the sized heater

# performance only (e.g. after a re-size)
OpenStudioSHW::NECB.apply_water_heater_efficiency(water_heater, vintage: '2020', audit: audit)

# reference treatment (8.4.4.20; 2025 renumbered)
OpenStudioSHW::NECB.reference_shw(model, vintage: '2020', audit: audit)

# costing (legacy shw_costing port on the openstudio-hvac engine)
report = OpenStudioSHW.cost(model, city: 'TORONTO', province_state: 'ONTARIO', audit: audit)
```

## What it does

- **Demand + tank sizing** (legacy-exact port of `auto_size_shw_capacity` /
  `model_add_swh`): per-space peaks (US gal/hr/ft² × area × scale), the weekly
  demand profile from the NECB SWH schedules, the peak-hour tank rule with the
  next-hour top-up (TRUE hour adjacency), capacity/parasitic arithmetic,
  per-space WaterUseEquipment. History (D-68): legacy's "next hour after
  peak" lookup originally indexed the unsorted hourly array with a
  *sorted*-array position (arbitrary hour, smaller tanks) — the gem preserved
  that defect for parity until upstream PR #2119 (merged 2026-07-15) fixed
  it; both sides now size by true adjacency and the parity gate compares
  live.
- **Water-heater performance** (Table 6.2.2.1, NECB2020 UEF procedure):
  electric standby-loss formulas → UA; gas/oil storage UEF ladders (first-hour
  rating = 0.7·V + 151 rule of thumb) with the Maguire-Roberts recovery/UA
  derivation; Et 0.9 + standby-loss formula for large equipment; the
  SWH-EFFFPLR-NECB2011 cubic part-load curve on fuel-fired heaters.
- **Reference SWH** (8.4.4.20): storage/power/energy-type identity is satisfied
  by construction in the umbrella (clone); the HP→ASHP rule is vacuous until HP
  SWH is modeled; sentences (3)–(4) sit in a PDF-extraction gap and are treated
  as Part 6 minimums (honest partial).
- **Costing**: tanks by fuel/efficiency class (small tanks that land on the
  Et = 0.9 row classify high-efficiency → PVC flue + power vent, matching
  legacy), galvanized flues with 20 ft headers, electric/fuel utility runs over
  the mech-room geometry, pumps (+VFD), tank-to-pump piping BOM. **Legacy
  defect fixed**: legacy's gas-line gate sums `num_reg_gas_tanks` twice, so
  HE-only-gas buildings get no fuel line; the port uses regular + HE.
  Distribution costing was never enabled in legacy — same here.

## Citation conventions

`article:` in audit entries = the NECB clause that mandates a value
(e.g. `6.2.2.1.`); `ruling: 'D-nn'` = the adjudicated reading of it (e.g.
`D-63` = the solar/pool apply-when-present minimums). The registry is
[openstudio-necb/docs/necb_decisions.md](../openstudio-necb/docs/necb_decisions.md)
(id-ordered index at the top) + its drift-tested `decisions.json` mirror.
Family glossary:
[openstudio-necb/docs/README.md](../openstudio-necb/docs/README.md).

## Testing

```bash
cd openstudio-shw
ruby test/test_shw.rb            # rules lint, loop+demand, efficiency bins, reference
ruby test/test_costing_e2e.rb    # costing (gas/electric/none), E+ water-systems energy,
                                 # family composition (loads+shw+hvac+envelope, ONE audit)
BUNDLE_GEMFILE=../legacy_pin/Gemfile bundle exec ruby test/test_shw_parity.rb
```

Parity: tank volume/capacity/parasitic/fuel and every per-space water-use
object EXACT vs legacy `model_add_swh`; 9 efficiency cases covering every
Table 6.2.2.1 bin EXACT vs the legacy NECB2020
`water_heater_mixed_apply_efficiency`.

## Section 6.2 prescriptive rules

Most of 6.2.3–6.2.7 governs installed hardware — a device that shuts a pool
heater off, an insulation thickness on a pipe run — that an energy model has no
object for. `necb/prescriptive.rb` checks the one rule a model *can* answer and
declares the rest by article, because silence reads as "not applicable" and
these very much apply.

| Article | |
|---|---|
| **6.2.4.1** temperature controls | **Implemented.** The tank is built with an automatic setpoint: a constant schedule installed as both the loop `SetpointManagerScheduled` and the `WaterHeaterMixed` setpoint, 2 °C deadband, `Cycle` control. |
| **6.2.5.1** remote/booster heaters | **Checked.** The fraction of design flow above 60 °C is computed from the per-space demand *before* `auto_size` collapses it to one `max_temp_c`. Note the sentence fires when that fraction is **small** — a minority high-temperature load may not drag the whole plant up to serve it. |
| **6.2.7** pools | **Partial.** Pool-heater minimums apply when a `SwimmingPoolIndoor` is present (D-63). 6.2.7.2 covers govern heated **outdoor** pools, and EnergyPlus models indoor pools only. |
| **6.2.3.1** piping insulation | Field-verified. No pipe objects, no pipe-run lengths — and Table 6.2.3.1 is known-damaged in the codes store. |
| **6.2.6** fixture flow limits | Field-verified. The demand data is a per-**area** aggregate with no fixture count, so a per-showerhead 7.6 L/min rate cannot be derived from it. |

Field-verified articles carry `gap_owner: "modeller"`, so they render as a scope
note rather than a failure the software could never clear (D-76).

## Documented future

Heat-pump and instantaneous water heaters (incl. the 2025 UEF ≥ 2.23 row and
the 8.4.4.20.(2) HP→ASHP reference rule) · the legacy geometric pump-head
calculation · SHW distribution costing · 2011–2017 backfill.

Section 6.2.3–6.2.7 is no longer a single "documented future" line. It was one
manifest row covering five articles, which hid that they have different answers;
it is now declared per article — see [Section 6.2 prescriptive rules](#section-62-prescriptive-rules).
