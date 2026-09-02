# btap.costing

Capital costing for OpenStudio models — HVAC equipment BOMs, envelope
assemblies, lighting fixtures, and SHW — consolidated into one subpackage
(D-77) so a single place owns the licensed-data seam.

## The licensed-data contract

The vendored CSVs are **unpriced placeholder schema copies** (RS-Means-derived
column layout). Real licensed values are injected at runtime and are **never
committed, never redistributed, never staged into the installer**:

1. `costs_csv=` / `local_factors_csv=` keyword arguments, or
2. a `BTAP_COSTING_DIR` directory (`OPENSTUDIO_COSTING_DIR` is honoured as
   the legacy name), else
3. the subpackage's own placeholder pair in `data/`.

## Layout

```
btap/costing/
  hvac/       Database, equipment quantifier, ventilation, ledger, report, geometry
  envelope/   Database, assemblies, quantities, thermal-bridging costs
  lighting/   Database, fixture sets + daylighting-sensor BOM
  shw.py      SHW costing on the hvac engine
  data/       shared placeholder pair + locations.csv; per-domain sheets below it
```

Dependencies: `btap.modeling` (it prices MODEL OBJECTS) and `btap.audit`.
**Never `btap.necb`** — import-linter's layered contract fails the build if
that ever changes. Where a costing rule needs NECB-owned geometry (the
daylighted-area sensors), the NECB layer passes a `daylighting_areas`
provider in, and `fixtures.cost` **raises** if controls exist and none was
given, rather than silently under-costing.

## Tests

```bash
cd python && .venv/bin/python -m pytest -q tests/costing/
```
