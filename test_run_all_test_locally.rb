require 'fileutils'
require 'parallel'
require 'open3'
require 'minitest/autorun'
require 'json'
require_relative './parallel_tests'
TestListFile = File.join(File.dirname(__FILE__), 'circleci_tests.txt')

class String
  # colorization
  def colorize(color_code)
    "\e[#{color_code}m#{self}\e[0m"
  end

  def red
    colorize(31)
  end
  def yellow
    colorize(33)
  end
end

class RunAllTests < Minitest::Test
  def test_all()
    full_file_list = nil
    if File.exist?(TestListFile)
      puts TestListFile
      # load test files from file.
      full_file_list = File.readlines(TestListFile).shuffle
      # Select only .rb files that exist
      full_file_list.select! {|item| item =~ /.*\.rb$/ && File.exist?(File.absolute_path("#{item.strip}"))}
      full_file_list.map! {|item| File.absolute_path("#{item.strip}")}
    else
      puts "Could not find list of files to test at #{TestListFile}".yellow
      return false
    end
    msg="Some tests failed. Please ensure all test pass and tests have been updated to reflect the changes you expect before issuing a pull request."
    assert(ParallelTests.new.run(full_file_list), msg.yellow)
  end
end