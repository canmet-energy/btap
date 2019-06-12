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

class BTAPChangeSetpointManager_Test < Minitest::Test

  include(BTAPMeasureTestHelper)

  def setup()
    @use_json_package = false
    @use_string_double = true
    @measure_interface_detailed = [
        {
            "name" => "setpPointManagerType",
            "type" => "Choice",
            "display_name" => "Type of Setpoint Manager",
            "default_value" => "setpointManager_SingleZoneReheat",
            "choices" => ["setpointManager_Warmest", "setpointManager_SingleZoneReheat", "setpointManager_OutdoorAirReset"],
            "is_required" => true
        }
    ]
    @good_input_arguments = {
        "setpPointManagerType" => "setpointManager_Warmest"

    }
  end

  def test_setpointManagerWarmest()
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
        "setpPointManagerType" => "setpointManager_Warmest"
    }

    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)
    measure = BTAPChangeSetpointManager.new
    # get arguments
    arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    runner = run_measure(input_arguments, model)

    # Double check that the Setpoint Manager was set to the new assigned value in the output osm file
    BTAP::FileIO::save_osm(model, File.join(File.dirname(__FILE__), "output", "out_warmest.osm"))

    final_SetpointManagers = 0
    setpointM_name_arr = []
    model.getNodes.each do |node|
      node.setpointManagers.each do |setpointM|
        setpointM_name = setpointM.name.to_s
        setpointM_name_arr.unshift(setpointM_name)
      end
    end
    num_warmest = 0;
    for s in setpointM_name_arr do
      if s.include? "Setpoint Manager Warmest"
        num_warmest += 1
      end
    end
    if (num_warmest == 0)
      raise ("The measure wasn't able to create any Setpoint Managers of type : Warmest.")
      return false
    end
  end

  def test_setpointManagerSingleZoneReheat()
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
        "setpPointManagerType" => "setpointManager_SingleZoneReheat"
    }

    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)
    measure = BTAPChangeSetpointManager.new
    # get arguments
    arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    runner = run_measure(input_arguments, model)

    # Double check that the Setpoint Manager was set to the new assigned value in the output osm file
    BTAP::FileIO::save_osm(model, File.join(File.dirname(__FILE__), "output", "out_SingleZoneReheat.osm"))

    final_SetpointManagers = 0
    setpointM_name_arr = []
    model.getNodes.each do |node|
      node.setpointManagers.each do |setpointM|
        setpointM_name = setpointM.name.to_s
        setpointM_name_arr.unshift(setpointM_name)
      end
    end
    num_SingleZoneReheat = 0;
    for s in setpointM_name_arr do
      if s.include? "Setpoint Manager Single Zone Reheat"
        num_SingleZoneReheat += 1
      end
    end
    if (num_SingleZoneReheat == 0)
      raise ("The measure wasn't able to create any Setpoint Managers of type : Single Zone Reheat.")
      return false
    end
  end

  def test_setpointManagerOutdoorAirReset()
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
        "setpPointManagerType" => "setpointManager_OutdoorAirReset"
    }

    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)
    measure = BTAPChangeSetpointManager.new
    # get arguments
    arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    runner = run_measure(input_arguments, model)

    # Double check that the Setpoint Manager was set to the new assigned value in the output osm file
    BTAP::FileIO::save_osm(model, File.join(File.dirname(__FILE__), "output", "out_OutdoorAirReset.osm"))

    final_SetpointManagers = 0
    setpointM_name_arr = []
    model.getNodes.each do |node|
      node.setpointManagers.each do |setpointM|
        setpointM_name = setpointM.name.to_s
        setpointM_name_arr.unshift(setpointM_name)
      end
    end
    num_OutdoorAirReset = 0;
    for s in setpointM_name_arr do
      if s.include? "Setpoint Manager Outdoor Air Reset"
        num_OutdoorAirReset += 1
      end
    end
    if (num_OutdoorAirReset == 0)
      raise ("The measure wasn't able to create any Setpoint Managers of type : OutdoorAirReset.")
      return false
    end

  end
end


