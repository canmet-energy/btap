# insert your copyright here

require 'openstudio'
require 'openstudio/measure/ShowRunnerOutput'
require 'minitest/autorun'
require_relative '../measure.rb'
require 'fileutils'

class BTAPNewSpacetypeLPDListTest < Minitest::Test

  def test_number_of_arguments_and_argument_names
    # create an instance of the measure
    measure = BTAPNewSpacetypeLPDList.new

    # load the test model
    translator = OpenStudio::OSVersion::VersionTranslator.new
    path = OpenStudio::Path.new(File.dirname(__FILE__) + "/in.osm")
    model = translator.loadModel(path)
    assert((not model.empty?))
    model = model.get

    # get arguments and test that they are what we are expecting
    arguments = measure.arguments(model)
    assert_equal(1, arguments.size)
    assert_equal('skip', arguments[0].name)
  end


  def test_argument_values
    # create an instance of the measure
    measure = BTAPNewSpacetypeLPDList.new

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
    args_hash['skip'] = 1
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

    lpd_hash ={}
    lpd_hash['Space Function Warehouse storage area medium to bulky palletized items'] = 3.6
    lpd_hash['Space Function Warehouse storage area small hand-carried items(4)'] = 7.4
    lpd_hash['Space Function Office enclosed <= 25 m2'] = 8.0
    #check lpd
    
    model.getSpaceTypes.each do |space_type|
      if space_type.lightingPowerPerFloorArea.is_initialized
        lpd = space_type.lightingPowerPerFloorArea.get
        name = space_type.name.to_s
        real_lpd = lpd_hash[name]
        assert( (real_lpd-lpd) < 0.001)
      end
    end

    # save the model to test output directory
    output_file_path = "#{File.dirname(__FILE__)}//output/test_output.osm"
    model.save(output_file_path, true)
  end
end
