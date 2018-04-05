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
    ecm_exterior_wall_conductance = OpenStudio::Ruleset::OSArgument.makeDoubleArgument("ecm_exterior_wall_conductance", true)
    ecm_exterior_wall_conductance.setDisplayName('Exterior Wall Conductance (W/m2 K)')
    ecm_exterior_wall_conductance.setDefaultValue(0.183)
    args << ecm_exterior_wall_conductance

    #Entered start angle
    ecm_start_angle_in_degrees= OpenStudio::Ruleset::OSArgument.makeDoubleArgument("ecm_start_angle_in_degrees", true)
    ecm_start_angle_in_degrees.setDisplayName('Start Angle [deg]')
    ecm_start_angle_in_degrees.setDefaultValue(0)
    args << ecm_start_angle_in_degrees

    #End angle
    ecm_end_angle_in_degrees = OpenStudio::Ruleset::OSArgument.makeDoubleArgument("ecm_end_angle_in_degrees", true)
    ecm_end_angle_in_degrees.setDisplayName('End Angle [deg]')
    ecm_end_angle_in_degrees.setDefaultValue(360)
    args << ecm_end_angle_in_degrees

    return args
  end

  # define what happens when the measure is run
  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)

    # use the built-in error checking
    if !runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end

    # assign the user inputs to variables
    ecm_exterior_wall_conductance = runner.getDoubleArgumentValue('ecm_exterior_wall_conductance',user_arguments)
    ecm_start_angle_in_degrees = runner.getDoubleArgumentValue('ecm_start_angle_in_degrees',user_arguments)
    ecm_end_angle_in_degrees = runner.getDoubleArgumentValue('ecm_end_angle_in_degrees',user_arguments)

    #check if conductance is negative or 0
    if ecm_exterior_wall_conductance <= 0
      runner.registerError("Conductance is less than or equal to 0")
      return false
    end

    #Get surfaces from model
    surfaces = model.getSurfaces
    exterior_wall = []
    exterior_wall_construction = []
    exterior_wall_construction_name = []

    #loop through ea surface to find exterior walls and store construction info
    surfaces.each do |surface|
      if surface.outsideBoundaryCondition == "Outdoors" and surface.surfaceType == "Wall"
        #add wall
        exterior_wall << surface
        temp_ext_wall_construction  = surface.construction.get

        if not exterior_wall_construction_name.include?(temp_ext_wall_construction.name.to_s)
          exterior_wall_construction << temp_ext_wall_construction.to_Construction.get
        end
        exterior_wall_construction_name<<temp_ext_wall_construction.name.to_s

        #puts("#{}")
      end
    end

    #loop through each construction and increase thickness of a single layer
    exterior_wall_construction.each do |wall_construction|
      layer_counter = 0

      #current construction's conductance
      current_exterior_wall_conductance = wall_construction.thermalConductance.to_f

      #Change factor
      change_factor = ecm_exterior_wall_conductance/current_exterior_wall_conductance

      #target conductance in ip units
      ecm_exterior_wall_conductance_ip=OpenStudio.convert(ecm_exterior_wall_conductance, 'W/m^2*K', 'Btu/ft^2*hr*R').get


      #counts how many layers there are in the construction
      wall_construction.layers.each do |layer|
        layer_counter = layer_counter + 1
      end

      if layer_counter == 0
        #error

      elsif layer_counter == 1 #one layer




      elsif layer_counter >=2 # 2 layer
        layer_counter2 = 0
        wall_construction.layers.each do |layer|
          layer_counter2 = layer_counter2 + 1
          puts("wall_construction #{wall_construction}")

          if layer_counter2==2
            insulation_layer_name = layer.name.to_s
            puts("layer #{layer}")
            puts("insulation_layer_name#{insulation_layer_name}")
            wall_construction.construction_set_u_value(wall_construction, ecm_exterior_wall_conductance_ip, insulation_layer_name, intended_surface_type = 'ExteriorWall', false, false)
          end
        end
      end
    end





    # report initial condition of model
    #runner.registerInitialCondition("The building started with #{model.getSpaces.size} spaces.")






    # echo the new space's name back to the user
    #runner.registerInfo("Space #{new_space.name} was added.")

    # report final condition of model
    #runner.registerFinalCondition("The building finished with #{model.getSpaces.size} spaces.")

    return true

  end

end

# register the measure to be used by the application
BTAPExteriorWallMeasure.new.registerWithApplication
