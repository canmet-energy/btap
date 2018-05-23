#see the URL below for information on how to write OpenStudio measures
# http://openstudio.nrel.gov/openstudio-measure-writing-guide

#see the URL below for information on using life cycle cost objects in OpenStudio
# http://openstudio.nrel.gov/openstudio-life-cycle-examples

#see the URL below for access to C++ documentation on model objects (click on "model" in the main window to view model objects)
# http://openstudio.nrel.gov/sites/openstudio.nrel.gov/files/nv_data/cpp_documentation_it/model/html/namespaces.html

#load OpenStudio measure libraries
#require "#{File.dirname(__FILE__)}/resources/OsLib_AedgMeasures"
require "#{File.dirname(__FILE__)}/resources/OsLib_HelperMethods"
require "#{File.dirname(__FILE__)}/resources/OsLib_HVAC"
require "#{File.dirname(__FILE__)}/resources/OsLib_Schedules"

#start the measure
class ChilledBeamwithDOAS < OpenStudio::Ruleset::ModelUserScript

  #define the name that a user will see, this method may be deprecated as
  #the display name in PAT comes from the name field in measure.xml
  def name
    return "Chilled Beam with DOAS"
  end

  #define the arguments that the user will input
  def arguments(model)
    args = OpenStudio::Ruleset::OSArgumentVector.new

    # create an argument for a space type to be used in the model, to see if one should be mapped as ceiling return air plenum
    spaceTypes = model.getSpaceTypes
    usedSpaceTypes_handle = OpenStudio::StringVector.new
    usedSpaceTypes_displayName = OpenStudio::StringVector.new
    spaceTypes.each do |spaceType|  #todo - I need to update this to use helper so GUI sorts by display name
      if spaceType.spaces.size > 0 # only show space types used in the building
        usedSpaceTypes_handle << spaceType.handle.to_s
        usedSpaceTypes_displayName << spaceType.name.to_s
      end
    end
	
    # make an argument for space type
    ceilingReturnPlenumSpaceType = OpenStudio::Ruleset::OSArgument::makeChoiceArgument("ceilingReturnPlenumSpaceType", usedSpaceTypes_handle, usedSpaceTypes_displayName,false)
    ceilingReturnPlenumSpaceType.setDisplayName("This space type should be part of a ceiling return air plenum.")
    #ceilingReturnPlenumSpaceType.setDefaultValue("We don't want a default, this is an optional argument")
    args << ceilingReturnPlenumSpaceType
	
    # make a list of space types that will be changed
		spaceTypes = model.getSpaceTypes
		spaceTypes.each do |spaceType|
			if spaceType.spaces.size > 0
				space_type_to_edit = OpenStudio::Ruleset::OSArgument::makeBoolArgument(spaceType.name.get.to_s,true)
				#make a bool argument for each space type
				space_type_to_edit.setDisplayName("Add #{spaceType.name.get} space type to Chilled Beam system?")
				space_type_to_edit.setDefaultValue(false)		
				args << space_type_to_edit
			end
		end
		
		#Chilled Beam Type
		beamChs = OpenStudio::StringVector.new
		beamChs << "Active"
		beamChs << "Passive"
		chilled_beam_type = OpenStudio::Ruleset::OSArgument::makeChoiceArgument("chilled_beam_type",beamChs,true)
		chilled_beam_type.setDisplayName("Chilled Beam Type")
		chilled_beam_type.setDefaultValue("Passive")
		args << chilled_beam_type
		
		#Zone Heating Type
		heatChs = OpenStudio::StringVector.new
		heatChs << "Baseboard"
		heatChs << "Radiant Floors"
		heating_type = OpenStudio::Ruleset::OSArgument::makeChoiceArgument("heating_type",heatChs,true)
		heating_type.setDisplayName("Zone Heating Type")
		heating_type.setDefaultValue("Baseboard")
		args << heating_type
		
		# Boiler Efficiency
		boilerEff = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("boilerEff",false)
		boilerEff.setDisplayName("Boiler Thermal Efficiency")
		boilerEff.setDefaultValue(0.9)
		args << boilerEff
		
		# Boiler fuel Type
		fuelChs = OpenStudio::StringVector.new
		fuelChs << "NaturalGas"
		fuelChs << "PropaneGas"
		fuelChs << "FuelOil#1"
		fuelChs << "FuelOil#2"
		fuelChs << "Electricity"
		boilerFuelType =  OpenStudio::Ruleset::OSArgument::makeChoiceArgument("boilerFuelType",fuelChs,false) 
		boilerFuelType.setDisplayName("Boiler Fuel Type")
		boilerFuelType.setDefaultValue("NaturalGas")
		args << boilerFuelType

		# boiler Hot water supply temperature
		boilerHWST = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("boilerHWST",false)
		boilerHWST.setDisplayName("Boiler Design Heating Water Outlet Temperature (F)")
		boilerHWST.setDefaultValue(140)	
		args << boilerHWST
		
		# Hot water loop supply temp
		hw_loop_temp = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("hw_loop_temp",false)
		hw_loop_temp.setDisplayName("How Water Loop Temperature (F)")
		hw_loop_temp.setDefaultValue(140)	
		args << hw_loop_temp

		
		# Chiller COP
		chiller_cop = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("chiller_cop",false)
		chiller_cop.setDisplayName("Chiller COP")
		chiller_cop.setDefaultValue(3.0)
		args << chiller_cop
		
		#Chiller condenser type
		chiller_condenser_chs = OpenStudio::StringVector.new
		chiller_condenser_chs << "AirCooled"
		chiller_condenser_chs << "WaterCooled"
		chiller_condenser =  OpenStudio::Ruleset::OSArgument::makeChoiceArgument("chiller_condenser",chiller_condenser_chs,false) 
		chiller_condenser.setDisplayName("Chiller Condenser Type")
		chiller_condenser.setDefaultValue("AirCooled")
		args << chiller_condenser

		#Chiller design water outlet temp
		chillerCHWST = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("chillerCHWST",false)
		chillerCHWST.setDisplayName("Chiller Design Chilled Water Outlet Temperature (F)")
		chillerCHWST.setDefaultValue(54)	
		args << chillerCHWST
		
		# Chilled Water Loop Temp
		chw_loop_temp = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("chw_loop_temp",false)
		chw_loop_temp.setDisplayName("Chilled Water Loop Temperature (F)")
		chw_loop_temp.setDefaultValue(54)	
		args << chw_loop_temp
		
		
		#Cooling Tower type
		cooling_tower_chs = OpenStudio::StringVector.new
		cooling_tower_chs << "SingleSpeed"
		cooling_tower_chs << "VariableSpeed"
		cooling_tower =  OpenStudio::Ruleset::OSArgument::makeChoiceArgument("cooling_tower",cooling_tower_chs,false) 
		cooling_tower.setDisplayName("Cooling Tower Type")
		cooling_tower.setDefaultValue("VariableSpeed")
		args << cooling_tower
		
		
		# DOAS Energy Recovery
		ervChs = OpenStudio::StringVector.new
		ervChs << "plate w/o economizer lockout"
		ervChs << "plate w/ economizer lockout"
		ervChs << "rotary wheel w/o economizer lockout"
		ervChs << "rotary wheel w/ economizer lockout"
		ervChs << "none"
		doasERV = OpenStudio::Ruleset::OSArgument::makeChoiceArgument("doasERV",ervChs,true)
		doasERV.setDisplayName("DOAS Energy Recovery?")
		doasERV.setDefaultValue("none")
		args << doasERV
		
		# DOAS Heating Coil
		heatingCoilChs = OpenStudio::StringVector.new
		heatingCoilChs << "Gas"
		heatingCoilChs << "Water"
		doasHeatingCoil = OpenStudio::Ruleset::OSArgument::makeChoiceArgument("doasHeatingCoil",heatingCoilChs,true)
		doasHeatingCoil.setDisplayName("DOAS Heating Coil Type")
		doasHeatingCoil.setDefaultValue("Gas")
		args << doasHeatingCoil
		
		# DOAS Cooling Coil
		coolingCoilChs = OpenStudio::StringVector.new
		coolingCoilChs << "SingleDX"
		coolingCoilChs << "TwoSpeedDX"
		coolingCoilChs << "Water"
		coolingCoilChs << "none"
		doasCoolingCoil = OpenStudio::Ruleset::OSArgument::makeChoiceArgument("doasCoolingCoil",coolingCoilChs,true)
		doasCoolingCoil.setDisplayName("DOAS Cooling Coil Type")
		doasCoolingCoil.setDefaultValue("none")
		args << doasCoolingCoil
		
		#DX COP
		dx_cop = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("dx_cop",false)
		dx_cop.setDisplayName("DOAS DX COP (if applicable)")
		dx_cop.setDefaultValue(3.0)	
		args << dx_cop
		
		# DOAS Evaporative Cooling
		evapChs = OpenStudio::StringVector.new
		evapChs << "Direct Evaporative Cooler"
		evapChs << "none"
		doasEvap = OpenStudio::Ruleset::OSArgument::makeChoiceArgument("doasEvap",evapChs,true)
		doasEvap.setDisplayName("DOAS Direct Evaporative Cooling?")
		doasEvap.setDefaultValue("none")
		args << doasEvap
		
    # make an argument for material and installation cost
    # todo - I would like to split the costing out to the air loops weighted by area of building served vs. just sticking it on the building
    costTotalHVACSystem = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("costTotalHVACSystem",true)
    costTotalHVACSystem.setDisplayName("Total Cost for HVAC System ($).")
    costTotalHVACSystem.setDefaultValue(0.0)
    args << costTotalHVACSystem
    
    #make an argument to remove existing costs
    remake_schedules = OpenStudio::Ruleset::OSArgument::makeBoolArgument("remake_schedules",true)
    remake_schedules.setDisplayName("Apply recommended availability and ventilation schedules for air handlers?")
    remake_schedules.setDefaultValue(true)
    args << remake_schedules

    return args
  end #end the arguments method

  #define what happens when the measure is run
  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)

    #use the built-in error checking 
    if not runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end
	
		# assign the user inputs to variables
		space_type_to_edits_hash ={}
		space_types = model.getSpaceTypes
		space_types.each do |space_type|
			if model.getSpaceTypeByName(space_type.name.get).is_initialized and space_type.spaces.size > 0
				space_type = model.getSpaceTypeByName(space_type.name.get).get
				space_type_to_edit = runner.getBoolArgumentValue(space_type.name.get.to_s,user_arguments)
				space_type_to_edits_hash[space_type] = space_type_to_edit 
			end		
		end

	
		
		chilled_beam_type = runner.getStringArgumentValue("chilled_beam_type",user_arguments)
		heating_type = runner.getStringArgumentValue("heating_type",user_arguments)
		boilerEff= runner.getDoubleArgumentValue("boilerEff",user_arguments)
		boilerFuelType = runner.getStringArgumentValue("boilerFuelType",user_arguments)
		boilerHWST = runner.getDoubleArgumentValue("boilerHWST",user_arguments)
		hw_loop_temp = runner.getDoubleArgumentValue("hw_loop_temp",user_arguments)
		chiller_cop= runner.getDoubleArgumentValue("chiller_cop",user_arguments)
		chiller_condenser = runner.getStringArgumentValue("chiller_condenser",user_arguments)
		chillerCHWST = runner.getDoubleArgumentValue("chillerCHWST",user_arguments)
		chw_loop_temp = runner.getDoubleArgumentValue("chw_loop_temp",user_arguments)
		cooling_tower = runner.getStringArgumentValue("cooling_tower",user_arguments)
		doasERV = runner.getStringArgumentValue("doasERV",user_arguments)
		doasHeatingCoil = runner.getStringArgumentValue("doasHeatingCoil",user_arguments)
		doasCoolingCoil = runner.getStringArgumentValue("doasCoolingCoil",user_arguments)
		dx_cop= runner.getDoubleArgumentValue("dx_cop",user_arguments)
		doasEvap = runner.getStringArgumentValue("doasEvap",user_arguments)

	
	  parameters ={"chilled_beam_type" => chilled_beam_type,
									"heating_type" => heating_type,
									"boilerEff" => boilerEff,
									"boilerFuelType" => boilerFuelType,
									"boilerHWST" => boilerHWST,	
									"hw_loop_temp" => hw_loop_temp,
									"chiller_cop" => chiller_cop,
									"chiller_condenser" => chiller_condenser,
									"chillerCHWST" => chillerCHWST,
									"chw_loop_temp" => chw_loop_temp,
									"cooling_tower" => cooling_tower,
									"doasERV" => doasERV,
									"doasHeatingCoil" => doasHeatingCoil,
									"doasCoolingCoil" => doasCoolingCoil,
									"dx_cop" => dx_cop,
									"doasEvap" => doasEvap}
									
									
    ### START INPUTS
    #assign the user inputs to variables
    ceilingReturnPlenumSpaceType = runner.getOptionalWorkspaceObjectChoiceValue("ceilingReturnPlenumSpaceType",user_arguments,model)
    costTotalHVACSystem = runner.getDoubleArgumentValue("costTotalHVACSystem",user_arguments)
    remake_schedules = runner.getBoolArgumentValue("remake_schedules",user_arguments)
    # check that spaceType was chosen and exists in model
    ceilingReturnPlenumSpaceTypeCheck = OsLib_HelperMethods.checkOptionalChoiceArgFromModelObjects(ceilingReturnPlenumSpaceType, "ceilingReturnPlenumSpaceType","to_SpaceType", runner, user_arguments)
    if ceilingReturnPlenumSpaceTypeCheck == false then return false else ceilingReturnPlenumSpaceType = ceilingReturnPlenumSpaceTypeCheck["modelObject"] end
    # default building/ secondary space types
    standardBuildingTypeTest = [] #ML Not used yet
		#secondarySpaceTypeTest = ["Cafeteria", "Kitchen", "Gym", "Auditorium"]
    standardBuildingTypeTest = ["Office"] #ML Not used yet
    secondarySpaceTypeTest = [] # empty for office
    primarySpaceType = "Office"
		primaryHVAC = {"doas" => true, "fan" => "Constant", "heat" => doasHeatingCoil, "cool" => doasCoolingCoil}
    secondaryHVAC = {"fan" => "None", "heat" => "None", "cool" => "None"} #ML not used for office; leave or empty?
    if heating_type == "Baseboard"
		zoneHVAC = "Baseboard"
		else
		zoneHVAC = "Radiant"
		end
		if chiller_condenser == "AirCooled"
    chillerType = "AirCooled" #set to none if chiller not used
    radiantChillerType = "AirCooled" #set to none if not radiant system
		else
		chillerType = "WaterCooled" #set to none if chiller not used
    radiantChillerType = "WaterCooled" #set to none if not radiant system
		end
    allHVAC = {"primary" => primaryHVAC,"secondary" => secondaryHVAC,"zone" => zoneHVAC}

		
    ### END INPUTS
  
    ### START SORT ZONES
    options = {"standardBuildingTypeTest" => standardBuildingTypeTest, #ML Not used yet
               "secondarySpaceTypeTest" => secondarySpaceTypeTest,
               "ceilingReturnPlenumSpaceType" => ceilingReturnPlenumSpaceType}
    zonesSorted = OsLib_HVAC.sortZones(model, runner, options, space_type_to_edits_hash)
    zonesPrimary = zonesSorted["zonesPrimary"]
    zonesSecondary = zonesSorted["zonesSecondary"]
    zonesPlenum = zonesSorted["zonesPlenum"]
    zonesUnconditioned = zonesSorted["zonesUnconditioned"]
    ### END SORT ZONES
    
    ### START REPORT INITIAL CONDITIONS
    OsLib_HVAC.reportConditions(model, runner, "initial")
    ### END REPORT INITIAL CONDITIONS

    ### START ASSIGN HVAC SCHEDULES
    options = {"primarySpaceType" => primarySpaceType,
               "allHVAC" => allHVAC,
               "remake_schedules" => remake_schedules}
    schedulesHVAC = OsLib_HVAC.assignHVACSchedules(model, runner, options)
    # assign schedules
    primary_SAT_schedule = schedulesHVAC["primary_sat"]
    building_HVAC_schedule = schedulesHVAC["hvac"]
    building_ventilation_schedule = schedulesHVAC["ventilation"]
    make_hot_water_plant = true
    unless schedulesHVAC["hot_water"].nil?
      hot_water_setpoint_schedule = schedulesHVAC["hot_water"]
      make_hot_water_plant = true
    end
    make_chilled_water_plant = true
    unless schedulesHVAC["chilled_water"].nil?
      chilled_water_setpoint_schedule = schedulesHVAC["chilled_water"]
      make_chilled_water_plant = true
    end
    make_radiant_hot_water_plant = false
    unless schedulesHVAC["radiant_hot_water"].nil?
      radiant_hot_water_setpoint_schedule = schedulesHVAC["radiant_hot_water"]
      make_radiant_hot_water_plant = true
    end
    make_radiant_chilled_water_plant = false
    unless schedulesHVAC["radiant_chilled_water"].nil?
      radiant_chilled_water_setpoint_schedule = schedulesHVAC["radiant_chilled_water"]
      make_radiant_chilled_water_plant = true
    end
    unless schedulesHVAC["hp_loop"].nil?
      heat_pump_loop_setpoint_schedule = schedulesHVAC["hp_loop"]
    end
    unless schedulesHVAC["hp_loop_cooling"].nil?
      heat_pump_loop_cooling_setpoint_schedule = schedulesHVAC["hp_loop_cooling"]
    end
    unless schedulesHVAC["hp_loop_heating"].nil?
      heat_pump_loop_heating_setpoint_schedule = schedulesHVAC["hp_loop_heating"]
    end
    unless schedulesHVAC["mean_radiant_heating"].nil?
      mean_radiant_heating_setpoint_schedule = schedulesHVAC["mean_radiant_heating"]
    end
    unless schedulesHVAC["mean_radiant_cooling"].nil?
      mean_radiant_cooling_setpoint_schedule = schedulesHVAC["mean_radiant_cooling"]
    end
    ### END ASSIGN HVAC SCHEDULES
    
    # START REMOVE EQUIPMENT
		options = {}
		options["zonesPrimary"] = zonesPrimary
		if options["zonesPrimary"].empty?
			runner.registerInfo("User did not pick any zones to be added to WSHP system, no changes to the model were made.")
 		else
			OsLib_HVAC.removeEquipment(model, runner, options)
		end
    ### END REMOVE EQUIPMENT
    
    ### START CREATE NEW PLANTS
    # create new plants
    # hot water plant
    if make_hot_water_plant
      hot_water_plant = OsLib_HVAC.createHotWaterPlant(model, runner, hot_water_setpoint_schedule, "Hot Water", parameters)
    end
    # chilled water plant
    if make_chilled_water_plant
      chilled_water_plant = OsLib_HVAC.createChilledWaterPlant(model, runner, chilled_water_setpoint_schedule, "Chilled Water", chillerType, parameters)
    end
    # radiant hot water plant
    # if make_radiant_hot_water_plant
      # radiant_hot_water_plant = OsLib_HVAC.createHotWaterPlant(model, runner, radiant_hot_water_setpoint_schedule, "Radiant Hot Water", parameters)
    # end
    # chilled water plant
    # if make_radiant_chilled_water_plant
      # radiant_chilled_water_plant = OsLib_HVAC.createChilledWaterPlant(model, runner, radiant_chilled_water_setpoint_schedule, "Radiant Chilled Water", radiantChillerType)
    # end
    # condenser loop
    # need condenser loop if there is a water-cooled chiller or if there is a water source heat pump loop
    options = {}
		options["zonesPrimary"] = zonesPrimary
    options["zoneHVAC"] = zoneHVAC
    if zoneHVAC.include? "SHP"
      options["loop_setpoint_schedule"] = heat_pump_loop_setpoint_schedule
      options["cooling_setpoint_schedule"] = heat_pump_loop_cooling_setpoint_schedule
      options["heating_setpoint_schedule"] = heat_pump_loop_heating_setpoint_schedule
    end  
		if options["zonesPrimary"].empty?
		  # runner.registerWarning("User did not pick any space types to be added to the WSHP system, no changes to the model were made")
			condenserLoops = {}
			# condenserLoops["condenser_loop"] ={}
		else
			condenserLoops = OsLib_HVAC.createCondenserLoop(model, runner, options, parameters)
		end
    unless condenserLoops["condenser_loop"].nil?
      condenser_loop = condenserLoops["condenser_loop"]
    end
    unless condenserLoops["heat_pump_loop"].nil?
      heat_pump_loop = condenserLoops["heat_pump_loop"]
    end
    ### END CREATE NEW PLANTS
    
    ### START CREATE PRIMARY AIRLOOPS
    # populate inputs hash for create primary airloops method
    options = {}
    options["zonesPrimary"] = zonesPrimary
    options["primaryHVAC"] = primaryHVAC
    options["zoneHVAC"] = zoneHVAC
    if primaryHVAC["doas"]
      options["hvac_schedule"] = building_ventilation_schedule
      options["ventilation_schedule"] = building_ventilation_schedule
    else
      # primary HVAC is multizone VAV
      unless zoneHVAC == "DualDuct"
        # primary system is multizone VAV that cools and ventilates
        options["hvac_schedule"] = building_HVAC_schedule
        options["ventilation_schedule"] = building_ventilation_schedule
      else
        # primary system is a multizone VAV that cools only (primary system ventilation schedule is set to always off; hvac set to always on)
        options["hvac_schedule"] = model.alwaysOnDiscreteSchedule()
      end
    end
    options["primary_sat_schedule"] = primary_SAT_schedule
    if make_hot_water_plant
      options["hot_water_plant"] = hot_water_plant
    end
    if make_chilled_water_plant
      options["chilled_water_plant"] = chilled_water_plant
    end
    primary_airloops = OsLib_HVAC.createPrimaryAirLoops(model, runner, options, parameters)
    ### END CREATE PRIMARY AIRLOOPS
    
    ### START CREATE SECONDARY AIRLOOPS
    # populate inputs hash for create primary airloops method
    options = {}
    options["zonesSecondary"] = zonesSecondary
    options["secondaryHVAC"] = secondaryHVAC
    options["hvac_schedule"] = building_HVAC_schedule
    options["ventilation_schedule"] = building_ventilation_schedule
    if make_hot_water_plant
      options["hot_water_plant"] = hot_water_plant
    end
    if make_chilled_water_plant
      options["chilled_water_plant"] = chilled_water_plant
    end
    secondary_airloops = OsLib_HVAC.createSecondaryAirLoops(model, runner, options)
    ### END CREATE SECONDARY AIRLOOPS
    
    ### START ASSIGN PLENUMS
    options = {"zonesPrimary" => zonesPrimary,"zonesPlenum" => zonesPlenum}
    zone_plenum_hash = OsLib_HVAC.validateAndAddPlenumZonesToSystem(model, runner, options)
    ### END ASSIGN PLENUMS
    
    ### START CREATE PRIMARY ZONE EQUIPMENT
    options = {}
    options["zonesPrimary"] = zonesPrimary
    options["zoneHVAC"] = zoneHVAC
    if make_hot_water_plant
      options["hot_water_plant"] = hot_water_plant
    end
    if make_chilled_water_plant
      options["chilled_water_plant"] = chilled_water_plant
    end
    if zoneHVAC.include? "SHP"
      options["heat_pump_loop"] = heat_pump_loop
    end
    if zoneHVAC == "DualDuct"
      options["ventilation_schedule"] = building_ventilation_schedule
    end
    if zoneHVAC == "Radiant"
      #options["radiant_hot_water_plant"] = radiant_hot_water_plant
      #options["radiant_chilled_water_plant"] = radiant_chilled_water_plant
      options["mean_radiant_heating_setpoint_schedule"] = mean_radiant_heating_setpoint_schedule
      options["mean_radiant_cooling_setpoint_schedule"] = mean_radiant_cooling_setpoint_schedule
    end
    OsLib_HVAC.createPrimaryZoneEquipment(model, runner, options, parameters)
    ### END CREATE PRIMARY ZONE EQUIPMENT
    
    # START ADD DCV
    options = {}
    unless zoneHVAC == "DualDuct"
      options["primary_airloops"] = primary_airloops
    end
    options["secondary_airloops"] = secondary_airloops
    options["allHVAC"] = allHVAC
    OsLib_HVAC.addDCV(model, runner, options)
    # END ADD DCV
       
    # todo - add in lifecycle costs
    expected_life = 25
    years_until_costs_start = 0
    costHVAC = costTotalHVACSystem
    lcc_mat = OpenStudio::Model::LifeCycleCost.createLifeCycleCost("HVAC System", model.getBuilding, costHVAC, "CostPerEach", "Construction", expected_life, years_until_costs_start).get

    # # add AEDG tips
    # aedgTips = ["HV04","HV10","HV12"]

    # # populate how to tip messages
    # aedgTipsLong = OsLib_AedgMeasures.getLongHowToTips("SmMdOff",aedgTips.uniq.sort,runner)
    # if not aedgTipsLong
      # return false # this should only happen if measure writer passes bad values to getLongHowToTips
    # end

    ### START REPORT FINAL CONDITIONS
    OsLib_HVAC.reportConditions(model, runner, "final")
    ### END REPORT FINAL CONDITIONS

    return true

  end #end the run method

end #end the measure

#this allows the measure to be used by the application
ChilledBeamwithDOAS.new.registerWithApplication