"""SDK-only envelope geometry (port of btap-modeling's envelope/geometry.rb):
exposed conditioned surface census and centroid-scaled subsurface helpers.
The NECB rule appliers built on these (apply_fdwr / apply_srr, 3.2.1.4) live
in btap.necb's envelope domain.

"Conditioned, non-plenum" is proxied by Space partofTotalFloorArea + a zone
thermostat (on standards-untagged models the proxy is equivalent to the
legacy setpoint-schedule check) — same convention as the hvac classifier.
"""

from __future__ import annotations

import math

import openstudio

from btap._compat import opt, sorted_by_name


def is_conditioned(space) -> bool:
    if not space.partofTotalFloorArea():
        return False
    zone = opt(space.thermalZone())
    return zone is not None and zone.thermostatSetpointDualSetpoint().is_initialized()


def exposed_walls(model, min_angle=89, max_angle=91) -> dict:
    """Census of exterior conditioned walls (near-vertical) with area totals
    and the current FDWR (port of find_exposed_conditioned_vertical_surfaces)."""
    walls = []
    wall_area = 0.0
    sub_area = 0.0
    for space in sorted_by_name(model.getSpaces()):
        if not is_conditioned(space):
            continue
        for surface in sorted_by_name(space.surfaces()):
            if not (surface.surfaceType() == "Wall"
                    and surface.outsideBoundaryCondition() == "Outdoors"):
                continue
            tilt = surface.tilt() * 180.0 / math.pi
            if not (min_angle <= tilt <= max_angle):
                continue
            walls.append(surface)
            wall_area += surface.grossArea() * space.multiplier()
            for ss in surface.subSurfaces():
                sub_area += ss.grossArea() * space.multiplier()
    return {"walls": walls, "wall_area_m2": wall_area, "subsurface_area_m2": sub_area,
            "fdwr": None if wall_area < 0.1 else sub_area / wall_area}


def exposed_roofs(model) -> dict:
    """Census of exterior conditioned roofs with the current SRR."""
    roofs = []
    roof_area = 0.0
    sub_area = 0.0
    for space in sorted_by_name(model.getSpaces()):
        if not is_conditioned(space):
            continue
        for surface in sorted_by_name(space.surfaces()):
            if not (surface.surfaceType() == "RoofCeiling"
                    and surface.outsideBoundaryCondition() == "Outdoors"):
                continue
            roofs.append(surface)
            roof_area += surface.grossArea() * space.multiplier()
            for ss in surface.subSurfaces():
                sub_area += ss.grossArea() * space.multiplier()
    return {"roofs": roofs, "roof_area_m2": roof_area, "subsurface_area_m2": sub_area,
            "srr": None if roof_area < 0.1 else sub_area / roof_area}


def scale_subsurfaces(surface, area_ratio):
    """Scale every subsurface of a surface about its own centroid so its area
    changes by `area_ratio` (the reference-envelope per-orientation FDWR
    reduction: 8.4.4.3.(3) scales EXISTING fenestration proportionally,
    never rebuilds)."""
    scale = math.sqrt(area_ratio)
    for sub in sorted_by_name(surface.subSurfaces()):
        centroid = vertex_centroid(sub.vertices())
        sub.setVertices([
            openstudio.Point3d(centroid.x() + (v.x() - centroid.x()) * scale,
                               centroid.y() + (v.y() - centroid.y()) * scale,
                               centroid.z() + (v.z() - centroid.z()) * scale)
            for v in sub.vertices()
        ])


def vertex_centroid(vertices):
    n = float(len(vertices))
    return openstudio.Point3d(sum(v.x() for v in vertices) / n,
                              sum(v.y() for v in vertices) / n,
                              sum(v.z() for v in vertices) / n)
