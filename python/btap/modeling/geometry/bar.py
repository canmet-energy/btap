"""The bar massing engine — verbatim port of OpenstudioStandards::Geometry
create_bar + bar_hash_setup_run (the David Goldwasser bar lineage) plus
their five polygon/space helpers from geometry/create.rb (via the Ruby
btap-modeling gem's geometry/bar.rb). The DOE/DEER building-type-ratio
wrappers (create_bar_from_building_type_ratios etc.) are deliberately NOT
ported — they depend on CreateTypical building-type metadata and
Standard.build; the family-native ratio entry is btap.modeling.bar (see the
package facade).

Port notes (D-79):
- Every hash key that was a Ruby symbol is a str here, spelled exactly as
  the facade passes them ('num_stories_below_grade', 'floor_area',
  'space_type', 'polygon', ...).
- Ruby's bare ``.sort`` on model-object arrays becomes ``sorted_by_name``
  (deterministic; Ruby's sort keyed on handle UUIDs, which is arbitrary
  per-run — name order is the family's determinism idiom).
"""

from __future__ import annotations

import math

import openstudio

from btap._compat import opt, ruby_round, sorted_by_name

_LOG = 'openstudio.standards.Geometry.Create'

# The engine (and the facade's space_types_hash) key dicts by
# SpaceType/BuildingStory objects exactly as the Ruby does — the wheel's SWIG
# bindings need the shared handle-hash patch for that (see _compat).
from btap._compat import ensure_sdk_hashable  # noqa: E402

ensure_sdk_hashable()


def create_bar(model, bar_hash):
    # ---- 1. Inputs, warnings, and story flattening ----
    # make custom story hash when number of stories below grade > 0
    # @todo update this so have option basements are not below 0? (useful for
    #   simplifying existing model and maintaining z position relative to site shading)
    story_hash = {}
    eff_below = bar_hash['num_stories_below_grade']
    eff_above = bar_hash['num_stories_above_grade']
    footprint_origin_point = bar_hash['center_of_footprint']
    typical_story_height = bar_hash['floor_height']

    # warn about site shading
    if len(model.getSite().shadingSurfaceGroups()) > 0:
        openstudio.logFree(openstudio.Warn, _LOG, 'The model has one or more site shading surfaces. New geometry may not be positioned where expected, it will be centered over the center of the original geometry.')

    # flatten story_hash out to individual stories included in building area
    stories_flat = []
    stories_flat_counter = 0
    for i, (k, v) in enumerate(bar_hash['stories'].items()):
        # k is invalid in some cases, old story object that has been removed,
        # should be from low to high including basement
        # skip if source story isn't included in building area
        if v.get('story_included_in_building_area') is None or v.get('story_included_in_building_area') is True:

            # add to counter
            stories_flat_counter += v['story_min_multiplier']

            flat_hash = {}
            flat_hash['story_party_walls'] = v['story_party_walls']
            flat_hash['below_partial_story'] = v['below_partial_story']
            flat_hash['bottom_story_ground_exposed_floor'] = v['bottom_story_ground_exposed_floor']
            flat_hash['top_story_exterior_exposed_roof'] = v['top_story_exterior_exposed_roof']
            if i < eff_below:
                flat_hash['story_type'] = 'b'
                flat_hash['multiplier'] = 1
            elif i == eff_below:
                flat_hash['story_type'] = 'ground'
                flat_hash['multiplier'] = 1
            elif stories_flat_counter == eff_below + math.ceil(eff_above):
                flat_hash['story_type'] = 'top'
                flat_hash['multiplier'] = 1
            else:
                flat_hash['story_type'] = 'mid'
                flat_hash['multiplier'] = v['story_min_multiplier']

            compare_hash = {}
            if stories_flat:
                for s, m in stories_flat[-1].items():
                    if flat_hash.get(s) != m:
                        compare_hash[s] = flat_hash.get(s)
            if (bar_hash['story_multiplier_method'] != 'None' and stories_flat and stories_flat[-1] == flat_hash) or \
               (bar_hash['story_multiplier_method'] != 'None' and len(compare_hash) == 1 and 'multiplier' in compare_hash):
                stories_flat[-1]['multiplier'] += v['story_min_multiplier']
            else:
                stories_flat.append(flat_hash)

    # ---- 2. Build story_hash: origin z, height, and multiplier per story ----
    if bar_hash['num_stories_below_grade'] > 0:
        # add in below grade levels (may want to add below grade multipliers at
        # some point if we start running deep basements)
        for i in range(eff_below):
            story_hash[f'B{i + 1}'] = {'space_origin_z': footprint_origin_point.z() - (typical_story_height * (i + 1)), 'space_height': typical_story_height, 'multiplier': 1}

    # add in above grade levels
    if eff_above > 2:
        story_hash['ground'] = {'space_origin_z': footprint_origin_point.z(), 'space_height': typical_story_height, 'multiplier': 1}

        footprint_counter = 0
        effective_stories_counter = 1
        for flat in stories_flat:
            if flat['story_type'] != 'mid':
                continue

            if footprint_counter == 0:
                string = 'mid'
            else:
                string = f'mid{footprint_counter + 1}'
            story_hash[string] = {'space_origin_z': footprint_origin_point.z() + (typical_story_height * effective_stories_counter) + (typical_story_height * (flat['multiplier'] - 1) / 2.0), 'space_height': typical_story_height, 'multiplier': flat['multiplier']}
            footprint_counter += 1
            effective_stories_counter += flat['multiplier']

        story_hash['top'] = {'space_origin_z': footprint_origin_point.z() + (typical_story_height * (math.ceil(eff_above) - 1)), 'space_height': typical_story_height, 'multiplier': 1}
    elif eff_above > 1:
        story_hash['ground'] = {'space_origin_z': footprint_origin_point.z(), 'space_height': typical_story_height, 'multiplier': 1}
        story_hash['top'] = {'space_origin_z': footprint_origin_point.z() + (typical_story_height * (math.ceil(eff_above) - 1)), 'space_height': typical_story_height, 'multiplier': 1}
    else:  # one story only
        story_hash['ground'] = {'space_origin_z': footprint_origin_point.z(), 'space_height': typical_story_height, 'multiplier': 1}

    # ---- 3. Create footprint polygons per bar division method ----
    # create footprints
    if bar_hash['bar_division_method'] == 'Multiple Space Types - Simple Sliced':
        footprints = []
        for i in range(len(story_hash)):
            # adjust size of bar of top story is not a full story
            if i + 1 == len(story_hash):
                area_multiplier = (1.0 - math.ceil(bar_hash['num_stories_above_grade']) + bar_hash['num_stories_above_grade'])
                edge_multiplier = math.sqrt(area_multiplier)
                length = bar_hash['length'] * edge_multiplier
                width = bar_hash['width'] * edge_multiplier
            else:
                length = bar_hash['length']
                width = bar_hash['width']
            footprints.append(create_sliced_bar_simple_polygons(bar_hash['space_types'], length, width, bar_hash['center_of_footprint']))

    elif bar_hash['bar_division_method'] == 'Multiple Space Types - Individual Stories Sliced':

        # update story_hash for partial_story_above
        for i, (k, v) in enumerate(story_hash.items()):
            # adjust size of bar of top story is not a full story
            if i + 1 == len(story_hash):
                story_hash[k]['partial_story_multiplier'] = (1.0 - math.ceil(bar_hash['num_stories_above_grade']) + bar_hash['num_stories_above_grade'])

        footprints = create_sliced_bar_multi_polygons(bar_hash['space_types'], bar_hash['length'], bar_hash['width'], bar_hash['center_of_footprint'], story_hash)

    else:
        footprints = []
        for i in range(len(story_hash)):
            # adjust size of bar of top story is not a full story
            if i + 1 == len(story_hash):
                area_multiplier = (1.0 - math.ceil(bar_hash['num_stories_above_grade']) + bar_hash['num_stories_above_grade'])
                edge_multiplier = math.sqrt(area_multiplier)
                length = bar_hash['length'] * edge_multiplier
                width = bar_hash['width'] * edge_multiplier
            else:
                length = bar_hash['length']
                width = bar_hash['width']
            # perimeter defaults to 15 ft
            footprints.append(create_core_and_perimeter_polygons(length, width, bar_hash['center_of_footprint']))

        # set primary space type to building default space type
        space_types = sorted(bar_hash['space_types'].items(), key=lambda kv: kv[1]['floor_area'])
        if isinstance(space_types[-1][0], openstudio.model.SpaceType):
            model.getBuilding().setSpaceType(space_types[-1][0])

    # ---- 4. Make spaces and stories from polygons ----
    # make spaces from polygons
    # (bar_hash carries no 'num_stories' key — Ruby read nil here; only used
    # when story_hash is empty, which it never is on this path)
    new_spaces = create_spaces_from_polygons(model, footprints, bar_hash['floor_height'], bar_hash.get('num_stories'), bar_hash['center_of_footprint'], story_hash)

    # ---- 5. Surface cleanup, intersection, and matching ----
    # put all of the spaces in the model into a vector for intersection and surface matching
    spaces = openstudio.model.SpaceVector()
    for space in sorted_by_name(model.getSpaces()):
        spaces.append(space)

    # flag for intersection and matching type
    diagnostic_intersect = True

    # only intersect if make_mid_story_surfaces_adiabatic false
    if diagnostic_intersect:

        for surface in sorted_by_name(model.getPlanarSurfaces()):
            array = []
            vertices = surface.vertices()
            fixed = False
            for vertex in vertices:
                if fixed:
                    continue

                if vertex in array:
                    # create a new set of vertices
                    new_vertices = openstudio.Point3dVector()
                    array_b = []
                    for vertex_b in surface.vertices():
                        if vertex_b in array_b:
                            continue

                        new_vertices.append(vertex_b)
                        array_b.append(vertex_b)
                    surface.setVertices(new_vertices)
                    num_removed = len(vertices) - len(surface.vertices())
                    openstudio.logFree(openstudio.Warn, _LOG, f"{surface.nameString()} has duplicate vertices. Started with {len(vertices)} vertices, removed {num_removed}.")
                    fixed = True
                else:
                    array.append(vertex)

        # remove collinear points in a surface
        for surface in sorted_by_name(model.getPlanarSurfaces()):
            new_vertices = openstudio.removeCollinear(surface.vertices())
            starting_count = len(surface.vertices())
            final_count = len(new_vertices)
            if final_count < starting_count:
                openstudio.logFree(openstudio.Warn, _LOG, f"Removing {starting_count - final_count} collinear vertices from {surface.nameString()}.")
                surface.setVertices(new_vertices)

        # remove duplicate surfaces in a space (should be done after remove duplicate and collinear points)
        for space in sorted_by_name(model.getSpaces()):
            # secondary array to compare against
            surfaces_b = sorted_by_name(space.surfaces())

            for surface_a in sorted_by_name(space.surfaces()):
                # delete from secondary array
                if surface_a in surfaces_b:
                    surfaces_b.remove(surface_a)

                for surface_b in surfaces_b:
                    if surface_a == surface_b:
                        continue  # don't test against same surface

                    if surface_a.equalVertices(surface_b):
                        openstudio.logFree(openstudio.Warn, _LOG, f"{surface_a.nameString()} and {surface_b.nameString()} in {space.nameString()} have duplicate geometry, removing {surface_b.nameString()}.")
                        surface_b.remove()
                    elif surface_a.reverseEqualVertices(surface_b):
                        # @todo add logic to determine which face naormal is reversed and which is correct
                        openstudio.logFree(openstudio.Warn, _LOG, f"{surface_a.nameString()} and {surface_b.nameString()} in {space.nameString()} have reversed geometry, removing {surface_b.nameString()}.")
                        surface_b.remove()

        if bar_hash['make_mid_story_surfaces_adiabatic']:
            # elsif bar_hash['double_loaded_corridor'] # only intersect spaces in each story, not between wtory
            for story in sorted_by_name(model.getBuilding().buildingStories()):
                # intersect and surface match two pair by pair
                spaces_b = sorted_by_name(story.spaces())
                # looping through vector of each space
                for space_a in sorted_by_name(story.spaces()):
                    if space_a in spaces_b:
                        spaces_b.remove(space_a)
                    for space_b in spaces_b:
                        spaces_temp = openstudio.model.SpaceVector()
                        spaces_temp.append(space_a)
                        spaces_temp.append(space_b)

                        # intersect and sort
                        openstudio.model.intersectSurfaces(spaces_temp)
                        openstudio.model.matchSurfaces(spaces_temp)
                openstudio.logFree(openstudio.Info, _LOG, f"Intersecting and matching surfaces in story {story.nameString()}, this will create additional geometry.")
        else:
            # intersect and surface match two pair by pair
            spaces_b = sorted_by_name(model.getSpaces())
            # looping through vector of each space
            for space_a in sorted_by_name(model.getSpaces()):
                if space_a in spaces_b:
                    spaces_b.remove(space_a)
                for space_b in spaces_b:
                    spaces_temp = openstudio.model.SpaceVector()
                    spaces_temp.append(space_a)
                    spaces_temp.append(space_b)
                    # intersect and sort
                    openstudio.model.intersectSurfaces(spaces_temp)
                    openstudio.model.matchSurfaces(spaces_temp)
            openstudio.logFree(openstudio.Info, _LOG, 'Intersecting and matching surfaces in model, this will create additional geometry.')
    else:
        if bar_hash['make_mid_story_surfaces_adiabatic']:
            # elsif bar_hash['double_loaded_corridor'] # only intersect spaces in each story, not between wtory
            for story in sorted_by_name(model.getBuilding().buildingStories()):
                story_spaces = openstudio.model.SpaceVector()
                for space in sorted_by_name(story.spaces()):
                    story_spaces.append(space)

                # intersect and sort
                openstudio.model.intersectSurfaces(story_spaces)
                openstudio.model.matchSurfaces(story_spaces)
                openstudio.logFree(openstudio.Info, _LOG, f"Intersecting and matching surfaces in story {story.nameString()}, this will create additional geometry.")
        else:
            # intersect surfaces
            # (when bottom floor has many space types and one above doesn't will end up with heavily
            # subdivided floor. Maybe use adiabatic and don't intersect floor/ceilings)
            intersect_surfaces = True
            if intersect_surfaces:
                openstudio.model.intersectSurfaces(spaces)
                openstudio.model.matchSurfaces(spaces)
                openstudio.logFree(openstudio.Info, _LOG, 'Intersecting and matching surfaces in model, this will create additional geometry.')

    # ---- 6. Boundary conditions: below-grade ground and mid-story adiabatic walls ----
    # set boundary conditions if not already set when geometry was created
    # @todo update this to use space original z value vs. story name
    if bar_hash['num_stories_below_grade'] > 0:
        for story in sorted_by_name(model.getBuildingStorys()):
            if 'Story B' not in story.nameString():
                continue

            for space in sorted_by_name(story.spaces()):
                if space not in new_spaces:
                    continue

                for surface in sorted_by_name(space.surfaces()):
                    if surface.surfaceType() != 'Wall':
                        continue
                    if surface.outsideBoundaryCondition() != 'Outdoors':
                        continue

                    surface.setOutsideBoundaryCondition('Ground')

    # set wall boundary condtions to adiabatic if using make_mid_story_surfaces_adiabatic
    # prior to windows being made
    if bar_hash['make_mid_story_surfaces_adiabatic']:

        openstudio.logFree(openstudio.Info, _LOG, 'Finding non-exterior walls and setting boundary condition to adiabatic')

        # need to organize by story incase top story is partial story
        # should also be only for a single bar
        story_bounding = {}
        missed_match_count = 0

        # gather new spaces by story
        for space in new_spaces:
            story = space.buildingStory().get()
            if story in story_bounding:
                story_bounding[story]['spaces'].append(space)
            else:
                story_bounding[story] = {'spaces': [space]}

        # get bounding box for each story
        for story, v in story_bounding.items():
            # get bounding_box
            bounding_box = openstudio.BoundingBox()
            for space in v['spaces']:
                for space_surface in space.surfaces():
                    bounding_box.addPoints(space.transformation() * space_surface.vertices())
            min_x = bounding_box.minX().get()
            min_y = bounding_box.minY().get()
            max_x = bounding_box.maxX().get()
            max_y = bounding_box.maxY().get()
            ext_wall_toll = 0.01

            # check surfaces again against min/max and change to adiabatic if not fully on one min or max x or y
            # todo - may need to look at aidiabiatc constructions in downstream measure.
            # Some may be exterior party wall others may be interior walls
            for space in v['spaces']:
                for space_surface in space.surfaces():
                    if space_surface.surfaceType() != 'Wall':
                        continue
                    if space_surface.outsideBoundaryCondition() == 'Surface':
                        continue  # if found a match leave it alone, don't change to adiabiatc

                    surface_bounding_box = openstudio.BoundingBox()
                    surface_bounding_box.addPoints(space.transformation() * space_surface.vertices())
                    surface_on_outside = False
                    # check xmin
                    if abs(surface_bounding_box.minX().get() - min_x) < ext_wall_toll and abs(surface_bounding_box.maxX().get() - min_x) < ext_wall_toll:
                        surface_on_outside = True
                    # check xmax
                    if abs(surface_bounding_box.minX().get() - max_x) < ext_wall_toll and abs(surface_bounding_box.maxX().get() - max_x) < ext_wall_toll:
                        surface_on_outside = True
                    # check ymin
                    if abs(surface_bounding_box.minY().get() - min_y) < ext_wall_toll and abs(surface_bounding_box.maxY().get() - min_y) < ext_wall_toll:
                        surface_on_outside = True
                    # check ymax
                    if abs(surface_bounding_box.minY().get() - max_y) < ext_wall_toll and abs(surface_bounding_box.maxY().get() - max_y) < ext_wall_toll:
                        surface_on_outside = True

                    # change if not exterior
                    if not surface_on_outside:
                        space_surface.setOutsideBoundaryCondition('Adiabatic')
                        missed_match_count += 1

        if missed_match_count > 0:
            openstudio.logFree(openstudio.Info, _LOG, f"{missed_match_count} surfaces that were exterior appear to be interior walls and had boundary condition chagned to adiabiatic.")

    # ---- 7. Party walls and window-to-wall ratios by story and facade ----
    # sort stories (by name for now but need better way)
    sorted_stories = {}
    for space in new_spaces:
        if not space.buildingStory().is_initialized():
            continue

        story = space.buildingStory().get()
        # Ruby bug ported as-is: the guard read `name.to_s` — Ruby's bare
        # `name` resolved to Module#name ("BtapModeling::Bar"), never a story
        # key, so the condition was always true and the assignment always ran
        # (same-key reassignment is idempotent).
        sorted_stories[story.nameString()] = story

    # flag space types that have wwr overrides
    space_type_wwr_overrides = {}

    # loop through building stories, spaces, and surfaces
    for i, (key, story) in enumerate(sorted(sorted_stories.items(), key=lambda kv: kv[0])):
        # (Ruby block-locals: fresh per iteration, nil unless assigned)
        adiabatic_floor = False
        adiabatic_ceiling = False
        # flag for adiabatic floor if building doesn't have ground exposed floor
        if stories_flat[i]['bottom_story_ground_exposed_floor'] is False:
            adiabatic_floor = True
        # flag for adiabatic roof if building doesn't have exterior exposed roof
        if stories_flat[i]['top_story_exterior_exposed_roof'] is False:
            adiabatic_ceiling = True

        # make all mid story floor and ceilings adiabatic if requested
        if bar_hash['make_mid_story_surfaces_adiabatic']:
            if i > 0:
                adiabatic_floor = True
            if i < len(sorted_stories) - 1:
                adiabatic_ceiling = True

        # flag orientations for this story to recieve party walls
        party_wall_facades = stories_flat[i]['story_party_walls']

        for space in story.spaces():
            if space not in new_spaces:
                continue

            for surface in space.surfaces():
                # set floor to adiabatic if requited
                if (adiabatic_floor and surface.surfaceType() == 'Floor') or (adiabatic_ceiling and surface.surfaceType() == 'RoofCeiling'):
                    surface.setOutsideBoundaryCondition('Adiabatic')

                # skip of not exterior wall
                if surface.surfaceType() != 'Wall':
                    continue
                if surface.outsideBoundaryCondition() != 'Outdoors':
                    continue

                # get the absolute azimuth for the surface so we can categorize it
                absolute_azimuth = opt(openstudio.convert(surface.azimuth(), 'rad', 'deg')) + surface.space().get().directionofRelativeNorth() + model.getBuilding().northAxis()
                absolute_azimuth = absolute_azimuth % 360.0  # should result in value between 0 and 360
                absolute_azimuth = ruby_round(absolute_azimuth, 5)  # this was creating issues at 45 deg angles with opposing facades

                # target wwr values that may be changed for specific space types
                wwr_n = bar_hash['building_wwr_n']
                wwr_e = bar_hash['building_wwr_e']
                wwr_s = bar_hash['building_wwr_s']
                wwr_w = bar_hash['building_wwr_w']

                # look for space type specific wwr values
                if surface.space().is_initialized() and surface.space().get().spaceType().is_initialized():
                    space_type = surface.space().get().spaceType().get()

                    # see if space type has wwr value
                    for k, v in bar_hash['space_types'].items():
                        if 'space_type' in v and space_type == v['space_type'] and 'wwr' in v:
                            # if matching space type specifies a wwr then override the
                            # orientation specific recommendations for this surface.
                            wwr_n = v['wwr']
                            wwr_e = v['wwr']
                            wwr_s = v['wwr']
                            wwr_w = v['wwr']
                            space_type_wwr_overrides[space_type] = v['wwr']

                # add fenestration (wwr for now, maybe overhang and overhead doors later)
                if absolute_azimuth >= 315.0 or absolute_azimuth < 45.0:
                    if 'north' in party_wall_facades:
                        surface.setOutsideBoundaryCondition('Adiabatic')
                    else:
                        surface.setWindowToWallRatio(wwr_n)
                elif absolute_azimuth >= 45.0 and absolute_azimuth < 135.0:
                    if 'east' in party_wall_facades:
                        surface.setOutsideBoundaryCondition('Adiabatic')
                    else:
                        surface.setWindowToWallRatio(wwr_e)
                elif absolute_azimuth >= 135.0 and absolute_azimuth < 225.0:
                    if 'south' in party_wall_facades:
                        surface.setOutsideBoundaryCondition('Adiabatic')
                    else:
                        surface.setWindowToWallRatio(wwr_s)
                elif absolute_azimuth >= 225.0 and absolute_azimuth < 315.0:
                    if 'west' in party_wall_facades:
                        surface.setOutsideBoundaryCondition('Adiabatic')
                    else:
                        surface.setWindowToWallRatio(wwr_w)
                else:
                    openstudio.logFree(openstudio.Error, _LOG, f"Unexpected value of facade: {absolute_azimuth}.")
                    return False

    # ---- 8. Report wwr overrides and final floor area ----
    # report space types with custom wwr values
    for space_type, wwr in space_type_wwr_overrides.items():
        openstudio.logFree(openstudio.Info, _LOG, f"For {space_type.nameString()} the default building wwr was replaced with a space type specfic value of {wwr}")

    new_floor_area_si = 0.0
    for space in new_spaces:
        new_floor_area_si += space.floorArea() * space.multiplier()
    new_floor_area_ip = opt(openstudio.convert(new_floor_area_si, 'm^2', 'ft^2'))

    final_floor_area_ip = opt(openstudio.convert(model.getBuilding().floorArea(), 'm^2', 'ft^2'))
    if new_floor_area_ip == final_floor_area_ip:
        openstudio.logFree(openstudio.Info, _LOG, f"Created bar envelope with floor area of {openstudio.toNeatString(new_floor_area_ip, 0, True)} ft^2.")
    else:
        openstudio.logFree(openstudio.Info, _LOG, f"Created bar envelope with floor area of {openstudio.toNeatString(new_floor_area_ip, 0, True)} ft^2. Total building area is {openstudio.toNeatString(final_floor_area_ip, 0, True)} ft^2.")

    return new_spaces


def bar_hash_setup_run(model, args, length, width, floor_height, center_of_footprint, space_types_hash, num_stories):
    """Give info messages bar hash for create_bar method.

    :param model: OpenStudio model object
    :param args: user arguments (str-keyed dict)
    :param length: length of building in meters
    :param width: width of building in meters
    :param floor_height: floor height in meters
    :param center_of_footprint: openstudio.Point3d center of footprint
    :param space_types_hash: {SpaceType: {'floor_area': m2}} space type hash
    :param num_stories: number of stories
    :return: truthy if successful, False if not
    """
    # create envelope
    # populate bar_hash and create envelope with data from envelope_data_hash and user arguments
    bar_hash = {}
    bar_hash['length'] = length
    bar_hash['width'] = width
    bar_hash['num_stories_below_grade'] = args['num_stories_below_grade']
    bar_hash['num_stories_above_grade'] = args['num_stories_above_grade']
    bar_hash['floor_height'] = floor_height
    bar_hash['center_of_footprint'] = center_of_footprint
    bar_hash['bar_division_method'] = args['bar_division_method']
    bar_hash['story_multiplier_method'] = args['story_multiplier_method']
    bar_hash['make_mid_story_surfaces_adiabatic'] = args['make_mid_story_surfaces_adiabatic']
    bar_hash['space_types'] = space_types_hash
    bar_hash['building_wwr_n'] = args['wwr']
    bar_hash['building_wwr_s'] = args['wwr']
    bar_hash['building_wwr_e'] = args['wwr']
    bar_hash['building_wwr_w'] = args['wwr']

    # round up non integer stoires to next integer
    num_stories_round_up = math.ceil(num_stories)
    openstudio.logFree(openstudio.Info, _LOG, f"Making bar with length of {openstudio.toNeatString(opt(openstudio.convert(length, 'm', 'ft')), 0, True)} ft and width of {openstudio.toNeatString(opt(openstudio.convert(width, 'm', 'ft')), 0, True)} ft")

    # party_walls_array to be used by orientation specific or fractional party wall values
    party_walls_array = []  # this is an array of arrays, where each entry is effective building story with array of directions

    if args['party_wall_stories_north'] + args['party_wall_stories_south'] + args['party_wall_stories_east'] + args['party_wall_stories_west'] > 0:

        # loop through effective number of stories add orientation specific party walls per user arguments
        for i in range(num_stories_round_up):
            test_value = i + 1 - bar_hash['num_stories_below_grade']

            array = []
            if args['party_wall_stories_north'] >= test_value:
                array.append('north')
            if args['party_wall_stories_south'] >= test_value:
                array.append('south')
            if args['party_wall_stories_east'] >= test_value:
                array.append('east')
            if args['party_wall_stories_west'] >= test_value:
                array.append('west')

            # populate party_wall_array for this story
            party_walls_array.append(array)

    # calculate party walls if using party_wall_fraction method
    if args['party_wall_fraction'] > 0 and party_walls_array:
        openstudio.logFree(openstudio.Warn, _LOG, 'Both orientation and fractional party wall values arguments were populated, will ignore fractional party wall input')
    elif args['party_wall_fraction'] > 0:
        # orientation of long and short side of building will vary based on building rotation

        # full story ext wall area
        typical_length_facade_area = length * floor_height
        typical_width_facade_area = width * floor_height

        # top story ext wall area, may be partial story
        partial_story_multiplier = (1.0 - math.ceil(args['num_stories_above_grade']) + args['num_stories_above_grade'])
        area_multiplier = partial_story_multiplier
        edge_multiplier = math.sqrt(area_multiplier)
        top_story_length = length * edge_multiplier
        top_story_width = width * edge_multiplier
        top_story_length_facade_area = top_story_length * floor_height
        top_story_width_facade_area = top_story_width * floor_height

        total_exterior_wall_area = (2 * (length + width) * (math.ceil(args['num_stories_above_grade']) - 1.0) * floor_height) + (2 * (top_story_length + top_story_width) * floor_height)
        target_party_wall_area = total_exterior_wall_area * args['party_wall_fraction']

        width_counter = 0
        width_area = 0.0
        facade_area = typical_width_facade_area
        while not ((width_area + facade_area >= target_party_wall_area) or (width_counter == math.ceil(args['num_stories_above_grade']) * 2)):
            # update facade area for top story
            if width_counter == (math.ceil(args['num_stories_above_grade']) - 1) or width_counter == (math.ceil(args['num_stories_above_grade']) * 2) - 1:
                facade_area = top_story_width_facade_area
            else:
                facade_area = typical_width_facade_area

            width_counter += 1
            width_area += facade_area

        width_area_remainder = target_party_wall_area - width_area

        length_counter = 0
        length_area = 0.0
        facade_area = typical_length_facade_area
        while not ((length_area + facade_area >= target_party_wall_area) or (length_counter == math.ceil(args['num_stories_above_grade']) * 2)):
            # update facade area for top story
            if length_counter == (math.ceil(args['num_stories_above_grade']) - 1) or length_counter == (math.ceil(args['num_stories_above_grade']) * 2) - 1:
                facade_area = top_story_length_facade_area
            else:
                facade_area = typical_length_facade_area

            length_counter += 1
            length_area += facade_area
        length_area_remainder = target_party_wall_area - length_area  # noqa: F841 — Ruby computes and never reads it

        # get rotation and best fit to adjust orientation for fraction party wall
        rotation = args['building_rotation'] % 360.0  # should result in value between 0 and 360
        card_dir_array = [0.0, 90.0, 180.0, 270.0, 360.0]
        # reverse array to properly handle 45, 135, 225, and 315
        best_fit = min(reversed(card_dir_array), key=lambda x: abs(float(x) - rotation))

        if best_fit not in [90.0, 270.0]:
            width_card_dir = ['east', 'west']
            length_card_dir = ['north', 'south']
        else:  # if rotation is closest to 90 or 270 then reverse which orientation is used for length and width
            width_card_dir = ['north', 'south']
            length_card_dir = ['east', 'west']

        # if dont' find enough on short sides
        if width_area_remainder <= typical_length_facade_area:

            for i in range(num_stories_round_up):
                if i + 1 <= args['num_stories_below_grade']:
                    party_walls_array.append([])
                    continue
                if i + 1 - args['num_stories_below_grade'] <= width_counter:
                    if i + 1 - args['num_stories_below_grade'] <= width_counter - args['num_stories_above_grade']:
                        party_walls_array.append(width_card_dir)
                    else:
                        party_walls_array.append([width_card_dir[0]])
                else:
                    party_walls_array.append([])

        else:
            # use long sides instead
            for i in range(num_stories_round_up):
                if i + 1 <= args['num_stories_below_grade']:
                    party_walls_array.append([])
                    continue
                if i + 1 - args['num_stories_below_grade'] <= length_counter:
                    if i + 1 - args['num_stories_below_grade'] <= length_counter - args['num_stories_above_grade']:
                        party_walls_array.append(length_card_dir)
                    else:
                        party_walls_array.append([length_card_dir[0]])
                else:
                    party_walls_array.append([])

        # @todo currently won't go past making two opposing sets of walls party walls.
        # Info and registerValue are after create_bar in measure.rb

    # populate bar hash with story information
    bar_hash['stories'] = {}
    for i in range(num_stories_round_up):
        if not party_walls_array:
            party_walls = []
        else:
            party_walls = party_walls_array[i]

        # add below_partial_story
        if math.ceil(num_stories) > num_stories and i == num_stories_round_up - 2:
            below_partial_story = True
        else:
            below_partial_story = False

        # bottom_story_ground_exposed_floor and top_story_exterior_exposed_roof already setup as bool
        bar_hash['stories'][f'key {i}'] = {'story_party_walls': party_walls, 'story_min_multiplier': 1, 'story_included_in_building_area': True, 'below_partial_story': below_partial_story, 'bottom_story_ground_exposed_floor': args['bottom_story_ground_exposed_floor'], 'top_story_exterior_exposed_roof': args['top_story_exterior_exposed_roof']}

    # create bar
    new_spaces = create_bar(model, bar_hash)

    # check expect roof and wall area
    target_footprint = bar_hash['length'] * bar_hash['width']
    ground_floor_area = 0.0
    roof_area = 0.0
    for space in new_spaces:
        for surface in space.surfaces():
            if surface.surfaceType() == 'Floor' and surface.outsideBoundaryCondition() == 'Ground':
                ground_floor_area += surface.netArea()
            elif surface.surfaceType() == 'RoofCeiling' and surface.outsideBoundaryCondition() == 'Outdoors':
                roof_area += surface.netArea()

    # @todo extend to address when top and or bottom story are not exposed via argument
    if ground_floor_area > target_footprint + 0.001 or roof_area > target_footprint + 0.001:
        # openstudio.logFree(openstudio.Error, _LOG, "Ground exposed floor or Roof area is larger
        #   than footprint, likely inter-floor surface matching and intersection error.")
        # return False

        # not providing adiabatic work around when top story is partial story.
        if int(args['num_stories_above_grade']) != math.ceil(args['num_stories_above_grade']):
            openstudio.logFree(openstudio.Error, _LOG, 'Ground exposed floor or Roof area is larger than footprint, likely inter-floor surface matching and intersection error.')
            return False
        else:
            openstudio.logFree(openstudio.Info, _LOG, 'Ground exposed floor or Roof area is larger than footprint, likely inter-floor surface matching and intersection error, altering impacted surfaces boundary condition to be adiabatic.')
            match_error = True
    else:
        match_error = False

    # @todo should be able to remove this fix after OpenStudio intersection issue is fixed.
    # At that time turn the above message into an error with return False after it
    if not match_error:
        return True

    # identify z value of top and bottom story
    bottom_story = None
    top_story = None
    for space in new_spaces:
        story = space.buildingStory().get()
        nom_z = story.nominalZCoordinate().get()
        if bottom_story is None:
            bottom_story = nom_z
        elif bottom_story > nom_z:
            bottom_story = nom_z
        if top_story is None:
            top_story = nom_z
        elif top_story < nom_z:
            top_story = nom_z

    # change boundary condition and intersection as needed.
    for space in new_spaces:
        if space.buildingStory().get().nominalZCoordinate().get() > bottom_story:
            # change floors
            for surface in space.surfaces():
                if not (surface.surfaceType() == 'Floor' and surface.outsideBoundaryCondition() == 'Ground'):
                    continue

                surface.setOutsideBoundaryCondition('Adiabatic')
        if space.buildingStory().get().nominalZCoordinate().get() < top_story:
            # change ceilings
            for surface in space.surfaces():
                if not (surface.surfaceType() == 'RoofCeiling' and surface.outsideBoundaryCondition() == 'Outdoors'):
                    continue

                surface.setOutsideBoundaryCondition('Adiabatic')
    # Ruby's implicit return of the trailing `.each` — the spaces array (truthy)
    return new_spaces


def create_core_and_perimeter_polygons(length, width, footprint_origin_point=None, perimeter_zone_depth=None):
    """Create core and perimeter polygons for a rectangular single-story footprint.

    :param length: length of building in meters
    :param width: width of building in meters
    :param footprint_origin_point: optional openstudio.Point3d for the new origin
    :param perimeter_zone_depth: optional perimeter zone depth in meters (15 ft)
    :return: dict of point vectors that define the space geometry for each direction
    """
    if footprint_origin_point is None:
        footprint_origin_point = openstudio.Point3d(0.0, 0.0, 0.0)
    if perimeter_zone_depth is None:
        perimeter_zone_depth = opt(openstudio.convert(15.0, 'ft', 'm'))
    # key is name, value is a hash, one item of which is polygon. Another could be space type.
    hash_of_point_vectors = {}

    # determine if core and perimeter zoning can be used
    if not (length > perimeter_zone_depth * 2.5 and width > perimeter_zone_depth * 2.5):
        # if any size is to small then just model floor as single zone, issue warning
        perimeter_zone_depth = 0.0
        openstudio.logFree(openstudio.Warn, _LOG, 'Due to the size of the building modeling each floor as a single zone.')

    x_delta = footprint_origin_point.x() - (length / 2.0)
    y_delta = footprint_origin_point.y() - (width / 2.0)
    z = 0
    nw_point = openstudio.Point3d(x_delta, y_delta + width, z)
    ne_point = openstudio.Point3d(x_delta + length, y_delta + width, z)
    se_point = openstudio.Point3d(x_delta + length, y_delta, z)
    sw_point = openstudio.Point3d(x_delta, y_delta, z)

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
        hash_of_point_vectors['West Perimeter Space'] = {}
        # other methods being used by makeSpacesFromPolygons may have space types
        # associated with each polygon but this doesn't.
        hash_of_point_vectors['West Perimeter Space']['space_type'] = None
        hash_of_point_vectors['West Perimeter Space']['polygon'] = west_polygon

        north_polygon = openstudio.Point3dVector()
        north_polygon.append(nw_point)
        north_polygon.append(ne_point)
        north_polygon.append(perimeter_ne_point)
        north_polygon.append(perimeter_nw_point)
        hash_of_point_vectors['North Perimeter Space'] = {}
        hash_of_point_vectors['North Perimeter Space']['space_type'] = None
        hash_of_point_vectors['North Perimeter Space']['polygon'] = north_polygon

        east_polygon = openstudio.Point3dVector()
        east_polygon.append(ne_point)
        east_polygon.append(se_point)
        east_polygon.append(perimeter_se_point)
        east_polygon.append(perimeter_ne_point)
        hash_of_point_vectors['East Perimeter Space'] = {}
        hash_of_point_vectors['East Perimeter Space']['space_type'] = None
        hash_of_point_vectors['East Perimeter Space']['polygon'] = east_polygon

        south_polygon = openstudio.Point3dVector()
        south_polygon.append(se_point)
        south_polygon.append(sw_point)
        south_polygon.append(perimeter_sw_point)
        south_polygon.append(perimeter_se_point)
        hash_of_point_vectors['South Perimeter Space'] = {}
        hash_of_point_vectors['South Perimeter Space']['space_type'] = None
        hash_of_point_vectors['South Perimeter Space']['polygon'] = south_polygon

        core_polygon = openstudio.Point3dVector()
        core_polygon.append(perimeter_sw_point)
        core_polygon.append(perimeter_nw_point)
        core_polygon.append(perimeter_ne_point)
        core_polygon.append(perimeter_se_point)
        hash_of_point_vectors['Core Space'] = {}
        hash_of_point_vectors['Core Space']['space_type'] = None
        hash_of_point_vectors['Core Space']['polygon'] = core_polygon

        # Minimal zones
    else:
        whole_story_polygon = openstudio.Point3dVector()
        whole_story_polygon.append(sw_point)
        whole_story_polygon.append(nw_point)
        whole_story_polygon.append(ne_point)
        whole_story_polygon.append(se_point)
        hash_of_point_vectors['Whole Story Space'] = {}
        hash_of_point_vectors['Whole Story Space']['space_type'] = None
        hash_of_point_vectors['Whole Story Space']['polygon'] = whole_story_polygon

    return hash_of_point_vectors


def create_sliced_bar_multi_polygons(space_types, length, width, footprint_origin_point, story_hash):
    """Sliced bar multi creates an array of multiple sliced bar simple hashes.

    :param space_types: {SpaceType: {'floor_area': m2, ...}} (MUTATED — running counts)
    :param length: length of building in meters
    :param width: width of building in meters
    :param footprint_origin_point: openstudio.Point3d for the new origin
    :param story_hash: building story information including space origin z value and space height
    :return: list (per story) of dicts of point vectors defining the space geometry
    """
    # total building floor area to calculate ratios from space type floor areas
    total_floor_area = 0.0
    target_per_space_type = {}
    for space_type, space_type_hash in space_types.items():
        total_floor_area += space_type_hash['floor_area']
        target_per_space_type[space_type] = space_type_hash['floor_area']

    # sort array by floor area, this hash will be altered to reduce floor area
    # for each space type to 0
    space_types_running_count = sorted(space_types.items(), key=lambda kv: kv[1]['floor_area'])

    # array entry for each story
    footprints = []

    # variables for sliver check
    # re-evaluate what the default should be
    valid_bar_width_min_m = opt(openstudio.convert(3.0, 'ft', 'm'))
    # building width
    bar_length = width
    valid_bar_area_min_m2 = valid_bar_width_min_m * bar_length

    # loop through stories to populate footprints
    for i, (k, v) in enumerate(story_hash.items()):
        # update the length and width for partial floors
        if i + 1 == len(story_hash):
            area_multiplier = v['partial_story_multiplier']
            edge_multiplier = math.sqrt(area_multiplier)
            length *= edge_multiplier
            width *= edge_multiplier

        # this will be populated for each building story
        target_footprint_area = v['multiplier'] * length * width
        current_footprint_area = 0.0
        space_types_local_count = {}

        for space_type, space_type_hash in space_types_running_count:
            # next if floor area is full or space type is empty

            tol_value = 0.0001
            if current_footprint_area + tol_value >= target_footprint_area:
                continue
            if space_type_hash['floor_area'] <= tol_value:
                continue

            # special test for when total floor area is smaller than valid_bar_area_min_m2,
            # just make bar smaller that valid min and warn user
            if target_per_space_type[space_type] < valid_bar_area_min_m2:
                sliver_override = True
                openstudio.logFree(openstudio.Warn, _LOG, f"Floor area of {space_type.nameString()} results in a bar with smaller than target minimum width.")
            else:
                sliver_override = False

            # add entry for space type if it doesn't have one yet
            if space_type not in space_types_local_count:
                if 'children' in space_type_hash:
                    space_type = space_type_hash['children']['default']['space_type']  # will re-using space type create issue
                    space_types_local_count[space_type] = {'floor_area': 0.0}
                    space_types_local_count[space_type]['children'] = space_type_hash['children']
                else:
                    space_types_local_count[space_type] = {'floor_area': 0.0}

            # if there is enough of this space type to fill rest of floor area
            remaining_in_footprint = target_footprint_area - current_footprint_area
            raw_footprint_area_used = min(space_type_hash['floor_area'], remaining_in_footprint)

            # add to local hash
            space_types_local_count[space_type]['floor_area'] = raw_footprint_area_used / float(v['multiplier'])

            # adjust balance ot running and local counts
            current_footprint_area += raw_footprint_area_used
            space_type_hash['floor_area'] -= raw_footprint_area_used

            # test if think sliver left on current floor.
            # fix by moving smallest space type to next floor and and the same amount
            # more of the sliver space type to this story
            test_a = raw_footprint_area_used < valid_bar_area_min_m2 and sliver_override is False

            # test if what would be left of the current space type would result in a sliver
            # on the next story. fix by removing some of this space type so their is enough
            # left for the next story, and replace the removed amount with the largest
            # space type in the model
            test_b = space_type_hash['floor_area'] < valid_bar_area_min_m2 and space_type_hash['floor_area'] > tol_value

            # identify very small slices and re-arrange spaces to different stories to avoid this
            # only apply test_a when there is more than one space type on this story; if there
            # is only one, shifting it out would leave space_types_local_count empty and crash
            # create_sliced_bar_simple_polygons
            if test_a and len(space_types_local_count) > 1:

                # get first/smallest space type to move to another story
                first_space_key = next(iter(space_types_local_count))
                first_space = (first_space_key, space_types_local_count[first_space_key])

                # adjustments running counter for space type being removed from this story
                for k2, v2 in space_types_running_count:
                    if k2 != first_space[0]:
                        continue

                    v2['floor_area'] += first_space[1]['floor_area'] * v['multiplier']

                # adjust running count for current space type
                space_type_hash['floor_area'] -= first_space[1]['floor_area'] * v['multiplier']

                # add to local count for current space type
                space_types_local_count[space_type]['floor_area'] += first_space[1]['floor_area']

                # remove from local count for removed space type
                space_types_local_count.pop(first_space_key)

            elif test_b:

                # swap size
                swap_size = valid_bar_area_min_m2 * 5.0  # currently equal to default perimeter zone depth of 15'
                # this prevents too much area from being swapped resulting in a
                # negative number for floor area
                if swap_size > space_types_local_count[space_type]['floor_area'] * float(v['multiplier']):
                    swap_size = space_types_local_count[space_type]['floor_area'] * float(v['multiplier'])

                # adjust running count for current space type
                space_type_hash['floor_area'] += swap_size

                # remove from local count for current space type
                space_types_local_count[space_type]['floor_area'] -= swap_size / float(v['multiplier'])

                # adjust footprint used
                current_footprint_area -= swap_size

                # the next larger space type will be brought down to fill out the
                # footprint without any additional code

        # creating footprint for story
        footprints.append(create_sliced_bar_simple_polygons(space_types_local_count, length, width, footprint_origin_point))

    return footprints


def create_sliced_bar_simple_polygons(space_types, length, width, footprint_origin_point=None, perimeter_zone_depth=None):
    """Sliced bar simple creates a single sliced bar for space types passed in.
    Look at length and width to adjust slicing direction.

    :param space_types: {SpaceType: {'floor_area': m2, ...}}
    :param length: length of building in meters
    :param width: width of building in meters
    :param footprint_origin_point: optional openstudio.Point3d for the new origin
    :param perimeter_zone_depth: optional perimeter zone depth in meters (15 ft)
    :return: dict of point vectors that define the space geometry for each direction
    """
    if footprint_origin_point is None:
        footprint_origin_point = openstudio.Point3d(0.0, 0.0, 0.0)
    if perimeter_zone_depth is None:
        perimeter_zone_depth = opt(openstudio.convert(15.0, 'ft', 'm'))

    # ---- 1. Setup: slice direction, perimeter depth, and bar corner points ----
    # key is name, value is a hash, one item of which is polygon. Another could be space type
    hash_of_point_vectors = {}

    reverse_slice = False
    if length < width:
        reverse_slice = True
        # openstudio.logFree(openstudio.Info, _LOG, "Reverse typical slice direction
        #   for bar because of aspect ratio less than 1.0.")

    # determine if core and perimeter zoning can be used
    if not (min(length, width) > perimeter_zone_depth * 2.5 and min(length, width) > perimeter_zone_depth * 2.5):
        perimeter_zone_depth = 0  # if any size is to small then just model floor as single zone, issue warning
        openstudio.logFree(openstudio.Warn, _LOG, 'Not modeling core and perimeter zones for some portion of the model.')

    x_delta = footprint_origin_point.x() - (length / 2.0)
    y_delta = footprint_origin_point.y() - (width / 2.0)
    z = 0.0
    # this represents the entire bar, not individual space type slices
    nw_point = openstudio.Point3d(x_delta, y_delta + width, z)
    sw_point = openstudio.Point3d(x_delta, y_delta, z)
    # used when length is less than width
    se_point = openstudio.Point3d(x_delta + length, y_delta, z)

    # ---- 2. Space type areas, sort order, and bar-end sizing rules ----
    # total building floor area to calculate ratios from space type floor areas
    total_floor_area = 0.0
    for space_type, space_type_hash in space_types.items():
        total_floor_area += space_type_hash['floor_area']

    # sort array by floor area but shift largest object to front
    space_types = sorted(space_types.items(), key=lambda kv: kv[1]['floor_area'])
    # guard against empty space_types (e.g. when all space types were slivers removed by caller)
    if not space_types:
        return hash_of_point_vectors
    space_types.insert(0, space_types.pop())

    # min and max bar end values
    min_bar_end_multiplier = 0.75
    max_bar_end_multiplier = 1.5

    # ---- 3. Per space type: slice widths and double-loaded corridor data ----
    # sorted items are (key, value) pairs, first is key, second is hash value
    re_apply_largest_space_type_at_end = False
    # used when looping through section_hash_for_space_type if first space type
    # needs to also be at far end of bar
    max_reduction = None
    for space_type, space_type_hash in space_types:
        # setup end perimeter zones if needed
        start_perimeter_width_deduction = 0.0
        end_perimeter_width_deduction = 0.0
        if space_type == space_types[0][0]:
            if (max(length, width) * space_type_hash['floor_area'] / total_floor_area) > (max_bar_end_multiplier * perimeter_zone_depth):
                start_perimeter_width_deduction = perimeter_zone_depth
            # see if last space type is too small for perimeter. If it is then save some of this space type
            if (max(length, width) * space_types[-1][1]['floor_area'] / total_floor_area) < (perimeter_zone_depth * min_bar_end_multiplier):
                re_apply_largest_space_type_at_end = True
        if space_type == space_types[-1][0]:
            if max(length, width) * space_type_hash['floor_area'] / total_floor_area > max_bar_end_multiplier * perimeter_zone_depth:
                end_perimeter_width_deduction = perimeter_zone_depth
        non_end_adjusted_width = (max(length, width) * space_type_hash['floor_area'] / total_floor_area) - start_perimeter_width_deduction - end_perimeter_width_deduction

        # adjustment of end space type is too small and is replaced with largest space type
        if space_type == space_types[0][0] and re_apply_largest_space_type_at_end:
            max_reduction = min(perimeter_zone_depth, non_end_adjusted_width)
            non_end_adjusted_width -= max_reduction
        if space_type == space_types[-1][0] and re_apply_largest_space_type_at_end:
            end_perimeter_width_deduction = space_types[0][0]
            end_b_flag = True
        else:
            end_b_flag = False

        # populate data for core and perimeter of slice
        section_hash_for_space_type = {}
        section_hash_for_space_type['end_a'] = start_perimeter_width_deduction
        section_hash_for_space_type[''] = non_end_adjusted_width
        section_hash_for_space_type['end_b'] = end_perimeter_width_deduction

        # determine if this space+type is double loaded corridor, and if so what the
        # perimeter zone depth should be based on building width
        # look at reverse_slice to see if length or width should be used to determine perimeter depth
        if 'children' in space_type_hash:
            core_ratio = space_type_hash['children']['circ']['orig_ratio']
            perim_ratio = space_type_hash['children']['default']['orig_ratio']
            core_ratio_adj = core_ratio / (core_ratio + perim_ratio)
            perim_ratio_adj = perim_ratio / (core_ratio + perim_ratio)  # noqa: F841 — Ruby computes and never reads it
            core_space_type = space_type_hash['children']['circ']['space_type']
            perim_space_type = space_type_hash['children']['default']['space_type']
            if reverse_slice:
                custom_cor_val = length * core_ratio_adj
                custom_perim_val = (length - custom_cor_val) / 2.0
            else:
                custom_cor_val = width * core_ratio_adj
                custom_perim_val = (width - custom_cor_val) / 2.0
            # use perimeter zone depth if the custom perimeter value is within 1 milimeter
            if abs(custom_perim_val - perimeter_zone_depth) < 0.001:
                actual_perim = perimeter_zone_depth
            else:
                actual_perim = custom_perim_val

            double_loaded_corridor = True
        else:
            actual_perim = perimeter_zone_depth
            double_loaded_corridor = False

        # may overwrite
        first_space_type_hash = space_types[0][1]
        if end_b_flag and 'children' in first_space_type_hash:
            end_b_core_ratio = first_space_type_hash['children']['circ']['orig_ratio']
            end_b_perim_ratio = first_space_type_hash['children']['default']['orig_ratio']
            end_b_core_ratio_adj = end_b_core_ratio / (end_b_core_ratio + end_b_perim_ratio)
            end_b_perim_ratio_adj = end_b_perim_ratio / (end_b_core_ratio + end_b_perim_ratio)
            end_b_core_space_type = first_space_type_hash['children']['circ']['space_type']
            end_b_perim_space_type = first_space_type_hash['children']['default']['space_type']
            if reverse_slice:
                end_b_custom_cor_val = length * end_b_core_ratio_adj
                end_b_custom_perim_val = (length - end_b_custom_cor_val) / 2.0
            else:
                end_b_custom_cor_val = width * end_b_core_ratio_adj
                end_b_custom_perim_val = (width - end_b_custom_cor_val) / 2.0
            end_b_actual_perim = end_b_custom_perim_val
            end_b_double_loaded_corridor = True
        else:
            end_b_actual_perim = perimeter_zone_depth
            end_b_double_loaded_corridor = False

        # ---- 4. Generate polygons for each section (perimeter/core, both slice directions) ----
        # loop through sections for space type (main and possibly one or two end perimeter sections)
        for k, slice_ in section_hash_for_space_type.items():
            # need to use different space type for end_b
            if end_b_flag and k == 'end_b' and 'children' in space_types[0][1]:
                slice_ = space_types[0][0]
                actual_perim = end_b_actual_perim
                double_loaded_corridor = end_b_double_loaded_corridor
                core_ratio = end_b_core_ratio  # noqa: F841
                perim_ratio = end_b_perim_ratio  # noqa: F841
                core_ratio_adj = end_b_core_ratio_adj  # noqa: F841
                perim_ratio_adj = end_b_perim_ratio_adj  # noqa: F841
                core_space_type = end_b_core_space_type
                perim_space_type = end_b_perim_space_type

            if isinstance(slice_, (openstudio.model.SpaceType, openstudio.model.Building)):
                space_type = slice_
                max_reduction = min(perimeter_zone_depth, max_reduction)
                slice_ = max_reduction
            if slice_ == 0:
                continue

            if reverse_slice:
                # create_bar at 90 degrees if aspect ration is less than 1.0
                # typical order (sw,nw,ne,se)
                # order used here (se,sw,nw,ne)
                nw_point = sw_point + openstudio.Vector3d(0, slice_, 0)
                ne_point = se_point + openstudio.Vector3d(0, slice_, 0)

                if actual_perim > 0 and (actual_perim * 2.0) < length:
                    polygon_a = openstudio.Point3dVector()
                    polygon_a.append(se_point)
                    polygon_a.append(se_point + openstudio.Vector3d(-actual_perim, 0, 0))
                    polygon_a.append(ne_point + openstudio.Vector3d(-actual_perim, 0, 0))
                    polygon_a.append(ne_point)
                    if double_loaded_corridor:
                        hash_of_point_vectors[f"{perim_space_type.nameString()} A {k}"] = {}
                        hash_of_point_vectors[f"{perim_space_type.nameString()} A {k}"]['space_type'] = perim_space_type
                        hash_of_point_vectors[f"{perim_space_type.nameString()} A {k}"]['polygon'] = polygon_a
                    else:
                        hash_of_point_vectors[f"{space_type.nameString()} A {k}"] = {}
                        hash_of_point_vectors[f"{space_type.nameString()} A {k}"]['space_type'] = space_type
                        hash_of_point_vectors[f"{space_type.nameString()} A {k}"]['polygon'] = polygon_a

                    polygon_b = openstudio.Point3dVector()
                    polygon_b.append(se_point + openstudio.Vector3d(-actual_perim, 0, 0))
                    polygon_b.append(sw_point + openstudio.Vector3d(actual_perim, 0, 0))
                    polygon_b.append(nw_point + openstudio.Vector3d(actual_perim, 0, 0))
                    polygon_b.append(ne_point + openstudio.Vector3d(-actual_perim, 0, 0))
                    if double_loaded_corridor:
                        hash_of_point_vectors[f"{core_space_type.nameString()} B {k}"] = {}
                        hash_of_point_vectors[f"{core_space_type.nameString()} B {k}"]['space_type'] = core_space_type
                        hash_of_point_vectors[f"{core_space_type.nameString()} B {k}"]['polygon'] = polygon_b
                    else:
                        hash_of_point_vectors[f"{space_type.nameString()} B {k}"] = {}
                        hash_of_point_vectors[f"{space_type.nameString()} B {k}"]['space_type'] = space_type
                        hash_of_point_vectors[f"{space_type.nameString()} B {k}"]['polygon'] = polygon_b

                    polygon_c = openstudio.Point3dVector()
                    polygon_c.append(sw_point + openstudio.Vector3d(actual_perim, 0, 0))
                    polygon_c.append(sw_point)
                    polygon_c.append(nw_point)
                    polygon_c.append(nw_point + openstudio.Vector3d(actual_perim, 0, 0))
                    if double_loaded_corridor:
                        hash_of_point_vectors[f"{perim_space_type.nameString()} C {k}"] = {}
                        hash_of_point_vectors[f"{perim_space_type.nameString()} C {k}"]['space_type'] = perim_space_type
                        hash_of_point_vectors[f"{perim_space_type.nameString()} C {k}"]['polygon'] = polygon_c
                    else:
                        hash_of_point_vectors[f"{space_type.nameString()} C {k}"] = {}
                        hash_of_point_vectors[f"{space_type.nameString()} C {k}"]['space_type'] = space_type
                        hash_of_point_vectors[f"{space_type.nameString()} C {k}"]['polygon'] = polygon_c
                else:
                    polygon_a = openstudio.Point3dVector()
                    polygon_a.append(se_point)
                    polygon_a.append(sw_point)
                    polygon_a.append(nw_point)
                    polygon_a.append(ne_point)
                    hash_of_point_vectors[f"{space_type.nameString()} {k}"] = {}
                    hash_of_point_vectors[f"{space_type.nameString()} {k}"]['space_type'] = space_type
                    hash_of_point_vectors[f"{space_type.nameString()} {k}"]['polygon'] = polygon_a

                # update west points
                sw_point = nw_point
                se_point = ne_point
            else:
                ne_point = nw_point + openstudio.Vector3d(slice_, 0, 0)
                se_point = sw_point + openstudio.Vector3d(slice_, 0, 0)

                if actual_perim > 0 and (actual_perim * 2.0) < width:
                    polygon_a = openstudio.Point3dVector()
                    polygon_a.append(sw_point)
                    polygon_a.append(sw_point + openstudio.Vector3d(0, actual_perim, 0))
                    polygon_a.append(se_point + openstudio.Vector3d(0, actual_perim, 0))
                    polygon_a.append(se_point)
                    if double_loaded_corridor:
                        hash_of_point_vectors[f"{perim_space_type.nameString()} A {k}"] = {}
                        hash_of_point_vectors[f"{perim_space_type.nameString()} A {k}"]['space_type'] = perim_space_type
                        hash_of_point_vectors[f"{perim_space_type.nameString()} A {k}"]['polygon'] = polygon_a
                    else:
                        hash_of_point_vectors[f"{space_type.nameString()} A {k}"] = {}
                        hash_of_point_vectors[f"{space_type.nameString()} A {k}"]['space_type'] = space_type
                        hash_of_point_vectors[f"{space_type.nameString()} A {k}"]['polygon'] = polygon_a

                    polygon_b = openstudio.Point3dVector()
                    polygon_b.append(sw_point + openstudio.Vector3d(0, actual_perim, 0))
                    polygon_b.append(nw_point + openstudio.Vector3d(0, -actual_perim, 0))
                    polygon_b.append(ne_point + openstudio.Vector3d(0, -actual_perim, 0))
                    polygon_b.append(se_point + openstudio.Vector3d(0, actual_perim, 0))
                    if double_loaded_corridor:
                        hash_of_point_vectors[f"{core_space_type.nameString()} B {k}"] = {}
                        hash_of_point_vectors[f"{core_space_type.nameString()} B {k}"]['space_type'] = core_space_type
                        hash_of_point_vectors[f"{core_space_type.nameString()} B {k}"]['polygon'] = polygon_b
                    else:
                        hash_of_point_vectors[f"{space_type.nameString()} B {k}"] = {}
                        hash_of_point_vectors[f"{space_type.nameString()} B {k}"]['space_type'] = space_type
                        hash_of_point_vectors[f"{space_type.nameString()} B {k}"]['polygon'] = polygon_b

                    polygon_c = openstudio.Point3dVector()
                    polygon_c.append(nw_point + openstudio.Vector3d(0, -actual_perim, 0))
                    polygon_c.append(nw_point)
                    polygon_c.append(ne_point)
                    polygon_c.append(ne_point + openstudio.Vector3d(0, -actual_perim, 0))
                    if double_loaded_corridor:
                        hash_of_point_vectors[f"{perim_space_type.nameString()} C {k}"] = {}
                        hash_of_point_vectors[f"{perim_space_type.nameString()} C {k}"]['space_type'] = perim_space_type
                        hash_of_point_vectors[f"{perim_space_type.nameString()} C {k}"]['polygon'] = polygon_c
                    else:
                        hash_of_point_vectors[f"{space_type.nameString()} C {k}"] = {}
                        hash_of_point_vectors[f"{space_type.nameString()} C {k}"]['space_type'] = space_type
                        hash_of_point_vectors[f"{space_type.nameString()} C {k}"]['polygon'] = polygon_c
                else:
                    polygon_a = openstudio.Point3dVector()
                    polygon_a.append(sw_point)
                    polygon_a.append(nw_point)
                    polygon_a.append(ne_point)
                    polygon_a.append(se_point)
                    hash_of_point_vectors[f"{space_type.nameString()} {k}"] = {}
                    hash_of_point_vectors[f"{space_type.nameString()} {k}"]['space_type'] = space_type
                    hash_of_point_vectors[f"{space_type.nameString()} {k}"]['polygon'] = polygon_a

                # update west points
                nw_point = ne_point
                sw_point = se_point

    return hash_of_point_vectors


def create_spaces_from_polygons(model, footprints, typical_story_height, effective_num_stories,
                                footprint_origin_point=None, story_hash=None):
    """Take diagram made by create_core_and_perimeter_polygons and make multi-story building.

    @todo add option to create shading surfaces when using multiplier. Mainly important
    for non rectangular buildings where self shading would be an issue.

    :param model: OpenStudio model object
    :param footprints: list of footprint polygon dicts that make up the spaces
    :param typical_story_height: typical story height in meters
    :param effective_num_stories: effective number of stories
    :param footprint_origin_point: optional openstudio.Point3d for the new origin
    :param story_hash: building story information including space origin z value and
        space height. If blank, this method will default to using information in the story_hash.
    :return: list of OpenStudio Space objects
    """
    if footprint_origin_point is None:
        footprint_origin_point = openstudio.Point3d(0.0, 0.0, 0.0)
    if story_hash is None:
        story_hash = {}

    # default story hash is for three stories with mid-story multiplier, but user
    # can pass in custom versions
    if not story_hash:
        if effective_num_stories > 2:
            story_hash['ground'] = {'space_origin_z': footprint_origin_point.z(), 'space_height': typical_story_height, 'multiplier': 1}
            story_hash['mid'] = {'space_origin_z': footprint_origin_point.z() + typical_story_height + (typical_story_height * (math.ceil(effective_num_stories) - 3) / 2.0), 'space_height': typical_story_height, 'multiplier': effective_num_stories - 2}
            story_hash['top'] = {'space_origin_z': footprint_origin_point.z() + (typical_story_height * (math.ceil(effective_num_stories) - 1)), 'space_height': typical_story_height, 'multiplier': 1}
        elif effective_num_stories > 1:
            story_hash['ground'] = {'space_origin_z': footprint_origin_point.z(), 'space_height': typical_story_height, 'multiplier': 1}
            story_hash['top'] = {'space_origin_z': footprint_origin_point.z() + (typical_story_height * (math.ceil(effective_num_stories) - 1)), 'space_height': typical_story_height, 'multiplier': 1}
        else:
            # one story only
            story_hash['ground'] = {'space_origin_z': footprint_origin_point.z(), 'space_height': typical_story_height, 'multiplier': 1}

    # hash of new spaces (only change boundary conditions for these)
    new_spaces = []

    # loop through story_hash and polygons to generate all of the spaces
    for index, (story_name, story_data) in enumerate(story_hash.items()):
        # make new story unless story at requested height already exists.
        story = None
        for ext_story in sorted_by_name(model.getBuildingStorys()):
            # (Ruby `.to_f` renders an unset optional nominalZCoordinate as 0.0)
            nom_z = opt(ext_story.nominalZCoordinate())
            nom_z = 0.0 if nom_z is None else float(nom_z)
            if abs(nom_z - float(story_data['space_origin_z'])) < 0.01:
                story = ext_story
        if story is None:
            story = openstudio.model.BuildingStory(model)
            # not used for anything
            story.setNominalFloortoFloorHeight(story_data['space_height'])
            # not used for anything
            story.setNominalZCoordinate(story_data['space_origin_z'])
            story.setName(f"Story {story_name}")

        # multiplier values for adjacent stories to be altered below as needed
        multiplier_story_above = 1
        multiplier_story_below = 1

        story_values = list(story_hash.values())
        if index == 0:  # bottom floor, only check above
            if len(story_hash) > 1:
                multiplier_story_above = story_values[index + 1]['multiplier']
        elif index == len(story_hash) - 1:  # top floor, check only below
            multiplier_story_below = story_values[index - 1]['multiplier']
        else:  # mid floor, check above and below
            multiplier_story_above = story_values[index + 1]['multiplier']
            multiplier_story_below = story_values[index - 1]['multiplier']

        # if adjacent story has multiplier > 1 then make appropriate surfaces adiabatic
        adiabatic_ceilings = False
        adiabatic_floors = False
        if story_data['multiplier'] > 1:
            adiabatic_ceilings = True
            adiabatic_floors = True
        elif multiplier_story_above > 1:
            adiabatic_ceilings = True
        elif multiplier_story_below > 1:
            adiabatic_floors = True

        # get the right collection of polygons to make up footprint for each building story
        if index > len(footprints) - 1:
            # use last footprint
            target_footprint = footprints[-1]
        else:
            target_footprint = footprints[index]

        for name, space_data in target_footprint.items():
            # gather options
            options = {
                'name': f"{name} - {story.nameString()}",
                'space_type': space_data['space_type'],
                'story': story,
                'make_thermal_zone': True,
                'thermal_zone_multiplier': story_data['multiplier'],
                'floor_to_floor_height': story_data['space_height'],
            }

            # make space
            space = create_space_from_polygon(model, space_data['polygon'][0], space_data['polygon'], options)
            new_spaces.append(space)

            # set z origin to proper position
            space.setZOrigin(story_data['space_origin_z'])

            # loop through celings and floors to hard asssign constructions and set boundary condition
            if adiabatic_ceilings or adiabatic_floors:
                for surface in space.surfaces():
                    if adiabatic_floors and surface.surfaceType() == 'Floor':
                        if surface.construction().is_initialized():
                            surface.setConstruction(surface.construction().get())
                        surface.setOutsideBoundaryCondition('Adiabatic')
                    if adiabatic_ceilings and surface.surfaceType() == 'RoofCeiling':
                        if surface.construction().is_initialized():
                            surface.setConstruction(surface.construction().get())
                        surface.setOutsideBoundaryCondition('Adiabatic')

        # @tofo in future add code to include plenums or raised floor to each/any story.

    # any changes to wall boundary conditions will be handled by same code that calls this method.
    # this method doesn't need to know about basements and party walls.
    return new_spaces


def create_space_from_polygon(model, space_origin, point_3d_vector, options=None):
    """Create a space from input, optionally take a name, space type, story and thermal zone.

    :param model: OpenStudio model object describing the space footprint polygon
    :param space_origin: openstudio.Point3d origin point
    :param point_3d_vector: openstudio.Point3dVector defining the space footprint
    :param options: dict of options for additional arguments —
        'name' (str), 'space_type' (SpaceType), 'story' (BuildingStory),
        'make_thermal_zone' (bool, defaults truthy from caller),
        'thermal_zone' (ThermalZone), 'thermal_zone_multiplier' (int, 1),
        'floor_to_floor_height' (m, defaults to 10 ft)
    :return: OpenStudio Space object
    """
    # set defaults to use if user inputs not passed in
    defaults = {
        'name': None,
        'space_type': None,
        'story': None,
        'make_thermal_zone': None,
        'thermal_zone': None,
        'thermal_zone_multiplier': 1,
        'floor_to_floor_height': opt(openstudio.convert(10.0, 'ft', 'm')),
    }

    # merge user inputs with defaults
    options = {**defaults, **(options or {})}

    # Identity matrix for setting space origins
    m = openstudio.Matrix(4, 4, 0)
    m[0, 0] = 1
    m[1, 1] = 1
    m[2, 2] = 1
    m[3, 3] = 1

    # make space from floor print
    space = openstudio.model.Space.fromFloorPrint(point_3d_vector, options['floor_to_floor_height'], model)
    space = space.get()
    m[0, 3] = space_origin.x()
    m[1, 3] = space_origin.y()
    m[2, 3] = space_origin.z()
    space.changeTransformation(openstudio.Transformation(m))
    space.setBuildingStory(options['story'])
    if options['name'] is not None:
        space.setName(options['name'])

    if options['space_type'] is not None and isinstance(options['space_type'], openstudio.model.SpaceType):
        space.setSpaceType(options['space_type'])

    # create thermal zone if requested and assign
    if options['make_thermal_zone']:
        new_zone = openstudio.model.ThermalZone(model)
        new_zone.setMultiplier(options['thermal_zone_multiplier'])
        space.setThermalZone(new_zone)
        new_zone.setName(f"Zone {space.nameString()}")
    else:
        if options['thermal_zone'] is not None:
            space.setThermalZone(options['thermal_zone'])

    return space
