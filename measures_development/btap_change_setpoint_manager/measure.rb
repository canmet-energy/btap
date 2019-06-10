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
    return 'Looks for a setpoint manager. Removes them and replaces them with setpoint Managers of type : Warmest, SingleZoneReheat, or OutdoorAirReset '
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

    initial_SetpointManagers = 0
    setpointM_name_arr = []
    model.getNodes.each do |node|
      node.setpointManagers.each do |setpointM|
        setpointM_name = setpointM.name.to_s
        if setpointM_name.include? "Setpoint Manager"
          setpointM_name_arr.unshift(setpointM_name)
          initial_SetpointManagers += 1
        end
        setpointM.remove
      end
    end
    runner.registerInitialCondition("The model started with #{initial_SetpointManagers} Setpoint Managers of type: #{setpointM_name_arr}.")
    setpPointManagerType = arguments['setpPointManagerType']

    if (setpPointManagerType == "setpointManager_Warmest")

      # loop through all air loops
      i_air_loop = 0
      model.getAirLoopHVACs.each do |air_loop|

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
      end

      final_SetpointManagers = 0
      setpointM_name_arr = []
      model.getNodes.each do |node|
        node.setpointManagers.each do |setpointM|
          setpointM_name = setpointM.name.to_s
          if setpointM_name.include? "Setpoint Manager Warmest"
            setpointM_name_arr.unshift(setpointM_name)
            final_SetpointManagers += 1
          else
            runner.registerError("The measure wasn't able to create any Setpoint Managers of type : Warmest.")
            return false
          end
        end
      end
      runner.registerFinalCondition("The model ended with #{final_SetpointManagers} SetpointManagers of type Warmest : #{setpointM_name_arr}.")

    elsif (setpPointManagerType == "setpointManager_SingleZoneReheat")
      #	if @cold_deck_reset_enabled.to_bool == true
      model.getAirLoopHVACs.each do |iairloop|
        cooling_present = false
        set_point_manager = nil
        iairloop.components.each do |icomponent|
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
          if iairloop.supplyOutletNode == manager.setpointNode.get
            set_point_manager = manager
          end
        end

        if set_point_manager.nil? and cooling_present == true
          set_point_manager = OpenStudio::Model::SetpointManagerSingleZoneReheat.new(model)
          set_point_manager.addToNode(iairloop.supplyOutletNode)
        end

        if cooling_present == true and not set_point_manager.nil?
          set_point_manager.setMaximumSupplyAirTemperature(20.0)
          set_point_manager.setMinimumSupplyAirTemperature(13.0)
          runner.registerInfo("Setpoint Manager SingleZoneReheat is set to 13.0 and 20.0")
        end
      end

      final_SetpointManagers = 0
      setpointM_name_arr = []
      model.getNodes.each do |node|
        node.setpointManagers.each do |setpointM|
          setpointM_name = setpointM.name.to_s
          if setpointM_name.include? "Setpoint Manager Single Zone Reheat"
            setpointM_name_arr.unshift(setpointM_name)
            final_SetpointManagers += 1
          else
            runner.registerError("The measure wasn't able to create any Setpoint Managers of type : Single Zone Reheat.")
            return false
          end
        end
      end
      runner.registerFinalCondition("The model ended with #{final_SetpointManagers} SetpointManagers of type SingleZoneReheat : #{setpointM_name_arr}.")

    elsif (setpPointManagerType == "setpointManager_OutdoorAirReset")
      model.getAirLoopHVACs.each do |iairloop|

        #check if setpoint manager is present at supply outlet
        model.getSetpointManagerSingleZoneReheats.each do |manager|
          if iairloop.supplyOutletNode == manager.setpointNode.get
            manager.disconnect
          end
        end

        new_set_point_manager = OpenStudio::Model::SetpointManagerOutdoorAirReset.new(model)
        new_set_point_manager.addToNode(iairloop.supplyOutletNode)
        new_set_point_manager.setOutdoorHighTemperature(25)
        new_set_point_manager.setOutdoorLowTemperature(15)
        new_set_point_manager.setSetpointatOutdoorHighTemperature(25)
        new_set_point_manager.setSetpointatOutdoorLowTemperature(15)
        new_set_point_manager.setControlVariable("5")
        puts ("Replaced SingleZoneReheat with OA reset control.")

        final_SetpointManagers = 0
        setpointM_name_arr = []
        model.getNodes.each do |node|
          node.setpointManagers.each do |setpointM|
            setpointM_name = setpointM.name.to_s
            if setpointM_name.include? "Setpoint Manager Outdoor Air Reset"
              setpointM_name_arr.unshift(setpointM_name)
              final_SetpointManagers += 1
            else
              runner.registerError("The measure wasn't able to create any Setpoint Managers of type : Outdoor Air Reset .")
              return false
            end
          end
        end
        runner.registerFinalCondition("The model ended with #{final_SetpointManagers} SetpointManagers of type Outdoor Air Reset  : #{setpointM_name_arr}.")
      end
    end #end the if loop
  end #end the run method
end #end the measure

#this allows the measure to be use by the application
BTAPChangeSetpointManager.new.registerWithApplication