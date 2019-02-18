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


class BTAPEnvelopeConstructionMeasure_Test < Minitest::Test
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
    @baseline = nil
    if @use_string_double
      @baseline = '-999'
    else
      @baseline = -999
    end

    #Creating a data-driven measure. This is because there are a large amount of inputs to enter and test.. So creating
    # an array to work around is programmatically easier.
    @necb_climate_zones = [
        {name: "zone_4", min_hdd: 0.0, max_hdd: 3000.0, epw_file: 'CAN_BC_Victoria.Intl.AP.717990_CWEC2016.epw'},
        {name: "zone_5", min_hdd: 3000.0, max_hdd: 4000.0, epw_file: 'CAN_ON_Windsor.Intl.AP.715380_CWEC2016.epw'},
        {name: "zone_6", min_hdd: 4000.0, max_hdd: 5000.0, epw_file: 'CAN_QC_Montreal-Trudeau.Intl.AP.716270_CWEC2016.epw'},
        {name: "zone_7a", min_hdd: 5000.0, max_hdd: 6000.0, epw_file: 'CAN_AB_Edmonton.Intl.AP.711230_CWEC2016.epw'},
        {name: "zone_7b", min_hdd: 6000.0, max_hdd: 7000.0, epw_file: 'CAN_YT_Whitehorse.Intl.AP.719640_CWEC2016.epw'},
        {name: "zone_8", min_hdd: 7000.0, max_hdd: 100000.0, epw_file: 'CAN_NT_Yellowknife.AP.719360_CWEC2016.epw'},
        {name: "all", min_hdd: 0.0, max_hdd: 100000.0, epw_file: 'CAN_NT_Yellowknife.AP.719360_CWEC2016.epw'}
    ]

    #Creating a data-driven measure. This is because there are a large amount of inputs to enter and test.. So creating
    # an array to work around is programmatically easier.
    @surface_index = [
        {"boundary_condition" => "Outdoors", "construction_type" => "opaque", "surface_type" => "Wall"},
        {"boundary_condition" => "Outdoors", "construction_type" => "opaque", "surface_type" => "RoofCeiling"},
        {"boundary_condition" => "Outdoors", "construction_type" => "opaque", "surface_type" => "Floor"},
        {"boundary_condition" => "Ground", "construction_type" => "opaque", "surface_type" => "Wall"},
        {"boundary_condition" => "Ground", "construction_type" => "opaque", "surface_type" => "RoofCeiling"},
        {"boundary_condition" => "Ground", "construction_type" => "opaque", "surface_type" => "Floor"}
    ]

    @sub_surface_index = [
        {"boundary_condition" => "Outdoors", "construction_type" => "glazing", "surface_type" => "FixedWindow"},
        {"boundary_condition" => "Outdoors", "construction_type" => "glazing", "surface_type" => "OperableWindow"},
        {"boundary_condition" => "Outdoors", "construction_type" => "glazing", "surface_type" => "Skylight"},
        {"boundary_condition" => "Outdoors", "construction_type" => "glazing", "surface_type" => "TubularDaylightDiffuser"},
        {"boundary_condition" => "Outdoors", "construction_type" => "glazing", "surface_type" => "TubularDaylightDome"},
        {"boundary_condition" => "Outdoors", "construction_type" => "opaque", "surface_type" => "Door"},
        {"boundary_condition" => "Outdoors", "construction_type" => "glazing", "surface_type" => "GlassDoor"},
        {"boundary_condition" => "Outdoors", "construction_type" => "opaque", "surface_type" => "OverheadDoor"}
    ]


    conductance_units = "Conductance (W/m2 K)"
    shgc_units = ""
    tvis_units = ""
    max_conductance_value = 5.0
    min_conductance_value = 0.005
    max_shgc_value = 1.0
    min_shgc_value = 0.0
    max_tvis_value = 1.0
    min_tvis_value = 0.0


    if @use_percentages
      conductance_units = "Percent Change (%)"
      shgc_units = "Percent Change (%)"
      tvis_units = "Percent Change (%)"
      max_conductance_value = 10000.0
      min_conductance_value = -10000.0
      max_shgc_value = 10000.0
      min_shgc_value = -10000.0
      max_tvis_value = 10000.0
      min_tvis_value = -10000.0
    end

    @measure_interface_detailed = []


    #Conductances
    (@surface_index + @sub_surface_index).each do |surface|
      @measure_interface_detailed << {
          "name" => "#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_conductance",
          "type" => "StringDouble",
          "display_name" => "#{surface['boundary_condition']} #{surface['surface_type']} #{conductance_units}",
          "default_value" => @baseline,
          "max_double_value" => max_conductance_value,
          "min_double_value" => min_conductance_value,
          "valid_strings" => [@baseline],
          "is_required" => false
      }
    end


=begin
    # SHGC
    @sub_surface_index.select {|surface| surface['construction_type'] == "glazing"}.each do |surface|
      @measure_interface_detailed << {
          "name" => "#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_shgc",
          "type" => "StringDouble",
          "display_name" => "#{surface['boundary_condition']} #{surface['surface_type']} #{shgc_units}",
          "default_value" => @baseline,
          "max_double_value" => max_shgc_value,
          "min_double_value" => min_shgc_value,
          "valid_strings" => [@baseline],
          "is_required" => false
      }
    end

    # Visible Transmittance
    @sub_surface_index.select {|surface| surface['construction_type'] == "glazing"}.each do |surface|
      @measure_interface_detailed << {
          "name" => "#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_tvis",
          "type" => "StringDouble",
          "display_name" => "#{surface['boundary_condition']} #{surface['surface_type']} Visible Transmittance #{tvis_units}",
          "default_value" => @baseline,
          "max_double_value" => max_tvis_value,
          "min_double_value" => min_tvis_value,
          "valid_strings" => [@baseline],
          "is_required" => false
      }
    end
=end


    @measure_interface_detailed << {
        "name" => "fdwr_lim",
        "type" => "StringDouble",
        "display_name" => "Fenestration Door to Wall Ratio",
        "default_value" => @baseline,
        "max_double_value" => 1.0,
        "min_double_value" => 0.0,
        "valid_strings" => [@baseline],
        "is_required" => false
    }

    @measure_interface_detailed << {
        "name" => "srr_lim",
        "type" => "StringDouble",
        "display_name" => "Skylight to Roof Ratio",
        "default_value" => @baseline,
        "max_double_value" => 1.0,
        "min_double_value" => 0.0,
        "valid_strings" => [@baseline],
        "is_required" => false
    }

    @measure_interface_detailed << {
        "name" => "apply_to_climate_zone",
        "type" => "Choice",
        "display_name" => "Apply Only to Climate Zone",
        "default_value" => "all",
        "choices" => @necb_climate_zones.map {|cz| cz[:name]},
        "is_required" => true
    }


    @good_input_arguments = {
        "outdoors_wall_conductance" => -999,
        "outdoors_roofceiling_conductance" => 3.2,
        "outdoors_floor_conductance" => 3.3,
        "ground_wall_conductance" => 3.4,
        "ground_roofceiling_conductance" => 3.5,
        "ground_floor_conductance" => 3.6,
        "outdoors_fixedwindow_conductance" => 1.4,
        "outdoors_operablewindow_conductance" => 3.8,
        "outdoors_skylight_conductance" => 3.9,
        "outdoors_tubulardaylightdiffuser_conductance" => 4.0,
        "outdoors_tubulardaylightdome_conductance" => 4.1,
        "outdoors_door_conductance" => 4.2,
        "outdoors_glassdoor_conductance" => 4.3,
        "outdoors_overheaddoor_conductance" => 4.4,
=begin
        "outdoors_fixedwindow_shgc" => 0.24,
        "outdoors_operablewindow_shgc" => 0.25,
        "outdoors_skylight_shgc" => 0.26,
        "outdoors_tubulardaylightdiffuser_shgc" => 0.27,
        "outdoors_tubulardaylightdome_shgc" => 0.28,
        "outdoors_glassdoor_shgc" => 0.29,
        "outdoors_fixedwindow_tvis" => 0.990,
        "outdoors_operablewindow_tvis" => 0.980,
        "outdoors_skylight_tvis" => 0.999,
        "outdoors_tubulardaylightdiffuser_tvis" => 0.970,
        "outdoors_tubulardaylightdome_tvis" => 0.960,
        "outdoors_glassdoor_tvis" => 0.959,
=end
        "fdwr_lim" => 0.50,
        "srr_lim" => 0.03,
        "apply_to_climate_zone" => 'all'
    }

  end

  def get_envelope_average_charecteristics(model)
    envelope_charecteristics = {}
    #Check that the conductances have indeed changed to what they should be.
    @surface_index.each do |surface|
      name = "#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_conductance"
      boundary_surfaces = BTAP::Geometry::Surfaces::filter_by_boundary_condition(model.getSurfaces(), surface['boundary_condition'])
      surfaces = BTAP::Geometry::Surfaces::filter_by_surface_types(boundary_surfaces, surface['surface_type'])
        if surfaces.size > 0
          envelope_charecteristics[name] = BTAP::Geometry::Surfaces::get_weighted_average_surface_conductance(surfaces).round(4)
        end
    end

    #Glazed surfaces
    @sub_surface_index.select {|item| item['construction_type'] == 'glazing'}.each do |surface|
      cond_name = "#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_conductance"
      boundary_surfaces = BTAP::Geometry::Surfaces::filter_by_boundary_condition(model.getSurfaces(), surface['boundary_condition'])
      sub_surfaces_all = BTAP::Geometry::Surfaces::get_subsurfaces_from_surfaces(boundary_surfaces)
      sub_surfaces = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(sub_surfaces_all, surface['surface_type'])
      if sub_surfaces.size > 0
        envelope_charecteristics[cond_name] = BTAP::Geometry::Surfaces::get_weighted_average_surface_conductance(sub_surfaces).round(4)
      end
    end
    return envelope_charecteristics
  end

  def dont_test_baseline_values()
    input_arguments = {
        "outdoors_wall_conductance" => @baseline,
        "outdoors_roofceiling_conductance" => @baseline,
        "outdoors_floor_conductance" => @baseline,
        "ground_wall_conductance" => @baseline,
        "ground_roofceiling_conductance" => @baseline,
        "ground_floor_conductance" => @baseline,
        "outdoors_fixedwindow_conductance" => @baseline,
        "outdoors_operablewindow_conductance" => @baseline,
        "outdoors_skylight_conductance" => @baseline,
        "outdoors_tubulardaylightdiffuser_conductance" => @baseline,
        "outdoors_tubulardaylightdome_conductance" => @baseline,
        "outdoors_door_conductance" => @baseline,
        "outdoors_glassdoor_conductance" => @baseline,
        "outdoors_overheaddoor_conductance" => @baseline,
=begin
        "outdoors_fixedwindow_shgc" => 0.24,
        "outdoors_operablewindow_shgc" => 0.25,
        "outdoors_skylight_shgc" => 0.26,
        "outdoors_tubulardaylightdiffuser_shgc" => 0.27,
        "outdoors_tubulardaylightdome_shgc" => 0.28,
        "outdoors_glassdoor_shgc" => 0.29,
        "outdoors_fixedwindow_tvis" => 0.990,
        "outdoors_operablewindow_tvis" => 0.980,
        "outdoors_skylight_tvis" => 0.999,
        "outdoors_tubulardaylightdiffuser_tvis" => 0.970,
        "outdoors_tubulardaylightdome_tvis" => 0.960,
        "outdoors_glassdoor_tvis" => 0.959,
=end
        "fdwr_lim" => 0.50,
        "srr_lim" => 0.03,
        "apply_to_climate_zone" => 'all'
    }
    envelope_changes(input_arguments)

  end


  def dont_test_envelope_changes()
    input_arguments = @good_input_arguments
    actual_results = nil
    # Use the NECB prototype to create a model to test against. Alterantively we could load an osm file instead.
    envelope_changes(input_arguments)
  end

  def envelope_changes(input_arguments)
    model = create_necb_protype_model(
        "FullServiceRestaurant",
        'NECB HDD Method',
        'CAN_BC_Vancouver.Intl.AP.718920_CWEC2016.epw',
        "NECB2011"
    )

    baseline_envelope_charecteristics = get_envelope_average_charecteristics(model)
    # Create an instance of the measure and run it...
    measure = get_measure_object()
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)
    # Test arguments and defaults
    arguments = measure.arguments(model)
    # set argument values to values and run the measure
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    #if json mode is turned on.
    input_arguments = {'json_input' => JSON.pretty_generate(input_arguments)} if @use_json_package
    runner = run_measure(input_arguments, model)
    assert(runner.result.value.valueName == 'NA' || runner.result.value.valueName == 'Success', show_output(runner.result))
    # Get report of model after the measure.
    actual_results = get_envelope_average_charecteristics(model)
    #test that the results are what we inputted into the model.
    errors = []
    actual_results.each_key do |key|
      if input_arguments[key] == @baseline
        #if set to baseline, then the value should be what was already in the model.
        errors << "#{key} for #{@baseline}, but changed to #{actual_results[key]}" unless baseline_envelope_charecteristics[key] == actual_results[key]
      else
        # Otherwise it should be what was inputted.
        errors << "#{key} called for #{input_arguments[key]}, but changed to #{actual_results[key]}" unless input_arguments[key] == actual_results[key]
      end
    end
    #Asset there are no errors...otherwise print errors.
    assert(errors.size == 0, JSON.pretty_generate(errors))
  end

  def test_climate_zone_all_applied()
    #this test will ensure that the climate zone is applied when selected.
    # Create an instance of the measure
    measure = get_measure_object()
    model = create_necb_protype_model(
        "FullServiceRestaurant",
        'NECB HDD Method',
        'CAN_QC_Kuujjuaq.AP.719060_CWEC2016.epw',
        "NECB2011"
    )

    # Test arguments and defaults
    arguments = measure.arguments(model)
    # set argument values to values and run the measure
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    input_arguments = @good_input_arguments.clone
    #set to apply to all climate zones which is last in the @necb_climate_zones array.
    input_arguments["apply_to_climate_zone"] = @necb_climate_zones.last[:name]
    input_arguments = {'json_input' => JSON.pretty_generate(input_arguments)} if @use_json_package
    runner = run_measure(input_arguments, model)
    assert(runner.result.value.valueName == 'Success', "Measure failed to run with apply_to_climate_zone set to climate zone 4. Returned #{runner.result.value.valueName} ")
  end

  def dont_test_climate_zone_applied()
    #this test will ensure that the climate zone is applied when selected.
    # Create an instance of the measure
    measure = get_measure_object()
    model = create_necb_protype_model(
        "FullServiceRestaurant",
        'NECB HDD Method',
        'CAN_ON_Windsor.Intl.AP.715380_CWEC2016.epw',
        "NECB2011"
    )

    # Test arguments and defaults
    arguments = measure.arguments(model)
    # set argument values to values and run the measure
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    input_arguments = @good_input_arguments.clone
    #set to apply to climate zone 4 which is zero in the @necb_climate_zones array.
    input_arguments["apply_to_climate_zone"] = @necb_climate_zones[2][:name]
    input_arguments = {'json_input' => JSON.pretty_generate(input_arguments)} if @use_json_package
    runner = run_measure(input_arguments, model)
    assert(runner.result.value.valueName == 'Success', "Measure failed to run with apply_to_climate_zone set to climate zone 4. Returned #{runner.result.value.valueName} ")
  end


  def dont_test_climate_zone_not_applied()
    #this test will ensure that the climate zone is applied when not selected.
    # Create an instance of the measure
    measure = get_measure_object()
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)
    model = create_necb_protype_model(
        "FullServiceRestaurant",
        'NECB HDD Method',
        'CAN_BC_Vancouver.Intl.AP.718920_CWEC2016.epw',
        "NECB2011"
    )

    # Test arguments and defaults
    arguments = measure.arguments(model)
    # set argument values to values and run the measure
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    input_arguments = @good_input_arguments.clone
    #set to apply to climate zone 4 which is zero in the @necb_climate_zones array.
    input_arguments["apply_to_climate_zone"] = @necb_climate_zones[2][:name]
    input_arguments = {'json_input' => JSON.pretty_generate(input_arguments)} if @use_json_package
    runner = run_measure(input_arguments, model)
    assert(runner.result.value.valueName == 'NA', "Measure should Not be Applicable since CAN_BC_Vancouver.Intl.AP.718920_CWEC2016.epw is not in #{@necb_climate_zones[2][:name]} . ")
  end


  def dont_test_fdwr_applied()
    standard = Standard.build('NECB2011')
    # This test will ensrue that the fdwr is set to the model
    fdwr_lim = 0.20
    # Create an instance of the measure
    measure = get_measure_object()
    model = create_necb_protype_model(
        "FullServiceRestaurant",
        'NECB HDD Method',
        'CAN_ON_Windsor.Intl.AP.715380_CWEC2016.epw',
        "NECB2011"
    )

    # Test arguments and defaults
    arguments = measure.arguments(model)
    # set argument values to values and run the measure
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    input_arguments = @good_input_arguments.clone
    #set to apply to climate zone 4 which is zero in the @necb_climate_zones array.
    input_arguments["fdwr_lim"] = fdwr_lim
    input_arguments = {'json_input' => JSON.pretty_generate(input_arguments)} if @use_json_package
    runner = run_measure(input_arguments, model)
    assert(runner.result.value.valueName == 'Success', "Measure did not complete sucessfully. Returned #{runner.result.value.valueName} ")
    result_fdwr = standard.find_exposed_conditioned_vertical_surfaces(model)['fdwr']
    assert( result_fdwr.round(2) == fdwr_lim.round(2), "FDWR was NOT set: Expected FDWR == #{fdwr_lim} instead got #{result_fdwr} ")
  end

  def dont_test_fdwr_not_applied()
    standard = Standard.build('NECB2011')
    # This test will ensrue that the fdwr is set to the model
    fdwr_lim = @baseline
    # Create an instance of the measure
    measure = get_measure_object()
    model = create_necb_protype_model(
        "FullServiceRestaurant",
        'NECB HDD Method',
        'CAN_ON_Windsor.Intl.AP.715380_CWEC2016.epw',
        "NECB2011"
    )

    # Test arguments and defaults
    arguments = measure.arguments(model)
    before_fdwr = standard.find_exposed_conditioned_vertical_surfaces(model)['fdwr']
    # set argument values to values and run the measure
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    input_arguments = @good_input_arguments.clone
    #set to apply to climate zone 4 which is zero in the @necb_climate_zones array.
    input_arguments["fdwr_lim"] = fdwr_lim
    input_arguments = {'json_input' => JSON.pretty_generate(input_arguments)} if @use_json_package
    runner = run_measure(input_arguments, model)
    assert(runner.result.value.valueName == 'Success', "Measure did not complete sucessfully. Returned #{runner.result.value.valueName} ")
    result_fdwr = standard.find_exposed_conditioned_vertical_surfaces(model)['fdwr']
    assert( result_fdwr.round(2) == before_fdwr.round(2), "FDWR was NOT set: Expected FDWR == #{before_fdwr} instead got #{result_fdwr} ")
  end

  def dont_test_srr_not_applied()
    standard = Standard.build('NECB2011')
    # This test will ensrue that the fdwr is set to the model
    srr_lim = @baseline
    # Create an instance of the measure
    measure = get_measure_object()
    model = create_necb_protype_model(
        "RetailStripmall",
        'NECB HDD Method',
        'CAN_ON_Windsor.Intl.AP.715380_CWEC2016.epw',
        "NECB2011"
    )

    # Test arguments and defaults
    arguments = measure.arguments(model)
    before_srr = standard.find_exposed_conditioned_roof_surfaces(model)['srr']
    # set argument values to values and run the measure
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    input_arguments = @good_input_arguments.clone
    #set to apply to climate zone 4 which is zero in the @necb_climate_zones array.
    input_arguments["srr_lim"] = srr_lim
    input_arguments = {'json_input' => JSON.pretty_generate(input_arguments)} if @use_json_package
    runner = run_measure(input_arguments, model)
    assert(runner.result.value.valueName == 'Success', "Measure did not complete sucessfully. Returned #{runner.result.value.valueName} ")
    result_srr = standard.find_exposed_conditioned_roof_surfaces(model)['srr']
    assert( result_srr.round(2) == before_srr.round(2), "SRR was NOT set: Expected SRR == #{before_srr} instead got #{result_srr} ")
  end


  def dont_test_srr_applied()
    standard = Standard.build('NECB2011')
    # This test will ensrue that the fdwr is set to the model
    srr_lim = 0.30
    # Create an instance of the measure
    measure = get_measure_object()
    model = create_necb_protype_model(
        "RetailStripmall",
        'NECB HDD Method',
        'CAN_ON_Windsor.Intl.AP.715380_CWEC2016.epw',
        "NECB2011"
    )

    # Test arguments and defaults
    arguments = measure.arguments(model)
    # set argument values to values and run the measure
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    input_arguments = @good_input_arguments.clone
    #set to apply to climate zone 4 which is zero in the @necb_climate_zones array.
    input_arguments["srr_lim"] = srr_lim
    input_arguments = {'json_input' => JSON.pretty_generate(input_arguments)} if @use_json_package
    runner = run_measure(input_arguments, model)
    assert(runner.result.value.valueName == 'Success', "Measure did not complete sucessfully. Returned #{runner.result.value.valueName} ")
    result_srr = standard.find_exposed_conditioned_roof_surfaces(model)['srr']
    assert( result_srr.round(2) == srr_lim.round(2), "SRR was NOT set: Expected SRR == #{srr_lim} instead got #{result_srr} ")
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
        building_type: building_type)
    #set weather file to epw_file passed to model.
    weather.set_weather_file(model)
    return model
  end
end
