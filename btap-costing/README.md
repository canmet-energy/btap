# btap-costing

Capital costing for OpenStudio models — HVAC equipment BOMs, envelope
assemblies, lighting fixtures, and SHW — consolidated from the four domain
gems (D-77) so ONE gem owns the licensed-data seam.

## The licensed-data contract

The vendored CSVs are **unpriced placeholder schema copies** (RS-Means-derived
column layout). Real licensed values are injected at runtime and are **never
committed, never redistributed, never staged into the installer**:

1. `costs_csv:` / `local_factors_csv:` keyword arguments, or
2. a `BTAP_COSTING_DIR` directory (`OPENSTUDIO_COSTING_DIR` is honoured as the
   legacy name), else
3. the gem's own placeholder pair in `lib/btap_costing/data/`.

## Layout

```
lib/btap_costing/
  hvac/       Database, EquipmentQuantifier, Ventilation, Ledger, report
  envelope/   Database, assemblies, quantities, thermal-bridging costs
  lighting/   Database, fixture sets + daylighting-sensor BOM
  shw.rb      SHW costing on the hvac engine
  data/       shared priced pair + locations.csv; per-domain sheets below it
```

Dependencies: `btap-modeling` (it prices MODEL OBJECTS) and `btap-audit`.
**Never `btap-necb`** — where a costing rule needs NECB-owned geometry (the
daylighted-area sensors), the NECB layer passes a `daylighting_areas:`
provider in, and `Fixtures.cost` RAISES if controls exist and none is given.

## Tests

```bash
cd btap-costing && ruby test/test_hvac_costing_engine.rb   # plain ruby, no bundler
rake test:gem[btap-costing]
```
