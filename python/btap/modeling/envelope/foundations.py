"""EnergyPlus Kiva foundations: which surfaces the engine accepts, how much slab
edge is exposed, and the ordered write that attaches one.

Code-agnostic, like everything in `btap.modeling`: this module decides WHICH
surfaces CAN carry a foundation and writes the objects. It sets no insulation
and carries no `article=` — NECB's 1.2 m perimeter strip (3.2.3.3.(3)) is
`btap.codes.necb.envelope`'s to prescribe, physically through Kiva or through
its declared simple-Ground equivalent-UA approximation.

Ported with attribution from `canmet-energy/openstudio-mcp` (SWR 26-035,
`mcp_server/skills/geometry/kiva_eligibility.py` and `kiva_apply.py`) at
revision 17e4deea. The interval-subtraction perimeter and the four SDK hazards
below are theirs, probed on OpenStudio 3.11.0 / EnergyPlus 25.2.0 — the pair
our CI image pins.

That upstream is NOT under a plain BSD licence: it carries the four-condition
OpenStudio(R) licence, copyright Alliance for Energy Innovation, LLC, whose
condition (1) requires source redistributions to retain the copyright notice,
the conditions and the disclaimer. They are reproduced in full in
`data/ATTRIBUTION.md` beside this file, which ships in the wheel. This file is
GPL-3.0-or-later as part of canmet-btap. See also
docs/plans/KIVA_FOUNDATION_PLAN.md.

SDK hazards, every one of which produces a silently wrong model:

  - `Surface.exposedPerimeter()` SEGFAULTS on a surface with no parent Space —
    no exception, the interpreter dies. `has_space()` is the guard and it is
    not optional. gbXML imports genuinely produce parentless surfaces.
  - `Surface.setAdjacentFoundation(kiva)` sets the boundary condition but
    LEAVES SunExposed/WindExposed intact, putting fictitious solar gain on a
    buried slab. `setOutsideBoundaryCondition("Foundation")` must come FIRST,
    because that one derives NoSun/NoWind.
  - `createSurfacePropertyExposedFoundationPerimeter` returns an INITIALIZED
    optional even when it discarded the input. `is_initialized()` is not a
    success signal: read both fields back and compare. A second call returns
    an empty optional rather than overwriting, so re-applying needs
    `resetSurfacePropertyExposedFoundationPerimeter()` first.
  - Neither `Surface.exposedPerimeter()` nor `joinAllPolygons()` can compute
    the perimeter we need: both assert |z| <= tolerance on every point, so a
    BASEMENT floor scores 0.0, and the join fills holes, so a building around
    an open COURTYARD loses the courtyard's edges entirely (a 3x3 ring of 10 m
    slabs gives 120 m where 160 m is right). Hence `exposed_perimeters`.

A known simplification, shared with the source: a basement floor at z=-3
abutting a slab at z=0 covers the shared edge in plan, in both directions.
Both are ground-contact, so the grade filter does not separate them.

`BySegment` is a legal IDD method and is deliberately not offered: EnergyPlus
cannot auto-correct a clockwise floor polygon under it and OpenStudio exposes
no segment API.
"""

from __future__ import annotations

import math

import openstudio

from btap._compat import opt, sorted_by_name

# Collinearity and overlap tolerance for the perimeter intervals, and the
# degenerate-edge floor. openstudio-mcp's POLYGON_JOIN_TOLERANCE_M.
TOLERANCE_M = 0.01
# A floor whose highest world z is at or below this counts as ground-contact,
# and only such a floor may cover another slab's edge.
GRADE_TOLERANCE_M = 0.01
# EnergyPlus refuses a Kiva wall with more vertices than this.
MAX_KIVA_WALL_VERTICES = 4
# The only exposed-perimeter method this module writes.
PERIMETER_METHOD_TOTAL = "TotalExposedPerimeter"


def has_space(surface) -> bool:
    """Guard for the `exposedPerimeter()` segfault. Never call that without this."""
    return surface.space().is_initialized()


def world_vertices(surface):
    """Surface vertices in world coordinates, or None when it has no parent space."""
    if not has_space(surface):
        return None
    return surface.space().get().transformation() * surface.vertices()


def _distance(p, q) -> float:
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5


def _xy_extent(vertices) -> float:
    """Longest horizontal distance between any two of a surface's vertices.

    NOT a bounding-box side. A wall at 45 degrees to the axes projects to a
    7.07 x 7.07 box, so `max(x_extent, y_extent)` reads 7.07 m for a 10 m wall
    and UNDER-counts — the dangerous direction for the E11 check below, because
    it lets through a model EnergyPlus will Fatal on. Measured by Fable on a
    space with `setDirectionofRelativeNorth(45)`: five 10 m walls (50 m true)
    against a 40 m slab edge were accepted where the unrotated control refused.
    """
    points = [(v.x(), v.y()) for v in vertices]
    return max(
        (_distance(p, q) for index, p in enumerate(points) for q in points[index + 1:]),
        default=0.0)


def _flat_edges(vertices) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """A polygon's edges as 2D endpoint pairs, z dropped, degenerate ones skipped."""
    points = [(v.x(), v.y()) for v in vertices]
    edges = []
    for index in range(len(points)):
        p, q = points[index], points[(index + 1) % len(points)]
        if _distance(p, q) > TOLERANCE_M:
            edges.append((p, q))
    return edges


def _covered_interval(edge, other, tolerance: float):
    """The [t0, t1] stretch of `edge` (metres from its start) lying under `other`, or None.

    `other` covers part of `edge` when both its endpoints are within `tolerance`
    of the line through `edge` and its projection overlaps by more than
    `tolerance`. Direction is irrelevant: a neighbour traverses a shared edge
    the other way, and a floor with flipped winding is still a neighbour.
    """
    (px, py), (qx, qy) = edge
    length = _distance(edge[0], edge[1])
    ux, uy = (qx - px) / length, (qy - py) / length
    projections = []
    for (x, y) in other:
        dx, dy = x - px, y - py
        if abs(dx * uy - dy * ux) > tolerance:   # perpendicular distance from the line
            return None
        projections.append(dx * ux + dy * uy)
    t0 = max(min(projections), 0.0)
    t1 = min(max(projections), length)
    if t1 - t0 <= tolerance:
        return None
    return t0, t1


def _exposed_length(own_edges, neighbour_edges, tolerance: float = TOLERANCE_M) -> float:
    """Length of `own_edges` not covered by any collinear stretch of `neighbour_edges`."""
    total = 0.0
    for edge in own_edges:
        length = _distance(edge[0], edge[1])
        intervals = sorted(
            interval for interval in (
                _covered_interval(edge, other, tolerance) for other in neighbour_edges
            ) if interval is not None
        )
        covered = 0.0
        current = None
        for t0, t1 in intervals:
            if current is None or t0 > current[1]:
                if current is not None:
                    covered += current[1] - current[0]
                current = (t0, t1)
            else:
                current = (current[0], max(current[1], t1))
        if current is not None:
            covered += current[1] - current[0]
        total += max(length - covered, 0.0)
    return total


def _duplicate_footprints(edges_by_floor) -> list:
    """Pairs of floors whose edge sets coincide within tolerance, either way round.

    Two coincident floors cover each other completely, so each would measure
    0.0 m of exposed edge and both would be refused. A twin is excluded from
    its twin's neighbours and reported instead.
    """
    def key(edges):
        def rounded(point):
            return (round(point[0], 3), round(point[1], 3))
        return sorted(tuple(sorted((rounded(p), rounded(q)))) for p, q in edges)

    keyed = {name: key(edges) for name, edges in edges_by_floor.items()}
    names = sorted(keyed)
    return [(a, b) for index, a in enumerate(names) for b in names[index + 1:]
            if keyed[a] == keyed[b]]


def coincident_surfaces(model, floors) -> list[dict]:
    """Ground floors with an exact co-planar counterpart elsewhere in the model.

    Absolute elevation is not evidence that a ``Ground`` boundary is wrong:
    model coordinates can be shifted arbitrarily. A second surface with the
    same world-coordinate polygon is evidence. Such a pair describes an
    interzone adjacency while one face still claims ground contact.
    """
    reported = {surface.nameString(): surface for surface in floors}

    def polygon_key(surface):
        vertices = world_vertices(surface)
        if vertices is None:
            return None
        return tuple(sorted(
            (round(vertex.x(), 3), round(vertex.y(), 3), round(vertex.z(), 3))
            for vertex in vertices
        ))

    keys = {}
    for surface in sorted_by_name(model.getSurfaces()):
        if surface.surfaceType() not in ("Floor", "RoofCeiling"):
            continue
        key = polygon_key(surface)
        if key is not None:
            keys.setdefault(key, []).append(surface)

    conflicts = []
    for name, floor in sorted(reported.items()):
        key = polygon_key(floor)
        if key is None:
            continue
        matches = [
            {
                "surface": other.nameString(),
                "surface_type": other.surfaceType(),
                "boundary_condition": other.outsideBoundaryCondition(),
            }
            for other in keys.get(key, [])
            if other.handle() != floor.handle()
        ]
        if matches:
            conflicts.append({"floor": name, "coincident_surfaces": matches})
    return conflicts


def exposed_perimeters(model, floors) -> dict:
    """Exposed slab-edge length per floor surface, by interval subtraction.

    Every floor's edges are projected to z=0; a floor's exposed perimeter is its
    edge length minus the stretches lying under a collinear edge of ANOTHER
    at-or-below-grade floor. Partial overlaps and T-junctions fall out of the
    interval arithmetic, and a courtyard keeps its edges because no floor lies
    on their far side.

    `floors` are the surfaces to report. Neighbours are drawn from every floor
    in the model, not just those reported, or an unreported abutting slab would
    leave its neighbour's shared edge counted as exposed.
    """
    reported = {s.nameString(): s for s in floors}
    edges_by_floor = {}
    neighbours_by_floor = {}
    skipped = []
    for surface in sorted_by_name(model.getSurfaces()):
        if surface.surfaceType() != "Floor":
            continue
        vertices = world_vertices(surface)
        if vertices is None:
            if surface.nameString() in reported:
                skipped.append(surface.nameString())
            continue
        name = surface.nameString()
        edges = _flat_edges(vertices)
        edges_by_floor[name] = edges
        # A floor covers a slab edge only if it is itself ground-contact. An
        # upper storey's plate sits directly ABOVE the slab in plan, so without
        # this filter a tower zeroes its own ground floor: measured on the
        # Hangar archetype as 38 of 45 slabs at 0.0 m and 143.1 m in total,
        # against 13 and 337.0 m once the filter is applied. Worse, a plate
        # that only PARTIALLY overlaps gives a wrong perimeter rather than
        # zero, so nothing refuses it. An interior floor matched to the ceiling
        # below reads 'Surface' and is excluded for the same reason.
        if (max(v.z() for v in vertices) <= GRADE_TOLERANCE_M
                and surface.outsideBoundaryCondition() != "Surface"):
            neighbours_by_floor[name] = edges

    twins = _duplicate_footprints(neighbours_by_floor)

    perimeters = {}
    duplicates = []
    for name in reported:
        own = edges_by_floor.get(name)
        if own is None:
            continue
        twinned = ({b for a, b in twins if a == name}
                   | {a for a, b in twins if b == name})
        if twinned:
            duplicates.append({"floor": name, "duplicates": sorted(twinned)})
        covering = [
            edge for other in sorted(neighbours_by_floor)
            if other != name and other not in twinned
            for edge in neighbours_by_floor[other]
        ]
        perimeters[name] = _exposed_length(own, covering)
    return {"perimeters": perimeters, "no_space": skipped,
            "duplicates": duplicates}


def _layers_are_standard_opaque(surface):
    """(ok, reason). EnergyPlus refuses a Foundation surface with no-mass layers."""
    construction = opt(surface.construction())
    if construction is None:
        return False, "no construction assigned"
    layered = opt(construction.to_LayeredConstruction())
    if layered is None:
        return False, "construction is not a layered construction"
    layers = layered.layers()
    if not layers:
        return False, "construction has no layers"
    for layer in layers:
        if opt(layer.to_StandardOpaqueMaterial()) is None:
            return False, (
                f"construction layer '{layer.nameString()}' is not a standard opaque "
                "material — EnergyPlus refuses massless layers on a Foundation surface"
            )
    return True, None


def kiva_blockers(surface, *, check_layers=True) -> list[str]:
    """Every reason EnergyPlus would refuse this surface as a Kiva surface.

    Empty means eligible. Each entry is a sentence naming the condition, so a
    caller can report it rather than restating the rule. ``check_layers=False``
    is the preflight used before a caller replaces a known no-mass material
    with a sourced Kiva-compatible representation; the final creation call
    always checks the resulting layers.
    """
    blockers = []

    surface_type = surface.surfaceType()
    if surface_type not in ("Floor", "Wall"):
        blockers.append(
            f"surface type is {surface_type}; Kiva accepts only Floor and Wall")

    if not has_space(surface):
        blockers.append("surface has no parent space")

    if len(surface.subSurfaces()) > 0:
        blockers.append(
            "surface carries windows or doors; the Foundation boundary condition is "
            "not allowed with subsurfaces")

    if surface_type == "Wall" and len(surface.vertices()) > MAX_KIVA_WALL_VERTICES:
        blockers.append(
            f"wall has {len(surface.vertices())} vertices; Kiva walls are limited to "
            f"{MAX_KIVA_WALL_VERTICES}")

    if check_layers:
        ok, reason = _layers_are_standard_opaque(surface)
        if not ok:
            blockers.append(reason)

    return blockers


def walls_exceed_perimeter(walls, perimeter_m: float):
    """The E11 refusal: paired wall length against the floor's exposed perimeter.

    EnergyPlus: "a combined length greater than the exposed perimeter of the
    foundation" is `** Fatal ** Kiva: Errors discovered, program terminates.`
    Measured by Fable while reviewing #121 — 80 m of wall against a 40 m
    perimeter — and refused here before anything is written.

    Returns (ok, reason). Wall length is the horizontal extent of each wall,
    which is what EnergyPlus pairs against the slab edge.
    """
    total = 0.0
    for wall in walls:
        vertices = world_vertices(wall)
        if vertices is None:
            return False, f"wall '{wall.nameString()}' has no parent space"
        total += _xy_extent(vertices)
    if total - perimeter_m > TOLERANCE_M:
        return False, (
            f"paired walls total {total:.3f} m against an exposed perimeter of "
            f"{perimeter_m:.3f} m; EnergyPlus treats a combined wall length greater "
            "than the exposed perimeter as a Kiva Fatal"
        )
    return True, None


def _write_exposed_perimeter(surface, perimeter_m: float):
    """Create the perimeter object and VERIFY it took. Returns a reason, or None.

    A Foundation surface with no exposed-perimeter object is fatal in
    EnergyPlus, and the constructor reports success even when it discarded the
    value, so both fields are read back.
    """
    if surface.surfacePropertyExposedFoundationPerimeter().is_initialized():
        surface.resetSurfacePropertyExposedFoundationPerimeter()
    created = surface.createSurfacePropertyExposedFoundationPerimeter(
        PERIMETER_METHOD_TOTAL, perimeter_m)
    if not created.is_initialized():
        return (f"OpenStudio would not create an exposed perimeter object on "
                f"'{surface.nameString()}'")

    obj = created.get()
    if obj.exposedPerimeterCalculationMethod() != PERIMETER_METHOD_TOTAL:
        return (
            f"exposed perimeter method did not take on '{surface.nameString()}': asked "
            f"for {PERIMETER_METHOD_TOTAL!r}, model holds "
            f"{obj.exposedPerimeterCalculationMethod()!r}")
    stored = opt(obj.totalExposedPerimeter())
    if stored is None or not math.isclose(stored, perimeter_m, rel_tol=1e-9, abs_tol=1e-9):
        return (
            f"exposed perimeter value did not take on '{surface.nameString()}': asked "
            f"for {perimeter_m}, model holds {stored}")
    return None


def create_kiva_foundation(model, floor, walls=(), *, perimeter_m=None, name=None) -> dict:
    """Attach ONE floor, and optionally its below-grade walls, to a new FoundationKiva.

    EnergyPlus allows exactly one floor per `Foundation:Kiva` object, so this
    takes one floor by design; a caller with several floors calls it several
    times. No insulation is set — that is the code layer's decision.

    Every refusal happens BEFORE anything is written, so a refused call leaves
    the model untouched. Returns
    `{'created': bool, 'foundation': name|None, 'floor':, 'walls': [...],
      'perimeter_m':, 'refusals': [...]}`.
    """
    walls = list(walls)
    refusals = []

    for surface, role in [(floor, "floor")] + [(w, "wall") for w in walls]:
        for blocker in kiva_blockers(surface):
            refusals.append(f"{role} '{surface.nameString()}': {blocker}")

    if floor.surfaceType() != "Floor":
        refusals.append(
            f"'{floor.nameString()}' is a {floor.surfaceType()}, not a Floor; "
            "EnergyPlus allows one floor per Foundation:Kiva object")
    for wall in walls:
        if wall.surfaceType() != "Wall":
            refusals.append(
                f"'{wall.nameString()}' was passed as a wall but is a "
                f"{wall.surfaceType()}")

    if perimeter_m is None and not refusals:
        measured = exposed_perimeters(model, [floor])
        perimeter_m = measured["perimeters"].get(floor.nameString())
        if perimeter_m is None:
            refusals.append(
                f"could not measure the exposed perimeter of '{floor.nameString()}'")
    if perimeter_m is not None and not math.isfinite(perimeter_m) and not refusals:
        # NaN passes every comparison below, and inf passes the small-value
        # gate, so both would reach the SDK write and be discarded there —
        # which is the only way the public API could reach the rollback.
        refusals.append(
            f"exposed perimeter for '{floor.nameString()}' is {perimeter_m}, which is "
            "not a finite length")
    if perimeter_m is not None and math.isfinite(perimeter_m) \
            and perimeter_m <= TOLERANCE_M and not refusals:
        refusals.append(
            f"'{floor.nameString()}' has an exposed perimeter of {perimeter_m:.3f} m; "
            "a Kiva floor needs exposed slab edge")

    if walls and not refusals:
        ok, reason = walls_exceed_perimeter(walls, perimeter_m)
        if not ok:
            refusals.append(reason)

    if refusals:
        return {"created": False, "foundation": None, "floor": floor.nameString(),
                "walls": [], "perimeter_m": perimeter_m, "refusals": refusals}

    kiva = openstudio.model.FoundationKiva(model)
    kiva.setName(name or f"Kiva Foundation {floor.nameString()}")

    # Snapshot every boundary condition BEFORE the write, because
    # `kiva.remove()` is not a rollback: it clears `adjacentFoundation` and
    # leaves the surface reading 'Foundation'. A surface in that state
    # forward-translates to a BuildingSurface:Detailed with a BLANK Foundation
    # reference, no translator error, and EnergyPlus resolves a blank reference
    # to its own default Foundation:Kiva — so a model the caller was told was
    # unmodified would run WITH a foundation. Measured by Fable on PR #132.
    original_conditions = {
        surface.nameString(): surface.outsideBoundaryCondition()
        for surface in [floor] + walls
    }

    # PIN A DEFAULTED CONSTRUCTION BEFORE THE FLIP. A surface whose
    # construction is resolved through a DefaultConstructionSet has no
    # construction at all once its boundary condition reads `Foundation`,
    # because the default set maps Ground but not Foundation: `construction()`
    # goes from the resolved object to None, and back again if the boundary is
    # reverted. Nothing refuses it — `kiva_blockers` ran while the surface was
    # still `Ground`, and the forward translator emits
    # `BuildingSurface:Detailed` with a BLANK Construction Name and NO error.
    # EnergyPlus then says `Missing required property 'construction_name'` and
    # FATALS, which the pipeline attributes to the submitted model.
    #
    # Measured by Fable on PR #133: 587 of the 588 ground floors in the shipped
    # archetypes are defaulted, and the six that took a foundation without also
    # taking an explicit construction clone — Office and Office-Small, Surface
    # 40 and Surface 221 — each lost their construction and made their
    # archetype unsimulatable. Every corpus fixture carries a CP02 layer and so
    # gets an explicit clone, which is why nothing in 2273 tests, 56 scenarios
    # or five green CI jobs saw it.
    pinned = []
    for surface in [floor] + walls:
        if not surface.isConstructionDefaulted():
            continue
        resolved = opt(surface.construction())
        if resolved is None:
            continue
        surface.setConstruction(resolved)
        pinned.append(surface)

    attached = []
    for surface in [floor] + walls:
        # ORDER IS LOAD-BEARING: the boundary condition first, because
        # setAdjacentFoundation leaves SunExposed/WindExposed intact and would
        # put solar gain on a buried slab.
        if not surface.setOutsideBoundaryCondition("Foundation"):
            refusals.append(
                "OpenStudio refused the Foundation boundary condition on "
                f"'{surface.nameString()}'")
            break
        if not surface.setAdjacentFoundation(kiva):
            refusals.append(
                f"OpenStudio refused to attach '{surface.nameString()}' to "
                f"{kiva.nameString()}")
            break
        attached.append(surface.nameString())

    if not refusals:
        reason = _write_exposed_perimeter(floor, perimeter_m)
        if reason is not None:
            refusals.append(reason)

    if refusals:
        # Unwind in the reverse order of the write, so nothing is left pointing
        # at an object that is about to go.
        if floor.surfacePropertyExposedFoundationPerimeter().is_initialized():
            floor.resetSurfacePropertyExposedFoundationPerimeter()
        kiva.remove()
        for surface in [floor] + walls:
            surface.setOutsideBoundaryCondition(
                original_conditions[surface.nameString()])
        # Hand the defaulted surfaces back to their default set, so a refused
        # call leaves no explicit assignment the caller did not have.
        for surface in pinned:
            surface.resetConstruction()
        return {"created": False, "foundation": None, "floor": floor.nameString(),
                "walls": [], "perimeter_m": perimeter_m, "refusals": refusals}

    return {"created": True, "foundation": kiva.nameString(),
            "floor": floor.nameString(), "walls": attached[1:],
            "perimeter_m": perimeter_m, "refusals": []}
