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
    baseline = 'baseline'

    # Conductance value entered

    ecm_exterior_wall_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_exterior_wall_conductance", true)
    ecm_exterior_wall_conductance.setDisplayName('Exterior Wall Conductance (W/m2 K)')
    ecm_exterior_wall_conductance.setDefaultValue(baseline)
    args << ecm_exterior_wall_conductance

    ecm_exterior_roof_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_exterior_roof_conductance", true)
    ecm_exterior_roof_conductance.setDisplayName('Exterior Roof Conductance (W/m2 K)')
    ecm_exterior_roof_conductance.setDefaultValue(baseline)
    args << ecm_exterior_roof_conductance

    ecm_exterior_floor_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_exterior_floor_conductance", true)
    ecm_exterior_floor_conductance.setDisplayName('Exterior Floor Conductance (W/m2 K)')
    ecm_exterior_floor_conductance.setDefaultValue(baseline)
    args << ecm_exterior_floor_conductance

    ecm_ground_wall_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_ground_wall_conductance", true)
    ecm_ground_wall_conductance.setDisplayName('Exterior Ground Wall Conductance (W/m2 K)')
    ecm_ground_wall_conductance.setDefaultValue(baseline)
    args << ecm_ground_wall_conductance

    ecm_ground_roof_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_ground_roof_conductance", true)
    ecm_ground_roof_conductance.setDisplayName('Ground Roof Conductance (W/m2 K)')
    ecm_ground_roof_conductance.setDefaultValue(baseline)
    args << ecm_ground_roof_conductance

    ecm_ground_floor_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_ground_floor_conductance", true)
    ecm_ground_floor_conductance.setDisplayName('Ground Floor Conductance (W/m2 K)')
    ecm_ground_floor_conductance.setDefaultValue(baseline)
    args << ecm_ground_floor_conductance

    ecm_exterior_window_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_exterior_window_conductance", true)
    ecm_exterior_window_conductance.setDisplayName('Window Conductance (W/m2 K)')
    ecm_exterior_window_conductance.setDefaultValue(baseline)
    args << ecm_exterior_window_conductance

    ecm_exterior_skylight_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_exterior_skylight_conductance", true)
    ecm_exterior_skylight_conductance.setDisplayName('Skylight Conductance (W/m2 K)')
    ecm_exterior_skylight_conductance.setDefaultValue(baseline)
    args << ecm_exterior_skylight_conductance

    ecm_exterior_door_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_exterior_door_conductance", true)
    ecm_exterior_door_conductance.setDisplayName('Door Conductance (W/m2 K)')
    ecm_exterior_door_conductance.setDefaultValue(baseline)
    args << ecm_exterior_door_conductance

    ecm_exterior_overhead_door_conductance = OpenStudio::Ruleset::OSArgument.makeStringArgument("ecm_exterior_overhead_door_conductance", true)
    ecm_exterior_overhead_door_conductance.setDisplayName('Overhead Door Conductance (W/m2 K)')
    ecm_exterior_overhead_door_conductance.setDefaultValue(baseline)
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

    #Set default rsi values to nil.
    wall_rsi = nil
    floor_rsi = nil
    roof_rsi = nil
    ground_wall_rsi = nil
    ground_floor_rsi = nil
    ground_roof_rsi = nil
    door_rsi = nil
    window_rsi = nil


    #
    ecm_exterior_wall_conductance = runner.getStringArgumentValue('ecm_exterior_wall_conductance', user_arguments)
    if not wall_rsi.nil? and wall_rsi <= 0
      runner.registerError("ecm_exterior_wall_conductance is less than or equal to 0")
      return false
    end


    outdoor_surfaces = BTAP::Geometry::Surfaces::filter_by_boundary_condition(model.getSurfaces(), "Outdoors")
    outdoor_subsurfaces = BTAP::Geometry::Surfaces::get_subsurfaces_from_surfaces(outdoor_surfaces)
    ground_surfaces = BTAP::Geometry::Surfaces::filter_by_boundary_condition(model.getSurfaces(), "Ground")

    ext_wall_surfaces = BTAP::Geometry::Surfaces::filter_by_surface_types(outdoor_surfaces, "Wall")
    ext_roof_surfaces = BTAP::Geometry::Surfaces::filter_by_surface_types(outdoor_surfaces, "RoofCeiling")
    ext_floor_surfaces = BTAP::Geometry::Surfaces::filter_by_surface_types(outdoor_surfaces, "Floor")
    gnd_wall_surfaces = BTAP::Geometry::Surfaces::filter_by_surface_types(ground_surfaces, "Wall")
    gnd_roof_surfaces = BTAP::Geometry::Surfaces::filter_by_surface_types(ground_surfaces, "RoofCeiling")
    gnd_floor_surfaces = BTAP::Geometry::Surfaces::filter_by_surface_types(ground_surfaces, "Floor")
    ext_windows = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(outdoor_subsurfaces, ["FixedWindow", "OperableWindow"])
    ext_skylights = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(outdoor_subsurfaces, ["Skylight", "TubularDaylightDiffuser", "TubularDaylightDome"])
    ext_doors = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(outdoor_subsurfaces, ["Door", "GlassDoor"])
    ext_overhead_doors = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(outdoor_subsurfaces, ["OverheadDoor"])

    unless ecm_exterior_wall_conductance == 'baseline'
      appy_conductances_to_ext_surfaces(model, ext_wall_surfaces, ecm_exterior_wall_conductance)
    end

    return true
  end

  def appy_conductances_to_ext_surfaces(model, surfaces, conductance)
    surfaces.each do |surface|
      construction = OpenStudio::Model::getConstructionByName(surface.model, surface.construction.get.name.to_s).get
      new_construction_name = "#{surface.construction.get.name.to_s} Cond=#{conductance}"
      new_construction = OpenStudio::Model::getConstructionByName(surface.model, new_construction_name)
      target_u_value_ip = OpenStudio.convert(conductance.to_f, 'W/m^2*K', 'Btu/ft^2*hr*R').get
      if new_construction.empty?
        #create new construction.
        #create a copy
        new_construction = self.deep_copy(model, construction)
        standard = Standard.new()

        BTAP::Resources::Envelope::Constructions::find_and_set_insulaton_layer(model, [new_construction])
        standard.construction_set_u_value(new_construction,
                                          target_u_value_ip.to_f,
                                          find_and_set_insulaton_layer(model, new_construction).name.get,
                                          intended_surface_type = nil,
                                          false,
                                          false
        )
        new_construction.setName(new_construction_name)
      else
        new_construction = new_construction.get
      end
      surface.setConstruction(new_construction)
    end
  end

  #This will create a deep copy of the construction
  #@author Phylroy A. Lopez <plopez@nrcan.gc.ca>
  #@param model [OpenStudio::Model::Model]
  #@param construction <String>
  #@return [String] new_construction
  def deep_copy(model, construction)
    construction = BTAP::Common::validate_array(model, construction, "Construction").first
    new_construction = construction.clone.to_Construction.get
    #interating through layers."
    (0..new_construction.layers.length-1).each do |layernumber|
      #cloning material"
      cloned_layer = new_construction.getLayer(layernumber).clone.to_Material.get
      #"setting material to new construction."
      new_construction.setLayer(layernumber, cloned_layer)
    end
    return new_construction
  end

  #This method will search through the layers and find the layer with the
  #lowest conductance and set that as the insulation layer. Note: Concrete walls
  #or slabs with no insulation layer but with a carper will see the carpet as the
  #insulation layer.
  #@author Phylroy A. Lopez <plopez@nrcan.gc.ca>
  #@param model [OpenStudio::Model::Model]
  #@param constructions_array [BTAP::Common::validate_array]
  #@return <String> insulating_layers
  def find_and_set_insulaton_layer(model, construction)

    insulating_layers = Array.new()
    return_material = ""
    #skip if already has an insulation layer set.
    if construction.insulation.empty?
      #find insulation layer
      min_conductance = 100.0
      #loop through Layers
      construction.layers.each do |layer|
        #try casting the layer to an OpaqueMaterial.
        material = nil
        material = layer.to_OpaqueMaterial.get unless layer.to_OpaqueMaterial.empty?
        material = layer.to_FenestrationMaterial.get unless layer.to_FenestrationMaterial.empty?
        #check if the cast was successful, then find the insulation layer.
        unless nil == material

          if BTAP::Resources::Envelope::Materials::get_conductance(material) < min_conductance
            #Keep track of the highest thermal resistance value.
            min_conductance = BTAP::Resources::Envelope::Materials::get_conductance(material)
            return_material = material
            unless material.to_OpaqueMaterial.empty?
              construction.setInsulation(material)
            end
          end
        end
      end
      if construction.insulation.empty? and construction.isOpaque
        raise ("construction #{construction.name.get.to_s} insulation layer could not be set!. This occurs when a insulation layer is duplicated in the construction.")
      end
    else
      return_material = construction.insulation.get
    end

    return return_material
  end
end

# register the measure to be used by the application
BTAPExteriorWallMeasure.new.registerWithApplication
