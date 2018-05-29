# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/
require_relative 'resources/BTAPMeasureHelper'
# start the measure
class BTAPCreateGeometry < OpenStudio::Measure::ModelMeasure

  #Adds helper functions to make life a bit easier and consistent.
  include(BTAPMeasureHelper)
  # human readable name
  def name
    #BEFORE YOU DO anything.. please generate a new <uid>224561f4-8ccc-4f60-8118-34b85359d6f7</uid>
    return "BTAPCreateGeometry"
  end

  # human readable description
  def description
    return "Create standard building shapes and define spaces. The total floor area, and number of floors are specified. The building is assumed to be in thirds (thus for the courtyard the middle third is the void)"
  end

  # human readable description of modeling approach
  def modeler_description
    return "Defines the geometry of the building based on the given inputs. Uses BTAP::Geometry::Wizards::create_shape_* methods"
  end

  #Use the constructor to set global variables
  def initialize()
    super()
    #Set to true if you want to package the arguments as json.
    @use_json_package = false
    #Set to true if you want to want to allow strings and doubles in stringdouble types. Set to false to force to use doubles. The latter is used for certain
    # continuous optimization algorithms. You may have to re-examine your input in PAT as this fundamentally changes the measure.
    @use_string_double = true

    # Put in this array of hashes all the input variables that you need in your measure. Your choice of types are Sting, Double,
    # StringDouble, and Choice. Optional fields are valid strings, max_double_value, and min_double_value. This will
    # create all the variables, validate the ranges and types you need,  and make them available in the 'run' method as a hash after
    # you run 'arguments = validate_and_get_arguments_in_hash(model, runner, user_arguments)'
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
    #You can now access the input argument by the name.
    # arguments['a_string_argument']
    # arguments['a_double_argument']
    # etc......
    # So write your measure code here!
	
	# Create a new model
    model = OpenStudio::Model::Model.new
	
	# Name the new model
	
	# Depending on the shape requested create the geometry.
    # "choices" => ["Courtyard", "H shape", "L shape", "Rectangular", "T shape", "U shape"],
	if arguments['building_shape'] == 'Courtyard'
	
		# Figure out dimensions from inputs
		floor_area=arguments['total_floor_area']/arguments['above_grade_floors']
        b = Math::sqrt((9/8)*(floor_area / arguments['aspect_ratio']))
        a = b * arguments['aspect_ratio']
		# Set perimeter depth to min of 1/3 smallest section width or 4.57 (=BTAP default)
		perimeter_depth=[([a,b].min/9),4.57].min
		
		# Generate the geometry
		BTAP::Geometry::Wizards::create_shape_courtyard(model,
          length = a,
          width = b,
          courtyard_length = a/3,
          courtyard_width = b/3,
          num_floors = arguments['above_grade_floors'],
          floor_to_floor_height = arguments['floor_to_floor_height'],
          plenum_height = arguments['plenum_height'],
          perimeter_zone_depth = perimeter_depth)
	end
	

    #Do something.
    return true
  end
end


# register the measure to be used by the application
BTAPCreateGeometry.new.registerWithApplication
