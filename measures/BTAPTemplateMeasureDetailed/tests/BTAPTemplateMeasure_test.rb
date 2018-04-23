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


class BTAPTemplateMeasureDetailed_Test < Minitest::Test
  def setup()


    @measure_interface_detailed = [
        {
            "name" => "packaged_or_detailed",
            "type" => "String",
            "display_name" => "Use Packaged or Detailed input",
            "default_value" => "Detailed",
            "choices" => ["Packaged", "Detailed"],
            "is_required" => true
        },
        {
            "name" => "json_package_input",
            "type" => "String",
            "display_name" => "JSON input for measure",
            "default_value" => '{
                                  "a_string_argument": "MyString",
                                  "a_double_argument": 10.0,
                                  "a_string_double_argument": "75.3",
                                  "a_choice_argument": "choice_1"
            }',
            "is_required" => false
        },
        {
            "name" => "a_string_argument",
            "type" => "String",
            "display_name" => "A String Argument (string)",
            "default_value" => "The Default Value",
            "is_required" => false
        },
        {
            "name" => "a_double_argument",
            "type" => "Double",
            "display_name" => "A Double numeric Argument",
            "default_value" => 0,
            "max_double_value" => 100.0,
            "min_double_value" => 0.0,
            "units" => "units",
            "is_required" => false
        },
        {
            "name" => "a_string_double_argument",
            "type" => "StringDouble",
            "display_name" => "A String Double numeric Argument (double)",
            "default_value" => "NA",
            "max_double_value" => 100.0,
            "min_double_value" => 0.0,
            "valid_strings" => ["NA"],
            "units" => "units",
            "is_required" => false
        },
        {
            "name" => "a_choice_argument",
            "type" => "Choice",
            "display_name" => "A Choice String Argument ",
            "default_value" => "choice_1",
            "choices" => ["choice_1", "choice_2"],
            "is_required" => false
        }

    ]

    @good_input_arguments = {
        "a_string_argument" => "MyString",
        "a_double_argument" => 50.0,
        "a_string_double_argument" => "50.0",
        "a_choice_argument" => "choice_1"
    }

  end

  def dont_test_sample_create_a_building_from_scratch()

    #Create/Load Model to test against
    model = OpenStudio::Model::Model.new
    # Set up your argument list to test.
    input_arguments = {
        "a_string_argument" => "MyString",
        "a_double_argument" => 10.0,
        "a_string_double_argument" => "75.3",
        "a_choice_argument" => "choice_1"
    }
    # Create an instance of the measure
    runner = run_measure(input_arguments, model)
    assert(runner.result.value.valueName == 'Success')
  end





























  ##### Helper methods

  def test_arguments_and_defaults
    # Create an instance of the measure
    measure = get_measure_object()
    model = OpenStudio::Model::Model.new

    # Create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    # Test arguments and defaults
    arguments = measure.arguments(model)
    #check number of arguments.
    assert_equal(@measure_interface_detailed.size, arguments.size, "The measure should have #{@measure_interface_detailed.size} but actually has #{arguments.size}. Here the the arguement expected #{@measure_interface_detailed} and this is the actual #{arguments}")
    (@measure_interface_detailed).each_with_index do |argument_expected, index|
      assert_equal(argument_expected['name'], arguments[index].name, "Measure argument name of #{argument_expected['name']} was expected, but got #{arguments[index].name} instead.")
      assert_equal(argument_expected['display_name'], arguments[index].displayName, "Display name for argument #{argument_expected['name']} was expected to be #{argument_expected['display_name']}, but got #{arguments[index].displayName} instead.")
      assert_equal(argument_expected['default_value'].to_s, arguments[index].defaultValueAsString, "The default value for argument #{argument_expected['name']} was #{argument_expected['default_value']}, but actual was #{arguments[index].defaultValueAsString}")
    end
  end

  def test_argument_ranges
    (@measure_interface_detailed).each_with_index do |argument|
      if argument['type'] == 'Double' or argument['type'] == 'StringDouble'
        #Check over max
        if not argument['max_double_value'].nil?
          model = OpenStudio::Model::Model.new
          input_arguments = @good_input_arguments.clone
          over_max_value = argument['max_double_value'].to_f + 1.0
          over_max_value = over_max_value.to_s if argument['type'].downcase == "StringDouble".downcase
          input_arguments[argument['name']] = over_max_value
          puts "Testing argument #{argument['name']} max limit of #{argument['max_double_value']}"
          run_measure(input_arguments, model)
          runner = run_measure(input_arguments, model)
          assert(runner.result.value.valueName != 'Success',"Checks did not stop a lower than limit value of #{over_max_value} for #{argument['name']}" )
        end
        #Check over max
        if not argument['min_double_value'].nil?
          model = OpenStudio::Model::Model.new
          input_arguments = @good_input_arguments.clone
          over_min_value = argument['min_double_value'].to_f - 1.0
          over_min_value = over_max_value.to_s if argument['type'].downcase == "StringDouble".downcase
          input_arguments[argument['name']] = over_min_value
          puts "Testing argument #{argument['name']} min limit of #{argument['min_double_value']}"
          run_measure(input_arguments, model)
          runner = run_measure(input_arguments, model)
          assert(runner.result.value.valueName != 'Success',"Checks did not stop a lower than limit value of #{over_min_value} for #{argument['name']}" )
        end

      end
      if argument['type'] == 'StringDouble' and not argument["valid_strings"].nil?
        model = OpenStudio::Model::Model.new
        input_arguments = @good_input_arguments.clone
        input_arguments[argument['name']] = SecureRandom.uuid.to_s
        puts "Testing argument #{argument['name']} min limit of #{argument['min_double_value']}"
        run_measure(input_arguments, model)
        runner = run_measure(input_arguments, model)
        assert(runner.result.value.valueName != 'Success',"Checks did not stop a lower than limit value of #{over_min_value} for #{argument['name']}" )
      end
    end
  end


  def create_necb_protype_model(building_type, climate_zone, epw_file, template)

    osm_directory = "#{Dir.pwd}/output/#{building_type}-#{template}-#{climate_zone}-#{epw_file}"
    FileUtils.mkdir_p (osm_directory) unless Dir.exist?(osm_directory)
    #Get Weather climate zone from lookup
    weather = BTAP::Environment::WeatherFile.new(epw_file)
    #create model
    building_name = "#{template}_#{building_type}"

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

  def run_measure(hash_input_arguments, model)

    # This will create a instance of the measure you wish to test. It does this based on the test class name.
    measure = get_measure_object()
    # Return false if can't
    return false if false == measure
    arguments = measure.arguments(model)
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)
    # Set the arguements in the argument map by searching for the correct argument
    hash_input_arguments.each_with_index do |(key, value), index|
      arguments.each do |arg|
        if arg.name == key
          argument = arg.clone
          assert(argument.setValue(value), "Could not set value for #{key} to #{value}")
          argument_map[key] = argument
        end
      end
    end

    #run the measure
    measure.run(model, runner, argument_map)
    runner.result
    return runner
  end

  def get_measure_object()
    measure_class_name = self.class.name.to_s.match(/(BTAP.*)(\_Test)/i).captures[0]
    measure = nil
    eval "measure = #{measure_class_name}.new"
    if measure.nil?
      puts "Measure class #{measure_class_name} is invalid. Please ensure the test class name is of the form 'MeasureName_Test' "
      return false
    end
    return measure
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

end
