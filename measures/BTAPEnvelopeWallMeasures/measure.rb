# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/

# start the measure
class BTAPExteriorWallMeasure < OpenStudio::Measure::ModelMeasure

  # human readable name
  def name
    return "BTAPExteriorWallMeasure"
  end

  # human readable description
  def description
    return "Changes exterior wall construction's thermal conductances"
  end

  # human readable description of modeling approach
  def modeler_description
    return "method"
  end

  # define the arguments that the user will input
  def arguments(model)
    args = OpenStudio::Ruleset::OSArgumentVector.new

    # Conductance value entered
    ecm_exterior_wall_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_exterior_wall_conductance", true)
    ecm_exterior_wall_conductance.setDisplayName('Exterior Wall Conductance (W/m2 K)')
    ecm_exterior_wall_conductance.setDefaultValue('baseline')
    args << ecm_exterior_wall_conductance

    ecm_exterior_roof_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_exterior_roof_conductance", true)
    ecm_exterior_roof_conductance.setDisplayName('Exterior Roof Conductance (W/m2 K)')
    ecm_exterior_roof_conductance.setDefaultValue('baseline')
    args << ecm_exterior_roof_conductance

    ecm_exterior_floor_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_exterior_floor_conductance", true)
    ecm_exterior_floor_conductance.setDisplayName('Exterior Floor Conductance (W/m2 K)')
    ecm_exterior_floor_conductance.setDefaultValue('baseline')
    args << ecm_exterior_floor_conductance

    ecm_ground_wall_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_ground_wall_conductance", true)
    ecm_ground_wall_conductance.setDisplayName('Exterior Ground Wall Conductance (W/m2 K)')
    ecm_ground_wall_conductance.setDefaultValue('baseline')
    args << ecm_ground_wall_conductance

    ecm_ground_roof_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_ground_roof_conductance", true)
    ecm_ground_roof_conductance.setDisplayName('Ground Roof Conductance (W/m2 K)')
    ecm_ground_roof_conductance.setDefaultValue('baseline')
    args << ecm_ground_roof_conductance

    ecm_ground_floor_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_ground_floor_conductance", true)
    ecm_ground_floor_conductance.setDisplayName('Ground Floor Conductance (W/m2 K)')
    ecm_ground_floor_conductance.setDefaultValue('baseline')
    args << ecm_ground_floor_conductance

    ecm_exterior_window_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_exterior_window_conductance", true)
    ecm_exterior_window_conductance.setDisplayName('Window Conductance (W/m2 K)')
    ecm_exterior_window_conductance.setDefaultValue('baseline')
    args << ecm_exterior_window_conductance

    ecm_exterior_skylight_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_exterior_skylight_conductance", true)
    ecm_exterior_skylight_conductance.setDisplayName('Skylight Conductance (W/m2 K)')
    ecm_exterior_skylight_conductance.setDefaultValue('baseline')
    args << ecm_exterior_skylight_conductance

    ecm_exterior_door_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_exterior_door_conductance", true)
    ecm_exterior_door_conductance.setDisplayName('Door Conductance (W/m2 K)')
    ecm_exterior_door_conductance.setDefaultValue('baseline')
    args << ecm_exterior_door_conductance

    ecm_exterior_overhead_door_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_exterior_overhead_door_conductance", true)
    ecm_exterior_overhead_door_conductance.setDisplayName('Overhead Door Conductance (W/m2 K)')
    ecm_exterior_overhead_door_conductance.setDefaultValue('baseline')
    args << ecm_exterior_overhead_door_conductance

    return args
  end

  # define what happens when the measure is run
  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)

    # use the built-in error checking
    if !runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end


    ecm_exterior_wall_conductance = runner.getStringArgumentValue('ecm_exterior_wall_conductance', user_arguments)
    return true if ecm_exterior_wall_conductance == "baseline"

    # assign the user inputs to variables
    ecm_exterior_wall_conductance = ecm_exterior_wall_conductance.to_f

    #check if conductance is negative or 0
    if ecm_exterior_wall_conductance <= 0
      runner.registerError("Conductance is less than or equal to 0")
      return false
    end

    #Get surfaces from model
    model.getDefaultConstructionSets.each do |default_surface_construction_set|

      # convert conductance values to rsi values. (Note: we should really be only using conductances)
      wall_rsi = 1.0 / ecm_exterior_wall_conductance
      floor_rsi = nil
      roof_rsi = nil
      ground_wall_rsi = nil
      ground_floor_rsi = nil
      ground_roof_rsi = nil
      door_rsi = nil
      window_rsi = nil
      BTAP::Resources::Envelope::ConstructionSets.customize_default_surface_construction_set_rsi!(model,
                                                                                                  new_name,
                                                                                                  default_surface_construction_set,
                                                                                                  wall_rsi, floor_rsi, roof_rsi,
                                                                                                  ground_wall_rsi, ground_floor_rsi, ground_roof_rsi,
                                                                                                  window_rsi, nil, nil,
                                                                                                  window_rsi, nil, nil,
                                                                                                  door_rsi,
                                                                                                  door_rsi, nil, nil,
                                                                                                  door_rsi,
                                                                                                  window_rsi, nil, nil,
                                                                                                  window_rsi, nil, nil,
                                                                                                  window_rsi, nil, nil)

    end

    return true

  end

end

# register the measure to be used by the application
BTAPExteriorWallMeasure.new.registerWithApplication
