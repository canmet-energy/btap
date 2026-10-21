"""EnergyPlus Kiva foundations: which surfaces the engine accepts, how much slab
edge is exposed, and the ordered write that attaches one.

Code-agnostic, like everything in `btap.modeling`: this module decides WHICH
surfaces CAN carry a foundation and writes the objects. It sets no insulation
and carries no `article=` — NECB's 1.2 m perimeter strip (3.2.3.3.(3)) is
`btap.codes.necb.envelope`'s to prescribe, and it already does, via
`_apply_ground_strip`, once a foundation exists.

Ported with attribution from `canmet-energy/openstudio-mcp` (SWR 26-035,
`mcp_server/skills/geometry/kiva_eligibility.py` and `kiva_apply.py`), which
is BSD-licensed; this file is GPL-3.0-or-later as part of canmet-btap. The
interval-subtraction perimeter and the four SDK hazards below are theirs,
probed on OpenStudio 3.11.0 / EnergyPlus 25.2.0 — the pair our CI image pins.
See docs/plans/KIVA_FOUNDATION_PLAN.md and ATTRIBUTION.md.

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
    skipped = []
    for surface in sorted_by_name(model.getSurfaces()):
        if surface.surfaceType() != "Floor":
            continue
        vertices = world_vertices(surface)
        if vertices is None:
            if surface.nameString() in reported:
                skipped.append(surface.nameString())
            continue
        edges_by_floor[surface.nameString()] = _flat_edges(vertices)

    perimeters = {}
    for name in reported:
        own = edges_by_floor.get(name)
        if own is None:
            continue
        neighbours = [
            edge for other, edges in edges_by_floor.items() if other != name
            for edge in edges
        ]
        perimeters[name] = _exposed_length(own, neighbours)
    return {"perimeters": perimeters, "no_space": skipped}


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


def kiva_blockers(surface) -> list[str]:
    """Every reason EnergyPlus would refuse this surface as a Kiva surface.

    Empty means eligible. Each entry is a sentence naming the condition, so a
    caller can report it rather than restating the rule.
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
        xs = [v.x() for v in vertices]
        ys = [v.y() for v in vertices]
        total += max(max(xs) - min(xs), max(ys) - min(ys))
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
    if perimeter_m is not None and perimeter_m <= TOLERANCE_M and not refusals:
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
        kiva.remove()
        return {"created": False, "foundation": None, "floor": floor.nameString(),
                "walls": [], "perimeter_m": perimeter_m, "refusals": refusals}

    return {"created": True, "foundation": kiva.nameString(),
            "floor": floor.nameString(), "walls": attached[1:],
            "perimeter_m": perimeter_m, "refusals": []}
