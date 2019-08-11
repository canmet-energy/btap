class BTAPCosting
  def cost_audit_envelope(model)

    # Store number of stories. Required for envelope costing logic.
    num_of_above_ground_stories = model.getBuilding.standardsNumberOfAboveGroundStories.to_i

    closest_loc = get_closest_cost_location(model.getWeatherFile.latitude, model.getWeatherFile.longitude)
    generate_construction_cost_database_for_city(@costing_report["rs_means_city"],@costing_report["rs_means_prov"])

    totEnvCost = 0

    # Iterate through the thermal zones.
    model.getThermalZones.sort.each do |zone|
      # Iterate through spaces.
      zone.spaces.sort.each do |space|
        # Get SpaceType defined for space.. if not defined it will skip the spacetype. May have to deal with Attic spaces.
        if space.spaceType.empty? or space.spaceType.get.standardsSpaceType.empty? or space.spaceType.get.standardsBuildingType.empty?
          raise ("standards Space type and building type is not defined for space:#{space.name.get}. Skipping this space for costing.")
        end

        # Get space type standard names.
        space_type = space.spaceType.get.standardsSpaceType
        building_type = space.spaceType.get.standardsBuildingType

        # Get standard constructions based on collected information (spacetype, no of stories, etc..)
        # This is a standard way to search a hash.
        construction_set = @costing_database['raw']['construction_sets'].select {|data|
          data['building_type'].to_s == building_type.to_s and
              data['space_type'].to_s == space_type.to_s and
              data['min_stories'].to_i <= num_of_above_ground_stories and
              data['max_stories'].to_i >= num_of_above_ground_stories
        }.first


        # Create Hash to store surfaces for this space by surface type
        surfaces = {}
        #Exterior
        exterior_surfaces = BTAP::Geometry::Surfaces::filter_by_boundary_condition(space.surfaces, "Outdoors")
        surfaces["ExteriorWall"] = BTAP::Geometry::Surfaces::filter_by_surface_types(exterior_surfaces, "Wall")
        surfaces["ExteriorRoof"]= BTAP::Geometry::Surfaces::filter_by_surface_types(exterior_surfaces, "RoofCeiling")
        surfaces["ExteriorFloor"] = BTAP::Geometry::Surfaces::filter_by_surface_types(exterior_surfaces, "Floor")
        # Exterior Subsurface
        exterior_subsurfaces = BTAP::Geometry::Surfaces::get_subsurfaces_from_surfaces(exterior_surfaces)
        surfaces["ExteriorFixedWindow"] = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(exterior_subsurfaces, ["FixedWindow"])
        surfaces["ExteriorOperableWindow"] = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(exterior_subsurfaces, ["OperableWindow"])
        surfaces["ExteriorSkylight"] = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(exterior_subsurfaces, ["Skylight"])
        surfaces["ExteriorTubularDaylightDiffuser"] = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(exterior_subsurfaces, ["TubularDaylightDiffuser"])
        surfaces["ExteriorTubularDaylightDome"] = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(exterior_subsurfaces, ["TubularDaylightDome"])
        surfaces["ExteriorDoor"] = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(exterior_subsurfaces, ["Door"])
        surfaces["ExteriorGlassDoor"] = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(exterior_subsurfaces, ["GlassDoor"])
        surfaces["ExteriorOverheadDoor"] = BTAP::Geometry::Surfaces::filter_subsurfaces_by_types(exterior_subsurfaces, ["OverheadDoor"])

        # Ground Surfaces
        ground_surfaces = BTAP::Geometry::Surfaces::filter_by_boundary_condition(space.surfaces, "Ground")
        surfaces["GroundContactWall"] = BTAP::Geometry::Surfaces::filter_by_surface_types(ground_surfaces, "Wall")
        surfaces["GroundContactRoof"] = BTAP::Geometry::Surfaces::filter_by_surface_types(ground_surfaces, "RoofCeiling")
        surfaces["GroundContactFloor"] = BTAP::Geometry::Surfaces::filter_by_surface_types(ground_surfaces, "Floor")

        # These are the only envelope costing items we are considering for envelopes..
        costed_surfaces = [
            "ExteriorWall",
            "ExteriorRoof",
            "ExteriorFloor",
            "ExteriorFixedWindow",
            "ExteriorOperableWindow",
            "ExteriorSkylight",
            "ExteriorTubularDaylightDiffuser",
            "ExteriorTubularDaylightDome",
            "ExteriorDoor",
            "ExteriorGlassDoor",
            "ExteriorOverheadDoor",
            "GroundContactWall",
            "GroundContactRoof",
            "GroundContactFloor"
        ]

        # Iterate through
        costed_surfaces.each do |surface_type|
          # Get Costs for this construction type. This will get the cost for the particular construction type
          # for all rsi levels for this location. This has been collected by RS means. Note that a space_type
          # of "- undefined -" will create a nil construction_set!
          if construction_set.nil?
            cost_range_hash = {}
          else
            cost_range_hash = @costing_database['constructions_costs'].select {|construction|
              construction['construction_type_name'] == construction_set[surface_type] &&
                  construction['province-state'] == @costing_report["rs_means_prov"] &&
                  construction['city'] == @costing_report["rs_means_city"]
            }
          end

          # We don't need all the information, just the rsi and cost. However, for windows rsi = 1/u_w_per_m2_k
          surfaceIsGlazing = (surface_type == 'ExteriorFixedWindow' || surface_type == 'ExteriorOperableWindow' ||
              surface_type == 'ExteriorSkylight' || surface_type == 'ExteriorTubularDaylightDiffuser' ||
              surface_type == 'ExteriorTubularDaylightDome' || surface_type == 'ExteriorGlassDoor')
          if surfaceIsGlazing
            cost_range_array = cost_range_hash.map {|cost|
              [
                  (1.0/cost['u_w_per_m2_k'].to_f),
                  cost['total_cost_with_op']
              ]
            }
          else
            cost_range_array = cost_range_hash.map {|cost|
              [
                  cost['rsi_k_m2_per_w'],
                  cost['total_cost_with_op']
              ]
            }
          end
          # Sorted based on rsi.
          cost_range_array.sort! {|a, b| a[0] <=> b[0]}

          # Iterate through actual surfaces in the model of surface_type.
          numSurfType = 0
          surfaces[surface_type].sort.each do |surface|
            numSurfType = numSurfType + 1

            # Get RSI of existing model surface (actually returns rsi for glazings too!).
            rsi = BTAP::Resources::Envelope::Constructions::get_rsi(OpenStudio::Model::getConstructionByName(surface.model, surface.construction.get.name.to_s).get)

            # Use the cost_range_array to interpolate the estimated cost for the given rsi.
            # Note that window costs in RS Means use U-value, which was converted to rsi for cost_range_array above
            cost = interpolate(cost_range_array, rsi)

            # If the cost is nil, that means the rsi is out of range. Flag in the report.
            if cost.nil?
              if !cost_range_array.empty?
                notes = "RSI out of the range (#{'%.2f' % rsi}) or cost is 0!. Range for #{construction_set[surface_type]} is #{'%.2f' % cost_range_array.first[0]}-#{'%.2f' % cost_range_array.last[0]}."
                cost = 0.0
              else
                notes = "Cost is 0!"
                cost = 0.0
              end
            else
              notes = "OK"
            end

            surfArea = (surface.netArea * zone.multiplier)
            surfCost = cost * surface.netArea * zone.multiplier
            totEnvCost = totEnvCost + surfCost

            # Bin the costing by construction standard type and rsi
            if construction_set.nil?
              name = "undefined space type_#{rsi}"
            else
              name = "#{construction_set[surface_type]}_#{rsi}"
            end
            if @costing_report["envelope"].has_key?(name)
              @costing_report["envelope"][name]['area'] += surfArea
              @costing_report["envelope"][name]['cost'] += surfCost
              @costing_report["envelope"][name]['note'] += " / #{numSurfType}: #{notes}"
            else
              @costing_report["envelope"][name]={'area' => surfArea,
                                                 'cost' => surfCost}
              @costing_report["envelope"][name]['note'] = "Surf ##{numSurfType}: #{notes}"
            end
          end # surfaces of surface type
        end # surface_type
      end # spaces
    end # thermalzone

    @costing_report["envelope"]['total_envelope_cost'] = totEnvCost

    return totEnvCost
  end

  def cost_construction(construction, location, type = 'opaque')

    material_layers = "material_#{type}_id_layers"
    material_id = "materials_#{type}_id"
    materials_database = @costing_database["raw"]["materials_#{type}"]

    total_with_op = 0.0
    material_cost_pairs = []
    construction[material_layers].split(',').reject {|c| c.empty?}.each do |material_index|
      material = materials_database.find {|data| data[material_id].to_s == material_index.to_s}
      if material.nil?
        puts "material error..could not find material #{material_index} in #{materials_database}"
        raise()
      else
        rs_means_data = @costing_database['rsmean_api_data'].detect {|data| data['id'].to_s.upcase == material['id'].to_s.upcase}
        if rs_means_data.nil?
          puts "This material id #{material['id']} was not found in the rs-means api. Skipping. This construction will be inaccurate. "
          raise()
        else
          regional_material, regional_installation = get_regional_cost_factors(location['province-state'], location['city'], material)

          # Get RSMeans cost information from lookup.
          # Note that "glazing" types don't have a 'quantity' hash entry!
          # Don't need "and" below but using in-case this hash field is added in the future.
          if type == 'glazing' and material['quantity'].to_f == 0.0
            material['quantity'] = '1.0'
          end
          material_cost = rs_means_data['baseCosts']['materialOpCost'].to_f * material['quantity'].to_f * material['material_mult'].to_f
          labour_cost = rs_means_data['baseCosts']['labourOpCost'].to_f * material['labour_mult'].to_f
          equipment_cost = rs_means_data['baseCosts']['equipmentOpCost'].to_f
          layer_cost = ((material_cost * regional_material / 100.0) + (labour_cost * regional_installation / 100.0) + equipment_cost).round(2)
          material_cost_pairs << {material_id.to_s => material_index,
                                  'cost' => layer_cost}
          total_with_op += layer_cost
        end
      end
    end
    new_construction = {
        'province-state' => location['province-state'],
        'city' => location['city'],
        "construction_type_name" => construction["construction_type_name"],
        'description' => construction["description"],
        'intended_surface_type' => construction["intended_surface_type"],
        'standards_construction_type' => construction["standards_construction_type"],
        'rsi_k_m2_per_w' => construction['rsi_k_m2_per_w'].to_f,
        'zone' => construction['climate_zone'],
        'fenestration_type' => construction['fenestration_type'],
        'u_w_per_m2_k' => construction['u_w_per_m2_k'],
        'materials' => material_cost_pairs,
        'total_cost_with_op' => total_with_op}

    @costing_database['constructions_costs'] << new_construction
  end
end