# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/

# start the measure
class BTAPEnvelopeConstructionMeasurePackaged < OpenStudio::Measure::ModelMeasure

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

    #Set to true if debugging measure.
    @debug = true

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
    #this is the 'do nothing value and most arguments should have. '
    @baseline = 'baseline'
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

  # define the arguments that the user will input
  def arguments(model)
    args = OpenStudio::Ruleset::OSArgumentVector.new

    package= OpenStudio::Ruleset::OSArgument.makeStringArgument('package', true)
    package.setDisplayName('Envelope Package JSON. Values are in Conductance (W/m2 K) and ratios where appropriate, or null if no change.')
    json_string_default = '{
  "outdoors_wall_conductance": 3.5,
  "outdoors_roofceiling_conductance": 3.5,
  "outdoors_floor_conductance": 3.5,
  "ground_wall_conductance": 3.5,
  "ground_roofceiling_conductance": 3.5,
  "ground_floor_conductance": 3.5,
  "outdoors_fixedwindow_conductance": 3.5,
  "outdoors_operablewindow_conductance": 3.5,
  "outdoors_skylight_conductance": 3.5,
  "outdoors_tubulardaylightdiffuser_conductance": 3.5,
  "outdoors_tubulardaylightdome_conductance": 3.5,
  "outdoors_door_conductance": 3.5,
  "outdoors_glassdoor_conductance": 3.5,
  "outdoors_overheaddoor_conductance": 3.5,
  "outdoors_fixedwindow_shgc": null,
  "outdoors_operablewindow_shgc": null,
  "outdoors_skylight_shgc": null,
  "outdoors_tubulardaylightdiffuser_shgc": null,
  "outdoors_tubulardaylightdome_shgc": null,
  "outdoors_glassdoor_shgc": null,
  "outdoors_fixedwindow_tvis": 0.999,
  "outdoors_operablewindow_tvis": 0.999,
  "outdoors_skylight_tvis": 0.999,
  "outdoors_tubulardaylightdiffuser_tvis": 0.999,
  "outdoors_tubulardaylightdome_tvis": 0.999,
  "outdoors_glassdoor_tvis": 0.999
}'
    package.setDefaultValue(json_string_default)
    args << package
    return args
  end

  # define what happens when the measure is run
  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)

    values = {}
    values = JSON.parse(runner.getStringArgumentValue("package", user_arguments))

    # use the built-in error checking
    if !runner.validateUserArguments(arguments(model), user_arguments)
      runner_register(runner, 'Error', "validateUserArguments failed... Check the argument definition for errors.")
      return false
    end
    # conductance values should be between 3.5 and 0.005 U-Value (R-value 1 to R-Value 1000)
    (@surface_index + @sub_surface_index).each do |surface|
      cond_name = "#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_conductance"
      value = values[cond_name]
      if value == @baseline
        values[cond_name] = nil
      else
        if value.to_f > 5.0 or value.to_f < 0.005
          runner_register(runner, 'Error', "Conductance must be between 5.0 and 0.005. You entered #{value} for #{cond_name}.")
          return false
        end
        values[cond_name] = value.to_f
      end
    end


    # SHGC should be between zero and 1.
    @sub_surface_index.select {|surface| surface['construction_type'] == "glazing"}.each do |surface|
      shgc_name = "#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_shgc"
      value = values[shgc_name]
      if value == @baseline or value.nil?
        values[shgc_name] = nil
      else
        if value.to_f >= 1.0 or value.to_f <= 0.0
          runner_register(runner, 'Error', "SHGCphyl must be between 0.0 and 1.0. You entered #{value} for #{shgc_name}.")
          return false
        end
        values[shgc_name] = value.to_f
      end
    end

    # TVis should be between zero and 1.
    @sub_surface_index.select {|surface| surface['construction_type'] == "glazing"}.each do |surface|
      tvis_name = "#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_tvis"
      value = values[tvis_name]
      if value == @baseline
        values[tvis_name] = nil
      else
        if value.to_f >= 1.0 or value.to_f <= 0.0
          runner_register(runner, 'Error', "Tvis must be between 0.0 and 1.0. You entered #{value} for #{tvis_name}.")
          return false
        end
        values[tvis_name] = value.to_f
      end
    end

    # Make a copy of the model before the measure is applied.
    report = Standard.new.change_construction_properties_in_model(model, values)

    #Store values in runner this will be used for data_viz.
    values.each do |key, value|
      runner_register_value(runner, "ecm_#{key}", value)
    end

    runner_register(runner,
                    'FinalCondition',
                    report)
    return true
  end
end


# register the measure to be used by the application
BTAPEnvelopeConstructionMeasurePackaged.new.registerWithApplication
