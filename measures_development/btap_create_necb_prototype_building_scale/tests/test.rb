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
class BTAPCreateNECBPrototypeBuildingScale_Test < Minitest::Test
  def test_create_building()
    # create an instance of the measure
    measure = BTAPCreateNECBPrototypeBuildingScale.new

    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    # make an empty model
    model = OpenStudio::Model::Model.new

    # test arguments and defaults
    arguments = measure.arguments(model)
    #check number of arguments.
    assert_equal(8, arguments.size)
    #check argument 0
    assert_equal('building_type', arguments[0].name)
    assert_equal('SmallOffice', arguments[0].defaultValueAsString)
    #check argument 1
    assert_equal('template', arguments[1].name)
    assert_equal('NECB2011', arguments[1].defaultValueAsString)
    #check argument 2
    assert_equal('epw_file', arguments[2].name)
    assert_equal('CAN_AB_Banff.CS.711220_CWEC2016.epw', arguments[2].defaultValueAsString)
    #check argument 3
    assert_equal('volume_scale_factor', arguments[3].name)
    assert_equal(1.0, arguments[3].defaultValueAsDouble)
    #check argument 4
    assert_equal('area_scale_factor', arguments[4].name)
    assert_equal(1.0, arguments[4].defaultValueAsDouble)
    #check argument 5
    assert_equal('x_scale_factor', arguments[5].name)
    assert_equal(1.0, arguments[5].defaultValueAsDouble)
    #check argument 6
    assert_equal('y_scale_factor', arguments[6].name)
    assert_equal(1.0, arguments[6].defaultValueAsDouble)
    #check argument 7
    assert_equal('z_scale_factor', arguments[7].name)
    assert_equal(1.0, arguments[7].defaultValueAsDouble)


    # set argument values to values and run the measure
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)

    #set argument 0
    building_type = arguments[0].clone
    assert(building_type.setValue('FullServiceRestaurant'))
    argument_map['building_type'] = building_type

    #set argument 1
    template = arguments[1].clone
    assert(template.setValue('NECB2011'))
    argument_map['template'] = template

    #set argument 2
    epw_file = arguments[2].clone
    assert(epw_file.setValue('CAN_AB_Banff.CS.711220_CWEC2016.epw'))
    argument_map['epw_file'] = epw_file

    #set argument 3
    volume_scale_factor = arguments[3].clone
    assert(volume_scale_factor.setValue(1.0))
    argument_map['volume_scale_factor'] = volume_scale_factor

    #set argument 4
    area_scale_factor = arguments[4].clone
    assert(area_scale_factor.setValue(1.0))
    argument_map['area_scale_factor'] = area_scale_factor

    #set argument 5
    x_scale_factor = arguments[5].clone
    assert(x_scale_factor.setValue(1.0))
    argument_map['x_scale_factor'] = x_scale_factor

    #set argument 6
    y_scale_factor = arguments[6].clone
    assert(y_scale_factor.setValue(1.0))
    argument_map['y_scale_factor'] = y_scale_factor

    #set argument 7
    z_scale_factor = arguments[7].clone
    assert(z_scale_factor.setValue(1.0))
    argument_map['z_scale_factor'] = z_scale_factor

    #run the measure
    measure.run(model, runner, argument_map)
    result = runner.result
    assert(result.value.valueName == 'Success')
  end
end
