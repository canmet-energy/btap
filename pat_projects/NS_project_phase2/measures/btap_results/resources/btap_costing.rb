require 'json'
require 'zlib'

class Hash
  def deep_find(key, object=self, found=[])
    if object.respond_to?(:key?) && object.key?(key)
      found << object
    end
    if object.is_a? Enumerable
      found << object.collect { |*a| deep_find(key, a.last) }
    end
    found.flatten.compact
  end
end

class SimpleLinearRegression
  #https://gist.github.com/rweald/3516193#file-full-slr-class-snippet-rb
  def initialize(xs, ys)
    @xs, @ys = xs, ys
    if @xs.length != @ys.length
      raise "Unbalanced data. xs need to be same length as ys"
    end
  end

  def y_intercept
    return mean(@ys) - (slope * mean(@xs))
  end

  def slope
    x_mean = mean(@xs)
    y_mean = mean(@ys)

    numerator = (0...@xs.length).reduce(0) do |sum, i|
      sum + ((@xs[i] - x_mean) * (@ys[i] - y_mean))
    end

    denominator = @xs.reduce(0) do |sum, x|
      sum + ((x - x_mean) ** 2)
    end

    return (numerator / denominator)
  end

  def mean(values)
    total = values.reduce(0) { |sum, x| x + sum }
    return Float(total) / Float(values.length)
  end
end


class BTAPCosting
  PATH_TO_COSTING_DATA = './'
  PATH_TO_GLOBAL_RESOURCES = '../../../resources/'
  attr_accessor :costing_database
  def initialize()
    # paths to files all set here.
    @rs_means_auth_hash_path = "#{File.dirname(__FILE__)}/#{PATH_TO_COSTING_DATA}/rs_means_auth"
    @xlsx_path = "#{File.dirname(__FILE__)}/#{PATH_TO_GLOBAL_RESOURCES}/national_average_cost_information.xlsm"
    @costing_database_filepath_zip = "#{File.dirname(__FILE__)}/#{PATH_TO_COSTING_DATA}/costing_database.json.gz"
    @costing_database_filepath_rsmeans_zip = "#{File.dirname(__FILE__)}/#{PATH_TO_COSTING_DATA}/costing_database_rsmeans.json.gz"
    @costing_database_filepath_rsmeans_json = "#{File.dirname(__FILE__)}/#{PATH_TO_COSTING_DATA}/costing_database_rsmeans.json"
    @costing_database_filepath_dummy_zip = "#{File.dirname(__FILE__)}/#{PATH_TO_COSTING_DATA}/costing_database.json.gz"
    @costing_database_filepath_dummy_json = "#{File.dirname(__FILE__)}/#{PATH_TO_COSTING_DATA}/costing_database.json"
    @error_log = "#{File.dirname(__FILE__)}/#{PATH_TO_COSTING_DATA}/errors.json"
    @cost_output_file = "#{File.dirname(__FILE__)}/#{PATH_TO_COSTING_DATA}/cost_output.json"
    @mech_sizing_data_file = "#{File.dirname(__FILE__)}/#{PATH_TO_COSTING_DATA}/mech_sizing.json"
  end

  def load_database()
    Zlib::GzipReader.open(@costing_database_filepath_zip ) { |gz|
      @costing_database = JSON.parse(gz.read)
    }
  end


  def create_database()
    # Keeping track of start time.
    start = Time.now
    # Set rs-means auth hash to nil.
    File.delete(@costing_database_filepath_rsmeans_zip) if File.exist?(@costing_database_filepath_rsmeans_zip)
    File.delete(@costing_database_filepath_rsmeans_json) if File.exist?(@costing_database_filepath_rsmeans_json)
    File.delete(@error_log) if File.exist?(@error_log)
    @auth_hash = nil
    # Create a hash to store items in excel database that could not be found in RSMeans api.
    @not_found_in_rsmeans_api = Array.new
    # Create costing database hash.
    @costing_database = Hash.new()
    # Read secret rsmeans hash if already run.
    if File.exist?(@rs_means_auth_hash_path)
      @auth_hash = File.read(@rs_means_auth_hash_path).strip
    else
      # Try to authenticate with rs-means.
      self.authenticate_rs_means_v1()
    end

    # Load all data from excel
    self.load_data_from_excel()
    self.validate_constructions_sets()
    # Get materials costing from rs-means and adjust using costing scaling factors for material and labour.
    self.generate_materials_cost_database()

    # Some user information.
    puts "Cost Database regenerated in #{Time.now - start} seconds"
    puts "#{@costing_database['rsmean_api_data'].size} Unique RSMeans items."
    puts "#{@costing_database['raw']['rsmeans_locations'].size} Canadian Locations Available."

    # If there are errors, write to @error_log
    unless @costing_database['rs_mean_errors'].empty?
      File.open(@error_log, "w") do |f|
        f.write(JSON.pretty_generate(@costing_database['rs_mean_errors']))
      end
      puts "#{@costing_database['rs_mean_errors'].size} Errors in Parsing Costing! See #{@error_log} for listing of errors."
    end

    Zlib::GzipWriter.open(@costing_database_filepath_rsmeans_zip) do |fo|
      fo.write(JSON.pretty_generate(@costing_database))
    end

    File.open(@costing_database_filepath_rsmeans_json, "w") do |f|
      f.write(JSON.pretty_generate(@costing_database))
    end
  end

  def create_dummy_database()
    File.delete(@costing_database_filepath_dummy_zip) if File.exist?(@costing_database_filepath_dummy_zip)
    File.delete(@costing_database_filepath_dummy_json) if File.exist?(@costing_database_filepath_dummy_json)
    # Replace RSMean data with dummy values.
    key = "materialOpCost"
    @costing_database.deep_find(key).each {|item| item[key] = 0.0}
    key = "laborOpCost"
    @costing_database.deep_find(key).each {|item| item[key] = 0.0}
    key = "equipmentOpCost"
    @costing_database.deep_find(key).each {|item| item[key] = 0.0}
    key = "material"
    @costing_database.deep_find(key).each {|item| item[key] = 0.0}
    key = "installation"
    @costing_database.deep_find(key).each {|item| item[key] = 0.0}
    key = "total"
    @costing_database.deep_find(key).each {|item| item[key] = 0.0}

    # Write database to file.
    require 'zlib'
    Zlib::GzipWriter.open(@costing_database_filepath_dummy_zip) do |fo|
      fo.write(JSON.pretty_generate(@costing_database))
    end

    File.open(@costing_database_filepath_dummy_json, "w") do |f|
      f.write(JSON.pretty_generate(@costing_database))
    end
  end


  def authenticate_rs_means_v1()
    puts '
       Your RSMeans Bearer code is out of date. It usually lasts 60 minutes.  Please do the following.
       1. Use Chrome and go here https://dataapi-sb.gordian.com/swagger/ui/index.html#!/CostData-Assembly-Catalogs/CostdataAssemblyCatalogsGet
       2. Click on the the off switch at the top right corner of the first table open.
       3. Select the checkbox rsm_api:costdata.
       4. Click authorize.
       5. Enter your rsmeans api username and password when prompted.
       6. When you return to the main page, click the "try it out" button at the bottom left of the first table.
       7. Copy the entire string in the curl command field.
       8. Paste it below.
      '

    puts "Paste RSMeans API Curl String and hit enter:"
    rs_auth_bearer = STDIN.gets.chomp
    #rs_auth_bearer ="curl -X GET --header 'Accept: application/json' --header 'Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsIng1dCI6Iml1MXFMSTVnbEM2RVBZMi1YbmF0TFBjVVFhRSIsImtpZCI6Iml1MXFMSTVnbEM2RVBZMi1YbmF0TFBjVVFhRSJ9.eyJpc3MiOiJodHRwczovL2xvZ2luLmdvcmRpYW4uY29tIiwiYXVkIjoiaHR0cHM6Ly9sb2dpbi5nb3JkaWFuLmNvbS9yZXNvdXJjZXMiLCJleHAiOjE1NDUwMDk5NzUsIm5iZiI6MTU0NTAwNjM3NSwiY2xpZW50X2lkIjoicnNtLWFwaSIsImNsaWVudF9yb2xlIjoicnNtLWFwaS1jdXN0b21lciIsInNjb3BlIjpbInJzbV9hcGk6Y29zdGRhdGEiLCJyc21fYXBpOmN0Y2RhdGEiXSwic3ViIjoiOWI0NzdiMGEtMjBkZS00ODZmLWFiMTItYzI4YmI3NzEwODE5IiwiYXV0aF90aW1lIjoxNTQ1MDAwMjYxLCJpZHAiOiJpZHNydiIsInByZWZlcnJlZF91c2VybmFtZSI6ImplZmYuYmxha2VAY2FuYWRhLmNhIiwiZVJvbGUiOiJGYWxzZSIsImFtciI6WyJwYXNzd29yZCJdfQ.cHqwHOUAR20xYIfHiTodtvx63F83V3PnVI_VfqESFu882h_orsn8EEfH1EO_H_Z5rxxuDbghse9cWQJJyUMEvn2zIYzZ25EXfIYPTQ0mj_AqDpqeR2mYN8BfehOLw1eWqfTbs4AKuhJ-PPE1nxKFN3_Jjyn-ECePTkPHj3PzeDlfIMJXGcONOr2JJmz4fk4elBQU2uVIMOvRKjUC3WZuFdP6MlUZn_JnSisVn2EPtcwWcb2yybFlrm1H9xIvFuxDniKFWXmf-PalHslO8dMi57xjh0VVild-cl_Pyc72Iw8B_E-6q0IIWdD0A7EkyV70XPfSvc89PnJa-WNJ9ytS_w' 'https://dataapi-sb.gordian.com/v1/costdata/assembly/catalogs'"

    puts "you entered.."
    puts rs_auth_bearer
    m = rs_auth_bearer.match(/.*Bearer (?<bearer>[^']+).*$/)

    #Store to disk to subsequent runs if required.
    File.write(@rs_means_auth_hash_path, m[:bearer].to_s.strip)
    @auth_hash = File.read(@rs_means_auth_hash_path).strip
  end

  def load_data_from_excel

    @costing_database = {} if @costing_database.nil?
    unless File.exist?(@xlsx_path)
      raise("could not find the national_average_cost_information.xlsm in location #{@xlsx_path}. This is a proprietary file manage by Natural resources Canada.")
    end

    #Get Raw Data from files.
    @costing_database['rsmean_api_data']= Array.new
    @costing_database['raw'] = {}
    @costing_database['rs_mean_errors']=[]
    ['rsmeans_locations',
     'rsmeans_local_factors',
     'construction_sets',
     'constructions_opaque',
     'materials_opaque',
     'constructions_glazing',
     'materials_glazing',
     'Constructions',
     'ConstructionProperties',
     'lighting_sets',
     'lighting',
     'materials_lighting',
     'hvac_vent_ahu',
     'materials_hvac'
    ].each do |sheet|
      @costing_database['raw'][sheet] = convert_workbook_sheet_to_array_of_hashes(@xlsx_path, sheet)
    end

  end


  # This method iterates through all the items in the materials spreadsheet and determines the RSMeans standard city
  # costs and stores it. There is a LOT of information that could be stored from RSMeans. We are trying to be very
  # data-efficient as every bytes counts downloading and uploading from CANMET Ottawa. For this reason we are only grabbing
  # the material id, catalog id and basecosts data hash. Even that may be too much.
  def generate_materials_cost_database(dummy = false)
    require 'rest-client'
    [@costing_database['raw']['materials_glazing'], @costing_database['raw']['materials_opaque'], @costing_database['raw']['materials_lighting'], @costing_database['raw']['materials_hvac']].each do |mat_lib|
      [mat_lib].each do |materials|

        lookup_list = materials.map {|material|
          {'type' => material['type'],
           'catalog_id' => material['catalog_id'],
           'id' => material['id']}
        }

        lookup_list.each do |material|
          # check if it's already in our database with right catalog year.
          api_return = @costing_database['rsmean_api_data'].detect {|rs_means|
            rs_means['id'] == material['id'] and rs_means['catalog']['id'] == material['catalog_id']
          }
          unless api_return.nil?
            puts "skipping duplicate entry #{material["id"]}"
            next
          end

          auth = {:Authorization => "bearer #{@auth_hash}"}
          path = "https://dataapi-sb.gordian.com/v1/costdata/#{material['type'].downcase.strip}/catalogs/#{material['catalog_id'].strip}/costlines/#{material['id'].strip}"


          begin
            api_return = JSON.parse(RestClient.get(path, auth).body)
            basecosts = nil
            if dummy == true
               basecosts =  {
                       "materialOpCost" => 1.0,
                       "laborOpCost" => 1.0,
                       "equipmentOpCost" => 1.0
               }
            else
              basecosts = {
                  "materialOpCost" => api_return['baseCosts']["materialOpCost" ],
                  "laborOpCost" => api_return['baseCosts']["laborOpCost"],
                  "equipmentOpCost" => api_return['baseCosts']["equipmentOpCost" ],
              }
            end
            filtered_return = { 'id' => material['id'],
                                'catalog' => { "id"=> material['catalog_id'] },
                                'description' => api_return['description'],
                                'baseCosts' => basecosts
            }
            @costing_database['rsmean_api_data'] << filtered_return

          rescue Exception => e
            if e.to_s.strip == "401 Unauthorized"
              self.authenticate_rs_means_v1()
            elsif e.to_s.strip == "404 Not Found"
              material['error'] = e
              @costing_database['rs_mean_errors'] << [material, e.to_s.strip]
            else
              raise("Error Occured #{e}")
            end
          end
          puts "Obtained #{material['id']} costing"
          raise('rs_means_database empty! ') if @costing_database['rsmean_api_data'].empty?
        end
      end
    end
  end


  def generate_construction_cost_database_for_all_cities()
    @costing_database['constructions_costs']= Array.new
    @costing_database['raw']['rsmeans_locations'].each do |location|
      rs_means_province_state = location["province-state"]
      rs_means_city = location['city']
      generate_construction_cost_database_for_city(rs_means_city, rs_means_province_state)
    end
  end

  def generate_construction_cost_database_for_city(rs_means_city, rs_means_province_state)
    @costing_database['constructions_costs']= Array.new
    puts "Costing for: #{rs_means_province_state},#{rs_means_city}"
    @costing_database["raw"]['constructions_opaque'].each do |construction|
      cost_construction(construction, {"province-state" => rs_means_province_state, "city" => rs_means_city}, 'opaque')
    end
    @costing_database["raw"]['constructions_glazing'].each do |construction|
      cost_construction(construction, {"province-state" => rs_means_province_state, "city" => rs_means_city}, 'glazing')
    end
    puts "#{@costing_database['constructions_costs'].size} Costed Constructions for #{rs_means_province_state},#{rs_means_city}."
  end


  def cost_audit_all(model, prototype_creator)
    # Create a Hash to collect costing data.
    @costing_report = {}
    #Use closest RSMeans city.
    closest_loc = get_closest_cost_location(model.getWeatherFile.latitude, model.getWeatherFile.longitude)
    @costing_report['rs_means_city']= closest_loc['city']
    @costing_report['rs_means_prov']= closest_loc['province-state']
    # Create a Hash in the hash for categories of costing.
    @costing_report['envelope'] = {}
    @costing_report['lighting'] = {}
    @costing_report['heating_and_cooling'] = {}
    @costing_report['heating_and_cooling']['plant_equipment'] = []
    @costing_report['heating_and_cooling']['zonal_systems'] = []
    @costing_report['shw'] = {}
    @costing_report['ventilation'] = {}
    @costing_report['totals'] = {}

    # Check to see if standards building type and the number of stories has been defined.  The former may be omitted in the future.
    if model.getBuilding.standardsBuildingType.empty? or model.getBuilding.standardsNumberOfAboveGroundStories.empty?
      raise("Building information is not complete, please ensure that the standardsBuildingType and standardsNumberOfAboveGroundStories are entered in the model. ")
    end

    envCost = self.cost_audit_envelope(model, prototype_creator)
    lgtCost = self.cost_audit_lighting(model, prototype_creator)
    boilerCost = self.boiler_costing(model, prototype_creator)
    chillerCost = self.chiller_costing(model, prototype_creator)
    coolingTowerCost = self.coolingtower_costing(model, prototype_creator)
    shwCost = self.shw_costing(model, prototype_creator)
    ventCost = self.ventilation_costing(model, prototype_creator)
    zonalSystemCost = self.zonalsys_costing(model, prototype_creator)

    @costing_report["totals"] = {
      'envelope' => envCost.round(2),
      'lighting' => lgtCost.round(2),
      'heating_and_cooling' => (boilerCost + chillerCost + coolingTowerCost + zonalSystemCost).round(2),
      'shw' => shwCost.round(2),
      'ventilation' => ventCost.round(2),
      'grand_total' => (envCost + lgtCost + boilerCost + chillerCost + coolingTowerCost +
          shwCost + ventCost + zonalSystemCost).round(2)
    }

    return @costing_report
  end

  #This will convert a sheet in a given workbook into an array of hashes with the headers as symbols.
  def convert_workbook_sheet_to_array_of_hashes(xlsx_path, sheet_name)
    require 'roo'
    #Load Constructions data sheet from workbook and convert to a csv object.
    data = Roo::Spreadsheet.open(xlsx_path).sheet(sheet_name).to_csv
    csv = CSV.new(data, {headers: true})
    return csv.to_a.map {|row| row.to_hash}
  end

  def get_regional_cost_factors(provinceState, city, material)
    @costing_database['raw']['rsmeans_local_factors'].select {|code|
      code['province-state'] == provinceState && code['city'] == city}.each do |code|
      id = material['id'].to_s
      prefixes = code['code_prefixes'].split(',')
      prefixes.each do |prefix|
        if id.start_with?(prefix.strip)
          return code['material'].to_f, code['installation'].to_f
        end
      end
    end
    error = [material, "Could not find regional adjustment factor for rs-means material used in #{city}, #{provinceState}."]
    @costing_database['rs_mean_errors'] << error unless @costing_database['rs_mean_errors'].include?(error)
    return 100.0, 100.0
  end


  # Interpolate array of hashes that contain 2 values (key=rsi, data=cost)
  def interpolate(x_y_array:, x2:, exterpolate_percentage_range: 30.0)
    ratio_range = exterpolate_percentage_range / 100.0
    array = x_y_array.uniq.sort {|a, b| a[0] <=> b[0]}
    #if there is only one...return what you got.
    if array.size == 1
      return array.first[1].to_f
    end
    # Check if value x2 is within range of array for interpolation
    # Extrapolate when x2 is out-of-range by +/- 10% of end values.
    if array.empty? || x2 < ((1.0 - ratio_range) * array.first[0].to_f) || x2 > ( (1.0 + ratio_range) * array.last[0].to_f)
      return nil
    elsif x2 < array.first[0].to_f
      # Extrapolate down using first and second cost value to this out-of-range input
      x_array = [array[0][0].to_f, array[1][0].to_f]
      y_array = [array[0][1].to_f, array[1][1].to_f]
      linear_model = SimpleLinearRegression.new(x_array, y_array)
      y2 = linear_model.y_intercept + linear_model.slope * x2
      return y2
    elsif x2 > array.last[0].to_f
      # Extrapolate up using second to last and last cost value to this out-of-range input
      x_array = [array[-2][0].to_f, array[-1][0].to_f]
      y_array = [array[-2][1].to_f, array[-1][1].to_f]
      linear_model = SimpleLinearRegression.new(x_array, y_array)
      y2 = linear_model.y_intercept + linear_model.slope * x2
      return y2
    else
      array.each_index do |counter|

        # skip last value.
        next if array[counter] == array.last

        x0 = array[counter][0]
        y0 = array[counter][1]
        x1 = array[counter + 1][0]
        y1 = array[counter + 1][1]

        # skip to next if x2 is not between x0 and x1
        next if x2 < x0 || x2 > x1

        # Do interpolation
        y2 = y0 # just in-case x0, x1 and x2 are identical!
        if (x1 - x0) > 0.0
          y2 = y0.to_f + ((y1 - y0).to_f * (x2 - x0).to_f / (x1 - x0).to_f)
        end
        return y2
      end
    end
  end

  # Enter in [latitude, longitude] for each loc and this method will return the distance.
  def distance(loc1, loc2)
    rad_per_deg = Math::PI/180 # PI / 180
    rkm = 6371 # Earth radius in kilometers
    rm = rkm * 1000 # Radius in meters

    dlat_rad = (loc2[0]-loc1[0]) * rad_per_deg # Delta, converted to rad
    dlon_rad = (loc2[1]-loc1[1]) * rad_per_deg

    lat1_rad, lon1_rad = loc1.map {|i| i * rad_per_deg}
    lat2_rad, lon2_rad = loc2.map {|i| i * rad_per_deg}

    a = Math.sin(dlat_rad/2)**2 + Math.cos(lat1_rad) * Math.cos(lat2_rad) * Math.sin(dlon_rad/2)**2
    c = 2 * Math::atan2(Math::sqrt(a), Math::sqrt(1-a))
    rm * c # Delta in meters
  end

  def get_closest_cost_location(lat, long)
    dist = 1000000000000000000000.0
    closest_loc = nil
    # province-state	city	latitude	longitude	source
    @costing_database['raw']['rsmeans_locations'].each do |location|
      if distance([lat, long], [location['latitude'].to_f, location['longitude'].to_f]) < dist
        closest_loc = location
        dist = distance([lat, long], [location['latitude'].to_f, location['longitude'].to_f])
      end
    end
    return closest_loc
  end

  # This will expand the two letter province abbreviation to a full uppercase province name
  def expandProvAbbrev(abbrev)

    # Note that the proper abbreviation for Quebec is QC not PQ. However, we've used PQ in openstudio-standards!
    Hash provAbbrev = {"AB" => "ALBERTA",
                       "BC" => "BRITISH COLUMBIA",
                       "MB" => "MANITOBA",
                       "NB" => "NEW BRUNSWICK",
                       "NL" => "NEWFOUNDLAND AND LABRADOR",
                       "NT" => "NORTHWEST TERRITORIES",
                       "NS" => "NOVA SCOTIA",
                       "NU" => "NUNAVUT",
                       "ON" => "ONTARIO",
                       "PE" => "PRINCE EDWARD ISLAND",
                       "PQ" => "QUEBEC",
                       "SK" => "SASKATCHEWAN",
                       "YT" => "YUKON"
    }
    return provAbbrev[abbrev]
  end

  def read_mech_sizing()
    file = File.read(@mech_sizing_data_file)
     return JSON.parse(file)
  end

end











