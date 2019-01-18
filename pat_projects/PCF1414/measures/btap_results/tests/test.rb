require 'openstudio'
require 'openstudio-standards'
require 'openstudio/ruleset/ShowRunnerOutput'
require 'minitest/autorun'

begin
  require 'openstudio_measure_tester/test_helper'
rescue LoadError
  puts 'OpenStudio Measure Tester Gem not installed -- will not be able to aggregate and dashboard the results of tests'
end

require_relative '../measure.rb'

require 'fileutils'

class BTAPResults_Test < MiniTest::Unit::TestCase
  # class level variable

  @@Building_types = [
  'FullServiceRestaurant',
  #'HighriseApartment',
  #'LargeHotel',
  #'LargeOffice',
  #'MediumOffice',
  #'MidriseApartment',
  #'Outpatient',
  #'PrimarySchool',
  #'QuickServiceRestaurant',
  #'RetailStandAlone',
  #'RetailStripMall',
  #'SeconcdarySchool',
  #'SmallHotel',
  #'SmallOffice',
  #'RetailStripmall',
  #'Warehouse'
  ]

  @@epw_files = [
      "CAN_AB_Banff.CS.711220_CWEC2016.epw"
  ]

  # NECB2015 will work after openstudio-standards/tree/nrcan_48
  # has been pulled into nrcan
  @@templates=[
      "NECB2011",
      "NECB2015",
      "NECB2017"
  ]

  # Added the template into the path name of the run dir so
  # both NECB2011 and NECB2015 can be tested
  def run_dir(test_name, template)
    # always generate test output in specially named 'output' directory so result files are not made part of the measure
    "#{File.dirname(__FILE__)}/output/#{template}/#{test_name}"
  end

  def model_out_path(test_name, template)
    "#{run_dir(test_name, template)}/final.osm"
  end

  def workspace_path(test_name, template)
    "#{run_dir(test_name, template)}/run/in.idf"
  end

  def sql_path(test_name, template)
    "#{run_dir(test_name, template)}/run/eplusout.sql"
  end


  def check_boolean_value (value, varname)
    return true if value =~ (/^(true|t|yes|y|1)$/i)
    return false if value.empty? || value =~ (/^(false|f|no|n|0)$/i)

    raise ArgumentError.new "invalid value for #{varname}: #{value}"
  end


  # create test files if they do not exist when the test first runs
  def setup_test(test_name, building, epw_filename, template)
    output_folder = "#{File.dirname(__FILE__)}/output/#{test_name}"

    unless File.exist?(run_dir(test_name, template))
      FileUtils.mkdir_p(run_dir(test_name, template))
    end
    assert(File.exist?(run_dir(test_name, template)))


    #assert(File.exist?(model_in_path))

    if File.exist?(model_out_path(test_name, template))
      FileUtils.rm(model_out_path(test_name, template))
    end


    prototype_creator = Standard.build(template)
    model = prototype_creator.model_create_prototype_model(
        template: template,
        epw_file: epw_filename,
        sizing_run_dir: output_folder,
        debug: @debug,
        building_type: building)

    BTAP::Environment::WeatherFile.new(epw_filename).set_weather_file(model)


    model.save(model_out_path(test_name, template), true)
    prototype_creator.model_run_simulation_and_log_errors(model, run_dir(test_name, template))

  end

  def dont_test_example_model_with_hourly_data
    setup_example_model("true")
  end

  def test_example_model_without_hourly_data
    setup_example_model("false")
  end

  def setup_example_model(h_data)

    # create an instance of the measure
    measure = BTAPResults.new

    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)
    @@Building_types.each do |building|
      @@epw_files.each do |weather|
        @@templates.each do |template|
          puts "========#{building}     #{weather}========\n"
          test_name = "#{building}_#{weather}"
          hourly_data_generate = check_boolean_value(h_data, "h_data")
          if hourly_data_generate
            test_name = "hourly_data/#{building}_#{weather}"
          end

          # get arguments
          arguments = measure.arguments()
          puts arguments
          argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)

          #check number of arguments.
          assert_equal(2, arguments.size)

          hourly_data = arguments[0].clone
          assert(hourly_data.setValue(h_data))
          argument_map['generate_hourly_report'] = hourly_data

          output_diet = arguments[1].clone
          assert(output_diet.setValue(false))
          argument_map['output_diet'] = output_diet


          # mimic the process of running this measure in OS App or PAT
          setup_test(test_name, building, weather, template)

          assert(File.exist?(model_out_path(test_name, template)), "Could not find osm at this path:#{model_out_path(test_name, template)}")
          assert(File.exist?(sql_path(test_name, template)), "Could not find sql at this path:#{sql_path(test_name, template)}")
          #assert(File.exist?(epw_path))

          # set up runner, this will happen automatically when measure is run in PAT or OpenStudio
          runner.setLastOpenStudioModelPath(OpenStudio::Path.new(model_out_path(test_name, template)))
          runner.setLastEnergyPlusWorkspacePath(OpenStudio::Path.new(workspace_path(test_name, template)))
          #runner.setLastEpwFilePath(epw_path)
          runner.setLastEnergyPlusSqlFilePath(OpenStudio::Path.new(sql_path(test_name, template)))


          # temporarily change directory to the run directory and run the measure
          start_dir = Dir.pwd
          begin
            Dir.chdir(run_dir(test_name, template))

            # run the measure
            measure.run(runner, argument_map)
            result = runner.result
            #show_output(result)
            assert_equal('Success', result.value.valueName)
          ensure
            Dir.chdir(start_dir)
          end
        end
      end
    end
  end
end
