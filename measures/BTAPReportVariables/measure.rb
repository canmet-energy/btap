# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/

require 'erb'

#start the measure
class BTAPReportVariables < OpenStudio::Ruleset::ReportingUserScript

  # human readable name
  def name
    return "BTAP Zone Report Variables"
  end

  # human readable description
  def description
    return "Adds a bunch of output variables that are useful for understanding zone conditions.  Does not create a report."
  end

  # human readable description of modeling approach
  def modeler_description
    return ""
  end

  # define the arguments that the user will input
  def arguments()
    args = OpenStudio::Ruleset::OSArgumentVector.new

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
    
    reporting_frequency = runner.getStringArgumentValue("reporting_frequency",user_arguments)

    out_var_names = []
    
    # Outdoor Air conditions
    #out_var_names << "Heating Coil Air Heating Energy"
    out_var_names << "Heating Coil Air Heating Rate"

    out_var_names << "Boiler Heating Rate"
    #out_var_names << "Boiler Heating Energy"

    out_var_names << "Cooling Coil Total Cooling Rate"
    #out_var_names << "Cooling Coil Total Cooling Energy"

    out_var_names << "Water Heater Heating Rate"
    #out_var_names << "Water Heater Heating Energy"

    #out_var_names << "Facility Total HVAC Electric Demand Power"
    out_var_names << "Facility Total Electric Demand Power"

    #out_var_names << "Heating Coil Gas Energy"
    #out_var_names << "Heating Coil Gas Rate"
    #out_var_names << "Heating Coil Electric Energy"
    #out_var_names << "Heating Coil Electric Power"

    #out_var_names << "Cooling Coil Sensible Cooling Rate"
    #out_var_names << "Cooling Coil Sensible Cooling Energy"
    #out_var_names << "Cooling Coil Latent Cooling Rate"
    #out_var_names << "Cooling Coil Latent Cooling Energy"
    #out_var_names << "Cooling Coil Electric Power"
    #out_var_names << "Cooling Coil Electric Energy"
    #out_var_names << "Cooling Coil Runtime Fraction"
    #out_var_names << "Coil System Part Load Ratio"
    #out_var_names << "Coil System Frost Control Status"

    out_var_names << 'Zone Air System Sensible Heating Rate'
    out_var_names << 'Zone Air System Sensible Cooling Rate'
    #out_var_names << 'Zone Total Internal Total Heating Energy'
    out_var_names << 'Zone Total Internal Total Heating Rate'
    #out_var_names << 'Zone Total Internal Latent Gain Energy'
    out_var_names << 'Zone Total Internal Latent Gain rate'

    out_var_names << 'Total Internal Radiant Heating Rate'
    out_var_names << 'Total Internal Convective Heating Rate'
    out_var_names << 'Zone Air Heat Balance Outdoor Air Transfer Rate'



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
