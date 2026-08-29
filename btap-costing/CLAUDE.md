# CLAUDE.md — btap-costing

Consolidated costing (D-77): `BtapCosting::{HVAC,Envelope,Lighting,SHW}`,
sub-namespaced because `Database`/`Report` exist per domain. Depends on
btap-modeling + btap-audit only.

## The Python twin (btap.costing)

This gem is fully mirrored by `python/btap/costing/` (the port is complete —
D-79; `PORT_STATUS.md` at the repo root is the record). **A behaviour change
here is now PYTHON-ONLY (D-82: the R4 handoff stopped Ruby backports)**:
this gem is FROZEN verification infrastructure — do not change its
behaviour. The Python twin changes with a re-frozen scenario baseline in
the same PR; the dormant cross-language gates sit behind `BTAP_LEGB=1`
until R6 deletes this tree.

## Traps

- **The dependency direction is the design.** Costing never requires
  btap-necb. The daylighted-area sensor costing takes a
  `daylighting_areas:` provider (a callable `(space) ->
  {sidelighted_m2:, skylight_m2:}`); `BtapNECB::Lighting.cost` supplies it by
  default. When daylighting controls exist and no provider was passed,
  `Fixtures.cost` RAISES — silently under-costing is the failure this guards.
- **Priced tables**: placeholder copies live at `lib/btap_costing/data/`
  (`costs.csv`, `costs_local_factors.csv`) and are EXCLUDED from the Windows
  stage (`Rakefile` `PRICED_CSVS`). Resolution: explicit kwargs →
  `BTAP_COSTING_DIR`/`OPENSTUDIO_COSTING_DIR` → the placeholders. The old
  cross-gem resolution (envelope/lighting reading hvac's copies) is dead —
  do not resurrect it.
- **`Gem::MissingSpecError` descends from `LoadError`, not `StandardError`**
  (see envelope/database.rb history) — name it in rescues.
- The `'BTAP-ExteriorWall-Mass-2'`-style strings in envelope/assemblies.rb
  and the `NECB20xx` rows in lighting_sets.csv are CATALOG KEYS matched
  against the legacy database — never rename them with the module namespace.
- `BtapCosting::HVAC::Geometry.above_ground_storeys` DELEGATES to
  `BtapModeling::Helpers` (pure geometry the authoring systems also need).
- Tests that hide the priced CSVs (btap-necb's `test_cli.rb`) run in the
  Rakefile's SERIAL lane — a pooled neighbour reading the tables mid-window
  dies with "costs.csv not found".
