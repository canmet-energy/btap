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

    @use_json_package = false
    @use_string_double = false
    @measure_interface_detailed = [

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
            "display_name" => "A Double numeric Argument (double)",
            "default_value" => 0,
            "max_double_value" => 100.0,
            "min_double_value" => 0.0,
            "is_required" => false
        },
        {
            "name" => "a_string_double_argument",
            "type" => "StringDouble",
            "display_name" => "A String Double numeric Argument (double)",
            "default_value" => 23.0,
            "max_double_value" => 100.0,
            "min_double_value" => 0.0,
            "valid_strings" => ["NA"],
            "is_required" => false
        },
        {
            "name" => "a_choice_argument",
            "type" => "Choice",
            "display_name" => "A Choice String Argument ",
            "default_value" => "choice_1",
            "choices" => ["choice_1", "choice_2"],
            "is_required" => false
        },
        {
            "name" => "a_bool_argument",
            "type" => "Bool",
            "display_name" => "A Boolean Argument ",
            "default_value" => false,
            "is_required" => true
        }

    ]

    @good_input_arguments = {
        "a_string_argument" => "MyString",
        "a_double_argument" => 50.0,
        "a_string_double_argument" => "50.0",
        "a_choice_argument" => "choice_1",
        "a_bool_argument" => true
    }

  end

  def test_sample()

    ####### Test Model Creation######
    #You'll need a seed model to test against. You have a few options.
    # If you are only testing arguments, you can use an empty model like I am doing here.
    # Option 1: Model CreationCreate Empty Model object and start doing things to it. Here I am creating an empty model
    # and adding surface geometry to the model
    model = OpenStudio::Model::Model.new
    # and adding surface geometry to the model using the wizard.
    BTAP::Geometry::Wizards.create_shape_rectangle(model,
                                                   length = 100.0,
                                                   width = 100.0,
                                                   above_ground_storys = 3,
                                                   under_ground_storys = 1,
                                                   floor_to_floor_height = 3.8,
                                                   plenum_height = 1,
                                                   perimeter_zone_depth = 4.57,
                                                   initial_height = 0.0)
    # If we wanted to apply some aspects of a standard to our model we can by using a factory method to bring the
    # standards we want into our tests. So to bring the necb2011 we write.
    necb2011_standard = Standard.build('NECB2011')

    # could add some example contructions if we want. This method will populate the model with some
    # constructions and apply it to the model
    necb2011_standard.model_clear_and_set_example_constructions(model)

    # While debugging and testing, it is sometimes nice to make a copy of the model as it was.
    before_measure_model = copy_model(model)

    # You can save your file anytime you want here I am saving to the
    BTAP::FileIO::save_osm(model, File.join(File.dirname(__FILE__), "output", "saved_file.osm"))

    #We can even call the standard methods to apply to the model.
    necb2011_standard.model_add_design_days_and_weather_file(model, 'NECB HDD Method', 'CAN_BC_Vancouver.Intl.AP.718920_CWEC2016.epw')

    puts BTAP::FileIO.compare_osm_files(before_measure_model, model)
    necb2011_standard.apply_standard_construction_properties(model) # standards candidate


    # Another simple way is to create an NECB
    # building using the helper method below.
    #Option #2 NECB method.
    #   model = create_necb_protype_model(
    #      "LargeOffice",
    #     'NECB HDD Method',
    #      'CAN_BC_Vancouver.Intl.AP.718920_CWEC2016.epw',
    #      "NECB2011"
    #   )

    # You can also run annually the model directly.
    #   necb2011_standard.model_run_simulation_and_log_errors( model, File.join(File.dirname(__FILE__),"output" ))

    # Or a quick sizing run if you need something fast.
    #   necb2011_standard.model_run_sizing_run(model, File.join(File.dirname(__FILE__),"output" ))

    # Another simple way is to create an NECB
    # building using the helper method below.
    # Option #3 Load osm file.
    # model = BTAP::FileIO.load_osm(filepath)


    # Set up your argument list to test.
    input_arguments = {
        "a_string_argument" => "MyString",
        "a_double_argument" => 10.0,
        "a_string_double_argument" => 75.3,
        "a_choice_argument" => "choice_1"
    }

    json_input_argument = {
    "json_input"=> '{
                      "a_string_argument": "The Default Value",
                      "a_double_argument": 0,
                      "a_string_double_argument": 23.0,
                      "a_choice_argument": "choice_1",
                      "a_bool_argument": false
}'
    }

    # Create an instance of the measure
    runner = run_measure(input_arguments, model)


    assert(runner.result.value.valueName == 'Success')
  end


  ##### Helper methods Do notouch unless you know the consequences.

  def test_arguments_and_defaults
    # Create an instance of the measure
    measure = get_measure_object()
    model = OpenStudio::Model::Model.new

    # Create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    # Test arguments and defaults
    arguments = measure.arguments(model)
    #convert whatever the input was into a hash. Then test.

    #check number of arguments.
    if @use_json_package
      assert_equal(@measure_interface_detailed.size, JSON.parse(arguments[0].defaultValueAsString).size, "The measure should have #{@measure_interface_detailed.size} but actually has #{arguments.size}. Here the the arguement expected #{@measure_interface_detailed} and this is the actual #{arguments}")
    else
      assert_equal(@measure_interface_detailed.size, arguments.size, "The measure should have #{@measure_interface_detailed.size} but actually has #{arguments.size}. Here the the arguement expected #{@measure_interface_detailed} and this is the actual #{arguments}")
      (@measure_interface_detailed).each_with_index do |argument_expected, index|
        assert_equal(argument_expected['name'], arguments[index].name, "Measure argument name of #{argument_expected['name']} was expected, but got #{arguments[index].name} instead.")
        assert_equal(argument_expected['display_name'], arguments[index].displayName, "Display name for argument #{argument_expected['name']} was expected to be #{argument_expected['display_name']}, but got #{arguments[index].displayName} instead.")
        case argument_type(arguments[index])
          when "String", "Choice"
            assert_equal(argument_expected['default_value'].to_s, arguments[index].defaultValueAsString, "The default value for argument #{argument_expected['name']} was #{argument_expected['default_value']}, but actual was #{arguments[index].defaultValueAsString}")
          when "Double", "Integer"
            assert_equal(argument_expected['default_value'].to_f, arguments[index].defaultValueAsDouble.to_f, "The default value for argument #{argument_expected['name']} was #{argument_expected['default_value']}, but actual was #{arguments[index].defaultValueAsString}")
          when "Bool"
            assert_equal(argument_expected['default_value'], arguments[index].defaultValueAsBool, "The default value for argument #{argument_expected['name']} was #{argument_expected['default_value']}, but actual was #{arguments[index].defaultValueAsString}")
        end
      end
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
          assert(runner.result.value.valueName != 'Success', "Checks did not stop a lower than limit value of #{over_max_value} for #{argument['name']}")
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
          assert(runner.result.value.valueName != 'Success', "Checks did not stop a lower than limit value of #{over_min_value} for #{argument['name']}")
        end

      end
      if (argument['type'] == 'StringDouble') and (not argument["valid_strings"].nil?) and @use_string_double
        model = OpenStudio::Model::Model.new
        input_arguments = @good_input_arguments.clone
        input_arguments[argument['name']] = SecureRandom.uuid.to_s
        puts "Testing argument #{argument['name']} min limit of #{argument['min_double_value']}"
        run_measure(input_arguments, model)
        runner = run_measure(input_arguments, model)
        assert(runner.result.value.valueName != 'Success', "Checks did not stop a lower than limit value of #{over_min_value} for #{argument['name']}")
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

  def run_measure(input_arguments, model)

    # This will create a instance of the measure you wish to test. It does this based on the test class name.
    measure = get_measure_object()
    # Return false if can't
    return false if false == measure
    arguments = measure.arguments(model)
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)
    #Check if

    # Set the arguements in the argument map
    input_arguments.each_with_index do |(key, value), index|
      argument = arguments[index].clone
      if argument_type(argument) == "Double"
        #forces it to a double if it is a double.
        assert(argument.setValue(value.to_f), "Could not set value for #{key} to #{value}")
      else
        assert(argument.setValue(value), "Could not set value for #{key} to #{value}")
      end
      argument_map[key] = argument
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

  def argument_type(argument)
    case argument.type.value
      when 0
        return "Bool"
      when 1 #Double
        return "Double"
      when 2 #Quantity
        return "Quantity"
      when 3 #Integer
        return "Integer"
      when 4
        return "String"
      when 5 #Choice
        return "Choice"
      when 6 #Path
        return "Path"
      when 7 #Separator
        return "Separator"
      else
        return "Blah"
    end
  end

  def valid_float?(str)
    !!Float(str) rescue false
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
