require 'rake/testtask'
namespace :test do
  #create test list
  sh 'openstudio measure --update_all measures/'
  array = []
  array << 'measures_development/BTAPTemplateModelMeasure/tests/test.rb'
  array << 'measures/btap_create_necb_prototype_building/tests/test.rb'
  array << 'measures/btap_create_necb_reference_building/tests/test.rb'
  array << 'measures/btap_envelope_construction_measure/tests/test.rb'
  array << 'measures/btap_envelope_fdwr_and_srr/tests/test.rb'
  array << 'measures/btap_ideal_air_loads_measure/tests/test.rb'
  array << 'measures/btap_ideal_air_loads_options_eplus/tests/test.rb'
  array << 'measures/btap_open_studio_results/tests/test.rb'
  #array << 'measures/btap_report_variables/tests/test.rb'
  array << 'measures/btap_results/tests/test.rb'
  #array << 'measures/btap_utility_tariffs/tests/test.rb'
  #array << 'measures/btap_view_model/tests/test.rb'





  desc 'Measures Tests'
  Rake::TestTask.new('measure-tests') do |t|
    t.libs << 'test'
    t.test_files = array
  end
end

desc 'Update Common Resources from TemplateModelMeasure'
task :update_resources do
  # Find all files in measures/BTAPTemplateModelMeasure/resources
  files =  Dir.glob("measures_development/BTAPTemplateModelMeasure/resources/*.*").map(&File.method(:realpath))
  folders =  Dir.glob("measures/*/resources").map(&File.method(:realpath))
  folders.concat(Dir.glob("measures_development/*/resources").map(&File.method(:realpath)))
  #copy files over
  folders.each do |folder|
    files.each do |file|
      FileUtils.cp(file, folder)
      puts "Copied #{file} to #{folder}"
    end unless folder.include?('BTAPTemplateModelMeasure')
  end

end




