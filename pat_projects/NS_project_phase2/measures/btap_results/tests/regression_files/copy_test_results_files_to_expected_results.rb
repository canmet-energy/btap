require 'fileutils'

folder_path = File.dirname(__FILE__)
puts folder_path
Dir.glob(folder_path + "/*test_result.cost.json").sort.each do |f|
  new_file = f.gsub("test_result.cost.json","expected_result.cost.json")
  FileUtils.cp(f,new_file )
  puts "created new #{new_file}"
end