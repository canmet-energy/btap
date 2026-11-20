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

## Costing a model

Every domain is costed the same way — `btap.costing.<domain>.cost(model, …)`
for `envelope`, `hvac`, `lighting` and `shw` — and resolves WHERE it is
costed the same way (#237):

- `city=` / `province_state=` name a row of `data/locations.csv`, matched
  ignoring case; a place the table does not list is REFUSED with the nearest
  spellings, rather than priced at the 100 % regional fallback;
- with no city, the cost location is the one nearest the model's SITE, and a
  model whose site was never set (latitude 0, longitude 0) is REFUSED rather
  than priced for St. John's, NL. Attaching a weather file sets the site.

Lighting takes the code id, `code="necb2020"`, like every public function.

**HVAC is costed from SIZED equipment.** On an autosized model the capacities
are unknown and items price at or near zero, with warnings. The
compliance pipeline sizes before it costs; for a model you authored, run a
sizing simulation in the same session first, so the model carries its sizing
results:

```python
from btap import simulation
from btap.costing import hvac

simulation.run(model, run_dir="runs/size", weather={"epw": epw, "ddy": ddy},
               sizing_only=True)
report = hvac.cost(model, city="Toronto", province_state="Ontario")
```

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
**Never `btap.codes`** — import-linter's layered contract fails the build if
that ever changes. Where a costing rule needs NECB-owned geometry (the
daylighted-area sensors), the NECB layer passes a `daylighting_areas`
provider in, and `fixtures.cost` **raises** if controls exist and none was
given, rather than silently under-costing.

## Tests

```bash
.venv/bin/python -m pytest -q tests/costing/
```
