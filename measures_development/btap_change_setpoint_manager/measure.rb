#see the URL below for information on how to write OpenStudio measures
# http://openstudio.nrel.gov/openstudio-measure-writing-guide

#see the URL below for access to C++ documentation on model objects (click on "model" in the main window to view model objects)
# http://openstudio.nrel.gov/sites/openstudio.nrel.gov/files/nv_data/cpp_documentation_it/model/html/namespaces.html
require_relative 'resources/BTAPMeasureHelper'
#start the measure

class BTAPChangeSetpointManager < OpenStudio::Measure::ModelMeasure
  attr_accessor :use_json_package, :use_string_double
  #Adds helper functions to make life a bit easier and consistent.
  include(BTAPMeasureHelper)

  #define the name that a user will see, this method may be deprecated as
  #the display name in PAT comes from the name field in measure.xml
  def name
    return "BTAPChangeSetpointManager"
  end

  def description
    return 'This measures creates new setpoint Managers'
  end

  def modeler_description
    return 'Looks for setpoint managers in airloops. Removes them and replaces them with setpoint Managers of type : Warmest, SingleZoneReheat, or OutdoorAirReset '
  end

  def initialize()
    super()

    #Set to true if you want to package the arguments as json.
    @use_json_package = false
    #Set to true if you want to want to allow strings and doubles in stringdouble types. Set to false to force to use doubles. The latter is used for certain
    # continuous optimization algorithms. You may have to re-examine your input in PAT as this fundamentally changes the measure.
    @use_string_double = true

    #model = OpenStudio::Model::Model.new

    @measure_interface_detailed = [
        {
            "name" => "setpPointManagerType",
            "type" => "Choice",
            "display_name" => "Type of Setpoint Manager",
            "default_value" => "setpointManager_SingleZoneReheat",
            "choices" => ["setpointManager_Warmest", "setpointManager_SingleZoneReheat", "setpointManager_OutdoorAirReset"],
            "is_required" => true
        }
    ]
  end

  #define what happens when the measure is run
  def run(model, runner, user_arguments)
    #Runs parent run method.
    super(model, runner, user_arguments)
    # Gets arguments from interfaced and puts them in a hash with there display name. This also does a check on ranges to
    # ensure that the values inputted are valid based on your @measure_interface array of hashes.
    arguments = validate_and_get_arguments_in_hash(model, runner, user_arguments)
    #puts JSON.pretty_generate(arguments)
    return false if false == arguments

    #use the built-in error checking
    if not runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end

    # loop through all air loops
    model.getAirLoopHVACs.each do |air_loop|
      air_loop.supplyComponents.each do |supply_component|
        runner.registerInfo("Checking supply component #{supply_component.name.to_s}")
        # Check if the supply component is a CAV fan or setpoint manager. If so modify the loop.
        if not supply_component.to_SetpointManager.empty?
          setpointMgr = supply_component.to_SetpointManager.get
          runner.registerInfo("Removing setpoint manager #{setpointMgr.name.to_s} from air model.")
          setpointMgr.remove
        end
      end

      setpPointManagerType = arguments['setpPointManagerType']
      if (setpPointManagerType == "setpointManager_Warmest")
        # Create new Setpoint manager (Warmest)
        setpointMgr = OpenStudio::Model::SetpointManagerWarmest.new(model)
        setpointMgr.setMinimumSetpointTemperature(16)
        setpointMgr.setMaximumSetpointTemperature(38)
        node = air_loop.supplyOutletNode
        setpointMgr.addToNode(node)
        runner.registerInfo("Setpoint Manager Warmest is set to 16.0 and 38.0")

        # List everything in the air loop now and fix what needs fixed.
        air_loop.supplyComponents.each do |supply_component|
          if not supply_component.to_CoilHeatingElectric.empty?
            # runner.registerInfo("+++ Resetting temperature setpoint notte for electric heating coil #{supply_component.name.to_s}")
            supply_component.to_CoilHeatingElectric.get.setTemperatureSetpointNode(node)
          end
        end
      elsif (setpPointManagerType == "setpointManager_SingleZoneReheat")
        cooling_present = false
        set_point_manager = nil
        air_loop.components.each do |icomponent|
          if icomponent.to_CoilCoolingDXSingleSpeed.is_initialized or
              icomponent.to_CoilCoolingDXTwoSpeed.is_initialized or
              icomponent.to_CoilCoolingWater.is_initialized or
              icomponent.to_CoilCoolingCooledBeam.is_initialized or
              icomponent.to_CoilCoolingDXMultiSpeed.is_initialized or
              icomponent.to_CoilCoolingDXVariableRefrigerantFlow.is_initialized or
              icomponent.to_CoilCoolingLowTempRadiantConstFlow.is_initialized or
              icomponent.to_CoilCoolingLowTempRadiantVarFlow.is_initialized
            cooling_present = true
          end
        end
        #check if setpoint manager is present at supply outlet.
        model.getSetpointManagerSingleZoneReheats.each do |manager|
          if air_loop.supplyOutletNode == manager.setpointNode.get
            set_point_manager = manager
          end
        end

        if set_point_manager.nil? and cooling_present == true
          set_point_manager = OpenStudio::Model::SetpointManagerSingleZoneReheat.new(model)
          set_point_manager.addToNode(iairloop.supplyOutletNode)
        end

        if cooling_present == true and not set_point_manager.nil?
          set_point_manager.setMaximumSupplyAirTemperature(45.0)
          set_point_manager.setMinimumSupplyAirTemperature(13.0)
          runner.registerInfo("Setpoint Manager SingleZoneReheat is set to 13.0 and 45.0")
        end
      elsif (setpPointManagerType == "setpointManager_OutdoorAirReset")
        #check if setpoint manager is present at supply outlet
        model.getSetpointManagerSingleZoneReheats.each do |manager|
          if air_loop.supplyOutletNode == manager.setpointNode.get
            manager.disconnect
          end
        end

        new_set_point_manager = OpenStudio::Model::SetpointManagerOutdoorAirReset.new(model)
        new_set_point_manager.addToNode(air_loop.supplyOutletNode)
        new_set_point_manager.setSetpointatOutdoorLowTemperature(17)
        new_set_point_manager.setOutdoorLowTemperature(10)
        new_set_point_manager.setOutdoorHighTemperature(24)
        new_set_point_manager.setSetpointatOutdoorHighTemperature(13)
        new_set_point_manager.setControlVariable("Temperature")
      end
    end

    final_SetpointManagers_w = 0
    final_SetpointManagers_sz = 0
    final_SetpointManagers_oa = 0
    setpointM_name_arr = []
    model.getNodes.each do |node|
      node.setpointManagers.each do |setpointM|
        setpointM_name = setpointM.name.to_s
        if setpointM_name.include? "Setpoint Manager Warmest"
          setpointM_name_arr.unshift(setpointM_name)
          final_SetpointManagers_w += 1
        elsif setpointM_name.include? "Setpoint Manager Single Zone Reheat"
          setpointM_name_arr.unshift(setpointM_name)
          final_SetpointManagers_sz += 1
        elsif setpointM_name.include? "Setpoint Manager Outdoor Air Reset"
          setpointM_name_arr.unshift(setpointM_name)
          final_SetpointManagers_oa += 1
        end
      end
    end
    runner.registerInfo("The model ended with  #{setpointM_name_arr}, #{final_SetpointManagers_w} SetpointManagers of type Warmest , #{final_SetpointManagers_sz} SetpointManagers of type Single Zone Reheat, #{final_SetpointManagers_oa} SetpointManagers of type Outdoor Air Reset.")
  end
end

#this allows the measure to be use by the application
BTAPChangeSetpointManager.new.registerWithApplication