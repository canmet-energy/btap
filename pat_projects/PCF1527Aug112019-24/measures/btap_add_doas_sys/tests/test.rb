# insert your copyright here

require 'openstudio'
require 'openstudio/measure/ShowRunnerOutput'
require 'minitest/autorun'
require_relative '../measure.rb'
require 'fileutils'

class BTAPAddDOASSysTest < Minitest::Test
  # def setup
  # end

  # def teardown
  # end

  def test_number_of_arguments_and_argument_names
    # create an instance of the measure
    measure = BTAPAddDOASSys.new

    # load the test model
    translator = OpenStudio::OSVersion::VersionTranslator.new
    path = OpenStudio::Path.new(File.dirname(__FILE__) + "/in.osm")
    model = translator.loadModel(path)
    assert((not model.empty?))
    model = model.get

    # get arguments and test that they are what we are expecting
    arguments = measure.arguments(model)
    assert_equal(1, arguments.size)
    assert_equal('zonesselected', arguments[0].name)
  end


  def test_argument_values
    # create an instance of the measure
    measure = BTAPAddDOASSys.new

    # create runner with empty OSW
    osw = OpenStudio::WorkflowJSON.new
    runner = OpenStudio::Measure::OSRunner.new(osw)

    # load the test model
    translator = OpenStudio::OSVersion::VersionTranslator.new
    path = OpenStudio::Path.new(File.dirname(__FILE__) + "/in.osm")
    model = translator.loadModel(path)
    assert((not model.empty?))
    model = model.get

    # store the number of spaces in the seed model
    num_spaces_seed = model.getSpaces.size

    # get arguments
    arguments = measure.arguments(model)
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)

    # create hash of argument values.
    # If the argument has a default that you want to use, you don't need it in the hash
    args_hash = {}
    args_hash['zonesselected'] = 'All Zones'
    # using defaults values from measure.rb for other arguments

    # populate argument with specified hash value if specified
    arguments.each do |arg|
      temp_arg_var = arg.clone
      if args_hash.key?(arg.name)
        assert(temp_arg_var.setValue(args_hash[arg.name]))
      end
      argument_map[arg.name] = temp_arg_var
    end

    # run the measure
    measure.run(model, runner, argument_map)
    result = runner.result

    # show the output
    show_output(result)

    # assert that it ran correctly
    assert_equal('Success', result.value.valueName)
    assert(result.warnings.empty?)

    # check for number of zonehvac:ERV
    num_of_ervs = model.getZoneHVACEnergyRecoveryVentilators.size
    num_of_zones= 0
    model.getAirLoopHVACs.each do |airloop|
      num_of_zones = num_of_zones + airloop.thermalZones.size.to_i
    end
    assert_equal(num_of_zones, num_of_ervs, "number of ervs do not match zones")

    #check for air loop outdoor air flowrate
    model.getAirLoopHVACs.each do |airloop|
      outdoor_flow=1.0
      if airloop.airLoopHVACOutdoorAirSystem.is_initialized
        if airloop.airLoopHVACOutdoorAirSystem.get.getControllerOutdoorAir.maximumOutdoorAirFlowRate.is_initialized
          outdoor_flow = airloop.airLoopHVACOutdoorAirSystem.get.getControllerOutdoorAir.maximumOutdoorAirFlowRate.get.to_f
        end
      end
      assert (0.001> outdoor_flow)
    end

    # save the model to test output directory
    output_file_path = "#{File.dirname(__FILE__)}//output/test_output.osm"
    model.save(output_file_path, true)
  end
end