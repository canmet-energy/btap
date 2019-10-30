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


  def test_a()
    # Load the geometry .osm
    osm_file = "#{File.dirname(__FILE__)}/test_models/FullServiceRestaurant-NECB2017-CAN_AB_Banff.CS.711220_CWEC2016.osm"
    unless File.exist?(osm_file)
      raise("The initial osm path: #{osm_file} does not exist.")
    end
    osm_model_path = OpenStudio::Path.new(osm_file.to_s)
    # Upgrade version if required.
    version_translator = OpenStudio::OSVersion::VersionTranslator.new
    model = version_translator.loadModel(osm_model_path).get

    # Create an instance of the measure
    measure = BTAPSetNECBInfiltration.new
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)
    input_arguments = @good_input_arguments
    runner = run_measure(input_arguments, model)

    puts "Checking runner was successful..."   
    assert(runner.result.value.valueName == 'Success')

    # Calculate 'correct' infiltration value 
    infiltration_si_m3 = Float (input_arguments['infiltration_si']) * 0.001 # to convert from L/(s*m2) to m3/(s*m2) multiply by 0.001
    infiltration_si_5Pa = Float(infiltration_si_m3) * 0.172004845 # to convert from 75 Pa to 5 Pa

    #get design flow rate space infiltration objects used in the model
    final_exteriorSurfaceAreaInfiltarion = model.getBuilding.infiltrationDesignFlowPerExteriorSurfaceArea

    # test that the measure has changed the exterior Surface Area Infiltarion to the value specified by the user
    puts "*** check new infiltartion value OK ***"
    assert_in_delta(final_exteriorSurfaceAreaInfiltarion, infiltration_si_5Pa, 0.01)
    assert_in_delta(final_exteriorSurfaceAreaInfiltarion, 999, 0.01)
  end
end
