# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/
require_relative 'resources/BTAPMeasureHelper'

# start the measure
class BtapCreateGeometry < OpenStudio::Measure::ModelMeasure

  attr_accessor :use_json_package, :use_string_double
  #Adds helper functions to make life a bit easier and consistent.
  include(BTAPMeasureHelper)
  # human readable name
  def name
    return "BtapCreateGeometry"
  end

  # human readable description
  def description
    return "Creates standard building shapes and define spaces. The total floor area, and number of floors are specified. The building is assumed to be in thirds (thus for the courtyard the middle third is the void)"
  end

  # human readable description of modeling approach
  def modeler_description
    return "Defines the geometry of the building based on the given inputs. Uses BTAP::Geometry::Wizards::create_shape_* methods"
  end

  #Use the constructor to set global variables
  def initialize() super()
  #Set to true if you want to package the arguments as json.
  @use_json_package = false
  #Set to true if you want to want to allow strings and doubles in stringdouble types. Set to false to force to use doubles. The latter is used for certain
  # continuous optimization algorithms. You may have to re-examine your input in PAT as this fundamentally changes the measure.
  @use_string_double = true

  @measure_interface_detailed = [
                                 {
                                  "name" => "building_name",
                                  "type" => "String",
                                  "display_name" => "Building name",
                                  "default_value" => "building",
                                  "is_required" => true

                                 },

                                 {
                                  "name" => "building_shape",
                                  "type" => "Choice",
                                  "display_name" => "Building shape",
                                  "default_value" => "Rectangular",
                                  "choices" => ["Courtyard", "H shape", "L shape", "Rectangular", "T shape", "U shape"],
                                  "is_required" => true
                                 },

                                 {
                                  "name" => "total_floor_area",
                                  "type" => "Double",
                                  "display_name" => "Total building area (m2)",
                                  "default_value" => 50000,
                                  "max_double_value" => 10000000.0,
                                  "min_double_value" => 10.0,
                                  "is_required" => true
                                 },

                                 {
                                  "name" => "aspect_ratio",
                                  "type" => "Double",
                                  "display_name" => "Aspect ratio (width/length; width faces south before rotation)",
                                  "default_value" => 1.0,
                                  "max_double_value" => 10.0,
                                  "min_double_value" => 0.1,
                                  "is_required" => true
                                 },

                                 {
                                  "name" => "rotation",
                                  "type" => "Double",
                                  "display_name" => "Rotation (degrees clockwise)",
                                  "default_value" => 0.0,
                                  "max_double_value" => 360.0,
                                  "min_double_value" => 0.0,
                                  "is_required" => true
                                 },

                                 {
                                  "name" => "above_grade_floors",
                                  "type" => "Integer",
                                  "display_name" => "Number of above grade floors",
                                  "default_value" => 3,
                                  "max_integer_value" => 200,
                                  "min_integer_value" => 1,
                                  "is_required" => true
                                 },

                                 {
                                 "name" => "floor_to_floor_height",
                                 "type" => "Double",
                                 "display_name" => "Floor to floor height (m)",
                                 "default_value" => 3.8,
                                 "max_double_value" => 10.0,
                                 "min_double_value" => 2.0,
                                 "is_required" => false
                                 },

                                 {
                                 "name" => "plenum_height",
                                 "type" => "Double",
                                 "display_name" => "Plenum height (m)",
                                 "default_value" => 1,
                                 "max_double_value" => 2.0,
                                 "min_double_value" => 0.1,
                                 "is_required" => false
                                 }
                                ]
  end

  # define what happens when the measure is run
  def run(model, runner, user_arguments)

    #Runs parent run method.
    super(model, runner, user_arguments)

    # Gets arguments from interfaced and puts them in a hash with there display name. This also does a check on ranges to
    # ensure that the values inputted are valid based on your @measure_interface array of hashes.
    arguments = validate_and_get_arguments_in_hash(model, runner, user_arguments)

    #puts JSON.pretty_generate(arguments)
    return false if false == arguments

    #" ******************* Creating Courtyard Shape ***********************************"
    if arguments['building_shape'] == 'Courtyard'

      # Figure out dimensions from inputs
      floor_area=arguments['total_floor_area']/arguments['above_grade_floors']
      b = Math::sqrt(((8.0/9.0)*floor_area))/ arguments['aspect_ratio']
      a = b * arguments['aspect_ratio']
      # Set perimeter depth to min of 1/3 smallest section width or 4.57 (=BTAP default)
      perimeter_depth=[([a, b].min/9.0), 4.57].min
    # Generate the geometry
      BTAP::Geometry::Wizards::create_shape_courtyard(model, length = a, width = b, courtyard_length = a/3, courtyard_width = b/3, num_floors = arguments['above_grade_floors'], floor_to_floor_height = arguments['floor_to_floor_height'], plenum_height = arguments['plenum_height'], perimeter_zone_depth = perimeter_depth)


      #" ******************* Creating Rectangular Shape ***********************************"
      elsif arguments['building_shape'] == 'Rectangular'
      # Figure out dimensions from inputs
      floor_area=arguments['total_floor_area']/arguments['above_grade_floors']
      b = Math::sqrt(floor_area) / arguments['aspect_ratio']
      a = b * arguments['aspect_ratio']
      # Set perimeter depth to min of 1/3 smallest section width or 4.57 (=BTAP default)
      perimeter_depth=[([a, b].min/9.0), 4.57].min
      # Generate the geometry
      BTAP::Geometry::Wizards::create_shape_rectangle(model, length = a, width = b, above_ground_storys = arguments['above_grade_floors'], under_ground_storys = 0, floor_to_floor_height = arguments['floor_to_floor_height'], plenum_height = arguments['plenum_height'], perimeter_zone_depth = perimeter_depth, initial_height = 0.0)

      #" ******************* Creating L-Shape ***********************************"
      elsif arguments['building_shape'] == 'L shape'
      # Figure out dimensions from inputs
      floor_area=arguments['total_floor_area']/arguments['above_grade_floors']
      b = Math::sqrt((5.0/9.0)*floor_area) / arguments['aspect_ratio']
      a = b * arguments['aspect_ratio']
      # Set perimeter depth to min of 1/3 smallest section width or 4.57 (=BTAP default)
      perimeter_depth=[([a, b].min/9.0), 4.57].min
      # Generate the geometry
      BTAP::Geometry::Wizards::create_shape_l(model, length = a, width = b, lower_end_width = b/3, upper_end_length = a/3, num_floors = arguments['above_grade_floors'], floor_to_floor_height = arguments['floor_to_floor_height'], plenum_height = arguments['plenum_height'], perimeter_zone_depth = perimeter_depth
      )

      #" ******************* Creating H-Shape Shape ***********************************"
      elsif arguments['building_shape'] == 'H shape'
      # Figure out dimensions from inputs
      floor_area=arguments['total_floor_area']/arguments['above_grade_floors']
      b = Math::sqrt((7.0/9.0)*floor_area) / arguments['aspect_ratio']
      a = b * arguments['aspect_ratio']
      # Set perimeter depth to min of 1/3 smallest section width or 4.57 (=BTAP default)
      perimeter_depth=[([a, b].min/9.0), 4.57].min
      # Generate the geometry
      # runner.registerInfo ("center_width = b/4 : #{b/4} , left_width = b/3 : #{b/3} , left_upper_end_offset = a/15: #{a/15} ")
      BTAP::Geometry::Wizards::create_shape_h(model, length = a, left_width = b/3, center_width = b/4, right_width = b/3, left_end_length = a/3, right_end_length = a/3, left_upper_end_offset = a/15, right_upper_end_offset = a/15, num_floors = arguments['above_grade_floors'], floor_to_floor_height = arguments['floor_to_floor_height'], plenum_height = arguments['plenum_height'], perimeter_zone_depth = perimeter_depth
      )

      #" ******************* Creating T-Shape Shape ***********************************"
      elsif arguments['building_shape'] == 'T shape'
      # Figure out dimensions from inputs
      floor_area=arguments['total_floor_area']/arguments['above_grade_floors']
      b = Math::sqrt((5.0/9.0)*floor_area) / arguments['aspect_ratio']
      a = b * arguments['aspect_ratio']
      # Set perimeter depth to min of 1/3 smallest section width or 4.57 (=BTAP default)
      perimeter_depth=[([a, b].min/9), 4.57].min
      # Generate the geometry
      BTAP::Geometry::Wizards::create_shape_t(model, length = a, width = b, upper_end_width = a/3, lower_end_length = b/3, left_end_offset = a/4, num_floors = arguments['above_grade_floors'], floor_to_floor_height = arguments['floor_to_floor_height'], plenum_height = arguments['plenum_height'], perimeter_zone_depth = perimeter_depth
      )

      #" ******************* Creating U-Shape Shape ***********************************"
      elsif arguments['building_shape'] == 'U shape'
      # Figure out dimensions from inputs
      floor_area=arguments['total_floor_area']/arguments['above_grade_floors']
      b = Math::sqrt((7.0/9.0)*floor_area) / arguments['aspect_ratio']
      a = b * arguments['aspect_ratio']
      # Set perimeter depth to min of 1/3 smallest section width or 4.57 (=BTAP default)
      perimeter_depth=[([a, b].min/9), 4.57].min

      # Generate the geometry

      BTAP::Geometry::Wizards::create_shape_u(model, length = a, left_width = b/3, right_width = b/3, left_end_length = a/10, right_end_length = a/3, left_end_offset = a/5, num_floors = arguments['above_grade_floors'], floor_to_floor_height =arguments['floor_to_floor_height'], plenum_height = arguments['plenum_height'], perimeter_zone_depth = perimeter_depth
      )

    end

    # Define standard to use
    #model_standard = Standard.build('NECB2011')

    # could add some example constructions if we want. This method will populate the model with some
    # constructions and apply it to the model
    #model_standard.model_clear_and_set_example_constructions(model)

    #Rotate model.
    t = OpenStudio::Transformation::rotation(OpenStudio::EulerAngles.new(0, 0, arguments['rotation']*Math::PI/180.0))
    model.getPlanarSurfaceGroups().each {|planar_surface| planar_surface.changeTransformation(t)}

    building = model.getBuilding
    building.setName(arguments['building_name'])

    return true
  end

end


# register the measure to be used by the application
BtapCreateGeometry.new.registerWithApplication
