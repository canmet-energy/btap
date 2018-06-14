# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/
require_relative 'resources/BTAPMeasureHelper'

# start the measure
class BTAPIdealAirLoadsMeasure < OpenStudio::Measure::ModelMeasure

  attr_accessor :use_json_package, :use_string_double
  #Adds helper functions to make life a bit easier and consistent.
  include(BTAPMeasureHelper)
  # human readable name
  def name
    #BEFORE YOU DO anything.. please generate a new <uid>224561f4-8ccc-4f60-8118-34b85359d6f7</uid> and add this to the measure.xml file
    # You can generate a new UUID using the ruby command
    # ruby -e 'require "securerandom";  puts SecureRandom.uuid '
    return "BTAPIdealAirLoadsMeasure"
  end

  # human readable description
  def description
    return "This measure will remove all HVAC and apply ideal air loads and remove outdoor air."
  end

  # human readable description of modeling approach
  def modeler_description
    return "This measure will remove all HVAC and apply ideal air loads and remove outdoor air."
  end

  #Use the constructor to set global variables
  def initialize()
    super()
    #Set to true if you want to package the arguments as json.
    @use_json_package = false
    #Set to true if you want to want to allow strings and doubles in stringdouble types. Set to false to force to use doubles. The latter is used for certain
    # continuous optimization algorithms. You may have to re-examine your input in PAT as this fundamentally changes the measure.
    @use_string_double = true

    # Put in this array of hashes all the input variables that you need in your measure. Your choice of types are Sting, Double,
    # StringDouble, and Choice. Optional fields are valid strings, max_double_value, and min_double_value. This will
    # create all the variables, validate the ranges and types you need,  and make them available in the 'run' method as a hash after
    # you run 'arguments = validate_and_get_arguments_in_hash(model, runner, user_arguments)'
    @measure_interface_detailed = []
  end

  # define what happens when the measure is run
  def run(model, runner, user_arguments)
    #Runs parent run method.
    super(model, runner, user_arguments)
    arguments = validate_and_get_arguments_in_hash(model, runner, user_arguments)
    return false if false == arguments

    #assign the user inputs to variables

    # array of zones initially using ideal air loads
    startingIdealAir = []

    BTAP::Resources::HVAC.clear_all_hvac_from_model(model)

    thermalZones = model.getThermalZones
    thermalZones.each do |zone|
      if zone.useIdealAirLoads
        startingIdealAir << zone
      else
        zone.setUseIdealAirLoads(true)
      end
    end

    #reporting initial condition of model
    runner.registerInitialCondition("In the initial model #{startingIdealAir.size} zones use ideal air loads.")

    #reporting final condition of model
    finalIdealAir = []
    thermalZones.each do |zone|
      if zone.useIdealAirLoads
        finalIdealAir << zone
      end
    end
    runner.registerFinalCondition("In the final model #{finalIdealAir.size} zones use ideal air loads.")
    return true
  end
end


# register the measure to be used by the application
BTAPIdealAirLoadsMeasure.new.registerWithApplication
