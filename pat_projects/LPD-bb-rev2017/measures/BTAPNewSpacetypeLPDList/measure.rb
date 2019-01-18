# see the URL below for information on how to write OpenStudio measures
# http://nrel.github.io/OpenStudio-user-documentation/reference/measure_writing_guide/
require_relative 'resources/BTAPMeasureHelper'
require 'json'
require 'openstudio-standards'

# start the measure
class BTAPNewSpacetypeLPDList < OpenStudio::Measure::ModelMeasure

  attr_accessor :use_json_package, :use_string_double
  include(BTAPMeasureHelper)

  # human readable name
  def name
    #BEFORE YOU DO anything.. please generate a new <uid>224561f4-8ccc-4f60-8118-34b85359d6f7</uid> and add this to the measure.xml file
    # You can generate a new UUID using the ruby command
    # ruby -e 'require "securerandom";  puts SecureRandom.uuid '
    return "BTAPNewSpacetypeLPDList"
  end

  # human readable description
  def description
    return "This  measure changes space type LPD based on associated json file in the resource folder."
  end

  # human readable description of modeling approach
  def modeler_description
    return "Reads the spacetypes in the model and replaces the model LPD with the LPD specified in the json file."
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
            "name" => "skipspacetype",
            "type" => "String",
            "display_name" => "Spacetypes to skip",
            "default_value" => "None",
            "is_required" => false
        },
        {
            "name" => "fracchange",
            "type" => "Double",
            "display_name" => "Fractional change",
            "default_value" => 1.0,
            "max_double_value" => 1.0,
            "min_double_value" => 0.0,
            "is_required" => false
        },

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

    #Do something.
    puts "#{}"
    puts "yay"

    #Read in space types and new LPD values
    path = File.expand_path('../resources/listofspacenameschangedIP.txt',__FILE__)
    spacetypedata = File.read(path).split(",").map(&:strip)
    length_of_spacetypedata = spacetypedata.length


    #Get space types in model
    model_space_types = model.getSpaceTypes


    #Loop through each space type from the model
    model_space_types.each do |model_space_type|
      puts "current model spactype #{model_space_type.name.to_s}"

      #Find matching space type from data file
      for index in (0...length_of_spacetypedata)
        if model_space_type.name.to_s == spacetypedata[index] #if it matches

          #Get model space type's lighting defn ready
          model_space_type_lights = model_space_type.lights
          model_space_type_lights.each do |model_space_type_light|

            #Get the model's light:definition object and print out initial LPD
            model_space_type_lightsDefn = model_space_type_light.lightsDefinition
            model_initial_LPD = model_space_type_lightsDefn.wattsperSpaceFloorArea
            puts "Initial LPD #{model_initial_LPD} W/m2"


            #Change the model space type's light:definition object's lighting power density to the value found in data file.
            # IF there is a value in the datafile (not "NA")
            datavalue = spacetypedata[index+1]
            if datavalue.to_s == "NA"

              puts "Datafile has NA LPD #{datavalue}"
              puts "The initial LPD #{model_space_type_light.lightsDefinition.wattsperSpaceFloorArea} remains unchanged"
              puts "-===================================NA================================================================"
            else
              puts "Datafile LPD is #{(spacetypedata[index+1].to_f)/0.092903}"
              model_space_type_lightsDefn.setWattsperSpaceFloorArea((datavalue.to_f)/0.092903)
              model_space_type_lightsDefn.setName("#{model_space_type_lightsDefn.name.to_s}-new")

              #Set the revised lighting definition as the new lighting definition
              model_space_type_light.setLightsDefinition(model_space_type_lightsDefn)

              puts "New LPD is #{model_space_type_light.lightsDefinition.wattsperSpaceFloorArea} W/m2"


            end



          end


        end

      end




    end




    return true
  end
end


# register the measure to be used by the application
BTAPNewSpacetypeLPDList.new.registerWithApplication
