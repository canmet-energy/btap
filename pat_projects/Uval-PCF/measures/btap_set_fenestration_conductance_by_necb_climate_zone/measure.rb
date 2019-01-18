#start the measure

require_relative 'resources/BTAPMeasureHelper'

class BtapSetFenestrationConductanceByNecbClimateZone< OpenStudio::Ruleset::ModelUserScript
  attr_accessor :use_json_package, :use_string_double
  include(BTAPMeasureHelper)

  #define the name that a user will see

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


    @measure_interface_detailed = [
        {
            "name" => "zone4_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone4 Fenestration Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 3.15,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },

        {
            "name" => "zone5_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone5 Fenestration Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 3.15,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
           "name" => "zone6_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone6 Fenestration Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 3.55,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "zone7A_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone7A Fenestration Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 3.55,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "zone7B_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone7B Fenestration Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 4,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "zone8_r_value",
            "type" => "Double",
            "display_name" => "NECB Zone8 Fenestration Insulation R-value (ft^2*h*R/Btu).",
            "default_value" => 4,
            "max_double_value" => 500.0,
            "min_double_value" => 0.0,
            "is_required" => true
        }

    ]

  end

  def name

    return "BtapSetFenestrationConductanceByNecbClimateZone"

  end

  def description

    return "Modifies fenestration conductances by climate zone."

  end
  # human readable description of modeling approach
  def modeler_description
    return "Modifies fenestartion conductances by climate zone."
  end


  #define what happens when the measure is run
  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)

    # Gets arguments from interfaced and puts them in a hash with there display name. This also does a check on ranges to
    # ensure that the values inputted are valid based on your @measure_interface array of hashes.
    arguments = validate_and_get_arguments_in_hash(model, runner, user_arguments)

    #puts JSON.pretty_generate(arguments)
    return false if false == arguments

    zone4_r_value = arguments['zone4_r_value']
    zone5_r_value = arguments['zone5_r_value']
    zone6_r_value = arguments['zone6_r_value']
    zone7A_r_value = arguments['zone7A_r_value']
    zone7B_r_value = arguments['zone7B_r_value']
    zone8_r_value = arguments['zone8_r_value']

    #get the building name and its climate zone from the archetype to be tested
    b_name=model.getBuilding.name.to_s
	wf_v1 = b_name.split("-")[1]
    wf_v2 = b_name.split("-")[2]
    wf_v3 = b_name.split("-")[3]
    # wf = BTAP::Environment::WeatherFile.new(wf_v)
    #puts "---------------------------------------------------------------------------------------"
    #puts"@@@@@@#{b_name}"

    #puts "---------------------------------------------------------------------------------------"
    #puts"@@@@@@#{wf_v2}"

    # puts "---------------------------------------------------------------------------------------"
    # puts"@@@@@@#{wf_v3}"
    wfile= wf_v1.split(' created')[0]

    puts "-------------------------Weather File--------------------------------------------------------------"
    puts"@@@@@@#{wfile}"
     # hdd = self.get_necb_hdd18(model)

    wf = BTAP::Environment::WeatherFile.new(wfile)
    data_array = []
    data = {}
    data_array << data
    #data['hdd10'] = wf.hdd10
    data['hdd18'] = wf.hdd18
    data['climate_zone'] = wf.climate_zone.force_encoding('ISO-8859-1').encode('UTF-8')

    puts "-------------------------hdd18-------------------------------------------------------------"
    puts  data['hdd18']

    if  data['hdd18'] <3000 then
      r_value = zone4_r_value
    elsif (data['hdd18'] >= 3000 && data['hdd18'] <4000) then
      r_value = zone5_r_value
    elsif  (data['hdd18'] >= 4000 && data['hdd18'] <5000)  then
      r_value = zone6_r_value
    elsif  (data['hdd18'] >= 5000 && data['hdd18'] <6000)  then
      r_value = zone7A_r_value
    elsif  (data['hdd18'] >= 6000 && data['hdd18'] <7000) then
      r_value = zone7B_r_value
    elsif  (data['hdd18'] >= 7000 ) then
      r_value = zone8_r_value
    else
      puts "Couldn't find a climate zone "
    end

    puts "------------------------- data['climate_zone']-------------------------------------------------------------"
    puts   data['climate_zone']


    puts "-------------------------  r_value -------------------------------------------------------------"
    puts    r_value

    #use the built-in error checking
    if not runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end
    #puts JSON.pretty_generate(arguments)
    return false if false == arguments

    #assign the user inputs to variables
    # r_value = runner.getDoubleArgumentValue("r_value",user_arguments)


    #set limit for minimum insulation. This is used to limit input and for inferring insulation layer in construction.
    min_expected_r_value_ip = 1 #ip units

    #short def to make numbers pretty (converts 4125001.25641 to 4,125,001.26 or 4,125,001). The definition be called through this measure
    def neat_numbers(number, roundto = 2) #round to 0 or 2)
      if roundto == 2
        number = sprintf "%.2f", number
      else
        number = number.round
      end
      #regex to add commas
      number.to_s.reverse.gsub(%r{([0-9]{3}(?=([0-9])))}, "\\1,").reverse
    end #end def neat_numbers

    #helper to make it easier to do unit conversions on the fly
    def unit_helper(number,from_unit_string,to_unit_string)
      converted_number = OpenStudio::convert(OpenStudio::Quantity.new(number, OpenStudio::createUnit(from_unit_string).get), OpenStudio::createUnit(to_unit_string).get).get.value
    end

    #convert r_value to si for future use
    r_value_si = unit_helper(r_value, "ft^2*h*R/Btu","m^2*K/W")


    #loop through sub surfaces
    starting_exterior_windows_constructions = []
    sub_surfaces_to_change = []
    sub_surfaces = model.getSubSurfaces
    sub_surfaces.each do |sub_surface|
     #  puts "sub_surface.construction.class #{sub_surface.construction.class}================================================================================================"
      # puts "------------------------- all sub_surface.construction : #{sub_surface.name.to_s}-------------------------------------------------------------"

      if sub_surface.outsideBoundaryCondition == "Outdoors" and sub_surface.subSurfaceType == "FixedWindow" || "OperableWindow" || "Skylight" || "TubularDaylightDiffuser" || "TubularDaylightDome"
        sub_surfaces_to_change << sub_surface
        sub_surface_const = sub_surface.construction.get
       # next if sub_surface.construction.isOpaque

        # if not sub_surface_const.empty?

          #report strings for initial condition
          initial_string = []
        construction = OpenStudio::Model::getConstructionByName(sub_surface.model, sub_surface.construction.get.name.to_s).get

        # puts "-------------------------  sub_surface.construction #{sub_surface.name.to_s} , comstruction #{construction.name.to_s}-------------------------------------------------------------"

        # puts "Only set the u-value of fenestratration. #{construction.name} is fenestratration ."

        if construction.isFenestration then

          # conductance = BTAP::Geometry::Surfaces::get_surface_construction_conductance(sub_surface)

          cond =  sub_surface.uFactor
          # puts "------------------------- initial conductance #{conductance} for #{sub_surface.name.to_s} -------------------------------------------------------------"
          new_conductance = (1/r_value_si)

        #BTAP::Geometry::Surfaces::set_surfaces_construction_conductance([sub_surface],new_conductance)
         # construction.setUFactor(new_conductance) 
          sub_surface.setUFactor(new_conductance)

        # target_u_value_si = BTAP::Resources::Envelope::Constructions.get_conductance(construction) unless conductance.nil?
        # test if the model was chnaged to the new conductance
          surface_const_cond1 = BTAP::Geometry::Surfaces::get_surface_construction_conductance(sub_surface)
          actual_new_cond =  sub_surface.uFactor
          if (new_conductance.to_f.round(3) == actual_new_cond.to_f.round(3)) then
          # new_construction = OpenStudio::Model::getConstructionByName(sub_surface.model, sub_surface.construction.get.name.to_s).get
            print " \e[32m The model's coductance of #{sub_surface.name.to_s} was =  #{cond.to_f.round(3)} \e[0m , now it is equal to \e[32m #{actual_new_cond.to_f.round(3)} \e[0m '\n'"
          else
            print " \e[33m The model's coductance of #{sub_surface.name.to_s} was =  #{cond.to_f.round(3)} \e[0m , now it is not equal to \e[33m #{actual_new_cond.to_f.round(3)} \e[0m '\n'"
        end

      end

      end

  end

    #report final condition
    runner.registerFinalCondition("The existing insulation for fenestrations was changed to R-#{r_value}. ")
    return true

 end #end the run method
#
 end #end the measure

#this allows the measure to be used by the application
BtapSetFenestrationConductanceByNecbClimateZone.new.registerWithApplication
