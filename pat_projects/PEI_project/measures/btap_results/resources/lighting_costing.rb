class BTAPCosting

  def cost_audit_lighting(model, prototype_creator)
    # Store number of stories. Required for envelope costing logic.
    num_of_above_ground_stories = model.getBuilding.standardsNumberOfAboveGroundStories.to_i

    template_type = prototype_creator.template

    closest_loc = get_closest_cost_location(model.getWeatherFile.latitude, model.getWeatherFile.longitude)
    generate_construction_cost_database_for_city(@costing_report["rs_means_city"],@costing_report["rs_means_prov"])

    totLgtCost = 0

    # Iterate through the thermal zones.

    #Create Zonal report.
    @costing_report["lighting"]["fixture_report"] = []
    @costing_report["lighting"]["space_report"] = []
    model.getThermalZones.sort.each do |zone|
      # Iterate through spaces.
      spaceNum = 0  # Counting number of spaces for reporting
      total_with_region = 0
      zone.spaces.sort.each do |space|
        spaceNum += 1  # Counting number of spaces for reporting
        # Get SpaceType defined for space.. if not defined it will skip the spacetype. May have to deal with Attic spaces.
        if space.spaceType.empty? or space.spaceType.get.standardsSpaceType.empty? or space.spaceType.get.standardsBuildingType.empty?
          raise ("standards Space type and building type is not defined for space:#{space.name.get}. Skipping this space for costing.")
        end

        # Get space type standard names.
        space_type = space.spaceType.get.standardsSpaceType
        building_type = space.spaceType.get.standardsBuildingType

        # Get standard lighting sets based on collected information (spacetype, no of stories, etc..)
        lighting_set = @costing_database['raw']['lighting_sets'].detect {|data|
          data['template'].to_s.gsub(/\s*/, '') == template_type and
          data['building_type'].to_s.downcase == building_type.to_s.downcase and
          data['space_type'].to_s.downcase == space_type.to_s.downcase
        }

        # Determine average space height using space volume and floor area (convert to feet)
        ceilHgt, flrArea = 0
        if space.floorArea > 0
          ceilHgt = space.volume / space.floorArea
          ceilHgt = OpenStudio.convert(ceilHgt,"m","ft").get
          flrArea = OpenStudio.convert(space.floorArea,"m^2","ft^2").get
        end

        # Find Fixture type for this space ceiling height (ft)
        fixtureType = 'Nil'
        fixture_description = ""
        if lighting_set.nil?
          raise("Error: lighting_set empty for zone #{zone.name.to_s} and space type #{building_type} #{space_type.to_s}!")
        else
          if ceilHgt > 0 && ceilHgt < 7.88
            fixtureType = lighting_set["Fixture_type_less_than_7.88ft_ht"]
          elsif ceilHgt >= 7.88 && ceilHgt <= 15.75
            fixtureType = lighting_set["Fixture_type_7.88_to_15.75ft_ht"]
          elsif ceilHgt > 15.75
            fixtureType = lighting_set["Fixture_type_greater_than_>15.75ft_ht"]
          end
        end

        # Costs are 0 for 'Nil' because no fixture type due to either zero floor area, zero ceiling height or a 'Nil'
        # setting for fixture type in lighting_sets sheet ("- undefined -" space)
        if fixtureType != 'Nil'
          # Get lighting type sets based on fixtureType
          lighting_type = @costing_database['raw']['lighting'].select {|lighting_layer_data|
            lighting_layer_data['lighting_type_id'].to_s == fixtureType.to_s
          }.first

          # Scan through layer IDs in id_layers field to get RS Means data from materials_lighting sheet
          materials_lighting_database = @costing_database["raw"]["materials_lighting"]

          layer_type_IDs = []
          layer_type_mult = []
          layer_MaterialCost = 0
          layer_LabourCost = 0

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
                raise
              else
                rs_means_data = @costing_database['rsmean_api_data'].detect {|data| data['id'].to_s.upcase == lighting_material['id'].to_s.upcase}
                if rs_means_data.nil?
                  puts "Lighting material id #{lighting_material['id']} not found in rs-means api. Skipping."
                  raise
                else
                  # Get RSMeans cost information from lookup.
                  material_cost = rs_means_data['baseCosts']['materialOpCost'].to_f * layer_mult.to_f * flrArea * zone.multiplier
                  labour_cost = rs_means_data['baseCosts']['laborOpCost'].to_f * layer_mult.to_f * flrArea * zone.multiplier
                  layer_MaterialCost += material_cost
                  layer_LabourCost += labour_cost

                  regional_material, regional_installation =
                      get_regional_cost_factors(@costing_report["rs_means_prov"], @costing_report["rs_means_city"], lighting_material)
                  total_with_region = layer_MaterialCost * regional_material / 100.0 + layer_LabourCost * regional_installation / 100.0

                end # rs_means_data Nil check
              end # lighting_material Nil check
            end # lighting layer ids loop

            totLgtCost += total_with_region
            fixture_description = lighting_type["description"]
          end # lighting layer ids check
        end # fixtureType Nil check

        zName = zone.name.to_s

        # Create Lighting space report.
        @costing_report["lighting"]["space_report"] << {
            'space' => space.name.to_s,
            'zone' => zone.name.to_s,
            'building_type' =>space.spaceType.get.standardsBuildingType.to_s,
            'space_type' => space.spaceType.get.standardsSpaceType.to_s,
            'zone_multiplier' => space.multiplier,
            'fixture_type' => fixtureType,
            'fixture_desciption' => fixture_description,
            'height_avg_ft' => ceilHgt.round(1),
            'floor_area_ft2' => (flrArea * space.multiplier).round(1),
            'cost' => total_with_region.round(2),
            'cost_per_ft2' => (total_with_region / ( flrArea * space.multiplier )).round(2),
            'note' => ""
        }

        # Create Lighting Zonal report.
        lighting_fixture_report = @costing_report["lighting"]["fixture_report"].detect {|fixture_report| fixture_report["fixture_type"] == fixtureType}
        unless lighting_fixture_report.nil?
          lighting_fixture_report['floor_area_ft2'] = (lighting_fixture_report['floor_area_ft2'] + (flrArea * space.multiplier)).round(1)
          lighting_fixture_report['cost'] = (lighting_fixture_report['cost'] + total_with_region).round(2)
          lighting_fixture_report['cost_per_ft2'] = (lighting_fixture_report['cost'] / lighting_fixture_report['floor_area_ft2']).round(2)
          lighting_fixture_report['spaces'] << space.name.get
          lighting_fixture_report['number_of_spaces'] = lighting_fixture_report['spaces'].size
        else
          @costing_report["lighting"]["fixture_report"] << {
              'fixture_type' => fixtureType,
              'fixture_description' => fixture_description,
              'floor_area_ft2' => (flrArea * space.multiplier).round(1),
              'cost' => total_with_region.round(2),
              'cost_per_ft2' => (total_with_region / (flrArea * space.multiplier)).round(2),
              'spaces' => [space.name.get],
              'number_of_spaces' => 1
          }
        end
      end # Spaces loop
    end # thermalzone loop

    @costing_report["lighting"]['total_lighting_cost'] = totLgtCost.round(2)
    puts "\nLighting costing data successfully generated. Total lighting cost is $#{totLgtCost.round(2)}"

    return totLgtCost
  end
end