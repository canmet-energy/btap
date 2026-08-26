"""Measured-footprint massing: turn a real building outline (GeoJSON ring from
a building-stock source, a survey, a GIS export) plus a measured height into
zoned OpenStudio massing.

Unlike `wizards.py` and `bar.py` this is NOT a port of upstream code — there is
no upstream equivalent (it is the direct port of the gem's own footprint.rb).
The seven parametric wizards build their polygons analytically from
length/width, so winding and validity hold by construction; a measured ring
guarantees neither, and every function here exists because raw outlines break
something in the SDK:

- `Space.fromFloorPrint` needs CLOCKWISE-from-above vertices. Counter-
  clockwise returns an uninitialized Optional with no message — the single
  most expensive trap in this path, so `normalize` always forces winding.
- `openstudio.removeSpikes` / `openstudio.buffer` are boost-backed and want
  the same clockwise rings; a counter-clockwise ring comes back EMPTY.
- `openstudio.simplify` only drops collinear points — it does NOT decimate
  (a 69-vertex outline stays 69 vertices at a 1 m tolerance), so `decimate`
  implements Douglas-Peucker to keep surface counts sane.

SDK-only and offline, like the rest of the gem: this module takes a ring of
coordinates and never knows where they came from. Fetching records from a
building-stock service, choosing a storey height, and mapping a building
class to space types all belong to the caller.
"""

from __future__ import annotations

import json
import math

import openstudio

from btap._compat import opt, ruby_round, sorted_by_name
from btap.modeling.geometry import helpers

# WGS84 tangent-plane constants. Exact enough at building scale: on a
# 5,257 m2 downtown outline this reproduces the publisher's own area to
# within 0.2%.
M_PER_DEG_LAT = 111_132.0
M_PER_DEG_LON_EQUATOR = 111_320.0

# Storey heights worth naming rather than burying as magic numbers. The
# facade default stays the gem-wide 3.8 m; these are the two other values a
# measured-height workflow is likely to want.
TEN_FEET = 3.048        # the OpenStudio-standards create_space_from_polygon default
NRCAN_IMPLIED = 3.5     # implied by NRCan's own estimated_floors = round(height / 3.5)


def ring_from_geojson(geojson):
    """Pull the outer ring out of a GeoJSON Polygon/MultiPolygon (parsed dict
    or raw JSON string). Interior rings (holes) are dropped — a hole would
    need a courtyard-style build, not an extrusion.

    geojson: GeoJSON geometry dict, JSON string, or an [[lon, lat], ...] ring.
    Returns the outer ring as [lon, lat] pairs."""
    if isinstance(geojson, str):
        geojson = json.loads(geojson)
    if (isinstance(geojson, list) and len(geojson) > 0 and isinstance(geojson[0], list)
            and len(geojson[0]) > 0
            and isinstance(geojson[0][0], (int, float)) and not isinstance(geojson[0][0], bool)):
        return geojson

    if not isinstance(geojson, dict):
        raise ValueError("expected a GeoJSON geometry Hash or an [[lon, lat], ...] ring")

    geojson = {str(k): v for k, v in geojson.items()}
    if geojson.get("geometry") is not None:
        geojson = {str(k): v for k, v in geojson["geometry"].items()}
    coordinates = geojson.get("coordinates")
    if coordinates is None or len(coordinates) == 0:
        raise ValueError("GeoJSON geometry has no coordinates")

    gtype = geojson.get("type")
    gtype = "" if gtype is None else str(gtype)
    if gtype == "Polygon":
        return coordinates[0]
    if gtype == "MultiPolygon":
        return max(coordinates, key=lambda polygon: len(polygon[0]))[0]
    raise ValueError(f"unsupported GeoJSON type '{gtype}' (Polygon or MultiPolygon)")


def project(ring, lat0=None, lon0=None):
    """Project a WGS84 ring onto a local tangent plane in metres, centred on
    the ring's own centroid unless an origin is given. Pure trigonometry — no
    projection library, no network.

    ring: [lon, lat] pairs (degrees); lat0/lon0: tangent point (defaults to
    the ring centroid). Returns a list of openstudio.Point3d at z = 0."""
    if len(ring) < 3:
        raise ValueError("a footprint ring needs at least 3 coordinates")

    if lat0 is None:
        lat0 = sum(coordinate[1] for coordinate in ring) / float(len(ring))
    if lon0 is None:
        lon0 = sum(coordinate[0] for coordinate in ring) / float(len(ring))
    m_per_deg_lon = M_PER_DEG_LON_EQUATOR * math.cos(lat0 * math.pi / 180.0)
    return [openstudio.Point3d((coordinate[0] - lon0) * m_per_deg_lon,
                               (coordinate[1] - lat0) * M_PER_DEG_LAT, 0.0)
            for coordinate in ring]


def signed_area(points):
    """Shoelace signed area. Positive = counter-clockwise viewed from above,
    negative = clockwise (which is what the SDK wants everywhere below)."""
    return sum((point.x() * points[(index + 1) % len(points)].y())
               - (points[(index + 1) % len(points)].x() * point.y())
               for index, point in enumerate(points)) / 2.0


def area(points):
    return abs(signed_area(points))


def clockwise(points):
    """Force clockwise-from-above winding — the orientation
    `Space.fromFloorPrint`, `openstudio.removeSpikes` and `openstudio.buffer`
    all require."""
    return list(reversed(points)) if signed_area(points) > 0 else list(points)


def to_vector(points):
    vector = openstudio.Point3dVector()
    for point in points:
        vector.append(point)
    return vector


def normalize(points, tolerance=0.01):
    """Make a raw outline safe to extrude: drop the GeoJSON closing vertex and
    any duplicates, force clockwise winding, then let the SDK strip spikes and
    collinear points. Returns clockwise points ready for `fromFloorPrint`.

    points: projected ring (openstudio.Point3d); tolerance: SDK
    spike/collinear tolerance in metres."""
    points = list(points)
    while len(points) > 1 and is_same_point(points[0], points[-1], tolerance):
        points.pop()
    points = [point for index, point in enumerate(points)
              if not (index > 0 and is_same_point(point, points[index - 1], tolerance))]
    if len(points) < 3:
        raise ValueError(f"footprint collapsed to {len(points)} distinct vertices")

    points = clockwise(points)
    despiked = list(openstudio.removeSpikes(to_vector(points), tolerance))
    if len(despiked) >= 3:
        points = despiked
    simplified = list(openstudio.simplify(to_vector(points), False, tolerance))
    if len(simplified) >= 3:
        points = simplified
    return clockwise(points)


def is_same_point(a, b, tolerance):
    return abs(a.x() - b.x()) < tolerance and abs(a.y() - b.y()) < tolerance


def decimate(points, tolerance):
    """Douglas-Peucker decimation for a closed ring. `openstudio.simplify`
    will not do this — it only removes collinear points, so a 69-vertex
    outline survives a 1 m tolerance untouched and becomes 69 exterior walls
    per storey. Winding and (approximate) area are preserved.

    points: clockwise ring; tolerance: max perpendicular deviation in metres
    (<= 0 is a no-op). Returns a ring with 3+ vertices."""
    if tolerance is None or tolerance <= 0 or len(points) <= 4:
        return points

    # Split the closed ring into two open chains at the most distant vertex so
    # Douglas-Peucker (an open-polyline algorithm) cannot collapse the ring.
    anchor = points[0]
    opposite = max(range(len(points)), key=lambda index: distance2(anchor, points[index]))
    first_chain = points[:opposite + 1]
    second_chain = list(points[opposite:]) + [points[0]]

    kept = douglas_peucker(first_chain, tolerance)[:-1] + \
        douglas_peucker(second_chain, tolerance)[:-1]
    if len(kept) < 3:
        return points

    return clockwise(kept)


def douglas_peucker(chain, tolerance):
    if len(chain) < 3:
        return list(chain)

    first = chain[0]
    last = chain[-1]
    index = None
    furthest = 0.0
    for i in range(1, len(chain) - 1):
        deviation = perpendicular_distance(chain[i], first, last)
        if deviation > furthest:
            furthest = deviation
            index = i
    if index is None or furthest <= tolerance:
        return [first, last]

    return douglas_peucker(chain[:index + 1], tolerance)[:-1] + \
        douglas_peucker(chain[index:], tolerance)


def distance2(a, b):
    return ((a.x() - b.x()) ** 2) + ((a.y() - b.y()) ** 2)


def perpendicular_distance(point, line_start, line_end):
    dx = line_end.x() - line_start.x()
    dy = line_end.y() - line_start.y()
    length = math.sqrt((dx * dx) + (dy * dy))
    if length < 1e-9:
        return math.sqrt(distance2(point, line_start))

    return abs(((point.x() - line_start.x()) * dy) - ((point.y() - line_start.y()) * dx)) / length


# Core and perimeter must tile the outline to within this fraction of its
# area. The mitred offset below is EXACT on a convex outline (a 50x30
# rectangle tiles to 1500.0000 m2), but adjacent perimeter quads overlap at
# reflex corners, and a noisy outline has many: the 69-vertex downtown
# outline this module was built against has 33 reflex corners and overlaps
# by 1.28% raw, 0.26% decimated at 2 m, and 0.00% at 4 m. Rather than ship
# overlapping spaces, the offset self-polices and the caller decimates
# harder or accepts single-zone storeys.
TILING_TOLERANCE = 0.005

# What a caller can actually do about a rejection, in order of usefulness.
# Lowering perimeter_zone_depth is the real lever and costs NO area
# fidelity: over 40 consecutive NRCan records, core/perimeter succeeded on 6
# at the 15 ft default, 12 at 9.8 ft and 20 at 6.6 ft with the outlines held
# identical. Raising decimate_tolerance is the weak lever — 6 -> 12 at 4 m,
# and only 16 at a destructive 10 m (45% worst-case area loss).
ZONING_HINT = "lower perimeter_zone_depth, raise decimate_tolerance, or use zoning='single'"


def apply_wwr(model, ratio, audit=None):
    """Cut windows into every exterior wall to hit a window-to-wall ratio.

    PURE GEOMETRY, and deliberately so. There is NO default ratio and no code
    knowledge here: NECB's FDWR maximum is a btap.necb (envelope domain)
    concern (`NECB.max_fdwr(vintage=, hdd=)`, article 3.2.1.4), and this gem
    carries no NECB rules data by family contract. Callers pass a number they
    chose.

    This exists because the envelope pass CANNOT seed itself: it retargets
    EXISTING subsurface constructions, so on measured massing — which has zero
    windows and zero constructions — `apply_prescriptive(apply_fdwr=True)`
    silently produces 0 subsurfaces. Cutting the openings first gives it
    something to retarget.

    `ratio` may be a single float, or a dict keyed by compass bin
    ('North'/'East'/'South'/'West') for orientation-specific glazing — the
    natural companion to orientation-merged zoning. Bins left out of the dict
    get no windows.

    Returns {'walls':, 'glazed':, 'refused':, 'fdwr': achieved ratio}."""
    ratios = {str(k): v for k, v in ratio.items()} if isinstance(ratio, dict) else None
    if ratios is None and not (_is_numeric(ratio) and ratio >= 0.0 and ratio < 1.0):
        raise ValueError(f"wwr must be a Float in [0, 1) or a Hash of them, got {ratio!r}")
    if ratios is not None and any(not (_is_numeric(v) and v >= 0.0 and v < 1.0)
                                  for v in ratios.values()):
        raise ValueError(f"every wwr in {ratio!r} must be a Float in [0, 1)")

    walls = [surface for surface in model.getSurfaces()
             if surface.surfaceType() == "Wall"
             and surface.outsideBoundaryCondition() == "Outdoors"]
    glazed = 0
    refused = []
    for surface in sorted_by_name(walls):
        target = ratios.get(wall_orientation(surface)) if ratios is not None else ratio
        if target is None or target <= 0.0:
            continue

        # setWindowToWallRatio refuses walls it cannot cut cleanly (too small,
        # non-vertical, degenerate). It returns an empty Optional rather than
        # raising, so a silent skip is the danger here, not a crash.
        if surface.setWindowToWallRatio(target).is_initialized():
            glazed += 1
        else:
            refused.append(surface.nameString())

    wall_area = sum(s.grossArea() * space_multiplier(s) for s in walls)
    window_area = sum(sum(ss.netArea() for ss in s.subSurfaces()) * space_multiplier(s)
                      for s in walls)
    achieved = window_area / wall_area if wall_area > 0 else 0.0

    if refused and audit is not None:
        audit.warn("geometry", "walls refused glazing — the achieved ratio is below target",
                   inputs={"refused": len(refused), "walls": len(walls),
                           "examples": refused[:3]})
    if audit is not None:
        audit.decision("geometry", "windows cut to a caller-specified ratio",
                       inputs={"requested": ratio, "walls": len(walls), "glazed": glazed,
                               "refused": len(refused)},
                       value=f"achieved WWR {ruby_round(achieved, 4)}")
    return {"walls": len(walls), "glazed": glazed, "refused": len(refused), "fdwr": achieved}


def _is_numeric(value):
    """Ruby's Numeric check: booleans are NOT numeric there."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def wall_orientation(surface):
    """Compass bin of a wall, from the SDK's own azimuth."""
    return ORIENTATIONS[math.floor((((surface.azimuth() * 180.0 / math.pi) + 45.0) % 360.0) / 90.0)]


def space_multiplier(surface):
    space = opt(surface.space())
    return space.multiplier() if space is not None else 1


# Compass bins for perimeter grouping, N/E/S/W on 45 degree boundaries.
ORIENTATIONS = ("North", "East", "South", "West")


def edge_azimuth(a, b):
    """Outward-normal azimuth of the wall standing on edge a->b, in degrees
    clockwise from north — the same convention as `Surface#azimuth`.

    For a clockwise ring the interior lies to the RIGHT of travel (the rule
    `offset_edge` already relies on), so the inward normal is (dy, -dx) and
    the outward normal is (-dy, dx). Verified against the SDK on a rectangle:
    `Surface#azimuth` reports 270/0/90/180 for the four walls and this returns
    exactly the same four numbers."""
    return (math.atan2(-(b.y() - a.y()), b.x() - a.x()) * 180.0 / math.pi) % 360.0


def edge_orientation(a, b):
    """Compass bin for an edge: North is [315, 45), then East, South, West."""
    return ORIENTATIONS[math.floor(((edge_azimuth(a, b) + 45.0) % 360.0) / 90.0)]


def interior_angle(points, index):
    """Signed interior angle at vertex i, in radians. Greater than pi means a
    reflex (concave) corner."""
    count = len(points)
    previous = points[(index - 1) % count]
    current = points[index]
    following = points[(index + 1) % count]
    v1 = (previous.x() - current.x(), previous.y() - current.y())
    v2 = (following.x() - current.x(), following.y() - current.y())
    cross = ((current.x() - previous.x()) * (following.y() - current.y())) - \
            ((current.y() - previous.y()) * (following.x() - current.x()))
    dot = (v1[0] * v2[0]) + (v1[1] * v2[1])
    magnitude = math.hypot(v1[0], v1[1]) * math.hypot(v2[0], v2[1])
    if magnitude < 1e-12:
        return math.pi

    angle = math.acos(min(max(dot / magnitude, -1.0), 1.0))
    return (2 * math.pi) - angle if cross > 0 else angle


def max_perimeter_depth(points):
    """THE definition of an outline "clean enough" for core-and-perimeter
    zoning, and the largest perimeter depth it can carry.

    Offsetting inward shortens every wall run from both ends: a corner with
    interior angle t eats D/tan(t/2) off the edges meeting there. So edge i of
    length L survives only while

        L > D * (cot(t_i / 2) + cot(t_i+1 / 2))

    and the outline's ceiling is the smallest depth any edge allows. Reflex
    corners contribute a NEGATIVE term — they lengthen the offset edge — which
    is why concavity per se is harmless and vertex count is not the criterion.
    For the ordinary case of two convex right angles the term is 2D, i.e. at
    the 15 ft default NO wall run shorter than 9.14 m can carry a perimeter
    zone. Measured across 40 consecutive NRCan records this separates
    perfectly: every outline the full offset accepted had margin +2.03 m or
    better, every one it rejected was negative.

    points: clockwise ring. Returns the largest viable perimeter_zone_depth
    in metres."""
    count = len(points)
    if count < 3:
        return math.inf

    ceilings = []
    for i in range(count):
        length = math.hypot(points[(i + 1) % count].x() - points[i].x(),
                            points[(i + 1) % count].y() - points[i].y())
        consumed = (1.0 / math.tan(interior_angle(points, i) / 2.0)) + \
                   (1.0 / math.tan(interior_angle(points, (i + 1) % count) / 2.0))
        ceilings.append(length / consumed if consumed > 1e-9 else math.inf)
    return min(ceilings)


# The perimeter depth building codes actually mean: 15 ft, the daylit /
# skin-influenced band. `auto_perimeter_depth` only ever reduces it.
CONVENTIONAL_DEPTH = 4.57

# Floor on the automatic reduction, ~10 ft: the thinnest band that still
# reads as a daylit / skin-influenced perimeter rather than a construction
# line offset. It is also where spurious cores stop appearing — across 46
# NRCan records, dropping the floor to 1 m starts handing core-and-perimeter
# zoning to 55 m2 houses, which are all perimeter in reality; at 3 m the
# smallest outline that still zones is 104 m2 and the median depth returns
# to the full 15 ft convention. Below this, callers get 'single', which is
# the physically honest answer for a small building.
MIN_USEFUL_DEPTH = 3.0

# A core smaller than this fraction of the floor is a sliver, not a core —
# the zoning adds surfaces without adding information. NOT an invented
# number: the ported `create_shape_rectangle` already refuses core/perimeter
# unless BOTH plan dimensions exceed 2.5x the depth, which for a square is
# exactly a ((2.5 - 2) / 2.5)^2 = 4% core. Same convention, generalized to
# arbitrary outlines.
MIN_CORE_FRACTION = 0.04


def auto_perimeter_depth(points, convention=CONVENTIONAL_DEPTH):
    """Perimeter depth fitted to the outline rather than to the building's
    size.

    Footprint SIZE is not usable here — measured over 40 consecutive NRCan
    records, the correlation between sqrt(area) and the depth an outline can
    carry is +0.198 (log-log +0.069), i.e. none: the ceiling is set by the
    SHORTEST WALL RUN, a local detail feature, and buildings under 15 m across
    had a HIGHER median ceiling (2.88 m) than 30-50 m ones (1.66 m). Scaling
    depth with size would be guessing.

    What is usable is the outline's own measured ceiling. This keeps the
    conventional 15 ft wherever the geometry allows it and backs off only
    where it must — raising the zoned share of that batch from 6/40 to 14/40
    while 6 buildings keep the full 15 ft. The 5% headroom keeps the binding
    wall run off the exact boundary.

    points: clockwise ring; convention: the depth to use when geometry
    permits. Returns the usable depth, or None when even the minimum will not
    fit."""
    depth = min(convention, max_perimeter_depth(points) * 0.95)
    return depth if depth >= MIN_USEFUL_DEPTH else None


def core_and_perimeter(points, depth):
    """Core-and-perimeter zoning for an arbitrary outline, by mitred inward
    offset: every outer edge is pushed inward by `depth` and adjacent offset
    lines are intersected, so the inner ring has the SAME vertex count as the
    outer one and outer edge i maps to perimeter zone i.

    Never returns a broken layout. When the offset is not viable — outline too
    narrow for a core, mitre blow-up at a reflex corner, parallel adjacent
    edges, or pieces that do not tile — it reports why, and the caller falls
    back to single-zone storeys and says so in the audit.

    points: clockwise ring; depth: perimeter zone depth in metres.
    Returns {'core':, 'perimeters':, 'tiling_error':, 'orientations':} on
    success, {'rejected': <reason>} otherwise."""
    if depth is None or depth <= 0:
        return {"rejected": "perimeter_zone_depth must be positive"}
    if len(points) < 4:
        return {"rejected": f"outline has only {len(points)} vertices"}

    # Cheap, exact, and precise about the fix: the binding constraint is
    # almost always a wall run too short to survive the offset from both ends.
    viable = max_perimeter_depth(points)
    if viable <= depth:
        return {"rejected": "wall runs too short for a %.2f m perimeter — this outline "
                            "supports perimeter_zone_depth up to %.2f m; %s"
                            % (depth, viable, ZONING_HINT)}

    count = len(points)
    inner = []
    for i in range(count):
        previous_edge = offset_edge(points[(i - 1) % count], points[i], depth)
        current_edge = offset_edge(points[i], points[(i + 1) % count], depth)
        intersection = intersect_lines(*previous_edge, *current_edge)
        if intersection is None:
            return {"rejected": f"parallel adjacent edges at vertex {i}"}
        if math.sqrt(distance2(points[i], intersection)) > depth * 6.0:
            return {"rejected": f"mitre blow-up at vertex {i} (sharp corner) — {ZONING_HINT}"}

        inner.append(intersection)

    outer_area = area(points)
    core_area = area(inner)
    if core_area < 1.0 or core_area >= outer_area:
        return {"rejected": f"no viable core at {depth} m depth (outline too narrow)"}
    if core_area / outer_area < MIN_CORE_FRACTION:
        return {"rejected": "core would be only %.1f%% of the floor (min %.0f%%) — a sliver, "
                            "not a core; %s" % (core_area / outer_area * 100,
                                                MIN_CORE_FRACTION * 100, ZONING_HINT)}
    if signed_area(inner) * signed_area(points) <= 0:
        return {"rejected": f"inward offset self-intersected (winding flipped) — {ZONING_HINT}"}
    # The defining property of a valid core: every core vertex stands at least
    # `depth` from every wall. Weaker tests are not enough — a symmetric
    # over-offset (each edge pushed past the far side) leaves an 8x6 outline
    # with an inverted core that is still inside the outline AND still
    # correctly wound, so it passes both the area and the winding checks
    # above. Counting violations also separates the two distinct failures:
    # EVERY corner too close means the outline is too narrow for a core at
    # all; a few means the outline is locally too spiky.
    escaped = sum(1 for point in inner
                  if not is_inside(point, points) or clearance(point, points) < depth * 0.99)
    if escaped == len(inner):
        return {"rejected": f"no viable core at {depth} m depth (outline too narrow)"}
    if escaped > 0:
        return {"rejected": f"inward offset escapes the outline at {escaped} of {len(inner)} "
                            f"sharp corners — {ZONING_HINT}"}

    perimeters = []
    for i in range(count):
        quad = [points[i], points[(i + 1) % count], inner[(i + 1) % count], inner[i]]
        unique = []
        seen = set()
        for point in quad:
            key = (ruby_round(point.x(), 4), ruby_round(point.y(), 4))
            if key in seen:
                continue
            seen.add(key)
            unique.append(point)
        quad = unique
        if len(quad) < 3 or area(quad) < 0.5:
            return {"rejected": f"degenerate perimeter zone at edge {i}"}

        perimeters.append(clockwise(quad))

    tiled = core_area + sum(area(quad) for quad in perimeters)
    error = abs(tiled - outer_area) / outer_area
    if error > TILING_TOLERANCE:
        return {"rejected": "perimeter zones overlap by %.2f%% — %s" % (error * 100, ZONING_HINT)}

    return {"core": clockwise(inner), "perimeters": perimeters, "tiling_error": error,
            "orientations": [edge_orientation(points[i], points[(i + 1) % count])
                             for i in range(count)]}


def offset_edge(from_point, to_point, depth):
    """Push an edge inward by `depth`. For a clockwise ring the interior lies
    to the right of the direction of travel."""
    dx = to_point.x() - from_point.x()
    dy = to_point.y() - from_point.y()
    length = math.sqrt((dx * dx) + (dy * dy))
    if length < 1e-9:
        return [from_point, to_point]

    normal_x = (dy / length) * depth
    normal_y = (-dx / length) * depth
    return [openstudio.Point3d(from_point.x() + normal_x, from_point.y() + normal_y,
                               from_point.z()),
            openstudio.Point3d(to_point.x() + normal_x, to_point.y() + normal_y,
                               to_point.z())]


def clearance(point, polygon):
    """Distance from a point to the nearest polygon edge."""
    distances = []
    for index, a in enumerate(polygon):
        b = polygon[(index + 1) % len(polygon)]
        dx = b.x() - a.x()
        dy = b.y() - a.y()
        length2 = (dx * dx) + (dy * dy)
        if length2 < 1e-18:
            distances.append(math.sqrt(distance2(point, a)))
        else:
            t = min(max((((point.x() - a.x()) * dx) + ((point.y() - a.y()) * dy)) / length2,
                        0.0), 1.0)
            distances.append(math.sqrt(((point.x() - (a.x() + (t * dx))) ** 2)
                                       + ((point.y() - (a.y() + (t * dy))) ** 2)))
    return min(distances)


def is_inside(point, polygon):
    """Ray-casting point-in-polygon (winding-agnostic)."""
    crossings = 0
    for index, a in enumerate(polygon):
        b = polygon[(index + 1) % len(polygon)]
        if (a.y() > point.y()) == (b.y() > point.y()):
            continue

        x_at = a.x() + (((point.y() - a.y()) / (b.y() - a.y())) * (b.x() - a.x()))
        if x_at > point.x():
            crossings += 1
    return crossings % 2 == 1


def intersect_lines(a1, a2, b1, b2):
    dx1 = a2.x() - a1.x()
    dy1 = a2.y() - a1.y()
    dx2 = b2.x() - b1.x()
    dy2 = b2.y() - b1.y()
    denominator = (dx1 * dy2) - (dy1 * dx2)
    if abs(denominator) < 1e-9:  # parallel adjacent edges
        return None

    t = (((b1.x() - a1.x()) * dy2) - ((b1.y() - a1.y()) * dx2)) / denominator
    return openstudio.Point3d(a1.x() + (t * dx1), a1.y() + (t * dy1), a1.z())


def auto_tolerance(footprint_area):
    """Decimation tolerance scaled to the building. A fixed tolerance cannot
    serve both ends of a real building stock: 2 m is mild on a 5,000 m2 tower
    and destroys a 100 m2 house (measured: 14.8% of its floor area). Tying it
    to the outline's own size holds the area loss roughly constant instead —
    a 25th of the footprint's characteristic width, floored so tiny outlines
    keep their shape and capped so huge ones still shed noise."""
    return min(max(math.sqrt(footprint_area) / 25.0, 0.25), 3.0)


def storeys_for(height_m, floor_to_floor_height):
    """Number of storeys implied by a measured height. Never returns less
    than 1."""
    if not float(floor_to_floor_height) > 0:
        raise ValueError("floor_to_floor_height must be positive")

    return max(ruby_round(float(height_m) / float(floor_to_floor_height)), 1)


def build_massing(model, plan, ring, storeys, floor_to_floor_height, multiplier="none"):
    """Extrude a cleaned clockwise ring into stacked, zoned, surface-matched
    storeys. `plan` is the {'core':, 'perimeters':} from `core_and_perimeter`,
    or None for one space per storey.

    multiplier: 'none' (build every storey) or 'mid' (ground/mid/top, mid
    carries a thermal-zone multiplier and adiabatic floors/ceilings).
    Returns the list of created spaces."""
    # Spaces stay ONE PER EDGE — that keeps the geometry exact and needs no
    # polygon union — while the thermal zone each space joins is its compass
    # bin. So a 19-edge outline yields 19 perimeter spaces but the 4 zones a
    # modeller expects. Zone membership, not geometry, is what "merge by
    # orientation" means here; a genuine polygon union would have to handle
    # non-contiguous same-facing walls (an L has two north faces) and would
    # need real clipping.
    if plan:
        layout = [("Core", plan["core"], "Core")]
        for i, quad in enumerate(plan["perimeters"]):
            orientation = plan["orientations"][i]
            layout.append((f"{orientation} {i + 1}", quad, orientation))
    else:
        layout = [("Whole Floor", ring, "Whole Floor")]

    levels = storey_levels(storeys, floor_to_floor_height, multiplier)
    spaces = []
    for level in levels:
        story = openstudio.model.BuildingStory(model)
        story.setName(f"Story {level['index']}")
        story.setNominalZCoordinate(level["z"])
        story.setNominalFloortoFloorHeight(floor_to_floor_height)

        zones = {}
        for name, polygon, group in layout:
            optional = openstudio.model.Space.fromFloorPrint(to_vector(polygon),
                                                             floor_to_floor_height, model)
            if not optional.is_initialized():
                raise RuntimeError(f"Space.fromFloorPrint rejected '{name}' on story "
                                   f"{level['index']} (winding or self-intersection — see "
                                   "the OpenStudio log)")

            space = optional.get()
            space.setName(f"Story {level['index']} {name}")
            space.setZOrigin(level["z"])
            space.setBuildingStory(story)
            zone = zones.get(group)
            if zone is None:
                zone = openstudio.model.ThermalZone(model)
                zone.setName(f"Story {level['index']} {group} ZN")
                zone.setMultiplier(level["multiplier"])
                zones[group] = zone
            space.setThermalZone(zone)
            spaces.append(space)

    helpers.match_surfaces(model)
    apply_boundary_conditions(spaces, levels, len(layout))
    return spaces


def storey_levels(storeys, floor_to_floor_height, multiplier):
    """Ground/mid/top level table. With 'none' every storey is real; with
    'mid' the middle storeys collapse into one multiplied storey placed at
    their mean height (the openstudio-standards story-multiplier convention)."""
    if multiplier == "mid" and storeys > 2:
        return [{"index": 0, "z": 0.0, "multiplier": 1, "position": "bottom"},
                {"index": 1, "z": floor_to_floor_height * ((storeys - 1) / 2.0),
                 "multiplier": storeys - 2, "position": "middle"},
                {"index": storeys - 1, "z": floor_to_floor_height * (storeys - 1),
                 "multiplier": 1, "position": "top"}]
    return [{"index": index, "z": floor_to_floor_height * index, "multiplier": 1,
             "position": ("bottom" if index == 0
                          else ("top" if index == storeys - 1 else "middle"))}
            for index in range(storeys)]


def apply_boundary_conditions(spaces, levels, spaces_per_storey):
    """Bottom floors meet the ground; surfaces that `match_surfaces` could not
    pair because a multiplied storey stands in for many go adiabatic rather
    than leaking heat to Outdoors."""
    multiplied = any(level["multiplier"] > 1 for level in levels)
    for order, level in enumerate(levels):
        storey_spaces = spaces[order * spaces_per_storey:(order + 1) * spaces_per_storey]
        for space in storey_spaces:
            for surface in space.surfaces():
                if surface.outsideBoundaryCondition() == "Surface":
                    continue

                if surface.surfaceType() == "Floor" and level["position"] == "bottom":
                    helpers.set_boundary_condition([surface], "Ground")
                elif (multiplied and surface.surfaceType() in ("Floor", "RoofCeiling")
                      and not (surface.surfaceType() == "RoofCeiling"
                               and level["position"] == "top")
                      and not (surface.surfaceType() == "Floor"
                               and level["position"] == "bottom")):
                    helpers.set_boundary_condition([surface], "Adiabatic")
