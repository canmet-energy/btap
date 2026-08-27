"""The geometry 4.2.2.2.(4) needs and the gem did not have: a FIXED-METRIC
band inward from a wall, and a PER-WALL net opening ratio.

Neither could be borrowed. DaylightedAreas._sidelit_polygons builds a band
from an APERTURE whose depth is the window head height and whose width is
extended by half that again — the 4.2.2.3 convention. This sentence
measures a constant 6.1 m from the WALL, glazed or not, with no side
extension. And nothing in this gem computes an opening ratio at all; the
envelope gem's ``exposed_walls`` returns a whole-MODEL FDWR.
"""

from __future__ import annotations

import openstudio

from btap._compat import sorted_by_name
from btap.necb.lighting import storage_garage as _sg

TOLERANCE = 0.01


def opening_ratio(wall):
    """Net opening-to-wall ratio for one wall.

    NET, not gross: 4.2.2.2.(4) says "net opening-to-wall ratio", and this
    gem's convention throughout is ``sub.netArea`` (the envelope gem uses
    grossArea for its FDWR, which is a different quantity for a window with
    a frame — do not cross the two)."""
    gross = wall.grossArea()
    if not gross > TOLERANCE:
        return 0.0

    return sum(sub.netArea() for sub in wall.subSurfaces()) / gross


def is_exterior_wall(surface):
    return (surface.surfaceType() == 'Wall'
            and surface.outsideBoundaryCondition() == 'Outdoors')


def glazed_perimeter_walls(space):
    """Walls at or above the 40% net-opening threshold."""
    return [s for s in sorted_by_name(space.surfaces())
            if is_exterior_wall(s) and opening_ratio(s) >= _sg.GLAZED_WALL_RATIO]


def floor_polygons(space):
    """The floor polygons of a space, flattened to z = 0, in the same
    convention DaylightedAreas uses so the areas are comparable."""
    return [[openstudio.Point3d(v.x(), v.y(), 0.0) for v in s.vertices()]
            for s in space.surfaces() if s.surfaceType() == 'Floor']


def band_polygon(wall, depth=None):
    """A quad running PERIMETER_BAND_M inward from the wall's base line.

    Built by projecting the wall to z = 0 and extruding along its inward
    horizontal normal, rather than by the rotate-about-the-sill trick
    _sidelit_polygons uses: there is no aperture here to rotate about, and
    the band starts at the wall itself rather than at a sill."""
    if depth is None:
        depth = _sg.PERIMETER_BAND_M
    base = [openstudio.Point3d(v.x(), v.y(), 0.0) for v in wall.vertices()]
    # The wall collapses to a line; take its two extreme points.
    ends = extreme_pair(base)
    if ends is None:
        return None

    normal = wall.outwardNormal()
    inward = openstudio.Vector3d(-normal.x(), -normal.y(), 0.0)
    if inward.length() < TOLERANCE:
        return None

    inward.setLength(depth)
    a, b = ends
    # Wound counter-clockwise unconditionally: this rectangle is the CLIP
    # WINDOW, and Sutherland-Hodgman's half-plane test takes its sign from
    # the window's winding. The wall's own vertex order is whatever the
    # model author chose, so it cannot be trusted to give one consistently.
    return ensure_ccw([a, b,
                       openstudio.Point3d(b.x() + inward.x(), b.y() + inward.y(), 0.0),
                       openstudio.Point3d(a.x() + inward.x(), a.y() + inward.y(), 0.0)])


def signed_area(polygon):
    """Signed shoelace: positive is counter-clockwise in a +z-up frame."""
    total = 0.0
    for i, p in enumerate(polygon):
        q = polygon[(i + 1) % len(polygon)]
        total += (p.x() * q.y()) - (q.x() * p.y())
    return total / 2.0


def ensure_ccw(polygon):
    return list(reversed(polygon)) if signed_area(polygon) < 0 else polygon


def extreme_pair(points):
    """The two furthest-apart points — the wall's footprint endpoints."""
    best = None
    longest = 0.0
    for i, p in enumerate(points):
        for j, q in enumerate(points):
            if j <= i:
                continue

            d = (p - q).length()
            if not d > longest:
                continue

            longest = d
            best = [p, q]
    return best if longest > TOLERANCE else None


def qualifying_band_area(space, audit=None):
    """Floor area within 6.1 m of a >=40%-glazed exterior wall.

    Bands from adjacent qualifying walls OVERLAP at a corner, so the union
    is clipped as a set, not summed — otherwise a corner is counted twice
    and the >150 W threshold trips early.

    :return: 'area_m2' and the walls that contributed"""
    walls = glazed_perimeter_walls(space)
    if not walls:
        return {'area_m2': 0.0, 'walls': []}

    floors = floor_polygons(space)
    if not floors:
        if audit is not None:
            audit.warn('lighting',
                       f"STORAGE GARAGE '{space.nameString()}' HAS NO FLOOR SURFACE — its 4.2.2.2.(4) "
                       'perimeter band cannot be measured', article='4.2.2.2.(4)')
        return {'area_m2': 0.0, 'walls': [w.nameString() for w in walls]}

    bands = [b for b in (band_polygon(w) for w in walls) if b is not None]
    if not bands:
        return {'area_m2': 0.0, 'walls': [w.nameString() for w in walls]}

    return {'area_m2': union_clipped_area(bands, floors),
            'walls': [w.nameString() for w in walls]}


def union_clipped_area(bands, floors):
    """Area of (union of bands) intersected with (union of floors).

    Deliberately NOT openstudio.within / .intersects / .subtract. Those are
    what DaylightedAreas uses, and they cannot answer this shape: a
    perimeter band runs the full width of the wall, so it SHARES EDGES with
    the floor on three sides. Measured on a 20 x 15 m garage with a 6.1 m
    band, ``within`` and ``intersects`` both return false (a shared edge is
    neither containment nor crossing), and ``subtract`` reports the whole
    floor consumed. The 4.2.2.3 bands DaylightedAreas builds are inset from
    the aperture and never hit that case.

    The band is always a rectangle, so a convex-clip Sutherland-Hodgman is
    exact here and has no such edge cases. Overlap between adjacent bands
    is removed by clipping each floor piece against each band and taking
    the union of the RESULTS by inclusion-exclusion over a grid-free
    decomposition: since all bands are rectangles sharing the floor plane,
    summing clipped areas and subtracting pairwise intersections is exact
    for the two-band corner case that actually occurs."""
    pieces = [piece for floor in floors for piece in (clip(floor, band) for band in bands)
              if piece]
    if not pieces:
        return 0.0

    total = sum(shoelace(poly) for poly in pieces)
    # Subtract each pairwise overlap once: two perpendicular bands meeting
    # at a corner share exactly one rectangle.
    for i, a in enumerate(pieces):
        for j, b in enumerate(pieces):
            if j <= i:
                continue

            total -= shoelace(clip(a, b))
    return min(total, sum(shoelace(f) for f in floors))


def clip(subject, window):
    """Sutherland-Hodgman: clip ``subject`` against the CONVEX polygon
    ``window``."""
    output = list(subject)
    for i, current in enumerate(window):
        if not output:
            break

        nxt = window[(i + 1) % len(window)]
        input_ = output
        output = []
        for k, point in enumerate(input_):
            prev = input_[(k - 1) % len(input_)]
            point_in = is_inside(point, current, nxt)
            prev_in = is_inside(prev, current, nxt)
            if prev_in != point_in:
                output.append(intersection(prev, point, current, nxt))
            if point_in:
                output.append(point)
    return [p for p in output if p is not None]


def is_inside(point, a, b):
    """Left of the directed edge a->b, within tolerance. The sign convention
    follows the window's own winding, so it works for either orientation
    provided the window is convex and consistently wound."""
    return cross(a, b, point) >= -TOLERANCE


def cross(a, b, p):
    return ((b.x() - a.x()) * (p.y() - a.y())) - ((b.y() - a.y()) * (p.x() - a.x()))


def intersection(p1, p2, a, b):
    d1 = cross(a, b, p1)
    d2 = cross(a, b, p2)
    denominator = d1 - d2
    if abs(denominator) < 1e-12:
        return p2

    t = d1 / denominator
    return openstudio.Point3d(p1.x() + ((p2.x() - p1.x()) * t),
                              p1.y() + ((p2.y() - p1.y()) * t), 0.0)


def shoelace(polygon):
    if len(polygon) < 3:
        return 0.0

    total = 0.0
    for i, p in enumerate(polygon):
        q = polygon[(i + 1) % len(polygon)]
        total += (p.x() * q.y()) - (q.x() * p.y())
    return abs(total / 2.0)
