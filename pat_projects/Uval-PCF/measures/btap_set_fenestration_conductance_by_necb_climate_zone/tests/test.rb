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


class BtapSetFenestrationConductanceByNecbClimateZone_Test  < Minitest::Test
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
            "display_name" => "NECB Zone4 Fenestration Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 3.15,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },

        {
            "name" => "zone5_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone5 Fenestration Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 3.15,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
           "name" => "zone6_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone6 Fenestration Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 3.55,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "zone7A_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone7A Fenestration Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 3.55,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "zone7B_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone7B Fenestration Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 4,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "zone8_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone8 Fenestration Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 4,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        }

    ]

    @good_input_arguments = {
        "zone4_r_value" => 3.15,
        "zone5_r_value" => 3.15,
        "zone6_r_value" => 3.55,
        "zone7A_r_value" => 3.55,
        "zone7B_r_value" => 4,
        "zone8_r_value" => 4
    }

  end

  def test_zone7B

    measure = BtapSetFenestrationConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    #load model
    # model = create_model_by_local_osm_file('/EnvelopeAndLoadTestModel_01.osm')
    # Use the NECB prototype to create a model to test against. Alterantively we could load an osm file instead.
    model = create_necb_protype_model(
        "LargeOffice",
        'NECB HDD Method',
        'CAN_AB_Fort.McMurray.AP.716890_CWEC2016.epw',
        "NECB2011"
    )

    # get arguments
   arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)


    input_arguments = {
        "zone4_r_value" => 3.15,
        "zone5_r_value" => 3.15,
        "zone6_r_value" => 3.55,
        "zone7A_r_value" => 3.55,
        "zone7B_r_value" => 4,
        "zone8_r_value" => 4
    }

    runner = run_measure(input_arguments, model)

    result = runner.result
    show_output(result)


    # save the model
    # output_file_path = OpenStudio::Path.new(File.dirname(__FILE__) + "/test.osm")
    # model.save(output_file_path,true)
  end

  def test_zone4

    measure = BtapSetFenestrationConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    #load model
    # model = create_model_by_local_osm_file('/EnvelopeAndLoadTestModel_01.osm')
    # Use the NECB prototype to create a model to test against. Alterantively we could load an osm file instead.
    model = create_necb_protype_model(
        "SmallHotel",
        'NECB HDD Method',
        'CAN_BC_Victoria.Intl.AP.717990_CWEC2016.epw',
        "NECB2011"
    )

    puts "testing zone 4 climate zone with new cond equals to 3.15 >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>"

    # get arguments
    arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)


    input_arguments = {
        "zone4_r_value" => 3.15,
        "zone5_r_value" => 3.15,
        "zone6_r_value" => 3.55,
        "zone7A_r_value" => 3.55,
        "zone7B_r_value" => 4,
        "zone8_r_value" => 4
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
