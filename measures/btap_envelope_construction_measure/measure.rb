# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/
require_relative 'resources/BTAPMeasureHelper'

# start the measure
class BTAPEnvelopeConstructionMeasure < OpenStudio::Measure::ModelMeasure
  attr_accessor :use_json_package, :use_string_double

  include(BTAPMeasureHelper)
  ### BTAP Measure helper methods.
  #  A wrapper for outputing feedback to users and developers.
  #  runner_register("InitialCondition",   "Your Information Message Here", runner)
  #  runner_register("Info",    "Your Information Message Here", runner)
  #  runner_register("Warning", "Your Information Message Here", runner)
  #  runner_register("Error",   "Your Information Message Here", runner)
  #  runner_register("Debug",   "Your Information Message Here", runner)
  #  runner_register("FinalCondition",   "Your Information Message Here", runner)
  #  @params type [String]
  #  @params runner [OpenStudio::Ruleset::OSRunner] # or a nil.
  def runner_register(runner, type, text)
    #dump to console if @debug is set to true
    puts "#{type.upcase}: #{text}" if @debug == true
    #dump to runner.
    if runner.is_a?(OpenStudio::Ruleset::OSRunner)
      case type.downcase
        when "info"
          runner.registerInfo(text)
        when "warning"
          runner.registerWarning(text)
        when "error"
          runner.registerError(text)
        when "notapplicable"
          runner.registerAsNotApplicable(text)
        when "finalcondition"
          runner.registerFinalCondition(text)
        when "initialcondition"
          runner.registerInitialCondition(text)
        when "debug"
        when "macro"
        else
          raise("Runner Register type #{type.downcase} not info,warning,error,notapplicable,finalcondition,initialcondition,macro.")
      end
    end
  end


  def runner_register_value(runner, name, value)
    if runner.is_a?(OpenStudio::Ruleset::OSRunner)
      runner.registerValue(name, value.to_s)
      BTAP::runner_register("Info", "#{name} = #{value} has been registered in the runner", runner)
    end
  end

  #Constructor to set global variables
  def initialize()
    super()
    #Set to true if you want to package the arguments as json.
    @use_json_package = false
    #Set to true if you want to want to allow strings and doubles in stringdouble types. Set to false to force to use doubles. The latter is used for certain
    # continuous optimization algorithms. You may have to re-examine your input in PAT as this fundamentally changes the measure.
    @use_string_double = false

    #Use percentages instead of values
    @use_percentages = false

    #Set to true if debugging measure.
    @debug = true
    #this is the 'do nothing value and most arguments should have. '
    @baseline = 'baseline'

    #Creating a data-driven measure. This is because there are a large amount of inputs to enter and test.. So creating
    # an array to work around is programmatically easier.
    @surface_index =[
        {"boundary_condition" => "Outdoors", "construction_type" => "opaque", "surface_type" => "Wall"},
        {"boundary_condition" => "Outdoors", "construction_type" => "opaque", "surface_type" => "RoofCeiling"},
        {"boundary_condition" => "Outdoors", "construction_type" => "opaque", "surface_type" => "Floor"},
        {"boundary_condition" => "Ground", "construction_type" => "opaque", "surface_type" => "Wall"},
        {"boundary_condition" => "Ground", "construction_type" => "opaque", "surface_type" => "RoofCeiling"},
        {"boundary_condition" => "Ground", "construction_type" => "opaque", "surface_type" => "Floor"}
    ]

    @sub_surface_index = [
        {"boundary_condition" => "Outdoors", "construction_type" => "glazing", "surface_type" => "FixedWindow"},
        {"boundary_condition" => "Outdoors", "construction_type" => "glazing", "surface_type" => "OperableWindow"},
        {"boundary_condition" => "Outdoors", "construction_type" => "glazing", "surface_type" => "Skylight"},
        {"boundary_condition" => "Outdoors", "construction_type" => "glazing", "surface_type" => "TubularDaylightDiffuser"},
        {"boundary_condition" => "Outdoors", "construction_type" => "glazing", "surface_type" => "TubularDaylightDome"},
        {"boundary_condition" => "Outdoors", "construction_type" => "opaque", "surface_type" => "Door"},
        {"boundary_condition" => "Outdoors", "construction_type" => "glazing", "surface_type" => "GlassDoor"},
        {"boundary_condition" => "Outdoors", "construction_type" => "opaque", "surface_type" => "OverheadDoor"}
    ]


    conductance_units = "Conductance (W/m2 K)"
    shgc_units = ""
    tvis_units = ""
    max_conductance_value = 5.0
    min_conductance_value = 0.005
    max_shgc_value = 1.0
    min_shgc_value = 0.0
    max_tvis_value = 1.0
    min_tvis_value = 0.0


    if @use_percentages
      conductance_units = "Percent Change (%)"
      shgc_units = "Percent Change (%)"
      tvis_units = "Percent Change (%)"
      max_conductance_value = 10000.0
      min_conductance_value = -10000.0
      max_shgc_value = 10000.0
      min_shgc_value = -10000.0
      max_tvis_value = 10000.0
      min_tvis_value = -10000.0
    end

    @measure_interface_detailed = []
    #Conductances
    (@surface_index + @sub_surface_index).each do |surface|
      @measure_interface_detailed << {
          "name" => "#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_conductance",
          "type" => "StringDouble",
          "display_name" => "#{surface['boundary_condition']} #{surface['surface_type']} #{conductance_units}",
          "default_value" => @baseline,
          "max_double_value" => max_conductance_value,
          "min_double_value" => min_conductance_value,
          "valid_strings" => [@baseline],
          "is_required" => false
      }
    end


    # SHGC
    @sub_surface_index.select {|surface| surface['construction_type'] == "glazing"}.each do |surface|
      @measure_interface_detailed << {
          "name" => "#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_shgc",
          "type" => "StringDouble",
          "display_name" => "#{surface['boundary_condition']} #{surface['surface_type']} #{shgc_units}",
          "default_value" => @baseline,
          "max_double_value" => max_shgc_value,
          "min_double_value" => min_shgc_value,
          "valid_strings" => [@baseline],
          "is_required" => false
      }
    end

    # Visible Transmittance
    @sub_surface_index.select {|surface| surface['construction_type'] == "glazing"}.each do |surface|
      @measure_interface_detailed << {
          "name" => "#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_tvis",
          "type" => "StringDouble",
          "display_name" => "#{surface['boundary_condition']} #{surface['surface_type']} Visible Transmittance #{tvis_units}",
          "default_value" => @baseline,
          "max_double_value" => max_tvis_value,
          "min_double_value" => min_tvis_value,
          "valid_strings" => [@baseline],
          "is_required" => false
      }
    end
  end

  # human readable name
  def name
    return "BTAPEnvelopeConstructionMeasureDetailed"
  end

  # human readable description
  def description
    return "Changes exterior wall construction's thermal conductances, Visible Transmittance and SHGC where application for each surface type."
  end

  # human readable description of modeling approach
  def modeler_description
    return "Changes exterior wall construction's thermal conductances, Visible Transmittance and SHGC where application for each surface type."
  end


  # define what happens when the measure is run
  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)

    arguments = validate_and_get_arguments_in_hash(model, runner, user_arguments)
    # Make a copy of the model before the measure is applied.
    report = Standard.new.change_construction_properties_in_model(model, arguments, @use_percentages)

    runner_register(runner,
                    'FinalCondition',
                    report)
    return true
  end
end


# register the measure to be used by the application
BTAPEnvelopeConstructionMeasure.new.registerWithApplication
