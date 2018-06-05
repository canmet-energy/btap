# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/

require 'erb'

#start the measure
class BTAPReportVariables < OpenStudio::Measure::ReportingMeasure

  # human readable name
  def name
    return "BTAPReportVariables"
  end

  # human readable description
  def description
    return "Adds E+ output variables.   Does not create a report."
  end

  # human readable description of modeling approach
  def modeler_description
    return "Get output variables from a E+ run and enter them in the variables as an array like '[\"variable_name_1\",\"variable_name_2\"]' and set the reporting frequency accordingly."
  end

  # define the arguments that the user will input
  def arguments()
    args = OpenStudio::Ruleset::OSArgumentVector.new

    variable_names = OpenStudio::Ruleset::OSArgument::makeStringArgument('variable_names', true)
    variable_names.setDisplayName("variable_names")
    variable_names.setDefaultValue('[
        "Heating Coil Air Heating Rate",
        "Boiler Heating Rate","Cooling Coil Total Cooling Rate",
        "Water Heater Heating Rate",
        "Facility Total Electric Demand Power",
        "Zone Air System Sensible Heating Rate",
        "Zone Air System Sensible Cooling Rate",
        "Zone Total Internal Total Heating Rate",
        "Zone Total Internal Latent Gain rate",
        "Total Internal Radiant Heating Rate",
        "Total Internal Convective Heating Rate",
        "Zone Air Heat Balance Outdoor Air Transfer Rate"
      ]')
    args << variable_names


    #make an argument for the timestep
    reporting_frequency_chs = OpenStudio::StringVector.new
    reporting_frequency_chs << "detailed"
    reporting_frequency_chs << "timestep"
    reporting_frequency_chs << "hourly"
    reporting_frequency = OpenStudio::Ruleset::OSArgument::makeChoiceArgument('reporting_frequency', reporting_frequency_chs, true)
    reporting_frequency.setDisplayName("Reporting Frequency.")
    reporting_frequency.setDefaultValue("timestep")
    args << reporting_frequency

    return args
  end

  # return a vector of IdfObject's to request EnergyPlus objects needed by the run method
  def energyPlusOutputRequests(runner, user_arguments)
    super(runner, user_arguments)

    result = OpenStudio::IdfObjectVector.new

    # use the built-in error checking 
    if !runner.validateUserArguments(arguments(), user_arguments)
      return result
    end

    variable_names = runner.getStringArgumentValue("variable_names", user_arguments)
    reporting_frequency = runner.getStringArgumentValue("reporting_frequency", user_arguments)

    out_var_names = []
    #convert string to array
    eval("out_var_names = #{variable_names}")

    # Request the variables
    out_var_names.each do |out_var_name|
      request = OpenStudio::IdfObject.load("Output:Variable,*,#{out_var_name},#{reporting_frequency};").get
      result << request
      runner.registerInfo("Adding output variable for '#{out_var_name}' reporting #{reporting_frequency}")
    end

    return result
  end

  # define what happens when the measure is run
  def run(runner, user_arguments)
    super(runner, user_arguments)

    # use the built-in error checking 
    if !runner.validateUserArguments(arguments(), user_arguments)
      return false
    end

    # get the last model and sql file
    model = runner.lastOpenStudioModel
    if model.empty?
      runner.registerError("Cannot find last model.")
      return false
    end
    model = model.get

    sqlFile = runner.lastEnergyPlusSqlFile
    if sqlFile.empty?
      runner.registerError("Cannot find last sql file.")
      return false
    end
    sqlFile = sqlFile.get
    model.setSqlFile(sqlFile)

    web_asset_path = OpenStudio.getSharedResourcesPath() / OpenStudio::Path.new("web_assets")

    # close the sql file
    sqlFile.close()

    return true

  end

end

# register the measure to be used by the application
BTAPReportVariables.new.registerWithApplication
