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

class BTAPSetNECBInfiltration_Test < Minitest::Test
  # Brings in helper methods to simplify argument testing of json and standard argument methods.
  include(BTAPMeasureTestHelper)

  def setup()

    @use_json_package = false
    @use_string_double = true

    # Load the geometry .osm
    osm_file = "#{File.dirname(__FILE__)}/test_models/FullServiceRestaurant-NECB2017-CAN_AB_Banff.CS.711220_CWEC2016.osm"
    unless File.exist?(osm_file)
      raise("The initial osm path: #{osm_file} does not exist.")
    end
    osm_model_path = OpenStudio::Path.new(osm_file.to_s)
    # Upgrade version if required.
    version_translator = OpenStudio::OSVersion::VersionTranslator.new
    model = version_translator.loadModel(osm_model_path).get

    @measure_interface_detailed = [
        {
            "name" => "infiltration_si",
            "type" => "Double",
            "display_name" => "Space Infiltration Flow per Exterior Envelope Surface Area L/(s*m2) at 75 Pa. ",
            "default_value" => 1.50,
            "max_double_value" => 20.00,
            "min_double_value" => 0.00,
            "is_required" => true
        }
    ]


    @good_input_arguments = {
        "infiltration_si" => 1.50
    }

  end

  def test_sample()
    # Load the geometry .osm
    osm_file = "#{File.dirname(__FILE__)}/test_models/FullServiceRestaurant-NECB2017-CAN_AB_Banff.CS.711220_CWEC2016.osm"
    unless File.exist?(osm_file)
      raise("The initial osm path: #{osm_file} does not exist.")
    end
    osm_model_path = OpenStudio::Path.new(osm_file.to_s)
    # Upgrade version if required.
    version_translator = OpenStudio::OSVersion::VersionTranslator.new
    model = version_translator.loadModel(osm_model_path).get

    input_arguments = {
        "infiltration_si" => 1.50
    }

    #get the initial infiltrationDesignFlowPerExteriorSurfaceArea
    exteriorSurfaceAreaInfiltarion_before = model.getBuilding.infiltrationDesignFlowPerExteriorSurfaceArea

    # Create an instance of the measure
    runner = run_measure(input_arguments, model)
    puts show_output(runner.result)
    # get arguments
    measure = BTAPSetNECBInfiltration.new
    arguments = measure.arguments(model)

    # get user arguments
    infiltration_si = arguments [0]

    infiltration_si_m3 = Float (infiltration_si.defaultValueAsDouble) * 0.001 # to convert from L/(s*m2) to m3/(s*m2) multiply by 0.001
    infiltration_si_5Pa = Float(infiltration_si_m3) * 0.172004845 # to convert from 75 Pa to 5 Pa

    #get design flow rate space infiltration objects used in the model
    space_infiltration_objects = model.getSpaceInfiltrationDesignFlowRates
    exteriorSurfaceAreaInfiltarion_new = model.getBuilding.infiltrationDesignFlowPerExteriorSurfaceArea
    
    # test that the measure has changed the exterior Surface Area Infiltarion to the value specified by the user
    assert_in_delta exteriorSurfaceAreaInfiltarion_new, infiltration_si_5Pa, 0.01

    # Double check that the infiltration flow rate was set to the new assigned value in the output osm file
    BTAP::FileIO::save_osm(model, File.join(File.dirname(__FILE__), "output", "saved_file.osm"))

    assert(runner.result.value.valueName == 'Success')
  end
end
