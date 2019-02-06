
require 'rake/testtask'
require 'json'


namespace :test do
  full_file_list = nil
  if File.exist?('circleci_tests.txt')
    # load test files from file.
    full_file_list = FileList.new(File.readlines('circleci_tests.txt'))
    # Select only .rb files that exist
    full_file_list.select! { |item| item.include?('rb') && File.exist?(File.absolute_path("#{item.strip}")) }
    full_file_list.map! { |item| File.absolute_path("#{item.strip}") }
    File.open("circleci_tests.json","w") do |f|
      f.write(JSON.pretty_generate(full_file_list.to_a))
    end
  else
    puts 'Could not find list of files to test at test/circleci_tests.txt'
    return false
  end

  desc 'Run All CircleCI tests locally'
  Rake::TestTask.new('measure-tests') do |t|
    file_list = FileList.new('test_run_all_test_locally.rb')
    t.libs << 'test'
    t.test_files = file_list
    t.verbose = false
  end

  # These tests only available in the CI environment
  if ENV['CI'] == 'true'

    desc 'Run CircleCI tests'
    Rake::TestTask.new('circleci') do |t|
      # Create a FileList for this task
      test_list = FileList.new
      # Read the parallelized list of tests
      # created by the circleci CLI in config.yml
      if File.exist?('circleci_tests.txt')
        File.open('circleci_tests.txt', 'r') do |f|
          f.each_line do |line|
            # Skip comments the CLI may have included
            next unless line.include?('.rb')
            # Remove whitespaces
            line = line.strip
            # Ensure the file exists
            pth = File.absolute_path("#{line}")
            unless File.exist?(pth)
              puts "Skipped #{line} because this file doesn't exist"
              puts "From #{Dir.pwd}"
              next
            end
            # Add this test to the list
            test_list.add(pth)
          end
        end
        # Assign the tests to this task
        t.test_files = test_list
      else
        puts 'Could not find parallelized list of CI tests.'
      end
    end


    desc 'Summarize the test timing'
    task 'times' do |t|
      require 'nokogiri'

      files_to_times = {}
      tests_to_times = {}
      Dir['test/reports/*.xml'].each do |xml|
        doc = File.open(xml) { |f| Nokogiri::XML(f) }
        doc.css('testcase').each do |testcase|
          time = testcase.attr('time').to_f
          file = testcase.attr('file')
          name = testcase.attr('name')
          # Add to total for this file
          if files_to_times[file].nil?
            files_to_times[file] = time
          else
            files_to_times[file] += time
          end
          # Record for this test itself
          if tests_to_times[name].nil?
            tests_to_times[name] = time
          else
            tests_to_times[name] += time
          end
        end
      end

      # Write out the test results to file
      folder = "#{Dir.pwd}/timing"
      Dir.mkdir(folder) unless File.exist?(folder)

      # By file
      File.open("#{Dir.pwd}/timing/test_by_file.html", 'w') do |html|
        html.puts '<table><tr><th>File Name</th><th>Time (min)</th></tr>'
        files_to_times.each do |f, time_s|
          s = (time_s / 60).round(1) # convert time from sec to min
          html.puts "<tr><td>#{f}</td><td>#{s}</td></tr>"
        end
        html.puts '</table>'
      end

      # By name
      File.open("#{Dir.pwd}/timing/test_by_name.html", 'w') do |html|
        html.puts '<table><tr><th>Test Name</th><th>Time (min)</th></tr>'
        tests_to_times.each do |f, time_s|
          s = (time_s / 60).round(1) # convert time from sec to min
          html.puts "<tr><td>#{f}</td><td>#{s}</td></tr>"
        end
        html.puts '</table>'
      end
    end

  end



end




desc 'Update Measures'
task :measure_xml_update do
  system( 'openstudio measure --update_all measures/')
end


desc 'Update Common Resources from TemplateModelMeasure'
task :update_resources do
  # Find all files in measures/BTAPTemplateModelMeasure/resources
  files = Dir.glob("measures_development/BTAPTemplateModelMeasure/resources/*.*").map(&File.method(:realpath))
  folders = Dir.glob("measures/*/resources").map(&File.method(:realpath))
  folders.concat(Dir.glob("measures_development/*/resources").map(&File.method(:realpath)))
  #copy files over
  folders.each do |folder|
    files.each do |file|
      FileUtils.cp(file, folder)
      puts "Copied #{file} to #{folder}"
    end unless folder.include?('BTAPTemplateModelMeasure')
  end
end

desc 'Update RSMeans Costing Data From Web API'
task :update_costing do
  require_relative './measures/btap_results/resources/btap_costing'
  data = BTAPCosting.new()
  data.create_database()
  data.create_dummy_database()
  puts "Dummy/Empty database created as default measures/btap_results/resources/costing_database.json.gz. "
  puts "Overwrite costing_database.json.gz with costing_database_rsmeans.json.gz to use rsmeans costing."
end






