# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/
require_relative 'resources/BTAPMeasureHelper'
# start the measure
class BTAPAlterSHGC < OpenStudio::Measure::ModelMeasure

  attr_accessor :use_json_package, :use_string_double
  #Adds helper functions to make life a bit easier and consistent.
  include(BTAPMeasureHelper)
  # human readable name
  def name
    #BEFORE YOU DO anything.. please generate a new <uid>224561f4-8ccc-4f60-8118-34b85359d6f7</uid> and add this to the measure.xml file
    # You can generate a new UUID using the ruby command
    # ruby -e 'require "securerandom";  puts SecureRandom.uuid '
    return "BTAPAlterSHGC"
  end

  # human readable description
  def description
    return "Changes SHGC of simple glazing systems"
  end

  # human readable description of modeling approach
  def modeler_description
    return "Get simple glazing systems and change the SHGC "
  end

    # define the arguments that the user will input
    def arguments(model)
      args = OpenStudio::Measure::OSArgumentVector.new
  
      new_shgc = OpenStudio::Measure::OSArgument::makeDoubleArgument('new_shgc', false)
      new_shgc.setDisplayName('new_shgc')
      new_shgc.setDefaultValue(0.3)
  
      args << new_shgc
  
      return args
    end

  # define what happens when the measure is run
  def run(model, runner, user_arguments)
    #Runs parent run method.
    super(model, runner, user_arguments)
    # Gets arguments from interfaced and puts them in a hash with there display name. This also does a check on ranges to
    # ensure that the values inputted are valid based on your @measure_interface array of hashes.
    if !runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end
  

    new_shgc =runner.getDoubleArgumentValue('new_shgc',user_arguments)
    
    if new_shgc == 999
      runner.registerInfo("BTAPAlterSHGC is skipped")
    else
      runner.registerInfo("BTAPAlterSHGC is not skipped")
      model.getSimpleGlazings.each do|sim_glaz|
        sim_glaz.setSolarHeatGainCoefficient(new_shgc)
      end
    end


    
    return true
  end
end


# register the measure to be used by the application
BTAPAlterSHGC.new.registerWithApplication
