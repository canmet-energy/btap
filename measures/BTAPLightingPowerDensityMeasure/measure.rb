# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/

# Start the measure
class LightingPowerDensityMeasure < OpenStudio::Measure::ModelMeasure

  # Readable name
  def name
    return "Lighting Power Density Measure"
  end

  # Readable description
  def description
    return "This measures adjusts the LPD max for selected or all space types. It adjusts the LPD by scalar or actual value."
  end

  # Readable description of modeling approach
  def modeler_description
    return "Open Studio 2.4, April 2018"
  end

  # Define the arguments that the user will input
  def arguments(model)
    args = OpenStudio::Ruleset::OSArgumentVector.new

    # Make a choice argument for model objects
    space_type_handles = OpenStudio::StringVector.new
    space_type_display_names = OpenStudio::StringVector.new

    # Put model object and names into hash
    space_type_args = model.getSpaceTypes
    space_type_args_hash = {}
    space_type_args.each do |space_type_arg|
    space_type_args_hash[space_type_arg.name.to_s] = space_type_arg
    end

    # Loop through sorted hash of model objects
    space_type_args_hash.sort.map do |key,value|
      # Only include if space type is used in the model
      if value.spaces.size > 0
        space_type_handles << value.handle.to_s
        space_type_display_names << key
      end
    end

    # Add building to string vector with space type
    building = model.getBuilding
    space_type_handles << building.handle.to_s
    space_type_display_names << "*Entire Building*"

    # Make a choice argument for space type or entire building
    space_type = OpenStudio::Ruleset::OSArgument::makeChoiceArgument("space_type", space_type_handles, space_type_display_names,true)
    space_type.setDisplayName("List_of_space_types_to_apply")
    space_type.setDefaultValue("*Entire Building*") #if no space type is chosen this will run on the entire building
    args << space_type
    
    # Make a choice argument for LPD type , value(W/ft^2), value(W/m^2) or percent
    lpd_type_options = OpenStudio::StringVector.new
    lpd_type_options << "value(W/ft^2)"
    lpd_type_options << "value(W/m^2)"
    lpd_type_options << "percent"
    lpd_type= OpenStudio::Ruleset::OSArgument::makeChoiceArgument("lpd_type", lpd_type_options, true)
    lpd_type.setDisplayName("Lighting Power Density Type")
    lpd_type.setDefaultValue("percent") #if no lpd type is chosen, then percent is the default
    args << lpd_type

    # Make an argument LPD value
    lpd_value = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("lpd_value",true)
    lpd_value.setDisplayName("Lighting Power Density Value")
    lpd_value.setDefaultValue(0.8)
    args << lpd_value

    return args
  end

  # Define what happens when the measure is run
  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)

    # Use the built-in error checking
    if !runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end

    # Assign the user inputs to variables
    object = runner.getOptionalWorkspaceObjectChoiceValue("space_type",user_arguments,model)
    lpd_type= runner.getStringArgumentValue("lpd_type", user_arguments)
    lpd_value = runner.getDoubleArgumentValue("lpd_value",user_arguments)

    # Check the space_type for reasonableness and check if measure should run on space type or on the entire building
    apply_to_building = false
    space_type = nil
    if object.empty?
      handle = runner.getStringArgumentValue("space_type",user_arguments)
      if handle.empty?
        runner.registerError("No SpaceType was chosen.")
      else
        runner.registerError("The selected space type with handle '#{handle}' was not found in the model. It may have been removed by another measure.")
      end
      return false
    else
      if not object.get.to_SpaceType.empty?
        space_type = object.get.to_SpaceType.get
      elsif not object.get.to_Building.empty?
        apply_to_building = true
        #space_type = model.getSpaceTypes
      else
        runner.registerError("Script Error - argument not showing up as space type or building.")
        return false
      end
    end
	  
    # Check the LPD value for reasonableness
	 handle_lpdType = runner.getStringArgumentValue("lpd_type",user_arguments)
     handle_lpdValue = runner.getDoubleArgumentValue("lpd_value",user_arguments)
    if handle_lpdType == "value(W/ft^2)"
      puts ("The selected lpd type is '#{handle_lpdType}' that is equal to #{lpd_value} W/ft^2.")
      runner.registerInfo("The selected lpd type is '#{handle_lpdType}' that is equal to #{lpd_value} W/ft^2.")
          if handle_lpdValue < 0 
          runner.registerError("A Lighting Power Density of #{lpd_value} W/ft^2 is lower than the measure limit ( 0 W/ft^2) .")
          return false
          elsif handle_lpdValue> 50
          runner.registerError("A Lighting Power Density of #{lpd_value} W/ft^2 is above the measure limit (50 W/ft^2) .")
          return false
          elsif handle_lpdValue > 21
          runner.registerWarning("A Lighting Power Density of #{lpd_value} W/ft^2 is abnormally high.")
        end
    end    
    if handle_lpdType == "value(W/m^2)"
      puts ("The selected lpd type is '#{handle_lpdType}' that is equal to #{lpd_value} W/m^2.")
      runner.registerInfo("The selected lpd type is '#{handle_lpdType}' that is equal to #{lpd_value} W/m^2.")
        if handle_lpdValue < 0 
          runner.registerError("A Lighting Power Density of #{lpd_value} W/m^2 is lower than the measure limit (0 w/m^2) .")
          return false
		  elsif handle_lpdValue > 538
          runner.registerError("A Lighting Power Density of #{lpd_value} W/m^2 is above the measure limit (538 w/m^2).")
		  return false
          elsif handle_lpdValue > 226
          runner.registerWarning("A Lighting Power Density of #{lpd_value} W/m^2 is abnormally high.")
        end
    end    

    # Check the lighting power reduction percent for reasonableness
    if handle_lpdType == "percent"
    puts ("The selected lpd type is '#{handle_lpdType}' that is equal to #{lpd_value} %.")
    runner.registerInfo("The selected lpd type is '#{handle_lpdType}' that is equal to #{lpd_value} %.")
      if lpd_value > 100
        runner.registerError("Please Enter a Value less than or equal to 100 for the Lighting Power Reduction Percentage.")
        return false
        elsif lpd_value == 0
        runner.registerInfo("No lighting power adjustment requested, but some life cycle costs may still be affected.")
        elsif lpd_value < 1 and lpd_value > -1
        runner.registerWarning("A Lighting Power Reduction Percentage of #{lpd_value} percent is abnormally low.")
		elsif lpd_value > 90
        runner.registerWarning("A Lighting Power Reduction Percentage of #{lpd_value} percent is abnormally high.")
        elsif lpd_value < 0
        runner.registerInfo("The requested value for lighting power reduction percentage was negative. This will result in an increase in lighting power.")
      end
    end

    # Setup OpenStudio units that we will need
    unit_lpd_ip = OpenStudio::createUnit("W/ft^2").get
    unit_lpd_si = OpenStudio::createUnit("W/m^2").get
	
	# Report initial condition
    building = model.getBuilding
    building_start_lpd_si = OpenStudio::Quantity.new(building.lightingPowerPerFloorArea, unit_lpd_si)
    building_start_lpd_ip = OpenStudio::convert(building_start_lpd_si, unit_lpd_ip).get
    runner.registerInitialCondition("The model's initial LPD is #{building_start_lpd_si} (#{building_start_lpd_ip} ).")

	# Define starting units
	# Unit conversion of LPD from IP units (W/ft^2) to SI units (W/m^2), and vise versa.
	if handle_lpdType == "value(W/ft^2)"
    lpd_ip = OpenStudio::Quantity.new(lpd_value, unit_lpd_ip) 
    lpd_si = OpenStudio::convert(lpd_ip, unit_lpd_si).get
	# Unit conversion of lpd from SI units (W/m^2) to IP units (W/ft^2)
    elsif handle_lpdType == "value(W/m^2)"
	lpd_si = OpenStudio::Quantity.new(lpd_value, unit_lpd_si) 
    lpd_ip = OpenStudio::convert(lpd_si, unit_lpd_ip).get
	elsif handle_lpdType == "percent"
	lpd_si= building_start_lpd_si - (building_start_lpd_si*lpd_value*0.01)
	lpd_ip = OpenStudio::convert(lpd_si, unit_lpd_ip).get
	end
	
    # Add if statement for NA if LPD = 0
    if not building_start_lpd_ip.value > 0
      runner.registerAsNotApplicable("The model has no lights, nothing will be changed.")
    end

    # Create a new LightsDefinition and new Lights object to use with setLightingPowerPerFloorArea
    template_light_def = OpenStudio::Model::LightsDefinition.new(model)
    template_light_def.setName("LPD #{lpd_ip} - LightsDef")
    template_light_def.setWattsperSpaceFloorArea(lpd_si.value)
    template_light_inst = OpenStudio::Model::Lights.new(template_light_def)
    template_light_inst.setName("LPD #{lpd_ip} - LightsInstance")

    # Get space types in model
    if apply_to_building
      space_types = model.getSpaceTypes
    else
      space_types = []
      space_types << space_type #only run on a single space type
    end

    # Loop through space types
      space_types.each do |space_type|
      space_type_lights = space_type.lights
      space_type_spaces = space_type.spaces
      multiple_schedules = false
      space_type_lights_array = []

      # If space type has lights and is used in the model
      if space_type_lights.size > 0 and space_type_spaces.size > 0
        lights_schedules = []
        space_type_lights.each do |space_type_light|
          lights_data_for_array = []
          if not space_type_light.schedule.empty?
            space_type_light_new_schedule =  space_type_light.schedule
            if not space_type_light_new_schedule.empty?
              lights_schedules << space_type_light.powerPerFloorArea
              if not space_type_light.powerPerFloorArea.empty?
                lights_data_for_array << space_type_light.powerPerFloorArea.get
              else
                lights_data_for_array << 0.0
              end
              lights_data_for_array << space_type_light_new_schedule.get
              lights_data_for_array << space_type_light.isScheduleDefaulted
              space_type_lights_array << lights_data_for_array
            end
          end
        end

        # Pick schedule to use and check if it is defaulted
        space_type_lights_array = space_type_lights_array.sort.reverse[0]
        if not space_type_lights_array == nil #this is need if schedule is empty but also not defaulted
          if not space_type_lights_array[2] == true #if not schedule defaulted
            preferred_schedule = space_type_lights_array[1]
          else
            # Leave schedule blank, it is defaulted
          end
        end

        # Flag if lights_schedules has more than one unique object
        if lights_schedules.uniq.size > 1
          multiple_schedules = true
        end

        # Delete lights and luminaires and add in new light.
        space_type_lights = space_type.lights
        space_type_luminaires = space_type.luminaires
        space_type_lights.each do |space_type_light|
          space_type_light.remove
        end
        space_type_luminaires.each do |space_type_luminaire|
          space_type_luminaire.remove
        end
        space_type_light_new = template_light_inst.clone(model)
        space_type_light_new = space_type_light_new.to_Lights.get
        space_type_light_new.setSpaceType(space_type)

        # Assign preferred schedule to new lights object
        if not space_type_light_new.schedule.empty? and not space_type_lights_array[2] == true
          space_type_light_new.setSchedule(preferred_schedule)
        end

        # If schedules had to be removed due to multiple lights add warning
        if not space_type_light_new.schedule.empty? and multiple_schedules == true
          space_type_light_new_schedule = space_type_light_new.schedule
          runner.registerWarning("The space type named '#{space_type.name.to_s}' had more than one light object with unique schedules. The schedule named '#{space_type_light_new_schedule.get.name.to_s}' was used for the new LPD light object.")
        end

      elsif space_type_lights.size == 0 and space_type_spaces.size > 0
        runner.registerInfo("The space type named '#{space_type.name.to_s}' doesn't have any lights, none will be added.")
      end #end if space type has lights

    end #end space types each do

    # Get spaces in the model
    spaces = model.getSpaces

    # Get space types in model
    if apply_to_building
      spaces = model.getSpaces
    else
      if not space_type.spaces.empty?
        spaces = space_type.spaces #only run on a single space type
      end
    end

    spaces.each do |space|
      space_lights = space.lights
      space_luminaires = space.luminaires
      space_space_type = space.spaceType
      if not space_space_type.empty?
        space_space_type_lights = space_space_type.get.lights
      else
        space_space_type_lights = []
      end

      # Array to manage light schedules within a space
      space_lights_array = []

      # If space has lights and space type also has lights
      if space_lights.size > 0 and space_space_type_lights.size > 0
        # Loop through and remove all lights and luminaires
        space_lights.each do |space_light|
          space_light.remove
        end
        runner.registerWarning("The space named '#{space.name.to_s}' had one or more light objects. These were deleted and a new LPD light object was added to the parent space type named '#{space_space_type.get.name.to_s}'.")

        space_luminaires.each do |space_luminaire|
          space_luminaire.remove
        end
        if space_luminaires.size > 0
          runner.registerWarning("Luminaire objects have been removed. Their schedules were not taken into consideration when choosing schedules for the new LPD light object.")
        end

	  # If space has lights and space type has no lights
      elsif space_lights.size > 0 and space_space_type_lights.size == 0

        # Inspect schedules for light objects
        multiple_schedules = false
        lights_schedules = []
        space_lights.each do |space_light|
        lights_data_for_array = []
          if not space_light.schedule.empty?
            space_light_new_schedule =  space_light.schedule
            if not space_light_new_schedule.empty?
              lights_schedules << space_light.powerPerFloorArea
              if not space_light.powerPerFloorArea.empty?
                lights_data_for_array << space_light.powerPerFloorArea.get
              else
                lights_data_for_array << 0.0
              end
              lights_data_for_array << space_light_new_schedule.get
              lights_data_for_array << space_light.isScheduleDefaulted
              space_lights_array << lights_data_for_array
            end
          end
        end

        # Pick schedule to use and see if it is defaulted
        space_lights_array = space_lights_array.sort.reverse[0]
        if not space_lights_array == nil
          if not space_lights_array[2] == true
            preferred_schedule = space_lights_array[1]
          else
            # Leave schedule blank, it is defaulted
          end
        end

        # Flag if lights_schedules has more than one unique object
        if lights_schedules.uniq.size > 1
          multiple_schedules = true
        end

        space_lights.each do |space_light|
          space_light.remove
        end
        space_luminaires.each do |space_luminaire|
          space_luminaire.remove
        end
        space_light_new = template_light_inst.clone(model)
        space_light_new = space_light_new.to_Lights.get
        space_light_new.setSpace(space)

        # Assign preferred schedule to new lights object
        if not space_light_new.schedule.empty? and not space_type_lights_array[2] == true
          space_light_new.setSchedule(preferred_schedule)
        end

        # If schedules had to be removed due to multiple lights add warning here
        if not space_light_new.schedule.empty? and multiple_schedules == true
          space_light_new_schedule = space_light_new.schedule
          runner.registerWarning("The space type named '#{space.name.to_s}' had more than one light object with unique schedules. The schedule named '#{space_light_new_schedule.get.name.to_s}' was used for the new LPD light object.")
        end

      elsif space_lights.size == 0 and space_space_type_lights.size == 0
        # Issue warning that the space does not have any direct or inherited lights.
        runner.registerInfo("The space named '#{space.name.to_s}' does not have any direct or inherited lights.")

      end #end of if space and space type have lights

    end #end of loop through spaces

    # Clean up template light instance. EnergyPlus will fail if you have an instance that isn't associated with a space or space type
    template_light_inst.remove

    # Report final condition
    building_final_lpd_si = OpenStudio::Quantity.new(building.lightingPowerPerFloorArea, unit_lpd_si)
    building_final_lpd_ip = OpenStudio::convert(building_final_lpd_si, unit_lpd_ip).get
    runner.registerFinalCondition("Your model's final LPD is #{building_final_lpd_si} (#{building_final_lpd_ip}).")
    return true

	end
  
end

#Register the measure to be used by the application
LightingPowerDensityMeasure.new.registerWithApplication
