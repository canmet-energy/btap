"""Parametric footprint wizards — verbatim port of openstudio-standards
OpenstudioStandards::Geometry.create_shape_* (rectangle, aspect-ratio,
courtyard, H, L, T, U): per storey, perimeter/core floor-print polygons are
extruded with Space.fromFloorPrint, below-grade storeys get Ground boundary
conditions, and surfaces are matched across spaces. The only changes from
upstream are the module wrapper and the three small BTAP helper calls
(helpers.match_surfaces / set_boundary_condition / rotate_model).

Ported from btap-modeling/lib/btap_modeling/geometry/wizards.rb (D-79).
"""

from __future__ import annotations

import math

import openstudio

from btap._compat import opt, ruby_round
from btap.modeling.geometry import helpers


def _ruby_div(a, b):
    """Ruby's `/`: floor division when both operands are Integers."""
    if isinstance(a, int) and isinstance(b, int):
        return a // b
    return a / b


# Methods to create basic shapes

# @!group Create:Shape

def create_shape_rectangle(model,
                           length=100.0,
                           width=100.0,
                           above_ground_storys=3,
                           under_ground_storys=1,
                           floor_to_floor_height=3.8,
                           plenum_height=1.0,
                           perimeter_zone_depth=4.57,
                           initial_height=0.0):
    """Create a Rectangle shape in a model.

    :param model: OpenStudio model object
    :param length: Building length in meters
    :param width: Building width in meters
    :param above_ground_storys: Number of above ground stories
    :param under_ground_storys: Number of below ground stories
    :param floor_to_floor_height: Floor to floor height in meters
    :param plenum_height: Plenum height in meters
    :param perimeter_zone_depth: Perimeter zone depth in meters
    :param initial_height: Initial height in meters
    :return: OpenStudio model object (None on rejection)
    """
    if length <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Length must be greater than 0.')
        return None

    if width <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Width must be greater than 0.')
        return None

    if (above_ground_storys + under_ground_storys) <= 0:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Number of floors must be greater than 0.')
        return None

    if floor_to_floor_height <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Floor to floor height must be greater than 0.')
        return None

    if plenum_height < 0:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Plenum height must be greater than 0.')
        return None

    shortest_side = min(length, width)
    if perimeter_zone_depth < 0 or 2 * perimeter_zone_depth >= (shortest_side - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Perimeter zone depth must be greater than or equal to 0 and less than half of the smaller of length and width, {ruby_round(_ruby_div(shortest_side, 2), 2)}m")
        return None

    # Loop through the number of floors
    building_stories = []
    for floor in range(under_ground_storys * -1, above_ground_storys):
        z = (floor_to_floor_height * floor) + initial_height

        # Create a new story within the building
        story = openstudio.model.BuildingStory(model)
        story.setNominalFloortoFloorHeight(floor_to_floor_height)
        story.setName(f"Story {floor + 1}")
        building_stories.append(story)

        nw_point = openstudio.Point3d(0, width, z)
        ne_point = openstudio.Point3d(length, width, z)
        se_point = openstudio.Point3d(length, 0, z)
        sw_point = openstudio.Point3d(0, 0, z)

        # Identity matrix for setting space origins
        m = openstudio.Matrix(4, 4, 0)
        m[0, 0] = 1
        m[1, 1] = 1
        m[2, 2] = 1
        m[3, 3] = 1

        # Define polygons for a rectangular building
        if perimeter_zone_depth > 0:
            perimeter_nw_point = nw_point + openstudio.Vector3d(perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_ne_point = ne_point + openstudio.Vector3d(-perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_se_point = se_point + openstudio.Vector3d(-perimeter_zone_depth, perimeter_zone_depth, 0)
            perimeter_sw_point = sw_point + openstudio.Vector3d(perimeter_zone_depth, perimeter_zone_depth, 0)

            west_polygon = openstudio.Point3dVector()
            west_polygon.append(sw_point)
            west_polygon.append(nw_point)
            west_polygon.append(perimeter_nw_point)
            west_polygon.append(perimeter_sw_point)
            west_space = openstudio.model.Space.fromFloorPrint(west_polygon, floor_to_floor_height, model)
            west_space = opt(west_space)
            m[0, 3] = sw_point.x()
            m[1, 3] = sw_point.y()
            m[2, 3] = sw_point.z()
            west_space.changeTransformation(openstudio.Transformation(m))
            west_space.setBuildingStory(story)
            west_space.setName(f"Story {floor + 1} West Perimeter Space")

            north_polygon = openstudio.Point3dVector()
            north_polygon.append(nw_point)
            north_polygon.append(ne_point)
            north_polygon.append(perimeter_ne_point)
            north_polygon.append(perimeter_nw_point)
            north_space = openstudio.model.Space.fromFloorPrint(north_polygon, floor_to_floor_height, model)
            north_space = opt(north_space)
            m[0, 3] = perimeter_nw_point.x()
            m[1, 3] = perimeter_nw_point.y()
            m[2, 3] = perimeter_nw_point.z()
            north_space.changeTransformation(openstudio.Transformation(m))
            north_space.setBuildingStory(story)
            north_space.setName(f"Story {floor + 1} North Perimeter Space")

            east_polygon = openstudio.Point3dVector()
            east_polygon.append(ne_point)
            east_polygon.append(se_point)
            east_polygon.append(perimeter_se_point)
            east_polygon.append(perimeter_ne_point)
            east_space = openstudio.model.Space.fromFloorPrint(east_polygon, floor_to_floor_height, model)
            east_space = opt(east_space)
            m[0, 3] = perimeter_se_point.x()
            m[1, 3] = perimeter_se_point.y()
            m[2, 3] = perimeter_se_point.z()
            east_space.changeTransformation(openstudio.Transformation(m))
            east_space.setBuildingStory(story)
            east_space.setName(f"Story {floor + 1} East Perimeter Space")

            south_polygon = openstudio.Point3dVector()
            south_polygon.append(se_point)
            south_polygon.append(sw_point)
            south_polygon.append(perimeter_sw_point)
            south_polygon.append(perimeter_se_point)
            south_space = openstudio.model.Space.fromFloorPrint(south_polygon, floor_to_floor_height, model)
            south_space = opt(south_space)
            m[0, 3] = sw_point.x()
            m[1, 3] = sw_point.y()
            m[2, 3] = sw_point.z()
            south_space.changeTransformation(openstudio.Transformation(m))
            south_space.setBuildingStory(story)
            south_space.setName(f"Story {floor + 1} South Perimeter Space")

            core_polygon = openstudio.Point3dVector()
            core_polygon.append(perimeter_sw_point)
            core_polygon.append(perimeter_nw_point)
            core_polygon.append(perimeter_ne_point)
            core_polygon.append(perimeter_se_point)
            core_space = openstudio.model.Space.fromFloorPrint(core_polygon, floor_to_floor_height, model)
            core_space = opt(core_space)
            m[0, 3] = perimeter_sw_point.x()
            m[1, 3] = perimeter_sw_point.y()
            m[2, 3] = perimeter_sw_point.z()
            core_space.changeTransformation(openstudio.Transformation(m))
            core_space.setBuildingStory(story)
            core_space.setName(f"Story {floor + 1} Core Space")
        else:
            # Minimal zones
            core_polygon = openstudio.Point3dVector()
            core_polygon.append(sw_point)
            core_polygon.append(nw_point)
            core_polygon.append(ne_point)
            core_polygon.append(se_point)
            core_space = openstudio.model.Space.fromFloorPrint(core_polygon, floor_to_floor_height, model)
            core_space = opt(core_space)
            m[0, 3] = sw_point.x()
            m[1, 3] = sw_point.y()
            m[2, 3] = sw_point.z()
            core_space.changeTransformation(openstudio.Transformation(m))
            core_space.setBuildingStory(story)
            core_space.setName(f"Story {floor + 1} Core Space")
        # Set vertical story position
        story.setNominalZCoordinate(z)

        # Ensure that underground stories (when z<0 have Ground set as Boundary conditions).
        # Apply the Ground BC to all surfaces, the top ceiling will be corrected below when the surface matching algorithm is called.
        underground_surfaces = [surface for space in story.spaces() for surface in space.surfaces()]
        if z < 0:
            helpers.set_boundary_condition(underground_surfaces, 'Ground')

    helpers.match_surfaces(model)
    return model


def create_shape_aspect_ratio(model,
                              aspect_ratio=0.5,
                              floor_area=1000.0,
                              rotation=0.0,
                              num_floors=3,
                              floor_to_floor_height=3.8,
                              plenum_height=1.0,
                              perimeter_zone_depth=4.57):
    """Create a Rectangle shape in a model based on a given aspect ratio.

    :param model: OpenStudio model object
    :param aspect_ratio: Aspect ratio
    :param floor_area: Building floor area in m2
    :param rotation: Building rotation in degrees from North
    :param num_floors: Number of floors
    :param floor_to_floor_height: Floor to floor height in meters
    :param plenum_height: Plenum height in meters
    :param perimeter_zone_depth: Perimeter zone depth in meters
    :return: OpenStudio model object
    """
    # determine length and width
    length = math.sqrt((floor_area / (num_floors * 1.0)) / aspect_ratio)
    width = math.sqrt((floor_area / (num_floors * 1.0)) * aspect_ratio)
    create_shape_rectangle(model,
                           length,
                           width,
                           num_floors,
                           0,
                           floor_to_floor_height,
                           plenum_height,
                           perimeter_zone_depth)
    helpers.rotate_model(model, rotation)

    return model


def create_shape_courtyard(model,
                           length=50.0,
                           width=30.0,
                           courtyard_length=15.0,
                           courtyard_width=5.0,
                           num_floors=3,
                           floor_to_floor_height=3.8,
                           plenum_height=1.0,
                           perimeter_zone_depth=4.57):
    """Create a Courtyard shape in a model.

    :param model: OpenStudio model object
    :param length: Building length in meters
    :param width: Building width in meters
    :param courtyard_length: Courtyard depth in meters
    :param courtyard_width: Courtyard width in meters
    :param num_floors: Number of floors
    :param floor_to_floor_height: Floor to floor height in meters
    :param plenum_height: Plenum height in meters
    :param perimeter_zone_depth: Perimeter zone depth in meters
    :return: OpenStudio model object (None on rejection)
    """
    if length <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Length must be greater than 0.')
        return None

    if width <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Width must be greater than 0.')
        return None

    if courtyard_length <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Courtyard length must be greater than 0.')
        return None

    if courtyard_width <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Courtyard width must be greater than 0.')
        return None

    if num_floors <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Number of floors must be greater than 0.')
        return None

    if floor_to_floor_height <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Floor to floor height must be greater than 0.')
        return None

    if plenum_height < 0:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Plenum height must be greater than 0.')
        return None

    shortest_side = min(length, width)
    if perimeter_zone_depth < 0 or 4 * perimeter_zone_depth >= (shortest_side - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Perimeter zone depth must be greater than or equal to 0 and less than {shortest_side / 4.0}m.")
        return None

    if courtyard_length >= (length - (4 * perimeter_zone_depth) - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Courtyard length must be less than {length - (4.0 * perimeter_zone_depth)}m.")
        return None

    if courtyard_width >= (width - (4 * perimeter_zone_depth) - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Courtyard width must be less than {width - (4.0 * perimeter_zone_depth)}m.")
        return None

    # Loop through the number of floors
    for floor in range(0, math.floor(num_floors - 1) + 1):
        z = floor_to_floor_height * floor

        # Create a new story within the building
        story = openstudio.model.BuildingStory(model)
        story.setNominalFloortoFloorHeight(floor_to_floor_height)
        story.setName(f"Story {floor + 1}")

        nw_point = openstudio.Point3d(0.0, width, z)
        ne_point = openstudio.Point3d(length, width, z)
        se_point = openstudio.Point3d(length, 0.0, z)
        sw_point = openstudio.Point3d(0.0, 0.0, z)

        courtyard_nw_point = openstudio.Point3d((length - courtyard_length) / 2.0, ((width - courtyard_width) / 2.0) + courtyard_width, z)
        courtyard_ne_point = openstudio.Point3d(((length - courtyard_length) / 2.0) + courtyard_length, ((width - courtyard_width) / 2.0) + courtyard_width, z)
        courtyard_se_point = openstudio.Point3d(((length - courtyard_length) / 2.0) + courtyard_length, (width - courtyard_width) / 2.0, z)
        courtyard_sw_point = openstudio.Point3d((length - courtyard_length) / 2.0, (width - courtyard_width) / 2.0, z)

        # Identity matrix for setting space origins
        m = openstudio.Matrix(4, 4, 0.0)
        m[0, 0] = 1.0
        m[1, 1] = 1.0
        m[2, 2] = 1.0
        m[3, 3] = 1.0

        # Define polygons for a building with a courtyard
        if perimeter_zone_depth > 0:
            outer_perimeter_nw_point = nw_point + openstudio.Vector3d(perimeter_zone_depth, -perimeter_zone_depth, 0.0)
            outer_perimeter_ne_point = ne_point + openstudio.Vector3d(-perimeter_zone_depth, -perimeter_zone_depth, 0.0)
            outer_perimeter_se_point = se_point + openstudio.Vector3d(-perimeter_zone_depth, perimeter_zone_depth, 0.0)
            outer_perimeter_sw_point = sw_point + openstudio.Vector3d(perimeter_zone_depth, perimeter_zone_depth, 0.0)
            inner_perimeter_nw_point = courtyard_nw_point + openstudio.Vector3d(-perimeter_zone_depth, perimeter_zone_depth, 0.0)
            inner_perimeter_ne_point = courtyard_ne_point + openstudio.Vector3d(perimeter_zone_depth, perimeter_zone_depth, 0.0)
            inner_perimeter_se_point = courtyard_se_point + openstudio.Vector3d(perimeter_zone_depth, -perimeter_zone_depth, 0.0)
            inner_perimeter_sw_point = courtyard_sw_point + openstudio.Vector3d(-perimeter_zone_depth, -perimeter_zone_depth, 0.0)

            west_outer_perimeter_polygon = openstudio.Point3dVector()
            west_outer_perimeter_polygon.append(sw_point)
            west_outer_perimeter_polygon.append(nw_point)
            west_outer_perimeter_polygon.append(outer_perimeter_nw_point)
            west_outer_perimeter_polygon.append(outer_perimeter_sw_point)
            west_outer_perimeter_space = openstudio.model.Space.fromFloorPrint(west_outer_perimeter_polygon, floor_to_floor_height, model)
            west_outer_perimeter_space = opt(west_outer_perimeter_space)
            m[0, 3] = sw_point.x()
            m[1, 3] = sw_point.y()
            m[2, 3] = sw_point.z()
            west_outer_perimeter_space.changeTransformation(openstudio.Transformation(m))
            west_outer_perimeter_space.setBuildingStory(story)
            west_outer_perimeter_space.setName(f"Story {floor + 1} West Outer Perimeter Space")

            north_outer_perimeter_polygon = openstudio.Point3dVector()
            north_outer_perimeter_polygon.append(nw_point)
            north_outer_perimeter_polygon.append(ne_point)
            north_outer_perimeter_polygon.append(outer_perimeter_ne_point)
            north_outer_perimeter_polygon.append(outer_perimeter_nw_point)
            north_outer_perimeter_space = openstudio.model.Space.fromFloorPrint(north_outer_perimeter_polygon, floor_to_floor_height, model)
            north_outer_perimeter_space = opt(north_outer_perimeter_space)
            m[0, 3] = outer_perimeter_nw_point.x()
            m[1, 3] = outer_perimeter_nw_point.y()
            m[2, 3] = outer_perimeter_nw_point.z()
            north_outer_perimeter_space.changeTransformation(openstudio.Transformation(m))
            north_outer_perimeter_space.setBuildingStory(story)
            north_outer_perimeter_space.setName(f"Story {floor + 1} North Outer Perimeter Space")

            east_outer_perimeter_polygon = openstudio.Point3dVector()
            east_outer_perimeter_polygon.append(ne_point)
            east_outer_perimeter_polygon.append(se_point)
            east_outer_perimeter_polygon.append(outer_perimeter_se_point)
            east_outer_perimeter_polygon.append(outer_perimeter_ne_point)
            east_outer_perimeter_space = openstudio.model.Space.fromFloorPrint(east_outer_perimeter_polygon, floor_to_floor_height, model)
            east_outer_perimeter_space = opt(east_outer_perimeter_space)
            m[0, 3] = outer_perimeter_se_point.x()
            m[1, 3] = outer_perimeter_se_point.y()
            m[2, 3] = outer_perimeter_se_point.z()
            east_outer_perimeter_space.changeTransformation(openstudio.Transformation(m))
            east_outer_perimeter_space.setBuildingStory(story)
            east_outer_perimeter_space.setName(f"Story {floor + 1} East Outer Perimeter Space")

            south_outer_perimeter_polygon = openstudio.Point3dVector()
            south_outer_perimeter_polygon.append(se_point)
            south_outer_perimeter_polygon.append(sw_point)
            south_outer_perimeter_polygon.append(outer_perimeter_sw_point)
            south_outer_perimeter_polygon.append(outer_perimeter_se_point)
            south_outer_perimeter_space = openstudio.model.Space.fromFloorPrint(south_outer_perimeter_polygon, floor_to_floor_height, model)
            south_outer_perimeter_space = opt(south_outer_perimeter_space)
            m[0, 3] = sw_point.x()
            m[1, 3] = sw_point.y()
            m[2, 3] = sw_point.z()
            south_outer_perimeter_space.changeTransformation(openstudio.Transformation(m))
            south_outer_perimeter_space.setBuildingStory(story)
            south_outer_perimeter_space.setName(f"Story {floor + 1} South Outer Perimeter Space")

            west_core_polygon = openstudio.Point3dVector()
            west_core_polygon.append(outer_perimeter_sw_point)
            west_core_polygon.append(outer_perimeter_nw_point)
            west_core_polygon.append(inner_perimeter_nw_point)
            west_core_polygon.append(inner_perimeter_sw_point)
            west_core_space = openstudio.model.Space.fromFloorPrint(west_core_polygon, floor_to_floor_height, model)
            west_core_space = opt(west_core_space)
            m[0, 3] = outer_perimeter_sw_point.x()
            m[1, 3] = outer_perimeter_sw_point.y()
            m[2, 3] = outer_perimeter_sw_point.z()
            west_core_space.changeTransformation(openstudio.Transformation(m))
            west_core_space.setBuildingStory(story)
            west_core_space.setName(f"Story {floor + 1} West Core Space")

            north_core_polygon = openstudio.Point3dVector()
            north_core_polygon.append(outer_perimeter_nw_point)
            north_core_polygon.append(outer_perimeter_ne_point)
            north_core_polygon.append(inner_perimeter_ne_point)
            north_core_polygon.append(inner_perimeter_nw_point)
            north_core_space = openstudio.model.Space.fromFloorPrint(north_core_polygon, floor_to_floor_height, model)
            north_core_space = opt(north_core_space)
            m[0, 3] = inner_perimeter_nw_point.x()
            m[1, 3] = inner_perimeter_nw_point.y()
            m[2, 3] = inner_perimeter_nw_point.z()
            north_core_space.changeTransformation(openstudio.Transformation(m))
            north_core_space.setBuildingStory(story)
            north_core_space.setName(f"Story {floor + 1} North Core Space")

            east_core_polygon = openstudio.Point3dVector()
            east_core_polygon.append(outer_perimeter_ne_point)
            east_core_polygon.append(outer_perimeter_se_point)
            east_core_polygon.append(inner_perimeter_se_point)
            east_core_polygon.append(inner_perimeter_ne_point)
            east_core_space = openstudio.model.Space.fromFloorPrint(east_core_polygon, floor_to_floor_height, model)
            east_core_space = opt(east_core_space)
            m[0, 3] = inner_perimeter_se_point.x()
            m[1, 3] = inner_perimeter_se_point.y()
            m[2, 3] = inner_perimeter_se_point.z()
            east_core_space.changeTransformation(openstudio.Transformation(m))
            east_core_space.setBuildingStory(story)
            east_core_space.setName(f"Story {floor + 1} East Core Space")

            south_core_polygon = openstudio.Point3dVector()
            south_core_polygon.append(outer_perimeter_se_point)
            south_core_polygon.append(outer_perimeter_sw_point)
            south_core_polygon.append(inner_perimeter_sw_point)
            south_core_polygon.append(inner_perimeter_se_point)
            south_core_space = openstudio.model.Space.fromFloorPrint(south_core_polygon, floor_to_floor_height, model)
            south_core_space = opt(south_core_space)
            m[0, 3] = outer_perimeter_sw_point.x()
            m[1, 3] = outer_perimeter_sw_point.y()
            m[2, 3] = outer_perimeter_sw_point.z()
            south_core_space.changeTransformation(openstudio.Transformation(m))
            south_core_space.setBuildingStory(story)
            south_core_space.setName(f"Story {floor + 1} South Core Space")

            west_inner_perimeter_polygon = openstudio.Point3dVector()
            west_inner_perimeter_polygon.append(inner_perimeter_sw_point)
            west_inner_perimeter_polygon.append(inner_perimeter_nw_point)
            west_inner_perimeter_polygon.append(courtyard_nw_point)
            west_inner_perimeter_polygon.append(courtyard_sw_point)
            west_inner_perimeter_space = openstudio.model.Space.fromFloorPrint(west_inner_perimeter_polygon, floor_to_floor_height, model)
            west_inner_perimeter_space = opt(west_inner_perimeter_space)
            m[0, 3] = inner_perimeter_sw_point.x()
            m[1, 3] = inner_perimeter_sw_point.y()
            m[2, 3] = inner_perimeter_sw_point.z()
            west_inner_perimeter_space.changeTransformation(openstudio.Transformation(m))
            west_inner_perimeter_space.setBuildingStory(story)
            west_inner_perimeter_space.setName(f"Story {floor + 1} West Inner Perimeter Space")

            north_inner_perimeter_polygon = openstudio.Point3dVector()
            north_inner_perimeter_polygon.append(inner_perimeter_nw_point)
            north_inner_perimeter_polygon.append(inner_perimeter_ne_point)
            north_inner_perimeter_polygon.append(courtyard_ne_point)
            north_inner_perimeter_polygon.append(courtyard_nw_point)
            north_inner_perimeter_space = openstudio.model.Space.fromFloorPrint(north_inner_perimeter_polygon, floor_to_floor_height, model)
            north_inner_perimeter_space = opt(north_inner_perimeter_space)
            m[0, 3] = courtyard_nw_point.x()
            m[1, 3] = courtyard_nw_point.y()
            m[2, 3] = courtyard_nw_point.z()
            north_inner_perimeter_space.changeTransformation(openstudio.Transformation(m))
            north_inner_perimeter_space.setBuildingStory(story)
            north_inner_perimeter_space.setName(f"Story {floor + 1} North Inner Perimeter Space")

            east_inner_perimeter_polygon = openstudio.Point3dVector()
            east_inner_perimeter_polygon.append(inner_perimeter_ne_point)
            east_inner_perimeter_polygon.append(inner_perimeter_se_point)
            east_inner_perimeter_polygon.append(courtyard_se_point)
            east_inner_perimeter_polygon.append(courtyard_ne_point)
            east_inner_perimeter_space = openstudio.model.Space.fromFloorPrint(east_inner_perimeter_polygon, floor_to_floor_height, model)
            east_inner_perimeter_space = opt(east_inner_perimeter_space)
            m[0, 3] = courtyard_se_point.x()
            m[1, 3] = courtyard_se_point.y()
            m[2, 3] = courtyard_se_point.z()
            east_inner_perimeter_space.changeTransformation(openstudio.Transformation(m))
            east_inner_perimeter_space.setBuildingStory(story)
            east_inner_perimeter_space.setName(f"Story {floor + 1} East Inner Perimeter Space")

            south_inner_perimeter_polygon = openstudio.Point3dVector()
            south_inner_perimeter_polygon.append(inner_perimeter_se_point)
            south_inner_perimeter_polygon.append(inner_perimeter_sw_point)
            south_inner_perimeter_polygon.append(courtyard_sw_point)
            south_inner_perimeter_polygon.append(courtyard_se_point)
            south_inner_perimeter_space = openstudio.model.Space.fromFloorPrint(south_inner_perimeter_polygon, floor_to_floor_height, model)
            south_inner_perimeter_space = opt(south_inner_perimeter_space)
            m[0, 3] = inner_perimeter_sw_point.x()
            m[1, 3] = inner_perimeter_sw_point.y()
            m[2, 3] = inner_perimeter_sw_point.z()
            south_inner_perimeter_space.changeTransformation(openstudio.Transformation(m))
            south_inner_perimeter_space.setBuildingStory(story)
            south_inner_perimeter_space.setName(f"Story {floor + 1} South Inner Perimeter Space")
        else:
            # Minimal zones
            west_polygon = openstudio.Point3dVector()
            west_polygon.append(sw_point)
            west_polygon.append(nw_point)
            west_polygon.append(courtyard_nw_point)
            west_polygon.append(courtyard_sw_point)
            west_space = openstudio.model.Space.fromFloorPrint(west_polygon, floor_to_floor_height, model)
            west_space = opt(west_space)
            m[0, 3] = sw_point.x()
            m[1, 3] = sw_point.y()
            m[2, 3] = sw_point.z()
            west_space.changeTransformation(openstudio.Transformation(m))
            west_space.setBuildingStory(story)
            west_space.setName(f"Story {floor + 1} West Space")

            north_polygon = openstudio.Point3dVector()
            north_polygon.append(nw_point)
            north_polygon.append(ne_point)
            north_polygon.append(courtyard_ne_point)
            north_polygon.append(courtyard_nw_point)
            north_space = openstudio.model.Space.fromFloorPrint(north_polygon, floor_to_floor_height, model)
            north_space = opt(north_space)
            m[0, 3] = courtyard_nw_point.x()
            m[1, 3] = courtyard_nw_point.y()
            m[2, 3] = courtyard_nw_point.z()
            north_space.changeTransformation(openstudio.Transformation(m))
            north_space.setBuildingStory(story)
            north_space.setName(f"Story {floor + 1} North Space")

            east_polygon = openstudio.Point3dVector()
            east_polygon.append(ne_point)
            east_polygon.append(se_point)
            east_polygon.append(courtyard_se_point)
            east_polygon.append(courtyard_ne_point)
            east_space = openstudio.model.Space.fromFloorPrint(east_polygon, floor_to_floor_height, model)
            east_space = opt(east_space)
            m[0, 3] = courtyard_se_point.x()
            m[1, 3] = courtyard_se_point.y()
            m[2, 3] = courtyard_se_point.z()
            east_space.changeTransformation(openstudio.Transformation(m))
            east_space.setBuildingStory(story)
            east_space.setName(f"Story {floor + 1} East Space")

            south_polygon = openstudio.Point3dVector()
            south_polygon.append(se_point)
            south_polygon.append(sw_point)
            south_polygon.append(courtyard_sw_point)
            south_polygon.append(courtyard_se_point)
            south_space = openstudio.model.Space.fromFloorPrint(south_polygon, floor_to_floor_height, model)
            south_space = opt(south_space)
            m[0, 3] = sw_point.x()
            m[1, 3] = sw_point.y()
            m[2, 3] = sw_point.z()
            south_space.changeTransformation(openstudio.Transformation(m))
            south_space.setBuildingStory(story)
            south_space.setName(f"Story {floor + 1} South Space")
        # Set vertical story position
        story.setNominalZCoordinate(z)
    helpers.match_surfaces(model)

    return model


def create_shape_h(model,
                   length=40.0,
                   left_width=40.0,
                   center_width=10.0,
                   right_width=40.0,
                   left_end_length=15.0,
                   right_end_length=15.0,
                   left_upper_end_offset=15.0,
                   right_upper_end_offset=15.0,
                   num_floors=3,
                   floor_to_floor_height=3.8,
                   plenum_height=1,
                   perimeter_zone_depth=4.57):
    """Create an H shape in a model.

    :param model: OpenStudio model object
    :param length: Building length in meters
    :param left_width: Left width in meters
    :param center_width: Center width in meters
    :param right_width: Right width in meters
    :param left_end_length: Left end length in meters
    :param right_end_length: Right end length in meters
    :param left_upper_end_offset: Left upper end offset in meters
    :param right_upper_end_offset: Right upper end offset in meters
    :param num_floors: Number of floors
    :param floor_to_floor_height: Floor to floor height in meters
    :param plenum_height: Plenum height in meters
    :param perimeter_zone_depth: Perimeter zone depth in meters
    :return: OpenStudio model object (None on rejection)
    """
    if length <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Length must be greater than 0.')
        return None

    if left_width <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Left width must be greater than 0.')
        return None

    if right_width <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Right width must be greater than 0.')
        return None

    if center_width <= 1e-4 or center_width >= (min(left_width, right_width) - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Center width must be greater than 0 and less than {min(left_width, right_width)}m.")
        return None

    if left_end_length <= 1e-4 or left_end_length >= (length - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Left end length must be greater than 0 and less than {length}m.")
        return None

    if right_end_length <= 1e-4 or right_end_length >= (length - left_end_length - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Right end length must be greater than 0 and less than {length - left_end_length}m.")
        return None

    if left_upper_end_offset <= 1e-4 or left_upper_end_offset >= (left_width - center_width - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Left upper end offset must be greater than 0 and less than {left_width - center_width}m.")
        return None

    if right_upper_end_offset <= 1e-4 or right_upper_end_offset >= (right_width - center_width - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Right upper end offset must be greater than 0 and less than {right_width - center_width}m.")
        return None

    if num_floors <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Number of floors must be greater than 0.')
        return None

    if floor_to_floor_height <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Floor to floor height must be greater than 0.')
        return None

    if plenum_height < 0:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Plenum height must be greater than 0.')
        return None

    shortest_side = min(_ruby_div(length, 2), left_width, center_width, right_width, left_end_length, right_end_length)
    if perimeter_zone_depth < 0 or 2 * perimeter_zone_depth >= (shortest_side - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Perimeter zone depth must be greater than or equal to 0 and less than {_ruby_div(shortest_side, 2)}m.")
        return None

    # Loop through the number of floors
    for floor in range(0, math.floor(num_floors - 1) + 1):
        z = floor_to_floor_height * floor

        # Create a new story within the building
        story = openstudio.model.BuildingStory(model)
        story.setNominalFloortoFloorHeight(floor_to_floor_height)
        story.setName(f"Story {floor + 1}")

        left_origin = ((right_width - right_upper_end_offset) - (left_width - left_upper_end_offset)
                       if (right_width - right_upper_end_offset) > (left_width - left_upper_end_offset) else 0)
        left_nw_point = openstudio.Point3d(0, left_width + left_origin, z)
        left_ne_point = openstudio.Point3d(left_end_length, left_width + left_origin, z)
        left_se_point = openstudio.Point3d(left_end_length, left_origin, z)
        left_sw_point = openstudio.Point3d(0, left_origin, z)
        center_nw_point = openstudio.Point3d(left_end_length, left_ne_point.y() - left_upper_end_offset, z)
        center_ne_point = openstudio.Point3d(length - right_end_length, center_nw_point.y(), z)
        center_se_point = openstudio.Point3d(length - right_end_length, center_nw_point.y() - center_width, z)
        center_sw_point = openstudio.Point3d(left_end_length, center_se_point.y(), z)
        right_nw_point = openstudio.Point3d(length - right_end_length, center_ne_point.y() + right_upper_end_offset, z)
        right_ne_point = openstudio.Point3d(length, right_nw_point.y(), z)
        right_se_point = openstudio.Point3d(length, right_ne_point.y() - right_width, z)
        right_sw_point = openstudio.Point3d(length - right_end_length, right_se_point.y(), z)

        # Identity matrix for setting space origins
        m = openstudio.Matrix(4, 4, 0)
        m[0, 0] = 1
        m[1, 1] = 1
        m[2, 2] = 1
        m[3, 3] = 1

        # Define polygons for an H-shape building with perimeter core zoning
        if perimeter_zone_depth > 0:
            perimeter_left_nw_point = left_nw_point + openstudio.Vector3d(perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_left_ne_point = left_ne_point + openstudio.Vector3d(-perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_left_se_point = left_se_point + openstudio.Vector3d(-perimeter_zone_depth, perimeter_zone_depth, 0)
            perimeter_left_sw_point = left_sw_point + openstudio.Vector3d(perimeter_zone_depth, perimeter_zone_depth, 0)
            perimeter_center_nw_point = center_nw_point + openstudio.Vector3d(-perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_center_ne_point = center_ne_point + openstudio.Vector3d(perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_center_se_point = center_se_point + openstudio.Vector3d(perimeter_zone_depth, perimeter_zone_depth, 0)
            perimeter_center_sw_point = center_sw_point + openstudio.Vector3d(-perimeter_zone_depth, perimeter_zone_depth, 0)
            perimeter_right_nw_point = right_nw_point + openstudio.Vector3d(perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_right_ne_point = right_ne_point + openstudio.Vector3d(-perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_right_se_point = right_se_point + openstudio.Vector3d(-perimeter_zone_depth, perimeter_zone_depth, 0)
            perimeter_right_sw_point = right_sw_point + openstudio.Vector3d(perimeter_zone_depth, perimeter_zone_depth, 0)

            west_left_perimeter_polygon = openstudio.Point3dVector()
            west_left_perimeter_polygon.append(left_sw_point)
            west_left_perimeter_polygon.append(left_nw_point)
            west_left_perimeter_polygon.append(perimeter_left_nw_point)
            west_left_perimeter_polygon.append(perimeter_left_sw_point)
            west_left_perimeter_space = openstudio.model.Space.fromFloorPrint(west_left_perimeter_polygon, floor_to_floor_height, model)
            west_left_perimeter_space = opt(west_left_perimeter_space)
            m[0, 3] = left_sw_point.x()
            m[1, 3] = left_sw_point.y()
            m[2, 3] = left_sw_point.z()
            west_left_perimeter_space.changeTransformation(openstudio.Transformation(m))
            west_left_perimeter_space.setBuildingStory(story)
            west_left_perimeter_space.setName(f"Story {floor + 1} West Left Perimeter Space")

            north_left_perimeter_polygon = openstudio.Point3dVector()
            north_left_perimeter_polygon.append(left_nw_point)
            north_left_perimeter_polygon.append(left_ne_point)
            north_left_perimeter_polygon.append(perimeter_left_ne_point)
            north_left_perimeter_polygon.append(perimeter_left_nw_point)
            north_left_perimeter_space = openstudio.model.Space.fromFloorPrint(north_left_perimeter_polygon, floor_to_floor_height, model)
            north_left_perimeter_space = opt(north_left_perimeter_space)
            m[0, 3] = perimeter_left_nw_point.x()
            m[1, 3] = perimeter_left_nw_point.y()
            m[2, 3] = perimeter_left_nw_point.z()
            north_left_perimeter_space.changeTransformation(openstudio.Transformation(m))
            north_left_perimeter_space.setBuildingStory(story)
            north_left_perimeter_space.setName(f"Story {floor + 1} North Left Perimeter Space")

            east_upper_left_perimeter_polygon = openstudio.Point3dVector()
            east_upper_left_perimeter_polygon.append(left_ne_point)
            east_upper_left_perimeter_polygon.append(center_nw_point)
            east_upper_left_perimeter_polygon.append(perimeter_center_nw_point)
            east_upper_left_perimeter_polygon.append(perimeter_left_ne_point)
            east_upper_left_perimeter_space = openstudio.model.Space.fromFloorPrint(east_upper_left_perimeter_polygon, floor_to_floor_height, model)
            east_upper_left_perimeter_space = opt(east_upper_left_perimeter_space)
            m[0, 3] = perimeter_center_nw_point.x()
            m[1, 3] = perimeter_center_nw_point.y()
            m[2, 3] = perimeter_center_nw_point.z()
            east_upper_left_perimeter_space.changeTransformation(openstudio.Transformation(m))
            east_upper_left_perimeter_space.setBuildingStory(story)
            east_upper_left_perimeter_space.setName(f"Story {floor + 1} East Upper Left Perimeter Space")

            north_center_perimeter_polygon = openstudio.Point3dVector()
            north_center_perimeter_polygon.append(center_nw_point)
            north_center_perimeter_polygon.append(center_ne_point)
            north_center_perimeter_polygon.append(perimeter_center_ne_point)
            north_center_perimeter_polygon.append(perimeter_center_nw_point)
            north_center_perimeter_space = openstudio.model.Space.fromFloorPrint(north_center_perimeter_polygon, floor_to_floor_height, model)
            north_center_perimeter_space = opt(north_center_perimeter_space)
            m[0, 3] = perimeter_center_nw_point.x()
            m[1, 3] = perimeter_center_nw_point.y()
            m[2, 3] = perimeter_center_nw_point.z()
            north_center_perimeter_space.changeTransformation(openstudio.Transformation(m))
            north_center_perimeter_space.setBuildingStory(story)
            north_center_perimeter_space.setName(f"Story {floor + 1} North Center Perimeter Space")

            west_upper_right_perimeter_polygon = openstudio.Point3dVector()
            west_upper_right_perimeter_polygon.append(center_ne_point)
            west_upper_right_perimeter_polygon.append(right_nw_point)
            west_upper_right_perimeter_polygon.append(perimeter_right_nw_point)
            west_upper_right_perimeter_polygon.append(perimeter_center_ne_point)
            west_upper_right_perimeter_space = openstudio.model.Space.fromFloorPrint(west_upper_right_perimeter_polygon, floor_to_floor_height, model)
            west_upper_right_perimeter_space = opt(west_upper_right_perimeter_space)
            m[0, 3] = center_ne_point.x()
            m[1, 3] = center_ne_point.y()
            m[2, 3] = center_ne_point.z()
            west_upper_right_perimeter_space.changeTransformation(openstudio.Transformation(m))
            west_upper_right_perimeter_space.setBuildingStory(story)
            west_upper_right_perimeter_space.setName(f"Story {floor + 1} West Upper Right Perimeter Space")

            north_right_perimeter_polygon = openstudio.Point3dVector()
            north_right_perimeter_polygon.append(right_nw_point)
            north_right_perimeter_polygon.append(right_ne_point)
            north_right_perimeter_polygon.append(perimeter_right_ne_point)
            north_right_perimeter_polygon.append(perimeter_right_nw_point)
            north_right_perimeter_space = openstudio.model.Space.fromFloorPrint(north_right_perimeter_polygon, floor_to_floor_height, model)
            north_right_perimeter_space = opt(north_right_perimeter_space)
            m[0, 3] = perimeter_right_nw_point.x()
            m[1, 3] = perimeter_right_nw_point.y()
            m[2, 3] = perimeter_right_nw_point.z()
            north_right_perimeter_space.changeTransformation(openstudio.Transformation(m))
            north_right_perimeter_space.setBuildingStory(story)
            north_right_perimeter_space.setName(f"Story {floor + 1} North Right Perimeter Space")

            east_right_perimeter_polygon = openstudio.Point3dVector()
            east_right_perimeter_polygon.append(right_ne_point)
            east_right_perimeter_polygon.append(right_se_point)
            east_right_perimeter_polygon.append(perimeter_right_se_point)
            east_right_perimeter_polygon.append(perimeter_right_ne_point)
            east_right_perimeter_space = openstudio.model.Space.fromFloorPrint(east_right_perimeter_polygon, floor_to_floor_height, model)
            east_right_perimeter_space = opt(east_right_perimeter_space)
            m[0, 3] = perimeter_right_se_point.x()
            m[1, 3] = perimeter_right_se_point.y()
            m[2, 3] = perimeter_right_se_point.z()
            east_right_perimeter_space.changeTransformation(openstudio.Transformation(m))
            east_right_perimeter_space.setBuildingStory(story)
            east_right_perimeter_space.setName(f"Story {floor + 1} East Right Perimeter Space")

            south_right_perimeter_polygon = openstudio.Point3dVector()
            south_right_perimeter_polygon.append(right_se_point)
            south_right_perimeter_polygon.append(right_sw_point)
            south_right_perimeter_polygon.append(perimeter_right_sw_point)
            south_right_perimeter_polygon.append(perimeter_right_se_point)
            south_right_perimeter_space = openstudio.model.Space.fromFloorPrint(south_right_perimeter_polygon, floor_to_floor_height, model)
            south_right_perimeter_space = opt(south_right_perimeter_space)
            m[0, 3] = right_sw_point.x()
            m[1, 3] = right_sw_point.y()
            m[2, 3] = right_sw_point.z()
            south_right_perimeter_space.changeTransformation(openstudio.Transformation(m))
            south_right_perimeter_space.setBuildingStory(story)
            south_right_perimeter_space.setName(f"Story {floor + 1} South Right Perimeter Space")

            west_lower_right_perimeter_polygon = openstudio.Point3dVector()
            west_lower_right_perimeter_polygon.append(right_sw_point)
            west_lower_right_perimeter_polygon.append(center_se_point)
            west_lower_right_perimeter_polygon.append(perimeter_center_se_point)
            west_lower_right_perimeter_polygon.append(perimeter_right_sw_point)
            west_lower_right_perimeter_space = openstudio.model.Space.fromFloorPrint(west_lower_right_perimeter_polygon, floor_to_floor_height, model)
            west_lower_right_perimeter_space = opt(west_lower_right_perimeter_space)
            m[0, 3] = right_sw_point.x()
            m[1, 3] = right_sw_point.y()
            m[2, 3] = right_sw_point.z()
            west_lower_right_perimeter_space.changeTransformation(openstudio.Transformation(m))
            west_lower_right_perimeter_space.setBuildingStory(story)
            west_lower_right_perimeter_space.setName(f"Story {floor + 1} West Lower Right Perimeter Space")

            south_center_perimeter_polygon = openstudio.Point3dVector()
            south_center_perimeter_polygon.append(center_se_point)
            south_center_perimeter_polygon.append(center_sw_point)
            south_center_perimeter_polygon.append(perimeter_center_sw_point)
            south_center_perimeter_polygon.append(perimeter_center_se_point)
            south_center_perimeter_space = openstudio.model.Space.fromFloorPrint(south_center_perimeter_polygon, floor_to_floor_height, model)
            south_center_perimeter_space = opt(south_center_perimeter_space)
            m[0, 3] = center_sw_point.x()
            m[1, 3] = center_sw_point.y()
            m[2, 3] = center_sw_point.z()
            south_center_perimeter_space.changeTransformation(openstudio.Transformation(m))
            south_center_perimeter_space.setBuildingStory(story)
            south_center_perimeter_space.setName(f"Story {floor + 1} South Center Perimeter Space")

            east_lower_left_perimeter_polygon = openstudio.Point3dVector()
            east_lower_left_perimeter_polygon.append(center_sw_point)
            east_lower_left_perimeter_polygon.append(left_se_point)
            east_lower_left_perimeter_polygon.append(perimeter_left_se_point)
            east_lower_left_perimeter_polygon.append(perimeter_center_sw_point)
            east_lower_left_perimeter_space = openstudio.model.Space.fromFloorPrint(east_lower_left_perimeter_polygon, floor_to_floor_height, model)
            east_lower_left_perimeter_space = opt(east_lower_left_perimeter_space)
            m[0, 3] = perimeter_left_se_point.x()
            m[1, 3] = perimeter_left_se_point.y()
            m[2, 3] = perimeter_left_se_point.z()
            east_lower_left_perimeter_space.changeTransformation(openstudio.Transformation(m))
            east_lower_left_perimeter_space.setBuildingStory(story)
            east_lower_left_perimeter_space.setName(f"Story {floor + 1} East Lower Left Perimeter Space")

            south_left_perimeter_polygon = openstudio.Point3dVector()
            south_left_perimeter_polygon.append(left_se_point)
            south_left_perimeter_polygon.append(left_sw_point)
            south_left_perimeter_polygon.append(perimeter_left_sw_point)
            south_left_perimeter_polygon.append(perimeter_left_se_point)
            south_left_perimeter_space = openstudio.model.Space.fromFloorPrint(south_left_perimeter_polygon, floor_to_floor_height, model)
            south_left_perimeter_space = opt(south_left_perimeter_space)
            m[0, 3] = left_sw_point.x()
            m[1, 3] = left_sw_point.y()
            m[2, 3] = left_sw_point.z()
            south_left_perimeter_space.changeTransformation(openstudio.Transformation(m))
            south_left_perimeter_space.setBuildingStory(story)
            south_left_perimeter_space.setName(f"Story {floor + 1} South Left Perimeter Space")

            west_core_polygon = openstudio.Point3dVector()
            west_core_polygon.append(perimeter_left_sw_point)
            west_core_polygon.append(perimeter_left_nw_point)
            west_core_polygon.append(perimeter_left_ne_point)
            west_core_polygon.append(perimeter_center_nw_point)
            west_core_polygon.append(perimeter_center_sw_point)
            west_core_polygon.append(perimeter_left_se_point)
            west_core_space = openstudio.model.Space.fromFloorPrint(west_core_polygon, floor_to_floor_height, model)
            west_core_space = opt(west_core_space)
            m[0, 3] = perimeter_left_sw_point.x()
            m[1, 3] = perimeter_left_sw_point.y()
            m[2, 3] = perimeter_left_sw_point.z()
            west_core_space.changeTransformation(openstudio.Transformation(m))
            west_core_space.setBuildingStory(story)
            west_core_space.setName(f"Story {floor + 1} West Core Space")

            center_core_polygon = openstudio.Point3dVector()
            center_core_polygon.append(perimeter_center_sw_point)
            center_core_polygon.append(perimeter_center_nw_point)
            center_core_polygon.append(perimeter_center_ne_point)
            center_core_polygon.append(perimeter_center_se_point)
            center_core_space = openstudio.model.Space.fromFloorPrint(center_core_polygon, floor_to_floor_height, model)
            center_core_space = opt(center_core_space)
            m[0, 3] = perimeter_center_sw_point.x()
            m[1, 3] = perimeter_center_sw_point.y()
            m[2, 3] = perimeter_center_sw_point.z()
            center_core_space.changeTransformation(openstudio.Transformation(m))
            center_core_space.setBuildingStory(story)
            center_core_space.setName(f"Story {floor + 1} Center Core Space")

            east_core_polygon = openstudio.Point3dVector()
            east_core_polygon.append(perimeter_right_sw_point)
            east_core_polygon.append(perimeter_center_se_point)
            east_core_polygon.append(perimeter_center_ne_point)
            east_core_polygon.append(perimeter_right_nw_point)
            east_core_polygon.append(perimeter_right_ne_point)
            east_core_polygon.append(perimeter_right_se_point)
            east_core_space = openstudio.model.Space.fromFloorPrint(east_core_polygon, floor_to_floor_height, model)
            east_core_space = opt(east_core_space)
            m[0, 3] = perimeter_right_sw_point.x()
            m[1, 3] = perimeter_right_sw_point.y()
            m[2, 3] = perimeter_right_sw_point.z()
            east_core_space.changeTransformation(openstudio.Transformation(m))
            east_core_space.setBuildingStory(story)
            east_core_space.setName(f"Story {floor + 1} East Core Space")
        else:
            # Minimal zones
            west_polygon = openstudio.Point3dVector()
            west_polygon.append(left_sw_point)
            west_polygon.append(left_nw_point)
            west_polygon.append(left_ne_point)
            west_polygon.append(center_nw_point)
            west_polygon.append(center_sw_point)
            west_polygon.append(left_se_point)
            west_space = openstudio.model.Space.fromFloorPrint(west_polygon, floor_to_floor_height, model)
            west_space = opt(west_space)
            m[0, 3] = left_sw_point.x()
            m[1, 3] = left_sw_point.y()
            m[2, 3] = left_sw_point.z()
            west_space.changeTransformation(openstudio.Transformation(m))
            west_space.setBuildingStory(story)
            west_space.setName(f"Story {floor + 1} West Space")

            center_polygon = openstudio.Point3dVector()
            center_polygon.append(center_sw_point)
            center_polygon.append(center_nw_point)
            center_polygon.append(center_ne_point)
            center_polygon.append(center_se_point)
            center_space = openstudio.model.Space.fromFloorPrint(center_polygon, floor_to_floor_height, model)
            center_space = opt(center_space)
            m[0, 3] = center_sw_point.x()
            m[1, 3] = center_sw_point.y()
            m[2, 3] = center_sw_point.z()
            center_space.changeTransformation(openstudio.Transformation(m))
            center_space.setBuildingStory(story)
            center_space.setName(f"Story {floor + 1} Center Space")

            east_polygon = openstudio.Point3dVector()
            east_polygon.append(right_sw_point)
            east_polygon.append(center_se_point)
            east_polygon.append(center_ne_point)
            east_polygon.append(right_nw_point)
            east_polygon.append(right_ne_point)
            east_polygon.append(right_se_point)
            east_space = openstudio.model.Space.fromFloorPrint(east_polygon, floor_to_floor_height, model)
            east_space = opt(east_space)
            m[0, 3] = right_sw_point.x()
            m[1, 3] = right_sw_point.y()
            m[2, 3] = right_sw_point.z()
            east_space.changeTransformation(openstudio.Transformation(m))
            east_space.setBuildingStory(story)
            east_space.setName(f"Story {floor + 1} East Space")
        # Set vertical story position
        story.setNominalZCoordinate(z)

    helpers.match_surfaces(model)

    return model


def create_shape_l(model,
                   length=40.0,
                   width=40.0,
                   lower_end_width=20.0,
                   upper_end_length=20.0,
                   num_floors=3,
                   floor_to_floor_height=3.8,
                   plenum_height=1.0,
                   perimeter_zone_depth=4.57):
    """Create an L shape in a model.

    :param model: OpenStudio model object
    :param length: Building length in meters
    :param width: Building width in meters
    :param lower_end_width: Lower end width in meters
    :param upper_end_length: Upper end width in meters
    :param num_floors: Number of floors
    :param floor_to_floor_height: Floor to floor height in meters
    :param plenum_height: Plenum height in meters
    :param perimeter_zone_depth: Perimeter zone depth in meters
    :return: OpenStudio model object (None on rejection)
    """
    if length <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Length must be greater than 0.')
        return None

    if width <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Width must be greater than 0.')
        return None

    if lower_end_width <= 1e-4 or lower_end_width >= (width - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Lower end width must be greater than 0 and less than {width}m.")
        return None

    if upper_end_length <= 1e-4 or upper_end_length >= (length - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Upper end length must be greater than 0 and less than {length}m.")
        return None

    if num_floors <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Number of floors must be greater than 0.')
        return None

    if floor_to_floor_height <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Floor to floor height must be greater than 0.')
        return None

    if plenum_height < 0:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Plenum height must be greater than 0.')
        return None

    shortest_side = min(lower_end_width, upper_end_length)
    if perimeter_zone_depth < 0 or 2 * perimeter_zone_depth >= (shortest_side - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Perimeter zone depth must be greater than or equal to 0 and less than {_ruby_div(shortest_side, 2)}m.")
        return None

    # Loop through the number of floors
    for floor in range(0, math.floor(num_floors - 1) + 1):
        z = floor_to_floor_height * floor

        # Create a new story within the building
        story = openstudio.model.BuildingStory(model)
        story.setNominalFloortoFloorHeight(floor_to_floor_height)
        story.setName(f"Story {floor + 1}")

        nw_point = openstudio.Point3d(0, width, z)
        upper_ne_point = openstudio.Point3d(upper_end_length, width, z)
        upper_sw_point = openstudio.Point3d(upper_end_length, lower_end_width, z)
        lower_ne_point = openstudio.Point3d(length, lower_end_width, z)
        se_point = openstudio.Point3d(length, 0, z)
        sw_point = openstudio.Point3d(0, 0, z)

        # Identity matrix for setting space origins
        m = openstudio.Matrix(4, 4, 0)
        m[0, 0] = 1
        m[1, 1] = 1
        m[2, 2] = 1
        m[3, 3] = 1

        # Define polygons for a L-shape building with perimeter core zoning
        if perimeter_zone_depth > 0:
            perimeter_nw_point = nw_point + openstudio.Vector3d(perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_upper_ne_point = upper_ne_point + openstudio.Vector3d(-perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_upper_sw_point = upper_sw_point + openstudio.Vector3d(-perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_lower_ne_point = lower_ne_point + openstudio.Vector3d(-perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_se_point = se_point + openstudio.Vector3d(-perimeter_zone_depth, perimeter_zone_depth, 0)
            perimeter_lower_sw_point = sw_point + openstudio.Vector3d(perimeter_zone_depth, perimeter_zone_depth, 0)

            west_perimeter_polygon = openstudio.Point3dVector()
            west_perimeter_polygon.append(sw_point)
            west_perimeter_polygon.append(nw_point)
            west_perimeter_polygon.append(perimeter_nw_point)
            west_perimeter_polygon.append(perimeter_lower_sw_point)
            west_perimeter_space = openstudio.model.Space.fromFloorPrint(west_perimeter_polygon, floor_to_floor_height, model)
            west_perimeter_space = opt(west_perimeter_space)
            m[0, 3] = sw_point.x()
            m[1, 3] = sw_point.y()
            m[2, 3] = sw_point.z()
            west_perimeter_space.changeTransformation(openstudio.Transformation(m))
            west_perimeter_space.setBuildingStory(story)
            west_perimeter_space.setName(f"Story {floor + 1} West Perimeter Space")

            north_upper_perimeter_polygon = openstudio.Point3dVector()
            north_upper_perimeter_polygon.append(nw_point)
            north_upper_perimeter_polygon.append(upper_ne_point)
            north_upper_perimeter_polygon.append(perimeter_upper_ne_point)
            north_upper_perimeter_polygon.append(perimeter_nw_point)
            north_upper_perimeter_space = openstudio.model.Space.fromFloorPrint(north_upper_perimeter_polygon, floor_to_floor_height, model)
            north_upper_perimeter_space = opt(north_upper_perimeter_space)
            m[0, 3] = perimeter_nw_point.x()
            m[1, 3] = perimeter_nw_point.y()
            m[2, 3] = perimeter_nw_point.z()
            north_upper_perimeter_space.changeTransformation(openstudio.Transformation(m))
            north_upper_perimeter_space.setBuildingStory(story)
            north_upper_perimeter_space.setName(f"Story {floor + 1} North Upper Perimeter Space")

            east_upper_perimeter_polygon = openstudio.Point3dVector()
            east_upper_perimeter_polygon.append(upper_ne_point)
            east_upper_perimeter_polygon.append(upper_sw_point)
            east_upper_perimeter_polygon.append(perimeter_upper_sw_point)
            east_upper_perimeter_polygon.append(perimeter_upper_ne_point)
            east_upper_perimeter_space = openstudio.model.Space.fromFloorPrint(east_upper_perimeter_polygon, floor_to_floor_height, model)
            east_upper_perimeter_space = opt(east_upper_perimeter_space)
            m[0, 3] = perimeter_upper_sw_point.x()
            m[1, 3] = perimeter_upper_sw_point.y()
            m[2, 3] = perimeter_upper_sw_point.z()
            east_upper_perimeter_space.changeTransformation(openstudio.Transformation(m))
            east_upper_perimeter_space.setBuildingStory(story)
            east_upper_perimeter_space.setName(f"Story {floor + 1} East Upper Perimeter Space")

            north_lower_perimeter_polygon = openstudio.Point3dVector()
            north_lower_perimeter_polygon.append(upper_sw_point)
            north_lower_perimeter_polygon.append(lower_ne_point)
            north_lower_perimeter_polygon.append(perimeter_lower_ne_point)
            north_lower_perimeter_polygon.append(perimeter_upper_sw_point)
            north_lower_perimeter_space = openstudio.model.Space.fromFloorPrint(north_lower_perimeter_polygon, floor_to_floor_height, model)
            north_lower_perimeter_space = opt(north_lower_perimeter_space)
            m[0, 3] = perimeter_upper_sw_point.x()
            m[1, 3] = perimeter_upper_sw_point.y()
            m[2, 3] = perimeter_upper_sw_point.z()
            north_lower_perimeter_space.changeTransformation(openstudio.Transformation(m))
            north_lower_perimeter_space.setBuildingStory(story)
            north_lower_perimeter_space.setName(f"Story {floor + 1} North Lower Perimeter Space")

            east_lower_perimeter_polygon = openstudio.Point3dVector()
            east_lower_perimeter_polygon.append(lower_ne_point)
            east_lower_perimeter_polygon.append(se_point)
            east_lower_perimeter_polygon.append(perimeter_se_point)
            east_lower_perimeter_polygon.append(perimeter_lower_ne_point)
            east_lower_perimeter_space = openstudio.model.Space.fromFloorPrint(east_lower_perimeter_polygon, floor_to_floor_height, model)
            east_lower_perimeter_space = opt(east_lower_perimeter_space)
            m[0, 3] = perimeter_se_point.x()
            m[1, 3] = perimeter_se_point.y()
            m[2, 3] = perimeter_se_point.z()
            east_lower_perimeter_space.changeTransformation(openstudio.Transformation(m))
            east_lower_perimeter_space.setBuildingStory(story)
            east_lower_perimeter_space.setName(f"Story {floor + 1} East Lower Perimeter Space")

            south_perimeter_polygon = openstudio.Point3dVector()
            south_perimeter_polygon.append(se_point)
            south_perimeter_polygon.append(sw_point)
            south_perimeter_polygon.append(perimeter_lower_sw_point)
            south_perimeter_polygon.append(perimeter_se_point)
            south_perimeter_space = openstudio.model.Space.fromFloorPrint(south_perimeter_polygon, floor_to_floor_height, model)
            south_perimeter_space = opt(south_perimeter_space)
            m[0, 3] = sw_point.x()
            m[1, 3] = sw_point.y()
            m[2, 3] = sw_point.z()
            south_perimeter_space.changeTransformation(openstudio.Transformation(m))
            south_perimeter_space.setBuildingStory(story)
            south_perimeter_space.setName(f"Story {floor + 1} South Perimeter Space")

            west_core_polygon = openstudio.Point3dVector()
            west_core_polygon.append(perimeter_lower_sw_point)
            west_core_polygon.append(perimeter_nw_point)
            west_core_polygon.append(perimeter_upper_ne_point)
            west_core_polygon.append(perimeter_upper_sw_point)
            west_core_space = openstudio.model.Space.fromFloorPrint(west_core_polygon, floor_to_floor_height, model)
            west_core_space = opt(west_core_space)
            m[0, 3] = perimeter_lower_sw_point.x()
            m[1, 3] = perimeter_lower_sw_point.y()
            m[2, 3] = perimeter_lower_sw_point.z()
            west_core_space.changeTransformation(openstudio.Transformation(m))
            west_core_space.setBuildingStory(story)
            west_core_space.setName(f"Story {floor + 1} West Core Space")

            east_core_polygon = openstudio.Point3dVector()
            east_core_polygon.append(perimeter_upper_sw_point)
            east_core_polygon.append(perimeter_lower_ne_point)
            east_core_polygon.append(perimeter_se_point)
            east_core_polygon.append(perimeter_lower_sw_point)
            east_core_space = openstudio.model.Space.fromFloorPrint(east_core_polygon, floor_to_floor_height, model)
            east_core_space = opt(east_core_space)
            m[0, 3] = perimeter_lower_sw_point.x()
            m[1, 3] = perimeter_lower_sw_point.y()
            m[2, 3] = perimeter_lower_sw_point.z()
            east_core_space.changeTransformation(openstudio.Transformation(m))
            east_core_space.setBuildingStory(story)
            east_core_space.setName(f"Story {floor + 1} East Core Space")
        else:
            # Minimal zones
            west_polygon = openstudio.Point3dVector()
            west_polygon.append(sw_point)
            west_polygon.append(nw_point)
            west_polygon.append(upper_ne_point)
            west_polygon.append(upper_sw_point)
            west_space = openstudio.model.Space.fromFloorPrint(west_polygon, floor_to_floor_height, model)
            west_space = opt(west_space)
            m[0, 3] = sw_point.x()
            m[1, 3] = sw_point.y()
            m[2, 3] = sw_point.z()
            west_space.changeTransformation(openstudio.Transformation(m))
            west_space.setBuildingStory(story)
            west_space.setName(f"Story {floor + 1} West Space")

            east_polygon = openstudio.Point3dVector()
            east_polygon.append(sw_point)
            east_polygon.append(upper_sw_point)
            east_polygon.append(lower_ne_point)
            east_polygon.append(se_point)
            east_space = openstudio.model.Space.fromFloorPrint(east_polygon, floor_to_floor_height, model)
            east_space = opt(east_space)
            m[0, 3] = sw_point.x()
            m[1, 3] = sw_point.y()
            m[2, 3] = sw_point.z()
            east_space.changeTransformation(openstudio.Transformation(m))
            east_space.setBuildingStory(story)
            east_space.setName(f"Story {floor + 1} East Space")
        # Set vertical story position
        story.setNominalZCoordinate(z)
    helpers.match_surfaces(model)

    return model


def create_shape_t(model,
                   length=40.0,
                   width=40.0,
                   upper_end_width=20.0,
                   lower_end_length=20.0,
                   left_end_offset=10.0,
                   num_floors=3,
                   floor_to_floor_height=3.8,
                   plenum_height=1.0,
                   perimeter_zone_depth=4.57):
    """Create a T shape in a model.

    :param model: OpenStudio model object
    :param length: Building length in meters
    :param width: Building width in meters
    :param upper_end_width: Upper end width in meters
    :param lower_end_length: Lower end length in meters
    :param left_end_offset: Left end offset in meters
    :param num_floors: Number of floors
    :param floor_to_floor_height: Floor to floor height in meters
    :param plenum_height: Plenum height in meters
    :param perimeter_zone_depth: Perimeter zone depth in meters
    :return: OpenStudio model object (None on rejection)
    """
    if length <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Length must be greater than 0.')
        return None

    if width <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Width must be greater than 0.')
        return None

    if upper_end_width <= 1e-4 or upper_end_width >= (width - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Upper end width must be greater than 0 and less than {width}m.")
        return None

    if lower_end_length <= 1e-4 or lower_end_length >= (length - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Lower end length must be greater than 0 and less than {length}m.")
        return None

    if left_end_offset <= 1e-4 or left_end_offset >= (length - lower_end_length - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Left end offset must be greater than 0 and less than {length - lower_end_length}m.")
        return None

    if num_floors <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Number of floors must be greater than 0.')
        return None

    if floor_to_floor_height <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Floor to floor height must be greater than 0.')
        return None

    if plenum_height < 0:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Plenum height must be greater than 0.')
        return None

    shortest_side = min(length, width, upper_end_width, lower_end_length)
    if perimeter_zone_depth < 0 or 2 * perimeter_zone_depth >= (shortest_side - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Perimeter zone depth must be greater than or equal to 0 and less than {_ruby_div(shortest_side, 2)}m.")
        return None

    # Loop through the number of floors
    for floor in range(0, math.floor(num_floors - 1) + 1):
        z = floor_to_floor_height * floor

        # Create a new story within the building
        story = openstudio.model.BuildingStory(model)
        story.setNominalFloortoFloorHeight(floor_to_floor_height)
        story.setName(f"Story {floor + 1}")

        lower_ne_point = openstudio.Point3d(left_end_offset, width - upper_end_width, z)
        upper_sw_point = openstudio.Point3d(0, width - upper_end_width, z)
        upper_nw_point = openstudio.Point3d(0, width, z)
        upper_ne_point = openstudio.Point3d(length, width, z)
        upper_se_point = openstudio.Point3d(length, width - upper_end_width, z)
        lower_nw_point = openstudio.Point3d(left_end_offset + lower_end_length, width - upper_end_width, z)
        lower_se_point = openstudio.Point3d(left_end_offset + lower_end_length, 0, z)
        lower_sw_point = openstudio.Point3d(left_end_offset, 0, z)

        # Identity matrix for setting space origins
        m = openstudio.Matrix(4, 4, 0)
        m[0, 0] = 1
        m[1, 1] = 1
        m[2, 2] = 1
        m[3, 3] = 1

        # Define polygons for a T-shape building with perimeter core zoning
        if perimeter_zone_depth > 0:
            perimeter_lower_ne_point = lower_ne_point + openstudio.Vector3d(perimeter_zone_depth, perimeter_zone_depth, 0)
            perimeter_upper_sw_point = upper_sw_point + openstudio.Vector3d(perimeter_zone_depth, perimeter_zone_depth, 0)
            perimeter_upper_nw_point = upper_nw_point + openstudio.Vector3d(perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_upper_ne_point = upper_ne_point + openstudio.Vector3d(-perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_upper_se_point = upper_se_point + openstudio.Vector3d(-perimeter_zone_depth, perimeter_zone_depth, 0)
            perimeter_lower_nw_point = lower_nw_point + openstudio.Vector3d(-perimeter_zone_depth, perimeter_zone_depth, 0)
            perimeter_lower_se_point = lower_se_point + openstudio.Vector3d(-perimeter_zone_depth, perimeter_zone_depth, 0)
            perimeter_lower_sw_point = lower_sw_point + openstudio.Vector3d(perimeter_zone_depth, perimeter_zone_depth, 0)

            west_lower_perimeter_polygon = openstudio.Point3dVector()
            west_lower_perimeter_polygon.append(lower_sw_point)
            west_lower_perimeter_polygon.append(lower_ne_point)
            west_lower_perimeter_polygon.append(perimeter_lower_ne_point)
            west_lower_perimeter_polygon.append(perimeter_lower_sw_point)
            west_lower_perimeter_space = openstudio.model.Space.fromFloorPrint(west_lower_perimeter_polygon, floor_to_floor_height, model)
            west_lower_perimeter_space = opt(west_lower_perimeter_space)
            m[0, 3] = lower_sw_point.x()
            m[1, 3] = lower_sw_point.y()
            m[2, 3] = lower_sw_point.z()
            west_lower_perimeter_space.changeTransformation(openstudio.Transformation(m))
            west_lower_perimeter_space.setBuildingStory(story)
            west_lower_perimeter_space.setName(f"Story {floor + 1} West Lower Perimeter Space")

            south_upper_left_perimeter_polygon = openstudio.Point3dVector()
            south_upper_left_perimeter_polygon.append(lower_ne_point)
            south_upper_left_perimeter_polygon.append(upper_sw_point)
            south_upper_left_perimeter_polygon.append(perimeter_upper_sw_point)
            south_upper_left_perimeter_polygon.append(perimeter_lower_ne_point)
            south_upper_left_perimeter_space = openstudio.model.Space.fromFloorPrint(south_upper_left_perimeter_polygon, floor_to_floor_height, model)
            south_upper_left_perimeter_space = opt(south_upper_left_perimeter_space)
            m[0, 3] = upper_sw_point.x()
            m[1, 3] = upper_sw_point.y()
            m[2, 3] = upper_sw_point.z()
            south_upper_left_perimeter_space.changeTransformation(openstudio.Transformation(m))
            south_upper_left_perimeter_space.setBuildingStory(story)
            south_upper_left_perimeter_space.setName(f"Story {floor + 1} South Upper Left Perimeter Space")

            west_upper_perimeter_polygon = openstudio.Point3dVector()
            west_upper_perimeter_polygon.append(upper_sw_point)
            west_upper_perimeter_polygon.append(upper_nw_point)
            west_upper_perimeter_polygon.append(perimeter_upper_nw_point)
            west_upper_perimeter_polygon.append(perimeter_upper_sw_point)
            west_upper_perimeter_space = openstudio.model.Space.fromFloorPrint(west_upper_perimeter_polygon, floor_to_floor_height, model)
            west_upper_perimeter_space = opt(west_upper_perimeter_space)
            m[0, 3] = upper_sw_point.x()
            m[1, 3] = upper_sw_point.y()
            m[2, 3] = upper_sw_point.z()
            west_upper_perimeter_space.changeTransformation(openstudio.Transformation(m))
            west_upper_perimeter_space.setBuildingStory(story)
            west_upper_perimeter_space.setName(f"Story {floor + 1} West Upper Perimeter Space")

            north_perimeter_polygon = openstudio.Point3dVector()
            north_perimeter_polygon.append(upper_nw_point)
            north_perimeter_polygon.append(upper_ne_point)
            north_perimeter_polygon.append(perimeter_upper_ne_point)
            north_perimeter_polygon.append(perimeter_upper_nw_point)
            north_perimeter_space = openstudio.model.Space.fromFloorPrint(north_perimeter_polygon, floor_to_floor_height, model)
            north_perimeter_space = opt(north_perimeter_space)
            m[0, 3] = perimeter_upper_nw_point.x()
            m[1, 3] = perimeter_upper_nw_point.y()
            m[2, 3] = perimeter_upper_nw_point.z()
            north_perimeter_space.changeTransformation(openstudio.Transformation(m))
            north_perimeter_space.setBuildingStory(story)
            north_perimeter_space.setName(f"Story {floor + 1} North Perimeter Space")

            east_upper_perimeter_polygon = openstudio.Point3dVector()
            east_upper_perimeter_polygon.append(upper_ne_point)
            east_upper_perimeter_polygon.append(upper_se_point)
            east_upper_perimeter_polygon.append(perimeter_upper_se_point)
            east_upper_perimeter_polygon.append(perimeter_upper_ne_point)
            east_upper_perimeter_space = openstudio.model.Space.fromFloorPrint(east_upper_perimeter_polygon, floor_to_floor_height, model)
            east_upper_perimeter_space = opt(east_upper_perimeter_space)
            m[0, 3] = perimeter_upper_se_point.x()
            m[1, 3] = perimeter_upper_se_point.y()
            m[2, 3] = perimeter_upper_se_point.z()
            east_upper_perimeter_space.changeTransformation(openstudio.Transformation(m))
            east_upper_perimeter_space.setBuildingStory(story)
            east_upper_perimeter_space.setName(f"Story {floor + 1} East Upper Perimeter Space")

            south_upper_right_perimeter_polygon = openstudio.Point3dVector()
            south_upper_right_perimeter_polygon.append(upper_se_point)
            south_upper_right_perimeter_polygon.append(lower_nw_point)
            south_upper_right_perimeter_polygon.append(perimeter_lower_nw_point)
            south_upper_right_perimeter_polygon.append(perimeter_upper_se_point)
            south_upper_right_perimeter_space = openstudio.model.Space.fromFloorPrint(south_upper_right_perimeter_polygon, floor_to_floor_height, model)
            south_upper_right_perimeter_space = opt(south_upper_right_perimeter_space)
            m[0, 3] = lower_nw_point.x()
            m[1, 3] = lower_nw_point.y()
            m[2, 3] = lower_nw_point.z()
            south_upper_right_perimeter_space.changeTransformation(openstudio.Transformation(m))
            south_upper_right_perimeter_space.setBuildingStory(story)
            # NOTE: upstream names this "South Upper Left" (a legacy bug kept verbatim;
            # OpenStudio uniquifies the duplicate name).
            south_upper_right_perimeter_space.setName(f"Story {floor + 1} South Upper Left Perimeter Space")

            east_lower_perimeter_polygon = openstudio.Point3dVector()
            east_lower_perimeter_polygon.append(lower_nw_point)
            east_lower_perimeter_polygon.append(lower_se_point)
            east_lower_perimeter_polygon.append(perimeter_lower_se_point)
            east_lower_perimeter_polygon.append(perimeter_lower_nw_point)
            east_lower_perimeter_space = openstudio.model.Space.fromFloorPrint(east_lower_perimeter_polygon, floor_to_floor_height, model)
            east_lower_perimeter_space = opt(east_lower_perimeter_space)
            m[0, 3] = perimeter_lower_se_point.x()
            m[1, 3] = perimeter_lower_se_point.y()
            m[2, 3] = perimeter_lower_se_point.z()
            east_lower_perimeter_space.changeTransformation(openstudio.Transformation(m))
            east_lower_perimeter_space.setBuildingStory(story)
            east_lower_perimeter_space.setName(f"Story {floor + 1} East Lower Perimeter Space")

            south_lower_perimeter_polygon = openstudio.Point3dVector()
            south_lower_perimeter_polygon.append(lower_se_point)
            south_lower_perimeter_polygon.append(lower_sw_point)
            south_lower_perimeter_polygon.append(perimeter_lower_sw_point)
            south_lower_perimeter_polygon.append(perimeter_lower_se_point)
            south_lower_perimeter_space = openstudio.model.Space.fromFloorPrint(south_lower_perimeter_polygon, floor_to_floor_height, model)
            south_lower_perimeter_space = opt(south_lower_perimeter_space)
            m[0, 3] = lower_sw_point.x()
            m[1, 3] = lower_sw_point.y()
            m[2, 3] = lower_sw_point.z()
            south_lower_perimeter_space.changeTransformation(openstudio.Transformation(m))
            south_lower_perimeter_space.setBuildingStory(story)
            south_lower_perimeter_space.setName(f"Story {floor + 1} South Lower Perimeter Space")

            north_core_polygon = openstudio.Point3dVector()
            north_core_polygon.append(perimeter_upper_sw_point)
            north_core_polygon.append(perimeter_upper_nw_point)
            north_core_polygon.append(perimeter_upper_ne_point)
            north_core_polygon.append(perimeter_upper_se_point)
            north_core_polygon.append(perimeter_lower_nw_point)
            north_core_polygon.append(perimeter_lower_ne_point)
            north_core_space = openstudio.model.Space.fromFloorPrint(north_core_polygon, floor_to_floor_height, model)
            north_core_space = opt(north_core_space)
            m[0, 3] = perimeter_upper_sw_point.x()
            m[1, 3] = perimeter_upper_sw_point.y()
            m[2, 3] = perimeter_upper_sw_point.z()
            north_core_space.changeTransformation(openstudio.Transformation(m))
            north_core_space.setBuildingStory(story)
            north_core_space.setName(f"Story {floor + 1} North Core Space")

            south_core_polygon = openstudio.Point3dVector()
            south_core_polygon.append(perimeter_lower_sw_point)
            south_core_polygon.append(perimeter_lower_ne_point)
            south_core_polygon.append(perimeter_lower_nw_point)
            south_core_polygon.append(perimeter_lower_se_point)
            south_core_space = openstudio.model.Space.fromFloorPrint(south_core_polygon, floor_to_floor_height, model)
            south_core_space = opt(south_core_space)
            m[0, 3] = perimeter_lower_sw_point.x()
            m[1, 3] = perimeter_lower_sw_point.y()
            m[2, 3] = perimeter_lower_sw_point.z()
            south_core_space.changeTransformation(openstudio.Transformation(m))
            south_core_space.setBuildingStory(story)
            south_core_space.setName(f"Story {floor + 1} South Core Space")
        else:
            # Minimal zones
            north_polygon = openstudio.Point3dVector()
            north_polygon.append(upper_sw_point)
            north_polygon.append(upper_nw_point)
            north_polygon.append(upper_ne_point)
            north_polygon.append(upper_se_point)
            north_polygon.append(lower_nw_point)
            north_polygon.append(lower_ne_point)
            north_space = openstudio.model.Space.fromFloorPrint(north_polygon, floor_to_floor_height, model)
            north_space = opt(north_space)
            m[0, 3] = upper_sw_point.x()
            m[1, 3] = upper_sw_point.y()
            m[2, 3] = upper_sw_point.z()
            north_space.changeTransformation(openstudio.Transformation(m))
            north_space.setBuildingStory(story)
            north_space.setName(f"Story {floor + 1} North Space")

            south_polygon = openstudio.Point3dVector()
            south_polygon.append(lower_sw_point)
            south_polygon.append(lower_ne_point)
            south_polygon.append(lower_nw_point)
            south_polygon.append(lower_se_point)
            south_space = openstudio.model.Space.fromFloorPrint(south_polygon, floor_to_floor_height, model)
            south_space = opt(south_space)
            m[0, 3] = lower_sw_point.x()
            m[1, 3] = lower_sw_point.y()
            m[2, 3] = lower_sw_point.z()
            south_space.changeTransformation(openstudio.Transformation(m))
            south_space.setBuildingStory(story)
            south_space.setName(f"Story {floor + 1} South Space")
        # Set vertical story position
        story.setNominalZCoordinate(z)
    helpers.match_surfaces(model)

    return model


def create_shape_u(model,
                   length=40.0,
                   left_width=40.0,
                   right_width=40.0,
                   left_end_length=15.0,
                   right_end_length=15.0,
                   left_end_offset=25.0,
                   num_floors=3.0,
                   floor_to_floor_height=3.8,
                   plenum_height=1.0,
                   perimeter_zone_depth=4.57):
    """Create a U shape in a model.

    :param model: OpenStudio model object
    :param length: Building length in meters
    :param left_width: Left width in meters
    :param right_width: Right width in meters
    :param left_end_length: Left end length in meters
    :param right_end_length: Right end length in meters
    :param left_end_offset: Left end offset in meters
    :param num_floors: Number of floors
    :param floor_to_floor_height: Floor to floor height in meters
    :param plenum_height: Plenum height in meters
    :param perimeter_zone_depth: Perimeter zone depth in meters
    :return: OpenStudio model object (None on rejection)
    """
    if length <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Length must be greater than 0.')
        return None

    if left_width <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Left width must be greater than 0.')
        return None

    if left_end_length <= 1e-4 or left_end_length >= (length - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Left end length must be greater than 0 and less than {length}m.")
        return None

    if right_end_length <= 1e-4 or right_end_length >= (length - left_end_length - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Right end length must be greater than 0 and less than {length - left_end_length}m.")
        return None

    if left_end_offset <= 1e-4 or left_end_offset >= (left_width - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Left end offset must be greater than 0 and less than {left_width}m.")
        return None

    if right_width <= (left_width - left_end_offset - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Right width must be greater than {left_width - left_end_offset}m.")
        return None

    if num_floors <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Number of floors must be greater than 0.')
        return None

    if floor_to_floor_height <= 1e-4:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Floor to floor height must be greater than 0.')
        return None

    if plenum_height < 0:
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', 'Plenum height must be greater than 0.')
        return None

    shortest_side = min(_ruby_div(length, 2), left_width, right_width, left_end_length, right_end_length, left_width - left_end_offset)
    if perimeter_zone_depth < 0 or 2 * perimeter_zone_depth >= (shortest_side - 1e-4):
        openstudio.logFree(openstudio.Error, 'openstudio.standards.Geometry.Create.Shape', f"Perimeter zone depth must be greater than or equal to 0 and less than {_ruby_div(shortest_side, 2)}m.")
        return None

    # Loop through the number of floors
    for floor in range(0, math.floor(num_floors - 1) + 1):
        z = floor_to_floor_height * floor

        # Create a new story within the building
        story = openstudio.model.BuildingStory(model)
        story.setNominalFloortoFloorHeight(floor_to_floor_height)
        story.setName(f"Story {floor + 1}")

        left_nw_point = openstudio.Point3d(0, left_width, z)
        left_ne_point = openstudio.Point3d(left_end_length, left_width, z)
        upper_sw_point = openstudio.Point3d(left_end_length, left_width - left_end_offset, z)
        upper_se_point = openstudio.Point3d(length - right_end_length, left_width - left_end_offset, z)
        right_nw_point = openstudio.Point3d(length - right_end_length, right_width, z)
        right_ne_point = openstudio.Point3d(length, right_width, z)
        lower_se_point = openstudio.Point3d(length, 0, z)
        lower_sw_point = openstudio.Point3d(0, 0, z)

        # Identity matrix for setting space origins
        m = openstudio.Matrix(4, 4, 0)
        m[0, 0] = 1
        m[1, 1] = 1
        m[2, 2] = 1
        m[3, 3] = 1

        # Define polygons for a U-shape building with perimeter core zoning
        if perimeter_zone_depth > 0:
            perimeter_left_nw_point = left_nw_point + openstudio.Vector3d(perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_left_ne_point = left_ne_point + openstudio.Vector3d(-perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_upper_sw_point = upper_sw_point + openstudio.Vector3d(-perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_upper_se_point = upper_se_point + openstudio.Vector3d(perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_right_nw_point = right_nw_point + openstudio.Vector3d(perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_right_ne_point = right_ne_point + openstudio.Vector3d(-perimeter_zone_depth, -perimeter_zone_depth, 0)
            perimeter_lower_se_point = lower_se_point + openstudio.Vector3d(-perimeter_zone_depth, perimeter_zone_depth, 0)
            perimeter_lower_sw_point = lower_sw_point + openstudio.Vector3d(perimeter_zone_depth, perimeter_zone_depth, 0)

            west_left_perimeter_polygon = openstudio.Point3dVector()
            west_left_perimeter_polygon.append(lower_sw_point)
            west_left_perimeter_polygon.append(left_nw_point)
            west_left_perimeter_polygon.append(perimeter_left_nw_point)
            west_left_perimeter_polygon.append(perimeter_lower_sw_point)
            west_left_perimeter_space = openstudio.model.Space.fromFloorPrint(west_left_perimeter_polygon, floor_to_floor_height, model)
            west_left_perimeter_space = opt(west_left_perimeter_space)
            m[0, 3] = lower_sw_point.x()
            m[1, 3] = lower_sw_point.y()
            m[2, 3] = lower_sw_point.z()
            west_left_perimeter_space.changeTransformation(openstudio.Transformation(m))
            west_left_perimeter_space.setBuildingStory(story)
            west_left_perimeter_space.setName(f"Story {floor + 1} West Left Perimeter Space")

            north_left_perimeter_polygon = openstudio.Point3dVector()
            north_left_perimeter_polygon.append(left_nw_point)
            north_left_perimeter_polygon.append(left_ne_point)
            north_left_perimeter_polygon.append(perimeter_left_ne_point)
            north_left_perimeter_polygon.append(perimeter_left_nw_point)
            north_left_perimeter_space = openstudio.model.Space.fromFloorPrint(north_left_perimeter_polygon, floor_to_floor_height, model)
            north_left_perimeter_space = opt(north_left_perimeter_space)
            m[0, 3] = perimeter_left_nw_point.x()
            m[1, 3] = perimeter_left_nw_point.y()
            m[2, 3] = perimeter_left_nw_point.z()
            north_left_perimeter_space.changeTransformation(openstudio.Transformation(m))
            north_left_perimeter_space.setBuildingStory(story)
            north_left_perimeter_space.setName(f"Story {floor + 1} North Left Perimeter Space")

            east_left_perimeter_polygon = openstudio.Point3dVector()
            east_left_perimeter_polygon.append(left_ne_point)
            east_left_perimeter_polygon.append(upper_sw_point)
            east_left_perimeter_polygon.append(perimeter_upper_sw_point)
            east_left_perimeter_polygon.append(perimeter_left_ne_point)
            east_left_perimeter_space = openstudio.model.Space.fromFloorPrint(east_left_perimeter_polygon, floor_to_floor_height, model)
            east_left_perimeter_space = opt(east_left_perimeter_space)
            m[0, 3] = perimeter_upper_sw_point.x()
            m[1, 3] = perimeter_upper_sw_point.y()
            m[2, 3] = perimeter_upper_sw_point.z()
            east_left_perimeter_space.changeTransformation(openstudio.Transformation(m))
            east_left_perimeter_space.setBuildingStory(story)
            east_left_perimeter_space.setName(f"Story {floor + 1} East Left Perimeter Space")

            north_lower_perimeter_polygon = openstudio.Point3dVector()
            north_lower_perimeter_polygon.append(upper_sw_point)
            north_lower_perimeter_polygon.append(upper_se_point)
            north_lower_perimeter_polygon.append(perimeter_upper_se_point)
            north_lower_perimeter_polygon.append(perimeter_upper_sw_point)
            north_lower_perimeter_space = openstudio.model.Space.fromFloorPrint(north_lower_perimeter_polygon, floor_to_floor_height, model)
            north_lower_perimeter_space = opt(north_lower_perimeter_space)
            m[0, 3] = perimeter_upper_sw_point.x()
            m[1, 3] = perimeter_upper_sw_point.y()
            m[2, 3] = perimeter_upper_sw_point.z()
            north_lower_perimeter_space.changeTransformation(openstudio.Transformation(m))
            north_lower_perimeter_space.setBuildingStory(story)
            north_lower_perimeter_space.setName(f"Story {floor + 1} North Lower Perimeter Space")

            west_right_perimeter_polygon = openstudio.Point3dVector()
            west_right_perimeter_polygon.append(upper_se_point)
            west_right_perimeter_polygon.append(right_nw_point)
            west_right_perimeter_polygon.append(perimeter_right_nw_point)
            west_right_perimeter_polygon.append(perimeter_upper_se_point)
            west_right_perimeter_space = openstudio.model.Space.fromFloorPrint(west_right_perimeter_polygon, floor_to_floor_height, model)
            west_right_perimeter_space = opt(west_right_perimeter_space)
            m[0, 3] = upper_se_point.x()
            m[1, 3] = upper_se_point.y()
            m[2, 3] = upper_se_point.z()
            west_right_perimeter_space.changeTransformation(openstudio.Transformation(m))
            west_right_perimeter_space.setBuildingStory(story)
            west_right_perimeter_space.setName(f"Story {floor + 1} West Right Perimeter Space")

            north_right_perimeter_polygon = openstudio.Point3dVector()
            north_right_perimeter_polygon.append(right_nw_point)
            north_right_perimeter_polygon.append(right_ne_point)
            north_right_perimeter_polygon.append(perimeter_right_ne_point)
            north_right_perimeter_polygon.append(perimeter_right_nw_point)
            north_right_perimeter_space = openstudio.model.Space.fromFloorPrint(north_right_perimeter_polygon, floor_to_floor_height, model)
            north_right_perimeter_space = opt(north_right_perimeter_space)
            m[0, 3] = perimeter_right_nw_point.x()
            m[1, 3] = perimeter_right_nw_point.y()
            m[2, 3] = perimeter_right_nw_point.z()
            north_right_perimeter_space.changeTransformation(openstudio.Transformation(m))
            north_right_perimeter_space.setBuildingStory(story)
            north_right_perimeter_space.setName(f"Story {floor + 1} North Right Perimeter Space")

            east_right_perimeter_polygon = openstudio.Point3dVector()
            east_right_perimeter_polygon.append(right_ne_point)
            east_right_perimeter_polygon.append(lower_se_point)
            east_right_perimeter_polygon.append(perimeter_lower_se_point)
            east_right_perimeter_polygon.append(perimeter_right_ne_point)
            east_right_perimeter_space = openstudio.model.Space.fromFloorPrint(east_right_perimeter_polygon, floor_to_floor_height, model)
            east_right_perimeter_space = opt(east_right_perimeter_space)
            m[0, 3] = perimeter_lower_se_point.x()
            m[1, 3] = perimeter_lower_se_point.y()
            m[2, 3] = perimeter_lower_se_point.z()
            east_right_perimeter_space.changeTransformation(openstudio.Transformation(m))
            east_right_perimeter_space.setBuildingStory(story)
            east_right_perimeter_space.setName(f"Story {floor + 1} East Right Perimeter Space")

            south_lower_perimeter_polygon = openstudio.Point3dVector()
            south_lower_perimeter_polygon.append(lower_se_point)
            south_lower_perimeter_polygon.append(lower_sw_point)
            south_lower_perimeter_polygon.append(perimeter_lower_sw_point)
            south_lower_perimeter_polygon.append(perimeter_lower_se_point)
            south_lower_perimeter_space = openstudio.model.Space.fromFloorPrint(south_lower_perimeter_polygon, floor_to_floor_height, model)
            south_lower_perimeter_space = opt(south_lower_perimeter_space)
            m[0, 3] = lower_sw_point.x()
            m[1, 3] = lower_sw_point.y()
            m[2, 3] = lower_sw_point.z()
            south_lower_perimeter_space.changeTransformation(openstudio.Transformation(m))
            south_lower_perimeter_space.setBuildingStory(story)
            south_lower_perimeter_space.setName(f"Story {floor + 1} South Lower Perimeter Space")

            west_core_polygon = openstudio.Point3dVector()
            west_core_polygon.append(perimeter_lower_sw_point)
            west_core_polygon.append(perimeter_left_nw_point)
            west_core_polygon.append(perimeter_left_ne_point)
            west_core_polygon.append(perimeter_upper_sw_point)
            west_core_space = openstudio.model.Space.fromFloorPrint(west_core_polygon, floor_to_floor_height, model)
            west_core_space = opt(west_core_space)
            m[0, 3] = perimeter_lower_sw_point.x()
            m[1, 3] = perimeter_lower_sw_point.y()
            m[2, 3] = perimeter_lower_sw_point.z()
            west_core_space.changeTransformation(openstudio.Transformation(m))
            west_core_space.setBuildingStory(story)
            west_core_space.setName(f"Story {floor + 1} West Core Space")

            south_core_polygon = openstudio.Point3dVector()
            south_core_polygon.append(perimeter_upper_sw_point)
            south_core_polygon.append(perimeter_upper_se_point)
            south_core_polygon.append(perimeter_lower_se_point)
            south_core_polygon.append(perimeter_lower_sw_point)
            south_core_space = openstudio.model.Space.fromFloorPrint(south_core_polygon, floor_to_floor_height, model)
            south_core_space = opt(south_core_space)
            m[0, 3] = perimeter_lower_sw_point.x()
            m[1, 3] = perimeter_lower_sw_point.y()
            m[2, 3] = perimeter_lower_sw_point.z()
            south_core_space.changeTransformation(openstudio.Transformation(m))
            south_core_space.setBuildingStory(story)
            south_core_space.setName(f"Story {floor + 1} South Core Space")

            east_core_polygon = openstudio.Point3dVector()
            east_core_polygon.append(perimeter_upper_se_point)
            east_core_polygon.append(perimeter_right_nw_point)
            east_core_polygon.append(perimeter_right_ne_point)
            east_core_polygon.append(perimeter_lower_se_point)
            east_core_space = openstudio.model.Space.fromFloorPrint(east_core_polygon, floor_to_floor_height, model)
            east_core_space = opt(east_core_space)
            m[0, 3] = perimeter_upper_se_point.x()
            m[1, 3] = perimeter_upper_se_point.y()
            m[2, 3] = perimeter_upper_se_point.z()
            east_core_space.changeTransformation(openstudio.Transformation(m))
            east_core_space.setBuildingStory(story)
            east_core_space.setName(f"Story {floor + 1} East Core Space")
        else:
            # Minimal zones
            west_polygon = openstudio.Point3dVector()
            west_polygon.append(lower_sw_point)
            west_polygon.append(left_nw_point)
            west_polygon.append(left_ne_point)
            west_polygon.append(upper_sw_point)
            west_space = openstudio.model.Space.fromFloorPrint(west_polygon, floor_to_floor_height, model)
            west_space = opt(west_space)
            m[0, 3] = lower_sw_point.x()
            m[1, 3] = lower_sw_point.y()
            m[2, 3] = lower_sw_point.z()
            west_space.changeTransformation(openstudio.Transformation(m))
            west_space.setBuildingStory(story)
            west_space.setName(f"Story {floor + 1} West Space")

            south_polygon = openstudio.Point3dVector()
            south_polygon.append(lower_sw_point)
            south_polygon.append(upper_sw_point)
            south_polygon.append(upper_se_point)
            south_polygon.append(lower_se_point)
            south_space = openstudio.model.Space.fromFloorPrint(south_polygon, floor_to_floor_height, model)
            south_space = opt(south_space)
            m[0, 3] = lower_sw_point.x()
            m[1, 3] = lower_sw_point.y()
            m[2, 3] = lower_sw_point.z()
            south_space.changeTransformation(openstudio.Transformation(m))
            south_space.setBuildingStory(story)
            south_space.setName(f"Story {floor + 1} South Space")

            east_polygon = openstudio.Point3dVector()
            east_polygon.append(upper_se_point)
            east_polygon.append(right_nw_point)
            east_polygon.append(right_ne_point)
            east_polygon.append(lower_se_point)
            east_space = openstudio.model.Space.fromFloorPrint(east_polygon, floor_to_floor_height, model)
            east_space = opt(east_space)
            m[0, 3] = upper_se_point.x()
            m[1, 3] = upper_se_point.y()
            m[2, 3] = upper_se_point.z()
            east_space.changeTransformation(openstudio.Transformation(m))
            east_space.setBuildingStory(story)
            east_space.setName(f"Story {floor + 1} East Space")
        # Set vertical story position
        story.setNominalZCoordinate(z)
    helpers.match_surfaces(model)

    return model

# @!endgroup Create:Shape
