# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/
require_relative 'resources/BTAPMeasureHelper'

# start the measure
class AddERVPower < OpenStudio::Measure::ModelMeasure

  attr_accessor :use_json_package, :use_string_double
  #Adds helper functions to make life a bit easier and consistent.
  include(BTAPMeasureHelper)
  # human readable name
  def name
    #BEFORE YOU DO anything.. please generate a new <uid>224561f4-8ccc-4f60-8118-34b85359d6f7</uid> and add this to the measure.xml file
    # You can generate a new UUID using the ruby command
    # ruby -e 'require "securerandom";  puts SecureRandom.uuid '
    return "AddERVPower"
  end

  # human readable description
  def description
    return " "
  end

  # human readable description of modeling approach
  def modeler_description
    return "This template measure is used to ensure consistency in BTAP measures."
  end

  #Use the constructor to set global variables
  def initialize()
    super()
    #Set to true if you want to package the arguments as json.
    @use_json_package = false
    #Set to true if you want to want to allow strings and doubles in stringdouble types. Set to false to force to use doubles. The latter is used for certain
    # continuous optimization algorithms. You may have to re-examine your input in PAT as this fundamentally changes the measure.
    @use_string_double = true

    # Put in this array of hashes all the input variables that you need in your measure. Your choice of types are Sting, Double,
    # StringDouble, and Choice. Optional fields are valid strings, max_double_value, and min_double_value. This will
    # create all the variables, validate the ranges and types you need,  and make them available in the 'run' method as a hash after
    # you run 'arguments = validate_and_get_arguments_in_hash(model, runner, user_arguments)'
    @measure_interface_detailed = [
        {
            "name" => "a_string_argument",
            "type" => "String",
            "display_name" => "A String Argument (string)",
            "default_value" => "The Default Value",
            "is_required" => true
        }
    ]
  end

  # define what happens when the measure is run
  def run(model, runner, user_arguments)
    #Runs parent run method.
    super(model, runner, user_arguments)
    # Gets arguments from interfaced and puts them in a hash with there display name. This also does a check on ranges to
    # ensure that the values inputted are valid based on your @measure_interface array of hashes.
    arguments = validate_and_get_arguments_in_hash(model, runner, user_arguments)
    #puts JSON.pretty_generate(arguments)
    return false if false == arguments
    #You can now access the input argument by the name.
    # arguments['a_string_argument']
    # arguments['a_double_argument']
    # etc......
    # So write your measure code here!
    eq_lists = model.getZoneHVACEquipmentLists
    model.getThermalZones.each do |zone|
      eq_lists.each do |eq_list|
        if eq_list.thermalZone == zone
          eq_list.equipmentInHeatingOrder.each do |eqp|
            if eqp.name.to_s.include?("erv doas") and eqp.to_ZoneHVACEnergyRecoveryVentilator.is_initialized
              area =zone.floorArea
              vent_per_floor = eqp.to_ZoneHVACEnergyRecoveryVentilator.get.ventilationRateperUnitFloorArea
              erv_vent_flow = area*vent_per_floor
              power = (erv_vent_flow * 212.5 / 0.5) + (erv_vent_flow * 0.9 * 162.5 / 0.5) + 50 #from op[enstudio] standards
              result= eqp.to_ZoneHVACEnergyRecoveryVentilator.get.heatExchanger.to_HeatExchangerAirToAirSensibleAndLatent.get.setNominalElectricPower(power)
              runner.registerInfo("#{result}")
              runner.registerInfo("#{power}")
            end
          end


        end
      end
    end
    return true
  end
end


# register the measure to be used by the application
AddERVPower.new.registerWithApplication
