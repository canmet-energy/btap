# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/

# start the measure
class BTAPEnvelopeConstructionMeasureDetailed < OpenStudio::Measure::ModelMeasure

  # human readable name
  def name
    return "BTAPTemplateMeasure"
  end

  # human readable description
  def description
    return "This template measure is used to ensure consistancy in BTAP measures."
  end

  # human readable description of modeling approach
  def modeler_description
    return "This template measure is used to ensure consistancy in BTAP measures."
  end

  #Use the constructor to set global variables
  def initialize()
    super()
    @arguments_interface = [
        {
            "name" => "a_string_argument",
            "argument_type" => "String",
            "argument_display_name" => "A String Argument (string)",
            "default_value" => "The Default Value",
            "valid_strings" => ["baseline", "NA"]
        },
        {
            "name" => "a_double_argument",
            "argument_type" => "Double",
            "argument_display_name" => "A Double numermic Argument (double)",
            "default_value" => 0,
            "max_double_value" => 100.0,
            "min_double_value" => 0.0
        },
        {
            "name" => "a_string_double_argument",
            "argument_type" => "StringDouble",
            "argument_display_name" => "A String based Double numeric Argument (double)",
            "default_value" => "NA",
            "max_double_value" => 100.0,
            "min_double_value" => 0.0,
            "valid_strings" => ["Baseline", "NA"]
        },
        {
            "name" => "a_choice_argument",
            "argument_type" => "Choice",
            "argument_display_name" => "A Choice String Argument ",
            "default_value" => 0,
            "max_double_value" => 100.0,
            "min_double_value" => 0.0,
            "choices" => ["choice_1", "choice_2"]
        },
    ]
  end

  # define what happens when the measure is run
  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)
    values = validate_and_get_arguments_in_hash(model, runner, user_arguments)
    return false unless values
    puts values
    return true
  end


  ###################Helper functions

  # define the arguments that the user will input
  def arguments(model)
    args = OpenStudio::Ruleset::OSArgumentVector.new
    # Conductances for all surfaces and subsurfaces.
    @arguments_interface.each do |argument|
      case argument['argument_type']
        when "String"
          statement = "
          #{argument['name']} = OpenStudio::Ruleset::OSArgument.makeStringArgument(#{argument['name']}, true)
          #{argument['name']}.setDisplayName('#{argument['display_name']}')
          #{argument['name']}.setDefaultValue('#{argument['default_value']}')
          args << #{argument['name']}"
          eval(statement)
        when "Double"
          statement = "
          #{argument['name']} = OpenStudio::Measure::OSArgument.makeDoubleArgument(#{argument['name']}, true)
          #{argument['name']}.setDisplayName('#{argument['display_name']}')
          #{argument['name']}.setDefaultValue(#{argument['default_value'].to_s})
          args << #{argument['name']}"
          eval(statement)
        when "Choice"
          statement = "
          #{argument['name']} = OpenStudio::Measure::OSArgument.makeChoiceArgument(#{argument['name']},#{argument['choices'].to_s},  true)
          #{argument['name']}.setDisplayName('#{argument['display_name']}')
          #{argument['name']}.setDefaultValue(#{argument['default_value'].to_s})
          args << #{argument['name']}"
          eval(statement)
        when "StringDouble"
          statement = "
          #{argument['name']} = OpenStudio::Ruleset::OSArgument.makeStringArgument(#{argument['name']}, true)
          #{argument['name']}.setDisplayName('#{argument['display_name']}')
          #{argument['name']}.setDefaultValue('#{argument['default_value']}')
          args << #{argument['name']}"
          eval(statement)
      end
    end
    return args
  end


  def validate_and_get_arguments_in_hash(model, runner, user_arguments)
    def valid_float?(str)
      !!Float(str) rescue false
    end

    return_value = true
    values = {}
    # use the built-in error checking
    if !runner.validateUserArguments(arguments(model), user_arguments)
      runner_register(runner, 'Error', "validateUserArguments failed... Check the argument definition for errors.")
      return_value = false
    end

    # Validate arguments
    @arguments_interface.each do |argument|

      case argument['argument_type']
        when "String", "Choice"
          value = runner.getStringArgumentValue("#{argument['name']}", user_arguments)
          values[argument['name']] = value
        when "Double"
          value = runner.getStringArgumentValue("#{argument['name']}", user_arguments)
          if (not argument["max_double_value"].nil and value.to_f >= argument["max_double_value"]) or
              (not argument["min_double_value"].nil? and value.to_f <= argument["min_double_value"])
            runner.registerError("#{argument['name']} must be between #{argument["min_double_value"]} and #{argument["max_double_value"]}. You entered #{value} for #{ecm_cond_name}.")
            return_value = false
          else
            values[argument['name']] = value
          end
        when "StringDouble"
          value = runner.getStringArgumentValue("#{argument['name']}", user_arguments)
          if not argument['valid_strings'].include?(argument['valid_strings']) or not valid_float?(str)
            runner.registerError("#{argument['name']} must be between number or a float representation #{argument["valid_strings"]}.")
            return_value = false
          elsif (not argument["max_double_value"].nil and value.to_f >= argument["max_double_value"]) or
              (not argument["min_double_value"].nil? and value.to_f <= argument["min_double_value"])
            runner.registerError("#{argument['name']} must be between #{argument["min_double_value"]} and #{argument["max_double_value"]}. You entered #{value} for #{ecm_cond_name}.")
            return_value = false
          else
            if argument['valid_strings'].include?(argument['valid_strings']) or valid_float?(str)
              values[argument['name']] = value
            end
          end
      end
    end
    if false == return_value
      return return_value
    end
    return values
  end
end


# register the measure to be used by the application
BTAPTemplateMeasure.new.registerWithApplication
