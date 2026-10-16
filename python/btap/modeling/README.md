# btap.modeling

Model AUTHORING — the generic, NECB-free half of the family (and the
intended MCP tool surface). SDK-only, shared AuditLog schema, never
simulates. Four engines: the footprint wizards and the bar engine (verbatim
ports from openstudio-standards), a 3D viewer (ported from
canmet-energy/campus) and a per-storey 2D floor-plan renderer — plus, since
the by-nature refactor (D-77), the **HVAC authoring machinery**: the
103-system topology catalog, `build_system` / `replace_system`, the system
builders, coil/curve/schedule components, `classify.characterize`,
teardown, and the envelope authoring pieces (constructions, the
exposed-surface census).

## Layout

```
btap/modeling/
  geometry/   wizards, bar engine, footprints, plans, 3D render
  hvac/       103-system catalog + builders (systems/, components/, data/)
  envelope/   constructions + surface census
```

No `lighting/` or `shw/`: their authoring is NECB-table application and
lives in `btap.codes` — see [CLAUDE.md](CLAUDE.md).

## Modern HVAC systems

Six opt-in catalog rows add modern hydronic and air-system topology without
changing the existing rows:

- active and passive chilled beams use a dehumidifying/reheating 100% OA DOAS,
  electric baseboards, and 15/18 C tempered chilled water;
- hydronic radiant floors use the same latent-control strategy, 40/35 C
  low-temperature hot water, 15/18 C chilled water, native condensation
  control, and builder-owned internal-source floor constructions that preserve
  the input slab's layers and conductance. Zero-outdoor-air DX terminal units
  provide cooling trim and gas-boiler hot-water baseboards provide perimeter
  heat;
- rotary ERV VAV and sensible-only plate HRV PVAV variants use a central
  air-to-air exchanger, pretreat setpoint control, explicit frost/bypass
  inputs, current-SDK effectiveness curves, and gas-boiler hydronic perimeter
  trim; and
- true dual-duct VAV uses independent 35 C hot and 13 C cold decks with one
  `AirTerminalDualDuctVAV` per zone.

The chilled-beam and radiant rows reset chilled-water setpoints to the warmest
served-zone dew point plus a 2 K margin. Each zone dew point is evaluated once
into an EMS variable before comparison; inline `@TdpFnWPb` evaluation in an
Erl `IF` produced 2265 psychrometric failures per annual run in EnergyPlus
25.2. Plant loops are reused only when their source and full temperature
profile match. Existing VRF and DOAS+VRF systems already enable heat recovery;
that behavior is tested rather than exposed as a duplicate row.

All six rows must complete the standard five-zone annual simulation cleanly,
consume both heating and cooling energy, and remain at or below 100 occupied
unmet hours in each mode. This common gate was introduced after completed runs
left the original radiant topology at 636.75 heating / 3449 cooling unmet
hours, both beam rows at 411-420 cooling unmet hours, and both recovery rows at
468.5 heating unmet hours. The corrected annual results are:

| System | Heating h | Cooling h |
| --- | ---: | ---: |
| Active chilled beam | 49.00 | 76.25 |
| Passive chilled beam | 49.00 | 89.00 |
| Hydronic radiant floor | 51.00 | 0.00 |
| Rotary ERV VAV | 70.00 | 0.75 |
| Plate HRV PVAV | 70.00 | 0.75 |
| Dual-duct VAV | 54.00 | 0.00 |

On that fixture the radiant conversion retains the original concrete and
carpet material handles and 3.401 W/(m2 K) slab conductance; HVAC authoring
does not insert insulation. The unrelated pre-existing NECB System 2/5
water-coil sizing failure discovered by the reference-generation gate is
tracked in [#113](https://github.com/canmet-energy/btap/issues/113); no
code-driven sizing workaround is part of this modeling feature.

UFAD is not a catalog option. OpenStudio 3.11 can author the required
EnergyPlus room-air objects in a translated workspace, but has no typed,
persistent OpenStudio Model (`.osm`) representation. Post-translation
injection would also be bypassed by ordinary external translation and the
remote OpenStudio-model workflow, so shipping a UFAD name would overstate
portable model behavior.

## Footprint wizards

`create_shape_*` ported whole (rectangle, aspect-ratio with rotation,
courtyard, H, L, T, U): perimeter/core zoning per storey, matched surfaces.
Rectangle supports below-grade storeys with Ground boundary conditions; the
other shapes do not (the aspect-ratio wrapper delegates to rectangle but
fixes below-grade storeys at 0).

```python
import btap.modeling as modeling

model = modeling.create(shape='rectangle', length=40.0, width=25.0,
                        storeys=3, below_grade_storeys=1,
                        perimeter_zone_depth=4.0, audit=audit)
modeling.create(shape='l', length=40.0, width=40.0, storeys=2)
```

`storeys` / `below_grade_storeys` are the canonical spellings across the
facade; the engines' own names (`above_ground_storys`, `under_ground_storys`,
`num_floors`, `num_stories_above_grade`, `num_stories_below_grade`) remain
accepted, but passing a canonical name and its engine name together raises.
Unknown parameters raise — typos never silently fall to defaults.

## Measured footprints

`create_from_footprint(geojson=…, height_m=…, …)` takes a real outline (a
GeoJSON ring from a building-stock service, survey or GIS export) plus a
measured height and returns zoned storeys. It is deliberately a PEER of
`create`, not a member of the shape table: `create` dispatches positional
scalars, and a coordinate ring is not that shape. It stays SDK-only and
offline — fetching records, choosing a storey height and class→space-type
mapping are the caller's job. See [CLAUDE.md](CLAUDE.md) for the zoning
thresholds, which were measured rather than chosen.

## The bar engine (Goldwasser lineage)

`create_bar` + `bar_hash_setup_run` and their five polygon/space helpers,
ported verbatim. The DOE/DEER building-type-ratio wrappers are deliberately
NOT ported (they depend on CreateTypical metadata); instead the family-native
entry assigns **NECB space types by ratio in one step**, so geometry arrives
already standards-tagged for the loads pass:

```python
model = modeling.bar(
    space_type_ratios={('Space Function', 'Office enclosed > 25 m2'): 0.7,
                       ('Space Function', 'Corridor/Transition area other-sch-A'): 0.3},
    length=50.0, width=20.0, storeys=3, wwr=0.4,
    party_wall_stories_north=2, below_grade_storeys=1)
```

Slicing is ratio-true (verified to 1%), WWR is honoured per facade,
party-wall storeys go adiabatic, below-grade surfaces go Ground.

## The 3D viewer (campus port)

`render(model_or_path, path=…, height=…)` — the SDK `GltfForwardTranslator`
produces glTF, embedded as a base64 data URI in a Google `<model-viewer>`
page. Every export runs in a child process (`render_worker.py`) because the
C++ translator can SEGFAULT on un-triangulatable surfaces; the fallback
ladder then retries — full model → sub-surfaces removed (massing shell) →
binary-search removal of crashing base surfaces. Unrenderable models return
`''`, audited, never raising.

Trade-off carried from campus: the `<model-viewer>` SCRIPT loads from a CDN
at view time; the geometry itself is fully embedded. A CSP that blocks
external hosts will not run this viewer.

## Floor plans (per-storey 2D)

`floor_plans(model_or_path, path=…, png_dir=…, audit=…)` — the 2D
counterpart, for the everyday question *"what are the spaces and zones in
this model called?"*. One inline-SVG plan per storey: space footprints in
**world coordinates** (`space.transformation * surface.vertices`, so rotated
buildings draw rotated), filled by thermal zone from a deterministic palette,
labelled with space and zone name at the centroid, every polygon carrying a
`space | zone | space type | area` hover tooltip — plus a shared zone legend
and a metric scale bar.

```python
bundle = modeling.floor_plans(model, path='floor_plans.html')
[s['name'] for s in bundle['storeys']]   # ['Story 0', 'Story 1', 'Story 2']
bundle['storeys'][0]['svg']              # inline <svg>, embeddable anywhere
bundle['legend_svg']                     # the shared thermal-zone legend
```

The returned bundle — `{storeys: [{name, svg}], legend_svg, empty,
inferred_storeys, error}` — is the same never-raises shape the catalog
report's `model_diagrams` returns, so a host report (the NECB AHJ compliance
report) can embed the plans and degrade to a one-line note on an empty or
unreadable model.

The standalone page is **fully self-contained** — inline CSS and SVG, native
`<details>`, no scripts and no external references (one `break-inside: avoid`
section per storey, so printing gives a plan per page). Unlike the 3D viewer,
it renders under a strict CSP.

`png_dir` additionally rasterizes one PNG per storey if a system converter is
installed (`rsvg-convert` → `cairosvg` → `magick`); when none is, the audit
gets a loud warning and no PNG is written — PNGs are never a required output.

Storeys come from `BuildingStory` objects ordered by minimum world z. A model
without them falls back to binning floor elevations at ±0.01 m into
synthesized levels, flagged `inferred_storeys` plus an audit warning. Spaces
with no floor surface are warned and skipped; a space with floors at several
elevations is cut at the lowest one.

## Composing with the family

Bar and wizard output carries **no constructions** — downstream envelope work
retargets existing ones, so seed a basic construction set (or start from an
OSM that has one) before any envelope pass. With that, the full authoring
chain is in-package:

geometry → `btap.codes.necb.loads` → `btap.codes.necb.lighting` → `btap.codes.necb.shw` →
`modeling.build_system` → `btap.codes.necb.envelope` prescriptive →
`btap.codes.performance_compliance` (proposed + reference + costing, one
audit) — pinned by the full-family composition test in `tests/modeling/`.

## Citation conventions

`article=` in audit entries is the NECB clause that mandates a value;
`ruling='D-nn'` is the adjudicated reading of it. The registry is
[docs/necb_decisions.md](../../../docs/necb_decisions.md) plus its
drift-tested `btap/codes/data/decisions.json` mirror; `L-nn` cites the legacy
findings register. The family glossary lives in
[docs/README.md](../../../docs/README.md).

**No `article=` citation belongs in this subpackage** — it is code-agnostic
authoring by contract.

## Tests

```bash
cd python && .venv/bin/python -m pytest -q tests/modeling/
```

## Documented future

A seed-construction-set helper (candidate for the envelope domain) ·
FloorspaceJS import · the DOE/DEER building-type-ratio wrappers (host scope).
