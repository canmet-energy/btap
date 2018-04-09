# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/

# start the measure
class BTAPEnvelopeConstructionMeasure < OpenStudio::Measure::ModelMeasure

  def initialize()
    super()
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
    return "BTAPEnvelopeConstructionMeasure"
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
    (@surface_index + @sub_surface_index).each do |surface|
      ecm_name = "ecm_#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_conductance"
      statement = "
      #{ecm_name} = OpenStudio::Ruleset::OSArgument.makeStringArgument(ecm_name, true)
      #{ecm_name}.setDisplayName('#{surface['boundary_condition']} #{surface['surface_type']} Conductance (W/m2 K)')
      #{ecm_name}.setDefaultValue(@baseline)
      args << #{ecm_name}"
      eval(statement)
    end

    #SHGC
    @sub_surface_index.select {|surface| surface['construction_type'] == "glazing"}.each do |surface|
      ecm_name = "ecm_#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_shgc"
      statement = "
      #{ecm_name} = OpenStudio::Ruleset::OSArgument.makeStringArgument(ecm_name, true)
      #{ecm_name}.setDisplayName('#{surface['boundary_condition']} #{surface['surface_type']} SHGC')
      #{ecm_name}.setDefaultValue(@baseline)
      args << #{ecm_name}"
      eval(statement)
    end

    #Visible Transmittance
    @sub_surface_index.select {|surface| surface['construction_type'] == "glazing"}.each do |surface|
      ecm_name = "ecm_#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_tvis"
      statement = "
      #{ecm_name} = OpenStudio::Ruleset::OSArgument.makeStringArgument(ecm_name, true)
      #{ecm_name}.setDisplayName('#{surface['boundary_condition']} #{surface['surface_type']} Visible Transmittance')
      #{ecm_name}.setDefaultValue(@baseline)
      args << #{ecm_name}"
      eval(statement)
    end


    return args
  end

  # define what happens when the measure is run
  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)

    # use the built-in error checking
    if !runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end
    # conductance values should be between 3.5 and 0.005 U-Value (R-value 1 to R-Value 1000)
    (@surface_index + @sub_surface_index).each do |surface|
      ecm_cond_name = "ecm_#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_conductance"
      value = runner.getStringArgumentValue("#{ecm_cond_name}",user_arguments)
      unless value == @baseline
        if value != @baseline and value.to_f > 3.5 or value.to_f < 0.005
          message = "Conductance must be between 5.0 and 0.005. You entered #{value} for #{ecm_cond_name}."
          runner.registerError(message)
          puts message
          return false
        end
      end
    end


    # SHGC should be between zero and 1.
    @sub_surface_index.select {|surface| surface['construction_type'] == "glazing"}.each do |surface|
      ecm_shgc_name = "ecm_#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_shgc"
      value = runner.getStringArgumentValue("#{ecm_shgc_name}",user_arguments)
      unless value == @baseline
        if value != @baseline and value.to_f >= 1.0 or value.to_f <= 0.0
          message = "SHGC must be between 0.0 and 1.0. You entered #{value} for #{ecm_shgc_name}."
          runner.registerError(message)
          puts message
          return false
        end
      end
    end

    # TVis should be between zero and 1.
    @sub_surface_index.select {|surface| surface['construction_type'] == "glazing"}.each do |surface|
      ecm_tvis_name = "ecm_#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_tvis"
      value = runner.getStringArgumentValue("#{ecm_tvis_name}",user_arguments)
      unless value == @baseline
        if value != @baseline and value.to_f >= 1.0 or value.to_f <= 0.0
          message = "Tvis must be between 0.0 and 1.0. You entered #{value} for #{ecm_tvis_name}."
          runner.registerError(message)
          puts message
          return false
        end
      end
    end



    # Make a copy of the model before the measure is applied.
    before_measure_model = copy_model(model)


    outdoor_surfaces = BTAP::Geometry::Surfaces::filter_by_boundary_condition(model.getSurfaces(), "Outdoors")
    outdoor_subsurfaces = BTAP::Geometry::Surfaces::get_subsurfaces_from_surfaces(outdoor_surfaces)
    ground_surfaces = BTAP::Geometry::Surfaces::filter_by_boundary_condition(model.getSurfaces(), "Ground")

    #get subsurfaces by type for ease of use.
    ext_windows = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(outdoor_subsurfaces, ["FixedWindow", "OperableWindow"])
    ext_skylights = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(outdoor_subsurfaces, ["Skylight", "TubularDaylightDiffuser", "TubularDaylightDome"])
    ext_doors = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(outdoor_subsurfaces, ["Door", "GlassDoor"])
    ext_glass_doors = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(outdoor_subsurfaces, ["GlassDoor"])
    ext_overhead_doors = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(outdoor_subsurfaces, ["OverheadDoor"])

    #Surfaces
    (outdoor_surfaces).each do |surface|
      ecm_name = "ecm_#{surface.outsideBoundaryCondition.downcase}_#{surface.surfaceType.downcase}_conductance"
      conductance = runner.getStringArgumentValue("#{ecm_name}", user_arguments)
      conductance = nil if conductance == @baseline
      appy_changes_to_surfaces(model, surface, conductance.to_f)
    end

    #Subsurfaces
    (ext_doors + ext_overhead_doors + ext_windows + ext_glass_doors +ext_skylights).each do |surface|
      ecm_cond_name = "ecm_#{surface.outsideBoundaryCondition.downcase}_#{surface.subSurfaceType.downcase}_conductance"
      ecm_shgc_name = "ecm_#{surface.outsideBoundaryCondition.downcase}_#{surface.subSurfaceType.downcase}_shgc"
      ecm_tvis_name = "ecm_#{surface.outsideBoundaryCondition.downcase}_#{surface.subSurfaceType.downcase}_tvis"
      conductance = runner.getStringArgumentValue("#{ecm_cond_name}", user_arguments)
      shgc = runner.getStringArgumentValue("#{ecm_shgc_name}", user_arguments)
      tvis = runner.getStringArgumentValue("#{ecm_tvis_name}", user_arguments)
      shgc = nil if shgc == @baseline
      conductance = nil if conductance == @baseline
      tvis = nil if tvis == @baseline
      appy_changes_to_surfaces(model,
                               surface,
                               conductance.to_f,
                               shgc.to_f,
                               tvis.to_f)
    end

    #This will produce a JSON 'diff' of the original osm and the final osm.
    runner.registerFinalCondition(JSON.pretty_generate(compare_osm_files(before_measure_model, model)))
    return true
  end

  def appy_changes_to_surfaces(model, surface, conductance = nil, shgc = nil, tvis = nil)
    #If user has no changes...do nothing and return true.
    return true if conductance.nil? and shgc.nil?
    standard = Standard.new()
    construction = OpenStudio::Model::getConstructionByName(surface.model, surface.construction.get.name.to_s).get
    new_construction_name_suffix = ""
    new_construction_name_suffix << "#{surface.construction.get.name.to_s} Cond=#{conductance.round(3)}" unless conductance.nil?
    new_construction_name_suffix << "#{surface.construction.get.name.to_s} SHGC=#{shgc.round(3)}" unless shgc.nil?
    new_construction_name_suffix << "#{surface.construction.get.name.to_s} TVis=#{shgc.round(3)}" unless tvis.nil?
    new_construction_name = "#{surface.construction.get.name.to_s}-#{new_construction_name_suffix}"
    new_construction = OpenStudio::Model::getConstructionByName(surface.model, new_construction_name)
    target_u_value_ip = OpenStudio.convert(conductance.to_f, 'W/m^2*K', 'Btu/ft^2*hr*R').get
    if new_construction.empty?
      #create new construction.
      #create a copy
      new_construction = self.deep_copy(model, construction)
      case surface.outsideBoundaryCondition
        when 'Outdoors'
          if standard.construction_simple_glazing?(new_construction)
            standard.construction_set_glazing_u_value(new_construction,
                                                      target_u_value_ip.to_f,
                                                      nil,
                                                      false,
                                                      false)
            standard.construction_set_glazing_shgc(new_construction,
                                                   shgc)
            if construction_set_glazing_tvis(new_construction, tvis) == false
              return false
            end


          else
            standard.construction_set_u_value(new_construction,
                                              target_u_value_ip.to_f,
                                              find_and_set_insulaton_layer(model, new_construction).name.get,
                                              intended_surface_type = nil,
                                              false,
                                              false
            )
          end
        when 'Ground'
          BTAP::Resources::Envelope::Constructions::find_and_set_insulaton_layer(model, [new_construction])
          case surface.surfaceType
            when 'Wall'
              standard.construction_set_underground_wall_c_factor(new_construction,
                                                                  target_u_value_ip.to_f,
                                                                  find_and_set_insulaton_layer(model, new_construction).name.get)
            when 'RoofCeiling', 'Floor'
              standard.construction_set_slab_f_factor(new_construction,
                                                      target_u_value_ip.to_f,
                                                      find_and_set_insulaton_layer(model, new_construction).name.get)
          end
      end
      new_construction.setName(new_construction_name)
    else
      new_construction = new_construction.get
    end
    surface.setConstruction(new_construction)
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


  def compare_osm_files(model_true, model_compare)

    only_model_true = [] # objects only found in the true model
    only_model_compare = [] # objects only found in the compare model
    both_models = [] # objects found in both models
    diffs = [] # differences between the two models
    num_ignored = 0 # objects not compared because they don't have names

    # Define types of objects to skip entirely during the comparison
    object_types_to_skip = [
        'OS:EnergyManagementSystem:Sensor', # Names are UIDs
        'OS:EnergyManagementSystem:Program', # Names are UIDs
        'OS:EnergyManagementSystem:Actuator', # Names are UIDs
        'OS:Connection', # Names are UIDs
        'OS:PortList', # Names are UIDs
        'OS:Building', # Name includes timestamp of creation
        'OS:ModelObjectList' # Names are UIDs
    ]

    # Find objects in the true model only or in both models
    model_true.getModelObjects.sort.each do |true_object|

      # Skip comparison of certain object types
      next if object_types_to_skip.include?(true_object.iddObject.name)

      # Skip comparison for objects with no name
      unless true_object.iddObject.hasNameField
        num_ignored += 1
        next
      end

      # Find the object with the same name in the other model
      compare_object = model_compare.getObjectByTypeAndName(true_object.iddObject.type, true_object.name.to_s)
      if compare_object.empty?
        only_model_true << true_object
      else
        both_models << [true_object, compare_object.get]
      end
    end

    # Report a diff for each object found in only the true model
    only_model_true.each do |true_object|
      diffs << "A #{true_object.iddObject.name} called '#{true_object.name}' was found only in the true model"
    end

    # Find objects in compare model only
    model_compare.getModelObjects.sort.each do |compare_object|

      # Skip comparison of certain object types
      next if object_types_to_skip.include?(compare_object.iddObject.name)

      # Skip comparison for objects with no name
      unless compare_object.iddObject.hasNameField
        num_ignored += 1
        next
      end

      # Find the object with the same name in the other model
      true_object = model_true.getObjectByTypeAndName(compare_object.iddObject.type, compare_object.name.to_s)
      if true_object.empty?
        only_model_compare << compare_object
      end
    end

    # Report a diff for each object found in only the compare model
    only_model_compare.each do |compare_object|
      #diffs << "An object called #{compare_object.name} of type #{compare_object.iddObject.name} was found only in the compare model"
      diffs << "A #{compare_object.iddObject.name} called '#{compare_object.name}' was found only in the compare model"
    end

    # Compare objects found in both models field by field
    both_models.each do |b|
      true_object = b[0]
      compare_object = b[1]
      idd_object = true_object.iddObject

      true_object_num_fields = true_object.numFields
      compare_object_num_fields = compare_object.numFields

      # loop over fields skipping handle
      (1...[true_object_num_fields, compare_object_num_fields].max).each do |i|

        field_name = idd_object.getField(i).get.name

        # Don't compare node, branch, or port names because they are populated with IDs
        next if field_name.include?('Node Name')
        next if field_name.include?('Branch Name')
        next if field_name.include?('Inlet Port')
        next if field_name.include?('Outlet Port')
        next if field_name.include?('Inlet Node')
        next if field_name.include?('Outlet Node')
        next if field_name.include?('Port List')
        next if field_name.include?('Cooling Control Zone or Zone List Name')
        next if field_name.include?('Heating Control Zone or Zone List Name')
        next if field_name.include?('Heating Zone Fans Only Zone or Zone List Name')

        # Don't compare the names of schedule type limits
        # because they appear to be created non-deteministically
        next if field_name.include?('Schedule Type Limits Name')

        # Get the value from the true object
        true_value = ""
        if i < true_object_num_fields
          true_value = true_object.getString(i).to_s
        end
        true_value = "-" if true_value.empty?

        # Get the same value from the compare object
        compare_value = ""
        if i < compare_object_num_fields
          compare_value = compare_object.getString(i).to_s
        end
        compare_value = "-" if compare_value.empty?

        # Round long numeric fields
        true_value = true_value.to_f.round(5) unless true_value.to_f.zero?
        compare_value = compare_value.to_f.round(5) unless compare_value.to_f.zero?

        # Move to the next field if no difference was found
        next if true_value == compare_value

        # Report the difference
        diffs << "For #{true_object.iddObject.name} called '#{true_object.name}' field '#{field_name}': true model = #{true_value}, compare model = #{compare_value}"

      end

    end

    return diffs
  end

  def copy_model(model)
    copy_model = OpenStudio::Model::Model.new
    # remove existing objects from model
    handles = OpenStudio::UUIDVector.new
    copy_model.objects.each do |obj|
      handles << obj.handle
    end
    copy_model.removeObjects(handles)
    # put contents of new_model into model_to_replace
    copy_model.addObjects(model.toIdfFile.objects)
    return copy_model
  end

  # Sets the T-vis of a simple glazing construction to a specified value
  # by modifying the thickness of the insulation layer.
  #
  # @param target_shgc [Double] Visible Transmittance
  # @return [Bool] returns true if successful, false if not
  def construction_set_glazing_tvis(construction, target_tvis)
    if target_tvis >= 1.0
      OpenStudio.logFree(OpenStudio::Error, 'openstudio.standards.ConstructionBase', "Can only set the Tvis can only be set to less than 1.0. #{target_tvis} is > 1.0")
      return false
    end

    OpenStudio.logFree(OpenStudio::Debug, 'openstudio.standards.ConstructionBase', "Setting TVis for #{construction.name} to #{target_tvis}")
    standard = Standard.new()
    # Skip layer-by-layer fenestration constructions
    unless standard.construction_simple_glazing?(construction)
      OpenStudio.logFree(OpenStudio::Error, 'openstudio.standards.ConstructionBase', "Can only set the Tvis of simple glazing. #{construction.name} is not simple glazing.")
      return false
    end

    # Set the Tvis
    glass_layer = construction.layers.first.to_SimpleGlazing.get
    glass_layer.setVisibleTransmittance(target_tvis)
    glass_layer.setName("#{glass_layer.name} TVis #{target_tvis.round(3)}")

    # Modify the construction name
    construction.setName("#{construction.name} TVis #{target_tvis.round(2)}")
    return true
  end


end

# register the measure to be used by the application
BTAPEnvelopeConstructionMeasure.new.registerWithApplication
