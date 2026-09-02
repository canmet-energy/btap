# CLAUDE.md — btap.costing

Consolidated costing (D-77): `btap.costing.{hvac,envelope,lighting,shw}`,
sub-packaged because `Database` and the report modules exist per domain.
Depends on `btap.modeling` + `btap.audit` only.

[README.md](README.md) is the API guide and the licensed-data contract.
This file is what a change *here* costs.

## The dependency direction IS the design

```toml
[[tool.importlinter.contracts]]
name = "family dependency direction (D-77)"
type = "layers"
layers = ["btap.necb", "btap.costing", "btap.modeling", "btap.audit"]
```

`lint-imports` fails if costing ever imports `btap.necb`. It prices MODEL
OBJECTS; it owns no code rules. Where a costing rule needs NECB-owned
geometry — the daylighted-area sensor BOM — the NECB layer passes a
`daylighting_areas` provider **in**:

- a callable `(space) -> {'sidelighted_m2': …, 'skylight_m2': …}`;
- `btap.necb.lighting` supplies `_daylighting.costing_area_provider()` by
  default when the caller passes none;
- when the model HAS daylighting controls and no provider was given,
  `fixtures.cost` **raises**. Silently under-costing is the failure that
  guard exists to prevent — do not soften it to a warning.

## The licensed-data seam — do not commit prices

`data/costs.csv` and `data/costs_local_factors.csv` are **unpriced
placeholder schema copies** (RS-Means-derived column layout). Real licensed
values are injected at runtime and are never committed, never
redistributed, never staged into the installer. Resolution order:

1. explicit `costs_csv=` / `local_factors_csv=` keyword arguments;
2. a `BTAP_COSTING_DIR` directory (`OPENSTUDIO_COSTING_DIR` is honoured as
   the legacy name);
3. the vendored placeholder pair.

The Windows installer stages the placeholders deliberately — one artifact
behaving one way beats two — but the priced pair must never reach it. The
old cross-domain resolution, where envelope and lighting read hvac's copies,
is dead: do not resurrect it.

## Traps

- **Catalog keys are not namespaces.** The `'BTAP-ExteriorWall-Mass-2'`-style
  strings in `envelope/assemblies.py` and the `NECB20xx` rows in
  `lighting_sets.csv` are matched against the legacy database. Renaming them
  to match a module name breaks the lookup silently — the row simply is not
  found.
- **`hvac.geometry.above_ground_storeys` delegates to `btap.modeling`** —
  it is pure geometry the authoring systems also need, and it lives down
  there so both layers share one implementation.
- **Tests that hide the priced CSVs must not run beside tests that read
  them.** A pooled neighbour reading the tables mid-window dies with
  "costs.csv not found". Under `pytest -n auto` this shows up as a flake
  that passes on rerun; if you write such a test, make it restore state in
  a fixture rather than mutating process-wide paths.

## Tests

```bash
cd python && .venv/bin/python -m pytest -q tests/costing/
```
