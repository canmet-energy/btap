"""The three small BTAP geometry helpers the wizards depend on, ported
standalone (BTAP::Geometry.match_surfaces / rotate_model and
BTAP::Geometry::Surfaces.set_surfaces_boundary_condition).

Port of btap-modeling/lib/btap_modeling/geometry/helpers.rb (D-79).
"""

from __future__ import annotations

import math

import openstudio

from btap._compat import opt, sorted_by_name


def match_surfaces(model):
    """Match interior surfaces between every pair of spaces (legacy semantics:
    sorted pairwise matchSurfaces)."""
    for space1 in sorted_by_name(model.getSpaces()):
        for space2 in sorted_by_name(model.getSpaces()):
            space1.matchSurfaces(space2)
    return model


def set_boundary_condition(surfaces, boundary_condition):
    """Set an outside boundary condition on surfaces; Adiabatic removes
    subsurfaces first (an adiabatic surface cannot carry them)."""
    if boundary_condition not in openstudio.model.Surface.validOutsideBoundaryConditionValues():
        raise ValueError(f"invalid outside boundary condition '{boundary_condition}'")

    for surface in surfaces:
        if boundary_condition == "Adiabatic":
            for sub_surface in surface.subSurfaces():
                sub_surface.remove()
        surface.setOutsideBoundaryCondition(boundary_condition)
    return surfaces


def rotate_model(model, degrees):
    """Rotate every planar surface group about the z axis."""
    transformation = openstudio.Transformation.rotation(openstudio.Vector3d(0, 0, 1),
                                                        degrees * math.pi / 180)
    for group in model.getPlanarSurfaceGroups():
        group.changeTransformation(transformation)
    return model


def above_ground_storeys(model):
    """Above-ground storey count: the declared standards value when set, else
    counted from storeys with any at-or-above-grade space. Lived in hvac's
    costing module historically, but it is pure geometry and the authoring
    systems (vav_reheat zoning) need it — so it lives here and costing
    delegates."""
    declared = opt(model.getBuilding().standardsNumberOfAboveGroundStories())
    if declared is not None:
        return declared

    count = sum(1 for story in model.getBuildingStorys()
                if any(float(s.zOrigin()) >= -0.01 for s in story.spaces()))
    return min(max(count, 1), 1000)
