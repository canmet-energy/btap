require 'openstudio'
require 'openstudio/ruleset/ShowRunnerOutput'

require "#{File.dirname(__FILE__)}/../measure.rb"

require 'minitest/autorun'

class IncreaseInsulationRValueForExteriorWalls_Test < MiniTest::Unit::TestCase
  
  
  def test_IncreaseInsulationRValueForExteriorWalls_01_bad
     
    # create an instance of the measure
    measure = IncreaseInsulationRValueForExteriorWalls.new
    
    # create an instance of a runner
    runner = OpenStudio::Ruleset::OSRunner.new
    
    # make an empty model
    model = OpenStudio::Model::Model.new
    
    # get arguments and test that they are what we are expecting
    arguments = measure.arguments(model)


    # set argument values to bad values and run the measure
    argument_map = OpenStudio::Ruleset::OSArgumentMap.new
    measure.run(model, runner, argument_map)
    result = runner.result
       
    assert(result.value.valueName == "Success")
    
  end  
  

end