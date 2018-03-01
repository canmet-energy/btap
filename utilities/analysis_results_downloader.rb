module OpenStudio
  module Analysis
    class ServerApi
      require 'optparse'
      require 'openstudio-aws'
      require 'openstudio-analysis'
      require 'fileutils'
      require 'pp'
      require 'colored'

      # This method will download the results files such as out.osw, view_model.html, etc.
      #
      # @param datapoint_id [:string] Datapoint ID param file_name [:string]
      # @Filename to be downloaded for the datapoint, with extension param
      # @save_directory [:string] path of output location, without filename
      # @extension return [downloaded, file_path_and_name] [:array]:
      # @[downloaded] boolean - true if download is successful;
      # @[file_path_and_name] String path and file name of the downloaded file
      # @with extension
      def download_file(datapoint_id, file_name, save_directory = '.')
        puts "download_file(#{datapoint_id}, #{file_name}, #{save_directory})".cyan
        downloaded = false
        file_path_and_name = nil
        response = @conn.get "/data_points/#{datapoint_id}/download_result_file?filename=#{file_name}"
        if response.status == 200
          filename = response['content-disposition'].match(/filename=(\"?)(.+)\1/)[2]
          downloaded = true
          file_path_and_name = "#{save_directory}/#{datapoint_id}-#{filename}"
          puts "File #{filename} already exists, overwriting" if File.exist?(file_path_and_name)
          File.open(file_path_and_name, 'wb') { |f| f << response.body }
        else
          response = @conn.get "/data_points/#{datapoint_id}/download"
          if response.status == 200
            filename = response['content-disposition'].match(/filename=(\"?)(.+)\1/)[2]
            downloaded = true
            file_path_and_name = "#{save_directory}/#{datapoint_id}-#{filename}"
            puts "File #{filename} already exists, overwriting" if File.exist?(file_path_and_name)
            File.open(file_path_and_name, 'wb') { |f| f << response.body }
          end
        end
        # if the file was not downloaded successfully, then write it in the error log
        if !downloaded
          File.open("#{save_directory}/missing_files.log", 'w') { |f| f.write("") } unless File.exist?("#{save_directory}/missing_files.log")
          File.open("#{save_directory}/missing_files.log", 'a') { |f| f.write("Unable to download #{datapoint_id}-#{file_name}\n") }
        end
        return [downloaded, file_path_and_name]
      end #download_file

      # This method will download the status of the entire analysis which includes the datapoint
      # status such as "completed normal" or "datapoint failure"
      #
      # @param datapoint_id [:string] Datapoint ID
      # @param file_name [:string] Filename to be downloaded for the datapoint, with extension
      # @param save_directory [:string] path and filename of output location, without filename extension
      def download_datapoint_status(analysis_id, save_directory = '.', filter = nil)
        data_points = nil
        # get the status of all the entire analysis
        unless analysis_id.nil?
          if filter.nil? || filter == ''
            resp = @conn.get "analyses/#{analysis_id}/status.json"
            if resp.status == 200
              data_points = JSON.parse(resp.body, symbolize_names: true)[:analysis][:data_points]
              file_path_and_name = "#{save_directory}/full_run_status.json"
              File.open(file_path_and_name, 'wb') { |f| f << resp.body }
            end
          else
            resp = @conn.get "analyses/#{analysis_id}/status.json", jobs: filter
            if resp.status == 200
              data_points = JSON.parse(resp.body, symbolize_names: true)[:analysis][:data_points]
              file_path_and_name = "#{save_directory}/ANALYSIS-#{analysis_id}.json"
              File.open(file_path_and_name, 'wb') { |f| f << resp.body }
            end
          end
        end
      end #download_datapoint_status

      # This method will download the status of the entire analysis which includes the datapoint
      # status such as "completed normal" or "datapoint failure"
      #
      # @param datapoint_id [:string] Datapoint ID
      # @param file_name [:string] Filename to be downloaded for the datapoint, with extension
      # @param save_directory [:string] path of output location, without filename extension
      # @return [downloaded, file_path_and_name] [:array]: [downloaded] boolean - true if download is successful; [file_path_and_name] String path and file name of the downloaded file with extension
      def get_log_file (analysis_id, data_point_id, save_directory = '.')
        downloaded = false
        file_path_and_name = nil
        unless analysis_id.nil?
          data_points = nil
          resp = @conn.get "analyses/#{analysis_id}/status.json"
          puts "status.json OK".green
          if resp.status == 200
            data_points = JSON.parse(resp.body)['analysis']['data_points']
            #data_points.each do |dp|
            data_points.each do |dp|
              next unless dp['_id'] == data_point_id
              puts "Checking #{dp['_id']}: Status: #{dp["status_message"]}".green
              log_resp = @conn.get "data_points/#{dp['_id']}.json"
              if log_resp.status == 200
                sdp_log_file = JSON.parse(log_resp.body)['data_point']['sdp_log_file']
                file_path_and_name = "#{save_directory}/#{dp['_id']}-sdp.log"
                File.open(file_path_and_name, 'wb') { |f|
                  sdp_log_file.each { |line| f.puts "#{line}"  }
                }
                downloaded = true
              else
                puts log_resp
              end
            end
          end
        end
        return [downloaded, file_path_and_name]
      end #get_log_file

    end
  end
end
### Users of this script: be aware that this will be replaced at some point with a set of classes for
### targets, queues, and the like.

require 'optparse'
require 'openstudio-aws'
require 'openstudio-analysis'
require 'fileutils'
require 'pp'
require 'colored'
require 'parallel'

# TODO: this is already in the workflow gem Openstudio::Workflow.extract_archive
# Unzip an archive to a destination directory using Rubyzip gem
#
# @param archive [:string] archive path for extraction
# @param dest [:string] path for archived file to be extracted to
def unzip_archive(archive, dest)
  # Adapted from examples at...
  #  https://github.com/rubyzip/rubyzip
  #  http://seenuvasan.wordpress.com/2010/09/21/unzip-files-using-ruby/
  Zip::File.open(archive) do |zf|
    zf.each do |f|
      f_path = File.join(dest, f.name)
      FileUtils.mkdir_p(File.dirname(f_path))
      zf.extract(f, f_path) unless File.exist?(f_path) # No overwrite
    end
  end
end

# Get excel project and return analysis json and zip
#
# @param filename [:string] input path and filename
# @param output_path [:string] path and filename of output location, without extension
# @return aws_instance_options [:hash] parsed options required to define an instance
def process_excel_project(filename, output_path)
  analyses = OpenStudio::Analysis.from_excel(filename)
  if analyses.size != 1
    puts 'ERROR: EXCEL-PROJECT -- More than one seed model specified. This feature is deprecated'.red
    fail 1
  end
  analysis = analyses.first
  analysis.save "#{output_path}.json"
  analysis.save_zip "#{output_path}.zip"

  OpenStudio::Analysis.aws_instance_options(filename)
end

# Get batch measure project and return analysis json and zip
#
# @param filename [:string] input path and filename
# @param output_path [:string] path and filename of the output location, without extension
# @return aws_instance_options if required, otherwise empty hash
def process_csv_project(filename, output_path)
  analysis = OpenStudio::Analysis.from_csv(filename)
  analysis.save "#{output_path}.json"
  analysis.save_zip "#{output_path}.zip"

  OpenStudio::Analysis.aws_instance_options(filename)
end

# Get ruby project and return analysis json and zip
#
# @param filename [:string] input path and filename
# @param output_path [:string] path and filename of output location, without extension
# @return aws_instance_options [:hash] parsed options required to define an instance
def process_rb_project(filename, output_path)
  fail 'This feature is under development'.red
end

# Find url associated with non-aws targets
# TODO: Make a target class with access keys and such not that is referenced here.
#
# @param target_type [:string] Non-aws environment target to get url of
# @return URL of input environment target
def lookup_target_url(target_type)
  server_dns = nil
  case target_type.downcase
  when 'vagrant'
    server_dns = 'http://localhost:8080'
  when 'nrel24'
    server_dns = 'http://bball-130449.nrel.gov:8080'
  when 'nrel24a'
    server_dns = 'http://bball-130553.nrel.gov:8080'
  when 'nrel24b'
    server_dns = 'http://bball-130590.nrel.gov:8080'
  when 'lcnode1'
    server_dns = 'http://10.60.7.61:8080'
  else
    puts "WARN: TARGET -- Unknown 'target_type' in #{__method__}"
    server_dns = target_type.downcase
  end

  server_dns
end

# Find or create the target machine
#
# @param target_type [:string] Environment to start /find (AWS, NREL***, vagrant)
# @param aws_instance_options [:hash] Number of workers to start. Can be zero
# @return [:osServerAPI] Return OpenStudioServerApi associated with the environment
def find_or_create_target(target_type, aws_instance_options)
  if target_type.downcase == 'aws'
    # Check or create new cluster on AWS
    if File.exist?("#{aws_instance_options[:cluster_name]}.json")
      puts "It appears that a cluster for #{aws_instance_options[:cluster_name]} is already running."
      puts "If this is not the case then delete ./#{aws_instance_options[:cluster_name]}.json file."
      puts "Or run 'bundle exec rake clean'"
      puts 'Will try to continue'

      # Load AWS instance
      aws = OpenStudio::Aws::Aws.new
      aws.load_instance_info_from_file("#{aws_instance_options[:cluster_name]}.json")
      server_dns = "http://#{aws.os_aws.server.data.dns}"
      puts "Server IP address #{server_dns}"

    else
      puts "Creating cluster for #{aws_instance_options[:user_id]}"
      puts 'Starting cluster...'

      # Don't use the old API (Version 1)
      ami_version = aws_instance_options[:os_server_version][0] == '2' ? 3 : 2
      aws_options = {ami_lookup_version: 3}
      aws = OpenStudio::Aws::Aws.new(aws_options)

      server_options = {
        instance_type: aws_instance_options[:server_instance_type],
        user_id: aws_instance_options[:user_id],
        tags: aws_instance_options[:aws_tags],
        image_id: 'ami-bc997fc1'
      }

      worker_options = {
        instance_type: aws_instance_options[:worker_instance_type],
        user_id: aws_instance_options[:user_id],
        tags: aws_instance_options[:aws_tags],
        image_id: 'ami-bc997fc1'
      }

      start_time = Time.now

      # Create the server & worker
      aws.create_server(server_options)
      aws.save_cluster_info("#{aws_instance_options[:cluster_name]}.json")
      aws.print_connection_info
      aws.create_workers(aws_instance_options[:worker_node_number], worker_options)
      aws.save_cluster_info("#{aws_instance_options[:cluster_name]}.json")
      aws.print_connection_info
      server_dns = "http://#{aws.os_aws.server.data.dns}"

      puts "Cluster setup in #{(Time.now - start_time).round} seconds. Awaiting analyses."
      puts "Server IP address is #{server_dns}"
    end
    OpenStudio::Analysis::ServerApi.new(hostname: server_dns)
  else
    OpenStudio::Analysis::ServerApi.new(hostname: lookup_target_url(target_type))
  end
end

# Execute threadsafe timeout loop for all requests contingent on analysis completion
#
# @param analysis_type [:string]
# @param download_dir [:string]
# @param flags [:hash]
# @param timeout [:fixnum]
# @return [:hash]
def run_queued_tasks(analysis_type, download_dir, flags, timeout)

  completed = {}
  submit_time = Time.now
  # if download and zip flags are set, this will download the
  # out.osw file in real time and extract the osm, eplustbl, 3d model, os-report, qaqc.json.
  # if the run fails it will download the log and eplus.err file and organize all the errors
  #   into one file in real time.
  if flags[:download] && flags[:zip]
    downloaded_all = false
    completed_dps = {} # will contain all the ids of the datapoint that have been downloaded
    download_count = 0 # keeps track of downloaded datapoints. This will determine if all datapoints are downloaded, and exit off the main loop
    total_dps = @server_api.get_datapoint_status(@analysis_id).length # gets the count of the total datapoints in the analysis

    root_folder = "#{download_dir}/#{@analysis_id}"
    simulations_json_folder = root_folder
    FileUtils.mkdir_p(root_folder)
    osw_folder = "#{root_folder}/osw_files"
    FileUtils.mkdir_p(osw_folder)
    output_folder = "#{root_folder}/output"
    FileUtils.mkdir_p(output_folder)
    File.open("#{root_folder}/missing_files.log", 'wb') { |f| f.write("") }
    File.open("#{root_folder}/missing_files.log", 'w') {|f| f.write("") }
    File.open("#{simulations_json_folder}/simulations.json", 'w'){}


    while !downloaded_all
      # update the list of completed datapoints
      comp_datapoint_list = @server_api.get_datapoint_status(@analysis_id, 'completed')
      processess = Parallel::processor_count
      Parallel.map(comp_datapoint_list, in_processes: processess) { |dp|
        #check if datapoint id is part of completed_dps list
        unless completed_dps.has_key?(dp[:_id])
          # download out.osw and get the status and the path of the downloaded file
          ok, osw_file = @server_api.download_file(dp[:_id], 'out.osw' , "#{osw_folder}")
          # ok => Boolean which determines if the file has been downloaded successfully
          # osw_file => path of the downloaded file name

          uuid = File.basename(osw_file, "-out.osw")
          # add the datapoint id to the list of downloaded datapoints and increment the count
          completed_dps[dp[:_id]] = ok
          download_count += 1
          results = JSON.parse(File.read(osw_file))

          # change the output folder directory based on building_type and climate_zone
          # get building_type and climate_zone from create_prototype_building measure if it exists
          results['steps'].each do |measure|
            next unless measure["name"] == "create_prototype_building"
            #template = measure["arguments"]["template"]
            building_type = measure["arguments"]["building_type"]
            #climate_zone = measure["arguments"]["climate_zone"]
            #remove the .epw suffix
            epw_file = measure["arguments"]["epw_file"].gsub(/\.epw/,"")
            output_folder = "#{root_folder}/output/#{building_type}/#{epw_file}"
            #puts output_folder
            FileUtils.mkdir_p(output_folder)
          end

          #parse the downloaded osw files and check if the datapoint failed or not
          #if failed download the eplusout.err and sldp_log files for error logging
          failed_log_folder = "#{output_folder}/failed_run_logs"
          check_and_log_error(results,root_folder,uuid,failed_log_folder)

          #itterate through all the steps of the osw file
          results['steps'].each do |measure|
            #puts "measure.name: #{measure['name']}"
            found_osm = false
            found_json = false

            # if the measure is openstudioresults, then download the eplustbl.htm and the pretty report [report.html]
            if measure["name"] == "openstudioresults" && measure.include?("result")
              measure["result"]["step_values"].each do |values|
                # extract the eplustbl.html blob data from the osw file and save it
                # in the output folder
                if values["name"] == 'eplustbl_htm'
                  eplustbl_htm_zip = values['value']
                  eplustbl_htm_string =  Zlib::Inflate.inflate(Base64.strict_decode64( eplustbl_htm_zip ))
                  FileUtils.mkdir_p("#{output_folder}/eplus_table")
                  File.open("#{output_folder}/eplus_table/#{uuid}-eplustbl.htm", 'wb') {|f| f.write(eplustbl_htm_string) }
                  #puts "#{uuid}-eplustbl.htm ok"
                end
                # extract the pretty report.html blob data from the osw file and save it
                # in the output folder
                if values["name"] == 'report_html'
                  report_html_zip = values['value']
                  report_html_string =  Zlib::Inflate.inflate(Base64.strict_decode64( report_html_zip ))
                  FileUtils.mkdir_p("#{output_folder}/os_report")
                  File.open("#{output_folder}/os_report/#{uuid}-os-report.html", 'wb') {|f| f.write(report_html_string) }
                  #puts "#{uuid}-os-report.html ok"
                end
              end
            end

            # if the measure is view_model, then extract the 3d.html model and save it
            if measure["name"] == "view_model" && measure.include?("result")
              measure["result"]["step_values"].each do |values|
                if values["name"] == 'view_model_html_zip'
                  view_model_html_zip = values['value']
                  view_model_html =  Zlib::Inflate.inflate(Base64.strict_decode64( view_model_html_zip ))
                  FileUtils.mkdir_p("#{output_folder}/3d_model")
                  File.open("#{output_folder}/3d_model/#{uuid}_3d.html", 'wb') {|f| f.write(view_model_html) }
                  #puts "#{uuid}-eplustbl.htm ok"
                end
              end
            end

            # if the measure is btapresults, then extract the osw file and qaqc json
            # While processing the qaqc json file, add it to the simulations.json file
            if measure["name"] == "btapresults" && measure.include?("result")
              measure["result"]["step_values"].each do |values|
                # extract the model_osm_zip blob data from the osw file and save it
                # in the output folder
                if values["name"] == 'model_osm_zip'
                  found_osm = true
                  model_osm_zip = values['value']
                  osm_string =  Zlib::Inflate.inflate(Base64.strict_decode64( model_osm_zip ))
                  FileUtils.mkdir_p("#{output_folder}/osm_files")
                  File.open("#{output_folder}/osm_files/#{uuid}.osm", 'wb') {|f| f.write(osm_string) }
                  #puts "#{uuid}.osm ok"
                end

                # extract the btap_results_hourly_data_8760 blob data from the osw file and save it
                # in the output folder
                if values["name"] == 'btap_results_hourly_data_8760'
                  model_osm_zip = values['value']
                  osm_string =  Zlib::Inflate.inflate(Base64.strict_decode64( model_osm_zip ))
                  FileUtils.mkdir_p("#{output_folder}/8760_files")
                  File.open("#{output_folder}/8760_files/#{uuid}-8760_hourly_data.csv", 'w+') {|f| f.write(osm_string) }
                  #puts "#{uuid}.osm ok"
                end

                # extract the btap_results_hourly_custom_8760 blob data from the osw file and save it
                # in the output folder
                if values["name"] == 'btap_results_hourly_custom_8760'
                  model_osm_zip = values['value']
                  osm_string =  Zlib::Inflate.inflate(Base64.strict_decode64( model_osm_zip ))
                  FileUtils.mkdir_p("#{output_folder}/8760_files")
                  File.open("#{output_folder}/8760_files/#{uuid}-8760_hour_custom.csv", 'w+') {|f| f.write(osm_string) }
                  #puts "#{uuid}.osm ok"
                end

                # extract the btap_results_monthly_7_day_24_hour_averages blob data from the osw file and save it
                # in the output folder
                if values["name"] == 'btap_results_monthly_7_day_24_hour_averages'
                  model_osm_zip = values['value']
                  osm_string =  Zlib::Inflate.inflate(Base64.strict_decode64( model_osm_zip ))
                  FileUtils.mkdir_p("#{output_folder}/8760_files")
                  File.open("#{output_folder}/8760_files/#{uuid}-mnth_24_hr_avg.csv", 'w+') {|f| f.write(osm_string) }
                  #puts "#{uuid}.osm ok"
                end

                # extract the btap_results_monthly_24_hour_weekend_weekday_averages blob data from the 
                #osw file and save it in the output folder
                if values["name"] == 'btap_results_monthly_24_hour_weekend_weekday_averages'
                  model_osm_zip = values['value']
                  osm_string =  Zlib::Inflate.inflate(Base64.strict_decode64( model_osm_zip ))
                  FileUtils.mkdir_p("#{output_folder}/8760_files")
                  File.open("#{output_folder}/8760_files/#{uuid}-mnth_weekend_weekday.csv", 'w+') {|f| f.write(osm_string) }
                  #puts "#{uuid}.osm ok"
                end

                # extract the btap_results_enduse_total_24_hour_weekend_weekday_averages blob data 
                # from the osw file and save it in the output folder
                if values["name"] == 'btap_results_enduse_total_24_hour_weekend_weekday_averages'
                  model_osm_zip = values['value']
                  osm_string =  Zlib::Inflate.inflate(Base64.strict_decode64( model_osm_zip ))
                  FileUtils.mkdir_p("#{output_folder}/8760_files")
                  File.open("#{output_folder}/8760_files/#{uuid}-endusetotal.csv", 'w+') {|f| f.write(osm_string) }
                  #puts "#{uuid}.osm ok"
                end


                # extract the qaqc json blob data from the osw file and save it
                # in the output folder
                if values["name"] == 'btap_results_json_zip'
                  found_json = true
                  btap_results_json_zip = values['value']
                  json_string =  Zlib::Inflate.inflate(Base64.strict_decode64( btap_results_json_zip ))
                  json = JSON.parse(json_string)
                  # indicate if the current model is a baseline run or not
                  json['is_baseline'] = "#{flags[:baseline]}"

                  #add ECM data to the json file
                  measure_data = []
                  results['steps'].each_with_index do |measure, index|
                    step = {}
                    measure_data << step
                    step['name'] = measure['name']
                    step['arguments'] = measure['arguments']
                    if measure.has_key?('result')
                      step['display_name'] = measure['result']['measure_display_name']
                      step['measure_class_name'] = measure['result']['measure_class_name']
                    end
                    step['index'] = index
                    # measure is an ecm if it starts with ecm_ (case ignored)
                    step['is_ecm'] = !(measure['name'] =~ /^ecm_/i).nil? # returns true if measure name starts with 'ecm_' (case ignored)
                  end

                  json['measures'] = measure_data

                  FileUtils.mkdir_p("#{output_folder}/qaqc_files")
                  File.open("#{output_folder}/qaqc_files/#{uuid}.json", 'wb') {|f| f.write(JSON.pretty_generate(json)) }

                  # append qaqc data to simulations.json
                  process_simulation_json(json,simulations_json_folder, uuid)
                  puts "#{uuid}.json ok"
                end # values["name"] == 'btap_results_json_zip'
              end
            end # if measure["name"] == "btapresults" && measure.include?("result")
          end # of grab step files
        end # unless completed_dps.has_key?(dp[:_id])
      } # Parallel.map(comp_datapoint_list, in_threads: 20)

      total_dps = @server_api.get_datapoint_status(@analysis_id).length
      puts "download_count: #{download_count}       total_dps: #{total_dps}".cyan
      downloaded_all = true if download_count >= total_dps
      sleep 1
    end #while !downloaded_all
    completed[:zip] = true
    File.open("#{simulations_json_folder}/simulations.json", 'a'){|f| f.write("]")} unless File.zero?("#{simulations_json_folder}/simulations.json")

    # create an index file which maps the uuid to the simulations json index
    # this file also has a list of building_types and weather files
    if File.exists?("#{simulations_json_folder}/simulations.json") && !File.zero?("#{simulations_json_folder}/simulations.json")
      File.open("#{simulations_json_folder}/index_map.json", 'wb'){|f|
        sim = JSON.parse(File.read("#{simulations_json_folder}/simulations.json"))
        out = {}
        out["building_type"] = []
        out["cities"] = []
        out["id"] = {}
        out["datapoint"] = {}
        sim.each_with_index { |datapoint, i|
          out["id"]["#{datapoint['run_uuid']}"] = i
          out["building_type"] << datapoint['building_type']
          out["cities"] << datapoint['geography']['city']
          out["datapoint"]["#{datapoint['building_type']}"] = {} unless out["datapoint"].has_key?("#{datapoint['building_type']}")
          out["datapoint"]["#{datapoint['building_type']}"]["#{datapoint['geography']['city']}"] = [] unless out["datapoint"]["#{datapoint['building_type']}"].has_key?("#{datapoint['geography']['city']}")
          out["datapoint"]["#{datapoint['building_type']}"]["#{datapoint['geography']['city']}"] << "#{datapoint['run_uuid']}"
        }
        out["building_type"].uniq!
        out["cities"].uniq!
        f.write(JSON.pretty_generate(out))
      }
    end
  end


  while Time.now - submit_time < timeout
    server_status = @server_api.get_analysis_status(@analysis_id, analysis_type)
    if server_status == 'completed' || server_status == 'failed'
      begin
        puts 'INFO: ANALYSIS STATUS -- Analysis has completed. Attempting to execute queued tasks.' if server_status == 'completed'
        puts 'WARN: ANALYSIS STATUS -- Attempting to execute queued tasks on failed analysis.' if server_status == 'failed'
        # Download results and metadata rdataframe
        if flags[:download] && flags[:rdata]
          @server_api.download_dataframe(@analysis_id, 'rdata', download_dir) #results
          @server_api.download_variables(@analysis_id, 'rdata', download_dir) # metadata
          completed[:rdata] = true
          puts 'INFO: DOWNLOAD STATUS -- RDataFrames have been downloaded.'
        end

        # Download results and metadata csv
        if flags[:download] && flags[:csv]
          @server_api.download_dataframe(@analysis_id, 'csv', download_dir)
          @server_api.download_variables(@analysis_id, 'csv', download_dir)
          completed[:csv] = true
          puts 'INFO: DOWNLOAD STATUS -- CSVs have been downloaded.'
        end
        output_folder = "#{download_dir}/#{@analysis_id}"
        FileUtils.mkdir_p(output_folder)
        #downloads the analysis status.json file
        @server_api.download_datapoint_status(@analysis_id, output_folder)

        # Stop aws instance
        if flags[:stop]
          aws.stop
          completed[:stop] = true
        end

        # Kill aws instance
        if flags[:kill]
          aws.terminate
          completed[:kill] = true
        end
      rescue => e # Print error message
        puts "ERROR: QUEUED TASKS -- Queued tasks (downloads, stop, or kill) commands erred in #{__method__}".red
        puts "with #{e.message}, #{e.backtrace.join("\n")}".red
      ensure # Return exit status
        return completed
      end
    end
    sleep 1
  end
end
#parse the downloaded osw files and check if the datapoint failed or not
#if failed download the eplusout.err and sldp_log files for error logging
#
# @param results [:hash] contains content of the out.osw file
# @param output_folder [:string] root folder where the csv log needs to be created
# @param uuid [:string] uuid of the datapoint. used to download the sdp log file if the datapoint has failed
# @param failed_output_folder [:string] root folder of the sdp log files
def check_and_log_error(results,output_folder,uuid,failed_output_folder)
  if results['completed_status'] == "Fail"
    FileUtils.mkdir_p(failed_output_folder) # create failed_output_folder
    log_k, log_f = @server_api.get_log_file(@analysis_id, uuid, failed_output_folder)
    # log_k => Boolean which determines if the log file has been downloaded successfully
    # log_f => path of the downloaded log file

    #create the csv file if it does not exist
    # this csv file will contain the building information with the eplusout.err log and the sdp_error log
    File.open("#{output_folder}/failed_run_error_log.csv", 'w'){|f| f.write("") } unless File.exists?("#{output_folder}/FAIL.log.csv")

    # output the errors to the csv file
    CSV.open("#{output_folder}/failed_run_error_log.csv", 'a') do |f|
      results['steps'].each do |measure|
        next unless measure["name"] == "create_prototype_building"
        out = {}
        eplus = "" # stores the eplusout error file

        # check if the eplusout.err file was generated by the run
        if results.has_key?('eplusout_err')
          eplus = results['eplusout_err']
          # if eplusout.err file has a fatal error, only store the error,
          # if not entire file will be stored
          match = eplus.to_s.match(/\*\*  Fatal  \*\*.+/)
          eplus = match unless match.nil?
        else
          eplus = "EPlusout.err file not generated by osw"
        end

        log_content = ""
        # ckeck if the log file has been downloaded successfully.
        # if the log file has been downloaded successfully, then match the last ERROR
        if log_k
          log_file = File.read(log_f)
          log_match = log_file.scan(/((\[.{12,18}ERROR\]).+?)(?=\[.{12,23}\])/m)
          #puts "log_match #{log_match}\n\n".cyan
          log_content = log_match.last unless log_match.nil?
          #puts "log_match #{log_match}\n\n".cyan
        else
          log_content = "No Error log Found"
        end

        # write building_type, climate_zone, epw_file, template, uuid, eplusout.err
        # and error log content to the comma delimited file
        out = %W{#{measure['arguments']['building_type']} #{measure['arguments']['climate_zone']} #{measure['arguments']['epw_file']} #{measure['arguments']['template']} #{uuid} #{eplus} #{log_content}}
        # make the write process thread safe by locking the file while the file is written
        f.flock(File::LOCK_EX)
        f.puts out
        f.flock(File::LOCK_UN)
      end
    end #File.open("#{output_folder}/FAIL.log", 'a')
  end #results['completed_status'] == "Fail"
end

# This method will append qaqc data to simulations.json
#
# @param json [:hash] contains original qaqc json file of a datapoint
# @param simulations_json_folder [:string] root folder of the simulations.json file
def process_simulation_json(json,simulations_json_folder,uuid)
  #modify the qaqc json file to remove eplusout.err information,
  # and add separate building information and uuid key
  #json contains original qaqc json file on start
  if json.has_key?('eplusout_err')
    json['eplusout_err']['warnings'] = json['eplusout_err']['warnings'].size
    json['eplusout_err']['severe'] = json['eplusout_err']['severe'].size
    json['eplusout_err']['fatal'] = json['eplusout_err']['fatal'].size
  else
    File.open("#{simulations_json_folder}/missing_files.log", 'a') {|f| f.write("ERROR: Unable to find eplusout_err #{uuid}.json\n") }
  end
  json['run_uuid'] = uuid
  #puts "json['run_uuid'] #{json['run_uuid']}"
  bldg = json['building']['name'].split('-')
  json['building_type'] = bldg[1]
  json['template'] = bldg[0]

  #write the simulations.json file thread safe
  File.open("#{simulations_json_folder}/simulations.json", 'a'){|f|
    f.flock(File::LOCK_EX)
    # add a [ to the simulations.json file if it is being written for the first time
    # if not, then add a comma
    if File.zero?("#{simulations_json_folder}/simulations.json")
      f.write("[#{JSON.generate(json)}")
    else
      f.write(",#{JSON.generate(json)}")
    end
    f.flock(File::LOCK_UN)
  }
end


# Run tasks contingent on the completion of the analysis
#
# @param options [:hash]
# @param analysis_type [:aliased string]
# @return [logical] Indicates if any errors were caught
def queued_tasks(options, analysis_type)
  # Initialize variables for queue dependent actions
  submit_time = Time.now #change to submit time for analysis
  rdata_flag = options[:rdata]
  csv_flag = options[:csv]
  osw_flag = options[:download_osw]
  zip_flag = options[:zip]
  download_flag = false
  stop_flag = options[:stop]
  kill_flag = options[:kill]
  baseline_flag = options[:baseline]
  warnings = []
  start_wait = options[:start_wait]
  analysis_wait = options[:analysis_wait]
  analysis_type = 'batch_run' if OpenStudio::Analysis::ServerApi::BATCH_RUN_METHODS.include? analysis_type

  # Verify download directories and set flags to true should they exist
  if rdata_flag || csv_flag || zip_flag
    if !File.exist? options[:download_directory]
      puts "INFO: MKDIR -- Making new directory for download results at #{options[:download_directory]}"
      Dir.mkdir options[:download_directory]
      download_flag = true
    else
      download_flag = true
    end
  end

  # Hash commands for run_queued_tasks and warning messages
  flags = {download: download_flag, rdata: rdata_flag, csv: csv_flag, zip: zip_flag, stop: stop_flag, kill: kill_flag, baseline: baseline_flag}
  completed = {rdata: nil, csv: nil, zip: nil, stop: nil, kill: nil}

  # Execute queued tasks should they exist with a Timeout
  puts 'INFO: ANALYSIS STATUS -- Waiting for analysis to start.'
  while Time.now - submit_time < start_wait
    server_status = @server_api.get_analysis_status(@analysis_id, analysis_type)
    if server_status == 'started'
      puts 'INFO: ANALYSIS STATUS -- Analysis has started. Waiting for analysis to complete.'
      returned = run_queued_tasks(analysis_type, options[:download_directory], flags, analysis_wait)
      returned ||= {}
      completed.merge! returned
      break
    elsif server_status == 'failed'
      puts 'WARN: ANALYSIS STATUS -- The analysis status has transitioned to failed. Attempting to execute queued tasks.'
      returned = run_queued_tasks(analysis_type, options[:download_directory], flags, analysis_wait)
      completed.merge! returned
      break
    elsif server_status == 'completed'
      returned = run_queued_tasks(analysis_type, options[:download_directory], flags, analysis_wait)
      returned ||= {}
      completed.merge! returned
      break
    else
      sleep 1
    end
  end

  # Warn if flags were set to true but code not executed.
  if flags[:rdata]
    warnings << 'WARN: TIMEOUT -- RData results were not downloaded due to timeout' unless completed[:rdata]
  end

  if flags[:csv]
    warnings << 'WARN: TIMEOUT -- CSV results were not downloaded due to timeout' unless completed[:csv]
  end

  if flags[:zip]
    warnings << 'WARN: TIMEOUT -- Zipped files were not downloaded due to timeout' unless completed[:zip]
  end

  if flags[:stop]
    warnings << 'WARN: TIMEOUT -- Instance was not stopped due to timeout' unless completed[:stop]
  end

  if flags[:kill]
    warnings << 'WARN: TIMEOUT -- Instance was not killed due to timeout' unless completed[:kill]
  end

  warnings.join(". ") if warnings != []

end


# Initialize optionsParser ARGV hash
options = {}

# Define allowed ARGV input
# --analysis-wait [integer]
# --server-wait [integer]
# -t --target default 'vagrant'
# -d --download-directory [string] default "./#{@analysis_id}/"
# -p --project [string] no default
# -r --rdataframe
# -c --csv
# -z --zipfiles
# -o --override
# -b --baseline
optparse = OptionParser.new do |opts|
  opts.banner = 'Usage:    bundle exec ruby cli.rb [-t] <target/web-address> [-p] <project> [-d] <download> [-s] [-k] [-o] [-h] [-a] <analysis-id> [-b]'

  options[:target] = 'vagrant'
  opts.on( '-t', '--target <target_alias>', 'target OpenStudio-Server instance') do |server|
    options[:target] = server
  end

  options[:project] = nil
  opts.on('-p', '--project <file>', 'specified project FILE') do |project_file|
    options[:project] = project_file
  end

  options[:download_directory] = './analysis_results'
  opts.on('-d', '--download-directory <DIRECTORY>', 'specified DIRECTORY for downloading all result files') do |download_directory|
    options[:download_directory] = download_directory
  end

  options[:analysis_id_custom] = ''
  opts.on('-a', '--analysis-id <ANALYSIS_ID>', 'specified ANALYSIS_ID for downloading all result files') do |analysis_id_custom|
    options[:analysis_id_custom] = analysis_id_custom
  end

  options[:rdata] = false
  opts.on('-r', '--rdataframe', 'download rdataframe results and metadata files') do
    options[:rdata] = true
  end

  options[:csv] = false
  opts.on('-c', '--csv', 'download csv results and metadata files') do
    options[:csv] = true
  end

  options[:zip] = false
  opts.on('-z', '--zip', 'download zip files') do
    options[:zip] = true
  end

  options[:baseline] = false
  opts.on('-b', '--baseline', 'set current run as baseline') do
    options[:baseline] = true
  end

  options[:stop] = false
  opts.on('-s', '--stop', 'stop server once completed') do
    options[:stop] = true
  end

  options[:kill] = false
  opts.on('-k', '--kill', 'kill server once completed') do
    options[:kill] = true
  end

  options[:override_safety] = false
  opts.on('-o', '--override-safety', 'allow KILL without DOWNLOAD or allow server to not shutdown') do
    options[:override_safety] = true
  end

  options[:start_wait] = 1800
  opts.on('--server-wait <INTEGER>', 'seconds to wait for job to start before timeout (Default: 1800s)') do |start_wait|
    options[:start_wait] = start_wait.to_i
  end

  options[:analysis_wait] = 1800
  opts.on('--analysis-wait <INTEGER', 'seconds to wait for job to complete before timeout (Default: 1800s)') do |analysis_wait|
    options[:analysis_wait] = analysis_wait.to_i
  end

  opts.on_tail('-h', '--help', 'display help') do
    puts opts
    exit
  end
end

# Execute ARGV parsing into options hash holding sybolized key values
optparse.parse!

# Check validity of options selected
unless options[:override_safety]
  if options[:kill] && options[:stop]
    fail 'ERROR: ARGV IN -- Both -s and -k entered. Please specify one or the other'
  elsif options[:kill] && (!options[:csv] || !options[:zip] || !options[:rdata])
    fail 'ERROR: ARGV IN -- Override required to keep server spinning after project or to kill the server without downloading'
  end
end

if (options[:target].downcase != 'aws') && options[:kill]
  fail 'ERROR: ARGV IN -- Unable to kill non-aws server'
end

# Process project file and construct cluster options
unless File.exists?(options[:project])
  fail "ERROR: ARGV IN -- Could not find project file #{options[:project]}."
end

unless %w[.rb .xlsx .csv].include? File.extname(options[:project])
  fail 'ERROR: Project file did not have a valid extension (.rb, .csv, or .xlsx)'
end

begin
  # Create temporary folder for server inputs
  Dir.mkdir '.temp' unless File.exist?('.temp')
  temp_filepath = '.temp/analysis'
  # Process project file and retrieve cluster options
  if File.extname(options[:project]).downcase == '.xlsx'
    aws_instance_options = process_excel_project(options[:project], temp_filepath)
  elsif File.extname(options[:project]).downcase == '.rb'
    aws_instance_options = process_rb_project(options[:project], temp_filepath)
  elsif File.extname(options[:project]).downcase == '.csv'
    aws_instance_options = process_csv_project(options[:project], temp_filepath)
  else
    fail "Did not recognize project file extension #{File.extname(options[:project])}"
  end

  # Get OpenStudioServerApi object and ensure the instance is running
  @server_api = find_or_create_target(options[:target], aws_instance_options)

  unless @server_api.machine_status
    fail "ERROR: Target #{options[:target]} server at #{@server_api.hostname} not responding".red
  end

  # Run project on target server
  unless options[:analysis_id_custom] == ''
    @analysis_id = options[:analysis_id_custom]
  else
    @analysis_id = @server_api.run("#{temp_filepath}.json","#{temp_filepath}.zip",aws_instance_options[:analysis_type])
  end

ensure
  begin
    #Ensure resource cleanup
    FileUtils.rm_r '.temp'
  rescue
    puts 'Unable to delete the `.temp` directory. Continuing'.red
  end
end
puts "Current Run set as BASELINE: #{options[:baseline]}".cyan
# Determine if there are queued tasks
options[:rdata] || options[:csv] || options[:zip] || options[:stop] || options[:kill] ? tasks_queued = true : tasks_queued = false

# Check if queued tasks are set to run
erred = queued_tasks(options, aws_instance_options[:analysis_type]) if tasks_queued
erred ||= nil

# Non-zero exit if errors in queued_tasks
fail erred if erred

# Puts completed
puts 'STATUS: COMPLETE'
