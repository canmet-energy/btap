"""SDK-only ports of the legacy BTAP/NECB geometry helpers that drive the
distance-based costing items (header piping, utility runs, flues, trunk
ducts, terminal piping/wiring runs). Port of btap-costing's hvac/geometry.rb.

Deviations from legacy (documented in the Ruby original):
- "conditioned, non-plenum" is proxied by Space#partofTotalFloorArea (legacy
  reads NECB space-type setpoint schedules from standards_data, which this
  package does not depend on). Plenums/attics are excluded from floor area in
  both schemes.
- The mechanical room can be pinned explicitly via the mech_room_name option
  on the hvac costing facade; otherwise the legacy election runs: a space
  whose space-type name contains 'Electrical/Mechanical', else the
  lowest-storey space closest to the building centre.
"""

from __future__ import annotations

import math

from btap._compat import opt, ruby_round, sorted_by_name
from btap.modeling.geometry import helpers as _modeling_helpers

M_TO_FT = 3.2808398950131235


def is_conditioned(space) -> bool:
    return space.partofTotalFloorArea()


def space_floor_centroid(space):
    """Area-weighted centroid of a space's floor (lowest) surfaces, in
    building coords."""
    surfaces = space.surfaces()
    if len(surfaces) == 0:
        return None

    min_surf = min(surfaces, key=lambda s: float(s.centroid().z()))
    cx = cy = area = 0.0
    for s in surfaces:
        if float(s.centroid().z()) != float(min_surf.centroid().z()):
            continue

        cx += float(s.centroid().x()) * float(s.grossArea())
        cy += float(s.centroid().y()) * float(s.grossArea())
        area += float(s.grossArea())
    if area == 0.0:
        return None

    return [cx / area + float(space.xOrigin()), cy / area + float(space.yOrigin()),
            float(min_surf.centroid().z()) + float(space.zOrigin())]


def mech_room(model, mech_room_name=None):
    """Legacy find_mech_room: explicit 'Electrical/Mechanical' space type wins;
    otherwise the lowest-storey conditioned space closest to the area-weighted
    building centre.

    :return: {'space':, 'centroid': [x, y, z]} or None (no conditioned spaces)
    """
    candidates = []
    centre = [0.0, 0.0, 0.0]
    for space in sorted_by_name(model.getSpaces()):
        if not is_conditioned(space):
            continue

        centroid = space_floor_centroid(space)
        if centroid is None:
            continue

        area = float(space.floorArea())
        centre[0] += centroid[0] * area
        centre[1] += centroid[1] * area
        centre[2] += area
        candidates.append({'space': space, 'centroid': centroid})
    if not candidates:
        return None

    if mech_room_name is not None:
        named = next((c for c in candidates
                      if c['space'].nameString() == mech_room_name), None)
        if named is not None:
            return named
    typed = next((c for c in candidates
                  if (st := opt(c['space'].spaceType())) is not None
                  and 'Electrical/Mechanical' in st.nameString()), None)
    if typed is not None:
        return typed

    centre[0] /= centre[2]
    centre[1] /= centre[2]
    lowest_z = min(c['centroid'][2] for c in candidates)
    return min((c for c in candidates if c['centroid'][2] == lowest_z),
               key=lambda c: ruby_round(math.sqrt((c['centroid'][0] - centre[0]) ** 2 +
                                                  (c['centroid'][1] - centre[1]) ** 2), 1))


def highest_roof_centroid(model):
    """Legacy find_highest_roof_centre: area-weighted centroid of the highest
    outdoor roof/ceiling surfaces.

    :return: [x, y, z] or None
    """
    tol = 6
    spaces_info = []
    max_height = -math.inf
    for space in sorted_by_name(model.getSpaces()):
        surfaces = space.surfaces()
        if not any(s.surfaceType().upper() == 'ROOFCEILING'
                   and s.outsideBoundaryCondition().upper() == 'OUTDOORS'
                   for s in surfaces):
            continue

        max_surf = max(surfaces, key=lambda s: ruby_round(float(s.centroid().z()), tol))
        cx = cy = area = 0.0
        for s in surfaces:
            if ruby_round(float(s.centroid().z()), tol) != \
                    ruby_round(float(max_surf.centroid().z()), tol):
                continue

            cx += float(s.centroid().x()) * float(s.grossArea())
            cy += float(s.centroid().y()) * float(s.grossArea())
            area += float(s.grossArea())
        if area == 0.0:
            continue

        z = float(max_surf.centroid().z()) + float(space.zOrigin())
        spaces_info.append({'x': cx / area + float(space.xOrigin()),
                            'y': cy / area + float(space.yOrigin()),
                            'z': z, 'area': area})
        if ruby_round(z, tol) > max_height:
            max_height = ruby_round(z, tol)
    if not spaces_info:
        return None

    top = [i for i in spaces_info if ruby_round(i['z'], tol) == max_height]
    area = sum(i['area'] for i in top)
    return [sum(i['x'] * i['area'] for i in top) / area,
            sum(i['y'] * i['area'] for i in top) / area, max_height]


def lowest_roof_centroid(model):
    """Legacy get_lowest_space: the lowest roof/ceiling centroid among
    conditioned spaces (the trunk duct drops from the roof centroid to this
    height)."""
    cents = []
    for space in sorted_by_name(model.getSpaces()):
        if not is_conditioned(space):
            continue

        for surface in space.surfaces():
            if surface.surfaceType().upper() != 'ROOFCEILING':
                continue

            cents.append([float(surface.centroid().x()) + float(space.xOrigin()),
                          float(surface.centroid().y()) + float(space.yOrigin()),
                          float(surface.centroid().z()) + float(space.zOrigin())])
    if not cents:
        return None
    return min(cents, key=lambda c: c[2])


def nominal_floor_height_m(model):
    building = model.getBuilding()
    declared = opt(building.nominalFloortoFloorHeight())
    if declared is not None:
        return declared

    volume = building.airVolume()
    conditioned = opt(building.conditionedFloorArea())
    floor_area = conditioned if conditioned is not None else building.floorArea()
    if floor_area < 0.01:
        return 0.0

    return volume / floor_area


def above_ground_storeys(model):
    """Moved to btap.modeling.geometry.helpers (pure geometry the authoring
    systems need); this delegation keeps costing and NECB callers working."""
    return _modeling_helpers.above_ground_storeys(model)


def building_data(model, mech_room_name=None):
    """Legacy getGeometryData: distances used by plant utility runs and header
    piping. All distances in FEET (matching legacy's unit convention
    downstream).

    :return: dict util_dist_ft, ht_roof_ft, flr_height_ft, horz_dist_ft,
        storeys, mech_room_in_basement, mech_room; or None when geometry
        cannot be resolved.
    """
    room = mech_room(model, mech_room_name=mech_room_name)
    if room is None:
        return None

    flr_height = nominal_floor_height_m(model)
    storeys = above_ground_storeys(model)
    story = next((st for st in model.getBuildingStorys()
                  if any(sp.nameString() == room['space'].nameString()
                         for sp in st.spaces())), None)
    edge = story_cent_to_edge(story, [room['centroid'][0], room['centroid'][1]]) \
        if story is not None else None
    horz = edge['start_point']['dist'] if edge is not None else 0.0

    z = room['centroid'][2]
    in_basement = z < 0
    if in_basement:
        ht_roof = (storeys + 1) * flr_height
        util = flr_height + horz
    elif z == 0:
        ht_roof = storeys * flr_height
        util = horz
    else:
        ht_roof = (storeys - ruby_round(z / flr_height)) * flr_height
        util = ht_roof + horz

    return {'util_dist_ft': util * M_TO_FT, 'ht_roof_ft': ht_roof * M_TO_FT,
            'flr_height_ft': flr_height * M_TO_FT, 'horz_dist_ft': horz * M_TO_FT,
            'storeys': storeys, 'mech_room_in_basement': in_basement,
            'mech_room': room}


def zone_story_centroids(zone):
    """Legacy thermal_zone_get_centroid_per_floor: the zone's conditioned
    spaces grouped by building storey with the area-weighted ceiling centroid
    of each group.

    :return: [{'story_name':, 'spaces':, 'centroid': [x,y,z], 'ceiling_area':}]
    """
    stories: dict[str, list] = {}
    for space in sorted_by_name(zone.spaces()):
        if not is_conditioned(space):
            continue

        story = opt(space.buildingStory())
        story_name = story.nameString() if story is not None else 'none'
        stories.setdefault(story_name, []).append(space)
    out = []
    for story_name, spaces in stories.items():
        cx = cy = cz = area = 0.0
        for space in spaces:
            sx = sy = sz = sarea = 0.0
            for surface in space.surfaces():
                if surface.surfaceType().upper() != 'ROOFCEILING':
                    continue

                sx += float(surface.centroid().x()) * float(surface.grossArea())
                sy += float(surface.centroid().y()) * float(surface.grossArea())
                sz += float(surface.centroid().z()) * float(surface.grossArea())
                sarea += float(surface.grossArea())
            if sarea == 0.0:
                continue

            cx += (sx / sarea + float(space.xOrigin())) * sarea
            cy += (sy / sarea + float(space.yOrigin())) * sarea
            cz += (sz / sarea + float(space.zOrigin())) * sarea
            area += sarea
        if area == 0.0:
            continue  # Ruby maps to nil then compacts

        out.append({'story_name': story_name, 'spaces': spaces,
                    'centroid': [cx / area, cy / area, cz / area],
                    'ceiling_area': area})
    return out


def story_cent_to_edge(story, target_cent, full_length=False):
    """Legacy get_story_cent_to_edge: the ceiling edge of the storey furthest
    from a target x,y point. Without full_length, returns the furthest-edge
    distance (used for the mech-room-to-exterior run). With full_length, also
    intersects the line (target -> furthest edge) with the opposite side of
    the storey outline so the full crossing length is available (used for
    floor trunk ducts).

    :return: {'start_point': {'point':, 'dist':}, 'end_point': {...} or None}
    """
    edges = []
    outlines = []
    for space in sorted_by_name(story.spaces()):
        if not is_conditioned(space):
            continue

        origin = [float(space.xOrigin()), float(space.yOrigin()), float(space.zOrigin())]
        for surface in space.surfaces():
            if surface.surfaceType().upper() != 'ROOFCEILING':
                continue

            verts = [[float(v.x()) + origin[0], float(v.y()) + origin[1],
                      float(v.z()) + origin[2]] for v in surface.vertices()]
            outlines.append(verts)
            for i in range(len(verts)):
                ip = len(verts) - 1 if i == 0 else i - 1
                mid = [(verts[i][0] + verts[ip][0]) / 2.0,
                       (verts[i][1] + verts[ip][1]) / 2.0,
                       (verts[i][2] + verts[ip][2]) / 2.0]
                dist = math.sqrt((target_cent[0] - mid[0]) ** 2 +
                                 (target_cent[1] - mid[1]) ** 2)
                edges.append({'point': mid, 'dist': dist})
    if not edges:
        return None

    start_edge = max(edges, key=lambda e: e['dist'])
    result = {'start_point': start_edge, 'end_point': None}
    if not full_length:
        return result

    # walk every outline segment; keep intersections with the target->start
    # line that lie on the OPPOSITE side of the target from the start edge;
    # take the furthest
    sx = start_edge['point'][0] - target_cent[0]
    sy = start_edge['point'][1] - target_cent[1]
    best = None
    for verts in outlines:
        for i in range(len(verts)):
            ip = len(verts) - 1 if i == 0 else i - 1
            intr = segment_line_intersection(verts[ip], verts[i], target_cent,
                                             start_edge['point'])
            if intr is None:
                continue

            dx = intr[0] - target_cent[0]
            dy = intr[1] - target_cent[1]
            if (dx * sx + dy * sy) > 0:  # same side as start edge
                continue

            dist = math.sqrt((start_edge['point'][0] - intr[0]) ** 2 +
                             (start_edge['point'][1] - intr[1]) ** 2)
            if best is None or dist > best['dist']:
                best = {'point': intr, 'dist': dist}
    result['end_point'] = best
    return result


def segment_line_intersection(a1, a2, b1, b2):
    """Intersection of segment a1-a2 with the infinite line through b1-b2
    (x,y plane)."""
    dax = a2[0] - a1[0]
    day = a2[1] - a1[1]
    dbx = b2[0] - b1[0]
    dby = b2[1] - b1[1]
    denom = dax * dby - day * dbx
    if abs(denom) < 1e-9:
        return None

    t = ((b1[0] - a1[0]) * dby - (b1[1] - a1[1]) * dbx) / denom
    if t < -1e-9 or t > 1.0 + 1e-9:
        return None

    return [a1[0] + t * dax, a1[1] + t * day, a1[2] + t * (a2[2] - a1[2])]


def manhattan_xy_m(a, b):
    """Manhattan x+y distance (used by legacy for terminal piping/wiring
    runs), metres."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def manhattan_xyz_m(a, b):
    """Manhattan x+y+z distance (used for mech-room-to-roof utility runs),
    metres."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def zone_exterior_wall_area_ft2(zone):
    """Zone exterior wall area in ft2 (legacy perimeter distribution runs)."""
    return sum(float(space.exteriorWallArea()) for space in zone.spaces()) * M_TO_FT * M_TO_FT
