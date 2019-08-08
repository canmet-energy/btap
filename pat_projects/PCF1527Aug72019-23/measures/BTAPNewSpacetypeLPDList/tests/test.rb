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


class BTAPNewSpacetypeLPDList_Test < Minitest::Test
  # Brings in helper methods to simplify argument testing of json and standard argument methods.
  include(BTAPMeasureTestHelper)
  def setup()

    @use_json_package = false
    @use_string_double = true
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
        }


    ]

    @good_input_arguments = {
        "skipspacetype" => "MyString",
        "fracchange" => 0.5,

    }

  end

  def test_sample()



      # Set up your argument list to test.
      input_arguments = {
          "skipspacetype" => "something",
          "fracchange" => 0.5,
      }

    model = create_necb_protype_model(
        "SmallHotel",
           'NECB HDD Method',
            'CAN_BC_Vancouver.Intl.AP.718920_CWEC2016.epw',
           "NECB2015"
         )


    # Create an instance of the measure
    runner = run_measure(input_arguments, model)
    puts show_output(runner.result)

    assert(runner.result.value.valueName == 'Success')
  end
end
