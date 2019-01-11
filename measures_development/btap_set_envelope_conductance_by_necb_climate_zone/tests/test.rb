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
            "choices" => ["NECB2011", "NECB2015" , "NECB2017"],
            "is_required" => true
        },


        {
            "name" => "surface_type",
            "type" => "Choice",
            "display_name" => "Surface Type",
            "default_value" => "Walls",
            "choices" => ["Walls", "Roofs", "Glazing"],
            "is_required" => true
        },

        {
            "name" => "zone4_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone4 Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 31.03,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },

        {
            "name" => "zone5_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone5 Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 31.03,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
           "name" => "zone6_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone6 Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 35.05,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "zone7A_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone7A Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 35.05,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "zone7B_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone7B Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 39.99,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "zone8_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone8 Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 47.32,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        }

    ]

    @good_input_arguments = {
       "necb_template" => "NECB2015",
	     "surface_type" => "Walls",
       "zone4_r_value" => 31.03,
       "zone5_r_value" => 31.03,
       "zone6_r_value" => 35.05,
       "zone7A_r_value" => 35.05,
       "zone7B_r_value" => 39.99,
       "zone8_r_value" => 47.32
    }

  end

 def test_Zone4_conductane

    measure = BtapSetEnvelopeConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    #load model
    # model = create_model_by_local_osm_file('/EnvelopeAndLoadTestModel_01.osm')
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

    if assert_equal(31.03, arguments[2].defaultValueAsDouble)
    runner.registerInfo("Zone 4 ( Victoria), test r-value of 31.03  >>>>>>>>>>  is equal to :'#{arguments[2].defaultValueAsDouble}' .")
    else
    runner.registerInfo(" \e[33m Zone 4 ( Victoria), test r-value of 31.03  >>>>>>>>>>  is NOT equal to :'#{arguments[2].defaultValueAsDouble}' \e[0m.")
    end
 end


 def test_Zone5_conductane

    measure = BtapSetEnvelopeConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    #load model
    # model = create_model_by_local_osm_file('/EnvelopeAndLoadTestModel_01.osm')
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
    #assert_equal(zone5_r_value.to_f.round(3),31.03)

    assert_equal(31.03, arguments[3].defaultValueAsDouble)
    runner.registerInfo(" \e[32m Zone 5 (Windsor), test r value of 31.03   >>>>>>>>>>  is equal to :'#{arguments[3].defaultValueAsDouble}' \e[0m .")
  end


  def test_Zone6_conductane

    measure = BtapSetEnvelopeConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    #load model
    # model = create_model_by_local_osm_file('/EnvelopeAndLoadTestModel_01.osm')
    # Use the NECB prototype to create a model to test against. Alterantively we could load an osm file instead.
    model = create_necb_protype_model(
        "SmallOffice",
        'NECB HDD Method',
        'CAN_ON_Ottawa-Macdonald-Cartier.Intl.AP.716280_CWEC2016.epw',
        "NECB2015"
    )

    # get arguments
    arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    runner = run_measure(@good_input_arguments, model)
    result = runner.result
    show_output(result)

    assert_equal(35.05, arguments[4].defaultValueAsDouble)
    runner.registerInfo(" \e[32m Zone 6 (Ottawa), test r-value of 35.05   >>>>>>>>>>  is equal to :'#{arguments[4].defaultValueAsDouble}' \e[0m .")
  end

  def test_Zone7a_conductane

    measure = BtapSetEnvelopeConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    #load model
    # model = create_model_by_local_osm_file('/EnvelopeAndLoadTestModel_01.osm')
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

   assert_equal(35.05, arguments[5].defaultValueAsDouble)
   runner.registerInfo(" \e[32m Zone 7A (Edmonton), test r-value of 35.05   >>>>>>>>>>  is equal to :'#{arguments[5].defaultValueAsDouble}' \e[0m .")
	
  end

  def test_Zone7b_conductane

    measure = BtapSetEnvelopeConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    #load model
    # model = create_model_by_local_osm_file('/EnvelopeAndLoadTestModel_01.osm')
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

  assert_equal(39.99, arguments[6].defaultValueAsDouble)
  runner.registerInfo(" \e[32m Zone 7B (White-horse), test r-value of 39.99  >>>>>>>>>>  is equal to :'#{arguments[6].defaultValueAsDouble}' \e[0m .")
  end


  def test_Zone8_conductane

    measure = BtapSetEnvelopeConductanceByNecbClimateZone.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    #load model
    # model = create_model_by_local_osm_file('/EnvelopeAndLoadTestModel_01.osm')
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
    assert_equal(47.32, arguments[7].defaultValueAsDouble)
    runner.registerInfo(" \e[31m Zone 8 (Yellowknife), test r-value of 47.32    >>>>>>>>>>  is equal to :'#{arguments[7].defaultValueAsDouble}' \e[0m .")
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

