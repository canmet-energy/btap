module BTAPMeasureHelper

  # =============================================================================================================================
  # define the arguments that the user will input
  def arguments(model)
    args = OpenStudio::Measure::OSArgumentVector.new

    if true == @use_json_package
      #Set up package version of input.
      json_default = {}
      @measure_interface_detailed.each do |argument|
        json_default[argument['name']] = argument["default_value"]
      end
      default = JSON.pretty_generate(json_default)
      arg = OpenStudio::Ruleset::OSArgument.makeStringArgument('json_input', true)
      arg.setDisplayName('Contains a json version of the input as a single package.')
      arg.setDefaultValue(default)
      args << arg
    else
      # Conductances for all surfaces and subsurfaces.
      @measure_interface_detailed.each do |argument|
        arg = nil
        statement = nil
        case argument['type']
          when "String"
            arg = OpenStudio::Ruleset::OSArgument.makeStringArgument(argument['name'], argument['is_required'])
            arg.setDisplayName(argument['display_name'])
            arg.setDefaultValue(argument['default_value'].to_s)

          when "Double"
            arg = OpenStudio::Ruleset::OSArgument.makeDoubleArgument(argument['name'], argument['is_required'])
            arg.setDisplayName("#{argument['display_name']}")
            arg.setDefaultValue("#{argument['default_value']}".to_f)

          when "Choice"
            arg = OpenStudio::Measure::OSArgument.makeChoiceArgument(argument['name'], argument['choices'], argument['is_required'])
            arg.setDisplayName(argument['display_name'])
            arg.setDefaultValue(argument['default_value'].to_s)
            puts arg.defaultValueAsString

          when "Bool"
            arg = OpenStudio::Measure::OSArgument.makeBoolArgument(argument['name'], argument['is_required'])
            arg.setDisplayName(argument['display_name'])
            arg.setDefaultValue(argument['default_value'])


          when "StringDouble"
            if @use_string_double == false
              arg = OpenStudio::Ruleset::OSArgument.makeDoubleArgument(argument['name'], argument['is_required'])
              arg.setDefaultValue(argument['default_value'].to_f)
            else
              arg = OpenStudio::Ruleset::OSArgument.makeStringArgument(argument['name'], argument['is_required'])
              arg.setDefaultValue(argument['default_value'].to_s)
            end
            arg.setDisplayName(argument['display_name'])
        end
        args << arg
      end
    end
    return args
  end

  # =============================================================================================================================
  #returns a hash of the user inputs for you to use in your measure.
  def get_hash_of_arguments(user_arguments, runner)
    values = {}
    if @use_json_package
      return JSON.parse(runner.getStringArgumentValue('json_input', user_arguments))
    else

      @measure_interface_detailed.each do |argument|

        case argument['type']
          when "String", "Choice"
            values[argument['name']] = runner.getStringArgumentValue(argument['name'], user_arguments)
          when "Double"
            values[argument['name']] = runner.getDoubleArgumentValue(argument['name'], user_arguments)
          when "Bool"
            values[argument['name']] = runner.getBoolArgumentValue(argument['name'], user_arguments)
          when "StringDouble"
            value = nil
            if @use_string_double == false
              value = (runner.getDoubleArgumentValue(argument['name'], user_arguments).to_f)
            else
              value = runner.getStringArgumentValue(argument['name'], user_arguments)
              if valid_float?(value)
                value = value.to_f
              end
            end
            values[argument['name']] = value
        end
      end
    end
    return values
  end

  # =============================================================================================================================
  # boilerplate that validated ranges of inputs.
  def validate_and_get_arguments_in_hash(model, runner, user_arguments)
    return_value = true
    values = get_hash_of_arguments(user_arguments, runner)
    # use the built-in error checking
    if !runner.validateUserArguments(arguments(model), user_arguments)
      runner_register(runner, 'Error', "validateUserArguments failed... Check the argument definition for errors.")
      return_value = false
    end

    # Validate arguments
    errors = ""
    @measure_interface_detailed.each do |argument|
      case argument['type']
        when "Double"
          value = values[argument['name']]
          if (not argument["max_double_value"].nil? and value.to_f > argument["max_double_value"].to_f) or
              (not argument["min_double_value"].nil? and value.to_f < argument["min_double_value"].to_f)
            error = "#{argument['name']} must be between #{argument["min_double_value"]} and #{argument["max_double_value"]}. You entered #{value.to_f} for this #{argument['name']}.\n Please enter a value withing the expected range.\n"
            errors << error
          end
        when "StringDouble"
          value = values[argument['name']]
          if (not argument["valid_strings"].include?(value)) and (not valid_float?(value))
            error = "#{argument['name']} must be a string that can be converted to a float, or one of these #{argument["valid_strings"]}. You have entered #{value}\n"
            errors << error
          elsif (not argument["max_double_value"].nil? and value.to_f > argument["max_double_value"]) or
              (not argument["min_double_value"].nil? and value.to_f < argument["min_double_value"])
            error = "#{argument['name']} must be between #{argument["min_double_value"]} and #{argument["max_double_value"]}. You entered #{value} for #{argument['name']}. Please enter a stringdouble value in the expected range.\n"
            errors << error
          end
      end
    end
    #If any errors return false, else return the hash of argument values for user to use in measure.
    if errors != ""
      runner.registerError(errors)
      return false
    end
    return values
  end

  # Helper method to see if str is a valid float.
  def valid_float?(str)
    !!Float(str) rescue false
  end


  # =============================================================================================================================
  def model_run_simulation_and_log_errors(model, run_dir = "#{Dir.pwd}/Run")
    # Make the directory if it doesn't exist
    unless Dir.exist?(run_dir)
      FileUtils.mkdir_p(run_dir)
    end

    # Save the model to energyplus idf
    idf_name = 'in.idf'
    osm_name = 'in.osm'
    osw_name = 'in.osw'
    OpenStudio.logFree(OpenStudio::Debug, 'openstudio.model.Model', "Starting simulation here: #{run_dir}.")
    OpenStudio.logFree(OpenStudio::Info, 'openstudio.model.Model', "Running simulation #{run_dir}.")
    forward_translator = OpenStudio::EnergyPlus::ForwardTranslator.new
    idf = forward_translator.translateModel(model)
    idf_path = OpenStudio::Path.new("#{run_dir}/#{idf_name}")
    osm_path = OpenStudio::Path.new("#{run_dir}/#{osm_name}")
    osw_path = OpenStudio::Path.new("#{run_dir}/#{osw_name}")
    idf.save(idf_path, true)
    model.save(osm_path, true)

    # Set up the simulation
    # Find the weather file
    epw_path = model_get_full_weather_file_path(model)
    if epw_path.empty?
      return false
    end
    epw_path = epw_path.get

    # close current sql file
    model.resetSqlFile

    # If running on a regular desktop, use RunManager.
    # If running on OpenStudio Server, use WorkFlowMananger
    # to avoid slowdown from the run.
    use_runmanager = true

    begin
      workflow = OpenStudio::WorkflowJSON.new
      use_runmanager = false
    rescue NameError
      use_runmanager = true
    end

    sql_path = nil
    if use_runmanager
      OpenStudio.logFree(OpenStudio::Debug, 'openstudio.model.Model', 'Running with RunManager.')

      # Find EnergyPlus
      ep_dir = OpenStudio.getEnergyPlusDirectory
      ep_path = OpenStudio.getEnergyPlusExecutable
      ep_tool = OpenStudio::Runmanager::ToolInfo.new(ep_path)
      idd_path = OpenStudio::Path.new(ep_dir.to_s + '/Energy+.idd')
      output_path = OpenStudio::Path.new("#{run_dir}/")

      # Make a run manager and queue up the run
      run_manager_db_path = OpenStudio::Path.new("#{run_dir}/run.db")
      # HACK: workaround for Mac with Qt 5.4, need to address in the future.
      OpenStudio::Application.instance.application(false)
      run_manager = OpenStudio::Runmanager::RunManager.new(run_manager_db_path, true, false, false, false)
      job = OpenStudio::Runmanager::JobFactory.createEnergyPlusJob(ep_tool,
                                                                   idd_path,
                                                                   idf_path,
                                                                   epw_path,
                                                                   output_path)

      run_manager.enqueue(job, true)

      # Start the run and wait for it to finish.
      while run_manager.workPending
        sleep 1
        OpenStudio::Application.instance.processEvents
      end

      sql_path = OpenStudio::Path.new("#{run_dir}/EnergyPlus/eplusout.sql")

      OpenStudio.logFree(OpenStudio::Info, 'openstudio.model.Model', 'Finished run.')

    else # method to running simulation within measure using OpenStudio 2.x WorkflowJSON

      OpenStudio.logFree(OpenStudio::Debug, 'openstudio.model.Model', 'Running with OS 2.x WorkflowJSON.')

      # Copy the weather file to this directory
      epw_name = 'in.epw'
      begin
        FileUtils.copy(epw_path.to_s, "#{run_dir}/#{epw_name}")
      rescue
        OpenStudio.logFree(OpenStudio::Error, 'openstudio.model.Model', "Due to limitations on Windows file path lengths, this measure won't work unless your project is located in a directory whose filepath is less than 90 characters long, including slashes.")
        return false
      end

      workflow.setSeedFile(osm_name)
      workflow.setWeatherFile(epw_name)
      workflow.saveAs(File.absolute_path(osw_path.to_s))

      cli_path = OpenStudio.getOpenStudioCLI
      cmd = "\"#{cli_path}\" run -w \"#{osw_path}\""
      puts cmd
      system(cmd)

      OpenStudio.logFree(OpenStudio::Info, 'openstudio.model.Model', 'Finished run.')

      sql_path = OpenStudio::Path.new("#{run_dir}/run/eplusout.sql")

    end

    # TODO: Delete the eplustbl.htm and other files created
    # by the run for cleanliness.

    if OpenStudio.exists(sql_path)
      sql = OpenStudio::SqlFile.new(sql_path)
      # Check to make sure the sql file is readable,
      # which won't be true if EnergyPlus crashed during simulation.
      unless sql.connectionOpen
        OpenStudio.logFree(OpenStudio::Error, 'openstudio.model.Model', "The run failed, cannot create model.  Look at the eplusout.err file in #{File.dirname(sql_path.to_s)} to see the cause.")
        return false
      end
      # Attach the sql file from the run to the model
      model.setSqlFile(sql)
    else
      OpenStudio.logFree(OpenStudio::Error, 'openstudio.model.Model', "Results for the run couldn't be found here: #{sql_path}.")
      return false
    end

    # Report severe errors in the run
    error_query = "SELECT ErrorMessage
        FROM Errors
        WHERE ErrorType in(1,2)"
    errs = model.sqlFile.get.execAndReturnVectorOfString(error_query)
    if errs.is_initialized
      errs = errs.get
    end

    # Check that the run completed
    completed_query = 'SELECT Completed FROM Simulations'
    completed = model.sqlFile.get.execAndReturnFirstDouble(completed_query)
    if completed.is_initialized
      completed = completed.get
      if completed.zero?
        OpenStudio.logFree(OpenStudio::Error, 'openstudio.model.Model', "The run did not finish and had following errors: #{errs.join('\n')}")
        return false
      end
    end

    # Check that the run completed with no severe errors
    completed_successfully_query = 'SELECT CompletedSuccessfully FROM Simulations'
    completed_successfully = model.sqlFile.get.execAndReturnFirstDouble(completed_successfully_query)
    if completed_successfully.is_initialized
      completed_successfully = completed_successfully.get
      if completed_successfully.zero?
        OpenStudio.logFree(OpenStudio::Error, 'openstudio.model.Model', "The run failed with the following severe or fatal errors: #{errs.join('\n')}")
        return false
      end
    end

    # Log any severe errors that did not cause simulation to fail
    unless errs.empty?
      OpenStudio.logFree(OpenStudio::Warn, 'openstudio.model.Model', "The run completed but had the following severe errors: #{errs.join('\n')}")
    end

    return true
  end

  # =============================================================================================================================
  def get_surfaces_from_thermal_zones(thermal_zone_array)
    surfaces = Array.new()
    thermal_zone_array.each do |thermal_zone|
      thermal_zone.spaces.sort.each do |space|
        surfaces.concat(space.surfaces())
      end
      return surfaces
    end
  end

  # =============================================================================================================================
  # Method to check if all zones have surfaces. This is required to run a simulation.
  def model_do_all_zones_have_surfaces?(model)
    error_string = ''
    error = false
    # Check to see if all zones have surfaces.
    model.getThermalZones.each do |zone|
      if get_surfaces_from_thermal_zones([zone]).empty?
        error_string << "Error: Thermal zone #{zone.name} does not contain surfaces.\n"
        error = true
      end
      if error == true
        puts error_string
        OpenStudio.logFree(OpenStudio::Error, 'openstudio.Siz.Model', error_string)
        return false
      else
        return true
      end
    end
  end
  
  # =============================================================================================================================
  # A helper method to run a sizing run and pull any values calculated during
  # autosizing back into the model.
  def model_run_sizing_run(model, sizing_run_dir = "#{Dir.pwd}/SR")
    # Change the simulation to only run the sizing days
    sim_control = model.getSimulationControl
    sim_control.setRunSimulationforSizingPeriods(true)
    sim_control.setRunSimulationforWeatherFileRunPeriods(false)

    # check that all zones have surfaces.
    raise 'Error: Sizing Run Failed. Thermal Zones with no surfaces exist.' unless model_do_all_zones_have_surfaces?(model)
    # Run the sizing run
    success = model_run_simulation_and_log_errors(model, sizing_run_dir)

    # Change the model back to running the weather file
    sim_control.setRunSimulationforSizingPeriods(false)
    sim_control.setRunSimulationforWeatherFileRunPeriods(true)

    return success
  end

  # =============================================================================================================================
  # A helper method to run a sizing run and pull any values calculated during
  # autosizing back into the model.
  def model_run_space_sizing_run(sizing_run_dir = "#{Dir.pwd}/SpaceSR")
    puts '*************Runing sizing space Run ***************************'
    # Make copy of model
    model = BTAP::FileIO.deep_copy(model, true)
    space_load_array = []

    # Make sure the model is good to run.
    # 1. Ensure External surfaces are set to a construction
    ext_surfaces = BTAP::Geometry::Surfaces.filter_by_boundary_condition(model.getSurfaces, ['Outdoors',
                                                                                             'Ground',
                                                                                             'GroundFCfactorMethod',
                                                                                             'GroundSlabPreprocessorAverage',
                                                                                             'GroundSlabPreprocessorCore',
                                                                                             'GroundSlabPreprocessorPerimeter',
                                                                                             'GroundBasementPreprocessorAverageWall',
                                                                                             'GroundBasementPreprocessorAverageFloor',
                                                                                             'GroundBasementPreprocessorUpperWall',
                                                                                             'GroundBasementPreprocessorLowerWall'])
    fail = false
    ext_surfaces.each do |surface|
      if surface.construction.nil?
        OpenStudio.logFree(OpenStudio::Error, 'openstudio.model.Model', "Ext Surface #{surface.name} does not have a construction.Cannot perform sizing.")
        fail = true
      end
    end
    puts "#{ext_surfaces.size} External Surfaces counted."
    raise "Can't run sizing since envelope is not set." if fail == true

    # remove any thermal zones.
    model.getThermalZones.each(&:remove)

    # assign a zone to each space.
    # Create a thermal zone for each space in the model
    model.getSpaces.each do |space|
      zone = OpenStudio::Model::ThermalZone.new(model)
      zone.setName("#{space.name} ZN")
      space.setThermalZone(zone)
    end
    # Add a thermostat
    BTAP::Compliance::NECB2011.set_zones_thermostat_schedule_based_on_space_type_schedules(model)
    OpenStudio.logFree(OpenStudio::Info, 'openstudio.model.Model', 'Finished creating thermal zones')
    # Add ideal loads to every zone/space and run
    # a sizing run to determine heating/cooling loads,
    # which will impact HVAC systems.
    model.getThermalZones.each do |zone|
      ideal_loads = OpenStudio::Model::ZoneHVACIdealLoadsAirSystem.new(model)
      ideal_loads.addToThermalZone(zone)
    end
    model_run_sizing_run(model, sizing_run_dir)
    model.getSpaces.each do |space|
      unless space.thermalZone.empty?
        space_load_array << { 'space_name' => space.name, 'CoolingDesignLoad' => space.thermalZone.get.coolingDesignLoad, 'HeatingDesignLoad' => space.thermalZone.get.heatingDesignLoad }
      end
    end
    puts space_load_array
    puts '*************Done Runing sizing space Run ***************************'
    return model
  end

  # =============================================================================================================================
  # Get the full path to the weather file that is specified in the model.
  #
  # @return [OpenStudio::OptionalPath]
  def model_get_full_weather_file_path(model)
    full_epw_path = OpenStudio::OptionalPath.new

    if model.weatherFile.is_initialized
      epw_path = model.weatherFile.get.path
      if epw_path.is_initialized
        if File.exist?(epw_path.get.to_s)
          full_epw_path = OpenStudio::OptionalPath.new(epw_path.get)
        else
          # If this is an always-run Measure, need to check a different path
          alt_weath_path = File.expand_path(File.join(Dir.pwd, '../../resources'))
          alt_epw_path = File.expand_path(File.join(alt_weath_path, epw_path.get.to_s))
          if File.exist?(alt_epw_path)
            full_epw_path = OpenStudio::OptionalPath.new(OpenStudio::Path.new(alt_epw_path))
          else
            OpenStudio.logFree(OpenStudio::Error, 'openstudio.standards.Model', "Model has been assigned a weather file, but the file is not in the specified location of '#{epw_path.get}'.")
          end
        end
      else
        OpenStudio.logFree(OpenStudio::Error, 'openstudio.standards.Model', 'Model has a weather file assigned, but the weather file path has been deleted.')
      end
    else
      OpenStudio.logFree(OpenStudio::Error, 'openstudio.standards.Model', 'Model has not been assigned a weather file.')
    end

    return full_epw_path
  end

  # =============================================================================================================================
  # A helper method to get component sizes from the model
  # returns the autosized value as an optional double
  def getAutosizedValue(model, object, value_name, units)

    result = OpenStudio::OptionalDouble.new

    name = object.name.get.upcase

    object_type = object.iddObject.type.valueDescription.gsub('OS:','')

    # Special logic for two coil types which are inconsistently
    # uppercase in the sqlfile:
    object_type = object_type.upcase if object_type == 'Coil:Cooling:WaterToAirHeatPump:EquationFit'
    object_type = object_type.upcase if object_type == 'Coil:Heating:WaterToAirHeatPump:EquationFit'
		object_type = 'Coil:Heating:GasMultiStage' if object_type == 'Coil:Heating:Gas:MultiStage'
		object_type = 'Coil:Heating:Fuel' if object_type == 'Coil:Heating:Gas'

    sql = model.sqlFile

    if sql.is_initialized
      sql = sql.get

      #SELECT * FROM ComponentSizes WHERE CompType = 'Coil:Heating:Gas' AND CompName = "COIL HEATING GAS 3" AND Description = "Design Size Nominal Capacity"
      query = "SELECT Value 
              FROM ComponentSizes 
              WHERE CompType='#{object_type}' 
              AND CompName='#{name}' 
              AND Description='#{value_name.strip}' 
              AND Units='#{units}'"
              
      val = sql.execAndReturnFirstDouble(query)

      if val.is_initialized
        result = OpenStudio::OptionalDouble.new(val.get)
      else
        # TODO: comment following line (debugging new HVACsizing objects right now)
        # OpenStudio::logFree(OpenStudio::Warn, "openstudio.model.Model", "QUERY ERROR: Data not found for query: #{query}")
      end
    else
      OpenStudio::logFree(OpenStudio::Error, 'openstudio.model.Model', 'Model has no sql file containing results, cannot lookup data.')
    end

    return result
  end

end
