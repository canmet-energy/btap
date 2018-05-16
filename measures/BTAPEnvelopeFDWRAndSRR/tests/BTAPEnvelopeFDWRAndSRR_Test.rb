# *******************************************************************************
# OpenStudio(R), Copyright (c) 2008-2018, Alliance for Sustainable Energy, LLC.
# All rights reserved.
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# (1) Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# (2) Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# (3) Neither the name of the copyright holder nor the names of any contributors
# may be used to endorse or promote products derived from this software without
# specific prior written permission from the respective party.
#
# (4) Other than as required in clauses (1) and (2), distributions in any form
# of modifications or other derivative works may not use the "OpenStudio"
# trademark, "OS", "os", or any other confusingly similar designation without
# specific prior written permission from Alliance for Sustainable Energy, LLC.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDER(S) AND ANY CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
# THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER(S), ANY CONTRIBUTORS, THE
# UNITED STATES GOVERNMENT, OR THE UNITED STATES DEPARTMENT OF ENERGY, NOR ANY OF
# THEIR EMPLOYEES, BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT
# OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
# OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
# *******************************************************************************

require 'openstudio'
require 'openstudio/measure/ShowRunnerOutput'
require 'fileutils'
require 'openstudio-standards'
begin
  require 'openstudio_measure_tester/test_helper'
rescue LoadError
  puts 'OpenStudio Measure Tester Gem not installed -- will not be able to aggregate and dashboard the results of tests'
end
require_relative '../resources/BTAPMeasureHelper'
require_relative '../measure.rb'
require 'minitest/autorun'

class BTAPEnvelopeFDWRandSRR_Test < Minitest::Test
  include(BTAPMeasureTestHelper)
  def setup
    @use_json_package = false
    @use_string_double = false
    @templates = [
        'NECB2011',
        'NECB2015'
    ]
    @limit_or_max_values = [
        'Limit',
        'Maximize'
    ]
    #Assuming a skylight area of this.
    @skylight_fixture_area = 0.0625
    @measure_interface_detailed = [

        {
            "name" => "wwr",
            "type" => "StringDouble",
            "display_name" => "FDWR (fraction) or a standard value of one of #{@templates}",
            "default_value" => 0.5,
            "max_double_value" => 1.0,
            "min_double_value" => 0.0,
            "valid_strings" => @templates,
            "is_required" => false
        },
        {
            "name" => "wwr_limit_or_max",
            "type" => "Choice",
            "display_name" => "FDWR Limit or Maximize?",
            "default_value" => "Maximize",
            "choices" => @limit_or_max_values,
            "is_required" => false
        },
        {
            "name" => "sillHeight",
            "type" => "Double",
            "display_name" => "Sill height (m)",
            "default_value" => 30.0,
            "max_double_value" => 100.0,
            "min_double_value" => 0.0,
            "is_required" => true
        },
        {
            "name" => "srr",
            "type" => "StringDouble",
            "display_name" => "FDWR (fraction) or a standard value of one of #{@templates}",
            "default_value" => 0.5,
            "max_double_value" => 1.0,
            "min_double_value" => 0.0,
            "valid_strings" => @templates,
            "is_required" => false
        },
        {
            "name" => "srr_limit_or_max",
            "type" => "Choice",
            "display_name" => "SRR Limit or Maximize?",
            "default_value" => "Maximize",
            "choices" => @limit_or_max_values,
            "is_required" => false
        },
        {
            "name" => "skylight_fixture_area",
            "type" => "Double",
            "display_name" => "Area of skylight fixtures used (m2)",
            "default_value" => 0.0625,
            "max_double_value" => 5.0,
            "min_double_value" => 0.0,
            "is_required" => false
        }

    ]

    @good_input_arguments = {
        "wwr" => 0.3,
        "wwr_limit_or_max" => "Maximize",
        "sillHeight" => 30.0,
        "srr" => 0.05,
        "srr_limit_or_max" => "Maximize",
        "skylight_fixture_area" => 0.0625
    }

  end

  def create_model_by_local_osm_file(filename)
    # load the test model
    translator = OpenStudio::OSVersion::VersionTranslator.new
    path = OpenStudio::Path.new(File.dirname(__FILE__) + filename)
    model = translator.loadModel(path)
    assert(!model.empty?)
    return model.get
  end


  def create_necb_protype_model(building_type, climate_zone, epw_file, template)
    osm_directory = "#{Dir.pwd}/output/#{building_type}-#{template}-#{climate_zone}-#{epw_file}"
    FileUtils.mkdir_p (osm_directory) unless Dir.exist?(osm_directory)
    #Get Weather climate zone from lookup
    weather = BTAP::Environment::WeatherFile.new(epw_file)
    #create model
    building_name = "#{template}_#{building_type}"
    puts "Creating #{building_name}"
    prototype_creator = Standard.build(building_name)
    model = prototype_creator.model_create_prototype_model(climate_zone,
                                                           epw_file,
                                                           osm_directory,
                                                           @debug,
                                                           model)
    #set weather file to epw_file passed to model.
    weather.set_weather_file(model)
    return model
  end




  def test_SetFDWR_Maximize

    limit_or_max = 'Maximize'

    measure = BTAPEnvelopeFDWRandSRR.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    #load model
    model = create_model_by_local_osm_file('/EnvelopeAndLoadTestModel_01.osm')

    # get arguments
    arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)


    input_arguments = {
        "wwr" => 0.3,
        "wwr_limit_or_max" => "Maximize",
        "sillHeight" => 1.0,
        "srr" => 0.05,
        "srr_limit_or_max" => "Maximize",
        "skylight_fixture_area" => 0.0625
    }

    runner = run_measure(input_arguments, model)

    result = runner.result
    show_output(result)


    # save the model
    # output_file_path = OpenStudio::Path.new(File.dirname(__FILE__) + "/test.osm")
    # model.save(output_file_path,true)
  end

end
