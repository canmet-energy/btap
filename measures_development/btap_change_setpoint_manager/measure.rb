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
		return 'Looks for a setpoint manager. Removes them and replaces them with setpointManager::Warmest'
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
						"default_value" => "setpointManager_Warmest",
						"choices" => ["setpointManager_Warmest", "setpointManager_Scheduled", "setpointManager_SingleZoneReheat"],
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

		# find the initial number of SetpointManager:Warmest.
		initial_SetpointManager = 0
		model.getNodes.each do |node|
			node.setpointManagers.each do |setpointM|
				setpointM_name = setpointM.name.to_s
				if setpointM_name.include? "Setpoint Manager Warmest"
					initial_SetpointManager += 1
				end
			end
		end
		puts("The model started with #{initial_SetpointManager} initial SetpointManager Warmest.")
		runner.registerInitialCondition("The model started with #{initial_SetpointManager} initial SetpointManager Warmest.")

		setpPointManagerType = arguments['setpPointManagerType']

		if (setpPointManagerType == "setpointManager_Warmest")
			# loop through all air loops and remove the set point managers
			i_air_loop = 0
			model.getAirLoopHVACs.each do |air_loop|
				other_components = []
				air_loop.supplyComponents.each do |supply_component|
					# Check if the supply component is a setpoint manager. If so modify the loop.
					if not supply_component.to_SetpointManager.empty?
						setpointMgr = supply_component.to_SetpointManager.get
						setpointMgr.remove
					end
				end

				# Create new Setpoint manager (Warmest)
				setpointMgr = OpenStudio::Model::SetpointManagerWarmest.new(model)
				setpointMgr.setMinimumSetpointTemperature(16)
				setpointMgr.setMaximumSetpointTemperature(38)
				node = air_loop.supplyOutletNode
				setpointMgr.addToNode(node)

				# List everything in the air loop now and fix what needs fixed.
				air_loop.supplyComponents.each do |supply_component|
					if not supply_component.to_CoilHeatingElectric.empty?
						# runner.registerInfo("+++ Resetting temperature setpoint notte for electric heating coil #{supply_component.name.to_s}")
						supply_component.to_CoilHeatingElectric.get.setTemperatureSetpointNode(node)
					end
				end
			end
			op_file_path = OpenStudio::Path.new(File.dirname(__FILE__) + "/tests/output/finalModel.osm")
			model.save(op_file_path, true)

			final_SetpointManagers = 0
			model.getNodes.each do |node|
				node.setpointManagers.each do |setpointM|
					setpointM_name = setpointM.name.to_s
					if setpointM_name.include? "Setpoint Manager Warmest"
						final_SetpointManagers += 1
					end
				end
			end

			if final_SetpointManagers.to_i > 0
				runner.registerFinalCondition("The model ended with #{final_SetpointManagers} final SetpointManagers Warmest.")
			else
				runner.registerFinalCondition("No final_SetpointManagers : Warmest were added to the model. The model ended with #{final_SetpointManagers} final_SetpointManagers Warmest.")
			end
			return true
		end #end the if loop
	end #end the run method
end #end the measure

#this allows the measure to be use by the application
BTAPChangeSetpointManager.new.registerWithApplication