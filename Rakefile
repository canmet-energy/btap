require 'rake/testtask'
namespace :test do
  #create test list
  sh 'openstudio measure --update_all measures/'
  array = []
  array << 'measures/BTAPTemplateModelMeasure/tests/BTAPTemplateModelMeasure_test.rb'
  array << 'measures/BTAPCreateNECBPrototypeBuildings/tests/BTAPCreateNECBPrototypeBuildings_test.rb'
  array << 'measures/BTAPEnvelopeConstructionMeasureDetailed/tests/BTAPEnvelopeConstructionMeasureDetailed_test.rb'
  array << 'measures/BTAPEnvelopeConstructionMeasurePackaged/tests/BTAPEnvelopeConstructionMeasurePackaged_test.rb'
  array << 'measures/BTAPEnvelopeFDWRAndSRR/tests/BTAPEnvelopeFDWRAndSRR_Test.rb'
  desc 'Measures Tests'
  Rake::TestTask.new('measure-tests') do |t|
    t.libs << 'test'
    t.test_files = array
  end
end




