require 'rake/testtask'
namespace :test do
  #create test list
  sh 'openstudio measure --update_all measures/'
  array = []
  array << 'measures_development/BTAPTemplateModelMeasure/tests/BTAPTemplateModelMeasure_test.rb'
  array << 'measures/BTAPCreateNECBPrototypeBuildings/tests/BTAPCreateNECBPrototypeBuildings_test.rb'
  array << 'measures/BTAPCreateNECBReferenceBuilding/tests/BTAPCreateNECBReferenceBuilding_test.rb'
  array << 'measures/BTAPEnvelopeConstructionMeasure/tests/BTAPEnvelopeConstructionMeasure_test.rb'
  array << 'measures/BTAPEnvelopeFDWRAndSRR/tests/BTAPEnvelopeFDWRAndSRR_Test.rb'
  array << 'measures/BTAPResults/tests/OpenStudioResults_Test.rb'
  array << 'measures/BTAPOpenstudioResults/tests/OpenStudioResults_Test.rb'
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




