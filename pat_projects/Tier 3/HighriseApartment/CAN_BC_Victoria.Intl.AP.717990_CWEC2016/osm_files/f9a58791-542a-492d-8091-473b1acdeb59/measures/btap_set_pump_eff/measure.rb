# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/
require_relative 'resources/BTAPMeasureHelper'
# start the measure
class BTAPSetPumpEff < OpenStudio::Measure::ModelMeasure

  attr_accessor :use_json_package, :use_string_double
  #Adds helper functions to make life a bit easier and consistent.
  include(BTAPMeasureHelper)
  # human readable name
  def name
    #BEFORE YOU DO anything.. please generate a new <uid>224561f4-8ccc-4f60-8118-34b85359d6f7</uid> and add this to the measure.xml file
    # You can generate a new UUID using the ruby command
    # ruby -e 'require "securerandom";  puts SecureRandom.uuid '
    return "BTAPSetpumpEff"
  end

  # human readable description
  def description
    return "Sets all pump efficiency to specified value "
  end

  # human readable description of modeling approach
  def modeler_description
    return ""
  end

    # define the arguments that the user will input
    def arguments(model)
      args = OpenStudio::Measure::OSArgumentVector.new
  
      eff_for_this_cz = OpenStudio::Measure::OSArgument::makeDoubleArgument('eff_for_this_cz', false)
      eff_for_this_cz.setDisplayName('eff_for_this_cz')
      eff_for_this_cz.setDefaultValue(0.91)
  
      args << eff_for_this_cz
  
      return args
    end

  # define what happens when the measure is run
  def run(model, runner, user_arguments)
    #Runs parent run method.
    super(model, runner, user_arguments)
    # Gets arguments from interfaced and puts them in a hash with there display name. This also does a check on ranges to
    # ensure that the values inputted are valid based on your @measure_interface array of hashes.
    # use the built-in error checking
    if !runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end

    #You can now access the input argument by the name.
    eff_for_this_cz = runner.getDoubleArgumentValue('eff_for_this_cz',user_arguments)  
    
    if eff_for_this_cz == 999
      runner.registerInfo("BTAPSetPumpEff is skipped")

    else
      runner.registerInfo("BTAPSetPumpEff is not skipped")
      #if existing pump eff is
      model.getPumpConstantSpeeds.each do |pump|
        pump.setMotorEfficiency(eff_for_this_cz)
      end

      model.getPumpVariableSpeeds.each do |pump|
        pump.setMotorEfficiency(eff_for_this_cz)
      end
    end

    return true
  end
end


# register the measure to be used by the application
BTAPSetPumpEff.new.registerWithApplication
