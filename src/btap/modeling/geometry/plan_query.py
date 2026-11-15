"""The floor-plan renderer's ONLY SDK-touching file: an OpenStudio model in,
plain dicts out (never raises). Everything downstream — ``plan_svg.py``,
``plan.py`` — is SDK-free and unit-testable against hand-written dicts.

Schema returned by :func:`extract`:

    {'storeys': [{'name': str, 'z': float,
                  'spaces': [{'name': str, 'zone': str|None,
                              'space_type': str|None,
                              'polygons': [[[x, y], ...], ...],
                              'centroid': [x, y], 'area_m2': float, 'z': float}]}],
     'bounds': {'min_x':, 'min_y':, 'max_x':, 'max_y':} | None,
     'north_axis_deg': float (Building North Axis, degrees clockwise from true north),
     'inferred_storeys': bool,
     'error': str (only on failure — then storeys is empty)}

Coordinates are WORLD coordinates in metres: every floor surface is
transformed with ``space.transformation() * surface.vertices()`` (the
bar.rb:347 idiom). The ``space.xOrigin/yOrigin`` offset shortcut is
deliberately NOT used — it is rotation-blind and silently draws rotated
buildings unrotated.

Port of btap-modeling/lib/btap_modeling/geometry/plan_query.rb (D-79).
"""

from __future__ import annotations

import openstudio

from btap._compat import ruby_round, sorted_by_name

#: Floor planes within this many metres are the same storey (also the
#: tolerance for "which floor surface set is the lowest one").
Z_TOL = 0.01


def extract(model, audit=None):
    """model in, the schema above out; never raises.

    ``audit`` is an optional warnings sink (step 'plan')."""
    try:
        pairs = []
        for space in sorted_by_name(model.getSpaces()):
            record = space_record(space, audit=audit)
            if record is not None:
                pairs.append((space, record))

        storeys, inferred = group_storeys(model, pairs, audit=audit)
        return {"storeys": storeys,
                "bounds": bounds(model, [space for space, _ in pairs]),
                "north_axis_deg": model.getBuilding().northAxis(),
                "inferred_storeys": inferred}
    except Exception as e:  # Ruby: rescue StandardError
        if audit is not None:
            audit.warn("plan", f"floor-plan extraction failed — no plans produced ({e})")
        return {"storeys": [], "bounds": None, "north_axis_deg": 0.0,
                "inferred_storeys": False, "error": str(e)}


# ------------------------------------------------------------- per space

def space_record(space, audit=None):
    """One space -> its plan record, or None when the space has no floor
    surface (audited, never silent)."""
    polygons = floor_polygons(space)
    if not polygons:
        if audit is not None:
            audit.warn("plan", "space has no Floor surface — omitted from the floor plan",
                       target=space.nameString())
        return None

    area = sum(polygon_area(ring) for ring in polygons)
    return {"name": space.nameString(),
            "zone": zone_name(space),
            "space_type": space_type_name(space),
            "polygons": [[[ruby_round(x, 3), ruby_round(y, 3)] for x, y in ring]
                         for ring in polygons],
            "centroid": [ruby_round(v, 3) for v in centroid(polygons)],
            "area_m2": ruby_round(area, 2),
            "z": ruby_round(floor_z(space), 3)}


def floor_polygons(space):
    """World-coordinate rings of the space's LOWEST floor plane. A space with
    floors at several elevations (a mezzanine modelled as one space) keeps
    only the lowest set — a plan shows one horizontal cut, not both."""
    floors = [s for s in space.surfaces() if s.surfaceType() == "Floor"]
    if not floors:
        return []

    transformation = space.transformation()
    rings = []
    for surface in floors:
        points = [[p.x(), p.y(), p.z()] for p in transformation * surface.vertices()]
        rings.append((min(p[2] for p in points), [[p[0], p[1]] for p in points]))
    lowest = min(z for z, _ in rings)
    return [ring for z, ring in rings
            if abs(z - lowest) <= Z_TOL and len(ring) >= 3]


def floor_z(space):
    """World z of the space's lowest floor plane (the storey-binning key)."""
    transformation = space.transformation()
    return float(min(p.z()
                     for s in space.surfaces() if s.surfaceType() == "Floor"
                     for p in transformation * s.vertices()))


def zone_name(space):
    zone = space.thermalZone()
    return zone.get().nameString() if zone.is_initialized() else None


def space_type_name(space):
    """Standards tags first ("Space Function | Office enclosed > 25 m2"),
    plain SpaceType name as the fallback, None when the space is untyped."""
    space_type = space.spaceType()
    if not space_type.is_initialized():
        return None

    space_type = space_type.get()
    standards = space_type.standardsSpaceType()
    if not standards.is_initialized():
        return space_type.nameString()

    building = space_type.standardsBuildingType()
    return (f"{building.get()} | {standards.get()}" if building.is_initialized()
            else standards.get())


# ----------------------------------------------------------- storeys

def group_storeys(model, pairs, audit=None):
    """Returns ``(storey_groups, inferred)`` — storey groups (display order =
    min world z) and whether they had to be inferred from floor elevations."""
    stories = model.getBuildingStorys()
    orphans = sum(1 for space, _ in pairs if not space.buildingStory().is_initialized())

    if len(stories) == 0 or orphans > 0:
        reason = ("the model has no BuildingStory objects" if len(stories) == 0
                  else f"{orphans} space(s) have no building storey")
        if audit is not None:
            audit.warn("plan", f"storeys inferred from floor elevations — {reason}",
                       inputs={"spaces": len(pairs), "building_storeys": len(stories)})
        return infer_storeys(pairs), True

    groups = []
    for story in sorted_by_name(stories):
        handle = str(story.handle())
        records = [record for space, record in pairs
                   if str(space.buildingStory().get().handle()) == handle]
        if not records:
            continue
        groups.append({"name": story.nameString(),
                       "z": min(r["z"] for r in records),
                       "spaces": records})
    return sorted(groups, key=lambda group: group["z"]), False


def infer_storeys(pairs):
    """Fallback grouping: bin the space records by floor-plane world z
    (±Z_TOL) and synthesize `Level N` names bottom-up."""
    bins = []
    for record in sorted((record for _, record in pairs), key=lambda r: r["z"]):
        found = next((b for b in bins if abs(b["z"] - record["z"]) <= Z_TOL), None)
        if found is not None:
            found["spaces"].append(record)
        else:
            bins.append({"z": record["z"], "spaces": [record]})
    return [{"name": f"Level {index + 1}", "z": b["z"],
             "spaces": sorted(b["spaces"], key=lambda record: record["name"])}
            for index, b in enumerate(sorted(bins, key=lambda b: b["z"]))]


# ----------------------------------------------------------- geometry

def bounds(_model, spaces):
    """Plan extents over every transformed floor point (the bar.rb:344-352
    BoundingBox idiom). None when nothing was extracted."""
    box = openstudio.BoundingBox()
    for space in spaces:
        transformation = space.transformation()
        for surface in space.surfaces():
            if surface.surfaceType() == "Floor":
                box.addPoints(transformation * surface.vertices())
    if not box.minX().is_initialized():
        return None

    return {"min_x": ruby_round(box.minX().get(), 3), "min_y": ruby_round(box.minY().get(), 3),
            "max_x": ruby_round(box.maxX().get(), 3), "max_y": ruby_round(box.maxY().get(), 3)}


def polygon_area(ring):
    """Shoelace area of a closed ring (absolute — winding order is irrelevant
    for a plan)."""
    total = 0.0
    for index, (x1, y1) in enumerate(ring):
        x2, y2 = ring[(index + 1) % len(ring)]
        total += (x1 * y2) - (x2 * y1)
    return abs(total / 2.0)


def centroid(rings):
    """Area-weighted centroid over the space's rings; degenerate rings fall
    back to the vertex average so a label always has somewhere to go."""
    total = 0.0
    cx = 0.0
    cy = 0.0
    for ring in rings:
        area = polygon_area(ring)
        if area == 0:
            continue
        rx, ry = ring_centroid(ring)
        total += area
        cx += rx * area
        cy += ry * area
    if total > 0:
        return [cx / total, cy / total]

    points = [point for ring in rings for point in ring]
    if not points:
        return [0.0, 0.0]

    return [sum(p[0] for p in points) / len(points),
            sum(p[1] for p in points) / len(points)]


def ring_centroid(ring):
    cross_sum = 0.0
    cx = 0.0
    cy = 0.0
    for index, (x1, y1) in enumerate(ring):
        x2, y2 = ring[(index + 1) % len(ring)]
        cross = (x1 * y2) - (x2 * y1)
        cross_sum += cross
        cx += (x1 + x2) * cross
        cy += (y1 + y2) * cross
    if cross_sum == 0:
        return [sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)]

    return [cx / (3.0 * cross_sum), cy / (3.0 * cross_sum)]
