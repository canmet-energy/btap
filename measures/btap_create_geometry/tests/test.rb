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


class BTAPCreateGeometry_Test < Minitest::Test
  # Brings in helper methods to simplify argument testing of json and standard argument methods.
  include(BTAPMeasureTestHelper)
  def setup()

    @use_json_package = false
    @use_string_double = true
    @measure_interface_detailed =
        [
            {
                "name" => "building_name",
                "type" => "String",
                "display_name" => "Building name",
                "default_value" => "building",
                "is_required" => true

            },

            {
                "name" => "building_shape",
                "type" => "Choice",
                "display_name" => "Building shape",
                "default_value" => "Rectangular",
                "choices" => ["Courtyard", "H shape", "L shape", "Rectangular", "T shape", "U shape"],
                "is_required" => true
            },
            {
                "name" => "template",
                "type" => "Choice",
                "display_name" => "template",
                "default_value" => "NECB2011",
                "choices" => ["NECB2011", "NECB2015","NECB2017"],
                "is_required" => true
            },

            {
                "name" => "building_type",
                "type" => "Choice",
                "display_name" => "Building Type ",
                "default_value" => "PrimarySchool",
                "choices" => ["SecondarySchool","PrimarySchool","SmallOffice","MediumOffice","LargeOffice","SmallHotel","LargeHotel","Warehouse","RetailStandalone","RetailStripmall","QuickServiceRestaurant","FullServiceRestaurant","MidriseApartment","HighriseApartment""MidriseApartment","Hospital","Outpatient",],
                "is_required" => true
            },
            {
                "name" => "epw_file",
                "type" => "Choice",
                "display_name" => "Weather file",
                "default_value" => 'CAN_ON_Ottawa-Macdonald-Cartier.Intl.AP.716280_CWEC2016.epw',
                "choices" => ['CAN_AB_Banff.CS.711220_CWEC2016.epw','CAN_AB_Calgary.Intl.AP.718770_CWEC2016.epw','CAN_AB_Edmonton.Intl.AP.711230_CWEC2016.epw','CAN_AB_Edmonton.Stony.Plain.AP.711270_CWEC2016.epw','CAN_AB_Fort.McMurray.AP.716890_CWEC2016.epw','CAN_AB_Grande.Prairie.AP.719400_CWEC2016.epw','CAN_AB_Lethbridge.AP.712430_CWEC2016.epw','CAN_AB_Medicine.Hat.AP.710260_CWEC2016.epw','CAN_BC_Abbotsford.Intl.AP.711080_CWEC2016.epw','CAN_BC_Comox.Valley.AP.718930_CWEC2016.epw','CAN_BC_Crankbrook-Canadian.Rockies.Intl.AP.718800_CWEC2016.epw','CAN_BC_Fort.St.John-North.Peace.Rgnl.AP.719430_CWEC2016.epw','CAN_BC_Hope.Rgnl.Airpark.711870_CWEC2016.epw','CAN_BC_Kamloops.AP.718870_CWEC2016.epw','CAN_BC_Port.Hardy.AP.711090_CWEC2016.epw','CAN_BC_Prince.George.Intl.AP.718960_CWEC2016.epw','CAN_BC_Smithers.Rgnl.AP.719500_CWEC2016.epw','CAN_BC_Summerland.717680_CWEC2016.epw','CAN_BC_Vancouver.Intl.AP.718920_CWEC2016.epw','CAN_BC_Victoria.Intl.AP.717990_CWEC2016.epw','CAN_MB_Brandon.Muni.AP.711400_CWEC2016.epw','CAN_MB_The.Pas.AP.718670_CWEC2016.epw','CAN_MB_Winnipeg-Richardson.Intl.AP.718520_CWEC2016.epw','CAN_NB_Fredericton.Intl.AP.717000_CWEC2016.epw','CAN_NB_Miramichi.AP.717440_CWEC2016.epw','CAN_NB_Saint.John.AP.716090_CWEC2016.epw','CAN_NL_Gander.Intl.AP-CFB.Gander.718030_CWEC2016.epw','CAN_NL_Goose.Bay.AP-CFB.Goose.Bay.718160_CWEC2016.epw','CAN_NL_St.Johns.Intl.AP.718010_CWEC2016.epw','CAN_NL_Stephenville.Intl.AP.718150_CWEC2016.epw','CAN_NS_CFB.Greenwood.713970_CWEC2016.epw','CAN_NS_CFB.Shearwater.716010_CWEC2016.epw','CAN_NS_Sable.Island.Natl.Park.716000_CWEC2016.epw','CAN_NT_Inuvik-Zubko.AP.719570_CWEC2016.epw','CAN_NT_Yellowknife.AP.719360_CWEC2016.epw','CAN_ON_Armstrong.AP.718410_CWEC2016.epw','CAN_ON_CFB.Trenton.716210_CWEC2016.epw','CAN_ON_Dryden.Rgnl.AP.715270_CWEC2016.epw','CAN_ON_London.Intl.AP.716230_CWEC2016.epw','CAN_ON_Moosonee.AP.713980_CWEC2016.epw','CAN_ON_Mount.Forest.716310_CWEC2016.epw','CAN_ON_North.Bay-Garland.AP.717310_CWEC2016.epw','CAN_ON_Ottawa-Macdonald-Cartier.Intl.AP.716280_CWEC2016.epw','CAN_ON_Sault.Ste.Marie.AP.712600_CWEC2016.epw','CAN_ON_Timmins.Power.AP.717390_CWEC2016.epw','CAN_ON_Toronto.Pearson.Intl.AP.716240_CWEC2016.epw','CAN_ON_Windsor.Intl.AP.715380_CWEC2016.epw','CAN_PE_Charlottetown.AP.717060_CWEC2016.epw','CAN_QC_Kuujjuaq.AP.719060_CWEC2016.epw','CAN_QC_Kuujuarapik.AP.719050_CWEC2016.epw','CAN_QC_Lac.Eon.AP.714210_CWEC2016.epw','CAN_QC_Mont-Joli.AP.717180_CWEC2016.epw','CAN_QC_Montreal-Mirabel.Intl.AP.719050_CWEC2016.epw','CAN_QC_Montreal-St-Hubert.Longueuil.AP.713710_CWEC2016.epw','CAN_QC_Montreal-Trudeau.Intl.AP.716270_CWEC2016.epw','CAN_QC_Quebec-Lesage.Intl.AP.717140_CWEC2016.epw','CAN_QC_Riviere-du-Loup.717150_CWEC2016.epw','CAN_QC_Roberval.AP.717280_CWEC2016.epw','CAN_QC_Saguenay-Bagotville.AP-CFB.Bagotville.717270_CWEC2016.epw','CAN_QC_Schefferville.AP.718280_CWEC2016.epw','CAN_QC_Sept-Iles.AP.718110_CWEC2016.epw','CAN_QC_Val-d-Or.Rgnl.AP.717250_CWEC2016.epw','CAN_SK_Estevan.Rgnl.AP.718620_CWEC2016.epw','CAN_SK_North.Battleford.AP.718760_CWEC2016.epw','CAN_SK_Saskatoon.Intl.AP.718660_CWEC2016.epw','CAN_YT_Whitehorse.Intl.AP.719640_CWEC2016.epw'],
                "is_required" => true
            },

          {
            "name" => "total_floor_area",
            "type" => "Double",
            "display_name" => "Total building area (m2)",
            "default_value" => 50000.0,
            "max_double_value" => 10000000.0,
            "min_double_value" => 10.0,
            "is_required" => true
        },

            {
                "name" => "aspect_ratio",
                "type" => "Double",
                "display_name" => "Aspect ratio (width/length; width faces south before rotation)",
                "default_value" => 1.0,
                "max_double_value" => 10.0,
                "min_double_value" => 0.1,
                "is_required" => true
            },

            {
                "name" => "rotation",
                "type" => "Double",
                "display_name" => "Rotation (degrees clockwise)",
                "default_value" => 0.0,
                "max_double_value" => 360.0,
                "min_double_value" => 0.0,
                "is_required" => true
            },

            {
                "name" => "above_grade_floors",
                "type" => "Integer",
                "display_name" => "Number of above grade floors",
                "default_value" => 3,
                "max_integer_value" => 200,
                "min_integer_value" => 1,
                "is_required" => true
            },

            {
                "name" => "floor_to_floor_height",
                "type" => "Double",
                "display_name" => "Floor to floor height (m)",
                "default_value" => 3.8,
                "max_double_value" => 10.0,
                "min_double_value" => 2.0,
                "is_required" => false
            },

            {
                "name" => "plenum_height",
                "type" => "Double",
                "display_name" => "Plenum height (m)",
                "default_value" => 1.0,
                "max_double_value" => 2.0,
                "min_double_value" => 0.1,
                "is_required" => false
            }
        ]
    @good_input_arguments = {
       "building_name" => "rectangular",
        "building_shape" => "Rectangular",
        "template" =>  "NECB2011",
        "building_type" => "PrimarySchool",
        "epw_file" => "CAN_ON_Ottawa-Macdonald-Cartier.Intl.AP.716280_CWEC2016.epw",
        "total_floor_area" => 50000.0,
        "aspect_ratio" => 0.5,
        "rotation" => 0.0,
        "above_grade_floors" => 2,
        "floor_to_floor_height" => 3.2,
        "plenum_height" => 1.0
    }


  end

  def test_sample()
     ####### Test Model Creation ######
	# Create an empty model. This measure will overwrite whatever is supplied here.
    model = OpenStudio::Model::Model.new

    # Create an instance of the measure with good values
    runner = run_measure(@good_input_arguments, model)
    BTAP::FileIO::save_osm(model, File.join(File.dirname(__FILE__), "outputRectangle", "test_rectangle.osm"))
    assert(runner.result.value.valueName == 'Success')


    # While debugging and testing, it is sometimes nice to make a copy of the model as it was.
    before_measure_model = copy_model(model)
    model = OpenStudio::Model::Model.new

   # Set up your argument list to test.
      input_arguments = {
        "building_name" => "courtyard",
        "building_shape" => "Courtyard",
        "template" =>  "NECB2011",
        "building_type" => "SmallOffice",
        "epw_file" => "CAN_ON_Ottawa-Macdonald-Cartier.Intl.AP.716280_CWEC2016.epw",
        "total_floor_area" => 50000.0,
        "aspect_ratio" => 0.5,
        "rotation" => 0.0,
        "above_grade_floors" => 2,
        "floor_to_floor_height" => 3.2,
        "plenum_height" => 1.0

      }


    # Create an instance of the measure
    runner = run_measure(input_arguments, model)
    #BTAP::FileIO::save_osm(model, File.join(File.dirname(__FILE__), "output", "courtyard.osm"))
    assert(runner.result.value.valueName == 'Success')
    puts ">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>"
    ########################################################################################################################


    model = OpenStudio::Model::Model.new

    input_arguments = {
        "building_name" => "rectangular",
        "building_shape" => "Rectangular",
        "template" =>  "NECB2011",
        "building_type" => "SmallOffice",
        "epw_file" => "CAN_ON_Ottawa-Macdonald-Cartier.Intl.AP.716280_CWEC2016.epw",
        "total_floor_area" => 50000,
        "aspect_ratio" => 0.5,
        "rotation" => 0.0,
        "above_grade_floors" => 3,
        "floor_to_floor_height" => 3.2,
        "plenum_height" => 1.0
    }


    # Create an instance of the measure
    runner = run_measure(input_arguments, model)
    #BTAP::FileIO::save_osm(model, File.join(File.dirname(__FILE__), "output", "rectangular.osm"))
    assert(runner.result.value.valueName == 'Success')
    runner.registerInfo(" \e[32m Rectangular shape is created. \e[0m .")

    puts ">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>"

##################################################################################################################################

    model = OpenStudio::Model::Model.new

    input_arguments = {
        "building_name" => "L shape",
        "building_shape" => "L shape",
        "template" =>  "NECB2011",
        "building_type" => "SmallOffice",
        "epw_file" => "CAN_ON_Ottawa-Macdonald-Cartier.Intl.AP.716280_CWEC2016.epw",
        "total_floor_area" => 50000,
        "aspect_ratio" => 0.5,
        "rotation" => 0.0,
        "above_grade_floors" => 3,
        "floor_to_floor_height" => 3.2,
        "plenum_height" => 1.0
    }
    #end

    # Create an instance of the measure
    runner = run_measure(input_arguments, model)
    #BTAP::FileIO::save_osm(model, File.join(File.dirname(__FILE__), "output", "L_Shape.osm"))
    assert(runner.result.value.valueName == 'Success')
    runner.registerInfo(" \e[32m Rectangular shape is craeted. \e[0m .")

    
###################################################################################################################################

    model = OpenStudio::Model::Model.new

    input_arguments = {
        "building_name" => "H shape",
        "building_shape" => "H shape",
         "template" =>  "NECB2011",
        "building_type" => "SmallOffice",
        "epw_file" => "CAN_ON_Ottawa-Macdonald-Cartier.Intl.AP.716280_CWEC2016.epw",
        "total_floor_area" => 50000,
        "aspect_ratio" => 0.5,
        "rotation" => 0.0,
        "above_grade_floors" => 3,
        "floor_to_floor_height" => 3.2,
        "plenum_height" => 1.0
    }
    #end

    # Create an instance of the measure
    runner = run_measure(input_arguments, model)
    #BTAP::FileIO::save_osm(model, File.join(File.dirname(__FILE__), "output", "H_Shape.osm"))
    assert(runner.result.value.valueName == 'Success')
    ############################################################################################################################################

    model = OpenStudio::Model::Model.new

    input_arguments = {
        "building_name" => "U shape",
        "building_shape" => "U shape",
        "template" =>  "NECB2011",
        "building_type" => "SmallOffice",
        "epw_file" => "CAN_ON_Ottawa-Macdonald-Cartier.Intl.AP.716280_CWEC2016.epw",
        "total_floor_area" => 500000,
        "aspect_ratio" => 0.5,
        "rotation" => 0.0,
        "above_grade_floors" => 3,
        "floor_to_floor_height" => 3.2,
        "plenum_height" => 1.0
    }
    #end

    # Create an instance of the measure
    runner = run_measure(input_arguments, model)
    #BTAP::FileIO::save_osm(model, File.join(File.dirname(__FILE__), "output", "U_Shape.osm"))
    assert(runner.result.value.valueName == 'Success')

    #############################################################################################################################################

    model = OpenStudio::Model::Model.new

    input_arguments = {
        "building_name" => "T shape",
        "building_shape" => "T shape",
        "template" =>  "NECB2011",
        "building_type" => "SmallOffice",
        "epw_file" => "CAN_ON_Ottawa-Macdonald-Cartier.Intl.AP.716280_CWEC2016.epw",
        "total_floor_area" => 500000,
        "aspect_ratio" => 0.75,
        "rotation" => 0.0,
        "above_grade_floors" => 3,
        "floor_to_floor_height" => 3.2,
        "plenum_height" => 1.0
    }


    # Create an instance of the measure
    runner = run_measure(input_arguments, model)
    #BTAP::FileIO::save_osm(model, File.join(File.dirname(__FILE__), "output", "T_Shape.osm"))
    assert(runner.result.value.valueName == 'Success')

  end
end
