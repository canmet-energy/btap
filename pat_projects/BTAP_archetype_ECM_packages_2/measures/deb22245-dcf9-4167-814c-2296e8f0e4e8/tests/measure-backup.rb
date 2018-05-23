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
class WSHPwithDOASMoreDesignParameters < OpenStudio::Ruleset::ModelUserScript

  #define the name that a user will see, this method may be deprecated as
  #the display name in PAT comes from the name field in measure.xml
  def name
    return "WSHPwithDOASMoreDesignParameters"
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
	
	# Heating COP of WSHP
	wshpHeatingCOP = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("wshpHeatingCOP",false)
	wshpHeatingCOP.setDisplayName("WSHP AHRI Heating COP")
	wshpHeatingCOP.setDefaultValue(4.0)
	args << wshpHeatingCOP
	
	# Cooling EER of WSHP
	wshpCoolingEER = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("wshpCoolingEER",false)
	wshpCoolingEER.setDisplayName("WSHP AHRI Cooling EER")
	wshpCoolingEER.setDefaultValue(14)
	args << wshpCoolingEER
	
	# WSHP Fan Type PSC or ECM
	fanChs = OpenStudio::StringVector.new
	fanChs << "PSC"
	fanChs << "ECM"
	wshpFanType =  OpenStudio::Ruleset::OSArgument::makeChoiceArgument("wshpFanType",fanChs,true) # note ECM fan type may correspond to different set of heat pump performance curves
	wshpFanType.setDisplayName("WSHP Fan Type: PSC or ECM?")
	wshpFanType.setDefaultValue("PSC")
    args << wshpFanType
	
	# Condenser Loop Cooling Temperature
	condLoopCoolingTemp = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("condLoopCoolingTemp",false)
	condLoopCoolingTemp.setDisplayName("Condenser Loop Cooling Temperature (F)")
	condLoopCoolingTemp.setDefaultValue(90)
	args << condLoopCoolingTemp
	
	# Condenser Loop Heating Temperature
	condLoopHeatingTemp = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("condLoopHeatingTemp",false)
	condLoopHeatingTemp.setDisplayName("Condenser Loop Heating Temperature (F)")
	condLoopHeatingTemp.setDefaultValue(60)	
	args << condLoopHeatingTemp
	
	# Cooling Tower
	coolingTowerWB = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("coolingTowerWB",false)
	coolingTowerWB.setDisplayName("Cooling Tower Design Wet Bulb (F)")
	coolingTowerWB.setDefaultValue(68)
	args << coolingTowerWB

	coolingTowerApproach = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("coolingTowerApproach",false)
	coolingTowerApproach.setDisplayName("Cooling Tower Design Approach (F)")
	coolingTowerApproach.setDefaultValue(7.0)
	args << coolingTowerApproach

	coolingTowerDeltaT = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("coolingTowerDeltaT",false)
	coolingTowerDeltaT.setDisplayName("Cooling Tower Design Delta T (F)")
	coolingTowerDeltaT.setDefaultValue(10.0)
	args << coolingTowerDeltaT
	
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
	boilerHWST.setDefaultValue(120)	
	args << boilerHWST
	
	# DOAS Fan Type
	doasFanChs = OpenStudio::StringVector.new
	doasFanChs << "Constant"
	doasFanChs << "Variable"
	doasFanType = OpenStudio::Ruleset::OSArgument::makeChoiceArgument("doasFanType",doasFanChs,true)
	doasFanType.setDisplayName("DOAS Fan Flow Control - Variable means DCV controls")
	doasFanType.setDefaultValue("Variable")
	args << doasFanType
	
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
	
	# DOAS Evaporative Cooling
	evapChs = OpenStudio::StringVector.new
	evapChs << "Direct Evaporative Cooler"
	evapChs << "none"
	doasEvap = OpenStudio::Ruleset::OSArgument::makeChoiceArgument("doasEvap",evapChs,true)
	doasEvap.setDisplayName("DOAS Direct Evaporative Cooling?")
	doasEvap.setDefaultValue("none")
	args << doasEvap
	
	# DOAS DX Cooling
	doasDXEER = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("doasDXEER",false)
	doasDXEER.setDisplayName("DOAS DX Cooling EER")
	doasDXEER.setDefaultValue(10.0)
	args << doasDXEER
	
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
	wshpHeatingCOP = runner.getDoubleArgumentValue("wshpHeatingCOP",user_arguments)
	wshpCoolingEER = runner.getDoubleArgumentValue("wshpCoolingEER",user_arguments)
	wshpFanType = runner.getStringArgumentValue("wshpFanType",user_arguments)
	condLoopCoolingTemp = runner.getDoubleArgumentValue("condLoopCoolingTemp",user_arguments)
	condLoopHeatingTemp = runner.getDoubleArgumentValue("condLoopHeatingTemp",user_arguments)
	coolingTowerWB = runner.getDoubleArgumentValue("coolingTowerWB",user_arguments)
	coolingTowerApproach= runner.getDoubleArgumentValue("coolingTowerApproach",user_arguments)
	coolingTowerDeltaT= runner.getDoubleArgumentValue("coolingTowerDeltaT",user_arguments)
	boilerEff= runner.getDoubleArgumentValue("boilerEff",user_arguments)
	boilerFuelType = runner.getStringArgumentValue("boilerFuelType",user_arguments)
	boilerHWST= runner.getDoubleArgumentValue("boilerHWST",user_arguments)
	doasFanType = runner.getStringArgumentValue("doasFanType",user_arguments)
	doasERV = runner.getStringArgumentValue("doasERV",user_arguments)
	doasEvap = runner.getStringArgumentValue("doasEvap",user_arguments)
	doasDXEER= runner.getDoubleArgumentValue("doasDXEER",user_arguments)
	
    ### START INPUTS
    #assign the user inputs to variables
    ceilingReturnPlenumSpaceType = runner.getOptionalWorkspaceObjectChoiceValue("ceilingReturnPlenumSpaceType",user_arguments,model)
    costTotalHVACSystem = runner.getDoubleArgumentValue("costTotalHVACSystem",user_arguments)
    remake_schedules = runner.getBoolArgumentValue("remake_schedules",user_arguments)
    # check that spaceType was chosen and exists in model
    ceilingReturnPlenumSpaceTypeCheck = OsLib_HelperMethods.checkOptionalChoiceArgFromModelObjects(ceilingReturnPlenumSpaceType, "ceilingReturnPlenumSpaceType","to_SpaceType", runner, user_arguments)
    if ceilingReturnPlenumSpaceTypeCheck == false then return false else ceilingReturnPlenumSpaceType = ceilingReturnPlenumSpaceTypeCheck["modelObject"] end
    # default building/ secondary space types
    standardBuildingTypeTest = ["Office"] #ML Not used yet
    secondarySpaceTypeTest = [] # empty for office
    primarySpaceType = "Office"
	if doasFanType == "Variable"
		primaryHVAC = {"doas" => true, "fan" => "Variable", "heat" => "Gas", "cool" => "SingleDX"} 
	else
		primaryHVAC = {"doas" => true, "fan" => "Constant", "heat" => "Gas", "cool" => "SingleDX"}
	end
    secondaryHVAC = {"fan" => "None", "heat" => "None", "cool" => "None"} #ML not used for office; leave or empty?
    zoneHVAC = "WSHP"
    chillerType = "None" #set to none if chiller not used
    radiantChillerType = "None" #set to none if not radiant system
    allHVAC = {"primary" => primaryHVAC,"secondary" => secondaryHVAC,"zone" => zoneHVAC}

		
    ### END INPUTS
  
    ### START SORT ZONES
    options = {"standardBuildingTypeTest" => standardBuildingTypeTest, #ML Not used yet
               "secondarySpaceTypeTest" => secondarySpaceTypeTest,
               "ceilingReturnPlenumSpaceType" => ceilingReturnPlenumSpaceType}
    zonesSorted = OsLib_HVAC.sortZones(model, runner, options)
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
    make_hot_water_plant = false
    unless schedulesHVAC["hot_water"].nil?
      hot_water_setpoint_schedule = schedulesHVAC["hot_water"]
      make_hot_water_plant = true
    end
    make_chilled_water_plant = false
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
    
    ### START REMOVE EQUIPMENT
    OsLib_HVAC.removeEquipment(model, runner)
    ### END REMOVE EQUIPMENT
    
    ### START CREATE NEW PLANTS
    # create new plants
    # hot water plant
    if make_hot_water_plant
      hot_water_plant = OsLib_HVAC.createHotWaterPlant(model, runner, hot_water_setpoint_schedule, "Hot Water",  boilerEff, boilerFuelType, boilerHWST)
    end
    # chilled water plant
    if make_chilled_water_plant
      chilled_water_plant = OsLib_HVAC.createChilledWaterPlant(model, runner, chilled_water_setpoint_schedule, "Chilled Water", chillerType)
    end
    # radiant hot water plant
    if make_radiant_hot_water_plant
      radiant_hot_water_plant = OsLib_HVAC.createHotWaterPlant(model, runner, radiant_hot_water_setpoint_schedule, "Radiant Hot Water")
    end
    # chilled water plant
    if make_radiant_chilled_water_plant
      radiant_chilled_water_plant = OsLib_HVAC.createChilledWaterPlant(model, runner, radiant_chilled_water_setpoint_schedule, "Radiant Chilled Water", radiantChillerType)
    end
    # condenser loop
    # need condenser loop if there is a water-cooled chiller or if there is a water source heat pump loop
    options = {}
    options["zoneHVAC"] = zoneHVAC
    if zoneHVAC.include? "SHP"
      options["loop_setpoint_schedule"] = heat_pump_loop_setpoint_schedule
      options["cooling_setpoint_schedule"] = heat_pump_loop_cooling_setpoint_schedule
      options["heating_setpoint_schedule"] = heat_pump_loop_heating_setpoint_schedule
    end  
    condenserLoops = OsLib_HVAC.createCondenserLoop(model, runner, options,boilerEff,boilerFuelType,boilerHWST,coolingTowerWB,coolingTowerApproach,coolingTowerDeltaT,condLoopCoolingTemp,condLoopHeatingTemp)
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
    primary_airloops = OsLib_HVAC.createPrimaryAirLoops(model, runner, options,doasFanType,doasERV,doasEvap,doasDXEER)
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
      options["radiant_hot_water_plant"] = radiant_hot_water_plant
      options["radiant_chilled_water_plant"] = radiant_chilled_water_plant
      options["mean_radiant_heating_setpoint_schedule"] = mean_radiant_heating_setpoint_schedule
      options["mean_radiant_cooling_setpoint_schedule"] = mean_radiant_cooling_setpoint_schedule
    end
    OsLib_HVAC.createPrimaryZoneEquipment(model, runner, options,wshpCoolingEER, wshpHeatingCOP,wshpFanType)
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
WSHPwithDOASMoreDesignParameters.new.registerWithApplication