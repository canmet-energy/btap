require 'openstudio'
require 'openstudio/measure/ShowRunnerOutput'
require 'fileutils'
begin
  require 'openstudio_measure_tester/test_helper'
rescue LoadError
  puts 'OpenStudio Measure Tester Gem not installed -- will not be able to aggregate and dashboard the results of tests'
end
require_relative '../measure.rb'
require 'minitest/autorun'


class BTAPExteriorWallMeasure_Test < Minitest::Test
  def test_create_building()
    # create an instance of the measure
    measure = BTAPExteriorWallMeasure.new

    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    # make an empty model
    model = OpenStudio::Model::Model.new

    # test arguments and defaults
    arguments = measure.arguments(model)
    #check number of arguments.
    assert_equal(3, arguments.size)
    #check argument 0
    assert_equal('ecm_exterior_wall_conductance', arguments[0].name)
    assert_equal(0.183, arguments[0].defaultValueAsDouble)
    #check argument 1
    assert_equal('ecm_start_angle_in_degrees', arguments[1].name)
    assert_equal(0.0, arguments[1].defaultValueAsDouble)
    #check argument 2
    assert_equal('ecm_end_angle_in_degrees', arguments[2].name)
    assert_equal(360.0, arguments[2].defaultValueAsDouble)

    # set argument values to values and run the measure
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)

    #set argument 0
    ecm_exterior_wall_conductance = arguments[0].clone
    assert(ecm_exterior_wall_conductance.setValue(0.183))
    argument_map['ecm_exterior_wall_conductance'] = ecm_exterior_wall_conductance

    #set argument 1
    ecm_start_angle_in_degrees = arguments[1].clone
    assert(ecm_start_angle_in_degrees.setValue(0.0))
    argument_map['ecm_start_angle_in_degrees'] = ecm_start_angle_in_degrees

    #set argument 2
    ecm_end_angle_in_degrees = arguments[2].clone
    assert(ecm_end_angle_in_degrees.setValue(360.0))
    argument_map['ecm_end_angle_in_degrees'] = ecm_end_angle_in_degrees

    #run the measure
    measure.run(model, runner, argument_map)
    result = runner.result
    assert(result.value.valueName == 'Success')
  end
end
