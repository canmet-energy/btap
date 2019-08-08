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


class BTAPSetInfiltration_Test < Minitest::Test
  # Brings in helper methods to simplify argument testing of json and standard argument methods.
  include(BTAPMeasureTestHelper)
  def setup()

    @use_json_package = false
    @use_string_double = true
    @measure_interface_detailed = [

        {
            "name" => "infiltration_ip",
            "type" => "Double",
            "display_name" => "infiltration_ip",
            "default_value" => 0.050787498,
            "max_double_value" => 10,
            "min_double_value" => 0.0,
            "is_required" => true
        }


    ]

    @good_input_arguments = {
        "a_double_argument" => 0.091417497

    }

  end


end
