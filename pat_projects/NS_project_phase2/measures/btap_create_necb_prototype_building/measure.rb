# Start the measure
require 'openstudio-standards'
class BTAPCreateNECBPrototypeBuilding < OpenStudio::Ruleset::ModelUserScript
  # Define the name of the Measure.
  def name
    return 'BTAPCreateNECBPrototypeBuilding'
  end


  # Human readable description
  def description
    return 'This measure creates an NECB prototype building from scratch and uses it as the base for an analysis.'
  end

  # Human readable description of modeling approach
  def modeler_description
    return 'This will replaced the model object with a brand new model. It effectively ignores the seed model.'
  end

  # Define the arguments that the user will input.
  def arguments(model)
    @templates = ['NECB2011','NECB2015','NECB2017']
    args = OpenStudio::Ruleset::OSArgumentVector.new

    # Make an argument for the building type
    building_type_chs = OpenStudio::StringVector.new
    building_type_chs << 'SecondarySchool'
    building_type_chs << 'PrimarySchool'
    building_type_chs << 'SmallOffice'
    building_type_chs << 'MediumOffice'
    building_type_chs << 'LargeOffice'
    building_type_chs << 'SmallHotel'
    building_type_chs << 'LargeHotel'
    building_type_chs << 'Warehouse'
    building_type_chs << 'RetailStandalone'
    building_type_chs << 'RetailStripmall'
    building_type_chs << 'QuickServiceRestaurant'
    building_type_chs << 'FullServiceRestaurant'
    building_type_chs << 'MidriseApartment'
    building_type_chs << 'HighriseApartment'
    building_type_chs << 'Hospital'
    building_type_chs << 'Outpatient'
    building_type = OpenStudio::Ruleset::OSArgument::makeChoiceArgument('building_type', building_type_chs, true)
    building_type.setDisplayName('Building Type.')
    building_type.setDefaultValue('SmallOffice')
    args << building_type

    # Make an argument for the template
    template_chs = OpenStudio::StringVector.new(@templates)

    template = OpenStudio::Ruleset::OSArgument::makeChoiceArgument('template', template_chs, true)
    template.setDisplayName('Template.')
    template.setDefaultValue('NECB2011')
    args << template

    #Drop down selector for Canadian weather files. 
    epw_files = OpenStudio::StringVector.new
    ['CAN_AB_Banff.CS.711220_CWEC2016.epw', 'CAN_AB_Calgary.Intl.AP.718770_CWEC2016.epw', 'CAN_AB_Edmonton.Intl.AP.711230_CWEC2016.epw', 'CAN_AB_Edmonton.Stony.Plain.AP.711270_CWEC2016.epw', 'CAN_AB_Fort.McMurray.AP.716890_CWEC2016.epw', 'CAN_AB_Grande.Prairie.AP.719400_CWEC2016.epw', 'CAN_AB_Lethbridge.AP.712430_CWEC2016.epw', 'CAN_AB_Medicine.Hat.AP.710260_CWEC2016.epw', 'CAN_BC_Abbotsford.Intl.AP.711080_CWEC2016.epw', 'CAN_BC_Comox.Valley.AP.718930_CWEC2016.epw', 'CAN_BC_Crankbrook-Canadian.Rockies.Intl.AP.718800_CWEC2016.epw', 'CAN_BC_Fort.St.John-North.Peace.Rgnl.AP.719430_CWEC2016.epw', 'CAN_BC_Hope.Rgnl.Airpark.711870_CWEC2016.epw', 'CAN_BC_Kamloops.AP.718870_CWEC2016.epw', 'CAN_BC_Port.Hardy.AP.711090_CWEC2016.epw', 'CAN_BC_Prince.George.Intl.AP.718960_CWEC2016.epw', 'CAN_BC_Smithers.Rgnl.AP.719500_CWEC2016.epw', 'CAN_BC_Summerland.717680_CWEC2016.epw', 'CAN_BC_Vancouver.Intl.AP.718920_CWEC2016.epw', 'CAN_BC_Victoria.Intl.AP.717990_CWEC2016.epw', 'CAN_MB_Brandon.Muni.AP.711400_CWEC2016.epw', 'CAN_MB_The.Pas.AP.718670_CWEC2016.epw', 'CAN_MB_Winnipeg-Richardson.Intl.AP.718520_CWEC2016.epw', 'CAN_NB_Fredericton.Intl.AP.717000_CWEC2016.epw', 'CAN_NB_Miramichi.AP.717440_CWEC2016.epw', 'CAN_NB_Saint.John.AP.716090_CWEC2016.epw', 'CAN_NL_Gander.Intl.AP-CFB.Gander.718030_CWEC2016.epw', 'CAN_NL_Goose.Bay.AP-CFB.Goose.Bay.718160_CWEC2016.epw', 'CAN_NL_St.Johns.Intl.AP.718010_CWEC2016.epw', 'CAN_NL_Stephenville.Intl.AP.718150_CWEC2016.epw', 'CAN_NS_CFB.Greenwood.713970_CWEC2016.epw', 'CAN_NS_CFB.Shearwater.716010_CWEC2016.epw', 'CAN_NS_Sable.Island.Natl.Park.716000_CWEC2016.epw', 'CAN_NS_Sydney-McCurdy.AP.717070_8205701_CWEC2016.epw'].each do |epw_file|
     epw_files << epw_file
    end

    ['CAN_NS_Truro.713980_CWEC.epw', 'CAN_NT_Inuvik-Zubko.AP.719570_CWEC2016.epw', 'CAN_NT_Yellowknife.AP.719360_CWEC2016.epw', 'CAN_ON_Armstrong.AP.718410_CWEC2016.epw', 'CAN_ON_CFB.Trenton.716210_CWEC2016.epw', 'CAN_ON_Dryden.Rgnl.AP.715270_CWEC2016.epw', 'CAN_ON_London.Intl.AP.716230_CWEC2016.epw', 'CAN_ON_Moosonee.AP.713980_CWEC2016.epw', 'CAN_ON_Mount.Forest.716310_CWEC2016.epw', 'CAN_ON_North.Bay-Garland.AP.717310_CWEC2016.epw', 'CAN_ON_Ottawa-Macdonald-Cartier.Intl.AP.716280_CWEC2016.epw', 'CAN_ON_Sault.Ste.Marie.AP.712600_CWEC2016.epw', 'CAN_ON_Timmins.Power.AP.717390_CWEC2016.epw', 'CAN_ON_Toronto.Pearson.Intl.AP.716240_CWEC2016.epw', 'CAN_ON_Windsor.Intl.AP.715380_CWEC2016.epw', 'CAN_PE_Charlottetown.AP.717060_CWEC2016.epw', 'CAN_QC_Kuujjuaq.AP.719060_CWEC2016.epw', 'CAN_QC_Kuujuarapik.AP.719050_CWEC2016.epw', 'CAN_QC_Lac.Eon.AP.714210_CWEC2016.epw', 'CAN_QC_Mont-Joli.AP.717180_CWEC2016.epw', 'CAN_QC_Montreal-Mirabel.Intl.AP.719050_CWEC2016.epw', 'CAN_QC_Montreal-St-Hubert.Longueuil.AP.713710_CWEC2016.epw', 'CAN_QC_Montreal-Trudeau.Intl.AP.716270_CWEC2016.epw', 'CAN_QC_Quebec-Lesage.Intl.AP.717140_CWEC2016.epw', 'CAN_QC_Riviere-du-Loup.717150_CWEC2016.epw', 'CAN_QC_Roberval.AP.717280_CWEC2016.epw', 'CAN_QC_Saguenay-Bagotville.AP-CFB.Bagotville.717270_CWEC2016.epw', 'CAN_QC_Schefferville.AP.718280_CWEC2016.epw', 'CAN_QC_Sept-Iles.AP.718110_CWEC2016.epw', 'CAN_QC_Val-d-Or.Rgnl.AP.717250_CWEC2016.epw', 'CAN_SK_Estevan.Rgnl.AP.718620_CWEC2016.epw', 'CAN_SK_North.Battleford.AP.718760_CWEC2016.epw', 'CAN_SK_Saskatoon.Intl.AP.718660_CWEC2016.epw', 'CAN_YT_Whitehorse.Intl.AP.719640_CWEC2016.epw'].each do |epw_file|
      epw_files << epw_file
    end

    epw_file = OpenStudio::Ruleset::OSArgument::makeChoiceArgument('epw_file', epw_files, true)
    epw_file.setDisplayName('Climate File')
    epw_file.setDefaultValue('CAN_AB_Banff.CS.711220_CWEC2016.epw')
    args << epw_file

    auto_zone = OpenStudio::Ruleset::OSArgument::makeBoolArgument('new_auto_zoner', true)
    auto_zone.setDisplayName('Use New Autozone method?')
    auto_zone.setDefaultValue(false)
    args << auto_zone

    #argument for geometry volume scaling
    fdwr = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("fdwr", false)
    fdwr.setDisplayName("Fenestration and Door to Wall Ratio (set a value between 0 and 1, or set to 1.1 or ignore to use NECB maximum).")
    fdwr.setDefaultValue(1.1)
    args << fdwr

    #argument for geometry volume scaling
    srr = OpenStudio::Ruleset::OSArgument::makeDoubleArgument("srr", false)
    srr.setDisplayName("Skylight to Roof Ratio (set a value between 0 and 1, or set to 1.1 or ignore to use NECB maximum).")
    srr.setDefaultValue(1.1)
    args << srr

    return args
  end

  # Define what happens when the measure is run.
  def run(model, runner, user_arguments)
    super(model, runner, user_arguments)

    # Use the built-in error checking
    if not runner.validateUserArguments(arguments(model), user_arguments)
      return false
    end

    # Assign the user inputs to variables that can be accessed across the measure
    building_type = runner.getStringArgumentValue('building_type', user_arguments)
    template = runner.getStringArgumentValue('template', user_arguments)
    epw_file = runner.getStringArgumentValue('epw_file', user_arguments)
    new_auto_zoner = runner.getBoolArgumentValue('new_auto_zoner', user_arguments)
    fdwr = runner.getDoubleArgumentValue('fdwr',user_arguments)
    srr = runner.getDoubleArgumentValue('srr',user_arguments)

    # Turn debugging output on/off
    @debug = false

    # Open a channel to log info/warning/error messages
    @msg_log = OpenStudio::StringStreamLogSink.new
    if @debug
      @msg_log.setLogLevel(OpenStudio::Debug)
    else
      @msg_log.setLogLevel(OpenStudio::Info)
    end
    @start_time = Time.new
    @runner = runner

    # Make a directory to save the resulting models for debugging
    build_dir = "#{Dir.pwd}/output"
    if !Dir.exists?(build_dir)
      Dir.mkdir(build_dir)
    end

    #Set OSM folder
    osm_directory = ""

    if @templates.include?(template)
      osm_directory = "#{build_dir}/#{building_type}-#{template}-#{epw_file}"
    else
      osm_directory = build_dir
    end
    if !Dir.exists?(osm_directory)
      Dir.mkdir(osm_directory)
    end

    #with this option, the measure will override whatever is in the climate zone for
    # NREL prototypes with the lookup climate zone based on the epw city.

    #Get Weather climate zone from lookup
    weather = BTAP::Environment::WeatherFile.new(epw_file)

    #Override climate zone from lookup if anything but NECB 2011.
    unless @templates.include?(template)
      climate_zone = weather.a169_2006_climate_zone()
    end

    #create model
    building_name = "#{template}_#{building_type}"
    puts "Creating #{building_name}"
    standard = Standard.build(template)

    # Side inject json files from
    path = "#{File.dirname(__FILE__)}/resources/data_sideload/"
    raise ('Could not find data_sideload folder') unless Dir.exist?(path)
    files = Dir.glob("#{path}/*.json").select {|e| File.file? e}
    files.each do |file|
      data = JSON.parse(File.read(file))
      if not data["tables"].nil?
        standard.standards_data["tables"] = [*standard.standards_data["tables"], *data["tables"]].to_h
      else
        #standard.standards_data[data.keys.first] = data[data.keys.first]
      end
      runner.registerWarning("Replaced default standard data with contents in #{file}")
      puts "Replaced default standard data with contents in #{file}"
    end



    new_model = standard.model_create_prototype_model(template: template,
                                                           building_type: building_type,
                                                           epw_file: epw_file,
                                                           sizing_run_dir: osm_directory,
                                                           debug: @debug,
                                                           fdwr_set: fdwr,
                                                           srr_set: srr,
                                                           new_auto_zoner: new_auto_zoner)
    standard.model_replace_model(model, new_model)


    log_msgs
    return true
  end

  #end the run method

  # Get all the log messages and put into output
  # for users to see.
  def log_msgs
    @msg_log.logMessages.each do |msg|
      # DLM: you can filter on log channel here for now
      if /openstudio.*/.match(msg.logChannel) #/openstudio\.model\..*/
        # Skip certain messages that are irrelevant/misleading
        next if msg.logMessage.include?("Skipping layer") || # Annoying/bogus "Skipping layer" warnings
            msg.logChannel.include?("runmanager") || # RunManager messages
            msg.logChannel.include?("setFileExtension") || # .ddy extension unexpected
            msg.logChannel.include?("Translator") || # Forward translator and geometry translator
            msg.logMessage.include?("UseWeatherFile") # 'UseWeatherFile' is not yet a supported option for YearDescription

        # Report the message in the correct way
        if msg.logLevel == OpenStudio::Info
          @runner.registerInfo(msg.logMessage)
        elsif msg.logLevel == OpenStudio::Warn
          @runner.registerWarning("[#{msg.logChannel}] #{msg.logMessage}")
        elsif msg.logLevel == OpenStudio::Error
          @runner.registerError("[#{msg.logChannel}] #{msg.logMessage}")
        elsif msg.logLevel == OpenStudio::Debug && @debug
          @runner.registerInfo("DEBUG - #{msg.logMessage}")
        end
      end
    end
    @runner.registerInfo("Total Time = #{(Time.new - @start_time).round}sec.")
  end

end #end the measure

#this allows the measure to be use by the application
BTAPCreateNECBPrototypeBuilding.new.registerWithApplication
