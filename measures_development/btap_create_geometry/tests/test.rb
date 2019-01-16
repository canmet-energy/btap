require 'openstudio'
require 'openstudio/measure/ShowRunnerOutput'
require 'fileutils'
require 'openstudio-standards'
begin
  require 'openstudio_measure_tester/test_helper'
rescue LoadError
  puts 'OpenStudio Measure Tester Gem not installed -- will not be able to aggregate and dashboard the results of tests'
end
require_relative '../measure.rb'
require_relative '../resources/BTAPMeasureHelper.rb'
require 'minitest/autorun'


class BtapCreateGeometry_Test < Minitest::Test
  # Brings in helper methods to simplify argument testing of json and standard argument methods.
  include(BTAPMeasureTestHelper)
  def setup()

    @use_json_package = false
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

    @good_input_arguments = {
        "building_name" => "courtyard",
        "building_shape" => "Courtyard",
        "total_floor_area" => 5000,
        "aspect_ratio" => 2.0,
        "rotation" => 0.0,
        "above_grade_floors" => 2,
        "floor_to_floor_height" => 3.2,
        "plenum_height" => 1.2
    }

  end

  def test_sample()
    ####### Test Model Creation ######
	# Create an empty model. This measure will overwrite whatever is supplied here.
    model = OpenStudio::Model::Model.new

    # Create an instance of the measure with good values
    runner = run_measure(@good_input_arguments, model)
    assert(runner.result.value.valueName == 'Success')

    # While debugging and testing, it is sometimes nice to make a copy of the model as it was.
    before_measure_model = copy_model(model)
    model = OpenStudio::Model::Model.new

   # Set up your argument list to test.
      input_arguments = {
        "building_name" => "courtyard",
        "building_shape" => "Courtyard",
        "total_floor_area" => 50000,
        "aspect_ratio" => 0.5,
        "rotation" => 0.0,
        "above_grade_floors" => 2,
        "floor_to_floor_height" => 3.2,
        "plenum_height" => 1.0
      }
    #end

    # Create an instance of the measure
    runner = run_measure(input_arguments, model)
    BTAP::FileIO::save_osm(model, File.join(File.dirname(__FILE__), "output", "courtyard.osm"))
    assert(runner.result.value.valueName == 'Success')

    ########################################################################################################################

    model = OpenStudio::Model::Model.new

    input_arguments = {
        "building_name" => "rectangular",
        "building_shape" => "Rectangular",
        "total_floor_area" => 50000,
        "aspect_ratio" => 0.5,
        "rotation" => 0.0,
        "above_grade_floors" => 2,
        "floor_to_floor_height" => 3.2,
        "plenum_height" => 1.0
    }
    #end

    # Create an instance of the measure
    runner = run_measure(input_arguments, model)
    BTAP::FileIO::save_osm(model, File.join(File.dirname(__FILE__), "output", "rectangular.osm"))
    assert(runner.result.value.valueName == 'Success')
    runner.registerInfo(" \e[32m Rectangular shape is created. \e[0m .")
    ##################################################################################################################################

    model = OpenStudio::Model::Model.new

    input_arguments = {
        "building_name" => "L shape",
        "building_shape" => "L shape",
        "total_floor_area" => 50000,
        "aspect_ratio" => 0.5,
        "rotation" => 0.0,
        "above_grade_floors" => 3,
        "floor_to_floor_height" => 3.2,
        "plenum_height" => 1.0
    }
    #end

    # Create an instance of the measure
    runner = run_measure(input_arguments, model)
    BTAP::FileIO::save_osm(model, File.join(File.dirname(__FILE__), "output", "L_Shape.osm"))
    assert(runner.result.value.valueName == 'Success')
    runner.registerInfo(" \e[32m L_Shape is created. \e[0m .")
    ###################################################################################################################################

    model = OpenStudio::Model::Model.new

    input_arguments = {
        "building_name" => "H shape",
        "building_shape" => "H shape",
        "total_floor_area" => 50000,
        "aspect_ratio" => 0.5,
        "rotation" => 0.0,
        "above_grade_floors" => 3,
        "floor_to_floor_height" => 3.2,
        "plenum_height" => 1.0
    }
    #end

    # Create an instance of the measure
    runner = run_measure(input_arguments, model)
    BTAP::FileIO::save_osm(model, File.join(File.dirname(__FILE__), "output", "H_Shape.osm"))
    assert(runner.result.value.valueName == 'Success')
    runner.registerInfo(" \e[32m H_Shape is created. \e[0m .")
    ############################################################################################################################################

    model = OpenStudio::Model::Model.new

    input_arguments = {
        "building_name" => "U shape",
        "building_shape" => "U shape",
        "total_floor_area" => 50000,
        "aspect_ratio" => 0.5,
        "rotation" => 0.0,
        "above_grade_floors" => 3,
        "floor_to_floor_height" => 3.2,
        "plenum_height" => 1.0
    }
    #end

    # Create an instance of the measure
    runner = run_measure(input_arguments, model)
    BTAP::FileIO::save_osm(model, File.join(File.dirname(__FILE__), "output", "U_Shape.osm"))
    assert(runner.result.value.valueName == 'Success')
    runner.registerInfo(" \e[32m U_Shape is created. \e[0m .")
    #############################################################################################################################################

    model = OpenStudio::Model::Model.new

    input_arguments = {
        "building_name" => "T shape",
        "building_shape" => "T shape",
        "total_floor_area" => 50000,
        "aspect_ratio" => 0.5,
        "rotation" => 0.0,
        "above_grade_floors" => 3,
        "floor_to_floor_height" => 3.2,
        "plenum_height" => 1.0
    }
    #end

    # Create an instance of the measure
    runner = run_measure(input_arguments, model)
    BTAP::FileIO::save_osm(model, File.join(File.dirname(__FILE__), "output", "T_Shape.osm"))
    assert(runner.result.value.valueName == 'Success')
    runner.registerInfo(" \e[32m T_Shape is created. \e[0m .")

  end
end