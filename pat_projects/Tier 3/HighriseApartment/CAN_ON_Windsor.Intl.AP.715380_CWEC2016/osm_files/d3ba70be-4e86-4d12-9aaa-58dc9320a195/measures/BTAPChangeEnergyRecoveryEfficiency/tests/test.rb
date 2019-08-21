# insert your copyright here

require 'openstudio'
require 'openstudio/measure/ShowRunnerOutput'
require 'minitest/autorun'
require_relative '../measure.rb'
require 'fileutils'

class BTAPChangeEnergyRecoveryEfficiencyTest < Minitest::Test

  def test_number_of_arguments_and_argument_names
    # create an instance of the measure
    measure = BTAPChangeEnergyRecoveryEfficiency.new

    # load the test model
    translator = OpenStudio::OSVersion::VersionTranslator.new
    path = OpenStudio::Path.new(File.dirname(__FILE__) + "/in.osm")
    model = translator.loadModel(path)
    assert((not model.empty?))
    model = model.get

    # get arguments and test that they are what we are expecting
    arguments = measure.arguments(model)
    assert_equal(8, arguments.size)
    assert_equal('sensible_eff_at_100_heating', arguments[0].name)
    assert_equal('latent_eff_at_100_heating', arguments[1].name)
    assert_equal('sensible_eff_at_75_heating', arguments[2].name)
    assert_equal('latent_eff_at_75_heating', arguments[3].name)
    assert_equal('sensible_eff_at_100_cooling', arguments[4].name)
    assert_equal('latent_eff_at_100_cooling', arguments[5].name)
    assert_equal('sensible_eff_at_75_cooling', arguments[6].name)
    assert_equal('latent_eff_at_75_cooling', arguments[7].name)
  end


  def test_argument_values
    # create an instance of the measure
    measure = BTAPChangeEnergyRecoveryEfficiency.new

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
    args_hash['sensible_eff_at_100_heating'] = 0.20
    args_hash['latent_eff_at_100_heating'] = 0.30
    args_hash['sensible_eff_at_75_heating'] = 0.40
    args_hash['latent_eff_at_75_heating'] = 0.50
    args_hash['sensible_eff_at_100_cooling'] = 0.60
    args_hash['latent_eff_at_100_cooling'] = 0.70
    args_hash['sensible_eff_at_75_cooling'] = 0.80
    args_hash['latent_eff_at_75_cooling'] = 0.90
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

    #check if efficiencies were changed correctly
    model.getAirLoopHVACOutdoorAirSystems.each do |oa_system|
      oa_system.oaComponents.each do |oa_component|
        if oa_component.to_HeatExchangerAirToAirSensibleAndLatent.is_initialized
          runner.registerInfo("*** Identified the ERV")
          erv = oa_component.to_HeatExchangerAirToAirSensibleAndLatent.get

          assert_equal(args_hash['latent_eff_at_100_cooling'],erv.latentEffectivenessat100CoolingAirFlow)
          assert_equal(args_hash['latent_eff_at_100_heating'],erv.latentEffectivenessat100HeatingAirFlow)
          assert_equal(args_hash['latent_eff_at_75_cooling'],erv.latentEffectivenessat75CoolingAirFlow)
          assert_equal(args_hash['latent_eff_at_75_heating'],erv.latentEffectivenessat75HeatingAirFlow)
          assert_equal(args_hash['sensible_eff_at_100_cooling'],erv.sensibleEffectivenessat100CoolingAirFlow)
          assert_equal(args_hash['sensible_eff_at_100_heating'],erv.sensibleEffectivenessat100HeatingAirFlow)
          assert_equal(args_hash['sensible_eff_at_75_cooling'],erv.sensibleEffectivenessat75CoolingAirFlow)
          assert_equal(args_hash['sensible_eff_at_75_heating'],erv.sensibleEffectivenessat75HeatingAirFlow)
        end
      end
    end
    
    # save the model to test output directory
    output_file_path = "#{File.dirname(__FILE__)}//output/test_output.osm"
    model.save(output_file_path, true)
  end
end
