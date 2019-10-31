require_relative 'resources/BTAPMeasureHelper'

# start the measure
class BTAPSetNECBInfiltration < OpenStudio::Measure::ModelMeasure
  attr_accessor :use_json_package, :use_string_double
  #Adds helper functions to make life a bit easier and consistent.
  include(BTAPMeasureHelper)

  # define the name that a user will see
  def name
    return 'BTAPSetNECBInfiltration'
  end

  # human readable description
  def description
    return "This measure will set a new space infiltration flow rate as per NECB. Input is in L/(s*m2)@75Pa."
  end

  # human readable description of modeling approach
  def modeler_description
   return "This measure will set a new space infiltration flow rate using the 'Flow per Exterior Surface Area' at at 75 Pa. User will enter si units and the value will be converted to a flow rate at 5Pa as per NECB assumptions and exponent of 0.65."
  end

  def initialize()
    super()
    #Set to true if you want to package the arguments as json.
    @use_json_package = false
    #Set to true if you want to want to allow strings and doubles in stringdouble types. Set to false to force to use doubles. The latter is used for certain
    # continuous optimization algorithms. You may have to re-examine your input in PAT as this fundamentally changes the measure.
    @use_string_double = true

    model = OpenStudio::Model::Model.new

    @measure_interface_detailed = [
        {
            "name" => "infiltration_si",
            "type" => "Double",
            "display_name" => "Space Infiltration Flow per Exterior Envelope Surface Area L/(s*m2) at 75 Pa. ",
            "default_value" => 1.50,
            "max_double_value" => 20.00,
            "min_double_value" => 0.00,
            "is_required" => true
        }
    ]
  end

  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)

    # Gets arguments from interfaced and puts them in a hash with there display name. This also does a check on ranges to
    # ensure that the values inputted are valid based on your @measure_interface array of hashes.
    arguments = validate_and_get_arguments_in_hash(model, runner, user_arguments)

    #puts JSON.pretty_generate(arguments)
    return false if false == arguments

    # assign the user inputs to variables
    infiltration_si = arguments['infiltration_si']

    infiltration_si_m3 = infiltration_si * 0.001 # to convert from L/(s*m2) to m3/(s*m2) multiply by 0.001
    infiltration_si_5Pa = infiltration_si_m3 * 0.172004845 # to convert from 75 Pa to 5 Pa multiply by (5/75)^0.65 ~ 0.172004845

    # get space infiltration objects used in the model
    space_infiltration_objects = model.getSpaceInfiltrationDesignFlowRates

    #loop through all infiltration objects and set to the new inflitration flow rate
    space_infiltration_objects.each do |space_infiltration_object|
      space_infiltration_object.setFlowperExteriorSurfaceArea(infiltration_si_5Pa)
    end

    return true
  end
end

# this allows the measure to be used by the application
BTAPSetNECBInfiltration.new.registerWithApplication
