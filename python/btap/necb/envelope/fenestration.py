"""The 3.2.1.4 fenestration-area rule appliers (FDWR window rebuild, SRR
centroid-scaled skylights) — rule application, hence NECB-side; the generic
census/scaling machinery they drive is btap.modeling.envelope.geometry.

Port of btap-necb's envelope/fenestration.rb.
"""

from __future__ import annotations

import math

import openstudio

from btap._compat import NullAudit, ruby_round, ruby_str, sorted_by_name
from btap.modeling.envelope import geometry as Geometry


def apply_fdwr(model, fdwr_lim, window_construction, audit=None):
    """Rebuild windows to hit an FDWR limit (port of apply_max_fdwr_nrcan):
    remove existing subsurfaces, setWindowToWallRatio per exposed wall, retype
    to FixedWindow and assign the given construction."""
    audit = audit if audit is not None else NullAudit()
    census = Geometry.exposed_walls(model)
    if census["wall_area_m2"] < 0.1 or fdwr_lim > 1:
        return False

    for surface in census["walls"]:
        for sub in sorted_by_name(surface.subSurfaces()):
            sub.remove()
        if fdwr_lim < 0.001:
            continue

        surface.setWindowToWallRatio(fdwr_lim)
        for sub in sorted_by_name(surface.subSurfaces()):
            sub.setSubSurfaceType("FixedWindow")
            sub.setConstruction(window_construction)
            sub.setName(f"{surface.nameString()}_{sub.subSurfaceType()}")
    resulting = Geometry.exposed_walls(model)["fdwr"]
    audit.decision("geometry", "windows rebuilt to FDWR limit",
                   inputs={"fdwr_limit": ruby_round(fdwr_lim, 4),
                           "walls": len(census["walls"])},
                   value=("resulting FDWR "
                          f"{ruby_str(None if resulting is None else ruby_round(resulting, 4))}"),
                   article="3.2.1.4.(1)")
    return True


def apply_srr(model, srr_lim, skylight_construction, audit=None):
    """Add centroid-scaled skylights at an SRR limit (port of OPTION A): one
    skylight per exposed conditioned roof, the roof polygon scaled about its
    centroid by sqrt(fraction) — exact for convex roofs (a scaled convex
    polygon has exactly fraction x the area)."""
    audit = audit if audit is not None else NullAudit()
    census = Geometry.exposed_roofs(model)
    if census["roof_area_m2"] < 0.1 or srr_lim > 1:
        return False

    scale = math.sqrt(srr_lim)
    for surface in census["roofs"]:
        for sub in sorted_by_name(surface.subSurfaces()):
            sub.remove()
        if srr_lim < 0.001:
            continue

        centroid = Geometry.vertex_centroid(surface.vertices())
        new_vertices = openstudio.Point3dVector([
            openstudio.Point3d(centroid.x() + (v.x() - centroid.x()) * scale,
                               centroid.y() + (v.y() - centroid.y()) * scale,
                               centroid.z() + (v.z() - centroid.z()) * scale)
            for v in surface.vertices()
        ])
        skylight = openstudio.model.SubSurface(new_vertices, model)
        skylight.setSurface(surface)
        skylight.setSubSurfaceType("Skylight")
        skylight.setConstruction(skylight_construction)
        skylight.setName(f"{surface.nameString()}_Skylight")
    resulting = Geometry.exposed_roofs(model)["srr"]
    audit.decision("geometry", "skylights added at SRR limit",
                   inputs={"srr_limit": ruby_round(srr_lim, 4),
                           "roofs": len(census["roofs"])},
                   value=("resulting SRR "
                          f"{ruby_str(None if resulting is None else ruby_round(resulting, 4))}"),
                   article="3.2.1.4.(2)")
    return True
