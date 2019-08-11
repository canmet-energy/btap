# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/

require_relative 'resources/BTAPMeasureHelper'
# start the measure
class BTAPAddASHPWH < OpenStudio::Measure::ModelMeasure
  attr_accessor :use_json_package, :use_string_double
  #Adds helper functions to make life a bit easier and consistent.
  include(BTAPMeasureHelper)
  # human readable name
  def name
    #BEFORE YOU DO anything.. please generate a new <uid>224561f4-8ccc-4f60-8118-34b85359d6f7</uid> and add this to the measure.xml file
    # You can generate a new UUID using the ruby command
    # ruby -e 'require "securerandom";  puts SecureRandom.uuid '
    return "BTAPAddASHPWH"
  end

  # human readable description
  def description
    return "Replaces existing water heater with a ASHPWH "
  end

  # human readable description of modeling approach
  def modeler_description
    return ""
  end

    # define the arguments that the user will input
    def arguments(model)
      args = OpenStudio::Measure::OSArgumentVector.new
  
      frac_oa = OpenStudio::Measure::OSArgument::makeDoubleArgument('frac_oa', false)
      frac_oa.setDisplayName('frac_oa')
      frac_oa.setDefaultValue(1.0)
  
      args << frac_oa
  
      return args
    end
  #Use the constructor to set global variables


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
    #puts JSON.pretty_generate(arguments)

    #You can now access the input argument by the name.

    wh_type = "All"
    frac_oa = runner.getDoubleArgumentValue('frac_oa',user_arguments)

    if frac_oa == 999
      runner.registerInfo("BTAPAddASHPWH is skipped")

    else
      runner.registerInfo("BTAPAddASHPWH is not skipped")
      model_hdd = 1
      if model.building.get.name.to_s.include?("LargeOffice")
        puts "skip large office"
        #skip measure for large offices
      else
        if wh_type == "All"
  
  
          model.getPlantLoops.each do |plantloop|
            plantloop.supplyComponents.each do |comp|
              if comp.to_WaterHeaterMixed.is_initialized
                a = add_ashpwh_mixed(model,plantloop,comp.to_WaterHeaterMixed.get,frac_oa,model_hdd)
                puts "#{a}"
              elsif comp.to_WaterHeaterStratified.is_initialized
                add_ashpwh_stratified(model,plantloop,comp.to_WaterHeaterStratified.get)
              end
            end #plantloop.supplyComponents.each do |comp|
  
  
          end #model.getPlantLoops.each do |plantloop|
        else # if wh_type == "All"
        end # if wh_type == "All"
      end
    end


    
    return true
  end
end


# register the measure to be used by the application
BTAPAddASHPWH.new.registerWithApplication
