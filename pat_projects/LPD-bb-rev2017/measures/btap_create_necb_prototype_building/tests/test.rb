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

  def test_create_necb_vintages
    @templates = ['NECB2011',
                  'NECB2015',
                  'NECB2017']
    @templates.each do |template|
      create_building(template)
    end
  end


  def create_building(template)
    # create an instance of the measure
    measure = BTAPCreateNECBPrototypeBuilding.new

    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    # make an empty model
    model = OpenStudio::Model::Model.new

    # test arguments and defaults
    arguments = measure.arguments(model)
    #check number of arguments.
    assert_equal(3, arguments.size)
    #check argument 0
    assert_equal('building_type', arguments[0].name)
    assert_equal('SmallOffice', arguments[0].defaultValueAsString)
    #check argument 1
    assert_equal('template', arguments[1].name)
    assert_equal(template, arguments[1].defaultValueAsString)
    #check argument 2
    assert_equal('epw_file', arguments[2].name)
    assert_equal('CAN_AB_Banff.CS.711220_CWEC2016.epw', arguments[2].defaultValueAsString)


    # set argument values to values and run the measure
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)

    #set argument 0
    building_type = arguments[0].clone
    assert(building_type.setValue('FullServiceRestaurant'))
    argument_map['building_type'] = building_type

    #set argument 1
    template = arguments[1].clone
    assert(template.setValue(template))
    argument_map['template'] = template

    #set argument 2
    epw_file = arguments[2].clone
    assert(epw_file.setValue('CAN_AB_Banff.CS.711220_CWEC2016.epw'))
    argument_map['epw_file'] = epw_file

    #run the measure
    measure.run(model, runner, argument_map)
    result = runner.result
    assert(result.value.valueName == 'Success')
  end
end
