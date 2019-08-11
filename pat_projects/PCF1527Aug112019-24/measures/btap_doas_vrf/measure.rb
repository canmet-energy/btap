# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/
require_relative 'resources/BTAPMeasureHelper'
# start the measure
class BTAPDOASVRF < OpenStudio::Measure::ModelMeasure

  attr_accessor :use_json_package, :use_string_double
  #Adds helper functions to make life a bit easier and consistent.
  include(BTAPMeasureHelper)
  # human readable name
  def name
    #BEFORE YOU DO anything.. please generate a new <uid>224561f4-8ccc-4f60-8118-34b85359d6f7</uid> and add this to the measure.xml file
    # You can generate a new UUID using the ruby command
    # ruby -e 'require "securerandom";  puts SecureRandom.uuid '
    return "BTAPDOASVRF"
  end

  # human readable description
  def description
    return "Changes air loop to doas, adds vrf for those zones"
  end

  # human readable description of modeling approach
  def modeler_description
    return ""
  end

  # define the arguments that the user will input
  def arguments(model)
    args = OpenStudio::Measure::OSArgumentVector.new

    loops_to_change = OpenStudio::Measure::OSArgument::makeStringArgument('loops_to_change', false)
    loops_to_change.setDisplayName('loops_to_change')
    loops_to_change.setDefaultValue("All")

    args << loops_to_change

    return args
  end
  # define what happens when the measure is run
  def run(model, runner, user_arguments)
    #Runs parent run method.
    super(model, runner, user_arguments)
    # Gets arguments from interfaced and puts them in a hash with there display name. This also does a check on ranges to
    # ensure that the values inputted are valid based on your @measure_interface array of hashes.
    # use the built-in error checking
    if !runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end
    #You can now access the input argument by the name.
    # arguments['a_string_argument']
    # arguments['a_double_argument']
    #loops_to_change = arguments["loops_to_change"]
    loops_to_change = runner.getStringArgumentValue('loops_to_change',user_arguments)

    if loops_to_change == "999"
      runner.registerInfo("BTAPDOASVRF is skipped")

    else
      runner.registerInfo("BTAPDOASVRF is not skipped")

      if model.building.get.name.to_s.include?("MediumOffice") or model.building.get.name.to_s.include?("HighriseApartment")
    
        if loops_to_change == "All"
          list_of_vrf_zones = []
          model.getAirLoopHVACs.each do|airloop|
            #turn each air loop into a doas
            loop_zones = airloop.thermalZones
            set_up_doas(model,airloop,loop_zones)
            #add vrf if these are offices
            if model.building.get.name.to_s.include?("MediumOffice")  #one vrf outdoor unit for each air loop
              add_vrf_for_offices(model,loop_zones)
            end 
            loop_zones.each do |zone|
              list_of_vrf_zones << zone
            end
          end
          if model.building.get.name.to_s.include?("MediumOffice")
          elsif model.building.get.name.to_s.include?("HighriseApartment") #highrise will share a single vrf outdoor unit
            add_vrf_for_offices(model,list_of_vrf_zones)
          end
        end #if loops_to_change == 'All'
      else
        puts "not a medium office or highrise"
      end#if model.building.get.name.to_s.include?("LargeOffice") or model.building.get.name.to_s.include?("MediumOffice") or model.buil....
  
    end



    #Do something.
    return true
  end
end


# register the measure to be used by the application
BTAPDOASVRF.new.registerWithApplication
