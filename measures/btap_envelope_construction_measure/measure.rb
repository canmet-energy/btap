# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/
require_relative 'resources/BTAPMeasureHelper'

# start the measure
class BTAPEnvelopeConstructionMeasure < OpenStudio::Measure::ModelMeasure
  attr_accessor :use_json_package, :use_string_double

  include(BTAPMeasureHelper)
  ### BTAP Measure helper methods.
  #  A wrapper for outputing feedback to users and developers.
  #  runner_register("InitialCondition",   "Your Information Message Here", runner)
  #  runner_register("Info",    "Your Information Message Here", runner)
  #  runner_register("Warning", "Your Information Message Here", runner)
  #  runner_register("Error",   "Your Information Message Here", runner)
  #  runner_register("Debug",   "Your Information Message Here", runner)
  #  runner_register("FinalCondition",   "Your Information Message Here", runner)
  #  @params type [String]
  #  @params runner [OpenStudio::Ruleset::OSRunner] # or a nil.
  def runner_register(runner, type, text)
    #dump to console if @debug is set to true
    puts "#{type.upcase}: #{text}" if @debug == true
    #dump to runner.
    if runner.is_a?(OpenStudio::Ruleset::OSRunner)
      case type.downcase
      when "info"
        runner.registerInfo(text)
      when "warning"
        runner.registerWarning(text)
      when "error"
        runner.registerError(text)
      when "notapplicable"
        runner.registerAsNotApplicable(text)
      when "finalcondition"
        runner.registerFinalCondition(text)
      when "initialcondition"
        runner.registerInitialCondition(text)
      when "debug"
      when "macro"
      else
        raise("Runner Register type #{type.downcase} not info,warning,error,notapplicable,finalcondition,initialcondition,macro.")
      end
    end
  end


  def runner_register_value(runner, name, value)
    if runner.is_a?(OpenStudio::Ruleset::OSRunner)
      runner.registerValue(name, value.to_s)
      BTAP::runner_register("Info", "#{name} = #{value} has been registered in the runner", runner)
    end
  end

  #Constructor to set global variables
  def initialize()
    super()
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

    # Climate Zone Filter

    @measure_interface_detailed << {
        "name" => "apply_to_climate_zone",
        "type" => "Choice",
        "display_name" => "Apply Only to Climate Zone",
        "default_value" => "all",
        "choices" => @necb_climate_zones.map {|cz| cz[:name]},
        "is_required" => true
    }

  end

  # human readable name
  def name
    return "BTAPEnvelopeConstructionMeasureDetailed"
  end

  # human readable description
  def description
    return "Changes exterior wall construction's thermal conductances, Visible Transmittance and SHGC where application for each surface type."
  end

  # human readable description of modeling approach
  def modeler_description
    return "Changes exterior wall construction's thermal conductances, Visible Transmittance and SHGC where application for each surface type."
  end

  # define what happens when the measure is run
  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)
    standard = Standard.build('NECB2015')
    necb_hdd18 = standard.get_necb_hdd18(model)
    runner.registerError("Couldn't find a hdd18 for weather file.") if necb_hdd18.nil?
    runner.registerInfo("The Weather File NECB hdd is '#{necb_hdd18}'.")
    arguments = validate_and_get_arguments_in_hash(model, runner, user_arguments)

    return false if arguments == false
    #apply_to_climate_zone = arguments['apply_to_climate_zone']
    # Find the climate zone according to the NECB hdds, then find the corresponding u-value of that climate zone.

    climate_zone = @necb_climate_zones.detect {|zone| zone[:min_hdd] <= necb_hdd18 and necb_hdd18 < zone[:max_hdd]}
    if climate_zone.nil?
      runner.registerError("Couldn't find a climate zone. For #{necb_hdd18}") if climate_zone.nil?
      raise("Couldn't find a climate zone. for #{necb_hdd18}")
    end

    #Only if the any climate zone is selected.. or the climate zone of the model matches the user selected climate zone will
    # the measure do anything.
    if arguments['apply_to_climate_zone'] == 'all' or arguments['apply_to_climate_zone'] == climate_zone[:name]
    # Make a copy of the model before the measure is applied.

      #save original conductances
      original = get_envelope_average_charecteristics(model)
      unless arguments['fdwr_lim'].nil?
        #Apply the max fdwr..this will sadly default to the NECB2015 window conductances.
        standard.apply_max_fdwr_nrcan(model: model, fdwr_lim: arguments['fdwr_lim'].to_f)
        # This will re apply the average window conductances to the new windows. ( SHould do this for doors. too...)
        standard.change_construction_properties_in_model(model, {"outdoors_fixedwindow_conductance" =>original["outdoors_fixedwindow_conductance" ] }, false)
      end
      unless arguments['srr_lim'].nil?
        #see above...same idea.
        standard.apply_max_srr_nrcan(model: model, srr_lim: arguments['srr_lim'].to_f)
        standard.change_construction_properties_in_model(model, {"outdoors_skylight_conductance" =>original["outdoors_skylight_conductance" ] }, false)
      end
      #Make the conducance changes contained in the arguments.
      report = standard.change_construction_properties_in_model(model, arguments, @use_percentages)


      runner_register(runner,
                      'FinalCondition',
                      report)
    else
      runner.registerAsNotApplicable("Measure does not apply since filtering based on only climate zone #{arguments['apply_to_climate_zone']} and current model is in #{climate_zone} ")
    end
    return true
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

end


# register the measure to be used by the application
BTAPEnvelopeConstructionMeasure.new.registerWithApplication
