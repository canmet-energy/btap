#require "#{File.dirname(__FILE__)}/resources/run_sizing"
require 'json'
require_relative 'resources/BTAPMeasureHelper'
require_relative 'resources/hvac_routines'

# =============================================================================================================================
# start the measure
class SetHeatPumpAirSystem < OpenStudio::Measure::ModelMeasure
  attr_accessor :use_json_package, :use_string_double

  include BTAPMeasureHelper
  include HVACRoutines

  # human readable name
  def name
    # Measure name should be the title case of the class name.
    return 'SetHeatPumpAirSystem'
  end

  # human readable description
  def description
    return 'Scan all air systems amd delete existing heating and cooling coils. Then add DX heating and cooling coils and supplemental heating electric coils for an air-source heat pump. The zonal heating units can either be deleted, left as is, or replaced with electric baseboards. Zonal cooling units can either be deleted or left as is in the model.'
  end

  # human readable description of modeling approach
  def modeler_description
    return 'A DX heating and cooling coils and supplemental electric coils are added to the air loop to model an air-source heat pump. Performance curves for the heat pump heating and cooling coils are read from file curves.json in the resources folder.'
  end

  def initialize()
    super()
	
    @use_json_package = false
    @use_string_double = false

    @measure_interface_detailed =
      { 
            "name" => "zone_htg_eqpt",
            "type" => "Choice",
            "display_name" => "Zone heating equipment",
            "default_value" => 'Electric Baseboard',
            "choices" => ['Keep Existing','Electric Baseboard','None'],
            "is_required" => false
      },
      { 
            "name" => "zone_clg_eqpt",
            "type" => "Choice",
            "display_name" => "Zone cooling equipment",
            "default_value" => 'Keep Existing',
            "choices" => ['Keep Existing','None'],
            "is_required" => false
      },
      { 
            "name" => "zone_term_reheat_eqpt",
            "type" => "Choice",
            "display_name" => "Zone terminal reheat equipment",
            "default_value" => 'Electric',
            "choices" => ['Keep Existing','Electric'],
            "is_required" => false
      },
      { 
            "name" => "htg_cop",
            "type" => "Double",
            "display_name" => "Heating COP",
            "default_value" => 0.0,
            "max_double_value" => 10.0,
            "min_double_value" => 0.0,
            "is_required" => true
      },
      { 
            "name" => "clg_cop",
            "type" => "Double",
            "display_name" => "Cooling COP",
            "default_value" => 0.0,
            "max_double_value" => 10.0,
            "min_double_value" => 0.0,
            "is_required" => true
      }
  end
  
  # define what happens when the measure is run
  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)
 
    # assign the user inputs to variables
    arguments = validate_and_get_arguments_in_hash(model, runner, user_arguments)
    return false if false == arguments

    # sizing factor for heat pump capacity
    air_sys_cap_siz_fr = 1.0  # fraction of design heating/cooling capacity of air system dx heating/cooling coils 

    # sizing factor baseboard
    baseboard_siz_fr = 1.0

    # type of zonal heating equipment
    zone_htg_eqpt = arguments['zone_htg_eqpt']

    # type of zonal cooling equipment
    zone_clg_eqpt = arguments['zone_clg_eqpt']

    # type of zonal terminal reheat equipment
    zone_term_reheat_eqpt = arguments['zone_term_reheat_eqpt']

    # heating COP
    htg_cop = arguments['htg_cop']

    # cooling COP
    clg_cop = arguments['clg_cop']

    # on-off schedules
    always_on = model.alwaysOnDiscreteSchedule
    always_off = model.alwaysOffDiscreteSchedule
 
    # get HVAC systems
    all_sys_objs = model.getAirLoopHVACs

    # scan HVAC systems and replace any existing system heating and cooling coils and fan with DX heating and cooling coils and electric heater
    setup_air_sys_variablespeed(model,all_sys_objs,zone_term_reheat_eqpt)

    # scan thermal zones and remove any zonal heating equipment and replace them with electric baseboards
    if zone_htg_eqpt == 'Electric Baseboard'
      remove_existing_htg_zone_units(model)
      setup_indoor_elec_baseboards(model)
    elsif zone_htg_eqpt == 'None'
      remove_existing_htg_zone_units(model)
    end

    # scan thermal zones and remove any zonal cooling equipment
    if zone_clg_eqpt == 'None'
      remove_existing_clg_zone_units(model)
    end

    # check for empty plant loops and remove them
    remove_empty_plt_loops(model)

    # perform sizing run
    model_run_sizing_run(model, sizing_run_dir = "#{Dir.pwd}/SR")

    # assign capacities to coils
    set_air_sys_variable_speed_cap(model,air_sys_cap_siz_fr)

    # use sizing information to set COPs
    set_air_sys_variable_speed_cop(model,htg_cop,clg_cop)

    # assign baseboard capacities
    if zone_htg_eqpt == 'Electric Baseboard'
      set_baseboard_cap(model,baseboard_siz_fr)
    end

    return true

  end
end

# register the measure to be used by the application
SetHeatPumpAirSystem.new.registerWithApplication
