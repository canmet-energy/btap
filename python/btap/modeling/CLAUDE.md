# CLAUDE.md — btap.modeling

Generic, code-agnostic authoring: everything that builds or edits an
OpenStudio model without knowing what a code requires. Depends on
`btap.audit` only.

[README.md](README.md) is the API guide. This file is the traps — most of
which were measured, not reasoned, and are expensive to rediscover.

## Layout

- `geometry/` — footprint wizards, the bar engine, measured footprints,
  plan/render tooling
- `hvac/` — the 97-system catalog + builders (`systems/`, `components/`,
  `data/`), classify, teardown, naming, canonical, validation
- `envelope/` — constructions machinery and the exposed-surface census

There is NO `lighting/` or `shw/` here: those domains had no code-free
authoring half — their "authoring" *was* applying NECB tables, so they live
wholesale in `btap.necb`. Only geometry, hvac and envelope had generic
machinery.

**No `article=` citation is permitted anywhere in this subpackage.** Rule
application lives in `btap.necb`; there is no article-coverage manifest here
because there is nothing to declare. `lint-imports` enforces the direction
(`btap.necb → btap.costing → btap.modeling → btap.audit`).

## Measured footprints — the part that is not a port

`geometry/footprint.py` has no upstream equivalent: the wizards build their
polygons analytically, so winding and validity hold by construction, which a
measured ring guarantees neither. Everything below was measured over real
NRCan building-stock records.

- **`Space.fromFloorPrint` needs CLOCKWISE-from-above vertices** and returns
  an uninitialized Optional with NO message otherwise — the caller dies later
  on a bare "Optional not initialized". `openstudio.removeSpikes` / `buffer`
  are boost-backed and want the same winding: a counter-clockwise ring comes
  back EMPTY, not reversed. `normalize` always forces winding; never hand a
  raw ring straight to the SDK.
- **`openstudio.simplify` does NOT decimate** — it only drops collinear
  points, so a 69-vertex outline survives a 1 m tolerance untouched and
  becomes 69 exterior walls per storey. `decimate` is Douglas-Peucker, split
  at the far vertex so a closed ring cannot collapse.
- **Mitred core/perimeter offset is EXACT on convex outlines** (a 50×30
  rectangle tiles to 1500.0000 m²) but adjacent perimeter quads OVERLAP at
  reflex corners, and real outlines are full of them (the Ottawa fixture: 33
  reflex of 69). So `core_and_perimeter` self-polices on **clearance** —
  every core vertex must stand ≥ depth from every wall — because the weaker
  area/winding/containment tests all pass on an inverted core from a
  symmetric over-offset. It returns a rejection reason rather than a broken
  layout, and the facade degrades to single-zone storeys with a warning.
- **What decides whether an outline can carry core/perimeter is WALL-RUN
  LENGTH against the offset depth — not vertex count, not concavity.** An
  inward offset eats `D/tan(t/2)` off both ends of every wall run, so edge i
  survives only while `L > D*(cot(t_i/2) + cot(t_{i+1}/2))`. Reflex corners
  contribute a NEGATIVE term, which is why concavity is harmless on its own
  (a 19-vertex outline with 37% reflex corners zones fine). For two convex
  right angles the term is `2D`, so **at the 15 ft default no wall run under
  9.14 m can carry a perimeter zone**. `max_perimeter_depth` returns the
  outline's own ceiling and the rejection quotes it. Over 40 consecutive
  NRCan records this separates perfectly — every accepted outline had margin
  ≥ +2.03 m, every rejected one negative — and the median outline's ceiling
  is only **2.59 m**, which is why the single-zone fallback is the common
  case on auto-extracted stock.
- **The lever is `perimeter_zone_depth`, not `decimate_tolerance`**, hence
  the `'auto'` default of `min(15 ft, 0.95 × ceiling)`. Lowering depth costs
  NO area (outlines held identical): 6/40 at a fixed 15 ft, 15/40 at 9.8 ft,
  24/40 at 6.6 ft. Decimating harder reaches 15/40 only at 4 m and 25/40 at a
  destructive 10 m (45% worst-case area loss). On full defaults the batch
  gets 14/40 core/perimeter, 6 keeping the full 15 ft, median depth 3.22 m.
  Any reduction below the convention warns — a narrowed band is no longer the
  code's daylit zone, so it must never be silent.
- **Footprint SIZE must NOT drive the depth.** Measured,
  `corr(sqrt(area), ceiling) = +0.198` (log-log +0.069) — none. The ceiling is
  set by the shortest wall run, a local feature: outlines under 15 m across
  had a HIGHER median ceiling (2.88 m) than 30–50 m ones (1.66 m). Only
  `decimate_tolerance` scales with size, and only because area LOSS does.
- **Perimeter zones merge by ORIENTATION, and it is zone membership that
  merges — not polygons.** Spaces stay one-per-edge (geometry exact, no
  polygon union, surface matching untouched) while each joins the thermal
  zone of its compass bin, so a storey presents North/East/South/West/Core
  however many edges the outline has. Across 46 records this capped zones per
  storey at 5 (was up to 20) with ZERO exterior walls in the wrong bin.
  `edge_azimuth` uses the SDK's own convention — outward normal, degrees
  clockwise from north — pinned against `Surface.azimuth`. A zone may hold
  NON-CONTIGUOUS spaces (an L has two north faces); that is legal in
  OpenStudio and is exactly why a real polygon union was not attempted.
- **Geometrically viable ≠ useful.** A 50×30 rectangle still offsets at
  14.9 m but leaves a 0.27% core, so `MIN_CORE_FRACTION` (4%) rejects
  slivers. The 4% is not invented: `create_shape_rectangle` already refuses
  core/perimeter unless both plan dims exceed 2.5× depth, which for a square
  is exactly a 4% core.
- **`MIN_USEFUL_DEPTH` is 3.0 m (~10 ft), not a token minimum.** `'auto'`
  will shrink depth to fit any outline, defeating the wizards' 2.5×-plan-dim
  convention (which presumes a FIXED depth). Over 46 records a 1 m floor
  starts handing core/perimeter to 55 m² houses — all perimeter in reality;
  at 3 m the smallest zoned outline is 104 m² and the median depth returns to
  the full 15 ft. Below the floor, callers get single-zone.
- **`decimate_tolerance` defaults to `'auto'`, and must.** A fixed tolerance
  cannot serve a whole building stock: at a flat 2 m the same batch lost
  14.8% of a small house's floor area (mean 1.60%), against 2.87% worst /
  0.67% mean once it scales as `sqrt(area)/25` clamped to [0.25, 3.0].

## Windows, thermostats, constructions

- **`apply_wwr(model, ratio)` is PURE GEOMETRY — no default, no code
  knowledge.** NECB's FDWR maximum is `btap.necb`'s envelope rule
  (`max_fdwr(vintage=, hdd=)`, article 3.2.1.4, vintages `'2020'`/`'2025'`
  — NOT `'NECB2020'`). Accepts a float, a dict of compass bins, or bins as
  keywords (`**bins`); bins left out get NO windows.
- **THERMOSTATS gate the whole envelope pass** (D-75 — an earlier note
  blamed construction seeding, wrongly). The conditioned-space test requires
  `partofTotalFloorArea` AND a zone `thermostatSetpointDualSetpoint`, and the
  exposed-wall/roof census filters on it. So on measured massing — zones but
  NO thermostats — the census returns 0 walls and a prescriptive pass with
  `apply_fdwr=True` bails silently at 0 subsurfaces. Add a dual-setpoint
  thermostat per zone and the SAME call yields 60 windows at FDWR 0.3667 with
  60/60 constructions, on a model that started windowless.
- **The envelope domain CAN seed fenestration constructions, but NOT opaque
  ones.** The subsurface target construction builds a SimpleGlazing
  construction at the prescriptive U from nothing. Opaque has no equivalent:
  surface assignment warns "no layered construction — skipped",
  `opaque_at_conductance` deep-copies a base you must supply, and the
  reference transform skips surfaces with no construction. An opaque SEED is
  still the real missing piece.
- **Wizard and bar output has NO constructions.** Envelope passes retarget
  EXISTING constructions, so authored models need a seed construction set
  before any envelope work.
- **Bar output IS standards-TAGGED** (SpaceTypes with
  standardsBuildingType/standardsSpaceType, sliced ratio-true to 1%); wizard
  output is NOT — run the loads assignment on it.

## Traps

- **Floor-plan zone colours hash zone names with a local djb2, never the
  builtin `hash()`.** Python randomizes `str` hashing per process
  (`PYTHONHASHSEED`), so colours would change on every run and every diff of
  a generated plan would be noise.
- **`rotate_model` leaves world coordinates INVARIANT.** It uses
  `changeTransformation`, re-expressing each space in a rotated LOCAL frame
  while the building stays put. Anything reading geometry must go through
  `space.transformation * surface.vertices`; the `space.xOrigin + local
  vertex` shortcut is rotation-blind and produces garbage after a rotate.
- **Every glTF export runs in a child process** (`render_worker.py`) because
  the C++ translator can SEGFAULT on un-triangulatable surfaces. Never call
  `modelToGLTF` in-process on untrusted geometry. The fallback ladder is
  full → sub-surfaces removed → binary-search the crashing base surfaces.
- **The 3D viewer loads `<model-viewer>` from a CDN at view time**; the
  geometry itself is embedded. A CSP that blocks external hosts will not run
  it. The 2D floor plan deliberately has no scripts and no external
  references, which is why it passes the self-containment assertions and the
  3D renderer cannot.
- `plan_query.py` is the ONLY SDK-touching file in the plan pipeline — plain
  dicts out, never raises. `plan_svg.py` holds a LOCAL COPY of the report's
  SVG primitives, copied rather than imported upward, because importing
  upward would invert the dependency direction.
- Bar space-type entries need ABSOLUTE floor-area values, not ratios — the
  facade converts.
- Full-family composition is pinned by test: bar geometry → loads → lighting
  → shw → hvac → envelope with ONE audit. Keep that green when changing
  output structure.

## The building-stock adapter

`python/scripts/building_stock.py` turns NRCan footprint records into
massing. It lives in `scripts/`, NOT in the package, so the networked fetch
sits beside its consumer without shipping in an SDK-only distribution
(D-71/D-72). `footprint.py` still never learns where a ring came from.

- Transport: stateless JSON-RPC `tools/call` over the shared HBIX client
  (`btap/_mcp.py`); the reply is an SSE `data:` frame whose
  `result.content[0].text` is itself JSON.
- Auth: `HBIX_API_KEY` — one key for all six servers. `HBIX_MCP_BASE_URL`
  repoints all six; there is no per-server override for either. Nothing is
  hardcoded; the key is never printed, never written to the cache, never
  stamped on a model.
- `--cache` / `--from-cache` split so a build is reproducible offline.
- The record is stamped onto `building.additionalProperties` as `nrcan_*`,
  deliberately NOT `setStandardsBuildingType` — `building_class` is NRCan's
  heuristic, not a standards building type.
- **The multiplier defaults to mid-floor here, unlike the package facade.**
  Stock work is bulk: a 28-storey record is 336 real spaces without it and 36
  with, for the same loads and envelope.

## Tests

```bash
cd python && .venv/bin/python -m pytest -q tests/modeling/
```

`tests/fixtures/footprint_ottawa_tower.json` is a REAL NRCan record (feature
`870226c8`, Ottawa K1P, 69 vertices / 33 reflex / 5,266 m² published /
82.65 m) kept verbatim so the traps above cannot quietly stop being tested.
Do not tidy it.
