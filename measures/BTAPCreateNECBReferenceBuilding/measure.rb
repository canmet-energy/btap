# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/
require_relative 'resources/BTAPMeasureHelper'
# start the measure

class NECB2011

  def model_modify_oa_controller(model)
    #do nothing
  end

  def model_reset_or_room_vav_minimum_damper(model, model1)
    #do nothing
  end

  def validate_initial_model(model)

    if model.getBuildingStorys.empty?
      OpenStudio.logFree(OpenStudio::Error, 'openstudio.model.Model', "Please assign Spaces to BuildingStorys in the geometry model.")
    end
    if model.getThermalZones.empty?
      OpenStudio.logFree(OpenStudio::Error, 'openstudio.model.Model', "Please assign Spaces to ThermalZones in the geometry model.")
    end
    if model.getBuilding.standardsNumberOfStories.empty?
      OpenStudio.logFree(OpenStudio::Error, 'openstudio.model.Model', "Please define Building.standardsNumberOfStories in the geometry model.")
    end
    if model.getBuilding.standardsNumberOfAboveGroundStories.empty?
      OpenStudio.logFree(OpenStudio::Error, 'openstudio.model.Model', "Please define Building.standardsNumberOfAboveStories in the geometry model.")
    end

    if @space_type_map.nil? || @space_type_map.empty?
      @space_type_map = get_space_type_maps_from_model(model)
      if @space_type_map.nil? || @space_type_map.empty?
        OpenStudio.logFree(OpenStudio::Error, 'openstudio.model.Model', "Please assign SpaceTypes in the geometry model or in standards database #{@space_type_map}.")
      else
        @space_type_map = @space_type_map.sort.to_h
        OpenStudio.logFree(OpenStudio::Info, 'openstudio.model.Model', "Loaded space type map from osm file")
      end
    end

    # ensure that model is intersected correctly.
    model.getSpaces.each {|space1| model.getSpaces.each {|space2| space1.intersectSurfaces(space2)}}
    # Get multipliers from TZ in model. Need this for HVAC contruction.
    @space_multiplier_map = {}
    model.getSpaces.sort.each do |space|
      @space_multiplier_map[space.name.get] = space.multiplier if space.multiplier > 1
    end
    OpenStudio.logFree(OpenStudio::Info, 'openstudio.model.Model', 'Finished adding geometry')
    unless @space_multiplier_map.empty?
      OpenStudio.logFree(OpenStudio::Info, 'openstudio.model.Model', "Found mulitpliers for space #{@space_multiplier_map}")
    end
    return model
  end

  def model_apply_standard_to_model(model, epw_file, sizing_run_dir = Dir.pwd, debug = false, measure_model = nil)
    climate_zone = 'NECB HDD Method'

    self.validate_initial_model(model)

    #Apply Climate and standard sizing and some housekeeping.
    model.yearDescription.get.setDayofWeekforStartDay('Sunday')
    model_add_design_days_and_weather_file(model, climate_zone, epw_file) # Standards
    model_add_ground_temperatures(model, nil, climate_zone) # prototype candidate
    model_apply_sizing_parameters(model)
    model.getOutputControlReportingTolerances.setToleranceforTimeHeatingSetpointNotMet(1.0)
    model.getOutputControlReportingTolerances.setToleranceforTimeCoolingSetpointNotMet(1.0)
    model_temp_fix_ems_references(model)
    model_modify_surface_convection_algorithm(model)


    #Apply Default Space Loads and Schedules
    model.getThermostatSetpointDualSetpoints(&:remove)
    model_add_loads(model) # standards candidate

    #Apply Infiltration Standard
    model_apply_infiltration_standard(model) # standards candidate

    #Apply Occupancy Sensor Standard
    set_occ_sensor_spacetypes(model, @space_type_map)

    # Apply Default Contruction Sets
    model_add_constructions(model, "NECB", climate_zone) # prototype candidate
    #Apply Standard construction Propeties
    apply_standard_construction_properties(model) # standards candidate

    #Apply Standard FDWR
    apply_standard_window_to_wall_ratio(model) # standards candidate

    #Apply Standard SRR
    apply_standard_skylight_to_roof_ratio(model) # standards candidate


    #Apply Default HVAC Systems.
    model_create_thermal_zones(model, @space_multiplier_map) # standards candidate
    raise("sizing run 0 failed!") if model_run_sizing_run(model, "#{sizing_run_dir}/SR0") == false
    OpenStudio.logFree(OpenStudio::Info, 'openstudio.model.Model', 'Started Adding HVAC')
    system_fuel_defaults = self.get_canadian_system_defaults_by_weatherfile_name(model)
    puts JSON.pretty_generate(system_fuel_defaults)
    raise('hell')
    necb_autozone_and_autosystem(model, nil, false, system_fuel_defaults)
    OpenStudio.logFree(OpenStudio::Info, 'openstudio.model.Model', 'Finished adding HVAC')

    raise("sizing run 1 failed!") if model_run_sizing_run(model, "#{sizing_run_dir}/SR1") == false
    model.getAirTerminalSingleDuctVAVReheats.each {|iobj| air_terminal_single_duct_vav_reheat_set_heating_cap(iobj)}
    model_apply_prototype_hvac_assumptions(model, nil, climate_zone)

    #Apply HVAC Standard
    model_apply_hvac_efficiency_standard(model, climate_zone)

    model_request_timeseries_outputs(model) if debug
    # If measure model is passed, then replace measure model with new model created here.
    if measure_model.nil?
      return model
    else
      model_replace_model(measure_model, model)
      return measure_model
    end
  end
end

class BTAPCreateNECBReferenceBuilding < OpenStudio::Measure::ModelMeasure

  attr_accessor :use_json_package, :use_string_double
  #Adds helper functions to make life a bit easier and consistent.
  include(BTAPMeasureHelper)
  # human readable name
  def name
    return "BTAPCreateNECBReferenceBuilding"
  end

  # human readable description
  def description
    return "This measure will take an osm file with NECB spacetypes and create a reference building for research purposes only. "
  end

  # human readable description of modeling approach
  def modeler_description
    return "This measure will selectively apply the rules of the NECB to a building."
  end

  #Use the constructor to set global variables
  def initialize()
    super()
    #Set to true if you want to package the arguments as json.
    @use_json_package = false
    #Set to true if you want to want to allow strings and doubles in stringdouble types. Set to false to force to use doubles. The latter is used for certain
    # continous optimization algorigthms. You may have to re-examine your input in PAT as this fundamentally changes the measure.
    @use_string_double = true

    # Put in this array of hashes all the input variables that you need in your measure. Your choice of types are Sting, Double,
    # StringDouble, and Choice. Optional fields are valid strings, max_double_value, and min_double_value. This will
    # create all the variables, validate the ranges and types you need,  and make them available in the 'run' method as a hash after
    # you run 'arguments = validate_and_get_arguments_in_hash(model, runner, user_arguments)'
    @measure_interface_detailed = [

        {
            "name" => "necb_standard",
            "type" => "Choice",
            "display_name" => "Select the NECB Standard that you wish to apply to your proposed model.",
            "default_value" => "NECB2011",
            "choices" => ["NECB2011", "NECB2015"],
            "is_required" => true
        },
        {
            "name" => "weather_file",
            "type" => "Choice",
            "display_name" => "Select the NECB Standard that you wish to apply to your proposed model.",
            "default_value" => 'CAN_AB_Banff.CS.711220_CWEC2016.epw',
            "choices" => ['CAN_AB_Banff.CS.711220_CWEC2016.epw', 'CAN_AB_Calgary.Intl.AP.718770_CWEC2016.epw', 'CAN_AB_Edmonton.Intl.AP.711230_CWEC2016.epw', 'CAN_AB_Edmonton.Stony.Plain.AP.711270_CWEC2016.epw', 'CAN_AB_Fort.McMurray.AP.716890_CWEC2016.epw', 'CAN_AB_Grande.Prairie.AP.719400_CWEC2016.epw', 'CAN_AB_Lethbridge.AP.712430_CWEC2016.epw', 'CAN_AB_Medicine.Hat.AP.710260_CWEC2016.epw', 'CAN_BC_Abbotsford.Intl.AP.711080_CWEC2016.epw', 'CAN_BC_Comox.Valley.AP.718930_CWEC2016.epw', 'CAN_BC_Crankbrook-Canadian.Rockies.Intl.AP.718800_CWEC2016.epw', 'CAN_BC_Fort.St.John-North.Peace.Rgnl.AP.719430_CWEC2016.epw', 'CAN_BC_Hope.Rgnl.Airpark.711870_CWEC2016.epw', 'CAN_BC_Kamloops.AP.718870_CWEC2016.epw', 'CAN_BC_Port.Hardy.AP.711090_CWEC2016.epw', 'CAN_BC_Prince.George.Intl.AP.718960_CWEC2016.epw', 'CAN_BC_Smithers.Rgnl.AP.719500_CWEC2016.epw', 'CAN_BC_Summerland.717680_CWEC2016.epw', 'CAN_BC_Vancouver.Intl.AP.718920_CWEC2016.epw', 'CAN_BC_Victoria.Intl.AP.717990_CWEC2016.epw', 'CAN_MB_Brandon.Muni.AP.711400_CWEC2016.epw', 'CAN_MB_The.Pas.AP.718670_CWEC2016.epw', 'CAN_MB_Winnipeg-Richardson.Intl.AP.718520_CWEC2016.epw', 'CAN_NB_Fredericton.Intl.AP.717000_CWEC2016.epw', 'CAN_NB_Miramichi.AP.717440_CWEC2016.epw', 'CAN_NB_Saint.John.AP.716090_CWEC2016.epw', 'CAN_NL_Gander.Intl.AP-CFB.Gander.718030_CWEC2016.epw', 'CAN_NL_Goose.Bay.AP-CFB.Goose.Bay.718160_CWEC2016.epw', 'CAN_NL_St.Johns.Intl.AP.718010_CWEC2016.epw', 'CAN_NL_Stephenville.Intl.AP.718150_CWEC2016.epw', 'CAN_NS_CFB.Greenwood.713970_CWEC2016.epw', 'CAN_NS_CFB.Shearwater.716010_CWEC2016.epw', 'CAN_NS_Sable.Island.Natl.Park.716000_CWEC2016.epw', 'CAN_NT_Inuvik-Zubko.AP.719570_CWEC2016.epw', 'CAN_NT_Yellowknife.AP.719360_CWEC2016.epw', 'CAN_ON_Armstrong.AP.718410_CWEC2016.epw', 'CAN_ON_CFB.Trenton.716210_CWEC2016.epw', 'CAN_ON_Dryden.Rgnl.AP.715270_CWEC2016.epw', 'CAN_ON_London.Intl.AP.716230_CWEC2016.epw', 'CAN_ON_Moosonee.AP.713980_CWEC2016.epw', 'CAN_ON_Mount.Forest.716310_CWEC2016.epw', 'CAN_ON_North.Bay-Garland.AP.717310_CWEC2016.epw', 'CAN_ON_Ottawa-Macdonald-Cartier.Intl.AP.716280_CWEC2016.epw', 'CAN_ON_Sault.Ste.Marie.AP.712600_CWEC2016.epw', 'CAN_ON_Timmins.Power.AP.717390_CWEC2016.epw', 'CAN_ON_Toronto.Pearson.Intl.AP.716240_CWEC2016.epw', 'CAN_ON_Windsor.Intl.AP.715380_CWEC2016.epw', 'CAN_PE_Charlottetown.AP.717060_CWEC2016.epw', 'CAN_QC_Kuujjuaq.AP.719060_CWEC2016.epw', 'CAN_QC_Kuujuarapik.AP.719050_CWEC2016.epw', 'CAN_QC_Lac.Eon.AP.714210_CWEC2016.epw', 'CAN_QC_Mont-Joli.AP.717180_CWEC2016.epw', 'CAN_QC_Montreal-Mirabel.Intl.AP.719050_CWEC2016.epw', 'CAN_QC_Montreal-St-Hubert.Longueuil.AP.713710_CWEC2016.epw', 'CAN_QC_Montreal-Trudeau.Intl.AP.716270_CWEC2016.epw', 'CAN_QC_Quebec-Lesage.Intl.AP.717140_CWEC2016.epw', 'CAN_QC_Riviere-du-Loup.717150_CWEC2016.epw', 'CAN_QC_Roberval.AP.717280_CWEC2016.epw', 'CAN_QC_Saguenay-Bagotville.AP-CFB.Bagotville.717270_CWEC2016.epw', 'CAN_QC_Schefferville.AP.718280_CWEC2016.epw', 'CAN_QC_Sept-Iles.AP.718110_CWEC2016.epw', 'CAN_QC_Val-d-Or.Rgnl.AP.717250_CWEC2016.epw', 'CAN_SK_Estevan.Rgnl.AP.718620_CWEC2016.epw', 'CAN_SK_North.Battleford.AP.718760_CWEC2016.epw', 'CAN_SK_Saskatoon.Intl.AP.718660_CWEC2016.epw', 'CAN_YT_Whitehorse.Intl.AP.719640_CWEC2016.epw'],
            "is_required" => true
        },
        {
            "name" => "hvac_charecteristics",
            "type" => "String",
            "display_name" => "A set to NA to use weather file location default assumptions, otherwise eneter the json data for each component you wish to not use the defaults. ",
            "default_value" => '{
                                  "boiler_fueltype": "NaturalGas",
                                  "baseboard_type": "Hot Water",
                                  "mau_type": true,
                                  "mau_heating_coil_type": "Hot Water",
                                  "mau_cooling_type": "DX",
                                  "chiller_type": "Scroll",
                                  "heating_coil_type_sys3": "Gas",
                                  "heating_coil_type_sys4": "Gas",
                                  "heating_coil_type_sys6": "Hot Water",
                                  "fan_type": "var_speed_drive",
                                  "swh_fueltype": "NaturalGas"
        }',
          "is_required" => true
        },


    ]
  end

  # define what happens when the measure is run
  def run(model, runner, user_arguments)
    #Runs parent run method.
    super(model, runner, user_arguments)
    # Gets arguments from interfaced and puts them in a hash with there display name. This also does a check on ranges to
    # ensure that the values inputted are valid based on your @measure_interface array of hashes.
    arguments = validate_and_get_arguments_in_hash(model, runner, user_arguments)
    #puts JSON.pretty_generate(arguments)
    return false if false == arguments

    #Set the standard to be used.
    Standard.build(arguments['necb_standard']).model_apply_standard_to_model(model, arguments['weather_file'])
    return true
  end


end


# register the measure to be used by the application
BTAPCreateNECBReferenceBuilding.new.registerWithApplication
