require 'rake/testtask'
namespace :test do
  #create test list
  array = []
  array << 'measures/BTAPCreateNECBPrototypeBuildings/tests/BTAPCreateNECBPrototypeBuildings_test.rb'
  array << 'measures/BTAPEnvelopeConstructionMeasureDetailed/tests/BTAPEnvelopeConstructionMeasureDetailed_test.rb'
  # array << 'measures/BTAPModifyConductancesByPercentage/tests/btap_modify_conductances_by_percentage_test.rb'
  # array << 'measures/BTAPOpenstudioResults/tests/OpenStudioResults_Test.rb'
  # array << 'measures/BTAPReportVariables/tests/zone_report_variables_test.rb'
  # array << 'measures/BTAPResults/tests/OpenStudioResults_Test.rb'
  # array << 'measures/BTAPUtilityTariffs/tests/UtilityTariffs_Test.rb'
  desc 'Measures Tests'
  Rake::TestTask.new('measure-tests') do |t|
    t.libs << 'test'
    t.test_files = array
  end
end


require 'rubocop/rake_task'
desc 'Check the code for style consistency'
RuboCop::RakeTask.new(:rubocop) do |t|
  # Make a folder for the output
  out_dir = '.rubocop'
  Dir.mkdir(out_dir) unless File.exist?(out_dir)
  # Output both XML (CheckStyle format) and HTML
  t.options = ["--out=#{out_dir}/rubocop-results.xml", '--format=h', "--out=#{out_dir}/rubocop-results.html", '--format=offenses', "--out=#{out_dir}/rubocop-summary.txt"]
  t.requires = ['rubocop/formatter/checkstyle_formatter']
  t.formatters = ['RuboCop::Formatter::CheckstyleFormatter']
  # don't abort rake on failure
  t.fail_on_error = false
end

desc 'Show the rubocop output in a web browser'
task 'rubocop:show' => [:rubocop] do
  link = "#{Dir.pwd}/.rubocop/rubocop-results.html"
  if RbConfig::CONFIG['host_os'] =~ /mswin|mingw|cygwin/
    system "start #{link}"
  elsif RbConfig::CONFIG['host_os'] =~ /darwin/
    system "open #{link}"
  elsif RbConfig::CONFIG['host_os'] =~ /linux|bsd/
    system "xdg-open #{link}"
  end
end
