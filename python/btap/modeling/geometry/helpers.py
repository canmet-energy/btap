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


class UndeterminedStoreys(ValueError):
    """The model does not say how many above-ground storeys it has."""


def above_ground_storeys(model):
    """Above-ground storey count, from the MODEL. Raises if it cannot say.

    Two sources, in order: the declared
    ``standardsNumberOfAboveGroundStories``, then a count of storeys holding
    any at-or-above-grade space. Both are real information the model carries.

    **A model that carries NEITHER is an error, not a one-storey building.**
    This used to return a fabricated 1, and the storey count decides the
    reference system — Table 8.4.x.7.-A sends a General Area building to
    System 3 at two storeys and System 6 at three — so guessing it chooses a
    different reference building and reports the comparison as a
    determination. `pipeline.py`'s preflight already warned that the fallback
    "would silently treat the building as ONE storey"; phylroy's direction
    (2026-10-08) is that a missing storey count is the MODELLER's omission and
    must reach them, not be papered over.

    Lived in hvac's costing module historically, but it is pure geometry and
    the authoring systems (vav_reheat zoning) need it — so it lives here and
    costing delegates.

    :raises UndeterminedStoreys: the model declares no standards storey count
        and has no storey holding an at-or-above-grade space
    """
    declared = opt(model.getBuilding().standardsNumberOfAboveGroundStories())
    if declared is not None:
        return declared

    count = sum(1 for story in model.getBuildingStorys()
                if any(float(s.zOrigin()) >= -0.01 for s in story.spaces()))
    if count < 1:
        raise UndeterminedStoreys(
            "the model does not say how many ABOVE-GROUND STOREYS it has: "
            "OS:Building has no 'Standards Number of Above Ground Stories' "
            "and no OS:BuildingStory holds a space at or above grade. The "
            "storey count selects the reference system (Table 8.4.x.7.-A), so "
            "it cannot be assumed — set the standards field on the Building, "
            "or assign spaces to BuildingStory objects")
    return min(count, 1000)
