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
require 'minitest/autorun'


class BTAPTemplateMeasure_Test < Minitest::Test
  def setup()
    @arguments_expected = [
        {
            "name" => "a_string_argument",
            "type" => "String",
            "display_name" => "A String Argument (string)",
            "default_value" => "The Default Value",
            "valid_strings" => ["baseline", "NA"]
        },
        {
            "name" => "a_double_argument",
            "type" => "Double",
            "display_name" => "A Double numermic Argument (double)",
            "default_value" => 0,
            "max_double_value" => 100.0,
            "min_double_value" => 0.0
        },
        {
            "name" => "a_string_double_argument",
            "type" => "StringDouble",
            "display_name" => "A Double numermic Argument (double)",
            "default_value" => "NA",
            "max_double_value" => 100.0,
            "min_double_value" => 0.0,
            "valid_strings" => ["Baseline", "NA"]
        },
        {
            "name" => "a_choice_argument",
            "type" => "Choice",
            "display_name" => "A Choice String Argument ",
            "default_value" => 0,
            "max_double_value" => 100.0,
            "min_double_value" => 0.0,
            "choices" => ["choice_1", "choice_2"]
        },
    ]
  end

  def test_sample_create_a_building_from_scratch()

    # Set up your argument list to test.
    input_arguments = {
        "a_string_argument" => "MyString",
        "a_double_argument" => 99999.99,
        "a_string_double_argument" => "888888.8",
        "a_choice_argument" => "NA"
    }

    # Create an instance of the measure
    self.class.name.demodulize
    measure = BTAPTemplateMeasure.new
    arguments = measure.arguments(model)
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)

    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)
    # Set the arguements in the argument map
    input_arguments.each_with_index do |(key, value), index|
      argument = arguments[index].clone
      assert(argument.setValue(value))
      argument_map[key] = argument
    end

    #run the measure
    measure.run(model, runner, argument_map)
    result = runner.result
    assert(result.value.valueName == 'Success')
  end

  def copy_model(model)
    copy_model = OpenStudio::Model::Model.new
    # remove existing objects from model
    handles = OpenStudio::UUIDVector.new
    copy_model.objects.each do |obj|
      handles << obj.handle
    end
    copy_model.removeObjects(handles)
    # put contents of new_model into model_to_replace
    copy_model.addObjects(model.toIdfFile.objects)
    return copy_model
  end

  ##### Helper methods

  def test_arguments_and_defaults
    # Create an instance of the measure
    measure = BTAPTemplateMeasure.new

    # Create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    # Test arguments and defaults
    arguments = measure.arguments(model)
    #check number of arguments.
    assert_equal(@arguments_expected.size, arguments.size)
    (@arguments_expected).each_with_index do |argument_expected, index|
      assert_equal(argument_expected['name'], arguments[index].name)
      assert_equal(argument_expected['display_name'], arguments[index].displayName)
      assert_equal(argument_expected['default_value'].to_s, arguments[index].defaultValueAsString)
    end
  end




  def create_necb_protype_model(building_type, climate_zone, epw_file, template)
    osm_directory = "#{Dir.pwd}/output/#{building_type}-#{template}-#{climate_zone}-#{epw_file}"
    FileUtils.mkdir_p (osm_directory) unless Dir.exist?(osm_directory)
    #Get Weather climate zone from lookup
    weather = BTAP::Environment::WeatherFile.new(epw_file)
    #create model
    building_name = "#{template}_#{building_type}"
    puts "Creating #{building_name}"
    prototype_creator = Standard.build(building_name)
    model = prototype_creator.model_create_prototype_model(climate_zone,
                                                           epw_file,
                                                           osm_directory,
                                                           @debug,
                                                           model)
    #set weather file to epw_file passed to model.
    weather.set_weather_file(model)
    return model
  end
end
