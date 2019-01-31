$: << 'C:\Users\barssoumm\new_tests\openstudio-standards\openstudio-standards\lib'

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


class BtapSetEnvelopeConductanceByNecbClimateZone_Test  < Minitest::Test
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
            "name" => "necb_template",
            "type" => "Choice",
            "display_name" => "Template",
            "default_value" => "NECB2015",
            "choices" => ["NECB2011", "NECB2015", "NECB2017"],
            "is_required" => true
        },


        {
            "name" => "surface_type",
            "type" => "Choice",
            "display_name" => "Surface Type",
            "default_value" => "Glazing",
             "choices" => ["Walls", "Roofs", "Floors", "Glazing"],
            "is_required" => true
        },

        {
            "name" => "zone4_u_value",
            "type" => "Double",
            "display_name" => "NECB Zone4 Insulation U-value (W/m^2 K).",
            "default_value" => 0.59,
            "max_double_value" => 5.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },

        {
            "name" => "zone5_u_value",
            "type" => "Double",
            "display_name" => "NECB Zone5 Insulation U-value (W/m^2 K).",
            "default_value" => 0.265,
            "max_double_value" => 5.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
           "name" => "zone6_u_value",
            "type" => "Double",
            "display_name" => "NECB Zone6 Insulation U-value (W/m^2 K).",
            "default_value" => 0.240,
            "max_double_value" => 5.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "zone7A_u_value",
            "type" => "Double",
            "display_name" => "NECB Zone7A Insulation U-value (W/m^2 K).",
            "default_value" => 0.215,
            "max_double_value" => 5.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "zone7B_u_value",
            "type" => "Double",
            "display_name" => "NECB Zone7B Insulation U-value (W/m^2 K).",
            "default_value" => 0.190,
            "max_double_value" => 5.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "zone8_u_value",
            "type" => "Double",
            "display_name" => "NECB Zone8 Insulation U-value (W/m^2 K).",
            "default_value" => 0.165,
            "max_double_value" => 5.0,
            "min_double_value" => 0.0,
            "is_required" => true
        }

    ]

    @good_input_arguments = {
       "necb_template" => "NECB2015",
	   "surface_type" => "Roofs",
       "zone4_u_value" => 0.59,
       "zone5_u_value" => 0.265,
       "zone6_u_value" => 0.240,
       "zone7A_u_value" => 0.215,
       "zone7B_u_value" => 0.190,
       "zone8_u_value" => 0.165
    }

  end


 def test_Zone4_conductane
    measure = BtapSetEnvelopeConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    # Use the NECB prototype to create a model to test against. Alterantively we could load an osm file instead.
    model = create_necb_protype_model(
        "SmallOffice",
        'NECB HDD Method',
        'CAN_BC_Victoria.Intl.AP.717990_CWEC2016.epw',
        "NECB2015"
    )

      # get arguments
   arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    runner = run_measure(@good_input_arguments, model)
    result = runner.result
    show_output(result)

    # test if the measure would grab the correct u value for the correct climate zone.
    assert_equal(0.59, arguments[2].defaultValueAsDouble)
 end


 def test_Zone5_conductane
    measure = BtapSetEnvelopeConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    # Use the NECB prototype to create a model to test against. Alterantively we could load an osm file instead.
    model = create_necb_protype_model(
        "SmallOffice",
        'NECB HDD Method',
        'CAN_ON_Windsor.Intl.AP.715380_CWEC2016.epw',
        "NECB2015"
    )

    # get arguments
    arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    runner = run_measure(@good_input_arguments, model)
    result = runner.result
    show_output(result)

    # test if the measure would grab the correct u value for the correct climate zone.
    assert_equal(0.265, arguments[3].defaultValueAsDouble)
  end



  def test_Zone6_conductane
    measure = BtapSetEnvelopeConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    # Use the NECB prototype to create a model to test against. Alterantively we could load an osm file instead.
    model = create_necb_protype_model(
        "SmallOffice",
        'NECB HDD Method',
        'CAN_QC_Montreal-Trudeau.Intl.AP.716270_CWEC2016.epw',
        "NECB2015"
    )

    # get arguments
    arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    runner = run_measure(@good_input_arguments, model)
    result = runner.result
    show_output(result)

    # test if the measure would grab the correct u value for the correct climate zone.
    assert_equal(0.240, arguments[4].defaultValueAsDouble)
  end


  def test_Zone7a_conductane
    measure = BtapSetEnvelopeConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    # Use the NECB prototype to create a model to test against. Alterantively we could load an osm file instead.
    model = create_necb_protype_model(
        "SmallOffice",
        'NECB HDD Method',
        'CAN_AB_Edmonton.Intl.AP.711230_CWEC2016.epw',
        "NECB2015"
    )

    # get arguments
    arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    runner = run_measure(@good_input_arguments, model)
    result = runner.result
    show_output(result)

   # test if the measure would grab the correct u value for the correct climate zone
   assert_equal(0.215, arguments[5].defaultValueAsDouble)
  end

  def test_Zone7b_conductane
    measure = BtapSetEnvelopeConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    # Use the NECB prototype to create a model to test against. Alterantively we could load an osm file instead.
    model = create_necb_protype_model(
        "SmallOffice",
        'NECB HDD Method',
        'CAN_YT_Whitehorse.Intl.AP.719640_CWEC2016.epw',
        "NECB2015"
    )
    # get arguments
    arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    runner = run_measure(@good_input_arguments, model)
    result = runner.result
    show_output(result)

  # test if the measure would grab the correct u value for the correct climate zone
  assert_equal(0.190, arguments[6].defaultValueAsDouble)
  end


  def test_Zone8_conductane
    measure = BtapSetEnvelopeConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    # Use the NECB prototype to create a model to test against. Alterantively we could load an osm file instead.
    model = create_necb_protype_model(
        "SmallOffice",
        'NECB HDD Method',
        'CAN_NT_Yellowknife.AP.719360_CWEC2016.epw',
        "NECB2015"
    )
	   
    # get arguments
    arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    runner = run_measure(@good_input_arguments, model)
    result = runner.result
    show_output(result)

    # test if the measure would grab the correct u value for the correct climate zone
    assert_equal(0.165, arguments[7].defaultValueAsDouble)
    end

  def create_necb_protype_model(building_type, climate_zone, epw_file, template)
    osm_directory = "#{File.dirname(__FILE__)}/output/#{building_type}-#{template}-#{climate_zone}-#{epw_file}"
    FileUtils.mkdir_p (osm_directory) unless Dir.exist?(osm_directory)
    #Get Weather climate zone from lookup
    weather = BTAP::Environment::WeatherFile.new(epw_file)
    #create model
    building_name = "#{template}_#{building_type}"
    puts "Creating #{building_name}"
    prototype_creator = Standard.build(template)
    model = prototype_creator.model_create_prototype_model(
        template: template,
        epw_file: epw_file,
        sizing_run_dir: osm_directory,
        debug: @debug,
        template: template,
        building_type: building_type)
    #set weather file to epw_file passed to model.
    weather.set_weather_file(model)
    return model
  end
  
 end

