require 'openstudio'
require 'openstudio-standards'
require 'openstudio/ruleset/ShowRunnerOutput'
require 'minitest/autorun'


require_relative '../measure.rb'

require 'fileutils'
require 'parallel'


class BTAPModifyConductancesByPercentage_Test < Minitest::Test
  @@building_types = [
    "FullServiceRestaurant",
    #    "LargeHotel",
    #    "LargeOffice",
    #    "MediumOffice",
    #    "MidriseApartment",
    #    "Outpatient",
    #    "PrimarySchool",
    #    "QuickServiceRestaurant",
    #    "RetailStandalone",
    #    "RetailStripmall",
    #    "SmallHotel",
    #    "SmallOffice",
    #    "Warehouse"
  ]

  templates =  'NECB 2011'
  climate_zones = 'NECB HDD Method'

  @@epw_files = #['CAN_AB_Calgary.718770_CWEC.epw','CAN_AB_Edmonton.711230_CWEC.epw','CAN_AB_Fort.McMurray.719320_CWEC.epw','CAN_AB_Grande.Prairie.719400_CWEC.epw','CAN_AB_Lethbridge.712430_CWEC.epw','CAN_AB_Medicine.Hat.718720_CWEC.epw','CAN_BC_Abbotsford.711080_CWEC.epw','CAN_BC_Comox.718930_CWEC.epw','CAN_BC_Cranbrook.718800_CWEC.epw','CAN_BC_Fort.St.John.719430_CWEC.epw','CAN_BC_Kamloops.718870_CWEC.epw','CAN_BC_Port.Hardy.711090_CWEC.epw','CAN_BC_Prince.George.718960_CWEC.epw','CAN_BC_Prince.Rupert.718980_CWEC.epw','CAN_BC_Sandspit.711010_CWEC.epw','CAN_BC_Smithers.719500_CWEC.epw','CAN_BC_Summerland.717680_CWEC.epw','CAN_BC_Vancouver.718920_CWEC.epw','CAN_BC_Victoria.717990_CWEC.epw','CAN_MB_Brandon.711400_CWEC.epw','CAN_MB_Churchill.719130_CWEC.epw','CAN_MB_The.Pas.718670_CWEC.epw','CAN_MB_Winnipeg.718520_CWEC.epw','CAN_NB_Fredericton.717000_CWEC.epw','CAN_NB_Miramichi.717440_CWEC.epw','CAN_NB_Saint.John.716090_CWEC.epw','CAN_NF_Gander.718030_CWEC.epw','CAN_NF_Goose.718160_CWEC.epw','CAN_NF_St.Johns.718010_CWEC.epw','CAN_NF_Stephenville.718150_CWEC.epw','CAN_NS_Greenwood.713970_CWEC.epw','CAN_NS_Sable.Island.716000_CWEC.epw','CAN_NS_Shearwater.716010_CWEC.epw','CAN_NS_Sydney.717070_CWEC.epw','CAN_NT_Inuvik.719570_CWEC.epw','CAN_NU_Resolute.719240_CWEC.epw','CAN_ON_London.716230_CWEC.epw','CAN_ON_Mount.Forest.716310_CWEC.epw','CAN_ON_North.Bay.717310_CWEC.epw','CAN_ON_Ottawa.716280_CWEC.epw','CAN_ON_Sault.Ste.Marie.712600_CWEC.epw','CAN_ON_Thunder.Bay.717490_CWEC.epw','CAN_ON_Timmins.717390_CWEC.epw','CAN_ON_Toronto.716240_CWEC.epw','CAN_ON_Trenton.716210_CWEC.epw','CAN_ON_Windsor.715380_CWEC.epw','CAN_PE_Charlottetown.717060_CWEC.epw','CAN_PQ_Bagotville.717270_CWEC.epw','CAN_PQ_Baie.Comeau.711870_CWEC.epw','CAN_PQ_Kuujjuarapik.719050_CWEC.epw','CAN_PQ_Kuujuaq.719060_CWEC.epw','CAN_PQ_La.Grande.Riviere.718270_CWEC.epw','CAN_PQ_Lake.Eon.714210_CWEC.epw','CAN_PQ_Mont.Joli.717180_CWEC.epw','CAN_PQ_Montreal.Intl.AP.716270_CWEC.epw','CAN_PQ_Quebec.717140_CWEC.epw','CAN_PQ_Riviere.du.Loup.717150_CWEC.epw','CAN_PQ_Roberval.717280_CWEC.epw','CAN_PQ_Schefferville.718280_CWEC.epw','CAN_PQ_Sept-Iles.718110_CWEC.epw','CAN_PQ_Sherbrooke.716100_CWEC.epw','CAN_PQ_St.Hubert.713710_CWEC.epw','CAN_PQ_Ste.Agathe.des.Monts.717200_CWEC.epw','CAN_PQ_Val.d.Or.717250_CWEC.epw','CAN_SK_Estevan.718620_CWEC.epw','CAN_SK_North.Battleford.718760_CWEC.epw','CAN_SK_Regina.718630_CWEC.epw','CAN_SK_Saskatoon.718660_CWEC.epw','CAN_SK_Swift.Current.718700_CWEC.epw','CAN_YT_Whitehorse.719640_CWEC.epw']





  #=begin 
  [
    'CAN_BC_Vancouver.718920_CWEC.epw',#  CZ 5 - Gas HDD = 3019 
    #    'CAN_ON_Toronto.716240_CWEC.epw', #CZ 6 - Gas HDD = 4088
    #    'CAN_PQ_Sherbrooke.716100_CWEC.epw', #CZ 7a - Electric HDD = 5068
    #    'CAN_YT_Whitehorse.719640_CWEC.epw', #CZ 7b - FuelOil1 HDD = 6946
    #    'CAN_NU_Resolute.719240_CWEC.epw', # CZ 8  -FuelOil2 HDD = 12570
  ]
  #=end
  
  def run_dir(test_name)
    # always generate test output in specially named 'output' directory so result files are not made part of the measure
    "#{File.dirname(__FILE__)}/output#{Time.now.strftime("%m-%d")}/#{test_name}"
  end

  def model_out_path(test_name)
    "#{run_dir(test_name)}/final.osm"
  end

  def workspace_path(test_name)
    "#{run_dir(test_name)}/in.idf"
  end

  def sql_path(test_name)
    "#{run_dir(test_name)}/run/eplusout.sql"
  end

  def setup_test(test_name,building,epw_filename)
    output_folder = run_dir(test_name)

    unless File.exist?(run_dir(test_name))
      FileUtils.mkdir_p(run_dir(test_name))
    end
    assert(File.exist?(run_dir(test_name)))


    #assert(File.exist?(model_in_path))

    if File.exist?(model_out_path(test_name))
      FileUtils.rm(model_out_path(test_name))
    end

    model = OpenStudio::Model::Model.new
    model.create_prototype_building(building,'NECB 2011','NECB HDD Method',epw_filename,output_folder)
    puts epw_filename
    BTAP::Environment::WeatherFile.new(epw_filename).set_weather_file(model)


    #model.save(model_out_path(test_name), true)
    model.run_simulation_and_log_errors(run_dir(test_name))
  end
  
  def test_model ()
    #    percentages = [-20,-10,0,10,20]
    percentages = [0,5]
    start = Time.now
    run_argument_array = []
    @@building_types.each do |building|
      @@epw_files.each do |epw|
        percentages.each do |wall|
          percentages.each do |roof|
            percentages.each do |floor|
              run_argument_array << { 'building'=> building, 'epw'=>epw, 'wall'=>wall, 'roof'=>roof, 'floor'=>floor }
            end
          end
        end
      end
    end
  
    # create an instance of the measure
    
  
    processess =  (Parallel::processor_count - 1)
    puts "processess #{processess}"
    Parallel.map(run_argument_array, in_processes: processess) { |info| 
      measure = BTAPModifyConductancesByPercentage.new
      puts measure

      # create an instance of a runner
      runner = OpenStudio::Ruleset::OSRunner.new
      
      #    run_argument_array.each { |info|
      puts info
      building = info['building']
      weather = info['epw']
      wall_cond_percentage = info['wall']
      floor_cond_percentage = info['floor']
      roof_cond_percentage = info['floor']
    
      test_name = "#{building}_#{weather}_w#{wall_cond_percentage}_f#{floor_cond_percentage}_r#{roof_cond_percentage}"
      puts "========#{building}     #{weather}========\n"
      puts "========#{test_name}========\n"
    
      # get arguments
      arguments = measure.arguments()
      puts "arguments: #{arguments}"
      argument_map = OpenStudio::Ruleset::OSArgumentMap.new
    
      wall = arguments[0].clone
      wall.setValue(wall_cond_percentage)
      argument_map['wall_cond_percentage'] = wall
    
      floor = arguments[1].clone
      floor.setValue(floor_cond_percentage)
      argument_map['floor_cond_percentage'] = floor
    
      roof = arguments[2].clone
      roof.setValue(roof_cond_percentage)
      argument_map['roof_cond_percentage'] = roof
    
    
    
    
    

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
    
    }
    BTAP::FileIO.compile_qaqc_results("#{File.dirname(__FILE__)}/output#{Time.now.strftime("%m-%d")}")
    puts "completed in #{Time.now - start} secs"
  end 
end
