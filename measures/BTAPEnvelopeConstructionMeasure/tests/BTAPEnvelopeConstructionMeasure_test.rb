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
    @baseline = 'baseline'

    #Creating a data-driven measure. This is because there are a large amount of inputs to enter and test.. So creating
    # an array to work around is programmatically easier.
    @surface_index =[
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
    @good_input_arguments = {
        "outdoors_wall_conductance" => 3.5,
        "outdoors_roofceiling_conductance" => 3.5,
        "outdoors_floor_conductance" => 3.5,
        "ground_wall_conductance" => 3.5,
        "ground_roofceiling_conductance" => 3.5,
        "ground_floor_conductance" => 3.5,
        "outdoors_fixedwindow_conductance" => 3.5,
        "outdoors_operablewindow_conductance" => 3.5,
        "outdoors_skylight_conductance" => 3.5,
        "outdoors_tubulardaylightdiffuser_conductance" => 3.5,
        "outdoors_tubulardaylightdome_conductance" => 3.5,
        "outdoors_door_conductance" => 3.5,
        "outdoors_glassdoor_conductance" => 3.5,
        "outdoors_overheaddoor_conductance" => 3.5,
        "outdoors_fixedwindow_shgc" => 0.4,
        "outdoors_operablewindow_shgc" => 0.4,
        "outdoors_skylight_shgc" => 0.4,
        "outdoors_tubulardaylightdiffuser_shgc" => 0.4,
        "outdoors_tubulardaylightdome_shgc" => 0.4,
        "outdoors_glassdoor_shgc" => 0.4,
        "outdoors_fixedwindow_tvis" => 0.999,
        "outdoors_operablewindow_tvis" => 0.999,
        "outdoors_skylight_tvis" => 0.999,
        "outdoors_tubulardaylightdiffuser_tvis" => 0.999,
        "outdoors_tubulardaylightdome_tvis" => 0.999,
        "outdoors_glassdoor_tvis" => 0.999
    }

  end


  def test_envelope_changes()

    # Create an instance of the measure
    measure = get_measure_object()


    # Create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    # Use the NECB prototype to create a model to test against. Alterantively we could load an osm file instead.
    model = create_necb_protype_model(
        "LargeOffice",
        'NECB HDD Method',
        'CAN_BC_Vancouver.Intl.AP.718920_CWEC2016.epw',
        "NECB2011"
    )

    # Test arguments and defaults
    arguments = measure.arguments(model)

    # set argument values to values and run the measure
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)


    #Set up conductance test values to validate against. Make each unique to make each surface type distinct.
    values = {}
    conductance = 3.5
    (@surface_index + @sub_surface_index).each_with_index do |surface, index|
      name = "#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_conductance"
      argument = arguments[index].clone
      assert(argument.setValue(conductance.to_f))
      argument_map[name] = argument
      values[name] =conductance
    end

    conductance_argument_size = (@surface_index + @sub_surface_index).size
    #SHGC
    shgc = 0.244
    @sub_surface_index.select {|surface| surface['construction_type'] == "glazing"}.each_with_index do |surface, index|
      name = "#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_shgc"
      argument = arguments[conductance_argument_size + index].clone
      assert(argument.setValue(shgc.to_f))
      argument_map[name] = argument
      values[name] =shgc
    end

    #SHGC
    shgc_argument_size = @sub_surface_index.select {|surface| surface['construction_type'] == "glazing"}.size
    tvis = 0.999
    @sub_surface_index.select {|surface| surface['construction_type'] == "glazing"}.each_with_index do |surface, index|
      name = "#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_tvis"
      argument = arguments[conductance_argument_size + shgc_argument_size + index].clone
      assert(argument.setValue(tvis.to_f))
      argument_map[name] = argument
      values[name] =tvis
    end

    #run the measure
    measure.run(model, runner, argument_map)
    result = runner.result
    assert(result.value.valueName == 'Success')
    #Check that the conductances have indeed changed to what they should be.
    outdoor_surfaces = BTAP::Geometry::Surfaces::filter_by_boundary_condition(
        model.getSurfaces(),
        "Outdoors"
    )
    outdoor_subsurfaces = BTAP::Geometry::Surfaces::get_subsurfaces_from_surfaces(outdoor_surfaces)
    ground_surfaces = BTAP::Geometry::Surfaces::filter_by_boundary_condition(
        model.getSurfaces(),
        "Ground"
    )

    ext_windows = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(
        outdoor_subsurfaces,
        [
            "FixedWindow",
            "OperableWindow"]
    )

    ext_skylights = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(
        outdoor_subsurfaces,
        [
            "Skylight",
            "TubularDaylightDiffuser",
            "TubularDaylightDome"]
    )
    ext_doors = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(
        outdoor_subsurfaces,
        ["Door"]
    )

    ext_glass_doors = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(
        outdoor_subsurfaces,
        ["GlassDoor"]
    )
    ext_overhead_doors = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(
        outdoor_subsurfaces,
        ["OverheadDoor"]
    )

    #opaque surfaces
    opaque_surfaces = outdoor_surfaces + ext_doors +ext_overhead_doors + ground_surfaces
    opaque_surfaces.sort.each do |surface|
      name = "#{surface.outsideBoundaryCondition.downcase}_#{surface.surfaceType.downcase}_conductance"
      unless values[name] == @baseline
        assert_equal(
            values[name].to_f.round(3),
            BTAP::Geometry::Surfaces::get_surface_construction_conductance(surface).round(3)
        )
      end
    end

    #glazing subsurfaces
    glazing_subsurfaces = ext_windows + ext_glass_doors + ext_skylights
    glazing_subsurfaces.sort.each do |surface|
      cond_name = "#{surface.outsideBoundaryCondition.downcase}_#{surface.subSurfaceType.downcase}_conductance"
      shgc_name = "#{surface.outsideBoundaryCondition.downcase}_#{surface.subSurfaceType.downcase}_shgc"
      tvis_name = "#{surface.outsideBoundaryCondition.downcase}_#{surface.subSurfaceType.downcase}_tvis"
      assert_equal(values[cond_name].to_f.round(3), BTAP::Geometry::Surfaces::get_surface_construction_conductance(surface).round(3)) unless values[cond_name] == @baseline
      construction = OpenStudio::Model::getConstructionByName(surface.model, surface.construction.get.name.to_s).get
      assert_equal(values[shgc_name].to_f.round(3), construction.layers.first.to_SimpleGlazing.get.getSolarHeatGainCoefficient.value.round(3)) unless values[shgc_name] == @baseline
      construction = OpenStudio::Model::getConstructionByName(surface.model, surface.construction.get.name.to_s).get
      error_message = "Setting TVis for #{construction.name} to #{values[tvis_name].to_f.round(3)} failed. Actual is #{construction.layers.first.to_SimpleGlazing.get.getVisibleTransmittance.get.value}"
      assert_equal(values[tvis_name].to_f.round(3), construction.layers.first.to_SimpleGlazing.get.getVisibleTransmittance.get.value.round(3), error_message) unless values[tvis_name] == @baseline
    end
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
