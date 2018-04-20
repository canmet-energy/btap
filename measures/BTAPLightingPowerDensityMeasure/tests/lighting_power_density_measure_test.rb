require 'openstudio'
require 'openstudio/measure/ShowRunnerOutput'
require 'minitest/autorun'
require_relative '../measure.rb'
require 'fileutils'

class LightingPowerDensityMeasure_Test < MiniTest::Unit::TestCase

 def test_number_of_arguments_and_argument_names
    # Create an instance of the measure
    measure = LightingPowerDensityMeasure.new
    # Create an instance of a runner
    runner = OpenStudio::Ruleset::OSRunner.new
    # Make an empty model
    model = OpenStudio::Model::Model.new

    # Get arguments and test that they are what we are expecting
    arguments = measure.arguments(model)
    assert_equal(3, arguments.size)
    assert_equal("space_type", arguments[0].name)
	assert_equal("lpd_type", arguments[1].name)
	assert_equal("percent", arguments[1].defaultValueAsString)
	assert_equal("lpd_value", arguments[2].name)
	assert_equal(0.8, arguments[2].defaultValueAsDouble)
	puts " The number of arguments and default values are correct" 

	# Set argument values to bad values and run the measure
    argument_map = OpenStudio::Ruleset::OSArgumentMap.new

    count = -1

    space_type = arguments[count += 1].clone
    assert(space_type.setValue("*Entire Building*"))
    argument_map["space_type"] = space_type
	
	lpd_type = arguments[count += 1].clone
    assert(lpd_type.setValue("percent"))
    argument_map["lpd_type"] = lpd_type

    lpd_value = arguments[count += 1].clone
    assert(lpd_value.setValue(120))
    argument_map["lpd_value"] = lpd_value
	
	measure.run(model, runner, argument_map)
    result = runner.result       
    # Assert that it ran correctly
    assert_equal("Fail", result.value.valueName)
	puts " The model succeeded to fail with too high values of 'lpd_percent' " 
 end
	
 def test_LightingPowerDensityMeasure_Very_High_percentages
    puts "Checking warning messages for very high percentages of LPD_values"

    # Create an instance of the measure
    measure = LightingPowerDensityMeasure.new
    # Create an instance of a runner
    runner = OpenStudio::Ruleset::OSRunner.new
    # Make an empty model
    model = OpenStudio::Model::Model.new
    # Get arguments and test that they are what we are expecting
    arguments = measure.arguments(model)
    # Set argument values to NA values and run the measure on empty model
    argument_map = OpenStudio::Ruleset::OSArgumentMap.new

    count = -1
	
	space_type = arguments[count += 1].clone
    assert(space_type.setValue("*Entire Building*"))
    argument_map["space_type"] = space_type
	
	lpd_type = arguments[count += 1].clone
    assert(lpd_type.setValue("percent"))
    argument_map["lpd_type"] = lpd_type

    lpd_value = arguments[count += 1].clone
    assert(lpd_value.setValue(95))
    argument_map["lpd_value"] = lpd_value
	
	measure.run(model, runner, argument_map)
    result = runner.result
    assert(result.value.valueName == "NA")
    assert(result.warnings.size == 1)
	puts "LPD percentage is very high. "
 end
	
 def test_LightingPowerDensityMeasure_low__percentages
    puts "Checking warning messages for very low values of LPD_percent"

    # Create an instance of the measure
    measure = LightingPowerDensityMeasure.new
    # Create an instance of a runner
    runner = OpenStudio::Ruleset::OSRunner.new
    # Make an empty model
    model = OpenStudio::Model::Model.new
    # Get arguments and test that they are what we are expecting
    arguments = measure.arguments(model)
    # Set argument values to NA values and run the measure on empty model
    argument_map = OpenStudio::Ruleset::OSArgumentMap.new

    count = -1
	
	# Set argument values to NA values and run the measure on empty model
    argument_map = OpenStudio::Ruleset::OSArgumentMap.new

    count = -1
	
	space_type = arguments[count += 1].clone
    assert(space_type.setValue("*Entire Building*"))
    argument_map["space_type"] = space_type
	
	lpd_type = arguments[count += 1].clone
    assert(lpd_type.setValue("percent"))
    argument_map["lpd_type"] = lpd_type

    lpd_value = arguments[count += 1].clone
    assert(lpd_value.setValue(0.75))
    argument_map["lpd_value"] = lpd_value
	
	measure.run(model, runner, argument_map)
    result = runner.result
    assert(result.value.valueName == "NA")
    assert(result.warnings.size == 1)	
	puts "LPD percentage is very low. "
 end
 
 def test_LightingPowerDensityMeasure_Too_High_IP_Values
    puts "Checking error messages for too high IP values of LPD_values"

    # Create an instance of the measure
    measure = LightingPowerDensityMeasure.new
    # Create an instance of a runner
    runner = OpenStudio::Ruleset::OSRunner.new

    # Load the test model
    translator = OpenStudio::OSVersion::VersionTranslator.new
    path = OpenStudio::Path.new(File.dirname(__FILE__) + "/example_model.osm")
    model = translator.loadModel(path)
    assert((not model.empty?))
    model = model.get
    
    # Refresh arguments
    arguments = measure.arguments(model)
    
    # Set argument values to good values and run the measure on entire model with spaces
    argument_map = OpenStudio::Ruleset::OSArgumentMap.new

    count = -1
	space_type = arguments[count += 1].clone
    assert(space_type.setValue("*Entire Building*"))
    argument_map["space_type"] = space_type
	
	lpd_type = arguments[count += 1].clone
    assert(lpd_type.setValue("value(W/ft^2)"))
    argument_map["lpd_type"] = lpd_type

    lpd_value = arguments[count += 1].clone
    assert(lpd_value.setValue(60))
    argument_map["lpd_value"] = lpd_value
	
	measure.run(model, runner, argument_map)
    result = runner.result
   	assert_equal("Fail", result.value.valueName)
	puts " The model succeeded to fail with too high IP LPD values. " 
 end
  
 def test_LightingPowerDensityMeasure_High_IP_Values
    puts "Checking warning messages for high IP LPD_values"

    # Create an instance of the measure
    measure = LightingPowerDensityMeasure.new
    # Create an instance of a runner
    runner = OpenStudio::Ruleset::OSRunner.new
    # Make an empty model
    model = OpenStudio::Model::Model.new
    # Get arguments and test that they are what we are expecting
    arguments = measure.arguments(model)
	# Set argument values to NA values and run the measure on empty model
    argument_map = OpenStudio::Ruleset::OSArgumentMap.new

    count = -1
	
	space_type = arguments[count += 1].clone
    assert(space_type.setValue("*Entire Building*"))
    argument_map["space_type"] = space_type
	
	lpd_type = arguments[count += 1].clone
    assert(lpd_type.setValue("value(W/ft^2)"))
    argument_map["lpd_type"] = lpd_type

    lpd_value = arguments[count += 1].clone
    assert(lpd_value.setValue(35))
    argument_map["lpd_value"] = lpd_value
	
	measure.run(model, runner, argument_map)
    result = runner.result
    assert(result.value.valueName == "NA")
    assert(result.warnings.size == 1)	
	puts "LPD value of 35 W/ft^2 is very high. "
 end
 
 def test_LightingPowerDensityMeasure_Negative_IP_Values
    puts "Checking error messages for negative values of LPD_IP_values"

    # Create an instance of the measure
    measure = LightingPowerDensityMeasure.new
    # Create an instance of a runner
    runner = OpenStudio::Ruleset::OSRunner.new
    # Load the test model
    translator = OpenStudio::OSVersion::VersionTranslator.new
    path = OpenStudio::Path.new(File.dirname(__FILE__) + "/example_model.osm")
    model = translator.loadModel(path)
    assert((not model.empty?))
    model = model.get
    # Refresh arguments
    arguments = measure.arguments(model)
    # Set argument values to good values and run the measure on entire model with spaces
    argument_map = OpenStudio::Ruleset::OSArgumentMap.new

    count = -1
	space_type = arguments[count += 1].clone
    assert(space_type.setValue("*Entire Building*"))
    argument_map["space_type"] = space_type
	
	lpd_type = arguments[count += 1].clone
    assert(lpd_type.setValue("value(W/ft^2)"))
    argument_map["lpd_type"] = lpd_type

    lpd_value = arguments[count += 1].clone
    assert(lpd_value.setValue(-10))
    argument_map["lpd_value"] = lpd_value
	
	measure.run(model, runner, argument_map)
    result = runner.result
   	assert_equal("Fail", result.value.valueName)
	puts " The model succeeded to fail with negative values of LPD (IP units). " 
 end
 
 def test2_LightingPowerDensityMeasure_Too_high_Values_SI
    puts "Checking error messages for too high LPD_values (W/m^2)"

    # Create an instance of the measure
    measure = LightingPowerDensityMeasure.new
    # Create an instance of a runner
    runner = OpenStudio::Ruleset::OSRunner.new
    # Make an empty model
    model = OpenStudio::Model::Model.new
    # Get arguments and test that they are what we are expecting
    arguments = measure.arguments(model)
    # Set argument values to NA values and run the measure on empty model
    argument_map = OpenStudio::Ruleset::OSArgumentMap.new

    count = -1
	
	space_type = arguments[count += 1].clone
    assert(space_type.setValue("*Entire Building*"))
    argument_map["space_type"] = space_type
	
	lpd_type = arguments[count += 1].clone
    assert(lpd_type.setValue("value(W/m^2)"))
    argument_map["lpd_type"] = lpd_type

    lpd_value = arguments[count += 1].clone
    assert(lpd_value.setValue(600))
    argument_map["lpd_value"] = lpd_value
	
	measure.run(model, runner, argument_map)
    result = runner.result
   	assert_equal("Fail", result.value.valueName)
	puts " The model succeeded to fail with too high values of 'lpd_value_w/m^2' " 
 end
  
 def test_LightingPowerDensityMeasure_High_Values_SI
   puts "Loading the example_model.osm and Checking warning messages for high values of LPD_SI_values"

    # Create an instance of the measure
    measure = LightingPowerDensityMeasure.new
    # Create an instance of a runner
    runner = OpenStudio::Ruleset::OSRunner.new

    # Load the test model
    translator = OpenStudio::OSVersion::VersionTranslator.new
    path = OpenStudio::Path.new(File.dirname(__FILE__) + "/example_model.osm")
    model = translator.loadModel(path)
    assert((not model.empty?))
    model = model.get
    
    # Refresh arguments
    arguments = measure.arguments(model)
    
    # Set argument values to good values and run the measure on entire model with spaces
    argument_map = OpenStudio::Ruleset::OSArgumentMap.new

    count = -1
	space_type = arguments[count += 1].clone
    assert(space_type.setValue("*Entire Building*"))
    argument_map["space_type"] = space_type
	
	lpd_type = arguments[count += 1].clone
    assert(lpd_type.setValue("value(W/m^2)"))
    argument_map["lpd_type"] = lpd_type

    lpd_value = arguments[count += 1].clone
    assert(lpd_value.setValue(350))
    argument_map["lpd_value"] = lpd_value
	
	measure.run(model, runner, argument_map)
    result = runner.result
    show_output(result)
    assert(result.value.valueName == "Success")
    assert(result.warnings.size == 1)
	puts "LPD value of 350 w/m^2 is very high. "
 end

 def test_LightingPowerDensityMeasure_Negative_SI_Values
    puts "Checking error messages for negative LPD_SI_values. "

    # Create an instance of the measure
    measure = LightingPowerDensityMeasure.new
    # Create an instance of a runner
    runner = OpenStudio::Ruleset::OSRunner.new
    # Load the test model
    translator = OpenStudio::OSVersion::VersionTranslator.new
    path = OpenStudio::Path.new(File.dirname(__FILE__) + "/example_model.osm")
    model = translator.loadModel(path)
    assert((not model.empty?))
    model = model.get
    # Refresh arguments
    arguments = measure.arguments(model)
    # Set argument values to good values and run the measure on entire model with spaces
    argument_map = OpenStudio::Ruleset::OSArgumentMap.new

    count = -1
	space_type = arguments[count += 1].clone
    assert(space_type.setValue("*Entire Building*"))
    argument_map["space_type"] = space_type
	
	lpd_type = arguments[count += 1].clone
    assert(lpd_type.setValue("value(W/m^2)"))
    argument_map["lpd_type"] = lpd_type

    lpd_value = arguments[count += 1].clone
    assert(lpd_value.setValue(-10))
    argument_map["lpd_value"] = lpd_value
	
	measure.run(model, runner, argument_map)
    result = runner.result
   	assert_equal("Fail", result.value.valueName)
	puts " The model succeeded to fail with negative values of LPD (SI units). " 
 end
    
 def test_good_argument_values
    # Create an instance of the measure
    measure = LightingPowerDensityMeasure.new
    # Create runner with empty OSW
    osw = OpenStudio::WorkflowJSON.new
    runner = OpenStudio::Measure::OSRunner.new(osw)
    # Load the test model
    translator = OpenStudio::OSVersion::VersionTranslator.new
    path = OpenStudio::Path.new(File.dirname(__FILE__) + "/example_model.osm")
    model = translator.loadModel(path)
    assert((not model.empty?))
    model = model.get
    # Store the number of spaces in the seed model
    num_spaces_seed = model.getSpaces.size
    # Get arguments
    arguments = measure.arguments(model)
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    
	count = -1 
	
    space_type = arguments[count += 1].clone
    assert(space_type.setValue("*Entire Building*"))
    argument_map["space_type"] = space_type
	
	lpd_type = arguments[count += 1].clone
    assert(lpd_type.setValue("value(W/m^2)"))
    argument_map["lpd_type"] = lpd_type

    lpd_value = arguments[count += 1].clone
    assert(lpd_value.setValue(20))
    argument_map["lpd_value"] = lpd_value
  
    # Check that there is now 1 space
    assert_equal(0, model.getSpaces.size - num_spaces_seed)
	
	measure.run(model, runner, argument_map)
    result = runner.result
    show_output(result)
    assert(result.value.valueName == "Success")
    

    # Save the model to test output directory
    output_file_path = OpenStudio::Path.new(File.dirname(__FILE__) + "/output/example_model.osm")
    model.save(output_file_path,true)
  end

end
