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


class BTAPSetRoofConductanceByNecbClimateZone_Test  < Minitest::Test
  include(BTAPMeasureTestHelper)

  def setup()
    #Set to true if you want to package the arguments as json.
    @use_json_package = false
    #Set to true if you want to want to allow strings and doubles in stringdouble types. Set to false to force to use doubles. The latter is used for certain
    # continuous optimization algorithms. You may have to re-examine your input in PAT as this fundamentally changes the measure.
    @use_string_double = false

    #Use percentages instead of values
    @use_percentages = false

    #Set to true if debugging measure.
    @debug = true
    #this is the 'do nothing value and most arguments should have. '
    @baseline = 0.0

    #Creating a data-driven measure. This is because there are a large amount of inputs to enter and test.. So creating
    # an array to work around is programmatically easier.

@measure_interface_detailed = [
        {
            "name" => "zone4_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone4 Roof Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 31.03,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },

        {
            "name" => "zone5_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone5 Roof Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 31.03,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
           "name" => "zone6_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone6 Roof Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 35.05,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "zone7A_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone7A Roof Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 35.05,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "zone7B_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone7B Roof Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 39.99,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "zone8_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone8 Roof Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 47.32,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        }

    ]


    @good_input_arguments = {
       "zone4_r_value" => 31.03,
        "zone5_r_value" => 31.03,
        "zone6_r_value" => 35.05,
        "zone7A_r_value" => 35.05,
        "zone7B_r_value" => 39.99,
        "zone8_r_value" => 47.32
    }



  end

  def test_Zone4_conductane

    measure = BTAPSetRoofConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    #load model
    # model = create_model_by_local_osm_file('/EnvelopeAndLoadTestModel_01.osm')
    # Use the NECB prototype to create a model to test against. Alterantively we could load an osm file instead.
    model = create_necb_protype_model(
        "SmallOffice",
        'NECB HDD Method',
        'CAN_BC_Victoria.Intl.AP.717990_CWEC2016.epw',
        "NECB2011"
    )
    puts "testing zone 4 climate zone with new cond equals to 36.4"
    # get arguments
   arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)


    input_arguments = {
     "zone4_r_value" => 31.03,
        "zone5_r_value" => 31.03,
        "zone6_r_value" => 35.05,
        "zone7A_r_value" => 35.05,
        "zone7B_r_value" => 39.99,
        "zone8_r_value" => 47.32
    }

    runner = run_measure(input_arguments, model)

    result = runner.result
    show_output(result)


    # save the model
    # output_file_path = OpenStudio::Path.new(File.dirname(__FILE__) + "/test.osm")
    # model.save(output_file_path,true)
  end

  def test_Zone5_conductane

    measure = BTAPSetRoofConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    #load model
    # model = create_model_by_local_osm_file('/EnvelopeAndLoadTestModel_01.osm')
    # Use the NECB prototype to create a model to test against. Alterantively we could load an osm file instead.
    model = create_necb_protype_model(
        "SmallOffice",
        'NECB HDD Method',
        'CAN_ON_Windsor.Intl.AP.715380_CWEC2016.epw',
        "NECB2011"
    )
    puts "testing zone 5 climate zone with new cond equals to 41 "
    # get arguments
    arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)


    input_arguments = {
      "zone4_r_value" => 31.03,
        "zone5_r_value" => 31.03,
        "zone6_r_value" => 35.05,
        "zone7A_r_value" => 35.05,
        "zone7B_r_value" => 39.99,
        "zone8_r_value" => 47.32
    }

    runner = run_measure(input_arguments, model)

    result = runner.result
    show_output(result)


    # save the model
    # output_file_path = OpenStudio::Path.new(File.dirname(__FILE__) + "/test.osm")
    # model.save(output_file_path,true)
  end

=begin
  def test_Zone6_conductane

    measure = BTAPSetRoofConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    #load model
    # model = create_model_by_local_osm_file('/EnvelopeAndLoadTestModel_01.osm')
    # Use the NECB prototype to create a model to test against. Alterantively we could load an osm file instead.
    model = create_necb_protype_model(
        "SmallOffice",
        'NECB HDD Method',
        'CAN_ON_Ottawa-Macdonald-Cartier.Intl.AP.716280_CWEC2016.epw',
        "NECB2011"
    )
    puts "testing zone 6 climate zone with new cond equals to 41"
    # get arguments
    arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)


    input_arguments = {
      "zone4_r_value" => 36.4,
        "zone5_r_value" => 41,
        "zone6_r_value" => 41,
        "zone7A_r_value" => 46.9,
        "zone7B_r_value" => 47.11,
        "zone8_r_value" => 53.73
    }

    runner = run_measure(input_arguments, model)

    result = runner.result
    show_output(result)


    # save the model
    # output_file_path = OpenStudio::Path.new(File.dirname(__FILE__) + "/test.osm")
    # model.save(output_file_path,true)
  end
=end

  def test_Zone7a_conductane

    measure = BTAPSetRoofConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    #load model
    # model = create_model_by_local_osm_file('/EnvelopeAndLoadTestModel_01.osm')
    # Use the NECB prototype to create a model to test against. Alterantively we could load an osm file instead.
    model = create_necb_protype_model(
        "SmallOffice",
        'NECB HDD Method',
        'CAN_AB_Edmonton.Intl.AP.711230_CWEC2016.epw',
        "NECB2011"
    )
    puts "testing zone 4 climate zone with new cond equals to 46.9"
    # get arguments
    arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)


    input_arguments = {
      "zone4_r_value" => 31.03,
        "zone5_r_value" => 31.03,
        "zone6_r_value" => 35.05,
        "zone7A_r_value" => 35.05,
        "zone7B_r_value" => 39.99,
        "zone8_r_value" => 47.32
    }

    runner = run_measure(input_arguments, model)

    result = runner.result
    show_output(result)


    # save the model
    # output_file_path = OpenStudio::Path.new(File.dirname(__FILE__) + "/test.osm")
    # model.save(output_file_path,true)
  end

  def test_Zone7b_conductane

    measure = BTAPSetRoofConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    #load model
    # model = create_model_by_local_osm_file('/EnvelopeAndLoadTestModel_01.osm')
    # Use the NECB prototype to create a model to test against. Alterantively we could load an osm file instead.
    model = create_necb_protype_model(
        "SmallOffice",
        'NECB HDD Method',
        'CAN_AB_Fort.McMurray.AP.716890_CWEC2016.epw',
        "NECB2011"
    )
    puts "testing zone 7b climate zone with new cond equals to 54"
    # get arguments
    arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)


    input_arguments = {
   "zone4_r_value" => 31.03,
        "zone5_r_value" => 31.03,
        "zone6_r_value" => 35.05,
        "zone7A_r_value" => 35.05,
        "zone7B_r_value" => 39.99,
        "zone8_r_value" => 47.32
    }

    runner = run_measure(input_arguments, model)

    result = runner.result
    show_output(result)


    # save the model
    # output_file_path = OpenStudio::Path.new(File.dirname(__FILE__) + "/test.osm")
    # model.save(output_file_path,true)
  end


  def test_Zone8_conductane

    measure = BTAPSetRoofConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    #load model
    # model = create_model_by_local_osm_file('/EnvelopeAndLoadTestModel_01.osm')
    # Use the NECB prototype to create a model to test against. Alterantively we could load an osm file instead.
    model = create_necb_protype_model(
        "SmallOffice",
        'NECB HDD Method',
        'CAN_NT_Yellowknife.AP.719360_CWEC2016.epw',
        "NECB2011"
    )
    puts "testing zone 8 climate zone with new cond equals to 61.9"
    # get arguments
    arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)


    input_arguments = {
      "zone4_r_value" => 31.03,
        "zone5_r_value" => 31.03,
        "zone6_r_value" => 35.05,
        "zone7A_r_value" => 35.05,
        "zone7B_r_value" => 39.99,
        "zone8_r_value" => 47.32
    }

    runner = run_measure(input_arguments, model)

    result = runner.result
    show_output(result)


    # save the model
    # output_file_path = OpenStudio::Path.new(File.dirname(__FILE__) + "/test.osm")
    # model.save(output_file_path,true)
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
