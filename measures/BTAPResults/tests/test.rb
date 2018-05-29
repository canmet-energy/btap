require 'openstudio'
require 'openstudio-standards'
require 'openstudio/ruleset/ShowRunnerOutput'
require 'minitest/autorun'


require_relative '../measure.rb'

require 'fileutils'

class BTAPResults_Test < MiniTest::Unit::TestCase
  # class level variable

  @@Building_types = [
    'FullServiceRestaurant'
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
  

  def run_dir(test_name)
    # always generate test output in specially named 'output' directory so result files are not made part of the measure
    "#{File.dirname(__FILE__)}/output/#{test_name}"
  end

  def model_out_path(test_name)
    "#{run_dir(test_name)}/final.osm"
  end

  def workspace_path(test_name)
    "#{run_dir(test_name)}/run/in.idf"
  end

  def sql_path(test_name)
    "#{run_dir(test_name)}/run/eplusout.sql"
  end

  
  def check_boolean_value (value,varname)
    return true if value =~ (/^(true|t|yes|y|1)$/i)
    return false if value.empty? || value =~ (/^(false|f|no|n|0)$/i)

    raise ArgumentError.new "invalid value for #{varname}: #{value}"
  end
  
  
  # create test files if they do not exist when the test first runs
  def setup_test(test_name,building,epw_filename)
    output_folder = "#{File.dirname(__FILE__)}/output/#{test_name}"

    unless File.exist?(run_dir(test_name))
      FileUtils.mkdir_p(run_dir(test_name))
    end
    assert(File.exist?(run_dir(test_name)))


    #assert(File.exist?(model_in_path))

    if File.exist?(model_out_path(test_name))
      FileUtils.rm(model_out_path(test_name))
    end


    prototype_creator = Standard.build("#{'NECB2011'}_#{building}")
    model = prototype_creator.model_create_prototype_model('NECB HDD Method', epw_filename, output_folder)
    BTAP::Environment::WeatherFile.new(epw_filename).set_weather_file(model)


    model.save(model_out_path(test_name), true)
    prototype_creator.model_run_simulation_and_log_errors(model, run_dir(test_name))

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
    runner = OpenStudio::Ruleset::OSRunner.new
    @@Building_types.each do |building|
      @@epw_files.each do |weather|
        puts "========#{building}     #{weather}========\n"
        test_name = "#{building}_#{weather}"
        hourly_data_generate = check_boolean_value(h_data,"h_data")
        if hourly_data_generate
          test_name = "hourly_data/#{building}_#{weather}"
        end

        # get arguments
        arguments = measure.arguments()
        argument_map = OpenStudio::Ruleset::OSArgumentMap.new
        hourly_data = arguments[0].clone
        assert(hourly_data.setValue(h_data))
        argument_map['generate_hourly_report'] = hourly_data


        # mimic the process of running this measure in OS App or PAT
        setup_test(test_name,building,weather)

        assert(File.exist?(model_out_path(test_name)),"Could not find osm at this path:#{model_out_path(test_name)}")
        assert(File.exist?(sql_path(test_name)),"Could not find sql at this path:#{sql_path(test_name)}")
        #assert(File.exist?(epw_path))

        # set up runner, this will happen automatically when measure is run in PAT or OpenStudio
        runner.setLastOpenStudioModelPath(OpenStudio::Path.new(model_out_path(test_name)))
        runner.setLastEnergyPlusWorkspacePath(OpenStudio::Path.new(workspace_path(test_name)))
        #runner.setLastEpwFilePath(epw_path)
        runner.setLastEnergyPlusSqlFilePath(OpenStudio::Path.new(sql_path(test_name)))


        # temporarily change directory to the run directory and run the measure
        start_dir = Dir.pwd
        begin
          Dir.chdir(run_dir(test_name))

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
