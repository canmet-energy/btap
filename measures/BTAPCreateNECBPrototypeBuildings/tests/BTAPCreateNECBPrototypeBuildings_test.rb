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
class BTAPCreateNECBPrototypeBuilding_Test < Minitest::Test
  def test_create_building()
    # create an instance of the measure
    measure = BTAPCreateNECBPrototypeBuilding.new

    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    # make an empty model
    model = OpenStudio::Model::Model.new

    # test arguments and defaults
    arguments = measure.arguments(model)
    assert_equal(3, arguments.size)
    assert_equal('building_type', arguments[0].name)
    assert_equal('template', arguments[1].name)
    assert_equal('epw_file', arguments[2].name)
    assert_equal('NECB2011', arguments[1].defaultValueAsString)

    # set argument values to values and run the measure
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)

    #argument 0
    building_type = arguments[0].clone
    assert(building_type.setValue('FullServiceRestaurant'))
    argument_map['building_type'] = building_type

    #argument 1
    template = arguments[1].clone
    assert(template.setValue('NECB2011'))
    argument_map['template'] = template

    #argument 2
    epw_file = arguments[2].clone
    assert(epw_file.setValue('CAN_AB_Banff.CS.711220_CWEC2016.epw'))
    argument_map['epw_file'] = epw_file
    measure.run(model, runner, argument_map)
    result = runner.result
    assert(result.value.valueName == 'Success')
  end
end
