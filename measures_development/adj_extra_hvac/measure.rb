# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/
require_relative 'resources/BTAPMeasureHelper'

# start the measure
class Adj_extra_hvac < OpenStudio::Measure::ModelMeasure

  attr_accessor :use_json_package, :use_string_double
  #Adds helper functions to make life a bit easier and consistent.
  include(BTAPMeasureHelper)
  # human readable name
  def name
    #BEFORE YOU DO anything.. please generate a new <uid>224561f4-8ccc-4f60-8118-34b85359d6f7</uid> and add this to the measure.xml file
    # You can generate a new UUID using the ruby command
    # ruby -e 'require "securerandom";  puts SecureRandom.uuid '
    return "Adj_extra_hvac"
  end

  # human readable description
  def description
    return "This template measure is used to ensure consistency in detailed BTAP measures."
  end

  # human readable description of modeling approach
  def modeler_description
    return "This template measure is used to ensure consistency in BTAP measures."
  end

  #Use the constructor to set global variables
  # define the arguments that the user will input
  def arguments(model)
    args = OpenStudio::Measure::OSArgumentVector.new

    measure_to_adj_for = OpenStudio::Ruleset::OSArgument::makeIntegerArgument('measure_to_adj_for', false)
    measure_to_adj_for.setDisplayName('measure_to_adj_for?')
    measure_to_adj_for.setDefaultValue(1)

    args << measure_to_adj_for

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
    measure_to_adj_for = runner.getIntegerArgumentValue('measure_to_adj_for',user_arguments)
 

    if measure_to_adj_for == 1
          #Get the zones that are connected to an air loop with an outdoor air system
          airloops = model.getAirLoopHVACs
          airloops.each do |airloop|
            airloop.supplyComponents.each do |supplyComponent|
              if supplyComponent.to_AirLoopHVACOutdoorAirSystem.is_initialized
                airloop_oas_sys = supplyComponent.to_AirLoopHVACOutdoorAirSystem.get
                #this air loop serves zones with an OAS. Set up DOAS for the zones served by this air loop

                #each of these zones got an ERV and does needs to have its 
                airloop.thermalZones.each do |zone|
                  remove_extra_comp_AddDOASSysAndVAV(model,zone)
                  autosize_affected_hvac_AddDOASSysAndVAV(model,zone)
                end
              end
            end
          end #airloops.each do |airloop|

    elsif measure_to_adj_for == 0
      puts "Adj_extra_hvac is skipped"

    else #adj for doas_vrf measure

      if model.building.get.name.to_s.include?("MediumOffice") or model.building.get.name.to_s.include?("HighriseApartment") or model.building.get.name.to_s.include?("LargeOffice")
    

          list_of_vrf_zones = []
          model.getAirLoopHVACs.each do|airloop|
            #turn each air loop into a doas
            loop_zones = airloop.thermalZones
            #add vrf if these are offices
            if model.building.get.name.to_s.include?("MediumOffice")  or model.building.get.name.to_s.include?("LargeOffice")#one vrf outdoor unit for each air loop
              remove_extra_comp_doas_vrf(model,loop_zones)
              autosize_affected_hvac_doas_vrf(model,loop_zones)
            end 
            loop_zones.each do |zone|
              list_of_vrf_zones << zone
            end
          end
          
          if model.building.get.name.to_s.include?("HighriseApartment") #highrise will share a single vrf outdoor unit
            remove_extra_comp_doas_vrf(model,list_of_vrf_zones)
            autosize_affected_hvac_doas_vrf(model,list_of_vrf_zones)
          end

        
      else
        puts "not a medium office or highrise"
      end#if model.building.get.name.to_s.include?("LargeOffice") or model.building.get.name.to_s.include?("MediumOffice") or model.buil....
  


    end #if measure_to_adj_for == 1

    return true
  end
end


# register the measure to be used by the application
Adj_extra_hvac.new.registerWithApplication
