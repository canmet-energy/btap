require_relative 'resources/BTAPMeasureHelper'

# start the measure
class BTAPSetInfiltration < OpenStudio::Measure::ModelMeasure
  attr_accessor :use_json_package, :use_string_double
  #Adds helper functions to make life a bit easier and consistent.
  include(BTAPMeasureHelper)

  # define the name that a user will see
  def name
    return 'BTAPSetInfiltration'
  end

  # human readable description
  def description
    return "This measure will set a new space infiltration flow rate in L/(s*m2)."
  end

  # human readable description of modeling approach
  def modeler_description
    return "This measure will set a new space infiltration flow rate using the 'Flow per Exterior Surface Area' at at 75 Pa. User will enter si units ."
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
            "max_double_value" => 10.00,
            "min_double_value" => 0.00,
            "is_required" => true
        },
        {
            "name" => "material_cost_si",
            "type" => "Double",
            "display_name" => "Increase in Material and Installation Costs for Building per Exterior Envelope Area ($/m^2).",
            "default_value" => 0.00,
            "max_double_value" => 1000.00,
            "min_double_value" => 0.00,
            "is_required" => true
        },

        {
            "name" => "om_cost_si",
            "type" => "Double",
            "display_name" => "O & M Costs for Construction per Area Used ($/m^2).",
            "default_value" => 0.00,
            "max_double_value" => 1000.00,
            "min_double_value" => 0.00,
            "is_required" => true
        },

        {
            "name" => "om_frequency",
            "type" => "Double",
            "display_name" => "O & M Frequency (whole years).",
            "default_value" => 1.00,
            "max_double_value" => 100.00,
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
    material_cost_si = arguments['material_cost_si']
    om_cost_si = arguments['om_cost_si']
    om_frequency = arguments['om_frequency']

    infiltration_si_m3 = infiltration_si * 0.001 # to convert from L/(s*m2) to m3/(s*m2) multiply by 0.001
    infiltration_si_5Pa = infiltration_si_m3 * 0.172004845 # to convert from 75 Pa to 5 Pa multiply by (5/75)^0.65 ~ 0.172004845

    # get space infiltration objects used in the model
    space_infiltration_objects = model.getSpaceInfiltrationDesignFlowRates

    # reporting initial condition of model
    if !space_infiltration_objects.empty?
      runner.registerInitialCondition("The initial model contained #{space_infiltration_objects.size} space infiltration objects.")
    else
      runner.registerInitialCondition('The initial model did not contain any space infiltration objects.')
    end

    #loop through all infiltration objects and set to the new inflitration flow rate
    space_infiltration_objects.each do |space_infiltration_object|
      space_infiltration_object.setFlowperExteriorSurfaceArea(infiltration_si_5Pa)
    end

    return true
  end
end

# this allows the measure to be used by the application
BTAPSetInfiltration.new.registerWithApplication
