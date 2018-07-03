require 'openstudio'
require 'openstudio/measure/ShowRunnerOutput'
require 'fileutils'
require 'openstudio-standards'
begin
  require 'openstudio_measure_tester/test_helper'
rescue LoadError
  puts 'OpenStudio Measure Tester Gem not installed -- will not be able to aggregate and dashboard the results of tests'
end
require_relative '../measure.rb'
require_relative '../resources/BTAPMeasureHelper.rb'
require 'minitest/autorun'


class BTAPModelMeasure_Test < Minitest::Test
  # Brings in helper methods to simplify argument testing of json and standard argument methods.
  include(BTAPMeasureTestHelper)
  def setup()

    @use_json_package = false
    @use_string_double = true
    @measure_interface_detailed = [
    ]

    @good_input_arguments = {}

  end

  def test_sample()
    ####### Test Model Creation######

      model = create_necb_protype_model(
          "LargeOffice",
         'NECB HDD Method',
          'CAN_BC_Vancouver.Intl.AP.718920_CWEC2016.epw',
          "NECB2011"
       )

    input_arguments = {}


    # Create an instance of the measure
    runner = run_measure(input_arguments, model)
    puts show_output(runner.result)

    assert(runner.result.value.valueName == 'Success')
  end
end
