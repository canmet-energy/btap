# *********************************************************************
# *  Copyright (c) 2008-2015, Natural Resources Canada
# *  All rights reserved.
# *
# *  This library is free software; you can redistribute it and/or
# *  modify it under the terms of the GNU Lesser General Public
# *  License as published by the Free Software Foundation; either
# *  version 2.1 of the License, or (at your option) any later version.
# *
# *  This library is distributed in the hope that it will be useful,
# *  but WITHOUT ANY WARRANTY; without even the implied warranty of
# *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# *  Lesser General Public License for more details.
# *
# *  You should have received a copy of the GNU Lesser General Public
# *  License along with this library; if not, write to the Free Software
# *  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
# **********************************************************************/

require 'openstudio'
require 'openstudio/ruleset/ShowRunnerOutput'
require_relative '../resources/BTAPMeasureHelper.rb'
require 'minitest/autorun'
require_relative '../measure.rb'
require 'fileutils' 

class BTAPUtilityTariffsModelSetup_test < Minitest::Test
  include(BTAPMeasureTestHelper)
  Building_types = [
    'FullServiceRestaurant',
    'HighriseApartment',
    'LargeHotel',
    'LargeOffice',
    'MediumOffice',
    'MidriseApartment',
    'Outpatient',
    'PrimarySchool',
    'QuickServiceRestaurant',
    'RetailStandAlone',
    'RetailStripMall',
    'SecondarySchool',
    'SmallHotel',
    'SmallOffice',
    'RetailStripmall', 
    'Warehouse'
  ]
  
  
  def set_test(building_type,epw_path)
    output_folder = "#{File.dirname(__FILE__)}/output"
    # create an instance of the measure, a runner and an empty model
    measure = BTAPUtilityTariffsModelSetup.new
    runner = OpenStudio::Ruleset::OSRunner.new
    #load osm file. 
    model = create_necb_protype_model(
              building_type,
             'NECB HDD Method',
              epw_path,
              "NECB2011"
           )
    BTAP::runner_register("INFO", "EPW file is #{epw_path}", runner)
    # Change the simulation to only run the weather file
    # and not run the sizing day simulations
    sim_control = model.getSimulationControl
    sim_control.setRunSimulationforSizingPeriods(false)
    sim_control.setRunSimulationforWeatherFileRunPeriods(true)
    #set weather file. 
    weather = BTAP::Environment::WeatherFile.new(epw_path)
    weather.set_weather_file( model )
    weather.epw_filepath
    # translate osm to idf
    ft = OpenStudio::EnergyPlus::ForwardTranslator.new
    workspace = ft.translateModel(model)
    
    # argument list
    args = OpenStudio::Ruleset::OSArgumentVector.new
    argument_map = OpenStudio::Ruleset.convertOSArgumentVectorToMap(args)

    # run the measure
    measure.run(workspace, runner, argument_map)
    show_output(runner.result)
    condition = assert_equal("Success", runner.result.value.valueName)
    #save the idf file for a run. 
    folder = "#{output_folder}/#{building_type}#{File.basename(epw_path, ".epw")}"
    idf_path = "#{folder}/in.idf"
    workspace.save(idf_path,true)
    
    #run the simulation.
    run_energy_plus(folder,weather.epw_filepath, idf_path,model )
    #return condition of measure.
    return condition
  end


  def run_energy_plus(run_dir = "#{Dir.pwd}/Run", epw_path, idf_path, model)
    # If the run directory is not specified
    # run in the current working directory

    # Make the directory if it doesn't exist
    unless Dir.exist?(run_dir)
      Dir.mkdir(run_dir)
    end

    OpenStudio.logFree(OpenStudio::Info, 'openstudio.model.Model', "Started simulation in '#{run_dir}'")



    # Rename the model to energyplus idf
    


    # If running on a regular desktop, use RunManager.
    # If running on OpenStudio Server, use WorkFlowMananger
    # to avoid slowdown from the sizing run.
    use_runmanager =false 

    begin
      require 'openstudio-workflow'
      use_runmanager = false
    rescue LoadError
      use_runmanager = false
    end

    sql_path = nil
    if use_runmanager == true
      OpenStudio.logFree(OpenStudio::Info, 'openstudio.prototype.Model', 'Running sizing run with RunManager.')

      # Find EnergyPlus
      ep_dir = OpenStudio.getEnergyPlusDirectory
      ep_path = OpenStudio.getEnergyPlusExecutable
      ep_tool = OpenStudio::Runmanager::ToolInfo.new(ep_path)
      idd_path = OpenStudio::Path.new(ep_dir.to_s + '/Energy+.idd')
      output_path = OpenStudio::Path.new("#{run_dir}/")

      # Make a run manager and queue up the run
      run_manager_db_path = OpenStudio::Path.new("#{run_dir}/run.db")
      run_manager = OpenStudio::Runmanager::RunManager.new(run_manager_db_path, true, false, false, false)
      job = OpenStudio::Runmanager::JobFactory.createEnergyPlusJob(ep_tool,
        idd_path,
        idf_path,
        epw_path,
        output_path)

      run_manager.enqueue(job, true)

      # Start the sizing run and wait for it to finish.
      while run_manager.workPending
        sleep 1
        OpenStudio::Application.instance.processEvents
      end

      sql_path = OpenStudio::Path.new("#{run_dir}/Energyplus/eplusout.sql")


    else # Use the openstudio-workflow gem
      OpenStudio.logFree(OpenStudio::Info, 'openstudio.prototype.Model', 'Running sizing run with openstudio-workflow gem.')

      # Copy the weather file to this directory
      FileUtils.copy(epw_path.to_s, run_dir)

      # Run the simulation
      sim = OpenStudio::Workflow.run_energyplus('Local', run_dir)
      final_state = sim.run

      if final_state == :finished
        OpenStudio.logFree(OpenStudio::Info, 'openstudio.prototype.Model', "Finished sizing run in #{(Time.new - start_time).round}sec.")
      end

      sql_path = OpenStudio::Path.new("#{run_dir}/run/eplusout.sql")

    end

    # Load the sql file created by the sizing run
    sql_path = OpenStudio::Path.new("#{run_dir}/Energyplus/eplusout.sql")
    if OpenStudio.exists(sql_path)
      sql = OpenStudio::SqlFile.new(sql_path)
      # Check to make sure the sql file is readable,
      # which won't be true if EnergyPlus crashed during simulation.
      unless sql.connectionOpen
        OpenStudio.logFree(OpenStudio::Error, 'openstudio.model.Model', "The run failed.  Look at the eplusout.err file in #{File.dirname(sql_path.to_s)} to see the cause.")
        return false
      end
      # Attach the sql file from the run to the sizing model
      model.setSqlFile(sql)
    else
      OpenStudio.logFree(OpenStudio::Error, 'openstudio.model.Model', "Results for the sizing run couldn't be found here: #{sql_path}.")
      return false
    end

    # Check that the run finished without severe errors
    error_query = "SELECT ErrorMessage
        FROM Errors
        WHERE ErrorType='2'"

    errs = model.sqlFile.get.execAndReturnVectorOfString(error_query)
    if errs.is_initialized
      errs = errs.get
      unless errs.empty?
        errs = errs.get
        OpenStudio.logFree(OpenStudio::Error, 'openstudio.model.Model', "The run failed with the following Fatal errors: #{errs.join('\n')}.")
        return false
      end
    end

    OpenStudio.logFree(OpenStudio::Info, 'openstudio.model.Model', "Finished simulation in '#{run_dir}'")

    return true
  end
  
  
  
  
  
  
  def test_CAN_BC_Vancouver
    set_test('FullServiceRestaurant',"CAN_BC_Vancouver.Intl.AP.718920_CWEC2016.epw")
  end
  
#  def test_SecondarySchool 
#    set_test('SecondarySchool',"CAN_AB_Calgary.718770_CWEC.epw")
#  end
  
#  def test_LargeHotel_the_pas
#    set_test('LargeHotel',"CAN_MB_The.Pas.718670_CWEC.epw")
#  end
#  
#  
#  def test_LargeHotel 
#    set_test('LargeHotel',"CAN_NB_Saint.John.716090_CWEC.epw")
#  end
  
#  def test_Outpatient 
#    set_test('Outpatient',"CAN_NB_Saint.John.716090_CWEC.epw")
#  end
#  
#  def test_RetailStandalone
#    set_test('RetailStandalone',"CAN_NB_Saint.John.716090_CWEC.epw")
#  end
  
#      
#  def test_QuickServiceRestaurant 
#    set_test('QuickServiceRestaurant',"CAN_NB_Saint.John.716090_CWEC.epw")
#  end
  
  
  
  #  def test_CAN_AB_Edmonton_711230_CWEC 
  #    set_weather("CAN_AB_Edmonton.711230_CWEC.epw")
  #  end
  #  def test_CAN_AB_Fort_McMurray_719320_CWEC 
  #    set_weather("CAN_AB_Fort.McMurray.719320_CWEC.epw")
  #  end
  #  def test_CAN_AB_Grande_Prairie_719400_CWEC 
  #    set_weather("CAN_AB_Grande.Prairie.719400_CWEC.epw")
  #  end
  #  def test_CAN_AB_Lethbridge_712430_CWEC 
  #    set_weather("CAN_AB_Lethbridge.712430_CWEC.epw")
  #  end
  #  def test_CAN_AB_Medicine_Hat_718720_CWEC 
  #    set_weather("CAN_AB_Medicine.Hat.718720_CWEC.epw")
  #  end
  #  def test_CAN_BC_Abbotsford_711080_CWEC 
  #    set_weather("CAN_BC_Abbotsford.711080_CWEC.epw")
  #  end
  #  def test_CAN_BC_Comox_718930_CWEC 
  #    set_weather("CAN_BC_Comox.718930_CWEC.epw")
  #  end
  #  def test_CAN_BC_Cranbrook_718800_CWEC 
  #    set_weather("CAN_BC_Cranbrook.718800_CWEC.epw")
  #  end
  #  def test_CAN_BC_Fort_St_John_719430_CWEC 
  #    set_weather("CAN_BC_Fort.St.John.719430_CWEC.epw")
  #  end
  #  def test_CAN_BC_Kamloops_718870_CWEC 
  #    set_weather("CAN_BC_Kamloops.718870_CWEC.epw")
  #  end
  #  def test_CAN_BC_Port_Hardy_711090_CWEC
  #    set_weather("CAN_BC_Port.Hardy.711090_CWEC.epw")
  #  end
  #  def test_CAN_BC_Prince_George_718960_CWEC 
  #    set_weather("CAN_BC_Prince.George.718960_CWEC.epw")
  #  end
  #  def test_CAN_BC_Prince_Rupert_718980_CWEC 
  #    set_weather("CAN_BC_Prince.Rupert.718980_CWEC.epw")
  #  end
  #  def test_CAN_BC_Sandspit_711010_CWEC 
  #    set_weather("CAN_BC_Sandspit.711010_CWEC.epw")
  #  end
  #  def test_CAN_BC_Smithers_719500_CWEC 
  #    set_weather("CAN_BC_Smithers.719500_CWEC.epw")
  #  end
  #  def test_CAN_BC_Summerland_717680_CWEC 
  #    set_weather("CAN_BC_Summerland.717680_CWEC.epw")
  #  end
  #  def test_CAN_BC_Vancouver_718920_CWEC 
  #    set_weather("CAN_BC_Vancouver.718920_CWEC.epw")
  #  end
  #  def test_CAN_BC_Victoria_717990_CWEC 
  #    set_weather("CAN_BC_Victoria.717990_CWEC.epw")
  #  end
  #  def test_CAN_MB_Brandon_711400_CWEC 
  #    set_weather("CAN_MB_Brandon.711400_CWEC.epw")
  #  end
  #  def test_CAN_MB_Churchill_719130_CWEC 
  #    set_weather("CAN_MB_Churchill.719130_CWEC.epw")
  #  end
  #  def test_CAN_MB_The_Pas_718670_CWEC 
  #    set_weather("CAN_MB_The.Pas.718670_CWEC.epw")
  #  end
  #  def test_CAN_MB_Winnipeg_718520_CWEC 
  #    set_weather("CAN_MB_Winnipeg.718520_CWEC.epw")
  #  end
  #  def test_CAN_NB_Fredericton_717000_CWEC 
  #    set_weather("CAN_NB_Fredericton.717000_CWEC.epw")
  #  end
  #  def test_CAN_NB_Miramichi_717440_CWEC 
  #    set_weather("CAN_NB_Miramichi.717440_CWEC.epw")
  #  end
  #  def test_CAN_NB_Saint_John_716090_CWEC 
  #    set_weather("CAN_NB_Saint.John.716090_CWEC.epw")
  #  end
  #  def test_CAN_NF_Battle_Harbour_718170_CWEC 
  #    set_weather("CAN_NF_Battle.Harbour.718170_CWEC.epw")
  #  end
  #  def test_CAN_NF_Gander_718030_CWEC 
  #    set_weather("CAN_NF_Gander.718030_CWEC.epw")
  #  end
  #  def test_CAN_NF_Goose_718160_CWEC 
  #    set_weather("CAN_NF_Goose.718160_CWEC.epw")
  #  end
  #  def test_CAN_NF_St_Johns_718010_CWEC 
  #    set_weather("CAN_NF_St.Johns.718010_CWEC.epw")
  #  end
  #  def test_CAN_NF_Stephenville_718150_CWEC 
  #    set_weather("CAN_NF_Stephenville.718150_CWEC.epw")
  #  end
  #  def test_CAN_NS_Greenwood_713970_CWEC 
  #    set_weather("CAN_NS_Greenwood.713970_CWEC.epw")
  #  end
  #  def test_CAN_NS_Sable_Island_716000_CWEC 
  #    set_weather("CAN_NS_Sable.Island.716000_CWEC.epw")
  #  end
  #  def test_CAN_NS_Shearwater_716010_CWEC 
  #    set_weather("CAN_NS_Shearwater.716010_CWEC.epw")
  #  end
  #  def test_CAN_NS_Sydney_717070_CWEC 
  #    set_weather("CAN_NS_Sydney.717070_CWEC.epw")
  #  end
  #  def test_CAN_NS_Truro_713980_CWEC 
  #    set_weather("CAN_NS_Truro.713980_CWEC.epw")
  #  end
  #  def test_CAN_NT_Inuvik_719570_CWEC 
  #    set_weather("CAN_NT_Inuvik.719570_CWEC.epw")
  #  end
  #  def test_CAN_NU_Resolute_719240_CWEC 
  #    set_weather("CAN_NU_Resolute.719240_CWEC.epw")
  #  end
  #  def test_CAN_ON_Kingston_716200_CWEC 
  #    set_weather("CAN_ON_Kingston.716200_CWEC.epw")
  #  end
  #  def test_CAN_ON_London_716230_CWEC 
  #    set_weather("CAN_ON_London.716230_CWEC.epw")
  #  end
  #  def test_CAN_ON_Mount_Forest_716310_CWEC 
  #    set_weather("CAN_ON_Mount.Forest.716310_CWEC.epw")
  #  end
  #  def test_CAN_ON_Muskoka_716300_CWEC 
  #    set_weather("CAN_ON_Muskoka.716300_CWEC.epw")
  #  end
  #  def test_CAN_ON_North_Bay_717310_CWEC 
  #    set_weather("CAN_ON_North.Bay.717310_CWEC.epw")
  #  end
  #  def test_CAN_ON_Ottawa_716280_CWEC 
  #    set_weather("CAN_ON_Ottawa.716280_CWEC.epw")
  #  end
  #  def test_CAN_ON_Sault_Ste_Marie_712600_CWEC 
  #    set_weather("CAN_ON_Sault.Ste.Marie.712600_CWEC.epw")
  #  end
  #  def test_CAN_ON_Simcoe_715270_CWEC 
  #    set_weather("CAN_ON_Simcoe.715270_CWEC.epw")
  #  end
  #  def test_CAN_ON_Thunder_Bay_717490_CWEC 
  #    set_weather("CAN_ON_Thunder.Bay.717490_CWEC.epw")
  #  end
  #  def test_CAN_ON_Timmins_717390_CWEC 
  #    set_weather("CAN_ON_Timmins.717390_CWEC.epw")
  #  end
  #  def test_CAN_ON_Toronto_716240_CWEC 
  #    set_weather("CAN_ON_Toronto.716240_CWEC.epw")
  #  end
  #  def test_CAN_ON_Trenton_716210_CWEC 
  #    set_weather("CAN_ON_Trenton.716210_CWEC.epw")
  #  end
  #  def test_CAN_ON_Windsor_715380_CWEC 
  #    set_weather("CAN_ON_Windsor.715380_CWEC.epw")
  #  end
  #  def test_CAN_PE_Charlottetown_717060_CWEC 
  #    set_weather("CAN_PE_Charlottetown.717060_CWEC.epw")
  #  end
  #  def test_CAN_PQ_Bagotville_717270_CWEC 
  #    set_weather("CAN_PQ_Bagotville.717270_CWEC.epw")
  #  end
  #  def test_CAN_PQ_Baie_Comeau_711870_CWEC 
  #    set_weather("CAN_PQ_Baie.Comeau.711870_CWEC.epw")
  #  end
  #  def test_CAN_PQ_Grindstone_Island_CWEC 
  #    set_weather("CAN_PQ_Grindstone.Island_CWEC.epw")
  #  end
  #  def test_CAN_PQ_Kuujjuarapik_719050_CWEC 
  #    set_weather("CAN_PQ_Kuujjuarapik.719050_CWEC.epw")
  #  end
  #  def test_CAN_PQ_Kuujuaq_719060_CWEC 
  #    set_weather("CAN_PQ_Kuujuaq.719060_CWEC.epw")
  #  end
  #  def test_CAN_PQ_La_Grande_Riviere_718270_CWEC 
  #    set_weather("CAN_PQ_La.Grande.Riviere.718270_CWEC.epw")
  #  end
  #  def test_CAN_PQ_Lake_Eon_714210_CWEC 
  #    set_weather("CAN_PQ_Lake.Eon.714210_CWEC.epw")
  #  end
  #  def test_CAN_PQ_Mont_Joli_717180_CWEC 
  #    set_weather("CAN_PQ_Mont.Joli.717180_CWEC.epw")
  #  end
  #  def test_CAN_PQ_Montreal_Intl_AP_716270_CWEC 
  #    set_weather("CAN_PQ_Montreal.Intl.AP.716270_CWEC.epw")
  #  end
  #  def test_CAN_PQ_Montreal_Jean_Brebeuf_716278_CWEC 
  #    set_weather("CAN_PQ_Montreal.Jean.Brebeuf.716278_CWEC.epw")
  #  end
  #  def test_CAN_PQ_Montreal_Mirabel_716278_CWEC 
  #    set_weather("CAN_PQ_Montreal.Mirabel.716278_CWEC.epw")
  #  end
  #  def test_CAN_PQ_Nitchequon_CAN270_CWEC
  #    set_weather("CAN_PQ_Nitchequon.CAN270_CWEC.epw")
  #  end
  #  def test_CAN_PQ_Quebec_717140_CWEC 
  #    set_weather("CAN_PQ_Quebec.717140_CWEC.epw")
  #  end
  #  def test_CAN_PQ_Riviere_du_Loup_717150_CWEC 
  #    set_weather("CAN_PQ_Riviere.du.Loup.717150_CWEC.epw")
  #  end
  #  def test_CAN_PQ_Roberval_717280_CWEC 
  #    set_weather("CAN_PQ_Roberval.717280_CWEC.epw")
  #  end
  #  def test_CAN_PQ_Schefferville_718280_CWEC 
  #    set_weather("CAN_PQ_Schefferville.718280_CWEC.epw")
  #  end
  #  def test_CAN_PQ_Sept_Iles_718110_CWEC 
  #    set_weather("CAN_PQ_Sept-Iles.718110_CWEC.epw")
  #  end
  #  def test_CAN_PQ_Sherbrooke_716100_CWEC 
  #    set_weather("CAN_PQ_Sherbrooke.716100_CWEC.epw")
  #  end
  #  def test_CAN_PQ_St_Hubert_713710_CWEC 
  #    set_weather("CAN_PQ_St.Hubert.713710_CWEC.epw")
  #  end
  #  def test_CAN_PQ_Ste_Agathe_des_Monts_717200_CWEC 
  #    set_weather("CAN_PQ_Ste.Agathe.des.Monts.717200_CWEC.epw")
  #  end
  #  def test_CAN_PQ_Val_d_Or_717250_CWEC 
  #    set_weather("CAN_PQ_Val.d.Or.717250_CWEC.epw")
  #  end
  #  def test_CAN_SK_Estevan_718620_CWEC 
  #    set_weather("CAN_SK_Estevan.718620_CWEC.epw")
  #  end
  #  def test_CAN_SK_North_Battleford_718760_CWEC 
  #    set_weather("CAN_SK_North.Battleford.718760_CWEC.epw")
  #  end
  #  def test_CAN_SK_Regina_718630_CWEC 
  #    set_weather("CAN_SK_Regina.718630_CWEC.epw")
  #  end
  #  def test_CAN_SK_Saskatoon_718660_CWEC 
  #    set_weather("CAN_SK_Saskatoon.718660_CWEC.epw")
  #  end
  #  def test_CAN_SK_Swift_Current_718700_CWEC 
  #    set_weather("CAN_SK_Swift.Current.718700_CWEC.epw")
  #  end
  #  def test_CAN_YT_Whitehorse_719640_CWEC 
  #    set_weather("CAN_YT_Whitehorse.719640_CWEC.epw")
  #  end
  
end
