#start the measure
$: << 'C:\Users\barssoumm\new_tests\openstudio-standards\openstudio-standards\lib'

require_relative 'resources/BTAPMeasureHelper'
require 'openstudio-standards'

class BtapSetEnvelopeConductanceByNecbClimateZone < OpenStudio::Ruleset::ModelUserScript
  attr_accessor :use_json_package, :use_string_double
  include(BTAPMeasureHelper)

  #define the name that a user will see
  def name
    return "BTAPSetEnvelopeConductanceByNecbClimateZone"
  end

  def description
    return "Modifies walls, roofs, and windows conductance by climate zone."
  end
  # human readable description of modeling approach
  def modeler_description
    return "Modifies walls, roofs, and windows conductances by NECB climate zone. OpenStudio 2.6.0 (October 2018)"
  end

  #define the arguments that the user will input
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
    @debug = false
    #this is the 'do nothing value and most arguments should have. '
    @baseline = 0.0


 # values for option 1
    @measure_interface_detailed = [

        {
            "name" => "necb_template",
            "type" => "Choice",
            "display_name" => "Template",
            "default_value" => "NECB2015",
            "choices" => ["NECB2011", "NECB2015", "NECB2017"],
            "is_required" => true
        },


        {
            "name" => "surface_type",
            "type" => "Choice",
            "display_name" => "Surface Type",
            "default_value" => "Glazing",
            "choices" => ["Walls", "Roofs", "Floors", "Glazing"],
            "is_required" => true
        },

        {
            "name" => "zone4_u_value",
            "type" => "Double",
            "display_name" => "NECB Zone4 Insulation U-value (W/m^2 K).",
            "default_value" => 0.59,
            "max_double_value" => 5.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },

        {
            "name" => "zone5_u_value",
            "type" => "Double",
            "display_name" => "NECB Zone5 Insulation U-value (W/m^2 K).",
            "default_value" => 0.265,
            "max_double_value" => 5.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
           "name" => "zone6_u_value",
            "type" => "Double",
            "display_name" => "NECB Zone6 Insulation U-value (W/m^2 K).",
            "default_value" => 0.240,
            "max_double_value" => 5.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "zone7A_u_value",
            "type" => "Double",
            "display_name" => "NECB Zone7A Insulation U-value (W/m^2 K).",
            "default_value" => 0.215,
            "max_double_value" => 5.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "zone7B_u_value",
            "type" => "Double",
            "display_name" => "NECB Zone7B Insulation U-value (W/m^2 K).",
            "default_value" => 0.190,
            "max_double_value" => 5.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "zone8_u_value",
            "type" => "Double",
            "display_name" => "NECB Zone8 Insulation U-value (W/m^2 K).",
            "default_value" => 0.165,
            "max_double_value" => 5.0,
            "min_double_value" => 0.0,
            "is_required" => true
        }

    ]

  end

  #define what happens when the measure is run
  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)

    # Gets arguments from interfaced and puts them in a hash with there display name. This also does a check on ranges to
    # ensure that the values inputted are valid based on your @measure_interface array of hashes.
    arguments = validate_and_get_arguments_in_hash(model, runner, user_arguments)

    #puts JSON.pretty_generate(arguments)
    return false if false == arguments

    necb_template = arguments['necb_template']
	surface_type = arguments['surface_type']
    zone4_u_value = arguments['zone4_u_value']
    zone5_u_value = arguments['zone5_u_value']
    zone6_u_value = arguments['zone6_u_value']
    zone7A_u_value = arguments['zone7A_u_value']
    zone7B_u_value = arguments['zone7B_u_value']
    zone8_u_value = arguments['zone8_u_value']

    # call get_necb_hdd18 from Standards
    standard = Standard.build(necb_template)
    necb_hdd18 = standard.get_necb_hdd18(model)
    runner.registerInfo("The Weather File NECB hdd is '#{necb_hdd18}'.")

	# Find the climate zone according to the NECB hdds, then find the corresponding r-value of that climate zone.
    if  necb_hdd18 <3000 then
      u_value = zone4_u_value
    elsif (necb_hdd18 >= 3000 && necb_hdd18 <4000) then
      u_value = zone5_u_value
    elsif  (necb_hdd18 >= 4000 && necb_hdd18 <5000)  then
      u_value = zone6_u_value
    elsif  (necb_hdd18 >= 5000 && necb_hdd18 <6000)  then
      u_value = zone7A_u_value
    elsif  (necb_hdd18 >= 6000 && necb_hdd18 <7000) then
      u_value = zone7B_u_value
    elsif  (necb_hdd18 >= 7000 ) then
      u_value = zone8_u_value
    else
      runner.registerInfo("Couldn't find a climate zone.")
    end

    #use the built-in error checking
    if not runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end
    #puts JSON.pretty_generate(arguments)
    return false if false == arguments

	# Check the selected surfact type
	 if surface_type == "Roofs"
     runner.registerInfo("The selected surface type is '#{surface_type}' So the conductance of roofs only will be changed.to #{u_value} ............. ")
       surfaces = model.getSurfaces
       surfaces.each do |surface|
         if surface.outsideBoundaryCondition == "Outdoors" and surface.surfaceType == "RoofCeiling"
         surface_conductance = BTAP::Geometry::Surfaces.get_surface_construction_conductance(surface)
         #set the construction according to the new conductance

         Standard.new.apply_changes_to_surface_construction(model,
                                                   surface,
                                                   u_value,
                                                   nil,
                                                   nil,
                                                   false)

         surface_conductance2 = BTAP::Geometry::Surfaces.get_surface_construction_conductance(surface)
         u_value_rounded = sprintf "%.3f", u_value
         surface_conductance2_rounded= sprintf "%.3f" , surface_conductance2
		     runner.registerInfo("Initial conductance for #{surface.surfaceType} was : #{surface_conductance} , now it has been changed to #{surface_conductance2} ")
         raise("U values for #{surface.surfaceType} was supposed to change to #{u_value_rounded}, but it is #{surface_conductance2_rounded}") if u_value_rounded != surface_conductance2_rounded

       end
       end
     return true

   elsif surface_type == "Walls"
     runner.registerInfo("The selected surface type is '#{surface_type}' So the conductance of walls only will be changed.")
     surfaces = model.getSurfaces
     surfaces.each do |surface|
       if surface.outsideBoundaryCondition == "Outdoors" and surface.surfaceType == "Wall"
         surface_conductance = BTAP::Geometry::Surfaces.get_surface_construction_conductance(surface)
         #set the construction according to the new conductance
         Standard.new.apply_changes_to_surface_construction(model,
                                                            surface,
                                                            u_value,
                                                            nil,
                                                            nil,
                                                            false)

         
         surface_conductance2 = BTAP::Geometry::Surfaces.get_surface_construction_conductance(surface)
         u_value_rounded = sprintf "%.3f", u_value
         surface_conductance2_rounded= sprintf "%.3f" , surface_conductance2
         runner.registerInfo("Initial conductance for #{surface.surfaceType} was : #{surface_conductance} , now it has been changed to #{surface_conductance2} ")
         raise("U values for #{surface.surfaceType} was supposed to change to #{u_value_rounded}, but it is #{surface_conductance2_rounded}") if u_value_rounded != surface_conductance2_rounded

       end
       end
     return true

   elsif surface_type == "Floors"
     runner.registerInfo("The selected surface type is '#{surface_type}' So the conductance of floors only will be changed.")
     surfaces = model.getSurfaces
     surfaces.each do |surface|
       if surface.outsideBoundaryCondition == "Outdoors" and surface.surfaceType == "Floor"
         surface_conductance = BTAP::Geometry::Surfaces.get_surface_construction_conductance(surface)
         #set the construction according to the new conductance
         Standard.new.apply_changes_to_surface_construction(model,
                                                            surface,
                                                            u_value,
                                                            nil,
                                                            nil,
                                                            false)

         surface_conductance2 = BTAP::Geometry::Surfaces.get_surface_construction_conductance(surface)
         u_value_rounded = sprintf "%.3f", u_value
         surface_conductance2_rounded= sprintf "%.3f" , surface_conductance2
         runner.registerInfo("Initial conductance for #{surface.surfaceType} was : #{surface_conductance} , now it has been changed to #{surface_conductance2} ")
         raise("U values for #{surface.surfaceType} was supposed to change to #{u_value_rounded}, but it is #{surface_conductance2_rounded}") if u_value_rounded != surface_conductance2_rounded

       end
       end
     return true

   elsif surface_type == "Glazing"
     #loop through sub surfaces
     sub_surfaces = model.getSubSurfaces
     sub_surfaces.each do |sub_surface|

       if sub_surface.outsideBoundaryCondition == "Outdoors" and ( sub_surface.subSurfaceType == "FixedWindow" || sub_surface.subSurfaceType == "OperableWindow" || sub_surface.subSurfaceType == "Skylight" || sub_surface.subSurfaceType == "TubularDaylightDiffuser" || sub_surface.subSurfaceType == "TubularDaylightDome")
         surface_conductance = BTAP::Geometry::Surfaces.get_surface_construction_conductance(sub_surface)
         #set the construction according to the new conductance

         Standard.new.apply_changes_to_surface_construction(model,
                                                            sub_surface,
                                                            u_value,
                                                            nil,
                                                            nil,
                                                            false)

         surface_conductance2 = BTAP::Geometry::Surfaces.get_surface_construction_conductance(sub_surface)
         u_value_rounded = sprintf "%.3f", u_value
         surface_conductance2_rounded= sprintf "%.3f" , surface_conductance2
         runner.registerInfo("Initial conductance for #{sub_surface.subSurfaceType} was : #{surface_conductance} , now it has been changed to #{surface_conductance2} ")
         raise("U values for #{surface.surfaceType} was supposed to change to #{u_value_rounded}, but it is #{surface_conductance2_rounded}") if u_value_rounded != surface_conductance2_rounded

       end
       end

end

end 
end
#this allows the measure to be used by the application
BtapSetEnvelopeConductanceByNecbClimateZone.new.registerWithApplication
