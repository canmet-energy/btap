require 'openstudio'
require 'openstudio/measure/ShowRunnerOutput'
require 'fileutils'

begin
  require 'openstudio_measure_tester/test_helper'
rescue LoadError
  puts 'OpenStudio Measure Tester Gem not installed -- will not be able to aggregate and dashboard the results of tests'
end
require_relative '../measure.rb'
require 'minitest/autorun'
class BTAPCreateNECBPrototypeBuilding_Test < Minitest::Test

  def test_create_necb_vintages
    @templates = ['NECB2011',
                  'NECB2015',
                  'NECB2017']
    @building_types = ['FullServiceRestaurant']
    @epw_file = ['CAN_AB_Banff.CS.711220_CWEC2016.epw']

    all_errors = []
    @building_types.each do |building_type|
      @epw_file.each do |epw_file|

        @templates.each do |template|
          status, errors = create_building(necb_template: template, building_type_in: building_type, epw_file_in: epw_file)
          all_errors  << errors if errors.size > 0
        end
      end
    end
    assert(all_errors.size == 0 , "The Following regression errors occured #{JSON.pretty_generate(all_errors)}")
  end


  def create_building(necb_template: , building_type_in:, epw_file_in:)
    # create an instance of the measure
    measure = BTAPCreateNECBPrototypeBuilding.new

    # create an instance of a runner
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

    # make an empty model
    model = OpenStudio::Model::Model.new

    # test arguments and defaults
    arguments = measure.arguments(model)
    #check number of arguments.
    assert_equal(4, arguments.size)
    #check argument 0
    assert_equal('building_type', arguments[0].name)
    assert_equal('SmallOffice', arguments[0].defaultValueAsString)
    #check argument 1
    assert_equal('template', arguments[1].name)
    assert_equal('NECB2011', arguments[1].defaultValueAsString)
    #check argument 2
    assert_equal('epw_file', arguments[2].name)
    assert_equal('CAN_AB_Banff.CS.711220_CWEC2016.epw', arguments[2].defaultValueAsString)
    #check argument 3
    assert_equal('new_auto_zoner', arguments[3].name)
    assert_equal(false, arguments[3].defaultValueAsBool)


    # set argument values to values and run the measure
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)

    #set argument 0
    building_type = arguments[0].clone
    assert(building_type.setValue(building_type_in))
    argument_map['building_type'] = building_type

    #set argument 1
    template = arguments[1].clone
    assert(template.setValue(necb_template))
    argument_map['template'] = template

    #set argument 2
    epw_file = arguments[2].clone
    assert(epw_file.setValue(epw_file_in))
    argument_map['epw_file'] = epw_file

    #run the measure
    measure.run(model, runner, argument_map)

    result = runner.result
    assert(result.value.valueName == 'Success')

    begin
      diffs = []
      test_dir = "#{File.dirname(__FILE__)}/output"
      if !Dir.exists?(test_dir)
        Dir.mkdir(test_dir)
      end
      model_name = "#{building_type_in}-#{necb_template}-#{File.basename(epw_file_in, '.epw')}"
      run_dir = "#{test_dir}/#{model_name}"
      if !Dir.exists?(run_dir)
        Dir.mkdir(run_dir)
      end


      print model.class.name
      unless model.instance_of?(OpenStudio::Model::Model)
        puts "Creation of Model for #{osm_model_path} failed. Please check output for errors."
      end
      #Save osm file.
      filename = "#{File.dirname(__FILE__)}/regression_models/#{model_name}_test_result.osm"
      FileUtils.mkdir_p(File.dirname(filename))
      File.delete(filename) if File.exist?(filename)
      puts "Saving osm file to : #{filename}"
      model.save(filename)

      #old models
      # Load the geometry .osm
      osm_file = "#{File.dirname(__FILE__)}/regression_models/#{model_name}_expected_result.osm"
      unless File.exist?(osm_file)
        raise("The initial osm path: #{osm_file} does not exist.")
      end
      osm_model_path = OpenStudio::Path.new(osm_file.to_s)
      # Upgrade version if required.
      version_translator = OpenStudio::OSVersion::VersionTranslator.new
      old_model = version_translator.loadModel(osm_model_path).get


      # Compare the two models.
      diffs = BTAP::FileIO::compare_osm_files(old_model, model)
    rescue => exception
      # Log error/exception and then keep going.
      error = "#{exception.backtrace.first}: #{exception.message} (#{exception.class})"
      exception.backtrace.drop(1).map {|s| "\n#{s}"}.each {|bt| error << bt.to_s}
      diffs << "#{model_name}: Error \n#{error}"

    end
    #Write out diff or error message
    diff_file = "#{File.dirname(__FILE__)}/regression_models/#{model_name}_diffs.json"
    FileUtils.rm(diff_file) if File.exists?(diff_file)
    if diffs.size > 0
      File.write(diff_file, JSON.pretty_generate(diffs))
      puts "There were #{diffs.size} differences/errors in #{osm_file} #{template} #{epw_file}"
      return false, {"diffs-errors" => diffs}
    else
      return true, []
    end
  end

end
