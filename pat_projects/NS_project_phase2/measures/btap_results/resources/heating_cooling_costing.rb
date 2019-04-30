class BTAPCosting

  # --------------------------------------------------------------------------------------------------
  # This function gets all costs associated with boilers (i.e., boilers, pumps, flues, electrical
  # lines and boxes, fuel lines and distribution piping to zonal heating units)
  # --------------------------------------------------------------------------------------------------
  def boiler_costing(model, prototype_creator)

    totalCost = 0.0

    # Get regional cost factors for this province and city
    materials_hvac = @costing_database["raw"]["materials_hvac"]
    hvac_material = materials_hvac.select {|data|
      data['Material'].to_s == "GasBoilers"}.first  # Get any row from spreadsheet in case of region error
    regional_material, regional_installation =
        get_regional_cost_factors(@costing_report['rs_means_prov'], @costing_report['rs_means_city'], hvac_material)

    # Store some geometry data for use below...
    util_dist, ht_roof, nom_flr_hght, horz_dist, numAGFlrs, mechRmInBsmt = getGeometryData(model, prototype_creator)

    template_type = prototype_creator.template

    plant_loop_info = {}
    plant_loop_info[:boilers] = []
    plant_loop_info[:boilerpumps] = []

    # Iterate through the plant loops to get boiler & pump data...
    model.getPlantLoops.each do |plant_loop|
      next unless plant_loop.name.get.to_s =~ /hot water loop/i
      plant_loop.supplyComponents.each do |supply_comp|
        if supply_comp.to_BoilerHotWater.is_initialized
          boiler = supply_comp.to_BoilerHotWater.get
          boiler_info = {}
          plant_loop_info[:boilers] << boiler_info
          boiler_info[:name] = boiler.name.get
          if boiler.fuelType =~ /Electric/i
            boiler_info[:fueltype] = 'ElecBoilers'
          elsif boiler.fuelType =~ /NaturalGas/i
            boiler_info[:fueltype] = 'GasBoilers'
          elsif boiler.fuelType =~ /Oil/i       # Oil, FuelOil, FuelOil#2
            boiler_info[:fueltype] = 'OilBoilers'
          end
          boiler_info[:nominal_capacity] = boiler.nominalCapacity.to_f / 1000 # kW
        elsif supply_comp.to_PumpConstantSpeed.is_initialized
          csPump = supply_comp.to_PumpConstantSpeed.get
          csPump_info = {}
          plant_loop_info[:boilerpumps] << csPump_info
          csPump_info[:name] = csPump.name.get
          csPumpSize = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Pumps' AND ColumnName='Electric Power' AND RowName='#{csPump_info[:name].upcase}' ")
          csPump_info[:size] = csPumpSize.to_f # Watts
          csPump_info[:water_flow_m3_per_s] = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Pumps' AND ColumnName='Water Flow' AND RowName='#{csPump_info[:name].upcase}' ")
        elsif supply_comp.to_PumpVariableSpeed.is_initialized
          vsPump = supply_comp.to_PumpVariableSpeed.get
          vsPump_info = {}
          plant_loop_info[:boilerpumps] << vsPump_info
          vsPump_info[:name] = vsPump.name.get
          vsPumpSize = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Pumps' AND ColumnName='Electric Power' AND RowName='#{vsPump_info[:name].upcase}' ")
          vsPump_info[:size] = vsPumpSize.to_f # Watts
          vsPump_info[:water_flow_m3_per_s] = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Pumps' AND ColumnName='Water Flow' AND RowName='#{vsPump_info[:name].upcase}' ")
        end
      end
    end

    boilerCost = 0.0 ; thisBoilerCost = 0.0 ; flueCost = 0.0 ; utilCost = 0.0 ; fuelFittingCost = 0.0
    numBoilers = 0 ; multiplier = 1.0 ; primaryFuel = ''; primaryCap = 0 ; backupBoiler = false

    # Get costs associated with each boiler
    plant_loop_info[:boilers].each do |boiler|

      # Get primary/secondary/backup boiler cost based on fuel type and capacity for each boiler
      numBoilers += 1
      if boiler[:name] =~ /primary/i
        primaryFuel = boiler[:fueltype]
        primaryCap = boiler[:nominal_capacity]
        matCost, labCost = getHVACCost(boiler[:name], boiler[:fueltype], boiler[:nominal_capacity], false)
        thisBoilerCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0

        # Flue and utility component costs (for gas and oil boilers only)
        if boiler[:fueltype] == 'GasBoilers' || boiler[:fueltype] == 'OilBoilers'
          # Calculate flue costs once for all boilers since flues combined by header when multiple boilers
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

          # Gas/Oil line fitting connection per boiler (#2)
          materialHash = materials_hvac.select {|data|
            data['id'].to_s == '231123205310'}.first
          matCost, labCost = getRSMeansCost('fuel line fitting connection', materialHash, multiplier)
          fuelFittingCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0

          # Header cost only non-zero if there is a secondary/backup gas/oil boiler
          headerCost = 0.0
        else  # Electric has no flue
          flueVentCost = 0.0 ; flueElbowCost = 0.0 ; flueTopCost = 0.0 ; headerCost = 0.0
        end

        # Electric utility cost components (i.e., power lines).
        # Calculate utility cost for primary boiler only since multiple boilers use common utilities

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

        if boiler[:fueltype] == 'GasBoilers'
          # Gas boilers require fuel line+valves+connectors and electrical conduit
          utilCost += (fuelLineCost + metalConduitCost) * util_dist + fuelFittingCost +
              elecWireCost * util_dist / 100

        elsif boiler[:fueltype] == 'OilBoilers'
          # Oil boilers require fuel line+valves+connectors and electrical conduit

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

        elsif boiler[:fueltype] == 'Electric'
          # Electric boilers require only conduit
          utilCost += metalConduitCost * util_dist + elecWireCost * util_dist / 100
        end

      elsif boiler[:name] =~ /secondary/i
        if boiler[:nominal_capacity] > 0.1
          # A secondary boiler exists so use it for costing
          matCost, labCost = getHVACCost(boiler[:name], boiler[:fueltype], boiler[:nominal_capacity], false)
          thisBoilerCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0
        else
          # Use existing value of thisBoilerCost to represent a backup boiler!
          # This just doubles the cost of the primary boiler.
          backupBoiler = true
        end

        # Flue costs set to zero if secondary boiler since already calculated in primary
        flueVentCost = 0.0; flueElbowCost = 0.0; flueTopCost = 0.0

        # Check if need a flue header (i.e., there are both primary and secondary/backup boilers)
        if thisBoilerCost > 0.0 && ( (backupBoiler && primaryFuel != 'ElecBoilers') || (boiler[:fueltype] != 'ElecBoilers') )
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

          # Assume a header length of 20 ft and an elbow fitting for each boiler connected to the header
          headerCost = (headerVentCost * 20  + headerElbowCost) * numBoilers
        else
          headerCost = 0.0
        end
      end
      boilerCost += thisBoilerCost
      flueCost += flueVentCost * ht_roof + flueElbowCost + flueTopCost + headerCost
      if numBoilers > 1
        # Adjust utility cost for extra fuel line fitting cost
        utilCost += fuelFittingCost * (numBoilers - 1)
      end
    end

    # Boiler pump costs
    pumpCost = 0.0; pipingToPumpCost = 0.0; numPumps = 0; pumpName = ''; pumpSize = 0.0 ; pumpFlow = 0.0
    plant_loop_info[:boilerpumps].each do |pump|
      numPumps += 1
      if pump[:name] =~ /variable/i
        # Cost the VFD controller for the variable pump
        pumpSize = pump[:size]; pumpName = pump[:name]
        pumpFlow += pump[:water_flow_m3_per_s].to_f
        matCost, labCost = getHVACCost(pumpName, 'VFD', pumpSize, false)
        pumpCost += matCost * regional_material / 100.0 + labCost * regional_installation / 100.0
      else
        # Cost variable and constant volume pumps the same (the difference is in extra cost for VFD controller)
        pumpSize = pump[:size]; pumpName = pump[:name]
        pumpFlow += pump[:water_flow_m3_per_s].to_f
        matCost, labCost = getHVACCost(pumpName, 'Pumps', pumpSize, false)
        pumpCost += matCost * regional_material / 100.0 + labCost * regional_installation / 100.0
      end
    end
    if numBoilers > 1 && numPumps < 2
      # Add pump costing for the backup boiler pump.
      pumpCost *= 2.0
      numPumps = 2  # reset the number of pumps for piping costs below
    end
    # Double the pump costs to accomodate the costing of a backup pumps for each boiler!
    pumpCost *= 2.0

    # Boiler water piping to pumps cost: Add piping elbows, valves and insulation from the boiler(s)
    # to the pumps(s) assuming a pipe diameter of 1” and a distance of 10 ft per pump

    if numBoilers > 0
      # 1 inch Steel pipe
      matCost, labCost = getHVACCost('1 inch steel pipe', 'SteelPipe', 1)
      pipingToPumpCost += 10.0 * numPumps * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

      # 1 inch Steel pipe insulation
      matCost, labCost = getHVACCost('1 inch pipe insulation', 'PipeInsulation', 1)
      pipingToPumpCost += 10.0 * numPumps * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

      # 1 inch Steel pipe elbow
      matCost, labCost = getHVACCost('1 inch steel pipe elbow', 'SteelPipeElbow', 1)
      pipingToPumpCost += 2.0 * numPumps * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

      # 1 inch gate valves
      matCost, labCost = getHVACCost('1 inch gate valves', 'ValvesGate', 1)
      pipingToPumpCost += 1.0 * numPumps * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)
    end

    if numBoilers > 1
      # Double pump piping cost to account for second boiler
      pipingToPumpCost *= 2
    end

    hdrDistributionCost = getHeaderPipingDistributionCost(numAGFlrs, mechRmInBsmt, regional_material, regional_installation, pumpFlow, horz_dist, nom_flr_hght)

    totalCost = boilerCost + flueCost + utilCost + pumpCost + pipingToPumpCost + hdrDistributionCost

        @costing_report['heating_and_cooling']['plant_equipment']  << {
        'type' => 'boilers',
        'nom_flr2flr_hght_ft' => nom_flr_hght.round(1),
        'ht_roof_ft' => ht_roof.round(1),
        'longest_distance_to_ext_ft' => horz_dist.round(1),
        'wiring_and_gas_connections_distance_ft' => util_dist.round(1),
        'equipment_cost' => boilerCost.round(2),
        'flue_cost' => flueCost.round(2),
        'wiring_and_gas_connections_cost' => utilCost.round(2),
        'pump_cost' => pumpCost.round(2),
        'piping_to_pump_cost' => pipingToPumpCost.round(2),
        'header_distribution_cost' => hdrDistributionCost.round(2),
        'total_cost' => totalCost.round(2)
    }
    puts "\nHVAC Boiler costing data successfully generated. Total boiler costs: $#{totalCost.round(2)}"

    return totalCost
  end

  # --------------------------------------------------------------------------------------------------
  # Chiller costing is similar to boiler costing above
  # --------------------------------------------------------------------------------------------------
  def chiller_costing(model, prototype_creator)

    totalCost = 0.0

    # Get regional cost factors for this province and city
    materials_hvac = @costing_database["raw"]["materials_hvac"]
    hvac_material = materials_hvac.select {|data|
      data['Material'].to_s == "GasBoilers"}.first  # Get any row from spreadsheet in case of region error
    regional_material, regional_installation =
        get_regional_cost_factors(@costing_report['rs_means_prov'], @costing_report['rs_means_city'], hvac_material)

    # Store some geometry data for use below...
    util_dist, ht_roof, nom_flr_hght, horz_dist, numAGFlrs, mechRmInBsmt = getGeometryData(model, prototype_creator)

    template_type = prototype_creator.template

    chillerCost = 0.0 ; thisChillerCost = 0.0 ; flueCost = 0.0 ; utilCost = 0.0
    plant_loop_info = {}
    plant_loop_info[:chillers] = []
    plant_loop_info[:chillerpumps] = []

    # Iterate through the plant loops to get chiller & pump data...
    model.getPlantLoops.each do |plant_loop|
      next unless plant_loop.name.get.to_s =~ /chilled water loop/i
      plant_loop.supplyComponents.each do |supply_comp|
        if supply_comp.to_ChillerElectricEIR.is_initialized #|| supply_comp.to_ChillerGasEIR.is_initialized
          chiller = supply_comp.to_ChillerElectricEIR.get
          chiller_info = {}
          plant_loop_info[:chillers] << chiller_info
          chiller_info[:name] = chiller.name.get
          if chiller_info[:name] =~ /WaterCooled Absorption/i
            chiller_info[:type] = 'HotAbsChiller'
            chiller_info[:fuel] = 'NaturalGas'
          elsif chiller_info[:name] =~ /WaterCooled Direct Gas/i
            chiller_info[:type] = 'GasAbsChiller'
            chiller_info[:fuel] = 'NaturalGas'
          elsif chiller_info[:name] =~ /WaterCooled Centrifugal/i
            chiller_info[:type] = 'CentChillerWater'
            chiller_info[:fuel] = 'Electric'
          elsif chiller_info[:name] =~ /WaterCooled Reciprocating/i
            chiller_info[:type] = 'RecChillerWater'
            chiller_info[:fuel] = 'Electric'
          elsif chiller_info[:name] =~ /AirCooled Reciprocating/i
            chiller_info[:type] = 'RecChillerAir'
            chiller_info[:fuel] = 'Electric'
          elsif chiller_info[:name] =~ /AirCooled Scroll/i
            chiller_info[:type] = 'ScrollChillerAir'
            chiller_info[:fuel] = 'Electric'
          elsif chiller_info[:name] =~ /WaterCooled Scroll/i
            chiller_info[:type] = 'ScrollChillerWater'
            chiller_info[:fuel] = 'Electric'
          elsif chiller_info[:name] =~ /AirCooled Screw/i
            chiller_info[:type] = 'ScrewChillerAir'
            chiller_info[:fuel] = 'Electric'
          elsif chiller_info[:name] =~ /WaterCooled Screw/i
            chiller_info[:type] = 'ScrewChillerWater'
            chiller_info[:fuel] = 'Electric'
          elsif chiller_info[:name] =~ /AirCooled DX/i
            chiller_info[:type] = 'DXChiller'
            chiller_info[:fuel] = 'Electric'
          end
          chiller_info[:reference_capacity] = chiller.referenceCapacity.to_f / 1000 # kW
        elsif supply_comp.to_PumpConstantSpeed.is_initialized
          csPump = supply_comp.to_PumpConstantSpeed.get
          csPump_info = {}
          plant_loop_info[:chillerpumps] << csPump_info
          csPump_info[:name] = csPump.name.get
          csPumpSize = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Pumps' AND ColumnName='Electric Power' AND RowName='#{csPump_info[:name].upcase}' ")
          csPump_info[:size] = csPumpSize.to_f # Watts
          csPump_info[:water_flow_m3_per_s] = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Pumps' AND ColumnName='Water Flow' AND RowName='#{csPump_info[:name].upcase}' ")
        elsif supply_comp.to_PumpVariableSpeed.is_initialized
          vsPump = supply_comp.to_PumpVariableSpeed.get
          vsPump_info = {}
          plant_loop_info[:chillerpumps] << vsPump_info
          vsPump_info[:name] = vsPump.name.get
          vsPumpSize = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Pumps' AND ColumnName='Electric Power' AND RowName='#{vsPump_info[:name].upcase}' ")
          vsPump_info[:size] = vsPumpSize.to_f # Watts
          vsPump_info[:water_flow_m3_per_s] = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND TableName='Pumps' AND ColumnName='Water Flow' AND RowName='#{vsPump_info[:name].upcase}' ")
        end
      end
    end

    # Get costs associated with each chiller
    numChillers = 0 ; multiplier = 1.0
    primaryFuel = ''; primaryCap = 0

    plant_loop_info[:chillers].each do |chiller|

      # Get primary/secondary/backup chiller cost based on type and capacity for each chiller
      numChillers += 1
      if chiller[:name] =~ /primary/i
        primaryFuel = chiller[:fuel]
        primaryCap = chiller[:reference_capacity]
        matCost, labCost = getHVACCost(chiller[:name], chiller[:type], chiller[:reference_capacity], false)
        thisChillerCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0

        # Flue cost for gas (absorption) chillers!
        if chiller[:fuel] == 'NaturalGas'
          # Calculate flue costs once for all chillets since flues combined by header when multiple chillers
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

          # Gas line piping cost per ft (#1)
          materialHash = materials_hvac.select {|data|
            data['id'].to_s == '231123200140'}.first
          matCost, labCost = getRSMeansCost('fuel line', materialHash, multiplier)
          fuelLineCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0

          # Gas line fitting connection per boiler (#2)
          materialHash = materials_hvac.select {|data|
            data['id'].to_s == '231123205310'}.first
          matCost, labCost = getRSMeansCost('fuel line fitting connection', materialHash, multiplier)
          fuelFittingCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0


          # Header cost only non-zero if there is a secondary/backup gas/oil boiler
          headerCost = 0.0
        else  # Electric
          flueVentCost = 0.0 ; flueElbowCost = 0.0 ; flueTopCost = 0.0 ; headerCost = 0.0
        end

        # Electric utility costs (i.e., power lines).
        # Calculate utility cost components for primary chiller only since multiple chillers use common utilities

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

        if chiller[:fuel] == 'NaturalGas'
          # Gas chillers require fuel line+valves+connectors and electrical conduit
          utilCost += (fuelLineCost + metalConduitCost) * util_dist + fuelFittingCost + elecWireCost * util_dist / 100

        else # Electric
          # Electric chillers require only conduit
          utilCost += metalConduitCost * util_dist + elecWireCost * util_dist / 100
        end

      elsif chiller[:name] =~ /secondary/i
        if chiller[:reference_capacity] <= 0.1
          # Chiller cost is zero!
          thisChillerCost = 0.0
        else
          # A secondary chiller exists so use it for costing
          matCost, labCost = getHVACCost(chiller[:name], chiller[:type], chiller[:reference_capacity], false)
          thisChillerCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0
        end

        # Flue costs set to zero if secondary chiler since already calculated in primary (if gas absorption)
        flueVentCost = 0.0; flueElbowCost = 0.0; flueTopCost = 0.0

        # Check if need a flue header (i.e., both primary and secondary chillers are gas absorption)
        if thisChillerCost > 0.0 && primaryFuel == 'NaturalGas' && chiller[:fuel] == 'NaturalGas'
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

          # Assume a header length of 20 ft and an elbow fitting for each boiler connected to the header
          headerCost = (headerVentCost * 20 + headerElbowCost) * numChillers
        else
          headerCost = 0.0
        end
      end
      chillerCost += thisChillerCost
      flueCost += flueVentCost * ht_roof + flueElbowCost + flueTopCost + headerCost
      if numChillers > 1 && primaryFuel == 'NaturalGas'
        # Adjust utility cost for extra fuel line fitting cost
        utilCost += fuelFittingCost * (numChillers - 1)
      end
      if numChillers < 2
        # Create a cost for a backup chiller by doubling cost of primary chiller
        chillerCost *= 2.0
      end
    end

    # Chiller pump costs
    pumpCost = 0.0; pipingCost = 0.0; numPumps = 0; pumpName = ''; pumpSize = 0.0 ; pumpFlow = 0.0
    plant_loop_info[:chillerpumps].each do |pump|
      numPumps += 1
      if pump[:name] =~ /variable/i
        # Cost the VFD controller for the variable pump costed above
        pumpSize = pump[:size]; pumpName = pump[:name]
        pumpFlow += pump[:water_flow_m3_per_s].to_f
        matCost, labCost = getHVACCost(pumpName, 'VFD', pumpSize, false)
        pumpCost += matCost * regional_material / 100.0 + labCost * regional_installation / 100.0
      else
        # Cost variable and constant volume pumps the same (the difference is in extra cost for VFD controller)
        pumpSize = pump[:size]; pumpName = pump[:name]
        pumpFlow += pump[:water_flow_m3_per_s].to_f
        matCost, labCost = getHVACCost(pumpName, 'Pumps', pumpSize, false)
        pumpCost += matCost * regional_material / 100.0 + labCost * regional_installation / 100.0
      end
    end
    if numChillers > 1 && numPumps < 2
      # Add pump costing for a backup pump.
      pumpCost *= 2.0
      numPumps = 2  # reset the number of pumps for piping costs below
    end
    # Double the pump costs to accomodate the costing of backup pumps for each chiller!
    pumpCost *= 2.0

    # Chiller water piping cost: Add piping elbows, valves and insulation from the chiller(s)
    # to the pumps(s) assuming a pipe diameter of 1” and a distance of 10 ft per pump
    if numChillers > 0
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

    if numChillers > 1
      # Double piping cost to account for second boiler piping
      pipingCost *= 2.0
    end

    hdrDistributionCost = getHeaderPipingDistributionCost(numAGFlrs, mechRmInBsmt, regional_material, regional_installation, pumpFlow, horz_dist, nom_flr_hght)

    totalCost = chillerCost + flueCost + utilCost + pumpCost + pipingCost + hdrDistributionCost

    @costing_report['heating_and_cooling']['plant_equipment']  << {
        'type' => 'chillers',
        'nom_flr2flr_hght_ft' => nom_flr_hght.round(1),
        'ht_roof_ft' => ht_roof.round(1),
        'longest_distance_to_ext_ft' => horz_dist.round(1),
        'wiring_and_gas_connections_distance_ft' => util_dist.round(1),
        'equipment_cost' => chillerCost.round(2),
        'flue_cost' => flueCost.round(2),
        'wiring_and_gas_connections_cost' => utilCost.round(2),
        'pump_cost' => pumpCost.round(2),
        'piping_to_pump_cost' => pipingCost.round(2),
        'header_distribution_cost' => hdrDistributionCost.round(2),
        'total_cost' => totalCost.round(2)
    }

    puts "\nHVAC Chiller costing data successfully generated. Total chiller costs: $#{totalCost.round(2)}"

    return totalCost
  end

  # ----------------------------------------------------------------------------------------------
  # Cooling tower (i.e., chiller condensor loop cooling) costing
  # ----------------------------------------------------------------------------------------------
  def coolingtower_costing(model, prototype_creator)

    totalCost = 0.0

    # Get regional cost factors for this province and city
    materials_hvac = @costing_database["raw"]["materials_hvac"]
    hvac_material = materials_hvac.select {|data|
      data['Material'].to_s == "GasBoilers"}.first  # Get any row from spreadsheet in case of region error
    regional_material, regional_installation =
        get_regional_cost_factors(@costing_report['rs_means_prov'], @costing_report['rs_means_city'], hvac_material)

    # Store some geometry data for use below...
    util_dist, ht_roof, nom_flr_hght, horz_dist, numAGFlrs, mechRmInBsmt = getGeometryData(model, prototype_creator)

    template_type = prototype_creator.template

    cltowerCost = 0.0
    thisClTowerCost = 0.0
    utilCost = 0.0
    plant_loop_info = {}
    plant_loop_info[:coolingtowers] = []
    plant_loop_info[:coolingtowerpumps] = []

    # Iterate through the plant loops to get cooling tower & pump data...
    model.getPlantLoops.each do |plant_loop|
      next unless plant_loop.name.get.to_s =~ /Condenser Water Loop/i
      plant_loop.supplyComponents.each do |supply_comp|
        if supply_comp.to_CoolingTowerSingleSpeed.is_initialized
          cltower = supply_comp.to_CoolingTowerSingleSpeed.get
          cltower_info = {}
          plant_loop_info[:coolingtowers] << cltower_info
          cltower_info[:name] = cltower.name.get
          cltower_info[:type] = 'ClgTwr'  # Material lookup name
          cltower_info[:fanPoweratDesignAirFlowRate] = cltower.fanPoweratDesignAirFlowRate.to_f / 1000 # kW
          cltower_info[:capacity] = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM " +
            "TabularDataWithStrings WHERE ReportName='EquipmentSummary' AND ReportForString='Entire Facility' AND " +
            "TableName='Central Plant' AND ColumnName='Nominal Capacity' AND " +
            "RowName='#{cltower_info[:name].upcase}' ").to_f / 1000 # kW
        elsif supply_comp.to_PumpConstantSpeed.is_initialized
          csPump = supply_comp.to_PumpConstantSpeed.get
          csPump_info = {}
          plant_loop_info[:coolingtowerpumps] << csPump_info
          csPump_info[:name] = csPump.name.get
          csPumpSize = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings " +
                        "WHERE ReportName='EquipmentSummary' AND " +
                        "ReportForString='Entire Facility' AND " +
                        "TableName='Pumps' AND " +
                        "ColumnName='Electric Power' AND " +
                        "RowName='#{csPump_info[:name].upcase}' ")
          csPump_info[:size] = csPumpSize.to_f # Watts
        elsif supply_comp.to_PumpVariableSpeed.is_initialized
          vsPump = supply_comp.to_PumpVariableSpeed.get
          vsPump_info = {}
          plant_loop_info[:coolingtowerpumps] << vsPump_info
          vsPump_info[:name] = vsPump.name.get
          vsPumpSize = model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings " +
                        "WHERE ReportName='EquipmentSummary' AND " +
                        "ReportForString='Entire Facility' AND " +
                        "TableName='Pumps' AND " +
                        "ColumnName='Electric Power' AND " +
                        "RowName='#{vsPump_info[:name].upcase}' ")
          vsPump_info[:size] = vsPumpSize.to_f # Watts
        end
      end
    end

    # Get costs associated with each cooling tower
    numTowers = 0 ; multiplier = 1.0

    plant_loop_info[:coolingtowers].each do |cltower|
      # Get cooling tower cost based on capacity
      numTowers += 1
      if numTowers == 1
        matCost, labCost = getHVACCost(cltower[:name], cltower[:type], cltower[:capacity], false)
        thisClTowerCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0
      else  # Multiple cooling towers
        if cltower[:capacity] <= 0.1
          # Cooling tower cost is zero!
          thisClTowerCost = 0.0
        else
          # A second cooling tower exists so use it for costing
          matCost, labCost = getHVACCost(cltower[:name], cltower[:type], cltower[:capacity], false)
          thisClTowerCost = matCost * regional_material / 100.0 + labCost * regional_installation / 100.0
        end
      end
      cltowerCost += thisClTowerCost

      # Electric utility costs (i.e., power lines) for cooling tower(s).

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

      utilCost += metalConduitCost * (ht_roof + 20) + elecWireCost * (ht_roof + 20) / 100
    end

    # Cooling Tower (condensor) pump costs
    pumpCost = 0.0; pipingCost = 0.0; numPumps = 0; pumpName = ''; pumpSize = 0.0
    plant_loop_info[:coolingtowerpumps].each do |pump|
      numPumps += 1
      # Cost variable and constant volume pumps the same (VFD controller added if variable)
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
    if numTowers > 1 && numPumps < 2
      # Add pump costing for the backup pump.
      pumpCost *= 2.0
    end
    # Double the pump costs to accomodate the costing of a backup pump(s)!
    pumpCost *= 2.0
    numPumps = 2  # reset the number of pumps for piping costs below

    # Chiller water piping cost: Add piping elbows, valves and insulation from the chiller(s)
    # to the pumps(s) assuming a pipe diameter of 1” and a distance of 10 ft per pump
    if numTowers > 0
      # 4 inch Steel pipe (vertical + horizontal)
      matCost, labCost = getHVACCost('4 inch steel pipe', 'SteelPipe', 4)
      pipingCost += (ht_roof * 2 + 10 * numPumps) * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

      # 4 inch Steel pipe insulation (vertical + horizontal)
      matCost, labCost = getHVACCost('1 inch pipe insulation', 'PipeInsulation', 4)
      pipingCost += (ht_roof * 2 + 10 * numPumps) * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

      # 4 inch Steel pipe elbow
      matCost, labCost = getHVACCost('4 inch steel pipe tee', 'SteelPipeTee', 4)
      pipingCost += 1.0 * numPumps * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

      # 4 inch valves
      matCost, labCost = getHVACCost('4 inch BFly valves', 'ValvesBFly', 4)
      pipingCost += 1.0 * numPumps * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)
    end

    # Note: No extra costs for piping for backup condenser pump or multiple cooling towers.

    totalCost = cltowerCost + utilCost + pumpCost + pipingCost

    @costing_report['heating_and_cooling']['plant_equipment']  << {
        'type' => 'cooling_towers',
        'nom_flr2flr_hght_ft' => nom_flr_hght.round(1),
        'ht_roof_ft' => ht_roof.round(1),
        'longest_distance_to_ext_ft' => horz_dist.round(1),
        'wiring_and_gas_connections_distance_ft' => util_dist.round(1),
        'equipment_cost' => cltowerCost.round(2),
        'wiring_and_gas_connections_cost' => utilCost.round(2),
        'pump_cost' => pumpCost.round(2),
        'piping_cost' => pipingCost.round(2),
        'total_cost' => totalCost.round(2)
    }

    puts "\nHVAC Cooling Tower costing data successfully generated. Total cooling tower costs: $#{totalCost.round(2)}"

    return totalCost
  end


  def get_HVAC_multiplier(materialLookup, materialSize)
    multiplier = 1.0
    materials_hvac = @costing_database['raw']['materials_hvac'].select {|data|
      data['Material'].to_s.upcase == materialLookup.to_s.upcase
    }
    if materials_hvac.nil?
      puts("Error: no hvac information available for equipment #{materialLookup}!")
      raise
    elsif materials_hvac.empty?
      puts("Error: no hvac information available for equipment #{materialLookup}!")
      raise
    end
    materials_hvac.length == 1 ? max_size = materials_hvac[0] : max_size = materials_hvac.max_by {|d| d['Size'].to_f}
    if max_size['Size'].to_f <= 0
      puts("Error: #{materialLookup} has a size of 0 or less.  Please check that the correct costing_database.json file is being used or check the costing spreadsheet!")
      raise
    end
    mult = materialSize.to_f / (max_size['Size'].to_f)
    multiplier = (mult.to_i).to_f.round(0) + 1  # Use next largest integer for multiplier
    return multiplier.to_f
  end

  def getHVACCost(name, materialLookup, materialSize, exactMatch=true)
    multiplier = 1.0
    materials_hvac = @costing_database["raw"]["materials_hvac"]
    if materialSize == 'nil' || materialSize == ''
      # When materialSize is blank because there is only one row in the data sheet, the value is nil
      hvac_material = materials_hvac.select { |data| data['Material'].to_s == materialLookup.to_s }.first
    else
      hvac_material = materials_hvac.select {|data|
        data['Material'].to_s == materialLookup.to_s && data['Size'].to_f == materialSize
        }.first
    end
    if hvac_material.nil?
      if exactMatch
        puts "HVAC material error! Could not find #{name} in materials_hvac!"
        raise
      else
        # There is no exact match in the costing spreadsheet so redo search for next largest size
        hvac_material = materials_hvac.select {|data|
          data['Material'].to_s == materialLookup.to_s && data['Size'].to_f >= materialSize.to_f
        }.first
        if hvac_material.nil?
          # The nominal capacity is greater than the maximum value in RS Means for this boiler!
          # Lookup cost for a capacity divided by the multiple of req'd size/max size.
          multiplier = get_HVAC_multiplier( materialLookup, materialSize )
          hvac_material = materials_hvac.select {|data|
            data['Material'].to_s == materialLookup.to_s && data['Size'].to_f >= materialSize.to_f / multiplier.to_f
          }.first
          if hvac_material.nil?
            puts "HVAC material error! Could not find next largest size for #{name} in #{materials_hvac}"
            raise
          end
        end
      end
    end
    return getRSMeansCost(name, hvac_material, multiplier)
  end


  def getRSMeansCost(materialType, materialHash, multiplier)
    material_cost = 0.0 ; labour_cost = 0.0
    rs_means_data = @costing_database['rsmean_api_data'].detect do |data|
      data['id'].to_s.upcase == materialHash['id'].to_s.upcase
    end
    if rs_means_data.nil?
      puts "HVAC #{materialType} with id #{materialHash['id']} not found in rs-means api. Skipping."
      raise
    else
      # Get RSMeans cost information from lookup.
      material_cost = rs_means_data['baseCosts']['materialOpCost'].to_f * multiplier
      labour_cost = rs_means_data['baseCosts']['laborOpCost'].to_f * multiplier
    end
    return material_cost, labour_cost
  end

  def getGeometryData(model, prototype_creator)
    num_of_above_ground_stories = model.getBuilding.standardsNumberOfAboveGroundStories.to_i
    if model.building.get.nominalFloortoFloorHeight().empty?
      volume = model.building.get.airVolume()
      flrArea = 0.0
      flrArea = model.building.get.conditionedFloorArea().get unless model.building.get.conditionedFloorArea().empty?
      nominal_flr2flr_height = 0.0
      nominal_flr2flr_height = volume / flrArea unless flrArea <= 0.01
    else
      nominal_flr2flr_height = model.building.get.nominalFloortoFloorHeight.get
    end

    # Location of mechanical room and utility distances for use below (space_centroid is an array
    # in mech_room hash containing the x,y and z coordinates of space centroid). Utility distance
    # uses the distance from the mech room centroid to the perimeter of the building.
    mech_room, cond_spaces = prototype_creator.find_mech_room(model)
    mech_room_story = nil
    target_cent = [mech_room['space_centroid'][0], mech_room['space_centroid'][1]]
    found = false
    model.getBuildingStorys.sort.each do |story|
      BTAP::Geometry::Spaces::get_spaces_from_storeys(model, story).sort.each do |space|
        if space.nameString == mech_room['space_name']
          mech_room_story = story
          found = true
          break
        end
      end
      break if found
    end
    distance_info_hash = get_story_cent_to_edge( building_story: mech_room_story, prototype_creator: prototype_creator,
                                                 target_cent: target_cent, full_length: false )
    horizontal_dist = distance_info_hash[:start_point][:line][:dist]  # in metres

    ht_roof = 0.0
    util_dist = 0.0
    mechRmInBsmt = false
    if mech_room['space_centroid'][2] < 0
      # Mechanical room is in the basement (z dimension is negative).
      mechRmInBsmt = true
      ht_roof = (num_of_above_ground_stories + 1) * nominal_flr2flr_height
      util_dist = nominal_flr2flr_height + horizontal_dist
    elsif mech_room['space_centroid'][2] == 0
      # Mech room on ground floor
      ht_roof = num_of_above_ground_stories * nominal_flr2flr_height
      util_dist = horizontal_dist
    else
      # Mech room on some other floor
      ht_roof = (num_of_above_ground_stories - (mech_room['space_centroid'][2]/nominal_flr2flr_height).round(0)) * nominal_flr2flr_height
      util_dist = ht_roof + horizontal_dist
    end

    util_dist = OpenStudio.convert(util_dist,"m","ft").get
    nominal_flr2flr_height = OpenStudio.convert(nominal_flr2flr_height,"m","ft").get
    ht_roof = OpenStudio.convert(ht_roof,"m","ft").get
    horizontal_dist = OpenStudio.convert(horizontal_dist,"m","ft").get

    return util_dist, ht_roof, nominal_flr2flr_height, horizontal_dist, num_of_above_ground_stories, mechRmInBsmt
  end

  # --------------------------------------------------------------------------------------------------
  # This function gets all costs associated zonal heating and cooling systems
  # (i.e., zonal units, pumps, flues & utility costs)
  # --------------------------------------------------------------------------------------------------
  def zonalsys_costing(model, prototype_creator)

    totalCost = 0.0

    # Get regional cost factors for this province and city
    materials_hvac = @costing_database["raw"]["materials_hvac"]
    hvac_material = materials_hvac.select {|data|
      data['Material'].to_s == "GasBoilers"}.first  # Get any row from spreadsheet in case of region error
    regional_material, regional_installation =
        get_regional_cost_factors(@costing_report['rs_means_prov'], @costing_report['rs_means_city'], hvac_material)

    # Store some geometry data for use below...
    util_dist, ht_roof, nom_flr_hght, horz_dist, numAGFlrs, mechRmInBsmt = getGeometryData(model, prototype_creator)

    template_type = prototype_creator.template

    zone_loop_info = {}
    zone_loop_info[:zonesys] = []
    numZones = 0; floorNumber = 0
    needCentralGasHdr = false

    model.getThermalZones.sort.each do |zone|
      numZones += 1
      zone.equipment.each do |equipment|
        if equipment.to_ZoneHVACComponent.is_initialized
          # This is a zonal HVAC component
          zone_info = {}
          zone_loop_info[:zonesys] << zone_info

          # Get floor number from zone name string using regexp (Flr-N, where N is the storey number)
          zone_info[:zonename] = zone.name.get
          zone_info[:zonename].scan(/.*Flr-(\d+).*/) {|num| zone_info[:flrnum] = num[0].to_i}

          unless zone.isConditioned.empty?
            zone_info[:is_conditioned] = zone.isConditioned.get
          else
            zone_info[:is_conditioned] = 'N/A'
            puts "Warning: zone.isConditioned is empty for #{zone.name.get}!"
          end

          zone_info[:multiplier] = zone.multiplier

          # Get the zone ceiling height value from the sql file...
          query = "SELECT CeilingHeight FROM Zones WHERE ZoneName='#{zone_info[:zonename].upcase}'"
          ceilHeight = model.sqlFile().get().execAndReturnFirstDouble(query)
          zone_info[:ceilingheight] = OpenStudio.convert(ceilHeight.to_f,"m","ft").get  # feet

          zone_info[:heatcost] = 0.0
          zone_info[:coolcost] = 0.0
          zone_info[:heatcoolcost] = 0.0
          zone_info[:pipingcost] = 0.0
          zone_info[:wiringcost] = 0.0
          zone_info[:multiplier] = zone.multiplier
          zone_info[:sysname] = equipment.name.get

          # Get the heat capacity values from the sql file - ZoneSizes table...
          query = "SELECT UserDesLoad FROM ZoneSizes WHERE ZoneName='#{zone_info[:zonename].upcase}' AND LoadType='Heating'"
          heatCapVal = model.sqlFile().get().execAndReturnFirstDouble(query)
          zone_info[:heatcapacity] = heatCapVal.to_f / 1000.0 # Watts -> kW

          component = equipment.to_ZoneHVACComponent.get
          if component.to_ZoneHVACPackagedTerminalAirConditioner.is_initialized
            cooling_coil_name = component.to_ZoneHVACPackagedTerminalAirConditioner.get.coolingCoil.name.to_s
          elsif component.to_ZoneHVACFourPipeFanCoil.is_initialized # 2PFC & 4PFC
            cooling_coil_name = component.to_ZoneHVACFourPipeFanCoil.get.coolingCoil.name.to_s
          elsif component.to_ZoneHVACPackagedTerminalHeatPump.is_initialized
            cooling_coil_name = component.to_ZoneHVACPackagedTerminalHeatPump.get.coolingCoil.name.to_s
          else
            cooling_coil_name = 'nil'
          end

          # Get the cooling total capacity (sen+lat) value from the sql file - ComponentSizes table.
          query = "SELECT Value FROM ComponentSizes WHERE CompName='#{cooling_coil_name.upcase}' AND Units='W'"
          coolCapVal = model.sqlFile().get().execAndReturnFirstDouble(query)
          zone_info[:coolcapacity] = coolCapVal.to_f / 1000.0 # Watts -> kW

          if zone_info[:sysname] =~ /Baseboard Convective Water/i
            zone_info[:systype] = 'HW'
            # HW convector length based on 0.425 kW/foot
            if zone_info[:heatcapacity] > 0
              heatCapacity = zone_info[:heatcapacity] / zone.multiplier
              convLength = (heatCapacity / 0.425).round(0)
              # HW convector 1" copper core pipe cost
              matCost, labCost = getHVACCost(zone_info[:sysname], 'ConvectCopper', 1.25, true)
              convPipeCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * convLength
              # For each convector there will be a shut-off valve, 2 Tee connections and 2 elbows to
              # isolate the convector from the hot water loop distribution for servicing and balancing.
              # Hot water convectors are manufactured in maximum 8 ft lengths, therefore the number of
              # convectors per thermal zone is (rounded up to nearest integer):
              ratio = (convLength.to_f / 8.0).to_f
              numConvectors = (ratio - ratio.to_i) > 0.10 ? (ratio + 0.5).round(0) : ratio
              # Cost of valves:
              matCost, labCost = getHVACCost('1.25 inch gate valve', 'ValvesGate', 1.25, true)
              convValvesCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * numConvectors
              # Cost of tees:
              matCost, labCost = getHVACCost('1.25 inch copper tees', 'CopperPipeTee', 1.25, true)
              convTeesCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * 2 * numConvectors
              # Cost of elbows:
              matCost, labCost = getHVACCost('1.25 inch copper elbows', 'CopperPipeElbow', 1.25, true)
              convElbowsCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * 2 * numConvectors
              # Total convector cost for this zone (excluding distribution piping):
              convCost = (convPipeCost + convValvesCost + convTeesCost + convElbowsCost) * zone.multiplier
              zone_info[:heatcost] = convCost
              zone_info[:num_units] = numConvectors

              # Single pipe supply and return
              perimPipingCost = getPerimDistPipingCost(zone, nom_flr_hght, regional_material, regional_installation)
              zone_info[:pipingcost] = perimPipingCost

              totalCost += convCost + perimPipingCost
            end

          elsif zone_info[:sysname]=~ /Baseboard Convective Electric/i
            zone_info[:systype] = 'BB'
            # BB number based on 0.935 kW/unit
            if zone_info[:heatcapacity] > 0
              heatCapacity = zone_info[:heatcapacity] / zone.multiplier
              ratio = (heatCapacity / 0.935).to_f
              numConvectors = (ratio - ratio.to_i) > 0.10 ? (ratio + 0.5).round(0) : ratio
              # BB electric convector unit cost (Just one in sheet)
              matCost, labCost = getHVACCost(zone_info[:sysname], 'ElectricBaseboard', 'nil', true)
              elecBBCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * numConvectors
              # For each baseboard there will be an electrical junction box
              matCost, labCost = getHVACCost('Electrical Outlet Box', 'Box', 1, true)
              elecBoxCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * numConvectors
              # Total electric basbeboard cost for this zone:
              elecConvCost = (elecBBCost + elecBoxCost) * zone.multiplier
              zone_info[:heatcost] = elecConvCost
              zone_info[:num_units] = numConvectors

              perimWiringCost = getPerimDistWiringCost(zone, nom_flr_hght, regional_material, regional_installation)
              zone_info[:wiringcost] = perimWiringCost

              totalCost += elecConvCost + perimWiringCost
            end

          elsif zone_info[:sysname] =~ /PTAC/i
            zone_info[:systype] = 'PTAC'
            # Heating cost of PTAC is handled by Baseboard Convective Electric Heater entry in Equipment list!
            # Cooling cost of PTAC ...
            if zone_info[:coolcapacity] > 0
              # DX cooling unit
              # Maximum capacity for PTAC in RSMeans is 14.070 kW
              coolCapacity = zone_info[:coolcapacity] / zone.multiplier
              numUnits = get_HVAC_multiplier('FanCoilHtgClgVent', coolCapacity)
              # PTAC unit cost (Note that same numUnits multiple applied within getHVACCost())
              matCost, labCost = getHVACCost(zone_info[:sysname], 'PTAC', coolCapacity, false)
              thePTACUnitCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)
              # For each PTAC unit there will be an electrical junction box (wiring costed with distribution - not here)
              matCost, labCost = getHVACCost('Electrical Outlet Box', 'Box', 1, true)
              elecBoxCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * numUnits
              # Total PTAC cost for this zone (excluding distribution piping):
              thePTACCost = (thePTACUnitCost + elecBoxCost) * zone.multiplier
              zone_info[:coolcost] = thePTACCost
              zone_info[:num_units] = numUnits

              perimWiringCost = getPerimDistWiringCost(zone, nom_flr_hght, regional_material, regional_installation)
              zone_info[:wiringcost] = perimWiringCost

              totalCost += thePTACCost + perimWiringCost
            end

          elsif zone_info[:sysname] =~ /PTHP/i
            zone_info[:systype] = 'HP'
            # Cost of PTAC based on heating capacity...
            if zone_info[:heatcapacity] > 0
              # DX heat pump unit
              # Maximum capacity for HP (ASHP) in RSMeans is 14.650 kW
              heatCapacity = zone_info[:heatcapacity] / zone.multiplier
              numUnits = get_HVAC_multiplier('FanCoilHtgClgVent', heatCapacity)
              # HP unit cost (Note that same numUnits multiple applied within getHVACCost())
              matCost, labCost = getHVACCost(zone_info[:sysname], 'ashp', heatcapacity, false)
              theHPUnitCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)
              # For each HP unit there will be an electrical junction box (wiring costed with distribution - not here)
              matCost, labCost = getHVACCost('Electrical Outlet Box', 'Box', 1, true)
              elecBoxCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * numUnits
              # Total HP cost for this zone (excluding distribution piping):
              theHPCost = (theHPUnitCost + elecBoxCost) * zone.multiplier
              zone_info[:heatcoolcost] = thePTACCost
              zone_info[:num_units] = numUnits

              perimWiringCost = getPerimDistWiringCost(zone, nom_flr_hght, regional_material, regional_installation)
              zone_info[:wiringcost] = perimWiringCost

              totalCost += theHPCost + perimWiringCost
            end

          elsif zone_info[:sysname] =~ /2-pipe Fan Coil/i
            zone_info[:sfurnaceystype] = '2FC'
            if zone_info[:heatcapacity] > 0 || zone_info[:coolcapacity] > 0
              # Hot water heating and chilled water cooling type fan coil unit
              # Maximum capacity for FanCoilHtgClgVent in RSMeans is 17.585 kW
              capacityFCUnit = zone_info[:coolcapacity] > zone_info[:heatcapacity] ?
                               zone_info[:coolcapacity] / zone.multiplier : zone_info[:heatcapacity] / zone.multiplier
              numFCUnits = get_HVAC_multiplier('FanCoilHtgClgVent', capacityFCUnit)
              # 2PFC unit cost (Note that same numFCUnits multiple applied within getHVACCost())
              matCost, labCost = getHVACCost(zone_info[:sysname], 'FanCoilHtgClgVent', capacityFCUnit, false)
              fcUnitCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)
              # For each 2PFC unit there will be a shut-off valve, 2 Tee connections and 2 elbows to
              # isolate the convector from the hot water loop distribution for servicing and balancing.
              # Assumed unit piping is 1.25 inches in diameter.
              # Cost of valves:
              matCost, labCost = getHVACCost('1.25 inch gate valve', 'ValvesGate', 1.25, true)
              fcValvesCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * numFCUnits
              # Cost of tees:
              matCost, labCost = getHVACCost('1.25 inch copper tees', 'CopperPipeTee', 1.25, true)
              fcTeesCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * 2 * numFCUnits
              # Cost of elbows:
              matCost, labCost = getHVACCost('1.25 inch copper elbows', 'CopperPipeElbow', 1.25, true)
              fcElbowsCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * 2 * numFCUnits
              # For each 2PFC unit there will be an electrical junction box (wiring costed with distribution - not here)
              matCost, labCost = getHVACCost('Electrical Outlet Box', 'Box', 1, true)
              elecBoxCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * numFCUnits
              # Total 2PFC cost for this zone (excluding distribution piping):
              fcCost = (fcUnitCost + fcValvesCost + fcTeesCost + fcElbowsCost + elecBoxCost) * zone.multiplier
              zone_info[:heatcoolcost] = fcCost
              zone_info[:num_units] = numFCUnits

              # Cost for one set supply/return piping
              perimPipingCost = getPerimDistPipingCost(zone, nom_flr_hght, regional_material, regional_installation)
              zone_info[:pipingcost] = perimPipingCost

              perimWiringCost = getPerimDistWiringCost(zone, nom_flr_hght, regional_material, regional_installation)
              zone_info[:wiringcost] = perimWiringCost

              totalCost += fcCost + perimPipingCost + perimWiringCost
            end

          elsif zone_info[:sysname] =~ /4-pipe Fan Coil/i
            zone_info[:systype] = '4FC'
            if zone_info[:heatcapacity] > 0 || zone_info[:coolcapacity] > 0
              # Hot water heating and chilled water cooling type fan coil unit
              # Maximum capacity for FanCoilHtgClgVent in RSMeans is 17.585 kW
              capacityFCUnit = zone_info[:coolcapacity] > zone_info[:heatcapacity] ?
                                   zone_info[:coolcapacity] / zone.multiplier : zone_info[:heatcapacity] / zone.multiplier
              numFCUnits = get_HVAC_multiplier('FanCoilHtgClgVent', capacityFCUnit)
              # 4PFC unit cost (Note that same numFCUnits multiple applied within getHVACCost())
              matCost, labCost = getHVACCost(zone_info[:sysname], 'FanCoilHtgClgVent', capacityFCUnit, false)
              fcUnitCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)
              # For each 4PFC unit there will be 2 shut-off valves, 4 Tee connections and 4 elbows to
              # isolate the convector from the hot water loop distribution for servicing and balancing.
              # Assumed unit piping is 1.25 inches in diameter.
              # Cost of valves:
              matCost, labCost = getHVACCost('1.25 inch gate valve', 'ValvesGate', 1.25, true)
              fcValvesCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * 2 * numFCUnits
              # Cost of tees:
              matCost, labCost = getHVACCost('1.25 inch copper tees', 'CopperPipeTee', 1.25, true)
              fcTeesCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * 4 * numFCUnits
              # Cost of elbows:
              matCost, labCost = getHVACCost('1.25 inch copper elbows', 'CopperPipeElbow', 1.25, true)
              fcElbowsCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * 4 * numFCUnits
              # For each 4PFC unit there will be an electrical junction box (wiring costed with distribution - not here)
              matCost, labCost = getHVACCost('Electrical Outlet Box', 'Box', 1, true)
              elecBoxCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * numFCUnits
              # Total 4PFC cost for this zone (excluding distribution piping):
              fcCost = (fcUnitCost + fcValvesCost + fcTeesCost + fcElbowsCost + elecBoxCost) * zone.multiplier
              zone_info[:heatcoolcost] = fcCost
              zone_info[:num_units] = numFCUnits

              # Cost for two sets supply/return piping
              perimPipingCost = 2 * getPerimDistPipingCost(zone, nom_flr_hght, regional_material, regional_installation)
              zone_info[:pipingcost] = perimPipingCost

              perimWiringCost = getPerimDistWiringCost(zone, nom_flr_hght, regional_material, regional_installation)
              zone_info[:wiringcost] = perimWiringCost

              totalCost += fcCost + perimPipingCost + perimWiringCost
            end

          elsif zone_info[:sysname] =~ /Unit Heater/i || zone_info[:sysname] =~ /Unitary/i
            zone_info[:systype] = 'FUR'
            # Two types of unit heaters: electric and gas
            if zone_info[:sysname] =~ /Gas/i   # TODO: Need to test this!!!!
              needCentralGasHdr = true
              # The gas unit heaters are cabinet type with a burner and blower rather than the radiant type
              if zone_info[:heatcapacity] > 0
                # Maximum capacity for gas heater in RSMeans is 94.000 kW
                heatCapacity = zone_info[:heatcapacity] / zone.multiplier
                numUnits = get_HVAC_multiplier('gasheater', heatCapacity)
                # Unit cost (Note that same unit multiple applied within getHVACCost())
                matCost, labCost = getHVACCost(zone_info[:sysname], 'gasheater', heatCapacity, false)
                unitCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)
                # For each unit heater there will be an electrical junction box (wiring costed with distribution - not here)
                matCost, labCost = getHVACCost('Electrical Outlet Box', 'Box', 1, true)
                elecBoxCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * numUnits
                # It is assumed that the gas unit heater(s) are located in the centre of this zone. An 8 in exhaust duct
                # must be costed from the unit heater to the exterior via the roof. The centroid of this zone:
                if zone_info[:flrnum] > 1
                  # TODO: Consider determining vertical distance using z component of this zone and roof.
                  zoneCentroidToRoof_Ft = 10 + nom_flr_hght * zone_info[:flrnum]
                else
                  zoneCentroidToRoof_Ft = 10
                end
                matCost, labCost = getHVACCost('Unit heater exhaust duct', 'Ductwork-S', 8, true)
                exhaustductCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * zoneCentroidToRoof_Ft
                zone_info[:heatcost] = (unitCost + elecBoxCost + exhaustductCost) * zone.multiplier
                zone_info[:num_units] = numUnits
                totalCost += zone_info[:heatcost]
              end
            elsif zone_info[:sysname] =~ /Electric/i
              if zone_info[:heatcapacity] > 0
                # Maximum capacity for electric heater in RSMeans is 24.000 kW
                heatCapacity = zone_info[:heatcapacity] / zone.multiplier
                numUnits = get_HVAC_multiplier('elecheat', heatCapacity)
                # Unit cost (Note that same unit multiple applied within getHVACCost())
                matCost, labCost = getHVACCost(zone_info[:sysname], 'elecheat', heatCapacity, false)
                unitCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)
                # For each unit heater there will be an electrical junction box (wiring costed with distribution - not here)
                matCost, labCost = getHVACCost('Electrical Outlet Box', 'Box', 1, true)
                elecBoxCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * numUnits
                zone_info[:heatcost] = (unitCost + elecBoxCost) * zone.multiplier
                zone_info[:num_units] = numUnits
                totalCost += zone_info[:heatcost]
              end
            elsif zone_info[:sysname] =~ /Water/i  # Hot water unit heater
              if zone_info[:heatcapacity] > 0
                heatCapacity = zone_info[:heatcapacity] / zone.multiplier
                # Max capacity for hot water heater is 75300 Watts
                numUnits = get_HVAC_multiplier('hotwateruh', heatCapacity)
                matCost, labCost = getHVACCost(zone_info[:sysname], 'hotwateruh', heatCapacity, false)
                unitHtrCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)
                # For each unit heater there will be a shut-off valve, 2 Tee connections and 2 elbows to
                # isolate the convector from the hot water loop distribution for servicing and balancing.
                # Cost of valves:
                matCost, labCost = getHVACCost('1.25 inch gate valve', 'ValvesGate', 1.25, true)
                unitHtrValvesCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * numUnits
                # Cost of tees:
                matCost, labCost = getHVACCost('1.25 inch copper tees', 'CopperPipeTee', 1.25, true)
                unitHtrTeesCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * 2 * numUnits
                # Cost of elbows:
                matCost, labCost = getHVACCost('1.25 inch copper elbows', 'CopperPipeElbow', 1.25, true)
                unitHtrElbowsCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * 2 * numUnits
                # For each unit heater there will be an electrical junction box (wiring costed with distribution - not here)
                matCost, labCost = getHVACCost('Electrical Outlet Box', 'Box', 1, true)
                elecBoxCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * numUnits
                # Total convector cost for this zone (excluding distribution piping):
                unitHeaterCost = (unitHtrCost + unitHtrValvesCost + unitHtrTeesCost + unitHtrElbowsCost + elecBoxCost) * zone.multiplier
                zone_info[:heatcost] = unitHeaterCost
                zone_info[:num_units] = numUnits
                totalCost += unitHeaterCost
              end
            end
          elsif zone_info[:sysname] =~ /WindowAC/i
            zone_info[:systype] = 'WinAC'
            # Cooling cost of WindowAC ...
            if cooling_coil_name == 'nil'
              # The cooling coil name doesn't exist so must use a different method to determine cooling
              # capacity for window AC units!
              query = "SELECT Value FROM ComponentSizes WHERE CompName='WindowAC' AND Units='W'"
              coolCapVal = model.sqlFile().get().execAndReturnFirstDouble(query)
              zone_info[:coolcapacity] = coolCapVal.to_f / 1000.0 # Watts -> kW
            end
            if zone_info[:coolcapacity] > 0
              # DX cooling unit
              # Maximum capacity for Window AC in RSMeans is 3.516 kW
              coolCapacity = zone_info[:coolcapacity] / zone.multiplier
              numUnits = get_HVAC_multiplier('WINAC', coolCapacity)
              # Window AC unit cost (Note that same numUnits multiple applied within getHVACCost())
              matCost, labCost = getHVACCost(zone_info[:sysname], 'WINAC', coolCapacity, false)
              unitWinACCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)
              # For each WinAC unit there will be an electrical junction box (wiring costed with distribution - not here)
              matCost, labCost = getHVACCost('Electrical Outlet Box', 'Box', 1, true)
              elecBoxCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * numUnits
              # Total WinAC cost for this zone:
              theWinACCost = (unitWinACCost + elecBoxCost) * zone.multiplier
              zone_info[:coolcost] = theWinACCost
              zone_info[:num_units] = numUnits
              totalCost += theWinACCost
            end
          elsif zone_info[:sysname] =~ /Split/i
            zone_info[:systype] = 'MiniSplit'
            # Cooling cost of Mini-split AC ...
            if cooling_coil_name == 'nil'
              # The cooling coil name doesn't exist so must use a different method to determine cooling
              # capacity for mini-spli units!
              query = "SELECT Value FROM ComponentSizes WHERE CompName='WindowAC' AND Units='W'"
              coolCapVal = model.sqlFile().get().execAndReturnFirstDouble(query)
              zone_info[:coolcapacity] = coolCapVal.to_f / 1000.0 # Watts -> kW
            end
            if zone_info[:coolcapacity] > 0
              # Mini-splt cooling unit
              # Maximum capacity for the Mini-split in RSMeans is 7.032 kW
              coolCapacity = zone_info[:coolcapacity] / zone.multiplier
              numUnits = get_HVAC_multiplier('SplitSZWall', coolCapacity)
              # PTAC unit cost (Note that same numUnits multiple applied within getHVACCost())
              matCost, labCost = getHVACCost(zone_info[:sysname], 'PTAC', coolCapacity, false)
              theMiniSplitUnitCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)
              # For each PTAC unit there will be an electrical junction box (wiring costed with distribution - not here)
              matCost, labCost = getHVACCost('Electrical Outlet Box', 'Box', 1, true)
              elecBoxCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0) * numUnits
              # Total PTAC cost for this zone (excluding distribution piping):
              theMiniSplitCost = (theMiniSplitUnitCost + elecBoxCost) * zone.multiplier
              zone_info[:coolcost] = theMiniSplitCost
              zone_info[:num_units] = numUnits
              totalCost += theMiniSplitCost
            end

          end
          @costing_report['heating_and_cooling']['zonal_systems'] << {
              'systype' => zone_info[:systype],
              'zone_number' => numZones,
              'zone_name' => zone_info[:zonename],
              'zone_multiple' => zone_info[:multiplier],
              'heat_capacity(kW)' => zone_info[:heatcapacity].round(1),
              'cool_capacity(kW)' => zone_info[:coolcapacity].round(1),
              'heat_cost' => zone_info[:heatcost].round(2),
              'cool_cost' => zone_info[:coolcost].round(2),
              'heatcool_cost' => zone_info[:heatcoolcost].round(2),
              'piping_cost' => zone_info[:pipingcost].round(2),
              'wiring_cost' => zone_info[:wiringcost].round(2),
              'num_units' => zone_info[:num_units],
              'cummultive_zonal_cost' => totalCost.round(2)
          }
        end
      end # End of equipment loop
    end # End of zone loop

    # Add in cost of central gas line header if there are gas-fired unit heaters
    hdrGasLineCost = 0.0
    if needCentralGasHdr
      mechRmInBsmt ? numFlrs = numAGFlrs + 1 : numFlrs = numAGFlrs
      hdrGasLen = numFlrs * nom_flr_hght
      # Gas line - first one in spreadsheet
      matCost, labCost = getHVACCost('Central header gas line', 'GasLine', '')
      hdrGasLineCost = hdrGasLen * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)
    end

    puts "\nZonal systems costing data successfully generated. Total zonal systems costs: $#{totalCost.round(2)}"

    return totalCost + hdrGasLineCost
  end

  def getHeaderPipingDistributionCost(numAGFlrs, mechRmInBsmt, regional_material, regional_installation, pumpFlow, horz_dist, nom_flr_hght)
    # Hot water central header piping distribution costs. Note that the piping distribution cost
    # of zone piping is done in the zonalsys_costing function

    # Central header piping Cost
    supHdrCost = 0; retHdrCost = 0
    mechRmInBsmt ? numFlrs = numAGFlrs + 1 : numFlrs = numAGFlrs
    if numFlrs < 3
      # Header pipe is same diameter as distribution pipes to zone floors
      supHdrLen = numFlrs * nom_flr_hght

      # 1.25 inch Steel pipe
      matCost, labCost = getHVACCost('Header 1.25 inch steel pipe', 'SteelPipe', 1.25)
      supHdrpipingCost = supHdrLen * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

      # 1.25 inch Steel pipe insulation
      matCost, labCost = getHVACCost('Header 1.25 inch pipe insulation', 'PipeInsulation', 1.25)
      supHdrInsulCost = supHdrLen * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

      # 1.25 inch gate valves
      matCost, labCost = getHVACCost('Header 1.25 inch gate valves', 'ValvesGate', 1.25)
      supHdrValvesCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

      # 1.25 inch tee
      matCost, labCost = getHVACCost('Header 1.25 inch steel tee', 'SteelPipeTee', 1.25)
      supHdrTeeCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

      supHdrCost = supHdrpipingCost + supHdrInsulCost + supHdrValvesCost + supHdrTeeCost
      retHdrCost = supHdrCost
    else  # Greater than 3 floors (including basement)
      # Use pumpFlow to determine pipe size
      if pumpFlow <= 0.0001262
        hdrPipeSize = 0.5
      elsif pumpFlow > 0.0001262 && pumpFlow <= 0.0002524
        hdrPipeSize = 0.75
      elsif pumpFlow > 0.0002524 && pumpFlow <= 0.0005047
        hdrPipeSize = 1.0
      elsif pumpFlow > 0.0005047 && pumpFlow <= 0.0010090
        hdrPipeSize = 1.25
      elsif pumpFlow > 0.0010090 && pumpFlow <= 0.0015773
        hdrPipeSize = 1.5
      elsif pumpFlow > 0.0015773 && pumpFlow <= 0.0031545
        hdrPipeSize = 2.0
      elsif pumpFlow > 0.0031545
        hdrPipeSize = 2.5
      end

      hdrPipeLen = horz_dist + nom_flr_hght * numFlrs

      # Steel pipe
      matCost, labCost = getHVACCost("Header Steel Pipe - #{hdrPipeSize} inch", 'SteelPipe', hdrPipeSize)
      supHdrpipingCost = hdrPipeLen * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

      # Steel pipe insulation
      matCost, labCost = getHVACCost("Header Pipe Insulation - #{hdrPipeSize} inch", 'PipeInsulation', hdrPipeSize)
      supHdrInsulCost = hdrPipeLen * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

      # Gate valves
      matCost, labCost = getHVACCost("Header Gate Valves - #{hdrPipeSize} inch", 'ValvesGate', hdrPipeSize)
      supHdrValvesCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

      # Tee
      matCost, labCost = getHVACCost("Header Steel Tee - #{hdrPipeSize} inch", 'SteelPipeTee', hdrPipeSize)
      supHdrTeeCost = (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

      supHdrCost = supHdrpipingCost + supHdrInsulCost + supHdrValvesCost + supHdrTeeCost
      retHdrCost = supHdrCost
    end

    hdrPipeCost = supHdrCost + retHdrCost

    # Electrical header costs. Central electric header cost for zonal heatingunits
    hdrLen = numFlrs * nom_flr_hght

    # Conduit - only one spreadsheet entry
    matCost, labCost = getHVACCost('Header Metal conduit', 'Conduit', '')
    hdrConduitCost = hdrLen * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

    # Wiring - size 10
    matCost, labCost = getHVACCost('Header No 10 Wiring', 'Wiring', 10)
    hdrWireCost = hdrLen / 100 * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

    # Box - size 4
    matCost, labCost = getHVACCost('Header 4 inch deep Box', 'Box', 4)
    hdrBoxCost = numFlrs * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

    elecHdrCost = hdrConduitCost + hdrWireCost + hdrBoxCost

    # Central gas header cost will be determined in zonalsys_costing function since
    # this cost depends on existence of at least one gas-fired unit heater in building.

    hdrDistributionCost = hdrPipeCost + elecHdrCost

    return hdrDistributionCost
  end

  def getPerimDistPipingCost(zone, nom_flr_hght, regional_material, regional_installation)
    # Get perimeter distribution piping cost
    extWallArea = 0.0
    perimPipingCost = 0.0
    zone.spaces.sort.each do |space|
      if space.spaceType.empty? or space.spaceType.get.standardsSpaceType.empty? or space.spaceType.get.standardsBuildingType.empty?
        raise ("standards Space type and building type is not defined for space:#{space.name.get}. Skipping this space for costing.")
      end
      extWallArea += OpenStudio.convert(space.exteriorWallArea.to_f,"m^2","ft^2").get  # sq.ft.
    end
    perimTotal = ( extWallArea / nom_flr_hght ) * zone.multiplier

    # 1.25 inch Steel pipe
    matCost, labCost = getHVACCost('Perimeter Distribution - 1.25 inch steel pipe', 'SteelPipe', 1.25)
    perimPipingCost = perimTotal * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

    # 1.25 inch Steel pipe insulation
    matCost, labCost = getHVACCost('Perimeter Distribution - 1.25 inch pipe insulation', 'PipeInsulation', 1.25)
    perimPipingCost += perimTotal * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

    return perimPipingCost
  end

  def getPerimDistWiringCost(zone, nom_flr_hght, regional_material, regional_installation)
    # Get perimeter distribution wiring cost
    extWallArea = 0.0
    perimWiringCost = 0.0
    zone.spaces.sort.each do |space|
      if space.spaceType.empty? or space.spaceType.get.standardsSpaceType.empty? or space.spaceType.get.standardsBuildingType.empty?
        raise ("standards Space type and building type is not defined for space:#{space.name.get}. Skipping this space for costing.")
      end
      extWallArea += OpenStudio.convert(space.exteriorWallArea.to_f,"m^2","ft^2").get  # sq.ft.
    end
    perimTotal = ( extWallArea / nom_flr_hght ) * zone.multiplier

    # Conduit - only one spreadsheet entry
    matCost, labCost = getHVACCost('Perimeter Distribution - Metal conduit', 'Conduit', '')
    perimWiringCost = perimTotal * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

    # Wiring - size 10
    matCost, labCost = getHVACCost('Perimeter Distribution - No 10 Wiring', 'Wiring', 10)
    perimWiringCost += perimTotal / 100 * (matCost * regional_material / 100.0 + labCost * regional_installation / 100.0)

    return perimWiringCost
  end
end