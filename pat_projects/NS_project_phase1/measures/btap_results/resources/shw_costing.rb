class BTAPCosting

  # --------------------------------------------------------------------------------------------------
  # This function gets all costs associated with SHW/DHW (i.e., tanks, pumps, flues, piping  and
  # utility costs)
  # --------------------------------------------------------------------------------------------------
  def shw_costing(model, prototype_creator)

    @costing_report['shw'] = {}
    totalCost = 0.0

    # Get regional cost factors for this province and city
    materials_hvac = @costing_database["raw"]["materials_hvac"]
    hvac_material = materials_hvac.select {|data|
      data['Material'].to_s == "WaterGas"}.first  # Get any row from spreadsheet in case of region error
    regional_material, regional_installation =
        get_regional_cost_factors(@costing_report['rs_means_prov'], @costing_report['rs_means_city'], hvac_material)

    # Store some geometry data for use below...
    util_dist, ht_roof, nominal_flr2flr_height, horizontal_dist = getGeometryData(model, prototype_creator)

    template_type = prototype_creator.template

    plant_loop_info = {}
    plant_loop_info[:shwtanks] = []
    plant_loop_info[:shwpumps] = []

    # Iterate through the plant loops to get shw tank & pump data...
    model.getPlantLoops.each do |plant_loop|
      next unless plant_loop.name.get.to_s =~ /Main Service Water Loop/i
      plant_loop.supplyComponents.each do |supply_comp|
        if supply_comp.to_WaterHeaterMixed.is_initialized
          tank = supply_comp.to_WaterHeaterMixed.get
          tank_info = {}
          plant_loop_info[:shwtanks] << tank_info
          tank_info[:name] = tank.name.get
          tank_info[:type] = "WaterHeater:Mixed"
          tank_info[:heater_thermal_efficiency] = tank.heaterThermalEfficiency.get unless tank.heaterThermalEfficiency.empty?
          tank_info[:heater_fuel_type] = tank.heaterFuelType
          if tank.heaterFuelType =~ /Electric/i
            tank_info[:heater_fuel_type] = 'WaterElec'
          elsif tank.heaterFuelType =~ /NaturalGas/i
            tank_info[:heater_fuel_type] = 'WaterGas'
          elsif tank.heaterFuelType =~ /Oil/i       # Oil, FuelOil, FuelOil#2
            tank_info[:heater_fuel_type] = 'WaterOil'
          end
          tank_info[:nominal_capacity] = tank.heaterMaximumCapacity.to_f / 1000 # kW
        elsif supply_comp.to_PumpConstantSpeed.is_initialized
          csPump = supply_comp.to_PumpConstantSpeed.get
          csPump_info = {}
          plant_loop_info[:shwpumps] << csPump_info
          csPump_info[:name] = csPump.name.get
          csPumpSize = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Pumps' AND ColumnName='Electric Power' AND RowName='#{csPump_info[:name].upcase}' ")
          csPump_info[:size] = csPumpSize.to_f # Watts
        elsif supply_comp.to_PumpVariableSpeed.is_initialized
          vsPump = supply_comp.to_PumpVariableSpeed.get
          vsPump_info = {}
          plant_loop_info[:shwpumps] << vsPump_info
          vsPump_info[:name] = vsPump.name.get
          vsPumpSize = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Pumps' AND ColumnName='Electric Power' AND RowName='#{vsPump_info[:name].upcase}' ")
          vsPump_info[:size] = vsPumpSize.to_f # Watts
        end
      end
    end

    # Get costs associated with each shw tank
    tankCost = 0.0 ; thisTankCost = 0.0 ; flueCost = 0.0 ; utilCost = 0.0 ; fuelFittingCost = 0.0
    numTanks = 0 ; multiplier = 1.0 ; primaryFuel = ''; primaryCap = 0 ; backupTank = false

    plant_loop_info[:shwtanks].each do |tank|

      # Electric utility cost components (i.e., power lines).

      # elec 600V #14 wire /100 ft (#848)
      materialHash = materials_hvac.select {|data|
        data['id'].to_s == '260519900920'}.first
      matCost, labCost = getRSMeansCost('electrical wire - 600V #14', materialHash, multiplier)
      elecWireCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0

      # 1 inch metal conduit (#851)
      materialHash = materials_hvac.select {|data|
        data['id'].to_s == '260533130700'}.first
      matCost, labCost = getRSMeansCost('1 inch metal conduit', materialHash, multiplier)
      metalConduitCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0

      # Get primary/secondary/backup tank cost based on fuel type and capacity for each tank
      numTanks += 1
      if tank[:heater_fuel_type] == 'WaterGas' || tank[:heater_fuel_type] == 'WaterOil'
        primaryFuel = tank[:heater_fuel_type]
        primaryCap = tank[:nominal_capacity]
        matCost, labCost = getHVACCost(tank[:name], tank[:heater_fuel_type], tank[:nominal_capacity], false)
        thisTankCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0

        # Flue and utility component costs (for gas and oil tanks only)
        # Calculate flue costs once for all tanks since flues combined by header when multiple tanks
        # 6 inch diameter flue (#384)
        materialHash = materials_hvac.select {|data|
          data['id'].to_s == '235123100140'}.first
        matCost, labCost = getRSMeansCost('flue', materialHash, multiplier)
        flueVentCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0

        #6 inch elbow fitting (#386)
        materialHash = materials_hvac.select {|data|
          data['id'].to_s == '235123100980'}.first
        matCost, labCost = getRSMeansCost('flue elbow', materialHash, multiplier)
        flueElbowCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0

        # 6 inch top (#392)
        materialHash = materials_hvac.select {|data|
          data['id'].to_s == '235123101780'}.first
        matCost, labCost = getRSMeansCost('flue top', materialHash, multiplier)
        flueTopCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0

        # Gas/Oil line piping cost per ft (#1)
        materialHash = materials_hvac.select {|data|
          data['id'].to_s == '231123200140'}.first
        matCost, labCost = getRSMeansCost('fuel line', materialHash, multiplier)
        fuelLineCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0

        # Gas/Oil line fitting connection per tank (#2)
        materialHash = materials_hvac.select {|data|
          data['id'].to_s == '231123205310'}.first
        matCost, labCost = getRSMeansCost('fuel line fitting connection', materialHash, multiplier)
        fuelFittingCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0

        # Header cost only non-zero if there is a secondary/backup gas/oil tank
        headerCost = 0.0

        if tank[:heater_fuel_type] == 'WaterGas'
          # Gas tanks require fuel line+valves+connectors and electrical conduit
          utilCost += (fuelLineCost + metalConduitCost) * util_dist + fuelFittingCost +
              elecWireCost * util_dist / 100

        elsif tank[:heater_fuel_type] == 'WaterOil'
          # Oil tanks require fuel line+valves+connectors and electrical conduit

          # Oil filtering system (#4)
          materialHash = materials_hvac.select {|data|
            data['id'].to_s == '231113101020'}.first
          matCost, labCost = getRSMeansCost('Oil filtering system', materialHash, multiplier)
          oilFilterCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0

          # 2000 USG above ground tank (#5)
          materialHash = materials_hvac.select {|data|
            data['id'].to_s == '231323163330'}.first
          matCost, labCost = getRSMeansCost('Oil tank (2000 USG)', materialHash, multiplier)
          oilTankCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0

          utilCost += (fuelLineCost + metalConduitCost) * util_dist + fuelFittingCost +
              elecWireCost * util_dist / 100 + oilFilterCost + oilTankCost
        end

      else  # Electric
        # Electric has no flue
        flueVentCost = 0.0 ; flueElbowCost = 0.0 ; flueTopCost = 0.0 ; headerCost = 0.0
        # Electric shw tanks require only conduit
        utilCost += metalConduitCost * util_dist + elecWireCost * util_dist / 100
      end

      # Check if need a flue header (i.e., there are both primary and secondary/backup tanks)
      if numTanks > 1 && ( (backupTank && primaryFuel != 'WaterElec') || (tank[:heater_fuel_type] != 'WaterElec') )
        # 6 inch diameter header (#384)
        materialHash = materials_hvac.select {|data|
          data['id'].to_s == '235123100140'}.first
        matCost, labCost = getRSMeansCost('flue header', materialHash, multiplier)
        headerVentCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0

        #6 inch elbow fitting for header (#386)
        materialHash = materials_hvac.select {|data|
          data['id'].to_s == '235123100980'}.first
        matCost, labCost = getRSMeansCost('flue header elbow', materialHash, multiplier)
        headerElbowCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0

        # Assume a header length of 20 ft and an elbow fitting for each tank connected to the header
        headerCost = (headerVentCost * 20  + headerElbowCost) * numTanks
      else
        headerCost = 0.0
      end
      tankCost += thisTankCost
      flueCost += flueVentCost * ht_roof + flueElbowCost + flueTopCost + headerCost
      if numTanks > 1
        # Adjust utility cost for extra fuel line fitting cost
        utilCost += fuelFittingCost * (numTanks - 1)
      end
    end

    # Tank pump costs
    pumpCost = 0.0; pipingCost = 0.0; numPumps = 0; pumpName = ''; pumpSize = 0.0
    plant_loop_info[:shwpumps].each do |pump|
      numPumps += 1
      # Cost variable and constant volume pumps the same (the difference is in extra cost for VFD controller
      pumpSize = pump[:size]; pumpName = pump[:name]
      matCost, labCost = getHVACCost(pumpName, 'Pumps', pumpSize, false)
      pumpCost += matCost * regional_material / 100.0 + labCost * regional_installation / 100.0
      if pump[:name] =~ /variable/i
        # Cost the VFD controller for the variable pump costed above
        pumpSize = pump[:size]; pumpName = pump[:name]
        matCost, labCost = getHVACCost(pumpName, 'VFD', pumpSize, false)
        pumpCost += matCost * regional_material / 100.0 + labCost * regional_installation / 100.0
      end
    end
    if numTanks > 1 && numPumps < 2
      # Add pump costing for the backup tank pump.
      pumpCost *= 2.0
      numPumps = 2  # reset the number of pumps for piping costs below
    end
    # Double the pump costs to accomodate the costing of a backup pumps for each tank!
    pumpCost *= 2.0

    # Tank water piping cost: Add piping elbows, valves and insulation from the tank(s)
    # to the pumps(s) assuming a pipe diameter of 1” and a distance of 10 ft per pump
    if numTanks > 0
      # 1 inch Steel pipe
      matCost, labCost = getHVACCost('1 inch steel pipe', 'SteelPipe', 1)
      pipingCost += 10.0 * numPumps * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

      # 1 inch Steel pipe insulation
      matCost, labCost = getHVACCost('1 inch pipe insulation', 'PipeInsulation', 1)
      pipingCost += 10.0 * numPumps * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

      # 1 inch Steel pipe elbow
      matCost, labCost = getHVACCost('1 inch steel pipe elbow', 'SteelPipeElbow', 1)
      pipingCost += 2.0 * numPumps * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

      # 1 inch gate valves
      matCost, labCost = getHVACCost('1 inch gate valves', 'ValvesGate', 1)
      pipingCost += 1.0 * numPumps * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)
    end

    if numTanks > 1
      # Double pump piping cost to account for second tank
      pipingCost *= 2
    end

    # ckirney, 2019-04-12:  shw_distribution_costing mostly completed however priorities have changed for now so
    # completion and testing will be delayed.  Adding code to master for now but it will not be called until it is
    # ready.
    # distCost = shw_distribution_costing(model: model, prototype_creator: prototype_creator)

    totalCost = tankCost + flueCost + utilCost + pumpCost + pipingCost

    @costing_report['shw'] = {
        'nom_flr2flr_hght_ft' => nominal_flr2flr_height.round(1),
        'ht_roof' => ht_roof.round(1),
        'shw_longest_distance_to_ext_ft' => horizontal_dist.round(1),
        'shw_utility_distance_ft' => util_dist.round(1),
        'shwtanks' => tankCost.round(2),
        'shw_flues' => flueCost.round(2),
        'shw_utilties' => utilCost.round(2),
        'shw_pumps' => pumpCost.round(2),
        'shw_piping' => pipingCost.round(2),
        'shw_total' => totalCost.round(2)
    }
    puts "\nHVAC SHW costing data successfully generated. Total shw costs: $#{totalCost.round(2)}"

    return totalCost
  end

  def shw_distribution_costing(model:, prototype_creator:)
    total_shw_dist_cost = 0
    roof_cent = prototype_creator.find_highest_roof_centre(model)
    mech_room, cond_spaces = prototype_creator.find_mech_room(model)
    min_space = get_lowest_space(spaces: cond_spaces)
    mech_sizing_info = read_mech_sizing()
    shw_sp_types = get_mech_table(mech_size_info: mech_sizing_info, table_name: 'shw_space_types')
    excl_sp_types = get_mech_table(mech_size_info: mech_sizing_info, table_name: 'exclusive_shw_space_types')
    shw_main_cost = cost_shw_main(mech_room: mech_room, roof_cent: roof_cent, min_space: min_space)
    total_shw_dist_cost += shw_main_cost[:cost]
    #determine if space is wet:  prototype_creator.is_an_necb_wet_space?(space)
    #Sort spaces by floor and conditioned spaces
    model.getBuildingStorys.sort.each do |build_story|
      public_wash = false
      other_public_wash = false
      build_story.spaces.sort.each do |space|
        next unless (prototype_creator.space_heated?(space) || prototype_creator.space_cooled?(space)) && !prototype_creator.space_plenum?(space)
        sp_type_name = space.spaceType.get.nameString
        shw_neccesary = shw_sp_types.select {|table_sp_type|
          !/#{table_sp_type.upcase}/.match(sp_type_name.upcase).nil?
        }
        if shw_neccesary.empty?
          public_wash = true
        else
          shw_dist_cost = get_shw_dist_cost(space: space, roof_cent: roof_cent)
          total_shw_dist_cost += shw_dist_cost[:cost]
          public_shw = excl_sp_types.select {|ex_table_sp_type|
            !/#{ex_table_sp_type.upcase}/.match(sp_type_name.upcase).nil?
          }
          other_public_wash = true
        end
      end
      if public_wash == true && other_public_wash == false
        #Cost two shw piping to two washrooms in the center of the story.  Assume each has 20 feet of supply and return
        #shw piping to the story center (10 feet supply, 10 feet return).
        dist_ft = 40
        shw_dist_search = []
        shw_dist_search << {
            mat: 'CopperPipe',
            unit: 'L.F.',
            size: 0.75,
            mult: dist_ft
        }
        washroom_shw_cost = get_comp_cost(cost_info: shw_dist_search)
        total_shw_dist_cost += washroom_shw_cost
      end
    end
    return total_shw_dist_cost
  end

  def get_space_floor_centroid(space:)
    # Determine the bottom surface of the space and calculate it's centroid.
    # Get the coordinates of the origin for the space (the coordinates of points in the space are relative to this).
    xOrigin = space.xOrigin
    yOrigin = space.yOrigin
    zOrigin = space.zOrigin
    # Get the surfaces for the space.
    space_surfaces = space.surfaces
    # Find the floor (aka the surface with the lowest centroid).
    min_surf = space_surfaces.min_by{|sp_surface| (sp_surface.centroid.z.to_f)}
    # The following is added to determine the overall floor centroid because some spaces have floors composed of more than one surface.
    floor_centroid = [0, 0, 0]
    space_surfaces.each do |sp_surface|
      if min_surf.centroid.z.to_f.round(8) == sp_surface.centroid.z.to_f.round(8)
        floor_centroid[0] = floor_centroid[0] + sp_surface.centroid.x.to_f*sp_surface.grossArea.to_f
        floor_centroid[1] = floor_centroid[1] + sp_surface.centroid.y.to_f*sp_surface.grossArea.to_f
        floor_centroid[2] = floor_centroid[2] + sp_surface.grossArea
      end
    end

    # Determine the floor centroid
    floor_centroid[0] = floor_centroid[0]/floor_centroid[2]
    floor_centroid[1] = floor_centroid[1]/floor_centroid[2]

    return {
        centroid: [floor_centroid[0] + xOrigin, floor_centroid[1] + yOrigin, min_surf.centroid.z.to_f + zOrigin],
        floor_area_m2: floor_centroid[2]
    }
  end

  def get_shw_dist_cost(space:, roof_cent:)
    shw_dist_search = []
    space_cent = get_space_floor_centroid(space: space)
    dist_m = (roof_cent[:roof_centroid][0] - space_cent[:centroid][0]).abs + (roof_cent[:roof_centroid][1] - space_cent[:centroid][1]).abs
    dist_ft = OpenStudio.convert(dist_m, 'm', 'ft').get
    shw_dist_search << {
        mat: 'CopperPipe',
        unit: 'L.F.',
        size: 0.75,
        mult: dist_ft
    }
    total_comp_cost = get_comp_cost(cost_info: shw_dist_search)
    return {
        length_m: dist_m,
        cost: total_comp_cost
    }
  end

  def cost_shw_main(mech_room:, roof_cent:, min_space:)
    shw_dist_search = []
    building_height_m = (roof_cent[:roof_centroid][2] - min_space[:roof_cent][2]).abs
    mech_to_cent_dist_m = (roof_cent[:roof_centroid][0] - mech_room['space_centroid'][0]).abs + (roof_cent[:roof_centroid][1] - mech_room['space_centroid'][1]).abs
    #Twice the distance to account for supply and return shw piping.
    total_dist_m = 2*(building_height_m + mech_to_cent_dist_m)
    total_dist_ft = OpenStudio.convert(total_dist_m, 'm', 'ft').get
    shw_dist_search << {
        mat: 'CopperPipe',
        unit: 'L.F.',
        size: 0.75,
        mult: total_dist_ft
    }
    total_comp_cost = get_comp_cost(cost_info: shw_dist_search)
    return {
        length_m: total_dist_m,
        cost: total_comp_cost
    }
  end
end