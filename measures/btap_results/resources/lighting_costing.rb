class BTAPCosting

  def cost_audit_lighting(model)
    # Store number of stories. Required for envelope costing logic.
    num_of_above_ground_stories = model.getBuilding.standardsNumberOfAboveGroundStories.to_i

    closest_loc = get_closest_cost_location(model.getWeatherFile.latitude, model.getWeatherFile.longitude)
    generate_construction_cost_database_for_city(@costing_report["rs_means_city"],@costing_report["rs_means_prov"])

    totLgtCost = 0
    total_with_op = 0.0

    # Iterate through the thermal zones.
    model.getThermalZones.sort.each do |zone|
      # Iterate through spaces.
      zone.spaces.sort.each do |space|
        # Get SpaceType defined for space.. if not defined it will skip the spacetype. May have to deal with Attic spaces.
        if space.spaceType.empty? or space.spaceType.get.standardsSpaceType.empty? or space.spaceType.get.standardsBuildingType.empty?
          raise ("standards Space type and building type is not defined for space:#{space.name.get}. Skipping this space for costing.")
        end

        # Get space type standard names.
        template_type = "NECB2011"  # Hardcoded until get template from model
        space_type = space.spaceType.get.standardsSpaceType
        building_type = space.spaceType.get.standardsBuildingType

        # Get standard lighting sets based on collected information (spacetype, no of stories, etc..)
        lighting_set = @costing_database['raw']['lighting_sets'].select {|data|
          data['template'].to_s.gsub(/\s*/, '') == template_type and
              data['building_type'].to_s == building_type.to_s and
              data['space_type'].to_s == space_type.to_s and
              data['min_stories'].to_i <= num_of_above_ground_stories and
              data['max_stories'].to_i >= num_of_above_ground_stories
        }.first

        # Determine average space height using space volume and floor area (convert to feet)
        ceilHgt = 0
        floorArea = 0
        if space.floorArea > 0
          ceilHgt = space.volume / space.floorArea
          ceilHgt = OpenStudio::convert(ceilHgt,"m","ft").get
          floorArea = OpenStudio::convert(space.floorArea,"m","ft").get
        end

        # Find Fixture type for this space ceiling height (ft)
        fixtureType = "Nil"
        if ceilHgt > 0 && ceilHgt < 7.88
          fixtureType = lighting_set["Fixture_type_less_than_7.88ft_ht"]
        elsif ceilHgt >= 7.88 && ceilHgt <= 15.75
          fixtureType = lighting_set["Fixture_type_7.88_to_15.75ft_ht"]
        elsif ceilHgt > 15.75
          fixtureType = lighting_set["Fixture_type_greater_than_>15.75ft_ht"]
        end

        if fixtureType == "Nil"
          # Set costs to 0 because no fixture type due to either zero floor area, zero ceiling height or a "Nil"
          # setting for fixture type in lighting_sets sheet ("- undefined -" space)
          total_with_op = 0.0
        else
          # Get lighting type sets based on fixtureType
          lighting_type = @costing_database['raw']['lighting'].select {|lighting_layer_data|
            lighting_layer_data['lighting_type_id'].to_s == fixtureType.to_s
          }.first

          # Scan through layer IDs in id_layers field to get RS Means data from materials_lighting sheet
          materials_lighting_database = @costing_database["raw"]["materials_lighting"]

          layer_type_IDs = []
          layer_type_mult = []

          if lighting_type["id_layers"].empty?
            raise ("Lighting type layers list for lighting type ID #{fixtureType} is empty.")
          else
            layer_type_IDs = lighting_type["id_layers"].split(/\s*,\s*/)
            layer_type_mult = lighting_type["Id_layers_quantity_multipliers"].split(/\s*,\s*/)
            lighting_layers = layer_type_IDs.zip(layer_type_mult).to_h

            lighting_layers.each do |layer_id, layer_mult|
              # Note: The column in the spreadsheet labelled "lighting_type_id" is mislabelled and should
              # really be "lighting_type_layer_id" but left it as-is (below).
              lighting_material = materials_lighting_database.find do |data|
                data["lighting_type_id"].to_s == layer_id.to_s
              end
              if lighting_material.nil?
                puts "Lighting material error..could not find lighting material #{layer_id} in #{materials_lighting_database}"
                raise()
              else
                rs_means_data = @costing_database['rsmean_api_data'].detect {|data| data['id'].to_s.upcase == lighting_material['id'].to_s.upcase}
                if rs_means_data.nil?
                  puts "Lighting material id #{lighting_material['id']} not found in rs-means api. Skipping."
                  raise()
                else
                  regional_material, regional_installation =
                      get_regional_cost_factors(@costing_report["rs_means_prov"], @costing_report["rs_means_city"],
                                                lighting_material)

                  # Get RSMeans cost information from lookup.
                  material_cost = rs_means_data['baseCosts']['materialOpCost'].to_f * layer_mult.to_f *
                      floorArea * zone.multiplier
                  labour_cost = rs_means_data['baseCosts']['labourOpCost'].to_f * layer_mult.to_f *
                      floorArea * zone.multiplier
                  equipment_cost = rs_means_data['baseCosts']['equipmentOpCost'].to_f
                  layer_cost = ((material_cost * regional_material / 100.0) +
                      (labour_cost * regional_installation / 100.0) + equipment_cost).round(2)
                  total_with_op += layer_cost
                end
              end
            end # lighting layer ids
          end # lighting layer ids check
        end
      end # spaces
    end # thermalzone

    totLgtCost += total_with_op
    @costing_report["lighting"]['total_lighting_cost'] = totLgtCost

    return totLgtCost
  end

end