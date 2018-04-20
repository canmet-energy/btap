require 'rake/testtask'
namespace :test do
  #create test list
  sh 'openstudio measure --update_all measures/'
  array = []
  array << 'measures/BTAPCreateNECBPrototypeBuildings/tests/BTAPCreateNECBPrototypeBuildings_test.rb'
  array << 'measures/BTAPEnvelopeConstructionMeasureDetailed/tests/BTAPEnvelopeConstructionMeasureDetailed_test.rb'
  array << 'measures/BTAPEnvelopeConstructionMeasurePackaged/tests/BTAPEnvelopeConstructionMeasurePackaged_test.rb'
  array << 'measures/BTAPEnvelopeFDWRAndSRR/tests/BTAPEnvelopeFDWRAndSRR_Test.rb'
  array << 'measures/BTAPLightingPowerDensityMeasure/tests/lighting_power_density_measure_test.rb'
  desc 'Measures Tests'
  Rake::TestTask.new('measure-tests') do |t|
    t.libs << 'test'
    t.test_files = array
  end
end





