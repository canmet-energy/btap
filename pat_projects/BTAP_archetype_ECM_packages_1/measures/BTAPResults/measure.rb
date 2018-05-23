require 'erb'
require 'json'
require 'zlib'
require 'base64'
require 'csv'
require 'date'
require 'time'

require "#{File.dirname(__FILE__)}/resources/os_lib_reporting"
require "#{File.dirname(__FILE__)}/resources/os_lib_schedules"
require "#{File.dirname(__FILE__)}/resources/os_lib_helper_methods"

module Enumerable
  def sum
    self.inject(0){|accum, i| accum + i }
  end

  def mean
    self.sum/self.length.to_f
  end

  def sample_variance
    m = self.mean
    sum = self.inject(0){|accum, i| accum +(i-m)**2 }
    sum/(self.length - 1).to_f
  end

  def standard_deviation
    return Math.sqrt(self.sample_variance)
  end
end

# Method for sig figs, from stackoverflow
class Float
  def signif(signs)
    Float("%.#{signs}g" % self)
  end
end


#padmassun's *TODO LIST*
#need <Lighting Adjustment Applied (0.9)>
#need information about  <Jan 2.5 Design Temp> to complete <HRV Calc> for each space type
#padmassun's comment end

# start the measure
class BTAPResults < OpenStudio::Ruleset::ReportingUserScript
  # define the name that a user will see, this method may be deprecated as
  # the display name in PAT comes from the name field in measure.xml
  def name
    'BTAP Results'
  end

  # human readable description
  def description
    'This measure creates BTAP result values used for NRCan analyses.'
  end

  # human readable description of modeling approach
  def modeler_description
    'Grabs data from OS model and sql database and keeps them in the '
  end

  def validate_optional (var, model, return_value = "N/A")
    if var.empty?
      return return_value
    else
      return var.get
    end
  end
  

  # define the arguments that the user will input
  def arguments ()
    args = OpenStudio::Ruleset::OSArgumentVector.new
    generate_hourly_report = OpenStudio::Ruleset::OSArgument::makeStringArgument('generate_hourly_report', false)
    generate_hourly_report.setDisplayName('Generate Hourly Report.')
    generate_hourly_report.setDefaultValue('false')
    args << generate_hourly_report
    return args
  end # end the arguments method


  def store_data(runner, value, name, units)

    name = name.to_s.downcase.tr(" ","_")
    runner.registerValue(name.to_s,value.to_s)

    #runner.registerError(" Error is RegisterValue for these arguments #{name}, value:#{value}, units:#{units} in runner #{runner}")

  end
  
  def look_up_csv_data(csv_fname, search_criteria)
    options = { :headers    => :first_row,
      :converters => [ :numeric ] }
    unless File.exist?(csv_fname)
      raise ("File: [#{csv_fname}] Does not exist")
    end
    # we'll save the matches here
    matches = nil
    # save a copy of the headers
    headers = nil
    CSV.open( csv_fname, "r", options ) do |csv|

      # Since CSV includes Enumerable we can use 'find_all'
      # which will return all the elements of the Enumerble for 
      # which the block returns true

      matches = csv.find_all do |row|
        match = true
        search_criteria.keys.each do |key|
          match = match && ( row[key].strip == search_criteria[key].strip )
        end
        match
      end
      headers = csv.headers
    end
    #puts matches
    raise("More than one match") if matches.size > 1
    puts "Zero matches found for [#{search_criteria}]" if matches.size == 0
    #return matches[0]
    return matches[0]
  end


  def necb_section_test(qaqc,result_value,bool_operator,expected_value,necb_section_name,test_text,tolerance = nil)
    test = "eval_failed"
    command = ''
    if tolerance.is_a?(Integer)
      command = "#{result_value}.round(#{tolerance}) #{bool_operator} #{expected_value}.round(#{tolerance})"
    elsif expected_value.is_a?(String) and result_value.is_a?(String)
      command = "'#{result_value}' #{bool_operator} '#{expected_value}'"
    else
      command = "#{result_value} #{bool_operator} #{expected_value}"
    end
    test = eval(command)
    test == 'true' ? true :false
    raise ("Eval command failed #{test}") if !!test != test 
    if test
      qaqc[:information] << "[Info][TEST-PASS][#{necb_section_name}]:#{test_text} result value:#{result_value} #{bool_operator} expected value:#{expected_value}"
    else
      qaqc[:errors] << "[ERROR][TEST-FAIL][#{necb_section_name}]:#{test_text} expected value:#{expected_value} #{bool_operator} result value:#{result_value}"
      unless (expected_value == -1.0 or expected_value == 'N/A')
        qaqc[:unique_errors] << "[ERROR][TEST-FAIL][#{necb_section_name}]:#{test_text} expected value:#{expected_value} #{bool_operator} result value:#{result_value}"
      end
    end
  end
  

  
  def runHourlyReports(runner, user_arguments)
    #super(runner, user_arguments)
    @json_data = {}
    @json_data["hourly_data"] = []
    @kvdata = {}

    # use the built-in error checking 
    if !runner.validateUserArguments(arguments(), user_arguments)
      return false
    end
    
    # get the last model and sql file
    #puts "#{Time.new} Loading model"
    model = runner.lastOpenStudioModel
    if model.empty?
      runner.registerError("Cannot find last model.")
      return false
    end
    model = model.get

    #puts "#{Time.new} Loading sql file"
    sql = runner.lastEnergyPlusSqlFile
    if sql.empty?
      runner.registerError("Cannot find last sql file.")
      return false
    end
    sql = sql.get
    model.setSqlFile(sql)

    time_of_peaks = sql.execAndReturnVectorOfString("SELECT Value FROM tabulardatawithstrings WHERE ReportName='DemandEndUseComponentsSummary'" +
        " AND ReportForString='Entire Facility' AND TableName='End Uses' AND RowName='Time of Peak'").get
    
    meters = sql.execAndReturnVectorOfString("SELECT ColumnName FROM tabulardatawithstrings WHERE ReportName='DemandEndUseComponentsSummary'" +
        " AND ReportForString='Entire Facility' AND TableName='End Uses' AND RowName='Time of Peak'").get
    
    units = sql.execAndReturnVectorOfString("SELECT Units FROM tabulardatawithstrings WHERE ReportName='DemandEndUseComponentsSummary'" +
        " AND ReportForString='Entire Facility' AND TableName='End Uses' AND RowName='Time of Peak'").get
      
    values = sql.execAndReturnVectorOfString("SELECT Value FROM tabulardatawithstrings WHERE ReportName='DemandEndUseComponentsSummary'" +
        " AND ReportForString='Entire Facility' AND TableName='End Uses' AND RowName='Total End Uses'").get
      
    if time_of_peaks.empty? || meters.empty? || units.empty? || values.empty? 
      runner.registerError("Could not get peak dates from sql file.")
    end
    annual_peaks = []
    meters.each_with_index do |meter, i|
      peak = {'meter'=>meter, 'day_of_peak'=>time_of_peaks[i], 'value'=>values[i], 'unit'=>units[i] }
      annual_peaks << peak
    end


    # Get the weather file run period (as opposed to design day run period)
    ann_env_pd = nil
    sql.availableEnvPeriods.each do |env_pd|
      env_type = sql.environmentType(env_pd)
      if env_type.is_initialized
        if env_type.get == OpenStudio::EnvironmentType.new("WeatherRunPeriod")
          ann_env_pd = env_pd
        end
      end
    end

    if ann_env_pd.nil?
      runner.registerAsNotApplicable("Can't find a weather runperiod, make sure you ran an annual simulation, not just the design days.")
      return true
    end
    
    # Get the timestep as fraction of an hour
    ts_frac = 1.0/4.0 # E+ default
    sim_ctrl = model.getSimulationControl
    step = sim_ctrl.timestep
    if step.is_initialized
      step = step.get
      steps_per_hr = step.numberOfTimestepsPerHour
      ts_frac = 1.0/steps_per_hr.to_f
    end
    #runner.registerInfo("The timestep is #{ts_frac} of an hour.")
    
    # Determine the number of hours simulated
    hrs_sim = sql.hoursSimulated
    if hrs_sim.is_initialized
      hrs_sim = hrs_sim.get
    else
      runner.registerWarning("Could not determine number of hours simulated, assuming 8760")
      hrs_sim = 8760
    end
    
    # Save simuated hours to hash
    
    @json_data['hourly_data'] << {'simulated_hours'=>hrs_sim }
    

    # Get all valid timeseries
    #puts "#{Time.new} Getting all valid timeseries"
    kvs = sql.execAndReturnVectorOfString('SELECT KeyValue FROM ReportDataDictionary')
    var_names = sql.execAndReturnVectorOfString('SELECT Name FROM ReportDataDictionary')
    freqs = sql.execAndReturnVectorOfString('SELECT ReportingFrequency FROM ReportDataDictionary')
    unitss = sql.execAndReturnVectorOfString('SELECT Units FROM ReportDataDictionary')
    variable_types = sql.execAndReturnVectorOfString('SELECT Type FROM ReportDataDictionary')
    index_groups = sql.execAndReturnVectorOfString('SELECT IndexGroup FROM ReportDataDictionary')
    rt_data_dictionarys = sql.execAndReturnVectorOfString('SELECT ReportDataDictionaryIndex FROM ReportDataDictionary')
    is_meters = sql.execAndReturnVectorOfString('SELECT IsMeter FROM ReportDataDictionary')
    if kvs.empty? || var_names.empty? || freqs.empty? || unitss.empty?
      runner.registerError("Could not get timeseries data from sql file.")
    end
    
    kvs = kvs.get
    var_names = var_names.get
    freqs = freqs.get
    unitss = unitss.get
    variable_types = variable_types.get
    index_groups = index_groups.get
    rt_data_dictionarys = rt_data_dictionarys.get
    is_meters = is_meters.get
    runner.registerInitialCondition("Found #{kvs.size} timeseries outputs.")  
    #Create container for all data records. 
    data_record_array = []
    #iterate through each data record. 
    kvs.each_with_index do |kv, i|
      freq = freqs[i]
      var_name = var_names[i]
      kv = kvs[i]
      units = unitss[i]
      variable_type = variable_types[i]
      index_group = index_groups[i]
      rt_data_dictionary = rt_data_dictionarys[i]
      is_meter = is_meters[i] 

      # For now, only collect hourly and subhourly data. 
      next unless ['HVAC System Timestep','Zone Timestep', 'Timestep','Hourly'].include?(freq)
      # Series frequency in hrs
      ts_hr = nil
      case freq
      when 'HVAC System Timestep'
        ts_hr = (1.0 / 60.0) # Convert from non-uniform to minutely
      when 'Timestep', 'Zone Timestep'
        ts_hr = ts_frac
      when 'Hourly'
        ts_hr = 1.0
      when 'Daily'
        ts_hr = 24.0
      when 'Monthly'
        ts_hr = ( 24.0 * 30 )# Even months
      when 'Runperiod'
        ts_hr = ( 24.0 * 365 )# Assume whole year run
      end

      # Get the values
      ts = sql.timeSeries(ann_env_pd, freq, var_name, kv)
      if ts.empty?
        runner.registerWarning("No data found for #{freq} #{var_name} #{kv}.")
        next
      else
        runner.registerInfo("Found data for #{freq} #{var_name} #{kv}.")
        ts = ts.get
      end
      #Get date and time for values
      date_times = ts.dateTimes
      #Store simulation year. 
      @simulation_year = Time.parse(date_times[0].to_s).year
      #store data values
      @runner.registerInfo("Total Time = #{(Time.new - @start_time).round}sec.")

      
      vals = ts.values

      # If this series is a mass or volume flow rate, determine
      # the type of loop the component is on (air or water)
      # for later unit conversion.
      on_plant_loop = false
      on_air_loop = false
      if ['m3/s','kg/s'].include?(units.downcase)
        model.getPlantLoops.each do |plant_loop|
          if plant_loop.name.get.to_s.upcase == kv.upcase
            on_plant_loop = true
            break
          end
          plant_loop.components.each do |comp|
            if comp.name.get.to_s.upcase == kv.upcase
              on_plant_loop = true
              break
            end
          end
        end
        # If not on plant loop, check air loops
        unless on_plant_loop
          model.getAirLoopHVACs.each do |air_loop|
            if air_loop.name.get.to_s.upcase == kv.upcase
              on_air_loop = true
              break
            end
            air_loop.components.each do |comp|
              if comp.name.get.to_s.upcase == kv.upcase
                on_air_loop = true
                break
              end
            end
          end
        end
      end

      # For HVAC System Timestep data, convert from E+ 
      # non-uniform timesteps to minutely with missing
      # entries linearly interpolated.
      if freq == 'HVAC System Timestep'
        # Loop through each of the non-uniformly
        # reported timesteps.
        start_min = 0
        first_timestep = date_times[0]
        minutely_vals = []
        for i in 1..(date_times.size - 1)
          reported_time = date_times[i]
          # Figure out how many minutes to the
          # it's been since the previous reported timestep.
          min_until_prev_ts = 0
          for min in start_min..525600
            minute_ts = OpenStudio::Time.new(0, 0, min, 0) # d, hr, min, s
            minute_time = first_timestep + minute_ts
            if minute_time == reported_time
              break
            elsif minute_time < reported_time
              min_until_prev_ts += 1
            else 
              # minute_time > reported_time
              # This scenario shouldn't happen
              runner.registerError("Somehow a timestep was skipped when converting from HVAC System Timestep to uniform minutely.  Results will not look correct.")
            end
          end          
          
          # Get this value
          this_val = vals[i]
          
          # Get the previous value
          prev_val = vals[i-1]
          
          # Linearly interpolate the values between
          val_per_min = (this_val - prev_val)/min_until_prev_ts

          # At each minute, report a value if one
          # exists and a blank if none exists.
          for min in start_min..525600
            minute_ts = OpenStudio::Time.new(0, 0, min, 0) # d, hr, min, s
            minute_time = first_timestep + minute_ts
            if minute_time == reported_time
              # There was a value for this minute,
              # report out this value and skip
              # to the next reported timestep
              start_min = min + 1
              minutely_vals << this_val
              #puts "#{minute_time} = #{this_val}"
              break
            elsif minute_time < reported_time
              # There wasn't a value for this minute,
              # report out a blank entry
              minutely_vals << prev_val + (val_per_min * (min - start_min + 1))
              #puts "#{minute_time} = #{prev_val + (val_per_min * (min - start_min + 1))} interp, mins = #{min - start_min + 1} val_per_min = #{val_per_min}, min_until_prev_ts = #{min_until_prev_ts}"
            else 
              # minute_time > reported_time
              # This scenario shouldn't happen
              runner.registerError("Somehow a timestep was skipped when converting from HVAC System Timestep to uniform minutely.  Results will not look correct.")
            end
          end
          
        end
        
        #puts "---- #{Time.new} Done nonuniform timestep interpolation"
        
        # Replace the original values
        # with the new minutely values
        #puts "minutely has #{minutely_vals.size} entries"
        vals = minutely_vals
      end

      # Convert the values to a normal array
      #puts "---- #{Time.new} Starting conversion to normal array" 
      data = []
      if freq == 'HVAC System Timestep'
        # Already normal array
        data = vals
      else
        for i in 0..(vals.size - 1)
          #next if vals[i].nil?
          data[i] = vals[i].signif(5)
        end
      end
      
      #Don't Create Hourly data if Hourly data already exists.
      #create Storage Array
      hourly_data = []
      if sql.timeSeries(ann_env_pd, 'Hourly', var_name, kv).empty?
        #Averaged versus Summed

        #Determine ts per hour
        timesteps_per_hour = 1/ts_hr
        #set Counter
        counter = 0
        # Set last hour uding the number of simulaiton hours minus 1. For a full year 
        # this is 8760-1. So the iterator will go from 0 to 8759. 
        last_hour =hrs_sim.to_i - 1
        (0..last_hour).each do |hour|
          #Start and stop 'chunk' that makes up an hour. 
          start = counter
          stop= counter + timesteps_per_hour.to_i - 1
          result = 0
          #iterate through the hour. 
          (start..stop).each do |value|
            #Either sum or average over the hour based on the type. 
            unless data[value].nil?
              if variable_type == "Sum"
                result += data[value] 
              elsif variable_type == "Avg"
                result += data[value] / timesteps_per_hour
              end
            end
          end
          #Increament the counter to start the next hour 'chunk'
          counter = stop + 1
          #store the data into an array. 
          hourly_data << result
        end
      else
        vals = sql.timeSeries(ann_env_pd, 'Hourly', var_name, kv).get.values
        for i in 0..(vals.size - 1)
          #next if vals[i].nil?
          hourly_data << vals[i].signif(5)
        end
      end
      
      #Get Annual PLR based not on Capacity, but on Min and Max Not total Capacity! 
      min_max_ratio = {}
      max = hourly_data.max
      (1..10).each { |bin| min_max_ratio["#{(bin-1)*10}-#{(bin*10)}%"] = 0 }
      #iterate through each hour and bin the information based on 10th percentages.  
      hourly_data.each do |data|
        #Get rid of any 
        if max.to_f != 0.0
          percentage = (100.0 * data.to_f/max.to_f).round
        else
          percentage = 0
        end
        case percentage
        when 0..10    then min_max_ratio['0-10%']   += 1
        when 11..20   then min_max_ratio['10-20%']  += 1
        when 21..30   then min_max_ratio['20-30%']  += 1
        when 31..40   then min_max_ratio['30-40%']  += 1
        when 41..50   then min_max_ratio['40-50%']  += 1
        when 51..60   then min_max_ratio['50-60%']  += 1
        when 61..70   then min_max_ratio['60-70%']  += 1
        when 71..80   then min_max_ratio['70-80%']  += 1
        when 81..90   then min_max_ratio['80-90%']  += 1
        when 91..100  then min_max_ratio['90-100%'] += 1
        end
      end
      
      
      
      
      
      
      
      #Get Monthly 24 day bins
      #Create hourly time array. 
      #start and end dates of simulation.
      date = DateTime.new(Time.parse(date_times.first.to_s).year,Time.parse(date_times.first.to_s).month, Time.parse(date_times.first.to_s).day)
      end_date = DateTime.new(Time.parse(date_times.last.to_s).year,Time.parse(date_times.last.to_s).month, Time.parse(date_times.last.to_s).day)
      counter = 0 
      monthly_24_hour_averages = []
      monthly_24_hour_weekend_weekday_averages = []
      month_array= []
      while ( date < end_date )
        month_array[date.month] = {} if month_array[date.month].nil?
        month_array[date.month][date.wday] = {} if month_array[date.month][date.wday].nil?
        month_array[date.month]['weekday'] = {} if month_array[date.month]['weekday'].nil?
        month_array[date.month]['weekend'] = {} if month_array[date.month]['weekend'].nil?
        month_array[date.month][date.wday][date.hour] = [] if month_array[date.month][date.wday][date.hour].nil?
        #create also weekday and weekend bins. 
        month_array[date.month]['weekday'][date.hour] = [] if month_array[date.month]['weekday'][date.hour].nil?
        month_array[date.month]['weekend'][date.hour] = [] if month_array[date.month]['weekend'][date.hour].nil?
        #push all hours values over the month for hour for the day type to an array. 
        #So this array will contain all the value for Monday at 1pm for example.
        # Keeping to 6 sig digits.
        month_array[date.month][date.wday][date.hour] << hourly_data[counter].to_f.signif(6) 
        
        #Set weekday and end bins. 
        if date.wday == 0 or date.wday == 6
          month_array[date.month]['weekend'][date.hour] << hourly_data[counter].to_f.signif(6) 
        elsif ( 1 .. 5 ).include?(date.wday)
          month_array[date.month]['weekday'][date.hour] << hourly_data[counter].to_f.signif(6)  
        end
        #puts "#{date.strftime('%^b')},#{date.strftime('%^a')},#{date.hour}"
        date += Rational( 3600, 86400 ) ; counter += 1
      end
      
      
      #keep month numbers from 1 to 12 to avoid confusion. 
      (1..12).each_with_index do |imonth|
        #do weekdays
        (0 .. 6).each do |day|
          day_hash = {"month"=>imonth, 'wday'=>day, 'mean_profile'=>[], 'std_dev_profile'=>[] }
          #Stick to 24 clock standard 0-23 hours. 
          (0 .. 23).each do |hour|
            #This will deal with partial year simulations if needed. 
            unless month_array[imonth].nil? or month_array[imonth][day].nil? or month_array[imonth][day][hour].nil?
              day_hash["mean_profile"] << month_array[imonth][day][hour].mean
              day_hash["std_dev_profile"] << month_array[imonth][day][hour].standard_deviation
            end
          end
          monthly_24_hour_averages << day_hash
        end
      end
      
      #keep month numbers from 1 to 12 to avoid confusion. 
      (1..12).each_with_index do |imonth|
        #do weekdays
        ['weekday','weekend'].each do |day|
          day_hash = {"month"=>imonth, 'wday'=>day, 'mean_profile'=>[], 'std_dev_profile'=>[] }
          #Stick to 24 clock standard 0-23 hours. 
          (0 .. 23).each do |hour|
            #This will deal with partial year simulations if needed. 
            unless month_array[imonth].nil? or month_array[imonth][day].nil? or month_array[imonth][day][hour].nil?
              day_hash["mean_profile"] << month_array[imonth][day][hour].mean
              day_hash["std_dev_profile"] << month_array[imonth][day][hour].standard_deviation
            end
          end
          monthly_24_hour_weekend_weekday_averages << day_hash
        end
      end
      

      raise("Hourly data is #{hourly_data.size} does not match the hours simulated which is #{hrs_sim} at a freq of #{freq}") if hourly_data.size != hrs_sim 
      #KV name may be blank...add "site" if blank and use that. 
      kv = 'site' if kv==''
      
      #Store all the data in a lovely hash. 
      record = {   
        'rt_data_dictionary' => rt_data_dictionary,
        'var_name' => var_name,
        'kv' => kv,
        'units' => units,
        'variable_type' => variable_type,
        'index_group' => index_group,
        'is_meter' => is_meter,
        'reporting_frequency' => freq,
        'hours_simulated'=>hrs_sim,
        'total_num_data_points' => hrs_sim / ts_hr,
        'total_num_actual_data_points'=>data.size,
        'total_num_actual_hourly_data_points'=>hourly_data.size,
        'data_points_per_hour' => (1.0 / ts_hr.to_f),
        'start_date_time' =>Time.parse(date_times.first.to_s),
        'end_date_time'=>Time.parse(date_times.last.to_s),
        'min_hourly_value'=>hourly_data.min,
        'max_hourly_value'=>hourly_data.max,
        'min_max_hourly_breakdown'=>min_max_ratio,
        'monthly_7_day_24_hour_averages'=>monthly_24_hour_averages,
        'monthly_24_hour_weekend_weekday_averages'=>monthly_24_hour_weekend_weekday_averages,
        'annual_peaks'=>annual_peaks,
        'data_hvac_system_filtered'=> data,
        'data_hourly_adjusted'=>hourly_data 
      }
      data_record_array << record

    end #End Data record loops. 
    write_to_monthly_average_week_csv(data_record_array)
    write_to_8760_hour_csv(data_record_array) 
    write_to_8760_hour_csv_all(data_record_array)
    monthly_24_hour_weekend_weekday_averages_csv(data_record_array)
    enduse_total_monthly_24_hour_weekend_weekday_averages_csv(data_record_array)
    return true
  end# end run
  
  
  def write_to_8760_hour_csv(data_record_array)
    selection = [
      'Heating Coil Air Heating Rate',
      'Cooling Coil Total Cooling Rate',
      'Boiler Heating Rate',
      'Chiller Condenser Heat Transfer Rate',
      'Water Heater Heating Rate',
      'Facility Total Electric Demand Power',
      'Gas:Facility',
      'Water Heater Gas Rate']
    selection = data_record_array.select {|record| selection.include?(record["var_name"])}
    CSV.open( '8760_hourly_data.csv', 'w' ) do |writer|
      row = []
      row << 'var_name' << 'key_variable' << 'units' << 'hours_simulated'
      row += (0..8760).to_a
      writer << row
      selection.each do |r|
        row = []
        row << r['var_name'] << r['kv'] << r['units'] <<  r['hours_simulated']
        row += r['data_hourly_adjusted'] 
        writer << row
      end
    end
  end


  def write_to_8760_hour_csv_all(data_record_array)
  selection = [
    "Total Internal Radiant Heating Rate",
    "Total Internal Convective Heating Rate",
    "Zone Air Heat Balance Outdoor Air Transfer Rate",
    "Zone Total Internal Latent Gain Rate",
    "Zone Total Internal Total Heating Rate",
    "Zone Air System Sensible Heating Rate",
    "Zone Air System Sensible Cooling Rate"
    ]
    selection = data_record_array.select {|record| selection.include?(record["var_name"])}
    CSV.open( '8760_hour_custom.csv', 'w' ) do |writer|
      row = []
      row << 'var_name' << 'key_variable' << 'units' << 'hours_simulated'
      row += (1..8760).to_a
      writer << row

      day = []
      day << 'Day of week:' << '' << '' << ''

      month = []
      month << 'Month:' << '' << '' << ''

      hour = []
      hour << 'hour:' << '' << '' << ''

      week = []
      week << 'Week #:' << '' << '' << ''

      full_date = []
      full_date << 'Full Date:' << '' << '' << ''
      
      puts selection[0]['start_date_time']
      start_date_time = selection[0]['start_date_time']
      end_date_time = selection[0]['end_date_time']

      date = DateTime.new(start_date_time.year,start_date_time.month, start_date_time.day)
      end_date = DateTime.new(end_date_time.year,end_date_time.month, end_date_time.day)
      # create the header (time and date information)
      while ( date < end_date )
        #puts "#{date.strftime('%^b')},#{date.strftime('%^d')},#{date.strftime('%^a')},#{date.hour}"
        day << "#{date.strftime('%^w')}" #Day of the week (Sunday is 0, 0 to 6).
        month << "#{date.strftime('%^b')}" #The abbreviated month name (Jan).
        week << "#{date.strftime('%^U')}" #Week number of the current year, starting with the first Sunday as the first day of the first week (00 to 53).
        hour << "#{date.strftime('%^H')}" #Hour of the day, 24-hour clock (00 to 23).
        full_date << "#{date.strftime('%^Y-%^m-%^d %^H:%^M:%^S')}"
        date += Rational( 3600, 86400 ) 
        
      end
      # write the header information
      writer << full_date
      writer << month
      writer << week
      writer << day
      writer << hour

      #write the hourly data to the csv file.
      selection.each do |r|
        row = []
        row << r['var_name'] << r['kv'] << r['units'] <<  r['hours_simulated']
        row += r['data_hourly_adjusted'] 
        writer << row
      end
    end
  end    
  
  def write_to_monthly_average_week_csv(data_record_array)
    selection = [
      'Heating Coil Air Heating Rate',
      'Cooling Coil Total Cooling Rate',
      'Boiler Heating Rate',
      'Chiller Condenser Heat Transfer Rate',
      'Water Heater Heating Rate',
      'Facility Total Electric Demand Power',
      'Gas:Facility',
      'Water Heater Gas Rate']
    selection = data_record_array.select {|record| selection.include?(record["var_name"])}
    CSV.open( 'monthly_7_day_24_hour_averages.csv', 'w' ) do |writer|
      row = []
      row << 'var_name' << 'key_variable' << 'units' << 'month' <<  'day_of_week' << "Data Type"
      row += (0..23).to_a
      writer << row
      selection.each do |r|
        r['monthly_7_day_24_hour_averages'].each do |m|
          #Write average 24 hour profile for day of the week m['day'] for each month.  
          row = []
          row << r['var_name'] << r['kv'] << r['units'] << m['month'] <<  m['wday'] << "MEAN"
          row += m['mean_profile']
          writer << row
          row = []
          row << r['var_name'] << r['kv'] << r['units'] << m['month'] <<  m['wday'] << "STD_DEV"
          row += m['std_dev_profile']
          writer << row
        end
      end
    end
  end
  
  
  def monthly_24_hour_weekend_weekday_averages_csv(data_record_array)
    selection = [
      'Heating Coil Air Heating Rate',
      'Cooling Coil Total Cooling Rate',
      'Boiler Heating Rate',
      'Chiller Condenser Heat Transfer Rate',
      'Water Heater Heating Rate',
      'Facility Total Electric Demand Power',
      'Gas:Facility',
      'Water Heater Gas Rate']
    selection = data_record_array.select {|record| selection.include?(record["var_name"])}
    CSV.open( 'monthly_24_hour_weekend_weekday_averages.csv', 'w' ) do |writer|
      row = []
      row << 'var_name' << 'key_variable' << 'units' << 'month' <<  'day_of_week' << "Data Type"
      row += (0..23).to_a
      writer << row
      selection.each do |r|
        r['monthly_24_hour_weekend_weekday_averages'].each do |m|
          #Write average 24 hour profile for day of the week m['day'] for each month.  
          row = []
          row << r['var_name'] << r['kv'] << r['units'] << m['month'] <<  m['wday'] << "MEAN"
          row += m['mean_profile']
          writer << row
          row = []
          row << r['var_name'] << r['kv'] << r['units'] << m['month'] <<  m['wday'] << "STD_DEV"
          row += m['std_dev_profile']
          writer << row
        end
      end
    end
  end

  def enduse_total_monthly_24_hour_weekend_weekday_averages_csv(data_record_array)
    sum_key = "monthly_24_hour_weekend_weekday_averages"
    total_data_record_array = []
    end_uses_lookup = {
      "SHW" => ['Water Heater Heating Rate'],
      "Space Heating" => ['Heating Coil Air Heating Rate', 'Boiler Heating Rate'],
      "Total Heating" => ['Heating Coil Air Heating Rate', 'Boiler Heating Rate','Water Heater Heating Rate'],
      "Space Cooling" => ['Cooling Coil Total Cooling Rate'],
      "Total Electricity" => ['Facility Total Electric Demand Power'],
      "Gas" => ['Gas:Facility'],
      "Total Site Energy" => ['Facility Total Electric Demand Power', 'Gas:Facility']
    }

    #File.open("end_uses_lookup.json", 'w') {|f| f.write(JSON.pretty_generate(end_uses_lookup)) }
    #File.open("data_record_array.json", 'w') {|f| f.write(JSON.pretty_generate(data_record_array)) }
    end_uses_lookup.keys.each{ |key|
      #puts "#{end_uses_lookup[key]}"
      data_groups = []
      data_record_array.each{ |item|
      #puts "\t#{item["var_name"]}"
        # only consider values that have an hourly timestamp to avoid duplicate variables with different 
        # time stamp values
        if end_uses_lookup[key].include?(item["var_name"]) && item["reporting_frequency"] == "Hourly"
          puts "#{item['var_name']}: Units: #{item['units']}"
          # convert Joules to Watts (Specific to Gas:Facility)
          if item['var_name'] == "Gas:Facility" && item['units'] == "J" && item["reporting_frequency"] == "Hourly"
            # perform deep copy to avoid changes in the original variable
            new_item = Marshal.load(Marshal.dump(item))
            new_item['units'] = "W"
            new_item[sum_key].each{|data_month|
              data_month['mean_profile'].map!{ |i| i/3600 }
            } 
            puts "^^#{new_item['var_name']}: Units: #{new_item['units']}^^"
            data_groups << Marshal.load(Marshal.dump(new_item))
            next
          end
          
          data_groups << Marshal.load(Marshal.dump(item))
        end
      }
      File.open("#{key}.json", 'w') {|f| f.write(JSON.pretty_generate(data_groups)) }
      if (data_groups[0].nil?)
        puts "end_uses_lookup[key] of #{end_uses_lookup[key]} was not found"
        next
      end
      # perform deep copy to avoid changes in the original variable
      out = Marshal.load(Marshal.dump(data_groups[0]))


      out["var_name"] = key
      out["kv"] = "TOTAL"
      data_groups.each_with_index{|data_set, data_groups_index|
      #puts "#{data_set['kv']}\ndata_groups_index: #{data_groups_index}"
      next if data_groups_index == 0
        data_set[sum_key].each_with_index{|data_month, data_month_index|
          #puts "\tdata_month_index: #{data_month_index}"
          out_mean_profile = out[sum_key][data_month_index]["mean_profile"]
          data_month_mean_profile = Marshal.load(Marshal.dump(data_month['mean_profile']))
          #add two arrays of mean_profile
          # the code concats the two arrays and adds it together 
          out[sum_key][data_month_index]["mean_profile"] = [out_mean_profile, data_month_mean_profile].transpose.map {|x| x.reduce(:+)}
          #puts "\t\t#{out[sum_key][data_month_index]["mean_profile"]}"
        }
        # sum all the hourly values to recalculate the bin distribution
        out_data_hourly_adjusted = out["data_hourly_adjusted"]
        data_set_data_hourly_adjusted = Marshal.load(Marshal.dump(data_set['data_hourly_adjusted']))
        #add two arrays of mean_profile
        out["data_hourly_adjusted"] = [out_data_hourly_adjusted, data_set_data_hourly_adjusted].transpose.map {|x| x.reduce(:+)}
      }

      #recalculate bin distributions
      #Get Annual PLR based not on Capacity, but on Min and Max Not total Capacity! 
      min_max_ratio = {}
      max = out["data_hourly_adjusted"].max
      (1..10).each { |bin| min_max_ratio["#{(bin-1)*10}-#{(bin*10)}%"] = 0 }
      #iterate through each hour and bin the information based on 10th percentages.  
      out["data_hourly_adjusted"].each do |data|
        #Get rid of any 
        if max.to_f != 0.0
          percentage = (100.0 * data.to_f/max.to_f).round
        else
          percentage = 0
        end
        case percentage
        when 0..10    then min_max_ratio['0-10%']   += 1
        when 11..20   then min_max_ratio['10-20%']  += 1
        when 21..30   then min_max_ratio['20-30%']  += 1
        when 31..40   then min_max_ratio['30-40%']  += 1
        when 41..50   then min_max_ratio['40-50%']  += 1
        when 51..60   then min_max_ratio['50-60%']  += 1
        when 61..70   then min_max_ratio['60-70%']  += 1
        when 71..80   then min_max_ratio['70-80%']  += 1
        when 81..90   then min_max_ratio['80-90%']  += 1
        when 91..100  then min_max_ratio['90-100%'] += 1
        end
      end

      out['min_max_hourly_breakdown'] = min_max_ratio

      total_data_record_array << out
      #File.open("#{key.gsub(":","_")}-out.json", 'w') {|f| f.write(JSON.pretty_generate(out)) }
    }
    # store min max information in a separate hash
    monthly_data = {}
    total_data_record_array.each_with_index{|data_set, data_groups_index|
      data_set[sum_key].each_with_index{|data_month, data_month_index|
        month = data_month['month']
        key = data_set['var_name']
        #puts month
        monthly_data[key] ||= {}
        monthly_data[key][month] ||= {}
        monthly_data[key][month]['total'] ||= 0
        #puts "total before: #{monthly_data[key][month]['total']}"
        monthly_data[key][month]['total'] += data_set[sum_key][data_month_index]["mean_profile"].inject(0, :+)
        #puts "total aftr: #{monthly_data[key][month]['total']}\n"

        monthly_data[key][month]['maximum'] ||= -(2**(0.size * 8 -2))
        monthly_data[key][month]['maximum_hour'] ||= -1

        #monthly_data[key][month]['minimum'] ||= (2**(0.size * 8 -2) -1)
        #monthly_data[key][month]['minimum_hour'] ||= -1

        if (monthly_data[key][month]['maximum'] < data_set[sum_key][data_month_index]["mean_profile"].max)
          monthly_data[key][month]['maximum'] = data_set[sum_key][data_month_index]["mean_profile"].max
          monthly_data[key][month]['maximum_hour'] = data_set[sum_key][data_month_index]["mean_profile"].each_with_index.max[1]
        end

        #if (monthly_data[key][month]['minimum'] > data_set[sum_key][data_month_index]["mean_profile"].min)
        #  monthly_data[key][month]['minimum'] = data_set[sum_key][data_month_index]["mean_profile"].min
        #  monthly_data[key][month]['minimum_hour'] = data_set[sum_key][data_month_index]["mean_profile"].each_with_index.min[1]
        #end

        #puts "\t\t#{data_set[sum_key][data_month_index]["mean_profile"]}"
        #puts "#{key}\n#{JSON.pretty_generate(monthly_data)}\n" unless key == "SHW" 
      }
    }
    
    #puts JSON.pretty_generate(monthly_data)
    CSV.open( 'enduse_total_24_hour_weekend_weekday_averages.csv', 'w' ) do |writer|
      row = []
      row << 'var_name' << 'key_variable' << 'units' << 'month' <<  'day_of_week' << "Data Type"
      row += (0..23).to_a
      writer << row
      #write the total end uses data to the csv file
      total_data_record_array.each do |r|
        r['monthly_24_hour_weekend_weekday_averages'].each do |m|
          #Write average 24 hour profile for day of the week m['day'] for each month.  
          row = []
          row << r['var_name'] << r['kv'] << r['units'] << m['month'] <<  m['wday'] << "MEAN"
          row += m['mean_profile']
          writer << row
        end
      end
      row = []
      writer << row
      #write the min and max information to the csv file
      row << "End Use Variable" << "Month" << "Total" << "Maximum" << "Maximum's Hour"
      writer << row
      monthly_data.keys.each { |end_use|
        (1..12).each { |month|
          row = []
          row << end_use << month << monthly_data[end_use][month]["total"] << monthly_data[end_use][month]["maximum"] << monthly_data[end_use][month]["maximum_hour"]
          writer << row
        }
      }
      row = []
      writer << row
      #write the bin distribution of the end uses to the csv file
      row << "Bin Distribution" << "Key Value"
      total_data_record_array[0]['min_max_hourly_breakdown'].keys.each { |key| row <<  key }
      writer << row
      total_data_record_array.each { |r|
        row = []
        row << r['var_name'] << r['kv']
        r['min_max_hourly_breakdown'].keys.each { |key| row <<  r['min_max_hourly_breakdown'][key] }
        writer << row
      }
      row = []
      writer << row
      #write the bin distribution of all the unlocked variables to the csv file
      data_record_array.each { |r|
        row = []
        row << r['var_name'] << r['kv']
        r['min_max_hourly_breakdown'].keys.each { |key| row <<  r['min_max_hourly_breakdown'][key] }
        writer << row
      }
    end
  end

  
  
  def check_boolean_value (value,varname)
    return true if value =~ (/^(true|t|yes|y|1)$/i)
    return false if value.empty? || value =~ (/^(false|f|no|n|0)$/i)

    raise ArgumentError.new "invalid value for #{varname}: #{value}"
  end
  
  
  def get_total_nominal_capacity (model)
    total_nominal_capacity = 0
    model.getSpaces.each do |space|
      zone_name = space.thermalZone.get.name.get.upcase
      area = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='InputVerificationandResultsSummary' AND ReportForString='Entire Facility' AND TableName='Zone Summary' AND ColumnName='Area' AND RowName='#{zone_name}'")
      area = validate_optional(area, model, -1)
      multiplier = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='InputVerificationandResultsSummary' AND ReportForString='Entire Facility' AND TableName='Zone Summary' AND ColumnName='Multipliers' AND RowName='#{zone_name}'")
      multiplier = validate_optional(multiplier, model, -1)
      area_per_person = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='InputVerificationandResultsSummary' AND ReportForString='Entire Facility' AND TableName='Zone Summary' AND ColumnName='People' AND RowName='#{zone_name}'")
      area_per_person = validate_optional(area_per_person, model, -1)
      next if area_per_person == 0
      puts "area: #{area}  multiplier: #{multiplier}   area_per_person: #{area_per_person}"
      total_nominal_capacity += area*multiplier/area_per_person
    end
    return total_nominal_capacity
  end
  
  # define what happens when the measure is run
  def run(runner, user_arguments)

    super(runner, user_arguments)
    generate_hourly_report = runner.getStringArgumentValue('generate_hourly_report',user_arguments)
    generate_hourly_report = check_boolean_value(generate_hourly_report,"generate_hourly_report")
    
    if generate_hourly_report
      runHourlyReports(runner, user_arguments)
    end
    # get sql, model, and web assets
    setup = OsLib_Reporting.setup(runner)
    unless setup
      return false
    end
    
    cli_path = OpenStudio.getOpenStudioCLI
    #contruct command with local libs
    f = open("| \"#{cli_path}\" openstudio_version")
    os_version = f.read()
    f = open("| \"#{cli_path}\" energyplus_version")
    eplus_version = f.read()
    puts "\n\n\nOS_version is [#{os_version.strip}]"
    puts "\n\n\nEP_version is [#{eplus_version.strip}]"
    
    model = setup[:model]
    # workspace = setup[:workspace]
    sql_file = setup[:sqlFile]
    web_asset_path = setup[:web_asset_path]
    model.setSqlFile( sql_file )

    # reporting final condition
    runner.registerInitialCondition('Gathering data from EnergyPlus SQL file and OSM model.')
    
    #Determine weighted area average conductances
    surfaces = {}
    outdoor_surfaces = BTAP::Geometry::Surfaces::filter_by_boundary_condition(model.getSurfaces(), "Outdoors")
    outdoor_walls = BTAP::Geometry::Surfaces::filter_by_surface_types(outdoor_surfaces, "Wall")
    outdoor_roofs = BTAP::Geometry::Surfaces::filter_by_surface_types(outdoor_surfaces, "RoofCeiling")
    outdoor_floors = BTAP::Geometry::Surfaces::filter_by_surface_types(outdoor_surfaces, "Floor")
    outdoor_subsurfaces = BTAP::Geometry::Surfaces::get_subsurfaces_from_surfaces(outdoor_surfaces)

    ground_surfaces = BTAP::Geometry::Surfaces::filter_by_boundary_condition(model.getSurfaces(), "Ground")
    ground_walls = BTAP::Geometry::Surfaces::filter_by_surface_types(ground_surfaces, "Wall")
    ground_roofs = BTAP::Geometry::Surfaces::filter_by_surface_types(ground_surfaces, "RoofCeiling")
    ground_floors = BTAP::Geometry::Surfaces::filter_by_surface_types(ground_surfaces, "Floor")

    windows = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(outdoor_subsurfaces, ["FixedWindow" , "OperableWindow" ])
    skylights = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(outdoor_subsurfaces, ["Skylight", "TubularDaylightDiffuser","TubularDaylightDome" ])
    doors = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(outdoor_subsurfaces, ["Door" , "GlassDoor" ])
    overhead_doors = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(outdoor_subsurfaces, ["OverheadDoor" ])
    electric_peak = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM tabulardatawithstrings WHERE ReportName='EnergyMeters'" +
        " AND ReportForString='Entire Facility' AND TableName='Annual and Peak Values - Electricity' AND RowName='Electricity:Facility'" +
        " AND ColumnName='Electricity Maximum Value' AND Units='W'")
    natural_gas_peak = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM tabulardatawithstrings WHERE ReportName='EnergyMeters'" +
        " AND ReportForString='Entire Facility' AND TableName='Annual and Peak Values - Gas' AND RowName='Gas:Facility'" +
        " AND ColumnName='Gas Maximum Value' AND Units='W'")

    # Create hash to store all the collected data. 
    qaqc = {}
    error_warning=[]
    qaqc[:os_standards_revision] = OpenstudioStandards::git_revision
    qaqc[:os_standards_version] = OpenstudioStandards::VERSION
    qaqc[:openstudio_version] = os_version.strip
    qaqc[:energyplus_version] = eplus_version.strip
    qaqc[:date] = Time.now
    # Store Building data. 
    qaqc[:building] = {}
    qaqc[:building][:name] = model.building.get.name.get
    qaqc[:building][:conditioned_floor_area_m2]=nil
    unless model.building.get.conditionedFloorArea().empty?
      qaqc[:building][:conditioned_floor_area_m2] = model.building.get.conditionedFloorArea().get 
    else
      error_warning <<  "model.building.get.conditionedFloorArea() is empty for #{model.building.get.name.get}"
    end
    qaqc[:building][:exterior_area_m2] = model.building.get.exteriorSurfaceArea() #m2
    qaqc[:building][:volume] = model.building.get.airVolume() #m3
    qaqc[:building][:number_of_stories] = model.getBuildingStorys.size
    # Store Geography Data
    qaqc[:geography] ={}
    puts "Phylroy" 
    puts model.getWeatherFile.path.get.to_s 
    puts model.getWeatherFile.city
    qaqc[:geography][:hdd] = BTAP::Environment::WeatherFile.new( model.getWeatherFile.path.get.to_s ).hdd18
    qaqc[:geography][:cdd] = BTAP::Environment::WeatherFile.new( model.getWeatherFile.path.get.to_s ).cdd18
    qaqc[:geography][:climate_zone] = BTAP::Compliance::NECB2011::get_climate_zone_name(qaqc[:geography][:hdd])
    qaqc[:geography][:city] = model.getWeatherFile.city
    qaqc[:geography][:state_province_region] = model.getWeatherFile.stateProvinceRegion
    qaqc[:geography][:country] = model.getWeatherFile.country
    qaqc[:geography][:latitude] = model.getWeatherFile.latitude
    qaqc[:geography][:longitude] = model.getWeatherFile.longitude
    
    #Spacetype Breakdown
    qaqc[:spacetype_area_breakdown]={}
    model.getSpaceTypes.sort.each do |spaceType|
      next if spaceType.floorArea == 0

      # data for space type breakdown
      display = spaceType.name.get
      floor_area_si = 0
      # loop through spaces so I can skip if not included in floor area
      spaceType.spaces.each do |space|
        next if not space.partofTotalFloorArea
        floor_area_si += space.floorArea * space.multiplier
      end
      qaqc[:spacetype_area_breakdown][spaceType.name.get.gsub(/\s+/, "_").downcase.to_sym] = floor_area_si
    end
    
    #Economics Section
    #Fuel cost based on National Energy Board rates
    qaqc[:economics] = {}
    provinces_names_map = {'QC' => 'Quebec','NL' => 'Newfoundland and Labrador','NS' => 'Nova Scotia','PE' => 'Prince Edward Island','ON' => 'Ontario','MB' => 'Manitoba','SK' => 'Saskatchewan','AB' => 'Alberta','BC' => 'British Columbia','YT' => 'Yukon','NT' => 'Northwest Territories','NB' => 'New Brunswick','NU' => 'Nunavut'}
    neb_prices_csv_file_name ="#{File.dirname(__FILE__)}/resources/neb_end_use_prices.csv"
    puts neb_prices_csv_file_name
	building_type = 'Commercial'
	province = provinces_names_map[qaqc[:geography][:state_province_region]]
    neb_fuel_list = ['Electricity','Natural Gas',"Oil"]
    neb_eplus_fuel_map = {'Electricity' => 'Electricity','Natural Gas' => 'Gas','Oil' => "FuelOil#2"}
    qaqc[:economics][:total_neb_cost]  = 0.0
    qaqc[:economics][:total_neb_cost_per_m2]  = 0.0
    neb_eplus_fuel_map.each do |neb_fuel,ep_fuel|
      row = look_up_csv_data(neb_prices_csv_file_name,{0 => building_type,1 => province, 2 => neb_fuel})
      neb_fuel_cost = row['2018']
	  fuel_consumption_gj = 0.0
      if neb_fuel == 'Electricity' || neb_fuel == 'Natural Gas'
        if model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM tabulardatawithstrings WHERE ReportName='EnergyMeters' AND ReportForString='Entire Facility' AND 
	      TableName='Annual and Peak Values - #{ep_fuel}' AND RowName='#{ep_fuel}:Facility' AND ColumnName='#{ep_fuel} Annual Value' AND Units='GJ'").is_initialized
          fuel_consumption_gj = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM tabulardatawithstrings WHERE ReportName='EnergyMeters' AND ReportForString='Entire Facility' AND 
	      TableName='Annual and Peak Values - #{ep_fuel}' AND RowName='#{ep_fuel}:Facility' AND ColumnName='#{ep_fuel} Annual Value' AND Units='GJ'").get
        end
	  else
        if model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM tabulardatawithstrings WHERE ReportName='EnergyMeters' AND ReportForString='Entire Facility' AND 
	      TableName='Annual and Peak Values - Other' AND RowName='#{ep_fuel}:Facility' AND ColumnName='Annual Value' AND Units='GJ'").is_initialized
          fuel_consumption_gj = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM tabulardatawithstrings WHERE ReportName='EnergyMeters' AND ReportForString='Entire Facility' AND 
	      TableName='Annual and Peak Values - Other' AND RowName='#{ep_fuel}:Facility' AND ColumnName='Annual Value' AND Units='GJ'").get
        end
      end
      qaqc[:economics][:"#{neb_fuel}_neb_cost"] = fuel_consumption_gj*neb_fuel_cost.to_f
      qaqc[:economics][:"#{neb_fuel}_neb_cost_per_m2"] = qaqc[:economics][:"#{neb_fuel}_neb_cost"]/qaqc[:building][:conditioned_floor_area_m2] unless model.building.get.conditionedFloorArea().empty?	
      qaqc[:economics][:total_neb_cost] += qaqc[:economics][:"#{neb_fuel}_neb_cost"]
      qaqc[:economics][:total_neb_cost_per_m2] += qaqc[:economics][:"#{neb_fuel}_neb_cost_per_m2"]
    end
    
    #Fuel cost based local utility rates
    costing_rownames = model.sqlFile().get().execAndReturnVectorOfString("SELECT RowName FROM TabularDataWithStrings WHERE ReportName='LEEDsummary' AND ReportForString='Entire Facility' AND TableName='EAp2-7. Energy Cost Summary' AND ColumnName='Total Energy Cost'").get
    #==> ["Electricity", "Natural Gas", "Additional", "Total"]
    costing_rownames.each do |rowname|
      case rowname
      when "Electricity"
        qaqc[:economics][:electricity_cost] = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='LEEDsummary' AND ReportForString='Entire Facility' AND TableName='EAp2-7. Energy Cost Summary' AND ColumnName='Total Energy Cost' AND RowName='#{rowname}'").get
        qaqc[:economics][:electricity_cost_per_m2]=qaqc[:economics][:electricity_cost]/qaqc[:building][:conditioned_floor_area_m2] unless model.building.get.conditionedFloorArea().empty?

      when "Natural Gas"
        qaqc[:economics][:natural_gas_cost] = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='LEEDsummary' AND ReportForString='Entire Facility' AND TableName='EAp2-7. Energy Cost Summary' AND ColumnName='Total Energy Cost' AND RowName='#{rowname}'").get
        qaqc[:economics][:natural_gas_cost_per_m2]=qaqc[:economics][:natural_gas_cost]/qaqc[:building][:conditioned_floor_area_m2] unless model.building.get.conditionedFloorArea().empty?

      when "Additional"
        qaqc[:economics][:additional_cost] = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='LEEDsummary' AND ReportForString='Entire Facility' AND TableName='EAp2-7. Energy Cost Summary' AND ColumnName='Total Energy Cost' AND RowName='#{rowname}'").get
        qaqc[:economics][:additional_cost_per_m2]=qaqc[:economics][:additional_cost]/qaqc[:building][:conditioned_floor_area_m2] unless model.building.get.conditionedFloorArea().empty?

      when "Total"
        qaqc[:economics][:total_cost] = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='LEEDsummary' AND ReportForString='Entire Facility' AND TableName='EAp2-7. Energy Cost Summary' AND ColumnName='Total Energy Cost' AND RowName='#{rowname}'").get
        qaqc[:economics][:total_cost_per_m2]=qaqc[:economics][:total_cost]/qaqc[:building][:conditioned_floor_area_m2] unless model.building.get.conditionedFloorArea().empty?

      end
    end
    
    #Store end_use data
    end_uses = [
      'Heating',
      'Cooling',
      'Interior Lighting',
      'Exterior Lighting',
      'Interior Equipment',
      'Exterior Equipment',
      'Fans',
      'Pumps',
      'Heat Rejection',
      'Humidification',
      'Heat Recovery',
      'Water Systems',
      'Refrigeration',
      'Generators',                                                                                
      'Total End Uses'
    ]
    
    fuels = [ 
      ['Electricity', 'GJ'],       
      ['Natural Gas', 'GJ'] , 
      ['Additional Fuel', 'GJ'],
      ['District Cooling','GJ'],             
      ['District Heating', 'GJ'], 
    ]
    
    qaqc[:end_uses] = {}
    qaqc[:end_uses_eui] = {}
    end_uses.each do |use_type|
      qaqc[:end_uses]["#{use_type.gsub(/\s+/, "_").downcase.to_sym}_gj"] = 0
      qaqc[:end_uses_eui]["#{use_type.gsub(/\s+/, "_").downcase.to_sym}_gj_per_m2"] = 0
      fuels.each do |fuel_type|
        value = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM tabulardatawithstrings WHERE ReportName='AnnualBuildingUtilityPerformanceSummary' AND ReportForString='Entire Facility' AND TableName='End Uses' AND RowName='#{use_type}' AND ColumnName='#{fuel_type[0]}' AND Units='#{fuel_type[1]}'")
        if value.empty? or value.get == 0
        else
          qaqc[:end_uses]["#{use_type.gsub(/\s+/, "_").downcase.to_sym}_gj"] += value.get
          unless qaqc[:building][:conditioned_floor_area_m2].nil?
            qaqc[:end_uses_eui]["#{use_type.gsub(/\s+/, "_").downcase.to_sym}_gj_per_m2"] += value.get / qaqc[:building][:conditioned_floor_area_m2]
          end
        end
      end
      value = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM tabulardatawithstrings WHERE ReportName='AnnualBuildingUtilityPerformanceSummary' AND ReportForString='Entire Facility' AND TableName='End Uses' AND RowName='#{use_type}' AND ColumnName='Water' AND Units='m3'")
      if value.empty? or value.get == 0
      else
        qaqc[:end_uses]["#{use_type.gsub(/\s+/, "_").downcase.to_sym}_water_m3"] = value.get
        unless qaqc[:building][:conditioned_floor_area_m2].nil?
          qaqc[:end_uses_eui]["#{use_type.gsub(/\s+/, "_").downcase.to_sym}_water_m3_per_m2"] = value.get / qaqc[:building][:conditioned_floor_area_m2]
        end
      end
    end
    
    # Store Peak Data
    qaqc[:meter_peaks] = {}
    qaqc[:meter_peaks][:electric_w] = electric_peak.empty? ? "NA" : electric_peak.get  
    qaqc[:meter_peaks][:natural_gas_w] = natural_gas_peak.empty? ? "NA" : natural_gas_peak.get 
    
    
    #Store unmet hour data
    qaqc[:unmet_hours] = {}
    qaqc[:unmet_hours][:cooling] = model.getFacility.hoursCoolingSetpointNotMet().get unless model.getFacility.hoursCoolingSetpointNotMet().empty?
    qaqc[:unmet_hours][:heating] = model.getFacility.hoursHeatingSetpointNotMet().get unless model.getFacility.hoursHeatingSetpointNotMet().empty?
    
    
    
    
    
    
    #puts "\n\n\n#{costing_rownames}\n\n\n"
    #Padmassun's Code -- Tarrif end


    #Padmassun's Code -- Service Hotwater Heating *start*
    qaqc[:service_water_heating] = {}
    qaqc[:service_water_heating][:total_nominal_occupancy]=-1
    #qaqc[:service_water_heating][:total_nominal_occupancy]=model.sqlFile().get().execAndReturnVectorOfDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='OutdoorAirSummary' AND ReportForString='Entire Facility' AND TableName='Average Outdoor Air During Occupied Hours' AND ColumnName='Nominal Number of Occupants'").get.inject(0, :+)
    qaqc[:service_water_heating][:total_nominal_occupancy]=get_total_nominal_capacity(model)
    
    qaqc[:service_water_heating][:electricity_per_year]=model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='AnnualBuildingUtilityPerformanceSummary' AND ReportForString='Entire Facility' AND TableName='End Uses' AND ColumnName='Electricity' AND RowName='Water Systems'")
    qaqc[:service_water_heating][:electricity_per_year]= validate_optional(qaqc[:service_water_heating][:electricity_per_year], model, -1)

    qaqc[:service_water_heating][:electricity_per_day]=qaqc[:service_water_heating][:electricity_per_year]/365.5
    qaqc[:service_water_heating][:electricity_per_day_per_occupant]=qaqc[:service_water_heating][:electricity_per_day]/qaqc[:service_water_heating][:total_nominal_occupancy]
  
    
    qaqc[:service_water_heating][:natural_gas_per_year]=model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='AnnualBuildingUtilityPerformanceSummary' AND ReportForString='Entire Facility' AND TableName='End Uses' AND ColumnName='Natural Gas' AND RowName='Water Systems'")
    qaqc[:service_water_heating][:natural_gas_per_year]=validate_optional(qaqc[:service_water_heating][:natural_gas_per_year], model, -1)

    qaqc[:service_water_heating][:additional_fuel_per_year]=model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='AnnualBuildingUtilityPerformanceSummary' AND ReportForString='Entire Facility' AND TableName='End Uses' AND ColumnName='Additional Fuel' AND RowName='Water Systems'")
    qaqc[:service_water_heating][:additional_fuel_per_year] = validate_optional(qaqc[:service_water_heating][:additional_fuel_per_year], model, -1)
    
    qaqc[:service_water_heating][:water_m3_per_year]=model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='AnnualBuildingUtilityPerformanceSummary' AND ReportForString='Entire Facility' AND TableName='End Uses' AND ColumnName='Water' AND RowName='Water Systems'")
    qaqc[:service_water_heating][:water_m3_per_year]=validate_optional(qaqc[:service_water_heating][:water_m3_per_year], model, -1)
    
    qaqc[:service_water_heating][:water_m3_per_day]=qaqc[:service_water_heating][:water_m3_per_year]/365.5
    qaqc[:service_water_heating][:water_m3_per_day_per_occupant]=qaqc[:service_water_heating][:water_m3_per_day]/qaqc[:service_water_heating][:total_nominal_occupancy]
    #puts qaqc[:service_water_heating][:total_nominal_occupancy]
    #Padmassun's Code -- Service Hotwater Heating *end*

    #Store Envelope data.
    qaqc[:envelope] = {}
  
    qaqc[:envelope][:outdoor_walls_average_conductance_w_per_m2_k]  = BTAP::Geometry::Surfaces::get_weighted_average_surface_conductance(outdoor_walls).round(4) if outdoor_walls.size > 0
    qaqc[:envelope][:outdoor_roofs_average_conductance_w_per_m2_k]  = BTAP::Geometry::Surfaces::get_weighted_average_surface_conductance(outdoor_roofs).round(4) if outdoor_roofs.size > 0
    qaqc[:envelope][:outdoor_floors_average_conductance_w_per_m2_k] = BTAP::Geometry::Surfaces::get_weighted_average_surface_conductance(outdoor_floors).round(4) if outdoor_floors.size > 0
    qaqc[:envelope][:ground_walls_average_conductance_w_per_m2_k]   = BTAP::Geometry::Surfaces::get_weighted_average_surface_conductance(ground_walls).round(4) if ground_walls.size > 0
    qaqc[:envelope][:ground_roofs_average_conductance_w_per_m2_k]   = BTAP::Geometry::Surfaces::get_weighted_average_surface_conductance(ground_roofs).round(4) if ground_roofs.size > 0
    qaqc[:envelope][:ground_floors_average_conductance_w_per_m2_k]  = BTAP::Geometry::Surfaces::get_weighted_average_surface_conductance(ground_floors).round(4) if ground_floors.size > 0
    qaqc[:envelope][:windows_average_conductance_w_per_m2_k]      = BTAP::Geometry::Surfaces::get_weighted_average_surface_conductance(windows).round(4) if windows.size > 0
    qaqc[:envelope][:skylights_average_conductance_w_per_m2_k]    = BTAP::Geometry::Surfaces::get_weighted_average_surface_conductance(skylights).round(4) if skylights.size > 0
    qaqc[:envelope][:doors_average_conductance_w_per_m2_k]      = BTAP::Geometry::Surfaces::get_weighted_average_surface_conductance(doors).round(4) if doors.size > 0
    qaqc[:envelope][:overhead_doors_average_conductance_w_per_m2_k] = BTAP::Geometry::Surfaces::get_weighted_average_surface_conductance(overhead_doors).round(4) if overhead_doors.size > 0
    qaqc[:envelope][:fdwr]                      = (BTAP::Geometry::get_fwdr(model) * 100.0).round(1)
    qaqc[:envelope][:srr]                       = (BTAP::Geometry::get_srr(model) * 100.0).round(1)
  
  
    qaqc[:envelope][:constructions] = {}
    qaqc[:envelope][:constructions][:exterior_fenestration] = []
    constructions = []
    outdoor_subsurfaces.each { |surface| constructions << surface.construction.get }
    ext_const_base = Hash.new(0)
    constructions.each { |name| ext_const_base[name] += 1 }
    #iterate thought each construction and get store data
    ext_const_base.sort.each do |construction, count|
      construction_info = {}
      qaqc[:envelope][:constructions][:exterior_fenestration] << construction_info
      construction_info[:name] = construction.name.get
      construction_info[:net_area_m2] = construction.getNetArea.round(2)
      construction_info[:thermal_conductance_m2_w_per_k] = BTAP::Resources::Envelope::Constructions::get_conductance(construction).round(3)
      construction_info[:solar_transmittance] = BTAP::Resources::Envelope::Constructions::get_tsol(model,construction).round(3)
      construction_info[:visible_tranmittance] = BTAP::Resources::Envelope::Constructions::get_tvis(model,construction).round(3)
    end 
    
    #Exterior
    qaqc[:envelope][:constructions][:exterior_opaque] = []
    constructions = []
    outdoor_surfaces.each { |surface| constructions << surface.construction.get }
    ext_const_base = Hash.new(0)
    constructions.each { |name| ext_const_base[name] += 1 }
    #iterate thought each construction and get store data
    ext_const_base.sort.each do |construction, count|
      construction_info = {}
      qaqc[:envelope][:constructions][:exterior_opaque] << construction_info
      construction_info[:name] = construction.name.get
      construction_info[:net_area_m2] = construction.getNetArea.round(2)
      construction_info[:thermal_conductance_m2_w_per_k] = construction.thermalConductance.get.round(3) if construction.thermalConductance.is_initialized
      construction_info[:net_area_m2] = construction.to_Construction.get.getNetArea.round(2)
      construction_info[:solar_absorptance] = construction.to_Construction.get.layers[0].exteriorVisibleAbsorptance.get
    end
  
    #Ground
    qaqc[:envelope][:constructions][:ground] = []
    constructions = []
    ground_surfaces.each { |surface| constructions << surface.construction.get }
    ext_const_base = Hash.new(0)
    constructions.each { |name| ext_const_base[name] += 1 }
    #iterate thought each construction and get store data
    ext_const_base.sort.each do |construction, count|
      construction_info = {}
      qaqc[:envelope][:constructions][:ground] << construction_info
      construction_info[:name] = construction.name.get
      construction_info[:net_area_m2] = construction.getNetArea.round(2)
      construction_info[:thermal_conductance_m2_w_per_k] = construction.thermalConductance.get.round(3) if construction.thermalConductance.is_initialized
      construction_info[:net_area_m2] = construction.to_Construction.get.getNetArea.round(2)
      construction_info[:solar_absorptance] = construction.to_Construction.get.layers[0].exteriorVisibleAbsorptance.get
    end
  

    # Store Space data.
    qaqc[:spaces] =[]
    model.getSpaces.each do |space|
      spaceinfo = {}
      qaqc[:spaces] << spaceinfo
      spaceinfo[:name] = space.name.get #name should be defined test
      spaceinfo[:multiplier] = space.multiplier 
      spaceinfo[:volume] = space.volume # should be greater than zero
      spaceinfo[:exterior_wall_area] = space.exteriorWallArea # just for information. 
      spaceinfo[:space_type_name] = space.spaceType.get.name.get unless space.spaceType.empty? #should have a space types name defined. 
      spaceinfo[:thermal_zone] = space.thermalZone.get.name.get unless space.thermalZone.empty? # should be assigned a thermalzone name.
      #puts space.name.get
      #puts space.thermalZone.empty?
      spaceinfo[:breathing_zone_outdoor_airflow_vbz] =-1
      breathing_zone_outdoor_airflow_vbz= model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='Standard62.1Summary' AND ReportForString='Entire Facility' AND TableName='Zone Ventilation Parameters' AND ColumnName='Breathing Zone Outdoor Airflow - Vbz' AND Units='m3/s' AND RowName='#{spaceinfo[:thermal_zone].to_s.upcase}' ")
      spaceinfo[:breathing_zone_outdoor_airflow_vbz] =breathing_zone_outdoor_airflow_vbz.get unless breathing_zone_outdoor_airflow_vbz.empty?
      spaceinfo[:infiltration_method] = 'N/A' 
      spaceinfo[:infiltration_flow_per_m2]  =-1.0
      unless space.spaceInfiltrationDesignFlowRates[0].nil?
        spaceinfo[:infiltration_method] = space.spaceInfiltrationDesignFlowRates[0].designFlowRateCalculationMethod
        spaceinfo[:infiltration_flow_per_m2] = "N/A"
        spaceinfo[:infiltration_flow_per_m2] = space.spaceInfiltrationDesignFlowRates[0].flowperExteriorSurfaceArea.get.round(5) unless space.spaceInfiltrationDesignFlowRates[0].flowperExteriorSurfaceArea.empty?
      else
        error_warning <<  "space.spaceInfiltrationDesignFlowRates[0] is empty for #{spaceinfo[:name]}"
        error_warning <<  "space.spaceInfiltrationDesignFlowRates[0].designFlowRateCalculationMethod is empty for #{spaceinfo[:name]}"
        error_warning <<  "space.spaceInfiltrationDesignFlowRates[0].flowperExteriorSurfaceArea is empty for #{spaceinfo[:name]}"
      end  

      #the following should have values unless the spacetype is "undefined" other they should be set to the correct NECB values. 
      unless space.spaceType.empty?
        spaceinfo[:occupancy_schedule] = nil
        unless (space.spaceType.get.defaultScheduleSet.empty?)
          unless space.spaceType.get.defaultScheduleSet.get.numberofPeopleSchedule.empty?
            spaceinfo[:occupancy_schedule] = space.spaceType.get.defaultScheduleSet.get.numberofPeopleSchedule.get.name.get  #should not empty.
          else
            error_warning <<  "space.spaceType.get.defaultScheduleSet.get.numberofPeopleSchedule is empty for #{space.name.get }"
          end
        else
          error_warning <<  "space.spaceType.get.defaultScheduleSet is empty for #{space.name.get }"
        end
      
        spaceinfo[:occ_per_m2] = space.spaceType.get.people[0].peopleDefinition.peopleperSpaceFloorArea.get.round(3) unless space.spaceType.get.people[0].nil? 
        unless space.spaceType.get.lights[0].nil?
          spaceinfo[:lighting_w_per_m2] = space.spaceType.get.lights[0].lightsDefinition.wattsperSpaceFloorArea#.get.round(3) unless space.spaceType.get.lights[0].nil?
          spaceinfo[:lighting_w_per_m2] = validate_optional(spaceinfo[:lighting_w_per_m2], model)
          unless spaceinfo[:lighting_w_per_m2].nil?
            spaceinfo[:lighting_w_per_m2] = spaceinfo[:lighting_w_per_m2].round(3)
          end
        end
        #spaceinfo[:electric_w_per_m2] = space.spaceType.get.electricEquipment[0].electricEquipmentDefinition.wattsperSpaceFloorArea.get.round(3) unless space.spaceType.get.electricEquipment[0].nil?
      
        unless space.spaceType.get.electricEquipment[0].nil?
          unless space.spaceType.get.electricEquipment[0].electricEquipmentDefinition.wattsperSpaceFloorArea.empty?
            spaceinfo[:electric_w_per_m2] = space.spaceType.get.electricEquipment[0].electricEquipmentDefinition.wattsperSpaceFloorArea.get.round(3)
          end
        end
        spaceinfo[:shw_m3_per_s] = space.waterUseEquipment[0].waterUseEquipmentDefinition.peakFlowRate.round(3) unless space.waterUseEquipment[0].nil?
        spaceinfo[:waterUseEquipment] = []
        if !space.waterUseEquipment.empty?
          waterUseEquipment_info={}
          spaceinfo[:waterUseEquipment] << waterUseEquipment_info
          waterUseEquipment_info[:peak_flow_rate]= space.waterUseEquipment[0].waterUseEquipmentDefinition.getPeakFlowRate.value
          waterUseEquipment_info[:peak_flow_rate_per_area] = waterUseEquipment_info[:peak_flow_rate] / space.floorArea

          area_per_occ = 1.0 / space.spaceType.get.people[0].peopleDefinition.peopleperSpaceFloorArea.get
          #                             Watt per person =             m3/s/m3                * 1000W/kW * (specific heat * dT) * m2/person
          waterUseEquipment_info[:shw_watts_per_person] = waterUseEquipment_info[:peak_flow_rate_per_area] * 1000 * (4.19 * 44.4) * 1000 * area_per_occ
          #puts waterUseEquipment_info[:shw_watts_per_person]
          #puts "\n\n\n"
        end
      else
        error_warning <<  "space.spaceType is empty for #{space.name.get }"
      end
    end
    
    # Store Thermal zone data
    qaqc[:thermal_zones] = [] 
    model.getThermalZones.each do  |zone|
      zoneinfo = {}
      qaqc[:thermal_zones] << zoneinfo
      zoneinfo[:name] = zone.name.get
      zoneinfo[:floor_area] = zone.floorArea
      zoneinfo[:multiplier] = zone.multiplier
      zoneinfo[:is_conditioned] = "N/A"
      unless zone.isConditioned.empty?
        zoneinfo[:is_conditioned] = zone.isConditioned.get
      else
        error_warning <<  "zone.isConditioned is empty for #{zone.name.get}"
      end
      
      zoneinfo[:is_ideal_air_loads] = zone.useIdealAirLoads
      zoneinfo[:heating_sizing_factor] = -1.0
      unless zone.sizingZone.zoneHeatingSizingFactor.empty?
        zoneinfo[:heating_sizing_factor] = zone.sizingZone.zoneHeatingSizingFactor.get
      else
        error_warning <<  "zone.sizingZone.zoneHeatingSizingFactor is empty for #{zone.name.get}"
      end  
      
      zoneinfo[:cooling_sizing_factor] = -1.0 #zone.sizingZone.zoneCoolingSizingFactor.get
      unless zone.sizingZone.zoneCoolingSizingFactor.empty?
        zoneinfo[:cooling_sizing_factor] = zone.sizingZone.zoneCoolingSizingFactor.get
      else
        error_warning <<  "zone.sizingZone.zoneCoolingSizingFactor is empty for #{zone.name.get}"
      end  
      
      zoneinfo[:zone_heating_design_supply_air_temperature] = zone.sizingZone.zoneHeatingDesignSupplyAirTemperature
      zoneinfo[:zone_cooling_design_supply_air_temperature] = zone.sizingZone.zoneCoolingDesignSupplyAirTemperature
      zoneinfo[:spaces] = []
      zone.spaces.each do |space|
        spaceinfo ={}
        zoneinfo[:spaces] << spaceinfo
        spaceinfo[:name] = space.name.get  
        spaceinfo[:type] = space.spaceType.get.name.get unless space.spaceType.empty?
      end
      zoneinfo[:equipment] = []
      zone.equipmentInHeatingOrder.each do |equipment|
        item = {}
        zoneinfo[:equipment] << item
        item[:name] = equipment.name.get
        if equipment.to_ZoneHVACComponent.is_initialized
          item[:type] = 'ZoneHVACComponent'
        elsif  equipment.to_StraightComponent.is_initialized
          item[:type] = 'StraightComponent'
        end
      end
    end #zone
    # Store Air Loop Information
    qaqc[:air_loops] = []
    model.getAirLoopHVACs.each do |air_loop|
      air_loop_info = {}
      air_loop_info[:name] = air_loop.name.get
      air_loop_info[:thermal_zones] = []
      air_loop_info[:total_floor_area_served] = 0.0
      air_loop.thermalZones.each do |zone|
        air_loop_info[:thermal_zones] << zone.name.get
        air_loop_info[:total_floor_area_served] += zone.floorArea
      end
      #Fan

      unless air_loop.supplyFan.empty?
        air_loop_info[:supply_fan] = {}
        if air_loop.supplyFan.get.to_FanConstantVolume.is_initialized 
          air_loop_info[:supply_fan][:type] = 'CV'
          fan = air_loop.supplyFan.get.to_FanConstantVolume.get
        elsif air_loop.supplyFan.get.to_FanVariableVolume.is_initialized 
          air_loop_info[:supply_fan][:type]  = 'VV'
          fan = air_loop.supplyFan.get.to_FanVariableVolume.get
        end
        air_loop_info[:supply_fan][:name] = fan.name.get
        #puts "\n\n\n\n#{fan.name.get}\n\n\n\n"
        air_loop_info[:supply_fan][:fan_efficiency] = fan.fanEfficiency
        air_loop_info[:supply_fan][:motor_efficiency] = fan.motorEfficiency
        air_loop_info[:supply_fan][:pressure_rise] = fan.pressureRise
        air_loop_info[:supply_fan][:max_air_flow_rate]  = -1.0
       
        if model.sqlFile().get().execAndReturnVectorOfString("SELECT RowName FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Fans' AND ColumnName='Max Air Flow Rate' AND Units='m3/s' ").get.include? "#{air_loop_info[:supply_fan][:name]}"
          air_loop_info[:supply_fan][:max_air_flow_rate] = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Fans' AND ColumnName='Max Air Flow Rate' AND Units='m3/s' AND RowName='#{air_loop_info[:supply_fan][:name].upcase}' ").get
        else
          error_warning <<  "#{air_loop_info[:supply_fan][:name]} does not exist in sql file WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Fans' AND ColumnName='Max Air Flow Rate' AND Units='m3/s'"
        end
      end

      #economizer                                                                                             
      air_loop_info[:economizer] = {}
      air_loop_info[:economizer][:name] = air_loop.airLoopHVACOutdoorAirSystem.get.getControllerOutdoorAir.name.get
      air_loop_info[:economizer][:control_type] = air_loop.airLoopHVACOutdoorAirSystem.get.getControllerOutdoorAir.getEconomizerControlType

      #DX cooling coils
      air_loop_info[:cooling_coils] ={}
      air_loop_info[:cooling_coils][:dx_single_speed]=[]
      air_loop_info[:cooling_coils][:dx_two_speed]=[]

      #Heating Coil
      air_loop_info[:heating_coils] = {}
      air_loop_info[:heating_coils][:coil_heating_gas] = []
      air_loop_info[:heating_coils][:coil_heating_electric]= []
      air_loop_info[:heating_coils][:coil_heating_water]= []
      
      air_loop.supplyComponents.each do |supply_comp|
        if supply_comp.to_CoilHeatingGas.is_initialized
          coil={}
          air_loop_info[:heating_coils][:coil_heating_gas] << coil
          gas = supply_comp.to_CoilHeatingGas.get
          coil[:name]=gas.name.get
          coil[:type]="Gas"
          coil[:efficency] = gas.gasBurnerEfficiency
        end
        if supply_comp.to_CoilHeatingElectric.is_initialized
          coil={}
          air_loop_info[:heating_coils][:coil_heating_electric] << coil
          electric = supply_comp.to_CoilHeatingElectric.get
          coil[:name]= electric.name.get
          coil[:type]= "Electric"
        end
        if supply_comp.to_CoilHeatingWater.is_initialized
          coil={}
          air_loop_info[:heating_coils][:coil_heating_water] << coil
          water = supply_comp.to_CoilHeatingWater.get
          coil[:name]= water.name.get
          coil[:type]= "Water"
        end
      end
      
      #I dont think i need to get the type of heating coil from the sql file, because the coils are differentiated by class, and I have hard coded the information
      #model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName= 'Heating Coils' AND ColumnName='Type' ").get #padmussen to complete #AND RowName='#{air_loop_info[:heating_coils][:name].upcase}'
      
      
      #Collect all the fans into the the array.
      air_loop.supplyComponents.each do |supply_comp|
        if supply_comp.to_CoilCoolingDXSingleSpeed.is_initialized
          coil = {}
          air_loop_info[:cooling_coils][:dx_single_speed] << coil
          single_speed = supply_comp.to_CoilCoolingDXSingleSpeed.get
          coil[:name] = single_speed.name.get
          coil[:cop] = single_speed.getRatedCOP.get
          coil[:nominal_total_capacity_w] = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Cooling Coils' AND ColumnName='Nominal Total Capacity' AND RowName='#{coil[:name].upcase}' ")
          coil[:nominal_total_capacity_w] = validate_optional(coil[:nominal_total_capacity_w], model)
        end
        if supply_comp.to_CoilCoolingDXTwoSpeed.is_initialized
          coil = {}
          air_loop_info[:cooling_coils][:dx_two_speed] << coil
          two_speed = supply_comp.to_CoilCoolingDXTwoSpeed.get
          coil[:name] = two_speed.name.get
          coil[:cop_low] = two_speed.getRatedLowSpeedCOP.get
          coil[:cop_high] =  two_speed.getRatedHighSpeedCOP.get
          coil[:nominal_total_capacity_w] = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Cooling Coils' AND ColumnName='Nominal Total Capacity' AND RowName='#{coil[:name].upcase}' ")
          coil[:nominal_total_capacity_w] = validate_optional(coil[:nominal_total_capacity_w] , model)
        end
      end
      qaqc[:air_loops] << air_loop_info
    end


    qaqc[:plant_loops] = []
    model.getPlantLoops.each do |plant_loop|
      plant_loop_info = {}
      qaqc[:plant_loops] << plant_loop_info
      plant_loop_info[:name] = plant_loop.name.get
      
      sizing = plant_loop.sizingPlant
      plant_loop_info[:design_loop_exit_temperature] = sizing.getDesignLoopExitTemperature.value()
      plant_loop_info[:loop_design_temperature_difference] = sizing.getLoopDesignTemperatureDifference.value()
      
      #Create Container for plant equipment arrays.
      plant_loop_info[:pumps] = []
      plant_loop_info[:boilers] = []
      plant_loop_info[:chiller_electric_eir] = []
      plant_loop_info[:cooling_tower_single_speed] = []
      plant_loop_info[:water_heater_mixed] =[]
      plant_loop.supplyComponents.each do |supply_comp|
      
        #Collect Constant Speed
        if supply_comp.to_PumpConstantSpeed.is_initialized
          pump = supply_comp.to_PumpConstantSpeed.get
          pump_info = {}
          plant_loop_info[:pumps] << pump_info
          pump_info[:name] = pump.name.get
          pump_info[:type] = "Pump:ConstantSpeed"
          pump_info[:head_pa] = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Pumps' AND ColumnName='Head' AND RowName='#{pump_info[:name].upcase}' ")
          pump_info[:head_pa] = validate_optional(pump_info[:head_pa], model)
          pump_info[:water_flow_m3_per_s] = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Pumps' AND ColumnName='Water Flow' AND RowName='#{pump_info[:name].upcase}' ")
          pump_info[:water_flow_m3_per_s] = validate_optional(pump_info[:water_flow_m3_per_s], model)
          pump_info[:electric_power_w] = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Pumps' AND ColumnName='Electric Power' AND RowName='#{pump_info[:name].upcase}' ")
          pump_info[:electric_power_w] = validate_optional(pump_info[:electric_power_w], model)
          pump_info[:motor_efficency] = pump.getMotorEfficiency.value() 
        end
        
        #Collect Variable Speed
        if supply_comp.to_PumpVariableSpeed.is_initialized
          pump = supply_comp.to_PumpVariableSpeed.get
          pump_info = {}
          plant_loop_info[:pumps] << pump_info
          pump_info[:name] = pump.name.get
          pump_info[:type] = "Pump:VariableSpeed" 
          pump_info[:head_pa] = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Pumps' AND ColumnName='Head' AND RowName='#{pump_info[:name].upcase}' ")
          pump_info[:head_pa] = validate_optional(pump_info[:head_pa], model)
          pump_info[:water_flow_m3_per_s] = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Pumps' AND ColumnName='Water Flow' AND RowName='#{pump_info[:name].upcase}' ")
          pump_info[:water_flow_m3_per_s] = validate_optional(pump_info[:water_flow_m3_per_s], model)
          pump_info[:electric_power_w] = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Pumps' AND ColumnName='Electric Power' AND RowName='#{pump_info[:name].upcase}' ")
          pump_info[:electric_power_w] = validate_optional(pump_info[:electric_power_w], model)
          pump_info[:motor_efficency] = pump.getMotorEfficiency.value() 
        end
        
        # Collect HotWaterBoilers
        if supply_comp.to_BoilerHotWater.is_initialized
          boiler = supply_comp.to_BoilerHotWater.get
          boiler_info = {}
          plant_loop_info[:boilers] << boiler_info
          boiler_info[:name] = boiler.name.get
          boiler_info[:type] = "Boiler:HotWater" 
          boiler_info[:fueltype] = boiler.fuelType
          boiler_info[:nominal_capacity] = boiler.nominalCapacity
          boiler_info[:nominal_capacity] = validate_optional(boiler_info[:nominal_capacity], model)
        end
        
        # Collect ChillerElectricEIR
        if supply_comp.to_ChillerElectricEIR.is_initialized
          chiller = supply_comp.to_ChillerElectricEIR.get
          chiller_info = {}
          plant_loop_info[:chiller_electric_eir] << chiller_info
          chiller_info[:name] = chiller.name.get
          chiller_info[:type] = "Chiller:Electric:EIR" 
          chiller_info[:reference_capacity] = validate_optional(chiller.referenceCapacity, model)
          chiller_info[:reference_leaving_chilled_water_temperature] =chiller.referenceLeavingChilledWaterTemperature
        end
        
        # Collect CoolingTowerSingleSpeed
        if supply_comp.to_CoolingTowerSingleSpeed.is_initialized
          coolingTower = supply_comp.to_CoolingTowerSingleSpeed.get
          coolingTower_info = {}
          plant_loop_info[:cooling_tower_single_speed] << coolingTower_info
          coolingTower_info[:name] = coolingTower.name.get
          coolingTower_info[:type] = "CoolingTower:SingleSpeed" 
          coolingTower_info[:fan_power_at_design_air_flow_rate] = validate_optional(coolingTower.fanPoweratDesignAirFlowRate, model)

        end

        # Collect WaterHeaterMixed
        if supply_comp.to_WaterHeaterMixed.is_initialized
          waterHeaterMixed = supply_comp.to_WaterHeaterMixed.get
          waterHeaterMixed_info = {}
          plant_loop_info[:water_heater_mixed] << waterHeaterMixed_info
          waterHeaterMixed_info[:name] = waterHeaterMixed.name.get
          waterHeaterMixed_info[:type] = "WaterHeater:Mixed"
          waterHeaterMixed_info[:heater_thermal_efficiency] = waterHeaterMixed.heaterThermalEfficiency.get unless waterHeaterMixed.heaterThermalEfficiency.empty?
          waterHeaterMixed_info[:heater_fuel_type] = waterHeaterMixed.heaterFuelType
        end
      end
      
      qaqc[:eplusout_err] ={}  
      qaqc[:eplusout_err][:warnings] = model.sqlFile().get().execAndReturnVectorOfString("SELECT ErrorMessage FROM Errors WHERE ErrorType='0' ").get
      qaqc[:eplusout_err][:fatal] =model.sqlFile().get().execAndReturnVectorOfString("SELECT ErrorMessage FROM Errors WHERE ErrorType='2' ").get
      qaqc[:eplusout_err][:severe] =model.sqlFile().get().execAndReturnVectorOfString("SELECT ErrorMessage FROM Errors WHERE ErrorType='1' ").get
      qaqc[:ruby_warnings] = error_warning
    end
       
    
    # Perform qaqc
    necb_2011_qaqc(qaqc) if qaqc[:building][:name].include?("NECB 2011") #had to nodify this because this is specifically for "NECB-2011" standard
    sanity_check(qaqc)
    
    #write to json file.
    puts qaqc
    File.open('qaqc.json', 'w') {|f| f.write(JSON.pretty_generate(qaqc, :allow_nan => true)) }
    #puts JSON.pretty_generate(qaqc)
    # closing the sql file
    sql_file.close

    if generate_hourly_report
      hourly_data_8760 = File.open("8760_hourly_data.csv", "rb") { |f| f.read }
      hourly_custom_8760 = File.open("8760_hour_custom.csv", "rb") { |f| f.read }
      monthly_7_day_24_hour_averages = File.open("monthly_7_day_24_hour_averages.csv", "rb") { |f| f.read }
      monthly_24_hour_weekend_weekday_averages = File.open("monthly_24_hour_weekend_weekday_averages.csv", "rb") { |f| f.read }
      enduse_total_24_hour_weekend_weekday_averages = File.open("enduse_total_24_hour_weekend_weekday_averages.csv", "rb") { |f| f.read }

      store_data(runner, Base64.strict_encode64( Zlib::Deflate.deflate(hourly_data_8760) ), "btap_results_hourly_data_8760","-")
      store_data(runner, Base64.strict_encode64( Zlib::Deflate.deflate(hourly_custom_8760) ), "btap_results_hourly_custom_8760","-")
      store_data(runner, Base64.strict_encode64( Zlib::Deflate.deflate(monthly_7_day_24_hour_averages) ), "btap_results_monthly_7_day_24_hour_averages","-")
      store_data(runner, Base64.strict_encode64( Zlib::Deflate.deflate(monthly_24_hour_weekend_weekday_averages) ), "btap_results_monthly_24_hour_weekend_weekday_averages","-")
      store_data(runner, Base64.strict_encode64( Zlib::Deflate.deflate(enduse_total_24_hour_weekend_weekday_averages) ), "btap_results_enduse_total_24_hour_weekend_weekday_averages","-")

      #test_csv = File.open("test.csv", "rb") { |f| f.read }
      #test_24hours_csv = File.open("test_24hours.csv", "rb") { |f| f.read }
      #monthly_24_hour_weekend_weekday_averages_csv = File.open("monthly_24_hour_weekend_weekday_averages.csv", "rb") { |f| f.read }
      #store_data(runner, Base64.strict_encode64( Zlib::Deflate.deflate(test_csv) ), "btap_results_test_csv","-")
      #store_data(runner, Base64.strict_encode64( Zlib::Deflate.deflate(test_24hours_csv) ), "btap_results_test_24hours_csv","-")
      #store_data(runner, Base64.strict_encode64( Zlib::Deflate.deflate(monthly_24_hour_weekend_weekday_averages_csv) ), "btap_results_monthly_24_hour_weekend_weekday_averages_csv","-")
    end
    

    #Now store this information into the runner object.  This will be present in the csv file from the OS server and the R dataset. 
    store_data(runner, Base64.strict_encode64( Zlib::Deflate.deflate(model.to_s) ), "model_osm_zip","-")
    #Now store this json information into the runner object.  This will be present in the csv file from the OS server and the R dataset. 
    store_data(runner, Base64.strict_encode64( Zlib::Deflate.deflate(JSON.pretty_generate(qaqc,:allow_nan => true)) ), "btap_results_json_zip","-")
    
    #Weather file

    store_data(runner,  qaqc[:geography][:city],          "geo|City","-")
    store_data(runner,  qaqc[:geography][:state_province_region],   "geo|province","-")
    store_data(runner,  qaqc[:geography][:country],         "geo|Country","-")
    store_data(runner,  qaqc[:geography][:latitude] ,         "geo|latitude-deg","-")
    store_data(runner,  qaqc[:geography][:longitude],         "geo|longitude-deg","-")
    store_data(runner,  qaqc[:geography][:hdd],           "geo|Heating Degree Days-DD","deg*Day")
    store_data(runner,  qaqc[:geography][:cdd],           "geo|Cooling Degree Days-DD","deg*Day")
    store_data(runner,  qaqc[:geography][:climate_zone],      "geo|_NECB Climate Zone","")
    #unmet hours
    store_data(runner,  qaqc[:unmet_hours][:heating],       "qaqc-unmet_hours_heating-hours ", "Hours")
    store_data(runner,  qaqc[:unmet_hours][:cooling],       "qaqc-unmet_hours_cooling-hours ", "Hours")
    #Store Values
    store_data(runner,  qaqc[:building][:conditioned_floor_area_m2],"envelope-conditioned_floor_area-m2","M2")
    store_data(runner,  qaqc[:building][:exterior_area_m2],     "envelope-exterior_surface_area-m2","M2")
    store_data(runner,  qaqc[:building][:volume],         "envelope-building_volume-m3","M3")
    store_data(runner,  qaqc[:envelope][:outdoor_walls_average_conductance_w_per_m2_k] ,  "envelope-outdoor_walls_average_conductance-W_per_m2_K", "?")
    store_data(runner,  qaqc[:envelope][:outdoor_roofs_average_conductance_w_per_m2_k] ,  "envelope-outdoor_roofs_average_conductance-W_per_m2_K", "?")
    store_data(runner,  qaqc[:envelope][:outdoor_floors_average_conductance_w_per_m2_k] , "envelope-outdoor_floors_average_conductance-W_per_m2_K", "?")
    store_data(runner,  qaqc[:envelope][:ground_walls_average_conductance_w_per_m2_k],    "envelope-ground_walls_average_conductance-W_per_m2_K", "?")
    store_data(runner,  qaqc[:envelope][:ground_roofs_average_conductance_w_per_m2_k],    "envelope-ground_roofs_average_conductance-W_per_m2_K", "?")
    store_data(runner,  qaqc[:envelope][:ground_floors_average_conductance_w_per_m2_k] ,  "envelope-ground_floors_average_conductance-W_per_m2_K", "?")
    store_data(runner,  qaqc[:envelope][:windows_average_conductance_w_per_m2_k],     "envelope-outdoor_windows_average_conductance-W_per_m2_K", "?")
    store_data(runner,  qaqc[:envelope][:doors_average_conductance_w_per_m2_k],       "envelope-outdoor_doors_average_conductance-W_per_m2_K", "?")
    store_data(runner,  qaqc[:envelope][:overhead_doors_average_conductance_w_per_m2_k] , "envelope-outdoor_overhead_doors_average_conductance-W_per_m2_K", "?")
    store_data(runner,  qaqc[:envelope][:skylights_average_conductance_w_per_m2_k],     "envelope-skylights_average_conductance-W_per_m2_K", "?")
    store_data(runner,  qaqc[:envelope][:fdwr],                       "envelope-fdwr.ratio", "%")
    store_data(runner,  qaqc[:envelope][:srr],                        "envelope-srr.ratio", "%")
    
    #store peak watts for gas and elec
    store_data(runner,  qaqc[:meter_peaks][:electric_w] ,   "peak-electricy_power-watts", "W")
    store_data(runner,  qaqc[:meter_peaks][:natural_gas_w] ,"peak-natural_gas-watts", "W")

    # reporting final condition
    runner.registerFinalCondition("Saved BTAP results to runner.")
    return true
  end # end the run method
  
  
  def sanity_check(qaqc)
    qaqc[:sanity_check] = {}
    qaqc[:sanity_check][:fail] = []
    qaqc[:sanity_check][:pass] = []
    #Padmassun's code for isConditioned start
    qaqc[:thermal_zones].each do |zoneinfo|
      zoneinfo[:spaces].each do |space|
        if zoneinfo[:space_type_name].to_s.include?"Space Function - undefined -"
          if zoneinfo[:is_conditioned].to_s == "No"
            qaqc[:sanity_check][:pass] << "[TEST-PASS][SANITY_CHECK-PASS] for [SPACE][#{space[:name]}] and [THERMAL ZONE] [#{zoneinfo[:name]}] where isConditioned is supposed to be [""No""] and found as #{zoneinfo[:is_conditioned]}"
          else
            qaqc[:sanity_check][:fail] << "[ERROR][SANITY_CHECK-FAIL] for [SPACE][#{space[:name]}] and [THERMAL ZONE] [#{zoneinfo[:name]}] where isConditioned is supposed to be [""No""] but found as #{zoneinfo[:is_conditioned]}"
          end
        else
          if zoneinfo[:is_conditioned].to_s == "Yes"
            qaqc[:sanity_check][:pass] << "[TEST-PASS][SANITY_CHECK-PASS] for [SPACE][#{space[:name]}] and [THERMAL ZONE] [#{zoneinfo[:name]}] where isConditioned is supposed to be [""Yes""] and found as #{zoneinfo[:is_conditioned]}"
          else
            qaqc[:sanity_check][:fail] << "[ERROR][SANITY_CHECK-FAIL] for [SPACE][#{space[:name]}] and [THERMAL ZONE] [#{zoneinfo[:name]}] where isConditioned is supposed to be [""Yes""] but found as #{zoneinfo[:is_conditioned]}"
          end          
        end
      end
    end 
    qaqc[:sanity_check][:fail] = qaqc[:sanity_check][:fail].sort
    qaqc[:sanity_check][:pass] = qaqc[:sanity_check][:pass].sort
    #Padmassun's code for isConditioned end
  end
  
  
  def necb_2011_qaqc(qaqc)
    #Now perform basic QA/QC on items for necb 2011 
    qaqc[:information] = []
    qaqc[:warnings] =[]
    qaqc[:errors] = []
    qaqc[:unique_errors]=[]
    

    #    #Padmassun's Code Start
    csv_file_name ="#{File.dirname(__FILE__)}/resources/necb_2011_spacetype_info.csv"
    puts csv_file_name
    qaqc[:spaces].each do |space|
      building_type =""
      space_type =""
      if space[:space_type_name].include? 'Space Function '
        space_type = (space[:space_type_name].to_s.rpartition('Space Function '))[2].strip
        building_type = 'Space Function'
      elsif space[:space_type_name].include? ' WholeBuilding'
        space_type = (space[:space_type_name].to_s.rpartition(' WholeBuilding'))[0].strip
        building_type = 'WholeBuilding'
      end
      row = look_up_csv_data(csv_file_name,{2 => space_type, 1 => building_type})
      if row.nil?
        #raise ("space type of [#{space_type}] and/or building type of [#{building_type}] was not found in the excel sheet for space: [#{space[:name]}]")
        qaqc[:ruby_warnings] << "space type of [#{space_type}] and/or building type of [#{building_type}] was not found in the excel sheet for space: [#{space[:name]}]"
        puts "space type of [#{space_type}] and/or building type of [#{building_type}] was not found in the excel sheet for space: [#{space[:name]}]"
      else
        # Start of Space Compliance
        necb_section_name = "NECB2011-Section 8.4.3.6"
        data = {}
        data[:lighting_per_area]            = [ row[3],'==',space[:lighting_w_per_m2] , "Table 4.2.1.6"     ,1 ] unless space[:lighting_w_per_m2].nil?
        data[:occupancy_per_area]           = [ row[4],'==',space[:occ_per_m2]        , "Table A-8.4.3.3.1" ,3 ] unless space[:occ_per_m2].nil?
        data[:occupancy_schedule]           = [ row[5],'==',space[:occupancy_schedule], "Table A-8.4.3.3.1" ,nil ] unless space[:occupancy_schedule].nil?
        data[:electric_equipment_per_area]  = [ row[6],'==',space[:electric_w_per_m2] , "Table A-8.4.3.3.1" ,1 ] unless space[:electric_w_per_m2].nil?
        data.each do |key,value|
          #puts key
          necb_section_test(
            qaqc,
            value[0],
            value[1],
            value[2],
            value[3],
            "[SPACE][#{space[:name]}]-#{key}",
            value[4]
          )
        end
      end#space Compliance
    end
    #Padmassun's Code End
    

    # Envelope
    necb_section_name = "NECB2011-Section 3.2.1.4"
    #store hdd in short form
    hdd = qaqc[:geography][:hdd]
    #calculate fdwr based on hdd. 
    fdwr = 0
    if hdd < 4000
      fdwr = 0.40
    elsif hdd >= 4000 and hdd <=7000
      fdwr = (2000-0.2 * hdd)/3000
    elsif hdd >7000
      fdwr = 0.20
    end
    #hardset srr to 0.05 
    srr = 0.05
    #create table of expected values and results.
    data = {}
    data[:fenestration_to_door_and_window_percentage]  = [ fdwr * 100,qaqc[:envelope][:fdwr].round(3)]
    data[:skylight_to_roof_percentage]  = [  srr * 100,qaqc[:envelope][:srr].round(3)]
    #perform test. result must be less than or equal to.
    data.each {|key,value| necb_section_test( 
        qaqc, 
        value[0],
        '>=',
        value[1],
        necb_section_name,
        "[ENVELOPE]#{key}",
        1 #padmassun added tollerance
      )
    }

    #Infiltration
    necb_section_name = "NECB2011-Section 8.4.3.6"
    qaqc[:spaces].each do |spaceinfo|
      data = {}
      data[:infiltration_method]    = [ "Flow/ExteriorArea", spaceinfo[:infiltration_method] , nil ] 
      data[:infiltration_flow_per_m2] = [ 0.00025,       spaceinfo[:infiltration_flow_per_m2], 5 ]
      data.each do |key,value|
        #puts key
        necb_section_test( 
          qaqc,
          value[0],
          '==',
          value[1],
          necb_section_name,
          "[SPACE][#{spaceinfo[:name]}]-#{key}",
          value[2]
        )
      end
    end
    #Exterior Opaque
    necb_section_name = "NECB2011-Section 3.2.2.2"
    climate_index = BTAP::Compliance::NECB2011::get_climate_zone_index(qaqc[:geography][:hdd])
    result_value_index = 6
    round_precision = 3
    data = {}
    data[:ext_wall_conductances]        =  [0.315,0.278,0.247,0.210,0.210,0.183,qaqc[:envelope][:outdoor_walls_average_conductance_w_per_m2_k]] unless qaqc[:envelope][:outdoor_walls_average_conductance_w_per_m2_k].nil?
    data[:ext_roof_conductances]        =  [0.227,0.183,0.183,0.162,0.162,0.142,qaqc[:envelope][:outdoor_roofs_average_conductance_w_per_m2_k]] unless qaqc[:envelope][:outdoor_roofs_average_conductance_w_per_m2_k].nil?
    data[:ext_floor_conductances]       =  [0.227,0.183,0.183,0.162,0.162,0.142,qaqc[:envelope][:outdoor_floors_average_conductance_w_per_m2_k]] unless qaqc[:envelope][:outdoor_floors_average_conductance_w_per_m2_k].nil?
    
    data.each {|key,value| necb_section_test( 
        qaqc,
        value[result_value_index],
        '==',
        value[climate_index],
        necb_section_name,
        "[ENVELOPE]#{key}",
        round_precision
      )
    }
    #Exterior Fenestration
    necb_section_name = "NECB2011-Section 3.2.2.3"
    climate_index = BTAP::Compliance::NECB2011::get_climate_zone_index(qaqc[:geography][:hdd])
    result_value_index = 6
    round_precision = 3
    data = {}
    data[:ext_window_conductances]      =     [2.400,2.200,2.200,2.200,2.200,1.600,qaqc[:envelope][:windows_average_conductance_w_per_m2_k]] unless qaqc[:envelope][:windows_average_conductance_w_per_m2_k].nil?
    data[:ext_door_conductances]        =     [2.400,2.200,2.200,2.200,2.200,1.600,qaqc[:envelope][:doors_average_conductance_w_per_m2_k]]   unless qaqc[:envelope][:doors_average_conductance_w_per_m2_k].nil?
    data[:ext_overhead_door_conductances] =   [2.400,2.200,2.200,2.200,2.200,1.600,qaqc[:envelope][:overhead_doors_average_conductance_w_per_m2_k]] unless qaqc[:envelope][:overhead_doors_average_conductance_w_per_m2_k].nil?
    data[:ext_skylight_conductances]  =       [2.400,2.200,2.200,2.200,2.200,1.600,qaqc[:envelope][:skylights_average_conductance_w_per_m2_k]] unless qaqc[:envelope][:skylights_average_conductance_w_per_m2_k].nil?
    data.each do |key,value|
  
      #puts key
      necb_section_test( 
        qaqc,
        value[result_value_index].round(round_precision),
        '==',
        value[climate_index].round(round_precision),
        necb_section_name,
        "[ENVELOPE]#{key}",
        round_precision
      )
    end    
    #Exterior Ground surfaces
    necb_section_name = "NECB2011-Section 3.2.3.1"
    climate_index = BTAP::Compliance::NECB2011::get_climate_zone_index(qaqc[:geography][:hdd])
    result_value_index = 6
    round_precision = 3
    data = {}
    data[:ground_wall_conductances]  = [ 0.568,0.379,0.284,0.284,0.284,0.210, qaqc[:envelope][:ground_walls_average_conductance_w_per_m2_k] ]  unless qaqc[:envelope][:ground_walls_average_conductance_w_per_m2_k].nil?
    data[:ground_roof_conductances]  = [ 0.568,0.379,0.284,0.284,0.284,0.210, qaqc[:envelope][:ground_roofs_average_conductance_w_per_m2_k] ]  unless qaqc[:envelope][:ground_roofs_average_conductance_w_per_m2_k].nil?
    data[:ground_floor_conductances] = [ 0.757,0.757,0.757,0.757,0.757,0.379, qaqc[:envelope][:ground_floors_average_conductance_w_per_m2_k] ] unless qaqc[:envelope][:ground_floors_average_conductance_w_per_m2_k].nil?
    data.each {|key,value| necb_section_test( 
        qaqc,
        value[result_value_index],
        '==',
        value[climate_index],
        necb_section_name,
        "[ENVELOPE]#{key}",
        round_precision
      )
    }
    #Zone Sizing and design supply temp tests
    necb_section_name = "NECB2011-?"
    qaqc[:thermal_zones].each do |zoneinfo|
      data = {}
      data[:heating_sizing_factor] = [1.3 , zoneinfo[:heating_sizing_factor]]
      data[:cooling_sizing_factor] = [1.1 ,zoneinfo[:cooling_sizing_factor]]
      data[:heating_design_supply_air_temp] =   [43.0, zoneinfo[:zone_heating_design_supply_air_temperature] ] #unless zoneinfo[:zone_heating_design_supply_air_temperature].nil?
      data[:cooling_design_supply_temp]   =   [13.0, zoneinfo[:zone_cooling_design_supply_air_temperature] ]
      data.each do |key,value| 
        #puts key
        necb_section_test( 
          qaqc,
          value[0],
          '==',
          value[1],
          necb_section_name,
          "[ZONE][#{zoneinfo[:name]}] #{key}",
          round_precision
        )
      end
    end 
    #Air flow sizing check
    qaqc[:air_loops].each do |air_loop_info|
      air_loop_info[:name] 
      air_loop_info[:thermal_zones] 
      air_loop_info[:total_floor_area_served] 
    end
  end
end # end the measure

# this allows the measure to be use by the application
BTAPResults.new.registerWithApplication
