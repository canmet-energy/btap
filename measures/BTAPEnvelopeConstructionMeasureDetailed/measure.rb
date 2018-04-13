# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/

# start the measure
class BTAPEnvelopeConstructionMeasureDetailed < OpenStudio::Measure::ModelMeasure

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
      diffs << "A #{true_object.iddObject.name} called '#{true_object.name}' was found only in the before model"
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
      diffs << "A #{compare_object.iddObject.name} called '#{compare_object.name}' was found only in the after model"
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
        diffs << "For #{true_object.iddObject.name} called '#{true_object.name}' field '#{field_name}': before model = #{true_value}, after model = #{compare_value}"

      end

    end

    return diffs
  end

  #Constructor to set global variables
  def initialize()
    super()

    #Set to true if debugging measure.
    @debug = true

    @standard = Standard.new

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
    # Conductances for all surfaces and subsurfaces.
    (@surface_index + @sub_surface_index).each do |surface|
      ecm_name = "ecm_#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_conductance"
      statement = "
      #{ecm_name} = OpenStudio::Ruleset::OSArgument.makeStringArgument(ecm_name, true)
      #{ecm_name}.setDisplayName('#{surface['boundary_condition']} #{surface['surface_type']} Conductance (W/m2 K)')
      #{ecm_name}.setDefaultValue(@baseline)
      args << #{ecm_name}"
      eval(statement)
    end

    # SHGC
    @sub_surface_index.select {|surface| surface['construction_type'] == "glazing"}.each do |surface|
      ecm_name = "ecm_#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_shgc"
      statement = "
      #{ecm_name} = OpenStudio::Ruleset::OSArgument.makeStringArgument(ecm_name, true)
      #{ecm_name}.setDisplayName('#{surface['boundary_condition']} #{surface['surface_type']} SHGC')
      #{ecm_name}.setDefaultValue(@baseline)
      args << #{ecm_name}"
      eval(statement)
    end

    # Visible Transmittance
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

    values = {}
    # use the built-in error checking
    if !runner.validateUserArguments(arguments(model), user_arguments)
      runner_register(runner, 'Error', "validateUserArguments failed... Check the argument definition for errors.")
      return false
    end
    # conductance values should be between 3.5 and 0.005 U-Value (R-value 1 to R-Value 1000)
    (@surface_index + @sub_surface_index).each do |surface|
      ecm_cond_name = "ecm_#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_conductance"
      value = runner.getStringArgumentValue("#{ecm_cond_name}", user_arguments)
      if value == @baseline
        values[ecm_cond_name] = nil
      else
        if value.to_f > 5.0 or value.to_f < 0.005
          runner_register(runner, 'Error', "Conductance must be between 5.0 and 0.005. You entered #{value} for #{ecm_cond_name}.")
          return false
        end
        values[ecm_cond_name] = value.to_f
      end
    end


    # SHGC should be between zero and 1.
    @sub_surface_index.select {|surface| surface['construction_type'] == "glazing"}.each do |surface|
      ecm_shgc_name = "ecm_#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_shgc"
      value = runner.getStringArgumentValue("#{ecm_shgc_name}", user_arguments)
      if value == @baseline
        values[ecm_cond_name] = nil
      else
        if value.to_f >= 1.0 or value.to_f <= 0.0
          runner_register(runner, 'Error', "SHGC must be between 0.0 and 1.0. You entered #{value} for #{ecm_shgc_name}.")
          return false
        end
        values[ecm_shgc_name] = value.to_f
      end
    end

    # TVis should be between zero and 1.
    @sub_surface_index.select {|surface| surface['construction_type'] == "glazing"}.each do |surface|
      ecm_tvis_name = "ecm_#{surface['boundary_condition'].downcase}_#{surface['surface_type'].downcase}_tvis"
      value = runner.getStringArgumentValue("#{ecm_tvis_name}", user_arguments)
      if value == @baseline
        values[ecm_cond_name] = nil
      else
        if value.to_f >= 1.0 or value.to_f <= 0.0
          runner_register(runner, 'Error', "Tvis must be between 0.0 and 1.0. You entered #{value} for #{ecm_tvis_name}.")
          return false
        end
        values[ecm_tvis_name] = value.to_f
      end
    end

    #get Arguments into a hash.


    # Make a copy of the model before the measure is applied.
    report = @standard.change_construction_properties_in_model(model, values)

    runner_register(runner,
                    'FinalCondition',
                    report)
    return true
  end

end


# register the measure to be used by the application
BTAPEnvelopeConstructionMeasureDetailed.new.registerWithApplication
