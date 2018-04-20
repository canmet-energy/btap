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
require_relative '../measure.rb'
require 'minitest/autorun'

class BTAPEnvelopeFDWRandSRR_Test < Minitest::Test
  def setup

        '{
            "wwr" => "0.04",
            "wwr_limit_or_max" => "Maximize",
            "srr" => "0.05",
            "srr_limit_or_max" => "Maximize",
            "sillHeight" => 0.75
        }'
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


  def test_arguments

    measure = BTAPEnvelopeFDWRandSRR.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    #load model
    model = create_model_by_local_osm_file('/EnvelopeAndLoadTestModel_01.osm')

    # get arguments
    arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)

    # Test arguments and defaults
    arguments = measure.arguments(model)
    #check number of arguments.
    assert_equal(5, arguments.size)

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

    # Test arguments and defaults
    arguments = measure.arguments(model)


    wwr = arguments[0].clone
    assert(wwr.setValue(limit_or_max))
    argument_map['wwr'] = wwr

    wwr_limit_or_max = arguments[1].clone
    assert(wwr_limit_or_max.setValue(limit_or_max))
    argument_map['wwr_limit_or_max'] = wwr_limit_or_max

    srr = arguments[2].clone
    assert(srr.setValue('0.05'))
    argument_map['srr'] = srr

    srr_limit_or_max = arguments[3].clone
    assert(srr_limit_or_max.setValue(limit_or_max))
    argument_map['srr_limit_or_max'] = srr_limit_or_max

    sillHeight = arguments[4].clone
    assert(sillHeight.setValue(0.75))
    argument_map['sillHeight'] = sillHeight

    measure.run(model, runner, argument_map)
    result = runner.result
    show_output(result)


    # save the model
    # output_file_path = OpenStudio::Path.new(File.dirname(__FILE__) + "/test.osm")
    # model.save(output_file_path,true)
  end


  def test_SetFDWR_Limit

    limit_or_max = 'Limit'
    measure = BTAPEnvelopeFDWRandSRR.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    #load model
    model = create_model_by_local_osm_file('/EnvelopeAndLoadTestModel_01.osm')

    # get arguments
    arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)

    # Test arguments and defaults
    arguments = measure.arguments(model)


    wwr = arguments[0].clone
    assert(wwr.setValue('0.04'))
    argument_map['wwr'] = wwr

    wwr_limit_or_max = arguments[1].clone
    assert(wwr_limit_or_max.setValue(limit_or_max))
    argument_map['wwr_limit_or_max'] = wwr_limit_or_max

    srr = arguments[2].clone
    assert(srr.setValue('0.05'))
    argument_map['srr'] = srr

    srr_limit_or_max = arguments[3].clone
    assert(srr_limit_or_max.setValue(limit_or_max))
    argument_map['srr_limit_or_max'] = srr_limit_or_max

    sillHeight = arguments[4].clone
    assert(sillHeight.setValue(0.75))
    argument_map['sillHeight'] = sillHeight

    measure.run(model, runner, argument_map)
    result = runner.result
    show_output(result)


    # save the model
    # output_file_path = OpenStudio::Path.new(File.dirname(__FILE__) + "/test.osm")
    # model.save(output_file_path,true)
  end


  def run_ratio_measure(model, inp_srr, inp_srr_limit_or_max, inp_wwr, inp_wwr_limit_or_max, inp_sill_height)
    measure = BTAPEnvelopeFDWRandSRR.new
    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    # get arguments
    arguments = measure.arguments(model)

    # set argument values to good values and run the measure on model with spaces
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)

    # Test arguments and defaults
    arguments = measure.arguments(model)


    wwr = arguments[0].clone
    assert(wwr.setValue(inp_wwr))
    argument_map['wwr'] = wwr

    wwr_limit_or_max = arguments[1].clone
    assert(wwr_limit_or_max.setValue('Maximum'))
    argument_map['wwr_limit_or_max'] = wwr_limit_or_max

    srr = arguments[2].clone
    assert(srr.setValue(inp_srr))
    argument_map['srr'] = srr

    srr_limit_or_max = arguments[3].clone
    assert(srr_limit_or_max.setValue(inp_srr_limit_or_max))
    argument_map['srr_limit_or_max'] = srr_limit_or_max

    sill_height = arguments[4].clone
    assert(sill_height.setValue(inp_sill_height))
    argument_map['sill_height'] = sill_height
    return argument_map, measure, runner
  end


end
