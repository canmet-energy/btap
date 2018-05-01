# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/

# start the measure
class BTAPTemplateMeasureDetailed < OpenStudio::Measure::ModelMeasure

  # human readable name
  def name
    return "BTAPTemplateMeasure"
  end

  # human readable description
  def description
    return "This template measure is used to ensure consistancy in detailed BTAP measures."
  end

  # human readable description of modeling approach
  def modeler_description
    return "This template measure is used to ensure consistancy in BTAP measures."
  end

  #Use the constructor to set global variables
  def initialize()
    super()
    @measure_input_type = "ARGS"

    # Put in this array of hashes all the variables that you need in your measure. Your choice of types are Sting, Double,
    # StringDouble, and Choice. Optional fields are valid strings, max_double_value, and min_double_value. This will
    # create all the variables, validate the ranges and types you need,  and make them available in the 'run' method as a hash after
    # you run 'arguments = validate_and_get_arguments_in_hash(model, runner, user_arguments)'
    @measure_interface_detailed = [
        {
            "name" => "a_string_argument",
            "type" => "String",
            "display_name" => "A String Argument (string)",
            "default_value" => "The Default Value",
            "is_required" => true
        },
        {
            "name" => "a_double_argument",
            "type" => "Double",
            "display_name" => "A Double numeric Argument (double)",
            "default_value" => 0,
            "max_double_value" => 100.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "a_string_double_argument",
            "type" => "StringDouble",
            "display_name" => "A String Double numeric Argument (double)",
            "default_value" => "NA",
            "max_double_value" => 100.0,
            "min_double_value" => 0.0,
            "valid_strings" => ["Baseline", "NA"],
            "is_required" => true
        },
        {
            "name" => "a_choice_argument",
            "type" => "Choice",
            "display_name" => "A Choice String Argument ",
            "default_value" => "choice_1",
            "choices" => ["choice_1", "choice_2"],
            "is_required" => true
        }
    ]

  end

  # define what happens when the measure is run
  def run(model, runner, user_arguments)
    #Runs parent run method.
    super(model, runner, user_arguments)
    # Gets arguments from interfaced and puts them in a hash with there display name. This also does a check on ranges to
    # ensure that the values inputted are valid based on your @measure_interface array of hashes.
    arguments = validate_and_get_arguments_in_hash(model, runner, user_arguments)
    #puts JSON.pretty_generate(arguments)
    return false if false == arguments
    #You can now access the input argument by the name.
    # arguments['a_string_argument']
    # arguments['a_double_argument']
    # etc......
    # So write your measure here!


    #Do something.
    return true
  end


  ###################Helper functions

  # define the arguments that the user will input
  def arguments(model)
    args = OpenStudio::Ruleset::OSArgumentVector.new
    # Conductances for all surfaces and subsurfaces.
    @measure_interface_detailed.each do |argument|
      arg = nil
      statement = nil
      case argument['type']
        when "String"
          arg = OpenStudio::Ruleset::OSArgument.makeStringArgument("#{argument['name']}", argument['is_required'])
          arg.setDisplayName("#{argument['display_name']}")
          arg.setDefaultValue("#{argument['default_value']}")

        when "Double"
          arg = OpenStudio::Ruleset::OSArgument.makeDoubleArgument("#{argument['name']}", argument['is_required'])
          arg.setDisplayName("#{argument['display_name']}")
          arg.setDefaultValue("#{argument['default_value']}".to_f)

        when "Choice"
          arg = OpenStudio::Measure::OSArgument.makeChoiceArgument("#{argument['name']}", argument['choices'], argument['is_required'])
          arg.setDisplayName(argument['display_name'])
          arg.setDefaultValue('choice_1')


        when "StringDouble"
          arg = OpenStudio::Ruleset::OSArgument.makeStringArgument(argument['name'], argument['is_required'])
          arg.setDisplayName(argument['display_name'])
          arg.setDefaultValue(argument['default_value'])
      end
      args << arg
    end
    return args
  end

  def get_hash_of_arguments(user_arguments,runner)
    values = {}
    @measure_interface_detailed.each do |argument|
      case @measure_input_type
        when "ARGS"
          case argument['type']
            when "String", "Choice"
              values[argument['name']] = runner.getStringArgumentValue(argument['name'], user_arguments)
            when "Double"
              values[argument['name']] = runner.getDoubleArgumentValue(argument['name'], user_arguments)
            when "StringDouble"
              value = runner.getStringArgumentValue(argument['name'], user_arguments)
              if valid_float?( value)
                value = value.to_f
              end
              values[argument['name']] = value
          end
        when "JSON"
        when "ARGS-DOUBLE"
      end
    end
    return values
  end


  def validate_and_get_arguments_in_hash(model, runner, user_arguments)


    return_value = true
    values = get_hash_of_arguments(user_arguments,runner)
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
          if (not argument["max_double_value"].nil? and value.to_f >= argument["max_double_value"]) or
              (not argument["min_double_value"].nil? and value.to_f <= argument["min_double_value"])
            error = "#{argument['name']} must be between #{argument["min_double_value"]} and #{argument["max_double_value"]}. You entered #{value} for #{argument['name']}.\n Please enter a value withing the expected range.\n"
            errors << error
          end
        when "StringDouble"
          value = values[argument['name']]
          if (not argument["valid_strings"].include?(value)) and (not valid_float?(value))
            error = "#{argument['name']} must be a string that can be converted to a float, or one of these #{argument["valid_strings"]}. You have entered #{value}\n"
            errors << error
          elsif (not argument["max_double_value"].nil? and value.to_f >= argument["max_double_value"]) or
              (not argument["min_double_value"].nil? and value.to_f <= argument["min_double_value"])
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
  def valid_float?(str)
    !!Float(str) rescue false
  end


end


# register the measure to be used by the application
BTAPTemplateMeasureDetailed.new.registerWithApplication
