class BTAPCosting
  def ventilation_costing(model, prototype_creator)
    @costing_report['ventilation'] = {system_1: [], system_2: [], system_3: [], system_4: [], system_5: [], system_6: [], system_7: [], mech_to_roof: [], trunk_duct: [], floor_trunk_ducts: [], tz_distribution: [], hrv_return_ducting: []}
    mech_sizing_info = read_mech_sizing()
    mech_room, cond_spaces = prototype_creator.find_mech_room(model)
    roof_cent = prototype_creator.find_highest_roof_centre(model)
    min_space = get_lowest_space(spaces: cond_spaces)
    vent_cost = 0
    vent_cost += ahu_costing(model: model, prototype_creator: prototype_creator, mech_room: mech_room, roof_cent: roof_cent, mech_sizing_info: mech_sizing_info, min_space: min_space)
    return vent_cost
  end

  def ahu_costing(model:, prototype_creator:, mech_room:, roof_cent:, mech_sizing_info:, min_space:)
    ahu_cost = 0
    heat_type = {
        'HP' => 0,
        'elec' => 0,
        'Gas' => 0,
        'HW' => 0
    }
    cool_type = {
        'DX' => 0,
        'CHW' => 0
    }
    rt_unit_num = 0
    total_vent_flow_m3_per_s = 0
    sys_1_4 = true
    hvac_floors = []
    model.getAirLoopHVACs.sort.each do |airloop|
      ind_ahu_cost = 0
      @airloop_info = nil
      airloop_name = airloop.nameString
      if /Sys_/.match(airloop_name).nil?
        next
      else
        sys_type = airloop_name[4].to_i
        sys_type = 1 if sys_type == 4
      end
      rt_unit_num += 1

      @airloop_info = {sys_type: sys_type}
      @airloop_info[:name] = airloop_name

      airloop_flow_m3_per_s = (model.getAutosizedValue(airloop, 'Design Supply Air Flow Rate', 'm3/s').to_f)
      airloop_flow_cfm = (OpenStudio.convert(airloop_flow_m3_per_s, 'm^3/s', 'cfm').get)
      airloop_flow_lps = (OpenStudio.convert(airloop_flow_m3_per_s, 'm^3/s', 'L/s').get)
      total_vent_flow_m3_per_s += airloop_flow_m3_per_s
      heat_cap = {
          'HP' => 0,
          'elec' => 0,
          'Gas' => 0,
          'HW' => 0
      }
      cool_cap = {
          'DX' => 0,
          'CHW' => 0
      }
      @airloop_info[:airloop_flow_m3_per_s] = airloop_flow_m3_per_s.round(3)
      al_eq_reporting_info = []
      total_heat_cool_cost = 0
      #@airloop_info[:equipment_info] = []
      hrv_info = get_hrv_info(airloop: airloop, model: model)
      airloop.supplyComponents.sort.each do |supplycomp|
        obj_type = supplycomp.iddObjectType.valueName.to_s
        mech_capacity = 0
        heating_fuel = 'none'
        cooling_type = 'none'
        cat_search = nil
        case obj_type
        when /OS_Coil_Heating_DX_VariableSpeed/
          heating_fuel = 'HP'
          suppcomp = supplycomp.to_CoilHeatingDXVariableSpeed.get
          if suppcomp.isRatedHeatingCapacityAtSelectedNominalSpeedLevelAutosized
            mech_capacity = (model.getAutosizedValue(supplycomp, 'Design Size Nominal Heating Capacity', 'W').to_f)/(1000.0)
          else
            mech_capacity = suppcomp.ratedHeatingCapacityAtSelectedNominalSpeedLevel.to_f/1000.0
          end
          cat_search = 'ashp'
          heat_cap['HP'] += mech_capacity
        when /OS_Coil_Heating_DX_SingleSpeed/
          heating_fuel = 'HP'
          suppcomp = supplycomp.to_CoilHeatingDXSingleSpeed.get
          if suppcomp.isRatedTotalHeatingCapacityAutosized
            mech_capacity = (model.getAutosizedValue(supplycomp, 'Design Size Gross Rated Heating Capacity', 'W').to_f)/(1000.0)
          else
            mech_capacity = suppcomp.ratedTotalHeatingCapacity.to_f/1000.0
          end
          cat_search = 'ashp'
          heat_cap['HP'] += mech_capacity
        when 'OS_Coil_Heating_Electric'
          heating_fuel = 'elec'
          suppcomp = supplycomp.to_CoilHeatingElectric.get
          if suppcomp.isNominalCapacityAutosized
            mech_capacity = (model.getAutosizedValue(supplycomp, 'Design Size Nominal Capacity', 'W').to_f)/(1000.0)
          else
            mech_capacity = suppcomp.nominalCapacity.to_f/1000.0
          end
          cat_search = 'elecheat'
          heat_cap['elec'] += mech_capacity
        when /OS_Coil_Heating_Gas/
          heating_fuel = 'Gas'
          suppcomp = supplycomp.to_CoilHeatingGas.get
          if suppcomp.isNominalCapacityAutosized
            mech_capacity = (model.getAutosizedValue(supplycomp, 'Design Size Nominal Capacity', 'W').to_f)/(1000.0)
          else
            mech_capacity = suppcomp.nominalCapacity.to_f/1000.0
          end
          cat_search = 'FurnaceGas'
          heat_cap['Gas'] += mech_capacity
        when /OS_Coil_Heating_Water/
          heating_fuel = 'HW'
          suppcomp = supplycomp.to_CoilHeatingWater.get
          if suppcomp.isRatedCapacityAutosized
            mech_capacity = (model.getAutosizedValue(supplycomp, 'Design Size Rated Capacity', 'W').to_f)/(1000.0)
          else
            suppcomp.ratedCapacity.to_f/1000.0
          end
          cat_search = 'coils'
          heat_cap['HW'] += mech_capacity
        when /OS_Coil_Cooling_DX_SingleSpeed/
          cooling_type = 'DX'
          suppcomp = supplycomp.to_CoilCoolingDXSingleSpeed.get
          if suppcomp.isRatedTotalCoolingCapacityAutosized
            mech_capacity = (model.getAutosizedValue(supplycomp, 'Design Size Gross Rated Total Cooling Capacity', 'W').to_f)/(1000.0)
          else
            mech_capacity = suppcomp.ratedTotalCoolingCapacity.to_f/1000.0
          end
          cat_search = 'DX'
          cool_cap['DX'] += mech_capacity
        when /OS_Coil_Cooling_DX_VariableSpeed/
          cooling_type = 'DX'
          suppcomp = supplycomp.to_CoilCoolingDXVariableSpeed.get
          if suppcomp.isGrossRatedTotalCoolingCapacityAtSelectedNominalSpeedLevelAutosized
            mech_capacity = (model.getAutosizedValue(supplycomp, 'Design Size Rated Total Cooling Capacity', 'W').to_f)/(1000.0)
          else
            mech_capacity = suppcomp.grossRatedTotalCoolingCapacityAtSelectedNominalSpeedLevel.to_f/1000.0
          end
          cat_search = 'DX'
          cool_cap['DX'] += mech_capacity
        when /Coil_Cooling_Water/
          cooling_type = 'CHW'
          mech_capacity = (model.getAutosizedValue(supplycomp, 'Design Size Design Coil Load', 'W').to_f)/(1000.0)
          cat_search = 'coils'
          cool_cap['CHW'] += mech_capacity
        end
        equipment_info = {
            supply_comp: supplycomp,
            heating_fuel: heating_fuel,
            cooling_type: cooling_type,
            mech_capacity_kw: mech_capacity,
            cat_search: cat_search
        }
        unless equipment_info[:mech_capacity_kw].to_f <= 0
          # Get ventilation heating and cooling equipment costs.
          heat_cool_cost = cost_heat_cool_equip(equipment_info: equipment_info, sys_type: sys_type)
          total_heat_cool_cost += heat_cool_cost
          al_eq_reporting_info = add_heat_cool_to_report(equipment_info: equipment_info, heat_cool_cost: heat_cool_cost, obj_type: obj_type, al_eq_reporting_info: al_eq_reporting_info)
        end
      end
      hvac_floors = gen_hvac_info_by_floor(hvac_floors: hvac_floors, model: model, prototype_creator: prototype_creator, airloop: airloop, sys_type: sys_type, hrv_info: hrv_info)
      sys_1_4 = false unless (sys_type == 1 || sys_type == 4)

      # Determine the predominant heating and cooling fuel type.
      heating_fuel = heat_cap.max_by{|key, value| value}[0]
      cooling_type = cool_cap.max_by{|key, value| value}[0]

      heat_type[heating_fuel] += 1
      cool_type[cooling_type] += 1
      # Cost rooftop ventilation unit.
      ind_ahu_cost = cost_ahu(sys_type: sys_type, airloop_flow_lps: airloop_flow_lps, heating_fuel: heating_fuel, cooling_type: cooling_type, airloop_name: airloop_name)
      # Remove gas burner cost if ventilation air not heated with a gas heating system.
      ind_ahu_cost -= gas_burner_cost(heating_fuel: heating_fuel, sys_type: sys_type, airloop_flow_cfm: airloop_flow_cfm)
      reheat_cost, reheat_array = reheat_recool_cost(airloop: airloop, prototype_creator: prototype_creator, model: model, roof_cent: roof_cent, mech_sizing_info: mech_sizing_info)

      if hrv_info[:hrv_present]
        ind_hrv_cost = hrv_cost(hrv_info: hrv_info, airloop: airloop)
        hrv_info[:return_cap_m3ps] >= hrv_info[:hrv_size_m3ps] ? hrv_add_return_flow_m3ps = 0.0 : hrv_add_return_flow_m3ps = hrv_info[:hrv_size_m3ps] - hrv_info[:return_cap_m3ps]
        hrv_rep = {
            hrv_type: (hrv_info[:hrv_data].iddObjectType.valueName.to_s)[3..-1],
            hrv_name: hrv_info[:hrv_data].nameString,
            hrv_size_m3ps: hrv_info[:hrv_size_m3ps].round(3),
            hrv_return_fan_size_m3ps: hrv_add_return_flow_m3ps.round(3),
            hrv_cost: ind_hrv_cost.round(2)
        }
      else
        hrv_rep = {}
      end
      hrv_info[:hrv_present] ? ind_hrv_cost = hrv_cost(hrv_info: hrv_info, airloop: airloop) : ind_hrv_cost = 0
      @airloop_info[:base_ahu_cost] = (ind_ahu_cost).round(2)
      @airloop_info[:hrv] = hrv_rep
      ahu_cost += ind_ahu_cost + reheat_cost + ind_hrv_cost + total_heat_cool_cost
      @airloop_info[:equipment_info] = al_eq_reporting_info
      @airloop_info[:reheat_recool] = reheat_array
      @costing_report['ventilation'].each {|key, value| value << @airloop_info if key.to_s == ('system_' + sys_type.to_s)}
    end
    mech_roof_cost, mech_roof_rep = mech_to_roof_cost(heat_type: heat_type, cool_type: cool_type, mech_room: mech_room, roof_cent: roof_cent, rt_unit_num: rt_unit_num)
    @costing_report['ventilation'][:mech_to_roof] = mech_roof_rep
    trunk_duct_cost, trunk_duct_info = vent_trunk_duct_cost(tot_air_m3pers: total_vent_flow_m3_per_s, min_space: min_space, roof_cent: roof_cent, mech_sizing_info: mech_sizing_info, sys_1_4: sys_1_4)
    @costing_report['ventilation'][:trunk_duct] << trunk_duct_info
    floor_dist_cost, build_floor_trunk_info = floor_vent_dist_cost(hvac_floors: hvac_floors, prototype_creator: prototype_creator, roof_cent: roof_cent, mech_sizing_info: mech_sizing_info)
    @costing_report['ventilation'][:floor_trunk_ducts] << build_floor_trunk_info
    tz_dist_cost, duct_dist_rep = tz_vent_dist_cost(hvac_floors: hvac_floors, mech_sizing_info: mech_sizing_info)
    @costing_report['ventilation'][:tz_distribution] << duct_dist_rep
    hrv_ducting_cost, hrv_ret_duct_report = hrv_duct_cost(prototype_creator: prototype_creator, roof_cent: roof_cent, mech_sizing_info: mech_sizing_info, hvac_floors: hvac_floors)
    @costing_report['ventilation'][:hrv_return_ducting] = hrv_ret_duct_report
    ahu_cost += (mech_roof_cost + trunk_duct_cost + floor_dist_cost + tz_dist_cost + hrv_ducting_cost)
    return ahu_cost
  end

  def vent_assembly_cost(ids:, id_quants:, overall_mult:)
    total_cost = 0
    ids.each_with_index do |id, index|
      mat_cost_info = @costing_database['raw']['materials_hvac'].select {|data|
        data['materials_hvac_id'].to_i == id.to_i
      }.first
      if mat_cost_info.nil?
        puts("Error: no assembly information available for material id #{id}!")
        raise
      end
      total_cost += get_vent_mat_cost(mat_cost_info: mat_cost_info)*id_quants[index].to_f
    end
    return total_cost*overall_mult
  end

  def get_vent_system_mult(loop_equip:, mult_floor: nil)
    heat_cool_cost = @costing_database['raw']['materials_hvac'].select {|data|
      data['Material'].to_s.upcase == loop_equip[:cat_search].to_s.upcase
    }
    if heat_cool_cost.nil?
      puts("Error: no ahu information available for equipment #{loop_equip[:supply_comp].nameString}!")
      raise
    elsif heat_cool_cost.empty?
      puts("Error: no ahu information available for equipment #{loop_equip[:supply_comp].nameString}!")
      raise
    end
    if heat_cool_cost.length == 1
      max_size = heat_cool_cost[0]
    else
      if mult_floor.nil?
        max_size = heat_cool_cost.max_by {|element| element['Size'].to_f}
      else
        max_size = heat_cool_cost.select {|data|
          data['Size'].to_s == mult_floor.to_f
        }.first
        if max_size.nil?
          puts("Error: could not find #{loop_equip[:cat_search]} with size #{mult_floor}!")
          raise
        end
      end
    end
    if max_size['Size'].to_f <= 0
      puts("Error: #{loop_equip[:cat_search]} has a size of 0 or less.  Please check that the correct costing_database.json file is being used or check the costing spreadsheet!")
      raise
    end
    mult = (loop_equip[:mech_capacity_kw].to_f) / (max_size['Size'].to_f)
    mult > (mult.to_i).to_f.round(0) ? multiplier = (mult.to_i).to_f.round(0) + 1 : multiplier = mult.round(0)
    return max_size, multiplier.to_f
  end

  def get_ahu_mult(loop_equip:)
    ahu = @costing_database['raw']['hvac_vent_ahu'].select {|data|
      data['Sys_type'].to_i == loop_equip[:sys_type].to_i and
          data['Htg'].to_s.upcase == loop_equip[:heating_fuel].to_s.upcase and
          data['Clg'].to_s.upcase == loop_equip[:cooling_type].to_s.upcase
    }
    if ahu.nil?
      puts("Error: no ahu information available for equipment #{loop_equip[:airloop_name]}!")
      raise
    elsif ahu.empty?
      puts("Error: no ahu information available for equipment #{loop_equip[:airloop_name]}!")
      raise
    end
    ahu.length == 1 ? max_size = ahu[0] : max_size = ahu.max_by {|element| element['Supply_air']}
    if max_size['Supply_air'].to_f <= 0
      puts("Error: #{loop_equip[:airloop_name]} has a size of 0 or less.  Please check that the correct costing_database.json file is being used or check the costing spreadsheet!")
      raise
    end
    mult = (loop_equip[:airloop_flow_lps].to_f) / (max_size['Supply_air'].to_f)
    mult > (mult.to_i).to_f.round(0) ? multiplier = (mult.to_i).to_f.round(0) + 1 : multiplier = mult.round(0)
    return max_size, multiplier
  end

  def get_vent_mat_cost(mat_cost_info:)
    if mat_cost_info.nil?
      puts("Error: no assembly information available for material!")
      raise
    end
    rs_means_data = @costing_database['rsmean_api_data'].detect {|data| data['id'].to_s.upcase == mat_cost_info['id'].to_s.upcase}
    if rs_means_data.nil?
      puts("Error: no rsmeans information available for material id #{mat_cost_info['id']}!")
      raise
    elsif rs_means_data['baseCosts']['materialOpCost'].nil? || rs_means_data['baseCosts']['laborOpCost'].nil?
      puts("Error: rsmeans costing information for material id #{mat_cost_info['id']} is nil.  Please check rsmeans data.")
      return 0.0
    end
    mat_mult, inst_mult = get_regional_cost_factors(@costing_report['rs_means_prov'], @costing_report['rs_means_city'], mat_cost_info)
    if mat_mult.nil? || inst_mult.nil?
      puts("Error: no localization information available for material id #{id}!")
      raise
    end
    mat_cost = rs_means_data['baseCosts']['materialOpCost']*(mat_mult/100.0)
    lab_cost = rs_means_data['baseCosts']['laborOpCost']*(inst_mult/100.0)
    quantity = mat_cost_info['quantity'].to_f
    quantity = 1.0 if quantity == 0
    return (mat_cost+lab_cost)*quantity
  end

  def cost_heat_cool_equip(equipment_info:, sys_type:)
    total_cost = 0
    multiplier = 1.0
    heat_cool_cost = @costing_database['raw']['materials_hvac'].select {|data|
      data['Material'].to_s.upcase == equipment_info[:cat_search].to_s.upcase and
          data['Size'].to_f.round(8) >= equipment_info[:mech_capacity_kw].to_f
    }.first
    if heat_cool_cost.nil?
      heat_cool_cost, multiplier = get_vent_system_mult(loop_equip: equipment_info)
    end
    total_cost += (get_vent_mat_cost(mat_cost_info: heat_cool_cost))*multiplier
    if equipment_info[:cooling_type] == 'DX'
      multiplier = 1.0
      equipment_info[:cat_search] = 'CondensingUnit'
      heat_cool_cost = @costing_database['raw']['materials_hvac'].select {|data|
        data['Material'].to_s.upcase == equipment_info[:cat_search].to_s.upcase and
            data['Size'].to_f.round(8) >= equipment_info[:mech_capacity_kw].to_f
      }.first
      if heat_cool_cost.nil?
        heat_cool_cost, multiplier = get_vent_system_mult(loop_equip: equipment_info)
      end
      total_cost += get_vent_mat_cost(mat_cost_info: heat_cool_cost)*multiplier

      piping_search = []

      piping_search << {
          mat: 'SteelPipe',
          unit: 'L.F.',
          size: 1.25,
          mult: 32.8
      }
      piping_search << {
          mat: 'PipeInsulationsilica',
          unit: 'L.F.',
          size: 1.25,
          mult: 32.8
      }
      piping_search << {
          mat: 'SteelPipeElbow',
          unit: 'each',
          size: 1.25,
          mult: 8
      }
      total_cost += get_comp_cost(cost_info: piping_search)*multiplier
    end
    # This needs to be revised as currently the costing spreadsheet may not inculde heating and cooling coil costs in
    # the ahu definition sheet.  This is commented out for now but will need to be revisited.  See btap_tasks issue 156.
=begin
    if equipment_info[:heating_fuel] == 'HP'
      if sys_type == 3 || sys_type == 6
        # Remove the DX cooling unit for ashp in type 3 and 6 systems
        heat_cool_cost = @costing_database['raw']['materials_hvac'].select {|data|
          data['Material'].to_s.upcase == 'DX' and
              data['Size'].to_f.round(8) >= equipment_info[:mech_capacity_kw].to_f
        }.first
        if heat_cool_cost.nil?
          heat_cool_cost, multiplier = get_vent_system_mult(loop_equip: equipment_info)
        end
        total_cost -= (get_vent_mat_cost(mat_cost_info: heat_cool_cost))*multiplier

        # Remove the heating coil for ashp in type 3 and 6 systems
        heat_cool_cost = @costing_database['raw']['materials_hvac'].select {|data|
          data['Material'].to_s.upcase == 'COILS' and
              data['Size'].to_f.round(8) >= equipment_info[:mech_capacity_kw].to_f
        }.first
        if heat_cool_cost.nil?
          heat_cool_cost, multiplier = get_vent_system_mult(loop_equip: equipment_info)
        end
        total_cost -= (get_vent_mat_cost(mat_cost_info: heat_cool_cost))*multiplier
        puts 'hello'
      end
      # Add pre-heat for ashp in all cases
      # This needs to be refined as well.  Only add the cost of an electric heat if a heater (presumably of any type) if
      # one is not already explicitly modeled in the air loop (and thus costed already as part of this method).  This is
      # also part of btap_tasks issue 156.
      heat_cool_cost = @costing_database['raw']['materials_hvac'].select {|data|
        data['Material'].to_s.upcase == 'ELECHEAT' and
            data['Size'].to_f.round(8) >= equipment_info[:mech_capacity_kw].to_f
      }.first
      if heat_cool_cost.nil?
        heat_cool_cost, multiplier = get_vent_system_mult(loop_equip: equipment_info)
      end
      total_cost += (get_vent_mat_cost(mat_cost_info: heat_cool_cost))*multiplier
    end
=end
    return total_cost
  end

  def gas_burner_cost(heating_fuel:, sys_type:, airloop_flow_cfm:)
    unless (heating_fuel.upcase == 'NONE' || heating_fuel.upcase == 'GAS') || (sys_type == 3 || sys_type == 6)
      if airloop_flow_cfm >= 1000 && airloop_flow_cfm <= 1500
        return get_vent_mat_cost(mat_cost_info: {'id' => 235513161140, 'quantity' => 1})
      elsif airloop_flow_cfm > 1500
        return get_vent_mat_cost(mat_cost_info: {'id' => 235513161180, 'quantity' => 1})
      end
    end
    return 0.0
  end

  def cost_ahu(sys_type:, airloop_flow_lps:, heating_fuel:, cooling_type:, airloop_name:)
    mult = 1
    ahu = @costing_database['raw']['hvac_vent_ahu'].select {|data|
      data['Sys_type'].to_i == sys_type and
          data['Supply_air'].to_f >= airloop_flow_lps and
          data['Htg'].to_s == heating_fuel and
          data['Clg'].to_s == cooling_type
    }.first
    if ahu.nil?
      loop_equip = {
          sys_type: sys_type,
          heating_fuel: heating_fuel,
          cooling_type: cooling_type,
          airloop_flow_lps: airloop_flow_lps,
          airloop_name: airloop_name
      }
      ahu, mult = get_ahu_mult(loop_equip: loop_equip)
    end
    @airloop_info[:num_rooftop_units] = mult
    ids = ahu['id_layers'].to_s.split(',')
    id_quants = ahu['Id_layers_quantity_multipliers'].to_s.split(',')
    overall_mult = ahu['material_mult'].to_f
    overall_mult = 1.0 if overall_mult == 0
    return mult*vent_assembly_cost(ids: ids, id_quants: id_quants, overall_mult: overall_mult)
  end

  def mech_to_roof_cost(heat_type:, cool_type:, mech_room:, roof_cent:, rt_unit_num:)
    mech_to_roof_rep = {
        Gas_Line_m: 0.0,
        HW_Line_m: 0.0,
        CHW_Line_m: 0.0,
        Elec_Line_m: 0.0,
        Total_cost: 0.0
    }
    mech_dist = [(roof_cent[:roof_centroid][0] - mech_room['space_centroid'][0]), (roof_cent[:roof_centroid][1] - mech_room['space_centroid'][1]), (roof_cent[:roof_centroid][2] - mech_room['space_centroid'][2])]
    utility_dist = 0
    ut_search = []
    rt_roof_dist = OpenStudio.convert(10, 'm', 'ft').get
    mech_dist.each{|dist| utility_dist+= dist.abs}
    utility_dist = OpenStudio.convert(utility_dist, 'm', 'ft').get
    heat_type.each do |key, value|
      if value >= 1
        case key
        when 'HP'
          next
        when 'elec'
          next
        when 'Gas'
          ut_search << {
              mat: 'GasLine',
              unit: 'L.F.',
              size: 0,
              mult: utility_dist + rt_roof_dist*value
          }
          heat_type['Gas'] = 0
          mech_to_roof_rep[:Gas_Line_m] == (utility_dist + rt_roof_dist*value).round(1)
        when 'HW'
          ut_search << {
              mat: 'SteelPipe',
              unit: 'L.F.',
              size: 4,
              mult: 2*utility_dist + 2*rt_roof_dist*value
          }
          mech_to_roof_rep[:HW_Line_m] = (2*utility_dist + 2*rt_roof_dist*value).round(1)
          ut_search << {
              mat: 'PipeInsulation',
              unit: 'none',
              size: 4,
              mult: 2*utility_dist + 2*rt_roof_dist*value
          }
          ut_search << {
              mat: 'PipeJacket',
              unit: 'none',
              size: 4,
              mult: 2*utility_dist + 2*rt_roof_dist*value
          }
        end
      end
    end

    cool_type.each do |key, value|
      if value >= 1
        case key
        when 'DX'
          next
        when 'CHW'
          ut_search << {
              mat: 'SteelPipe',
              unit: 'L.F.',
              size: 4,
              mult: 2*utility_dist + 2*rt_roof_dist*value
          }
          mech_to_roof_rep[:CHW_Line_m] = (2*utility_dist + 2*rt_roof_dist*value).round(1)
          ut_search << {
              mat: 'PipeInsulation',
              unit: 'none',
              size: 4,
              mult: 2*utility_dist + 2*rt_roof_dist*value
          }
          ut_search << {
              mat: 'PipeJacket',
              unit: 'none',
              size: 4,
              mult: 2*utility_dist + 2*rt_roof_dist*value
          }
        end
      end
    end
    mech_to_roof_rep[:Elec_Line_m] = (utility_dist + rt_unit_num*rt_roof_dist).round(1)
    ut_search << {
        mat: 'Wiring',
        unit: 'CLF',
        size: 10,
        mult: (utility_dist + rt_unit_num*rt_roof_dist)/100
    }
    ut_search << {
        mat: 'Conduit',
        unit: 'L.F.',
        size: 0,
        mult: utility_dist + rt_unit_num*rt_roof_dist
    }
    total_comp_cost = get_comp_cost(cost_info: ut_search)
    mech_to_roof_rep[:Total_cost] = total_comp_cost.round(2)
    return total_comp_cost, mech_to_roof_rep
  end

  def reheat_recool_cost(airloop:, prototype_creator:, model:, roof_cent:, mech_sizing_info:)
    heat_cost = 0
    out_reheat_array = []
    airloop.thermalZones.sort.each do |thermalzone|
      tz_mult = thermalzone.multiplier.to_f
      thermalzone.equipment.sort.each do |eq|
        tz_eq_cost = 0
        terminal, box_name = get_airloop_terminal_type(eq: eq)

        next if box_name.nil?
        air_m3_per_s = (model.getAutosizedValue(terminal, 'Design Size Maximum Air Flow Rate', 'm3/s').to_f)/(tz_mult)
        tz_centroids = prototype_creator.thermal_zone_get_centroid_per_floor(thermalzone)
        if box_name == 'CVMixingBoxes'
          tz_eq_cost, box_info = reheat_coil_costing(terminal: terminal, tz_centroids: tz_centroids, model: model, tz: thermalzone, roof_cent: roof_cent, tz_mult: tz_mult, mech_sizing_info: mech_sizing_info, air_m3_per_s: air_m3_per_s, box_name: box_name)
        else
          tz_eq_cost, box_info = vav_cost(terminal: terminal, tz_centroids: tz_centroids, tz: thermalzone, roof_cent: roof_cent, mech_sizing_info: mech_sizing_info, air_flow_m3_per_s: air_m3_per_s, box_name: box_name)
        end
        heat_cost += tz_mult*tz_eq_cost
        out_reheat_array << {
            terminal: (terminal.iddObjectType.valueName.to_s)[3..-1],
            zone_mult: tz_mult,
            box_type: box_name,
            box_name: terminal.nameString,
            unit_info: box_info,
            cost: tz_eq_cost.round(2)
        }
      end
    end
    return heat_cost, out_reheat_array
  end

  def get_airloop_terminal_type(eq:)
    case eq.iddObject.name
    when /OS:AirTerminal:SingleDuct:ConstantVolume:Reheat/
      terminal = eq.to_AirTerminalSingleDuctConstantVolumeReheat.get
      box_name = 'CVMixingBoxes'
    when /OS:AirTerminal:VAV:HeatAndCool:NoReheat/
      terminal = eq.to_AirTerminalVavHeatAndCoolNoReheat.get
      box_name = 'VAVFanMixingBoxesClg'
    when /OS:AirTerminal:VAV:HeatAndCool:Reheat/
      terminal = eq.to_AirTerminalVAVHeatAndCoolReheat.get
      box_name = 'VAVFanMixingBoxesHtg'
    when /OS:AirTerminal:SingleDuct:VAV:NoReheat/
      terminal = eq.to_AirTerminalSingleDuctVavNoReheat.get
      box_name = 'VAVFanMixingBoxesClg'
    when /OS:AirTerminal:SingleDuct:VAV:Reheat/
      terminal = eq.to_AirTerminalSingleDuctVAVReheat.get
      box_name = 'VAVFanMixingBoxesHtg'
    when /OS:AirTerminal:SingleDuct:Uncontrolled/
      terminal = eq.to_AirTerminalSingleDuctUncontrolled.get
      box_name = nil
    else
      terminal = nil
      box_name = nil
    end
    return terminal, box_name
  end

  def reheat_coil_costing(terminal:, tz_centroids:, model:, tz:, roof_cent:, tz_mult:, mech_sizing_info:, air_m3_per_s:, box_name:)
    coil_mat = 'none'
    coil_cost = 0
    coil = terminal.reheatCoil
    case coil.iddObject.name
    when /Water/
      capacity = (model.getAutosizedValue(coil, 'Design Size Rated Capacity', 'W').to_f)/(1000.0*tz_mult)
      coil_mat = 'Coils'
    when /Electric/
      capacity = (model.getAutosizedValue(coil, 'Design Size Nominal Capacity', 'W').to_f)/(1000.0*tz_mult)
      coil_mat = 'ElecDuct'
    end
    return 0, {size_kw: 0.0, air_flow_m3_per_s: 0.0, pipe_dist_m: 0.0, elect_dist_m: 0.0, num_units: 0} if coil_mat == 'none'
    pipe_length_m = 0
    elect_length_m = 0
    num_coils = 0
    tz_centroids.sort.each do |tz_cent|
      story_floor_area = 0
      num_coils += 1
      tz_cent[:spaces].each { |space| story_floor_area += space.floorArea.to_f }
      floor_area_frac = (story_floor_area/tz.floorArea).round(2)
      floor_cap = floor_area_frac*capacity
      coil_cost += get_mech_costing(mech_name: coil_mat, size: floor_cap, terminal: terminal, mult: true)
      coil_cost += get_mech_costing(mech_name: box_name, size: floor_area_frac*(OpenStudio.convert(air_m3_per_s, 'm^3/s', 'cfm').get), terminal: terminal, mult: true)
      ut_dist = (tz_cent[:centroid][0].to_f - roof_cent[:roof_centroid][0].to_f).abs + (tz_cent[:centroid][1].to_f - roof_cent[:roof_centroid][1].to_f).abs
      if coil_mat == 'Coils'
        pipe_length_m += ut_dist
        coil_cost += piping_cost(pipe_dist_m: ut_dist, mech_sizing_info: mech_sizing_info, air_m3_per_s: air_m3_per_s)
      end
      elect_length_m += ut_dist
      coil_cost += vent_box_elec_cost(cond_dist_m: ut_dist)
    end
    box_info = {size_kw: capacity.round(3), air_flow_m3_per_s: air_m3_per_s.round(3), pipe_dist_m: pipe_length_m.round(1), elect_dist_m: elect_length_m.round(1), num_units: num_coils}
    return coil_cost, box_info
  end

  def vav_cost(terminal:, tz_centroids:, tz:, roof_cent:, mech_sizing_info:, air_flow_m3_per_s:, box_name:)
    cost = 0
    pipe_length_m = 0
    elect_length_m = 0
    num_coils = 0
    tz_centroids.sort.each do |tz_cent|
      num_coils += 1
      story_floor_area = 0
      tz_cent[:spaces].each { |space| story_floor_area += space.floorArea.to_f }
      floor_area_frac = (story_floor_area/tz.floorArea).round(2)
      cost += get_mech_costing(mech_name: box_name, size: floor_area_frac*(OpenStudio.convert(air_flow_m3_per_s, 'm^3/s', 'cfm').get), terminal: terminal, mult: true)
      ut_dist = (tz_cent[:centroid][0].to_f - roof_cent[:roof_centroid][0].to_f).abs + (tz_cent[:centroid][1].to_f - roof_cent[:roof_centroid][1].to_f).abs
      if /Htg/.match(box_name)
        pipe_length_m += ut_dist
        cost += piping_cost(pipe_dist_m: ut_dist, mech_sizing_info: mech_sizing_info, air_m3_per_s: floor_area_frac*air_flow_m3_per_s)
      end
      elect_length_m += ut_dist
      cost += vent_box_elec_cost(cond_dist_m: ut_dist)
    end
    box_info = {size_kw: 0.0, air_flow_m3_per_s: air_flow_m3_per_s.round(3), pipe_dist_m: pipe_length_m.round(1), elect_dist_m: elect_length_m.round(1), num_units: num_coils}
    return cost, box_info
  end

  def get_mech_costing(mech_name:, size:, terminal:, mult: false)
    mech_mult = 1.0
    cost_info = @costing_database['raw']['materials_hvac'].select {|data|
      data['Material'].to_s.upcase == mech_name.upcase and
          data['Size'].to_f.round(2) >= size.to_f.round(2)
    }.first
    if cost_info.nil?
      equip = {
          cat_search: mech_name,
          supply_comp: terminal,
          mech_capacity: size
      }
      cost_info, mech_mult = get_vent_system_mult(loop_equip: equip)
      mech_mult = 1.0 unless mult
    end
    return get_vent_mat_cost(mat_cost_info: cost_info)*mech_mult
  end

  def piping_cost(pipe_dist_m:, mech_sizing_info:, air_m3_per_s:, is_cool: false)
    pipe_dist = OpenStudio.convert(pipe_dist_m, 'm', 'ft').get
    air_flow = (OpenStudio.convert(air_m3_per_s, 'm^3/s', 'L/s').get)
    air_flow = 15000 if air_flow > 15000
    mech_table = get_mech_table(mech_size_info: mech_sizing_info, table_name: 'piping')
    pipe_sz_info = mech_table.select {|pipe_choice|
      pipe_choice['ahu_airflow_range_Literpers'][0].to_f.round(0) < air_flow.round(0) and
          pipe_choice['ahu_airflow_range_Literpers'][1].to_f.round(0) >= air_flow.round(0)
    }.first
    pipe_dia = pipe_sz_info['heat_valve_pipe_dia_inch'].to_f.round(2)
    pipe_dia = pipe_sz_info['cool_valve_pipe_dia_inch'].to_f.round(2) if is_cool == true
    pipe_cost_search = []
    pipe_cost_search << {
        mat: 'Steelpipe',
        unit: 'L.F.',
        size: pipe_dia,
        mult: 2*pipe_dist
    }
    pipe_cost_search << {
        mat: 'SteelPipeElbow',
        unit: 'none',
        size: pipe_dia,
        mult: 2
    }
    pipe_cost_search << {
        mat: 'SteelPipeTee',
        unit: 'none',
        size: pipe_dia,
        mult: 2
    }
    pipe_cost_search << {
        mat: 'SteelPipeTeeRed',
        unit: 'none',
        size: pipe_dia,
        mult: 2
    }
    pipe_cost_search << {
        mat: 'SteelPipeRed',
        unit: 'none',
        size: pipe_dia,
        mult: 2
    }
    pipe_dia > 3 ? pipe_dia_union = 3 : pipe_dia_union = pipe_dia
    pipe_cost_search << {
        mat: 'SteelPipeUnion',
        unit: 'none',
        size: pipe_dia_union,
        mult: 2
    }
    return get_comp_cost(cost_info: pipe_cost_search)
  end

  def vent_box_elec_cost(cond_dist_m:)
    cond_dist = OpenStudio.convert(cond_dist_m, 'm', 'ft').get
    elec_cost_search = []
    elec_cost_search << {
        mat: 'Wiring',
        unit: 'CLF',
        size: 14,
        mult: cond_dist/100
    }
    elec_cost_search << {
        mat: 'Conduit',
        unit: 'L.F.',
        size: 0,
        mult: cond_dist
    }
    elec_cost_search << {
        mat: 'Box',
        unit: 'none',
        size: 4,
        mult: 1
    }
    elec_cost_search << {
        mat: 'Box',
        unit: 'none',
        size: 1,
        mult: 1
    }
    return get_comp_cost(cost_info: elec_cost_search)
  end

  def get_comp_cost(cost_info:)
    cost = 0
    cost_info.each do |comp|
      comp_info = nil
      if comp[:unit].to_s == 'none'
        comp_info = @costing_database['raw']['materials_hvac'].select {|data|
          data['Material'].to_s.upcase == comp[:mat].to_s.upcase and
              data['Size'].to_f.round(2) == comp[:size].to_f.round(2)
        }.first
      elsif comp[:size].to_f == 0
        comp_info = @costing_database['raw']['materials_hvac'].select {|data|
          data['Material'].to_s.upcase == comp[:mat].to_s.upcase and
              data['unit'].to_s.upcase == comp[:unit].to_s.upcase
        }.first
      else
        comp_info = @costing_database['raw']['materials_hvac'].select {|data|
          data['Material'].to_s.upcase == comp[:mat].to_s.upcase and
              data['Size'].to_f.round(2) == comp[:size].to_f.round(2) and
              data['unit'].to_s.upcase == comp[:unit].to_s.upcase
        }.first
      end
      if comp_info.nil?
        puts("No data found for #{comp}!")
        raise
      end
      cost += get_vent_mat_cost(mat_cost_info: comp_info)*(comp[:mult].to_f)
    end
    return cost
  end

  def get_mech_table(mech_size_info:, table_name:)
    table = mech_size_info.select {|hash|
      hash['component'].to_s.upcase == table_name.to_s.upcase
    }.first
    return table['table']
  end

  # This method finds the centroid of the ceiling line on a given story furthest from the specified point.  It only
  # takes into account ceilings that above conditioned spaces that are not plenums.  A line can be defined between the
  # supplied point (we'll call it point O) and the ceiling line centroid furthest from that point(we'll call it point A).
  # We will call this line AO.  If the full_length input argument is set to true the method will also return the point
  # where line AO intercepts the ceiling line on the other side of the building.  Note that the method only looks at x
  # and y coordinates and ignores the z coordinate of the point you pass it.  The method assumes that the ceilings of
  # all of the spaces on the floor you pass it are flat so generally ignores their z components as well.  This was done
  # to avoid further complicating things with 3D geometry.  If the ceilings of all of the spaces in the building story
  # you pass the method are not flat it will still work but pretend as though the ceilings are flat by ignoring the z
  # coordinate.
  #
  # The method works by going through each space in the supplied building story and finding the ones which are
  # conditioned (either heated or cooled) and which are not considered plenums.  It then goes through the surfaces of
  # the conditioned spaces and finds the ones which have an OpenStudio SurfaceType of 'RoofCeiling'.  It then goes
  # through each point on that surface and makes lines going from the current point (CP) to the previous point (PP).  It
  # calculates the centroid (LC) of the line formed between PP and CP by averaging each coordinate of PP and CP.  It then
  # determines which LC is furthest from the supplied point (point O) and this becomes point A.  Note that point A is not
  # necessarily on the outside of a building since no checks are made on where line P lies in the building (only that it
  # is on a RoofCeiling above a conditioned space that is not a plenum).  For example in the LargeOffice building
  # archetype point P generally lies on one of the short edges of the trapezoids forming the perimeter spaces.  This is
  # if this reference point (O) is the center of the building.
  #
  # The inputs arguments are are:
  # building_story:  OpenStudio BuildingStory object.  A building story defined in OpenStudio.
  # prototype_creator:  The Openstudio-standards object, containing all of the methods etc. in the nrcan branch of
  #                     Openstudio-standards.
  # target_cent:  Array.  The point you supply from which you want to find the furthest ceiling line centroid (point O
  #               in the description above).  This point should be a one dimensional array containing at least two
  #               elements target_cent[0] = x, target_cent[1] = y.  The array can have more points but they will be
  #               ignored.  This point should be inside the building.
  # tol:  Float.  The tolerence used by the method when rounding geometry (default is 8 digits after decimal).
  # full_length:  Boolean true/false
  #               The switch which tells the method whether or not it should find, and supply, the point where line AO (
  #               as defined above) intercepts the other side of the building.  It is defaulted to false, meaning it
  #               will only return points A and O.  If it set to 'true' it will return the point where line AO
  #               intercepts the other side of the building.  It does this by going through all of the ceiling lines
  #               in the specified building story and determining if any intercept line AO (let us call each intercepts
  #               point C).  It then runs through each intercept (point C) and determines which C makes line AOC the
  #               longest.
  #
  # The output is the following hash.
  #
  # {
  #   start_point:  Hash.  A hash which defines point A and provides a bunch of other information (see below),
  #   mid_point:  Hash.  This is a hash containing the array defining the point you passed the method in the first
  #               place.,
  #   end_point:  Hash.  If full_length was set to true then this defines point C and provides a bunch of other
  #               information (see below).  If full_length was not set to false or undefined then this is set to nil.
  #
  # The structure of the hashes start_point and end_point are identical.  I will only define the hash start_point below
  # noting differences for end_point.
  #
  # start_point: {
  #   space:  OpenStudio Space object.  The space that contains point A (or point C if in the end_point hash).,
  #   surface:  OpenStudio Surface object.  The surface in space that contains point A (should have a RoofCeiling
  #             SpaceType).  In the case of the end_point hash this is the surface that contains point C.,
  #   verts:  Two dimmensional array.  The points defining ':surface'.  These points are in the building coordinate
  #           system (rather than the space coordinate system).  These points are ordered clockwise when viewed with the
  #           surface normal pointed towards the viewer.  The array would be structured as follows:
  #           [1st point, 2nd point, ..., last point].  Each point is an array as follows:  [x coord, y coord, z coord].
  #           The points are in meters.,
  #   line:  Hash.  A hash defining the line containing point A (point C if this is in the 'end_point' hash).  See
  #          definition below.
  # }
  #
  # 'line' has the identical structure in the start_point and end_point hashes.  I will define it once but note any
  # differences for when it is containing in the start_point and end_point hashes.
  #
  # line: {
  #   verta:  Array.  The end point of the line containing point A (when in the start_point hash) or point C (when in
  #           the end_point hash).  It is formed as [x, y, z].  It is in the building coordinate system, in meters.
  #   ventb:  Array.  The start point of the line containing point A (when in the start_point hash) or point C (when in
  #           the end_point hash).  It is formed as [x, y, z].  It is in the building coordinate system, in meters.
  #   int:  Array.  If this is in the start_point hash then this is the centre of the line from vertb to verta.  If this
  #         is in the end_point hash then this is the intercept of the line AO with the line starting with vertb and
  #         ending with verta.  It is formed as [x, y, z].  It is in the building coordinate system, in meters.  If in
  #         the start_point hash then the z coordinate is the average of the z coordinates of verta and vertb.  If in
  #         the end_point hash then the z coordinate is calculated by first determining of the distance of the line
  #         between vertb and verta when only using their x and y coordinates (we will call it the xy_dist).  Then the
  #         distance from just the x and y coordinates of ventb to the x and y coordinates (the only ones provided) of
  #         point C is determined (we will call it the c_dist).  The fraction c_dist/xy_dist is then found and added to
  #         the z coordinate of ventb thus providing the z coordinate of point C.
  #   i:    Integer.  The index of verta in the verts array.
  #   ip:   Integer.  The index of vertb in the verts array.
  #   dist:  If in the start_point hash this is the distance between point A and point O using only the x and y
  #          coordinates of the respective points.  If in the end_point hash this is the distance between point A and
  #          point C using only the x and y coordinates of the respective points.  In meters.
  # }
  #
  def get_story_cent_to_edge(building_story:, prototype_creator:, target_cent:, tol: 8, full_length: false)
    ceiling_start = []
    building_story.spaces.sort.each do |space|
      if (prototype_creator.space_cooled?(space) || prototype_creator.space_heated?(space)) and not prototype_creator.space_plenum?(space)
        origin = [space.xOrigin.to_f, space.yOrigin.to_f, space.zOrigin.to_f]
        space.surfaces.each do |surface|
          if surface.surfaceType.to_s.upcase == 'ROOFCEILING'
            verts = surface.vertices
            dists = []
            surf_verts = []
            for index in 1..verts.length
              index == verts.length ? i = 0 : i = index
              i == 0 ? ip = verts.length - 1 : ip = i - 1
              verta = [verts[i].x.to_f + origin[0], verts[i].y.to_f + origin[1], verts[i].z.to_f + origin[2]]
              vertb = [verts[ip].x.to_f + origin[0], verts[ip].y.to_f + origin[1], verts[ip].z.to_f + origin[2]]
              cent = [(verta[0] + vertb[0])/2.0 , (verta[1] + vertb[1])/2.0, (verta[2] + vertb[2])/2.0]
              dist = Math.sqrt((target_cent[0].to_f - cent[0])**2 + (target_cent[1].to_f - cent[1])**2)
              dists << {
                  verta: verta,
                  vertb: vertb,
                  int: cent,
                  i: i,
                  ip: ip,
                  dist: dist
              }
              surf_verts << vertb
            end
            max_dist = dists.max_by{|dist_el| dist_el[:dist].to_f}
            ceiling_start << {
                space: space,
                surface: surface,
                verts: surf_verts,
                line: max_dist
            }
          end
        end
      end
    end

    return nil if ceiling_start.empty?

    furthest_line = ceiling_start.max_by{|wall| wall[:line][:dist].to_f}

    return {start_point: furthest_line, mid_point: target_cent, end_point: nil} unless full_length

    x_dist_ref = (furthest_line[:line][:int][0].round(tol) - target_cent[0].round(tol))
    x_dist_ref == 1 if x_dist_ref == 0
    y_dist_ref = (furthest_line[:line][:int][1].round(tol) - target_cent[1].round(tol))
    y_dist_ref == 1 if y_dist_ref == 0
    x_side_ref = x_dist_ref/x_dist_ref.abs
    y_side_ref = y_dist_ref/y_dist_ref.abs
    linea_eq = get_line_eq(a: target_cent, b: furthest_line[:line][:int], tol: tol)
    ints = []
    ceiling_start.each do |side|
      verts = side[:verts]
      for index in 1..(verts.length)
        index == verts.length ? i = 0 : i = index
        i == 0 ? ip = verts.length-1 : ip = i - 1
        lineb = [verts[i], verts[ip]]
        int = line_int(line_seg: lineb, line: linea_eq, tol: tol)
        next if int.nil?
        x_dist = (int[0].round(tol) - target_cent[0].round(tol))
        x_dist = 1 if x_dist == 0
        y_dist = (int[1].round(tol) - target_cent[1].round(tol))
        y_dist = 1 if y_dist == 0
        x_side = x_dist/x_dist.abs
        y_side = y_dist/y_dist.abs
        next if x_side == x_side_ref && y_side == y_side_ref
        ceil_dist = Math.sqrt((furthest_line[:line][:int][0] - int[0])**2 + (furthest_line[:line][:int][1] - int[1])**2)
        int_dist = Math.sqrt((int[0] - verts[ip][0])**2 + (int[1] - verts[ip][1])**2)
        line_dist = Math.sqrt((verts[i][0] - verts[ip][0])**2 + (verts[i][1] - verts[ip][1])**2)
        z_coord = verts[ip][2] + ((verts[i][2] - verts[ip][2])*int_dist/line_dist)
        ints << {
            ceiling_info: side,
            line: lineb,
            int: [int[0], int[1], z_coord],
            i: i,
            ip: ip,
            dist: ceil_dist
        }
      end
    end

    return nil if ints.empty?
    end_wall = ints.max_by{|wall| wall[:dist].to_f}
    return {
        start_point: furthest_line,
        mid_point: target_cent,
        end_point: {
            space: end_wall[:ceiling_info][:space],
            surface: end_wall[:ceiling_info][:surface],
            verts: end_wall[:ceiling_info][:verts],
            line: {
                verta: end_wall[:line][0],
                vertb: end_wall[:line][1],
                int: end_wall[:int],
                i: end_wall[:i],
                ip: end_wall[:ip],
                dist: end_wall[:dist]
            },
        }
    }
  end

  def get_line_eq(a:, b:, tol: 8)
    if a[0].round(tol) == b[0].round(tol) and a[1].round(tol) == b[1].round(tol)
      return {
          slope: 0,
          int: 0,
          inf: true
      }
    elsif a[0].round(tol) == b[0].round(tol)
      return {
          slope: a[0].round(tol),
          int: 1,
          inf: true
      }
    else
      slope = (b[1].round(tol) - a[1].round(tol))/(b[0].round(tol) - a[0].round(tol))
      int = a[1].round(tol) - (slope*a[0].round(tol))
    end
    return {
        slope: slope,
        int: int,
        inf: false
    }
  end

  def line_int(line_seg:, line:, tol: 8)
    line[:inf] == true && line[:int] == 1 ? x_cross = line[:slope] : x_cross = nil
    if line_seg[0][0].round(tol) == line_seg[1][0].round(tol) && line_seg[0][1].round(tol) == line_seg[1][1].round(tol)
      if x_cross.nil?
        y_val = line[:slope]*line_seg[0][0] + line[:int]
        y_val.round(tol) == line_seg[0][1].round(tol) ? (return line_seg[0]) : (return nil)
      else
        x_cross.round(tol) == line_seg[0][0].round(tol) ? (return line_seg[0]) : (return nil)
      end
    elsif line_seg[0][0].round(tol) == line_seg[1][0]
      if x_cross.nil?
        y_val = line[:slope]*line_seg[0][0] + line[:int]
        if (line_seg[0][1].round(tol) >= y_val.round(tol) && y_val.round(tol) >= line_seg[1][1].round(tol)) ||
            (line_seg[0][1].round(tol) <= y_val.round(tol) && y_val.round(tol) <= line_seg[1][1].round(tol))
          return [line_seg[0][0] , y_val, line_seg[0][2]]
        else
          return nil
        end
      else
        if x_cross.round(tol) == line_seg[0][0]
          y_val = (line_seg[0][1] + line_seg[1][1])/2
          return [line_seg[0][0] , y_val, line_seg[0][2]]
        else
          return nil
        end
      end
    end
    lineb = get_line_eq(a: line_seg[0], b: line_seg[1], tol: tol)
    if lineb[:slope].round(tol) == 0 && line[:slope].round(tol) == 0
      if x_cross.nil?
        if lineb[:int].round(tol) == line[:int].round(tol)
          x_val = (line_seg[0][0] + line_seg[1][0])/2
          return [x_val, lineb[:slope], line_seg[0][2]]
        else
          return nil
        end
      else
        if (line_seg[0][0].round(tol) <= x_cross.round(tol) && x_cross.round(tol) <= line_seg[1][0].round(tol)) ||
            (line_seg[0][0].round(tol) >= x_cross.round(tol) && x_cross.round(tol) >= line_seg[1][0].round(tol))
          [x_cross, lineb[:slope]]
        else
          return nil
        end
      end
    end
    unless x_cross.nil?
      if (line_seg[0][0].round(tol) <= x_cross.round(tol) && x_cross.round(tol) <= line_seg[1][0].round(tol)) ||
          (line_seg[0][0].round(tol) >= x_cross.round(tol) && x_cross.round(tol) >= line_seg[1][0].round(tol))
        y_val = lineb[:slope]*x_cross + lineb[:int]
        return [x_cross , y_val, line_seg[0][2]]
      else
        return nil
      end
    end
    if lineb[:inf] == true && lineb[:int] == 1
      x_int = lineb[:slope]
      y_int = line[:slope].to_f*x_int + line[:int].to_f
    else
      x_int = (lineb[:int].to_f - line[:int].to_f)/(line[:slope].to_f - lineb[:slope].to_f)
      y_int = lineb[:slope].to_f*x_int + lineb[:int].to_f
    end
    if (line_seg[0][0].round(tol) <= x_int.round(tol) && x_int.round(tol) <= line_seg[1][0].round(tol)) ||
        (line_seg[0][0].round(tol) >= x_int.round(tol) && x_int.round(tol) >= line_seg[1][0].round(tol))
      if (line_seg[0][1].round(tol) >= y_int.round(tol) && y_int.round(tol) >= line_seg[1][1].round(tol)) ||
          (line_seg[0][1].round(tol) <= y_int.round(tol) && y_int.round(tol) <= line_seg[1][1].round(tol))
        return [x_int, y_int, line_seg[0][2]]
      end
    end
    return nil
  end

  def line_seg_int(linea:, lineb:, tol: 8)
    if linea[0][0].round(tol) == lineb[0][0].round(tol) && linea[0][1].round(tol) == lineb[0][1].round(tol) &&
    linea[1][0].round(tol) == lineb[1][0].round(tol) && linea[1][1].round(tol) == lineb[1][1].round(tol)
      return [(linea[0][0] + linea[1][0])/2 , (linea[0][1] + linea[1][1])/2]
    elsif linea[0][0].round(tol) == linea[1][0].round(tol) && linea[0][1].round(tol) == linea[1][1].round(tol)
      return linea[0]
    elsif lineb[0][0].round(tol) == lineb[1][0].round(tol) && lineb[0][1].round(tol) == lineb[1][1].round(tol)
      return lineb[0]
    end

    o1 = get_orient(p: linea[0], q: linea[1], r: lineb[0], tol: tol)
    o2 = get_orient(p: linea[0], q: linea[1], r: lineb[1], tol: tol)
    o3 = get_orient(p: lineb[0], q: lineb[1], r: linea[0], tol: tol)
    o4 = get_orient(p: lineb[0], q: lineb[1], r: linea[1], tol: tol)

    int_sect = 0
    int_sect = 1 if o1 != o2 && o3 != o4
    return lineb[0] if o1 == 0 && point_on_line(p: linea[0], q: lineb[0], r: linea[1], tol: tol)
    return lineb[1] if o2 == 0 && point_on_line(p: linea[0], q: lineb[1], r: linea[1], tol: tol)
    return linea[0] if o3 == 0 && point_on_line(p: lineb[0], q: linea[0], r: lineb[1], tol: tol)
    return linea[1] if o4 == 0 && point_on_line(p: lineb[0], q: linea[1], r: lineb[1], tol: tol)

    return nil if int_sect == 0

    eq_linea = get_line_eq(a: linea[0], b: linea[1], tol: tol)
    eq_lineb = get_line_eq(a: lineb[0], b: lineb[1], tol: tol)
    if eq_linea[:inf] == true && eq_linea[:slope].to_f == 1
      x_int = linea[0][0]
      y_int = eq_lineb[:slope].to_f*x_int + eq_lineb[:int].to_f
      return [x_int, y_int]
    elsif eq_lineb[:inf] == true && eq_lineb[:slope].to_f == 1
      x_int = lineb[0][0]
      y_int = eq_linea[:slope].to_f*x_int + eq_linea[:int].to_f
      return [x_int, y_int]
    else
      x_int = (eq_lineb[:int].to_f - eq_linea[:int].to_f) / (eq_linea[:slope].to_f - eq_lineb[:slope].to_f)
      y_int = eq_lineb[:slope].to_f*x_int + eq_lineb[:int].to_f
      return [x_int, y_int]
    end
  end

  def get_orient(p:, q:, r:, tol: 8)
    orient = (q[1].round(tol) - p[1].round(tol))*(r[0].round(tol) - q[0].round(tol)) - (q[0].round(tol) - p[0].round(tol))*(r[1].round(tol) - q[1].round(tol))
    return 0 if orient == 0
    orient > 0 ? (return 1) : (return 2)
  end

  def point_on_line(p:, q:, r:, tol: 8)
    q[0].round(tol) <= [p[0].round(tol), r[0].round(tol)].max ? crita = true : crita = false
    q[0].round(tol) >= [p[0].round(tol), r[0].round(tol)].min ? critb = true : critb = false
    q[1].round(tol) <= [p[1].round(tol), r[1].round(tol)].max ? critc = true : critc = false
    q[1].round(tol) >= [p[1].round(tol), r[1].round(tol)].min ? critd = true : critd = false
    return true if crita && critb && critc && critd
    return false
  end

  def get_lowest_space(spaces:)
    cents = []
    spaces.each do |space|
      test = space['space']
      origin = [space['space'].xOrigin.to_f, space['space'].yOrigin.to_f, space['space'].zOrigin.to_f]
      space['space'].surfaces.each do |surface|
        if surface.surfaceType.to_s.upcase == 'ROOFCEILING'
          cents <<{
              space: space['space'],
              roof_cent: [surface.centroid.x.to_f + origin[0], surface.centroid.y.to_f + origin[1], surface.centroid.z.to_f + origin[2]]
          }
        end
      end
    end
    min_space = cents.min_by{|cent| cent[:roof_cent][2]}
    return min_space
  end

  def vent_trunk_duct_cost(tot_air_m3pers:, min_space:, roof_cent:, mech_sizing_info:, sys_1_4:)
    sys_1_4 ? overall_mult = 1 : overall_mult = 2
    duct_cost_search = []
    mech_table = get_mech_table(mech_size_info: mech_sizing_info, table_name: 'trunk')
    max_trunk_line = mech_table.max_by {|entry| entry['max_flow_range_m3pers'][0]}
    tot_air_m3pers = max_trunk_line['max_flow_range_m3pers'][0].to_f.round(2) if tot_air_m3pers.round(2) > max_trunk_line['max_flow_range_m3pers'][1].to_f.round(2)
    trunk_sz_info = mech_table.select {|trunk_choice|
      trunk_choice['max_flow_range_m3pers'][0].to_f.round(2) < tot_air_m3pers.round(2) and
          trunk_choice['max_flow_range_m3pers'][1].to_f.round(2) >= tot_air_m3pers.round(2)
    }.first
    duct_dia = trunk_sz_info['duct_dia_inch']
    duct_length_m = (roof_cent[:roof_centroid][2].to_f - min_space[:roof_cent][2].to_f).abs
    duct_length = (OpenStudio.convert(duct_length_m, 'm', 'ft').get)
    duct_cost_search << {
        mat: 'Ductwork-S',
        unit: 'L.F.',
        size: duct_dia,
        mult: duct_length*overall_mult
    }
    duct_area = (duct_dia/12)*Math::PI*duct_length*overall_mult
    duct_cost_search << {
        mat: 'Ductinsulation',
        unit: 'ft2',
        size: 1.5,
        mult: duct_area
    }
    duct_cost = get_comp_cost(cost_info: duct_cost_search)
    trunk_duct_info = {
        DuctSize_in: duct_dia.round(1),
        DuctLength_m: duct_length_m.round(1),
        NumberRuns: overall_mult,
        DuctCost: duct_cost.round(2)
    }
    return duct_cost, trunk_duct_info
  end

  def gen_hvac_info_by_floor(hvac_floors:, model:, prototype_creator:, airloop:, sys_type:, hrv_info:)
    airloop.thermalZones.sort.each do |tz|
      tz.equipment.sort.each do |eq|
        tz_mult = tz.multiplier.to_f
        terminal, box_name = get_airloop_terminal_type(eq: eq)
        next if terminal.nil?
        tz_air = (model.getAutosizedValue(terminal, 'Design Size Maximum Air Flow Rate', 'm3/s').to_f)/(tz_mult)
        tz_cents = prototype_creator.thermal_zone_get_centroid_per_floor(tz)
        tz_cents.each do |tz_cent|
          story_floor_area = 0
          tz_outdoor_air_m3ps = 0
          tz_cent[:spaces].each do |space|
            # Note that space.floorArea gets the floor area for the space only and does not include a thermal zone multiplier.
            # Thus the outdoor air flow rate totaled here will be for only one thermal zone and will not include thermal zone multipliers.
            story_floor_area += space.floorArea.to_f
            outdoor_air_obj = space.designSpecificationOutdoorAir
            outdoor_air_obj.is_initialized ? outdoor_air_m3ps = (outdoor_air_obj.get.outdoorAirFlowperFloorArea)*(space.floorArea.to_f) : outdoor_air_m3ps = 0
            tz_outdoor_air_m3ps += outdoor_air_m3ps
          end
          story_obj = tz_cent[:spaces][0].buildingStory.get
          floor_area_frac = (story_floor_area/tz.floorArea).round(2)
          tz_floor_air = floor_area_frac*tz_air
          (sys_type == 1 || sys_type == 4) ? tz_floor_return = 0 : tz_floor_return = tz_floor_air
          tz_floor_system = {
              story_name: tz_cent[:story_name],
              story: story_obj,
              sys_name: airloop.nameString,
              sys_type: sys_type,
              sys_info: airloop,
              tz: tz,
              tz_mult: tz_mult,
              terminal: terminal,
              floor_area_frac: floor_area_frac,
              tz_floor_area: story_floor_area,
              tz_floor_supp_air_m3ps: tz_floor_air,
              tz_floor_ret_air_m3ps: tz_floor_return,
              tz_floor_outdoor_air_m3ps: tz_outdoor_air_m3ps,
              hrv_info: hrv_info,
              tz_cent: tz_cent
          }
          hvac_floors = add_floor_sys(hvac_floors: hvac_floors, tz_floor_sys: tz_floor_system)
        end
      end
    end
    return hvac_floors
  end

  def add_floor_sys(hvac_floors:, tz_floor_sys:)
    if hvac_floors.empty?
      hvac_floors << {
          story_name: tz_floor_sys[:story_name],
          story: tz_floor_sys[:story],
          supply_air_m3ps: tz_floor_sys[:tz_floor_supp_air_m3ps],
          return_air_m3ps: tz_floor_sys[:tz_floor_ret_air_m3ps],
          tz_mult: tz_floor_sys[:tz_mult],
          tz_num: 1,
          floor_tz: [tz_floor_sys]
      }
    else
      found_story = false
      hvac_floors.each do |hvac_floor|
        if hvac_floor[:story_name].to_s.upcase == tz_floor_sys[:story_name].to_s.upcase
          hvac_floor[:supply_air_m3ps] += tz_floor_sys[:tz_floor_supp_air_m3ps]
          hvac_floor[:return_air_m3ps] += tz_floor_sys[:tz_floor_ret_air_m3ps]
          hvac_floor[:tz_mult] += tz_floor_sys[:tz_mult]
          hvac_floor[:tz_num] += 1
          hvac_floor[:floor_tz] << tz_floor_sys
          found_story = true
        end
      end
      if found_story == false
        hvac_floors << {
            story_name: tz_floor_sys[:story_name],
            story: tz_floor_sys[:story],
            supply_air_m3ps: tz_floor_sys[:tz_floor_supp_air_m3ps],
            return_air_m3ps: tz_floor_sys[:tz_floor_ret_air_m3ps],
            tz_mult: tz_floor_sys[:tz_mult],
            tz_num: 1,
            floor_tz: [tz_floor_sys]
        }
      end
    end
    return hvac_floors
  end

  def floor_vent_dist_cost(hvac_floors:, prototype_creator:, roof_cent:, mech_sizing_info:)
    floor_duct_cost = 0
    build_floor_trunk_info = []
    mech_table = get_mech_table(mech_size_info: mech_sizing_info, table_name: 'vel_prof')
    hvac_floors.each do |hvac_floor|
      next if hvac_floor[:tz_num] < 2 && hvac_floor[:floor_tz][0][:sys_type] == 3
      tz_floor_mult = (hvac_floor[:tz_mult].to_f)/(hvac_floor[:tz_num].to_f)
      floor_trunk_line = get_story_cent_to_edge(building_story: hvac_floor[:story], prototype_creator: prototype_creator, target_cent: roof_cent[:roof_centroid], full_length: true)
      current_floor_duct_cost, floor_trunk_info = get_floor_trunk_cost(mech_table: mech_table, hvac_floor: hvac_floor, prototype_creator: prototype_creator, floor_trunk_dist_m: floor_trunk_line[:end_point][:line][:dist])
      floor_duct_cost += current_floor_duct_cost*tz_floor_mult
      floor_trunk_info[:Floor] = hvac_floor[:story_name]
      floor_trunk_info[:Multiplier] = tz_floor_mult
      build_floor_trunk_info << floor_trunk_info
    end
    return floor_duct_cost, build_floor_trunk_info
  end

  def get_floor_trunk_cost(mech_table:, hvac_floor:, prototype_creator:, floor_trunk_dist_m:, fric_allow: 1)
    floor_trunk_info = {
        Floor: '',
        Predominant_space_type: 0,
        SupplyDuctSize_in: 0,
        SupplyDuctLength_m: 0,
        ReturnDuctSize_in: 0,
        ReturnDuctLength_m: 0,
        TotalDuctCost: 0,
        Multiplier: 1
    }
    floor_trunk_cost = 0
    duct_comp_search = []
    floor_trunk_dist = (OpenStudio.convert(floor_trunk_dist_m, 'm', 'ft').get)
    space_type = get_predominant_floor_space_type_area(hvac_floor: hvac_floor, prototype_creator: prototype_creator)
    floor_trunk_info[:Predominant_space_type] = space_type[:space_type]
    loor_vel_fpm = nil
    mech_table.each do |vel_prof|
      spc_type_name = nil
      spc_type_name = vel_prof['space_types'].select {|spc_type|
        spc_type.to_s.upcase == space_type[:space_type].to_s.upcase
      }.first
      floor_vel_fpm = vel_prof['vel_fpm'].to_f unless spc_type_name.nil?
    end
    floor_vel_fpm = mech_table[mech_table.size - 1]['vel_fpm'].to_f if floor_vel_fpm.nil?
    supply_flow_cfm = (OpenStudio.convert(hvac_floor[:supply_air_m3ps], 'm^3/s', 'cfm').get)
    sup_cross_in2 = ((supply_flow_cfm*fric_allow)/floor_vel_fpm)*144
    sup_dia_in = 2*Math.sqrt(sup_cross_in2/Math::PI)
    duct_cost_search = {
        mat: 'Ductwork-S',
        unit: 'L.F.',
        size: sup_dia_in,
        mult: floor_trunk_dist
    }
    duct_cost, comp_info = get_duct_cost(cost_info: duct_cost_search)
    floor_trunk_info[:SupplyDuctSize_in] = sup_dia_in.round(2)
    floor_trunk_info[:SupplyDuctLength_m] = floor_trunk_dist_m.round(1)
    floor_trunk_cost += duct_cost
    sup_area_sqrft = (comp_info['Size'].to_f/12)*Math::PI*floor_trunk_dist
    duct_comp_search << {
        mat: 'Ductinsulation',
        unit: 'ft2',
        size: 1.5,
        mult: sup_area_sqrft
    }
    if hvac_floor[:return_air_m3ps] == hvac_floor[:supply_air_m3ps]
      floor_trunk_cost += duct_cost
      duct_comp_search[0][:mult] = sup_area_sqrft*2
      floor_trunk_info[:ReturnDuctSize_in] = floor_trunk_info[:SupplyDuctSize_in]
      floor_trunk_info[:ReturnDuctLength_m] = floor_trunk_info[:SupplyDuctLength_m]
    elsif hvac_floor[:return_air_m3ps].to_f > 0
      return_flow_cfm = (OpenStudio.convert(hvac_floor[:return_air_m3ps], 'm^3/s', 'cfm').get)
      ret_cross_in2 = ((return_flow_cfm*fric_allow)/floor_vel_fpm)*144
      ret_dia_in = 2*Math.sqrt(ret_cross_in2/Math::PI)
      duct_cost_search = {
          mat: 'Ductwork-S',
          unit: 'L.F.',
          size: ret_dia_in,
          mult: floor_trunk_dist
      }
      duct_cost, comp_info = get_duct_cost(cost_info: duct_cost_search)
      floor_trunk_cost += duct_cost
      ret_area_sqrft = (comp_info['Size'].to_f/12)*Math::PI*floor_trunk_dist
      duct_comp_search << {
          mat: 'Ductinsulation',
          unit: 'ft2',
          size: 1.5,
          mult: ret_area_sqrft
      }
      floor_trunk_info[:ReturnDuctSize_in] = ret_dia_in.round(2)
      floor_trunk_info[:ReturnDuctLength_m] = floor_trunk_dist_m.round(1)
    end
    floor_trunk_cost += get_comp_cost(cost_info: duct_comp_search)
    floor_trunk_info[:TotalDuctCost] = floor_trunk_cost.round(2)
    return floor_trunk_cost, floor_trunk_info
  end

  def get_duct_cost(cost_info:)
    comp_info = nil
    comp_info = @costing_database['raw']['materials_hvac'].select {|data|
      data['Material'].to_s.upcase == cost_info[:mat].to_s.upcase and
          data['Size'].to_f.round(1) >= cost_info[:size].to_f.round(1) and
          data['unit'].to_s.upcase == cost_info[:unit].to_s.upcase
    }.first
    if comp_info.nil?
      max_size_info = @costing_database['raw']['materials_hvac'].select {|data|
        data['Material'].to_s.upcase == cost_info[:mat].to_s.upcase
      }
      if max_size_info.nil?
        puts("No data found for #{cost_info}!")
        raise
      end
      comp_info = max_size_info.max_by {|element| element['Size'].to_f}
    end
    cost = get_vent_mat_cost(mat_cost_info: comp_info)*cost_info[:mult].to_f
    return cost, comp_info
  end

  def get_predominant_floor_space_type_area(hvac_floor:, prototype_creator:)
    spaces = hvac_floor[:story].spaces
    space_list = []
    spaces.sort.each do |space|
      if (prototype_creator.space_cooled?(space) || prototype_creator.space_heated?(space)) and not prototype_creator.space_plenum?(space)
        space_type = space.spaceType.get.nameString[15..-1]
        if space_list.empty?
          space_list << {
              space_type: space_type,
              floor_area: space.floorArea
          }
        else
          new_space = nil
          space_list.each do |spc_lst|
            if space_type.upcase == spc_lst[:space_type]
              spc_lst[:floor_area] += space.floorArea
            else
              new_space = {
                  space_type: space_type,
                  floor_area: space.floorArea
              }
            end
          end
          unless new_space.nil?
            space_list << new_space
          end
        end
      end
    end
    max_space_type = space_list.max_by {|spc_lst| spc_lst[:floor_area]}
    return max_space_type
  end

  def tz_vent_dist_cost(hvac_floors:, mech_sizing_info:)
    dist_reporting = []
    vent_dist_cost = 0
    mech_table = get_mech_table(mech_size_info: mech_sizing_info, table_name: 'tz_dist_info')
    flexduct_table = get_mech_table(mech_size_info: mech_sizing_info, table_name: 'flex_duct')
    hvac_floors.each_with_index do |hvac_floor, index|
      dist_reporting << {
          Story: hvac_floor[:story_name],
          thermal_zones: []
      }
      hvac_floor[:floor_tz].each do |floor_tz|
        airflow_m3ps = []
        airflow_m3ps << floor_tz[:tz_floor_supp_air_m3ps]*floor_tz[:floor_area_frac]
        airflow_m3ps << floor_tz[:tz_floor_ret_air_m3ps]*floor_tz[:floor_area_frac] if floor_tz[:tz_floor_ret_air_m3ps].to_f.round(6) > 0.0
        airflow_m3ps.each_with_index do |max_air_m3ps, flow_index|
          # Using max supply air flow rather than breathing zone outdoor airflow.  Keep breathing zone outdoor airflow in
          # case we change our minds.
          # breathing_zone_outdoor_airflow_vbz= model.sqlFile().get().execAndReturnFirstDouble("SELECT Value FROM TabularDataWithStrings WHERE ReportName='Standard62.1Summary' AND ReportForString='Entire Facility' AND TableName='Zone Ventilation Parameters' AND ColumnName='Breathing Zone Outdoor Airflow - Vbz' AND Units='m3/s' AND RowName='#{tz.nameString.to_s.upcase}' ")
          # bz_outdoor_airflow_m3_s = breathing_zone_outdoor_airflow_vbz.get unless breathing_zone_outdoor_airflow_vbz.empty?
          tz_dist_sz = mech_table.select {|size_range|
            max_air_m3ps > size_range['airflow_m3ps'][0] && max_air_m3ps <= size_range['airflow_m3ps'][1]
          }
          if tz_dist_sz.empty?
            size_range = mech_table[mech_table.size - 1]
            diffusers = (max_air_m3ps/size_range["diffusers"]).round(0)
            tz_dist_sz << {
                "airflow_m3ps" => size_range['airflow_m3ps'],
                "diffusers" => diffusers,
                "ducting_lbs" => (diffusers*size_range["ducting_lbs"]).round(0),
                "duct_insulation_ft2" => (diffusers*size_range["duct_insulation_ft2"]).round(0),
                "flex_duct_ft" => (diffusers*size_range["flex_duct_ft"]).round(0)
            }
          elsif tz_dist_sz[0] == mech_table[mech_table.size - 1]
            diffusers = (max_air_m3ps/tz_dist_sz[0]['diffusers']).round(0)
            tz_dist_sz[0] = {
                "airflow_m3ps" => tz_dist_sz[0]['airflow_m3ps'],
                "diffusers" => diffusers,
                "ducting_lbs" => (diffusers*tz_dist_sz[0]['ducting_lbs']).round(0),
                "duct_insulation_ft2" => (diffusers*tz_dist_sz[0]['duct_insulation_ft2']).round(0),
                "flex_duct_ft" => (diffusers*tz_dist_sz[0]['flex_duct_ft']).round(0)
            }
          end
          duct_cost_search = []
          duct_cost_search << {
              mat: 'Diffusers',
              unit: 'each',
              size: 36,
              mult: tz_dist_sz[0]['diffusers']
          }
          if tz_dist_sz[0]["ducting_lbs"] < 200
            duct_cost_search << {
                mat: 'Ductwork',
                unit: 'lb.',
                size: 199,
                mult: tz_dist_sz[0]['ducting_lbs']
            }
          else
            duct_cost_search << {
                mat: 'Ductwork',
                unit: 'lb.',
                size: 200,
                mult: tz_dist_sz[0]['ducting_lbs']
            }
          end
          duct_cost_search << {
              mat: 'DuctInsulation',
              unit: 'ft2',
              size: 1.5,
              mult: tz_dist_sz[0]['duct_insulation_ft2']
          }
          vent_dist_cost += get_comp_cost(cost_info: duct_cost_search)*floor_tz[:tz_mult]
          flex_duct_sz = flexduct_table.select {|flex_duct|
            max_air_m3ps > flex_duct['airflow_m3ps'][0] && max_air_m3ps <= flex_duct['airflow_m3ps'][1]
          }
          flex_duct_sz << flexduct_table[flexduct_table.size-1] if flex_duct_sz.empty?
          duct_cost_search = {
              mat: 'Ductwork-M',
              unit: 'L.F.',
              size: flex_duct_sz[0]['diameter_in'],
              mult: tz_dist_sz[0]['flex_duct_ft']
          }
          duct_cost, comp_info = get_duct_cost(cost_info: duct_cost_search)
          vent_dist_cost += duct_cost*floor_tz[:tz_mult]
          if flow_index == 0
            flow_dir = 'Supply'
          else
            flow_dir = 'Return'
          end
          dist_reporting[index][:thermal_zones] << {
              ThermalZone: floor_tz[:tz].nameString,
              ducting_direction: flow_dir,
              tz_mult: floor_tz[:tz_mult],
              airflow_m3ps: max_air_m3ps.round(3),
              num_diff: tz_dist_sz[0]['diffusers'],
              ducting_lbs: tz_dist_sz[0]['ducting_lbs'],
              duct_insulation_ft2: tz_dist_sz[0]['duct_insulation_ft2'],
              cost: duct_cost.round(2)
          }
        end
      end
    end
    return vent_dist_cost, dist_reporting
  end

  def get_hrv_info(airloop:, model:)
    hrv_present = false
    hrv_data = nil
    hrv_design_flow_m3ps = 0
    airloop.oaComponents.each do |oaComp|
      if oaComp.iddObjectType.valueName.to_s == 'OS_HeatExchanger_AirToAir_SensibleAndLatent'
        hrv_present = true
        hrv_data = oaComp.to_HeatExchangerAirToAirSensibleAndLatent.get
        hrv_design_flow_m3ps = model.getAutosizedValue(hrv_data, 'Design Size Nominal Supply Air Flow Rate', 'm3/s').to_f
      end
    end
    return {hrv_present: hrv_present, hrv_data: hrv_data, hrv_size_m3ps: hrv_design_flow_m3ps, supply_cap_m3ps: 0, return_cap_m3ps: 0} unless hrv_present
    airloop.supplyFan.is_initialized ? supply_fan_cap = get_fan_cap(fan: airloop.supplyFan.get, model: model) : supply_fan_cap = 0
    airloop.returnFan.is_initialized ? return_fan_cap = get_fan_cap(fan: airloop.returnFan.get, model: model) : return_fan_cap = 0
    return {hrv_present: hrv_present, hrv_data: hrv_data, hrv_size_m3ps: hrv_design_flow_m3ps, supply_cap_m3ps: supply_fan_cap, return_cap_m3ps: return_fan_cap}
  end

  def get_fan_cap(fan:, model:)
    fan_type = fan.iddObjectType.valueName.to_s
    case fan_type
    when /OS_Fan_VariableVolume/
      fan_cap_m3ps = model.getAutosizedValue(fan, 'Design Size Maximum Flow Rate', 'm3/s').to_f
    when /OS_Fan_ConstantVolume/
      fan_cap_m3ps = model.getAutosizedValue(fan, 'Design Size Maximum Flow Rate', 'm3/s').to_f
    else
      fan_cap_m3ps = 0
    end
    return fan_cap_m3ps
  end

  def hrv_duct_cost(prototype_creator:, roof_cent:, mech_sizing_info:, hvac_floors:)
    hrv_cost_tot = 0
    mech_table = get_mech_table(mech_size_info: mech_sizing_info, table_name: 'trunk')
    air_system_totals = []
    hrv_dist_rep = []
    hvac_floors.each_with_index do |hvac_floor, floor_index|
      hrv_dist_rep << {
          floor: hvac_floor[:story_name],
          air_systems: []
      }
      floor_systems = sort_tzs_by_air_system(hvac_floor: hvac_floor)
      floor_systems.each_with_index do |air_system, air_index|
        next if air_system[:sys_hrv_flow_m3ps].round(2) == 0.0 || air_system[:hrv_info][:hrv_present] == false
        floor_trunk_line = nil
        floor_air_sys = {
            air_system: air_system[:air_sys].nameString,
            hrv: air_system[:hrv_info][:hrv_data].nameString,
            floor_mult: 1,
            hrv_ret_trunk: {},
            tz_dist: [],
        }
        if air_system[:num_tz] > 1
          sys_floor_mult = air_system[:tz_mult]/(air_system[:num_tz])
          floor_trunk_line = get_story_cent_to_edge(building_story: hvac_floor[:story], prototype_creator: prototype_creator, target_cent: roof_cent[:roof_centroid], full_length: true)
          hrv_trunk_cost, floor_air_sys[:hrv_ret_trunk] = get_hrv_floor_trunk_cost(mech_table: mech_table, air_system: air_system, floor_trunk_dist_m: floor_trunk_line[:end_point][:line][:dist])
          hrv_cost_tot += hrv_trunk_cost*sys_floor_mult
          floor_air_sys[:floor_mult] = sys_floor_mult
        end
        air_system[:floor_tz].each do |floor_tz|
          floor_tz[:tz_floor_ret_air_m3ps] >= floor_tz[:tz_floor_outdoor_air_m3ps] ? hrv_air = 0 : hrv_air = (floor_tz[:tz_floor_outdoor_air_m3ps] - floor_tz[:tz_floor_ret_air_m3ps]).abs
          next if hrv_air.round(2) == 0.0
          air_system_total = {
              dist_to_roof_m: (roof_cent[:roof_centroid][2] - floor_tz[:tz_cent][:centroid][2]).abs,
              hrv_air_m3ps: hrv_air*floor_tz[:tz_mult],
              num_systems: floor_tz[:tz_mult]
          }
          if floor_trunk_line.nil?
            floor_duct_coords = [roof_cent[:roof_centroid][0] - floor_tz[:tz_cent][:centroid][0], roof_cent[:roof_centroid][1] - floor_tz[:tz_cent][:centroid][1], roof_cent[:roof_centroid][2] - floor_tz[:tz_cent][:centroid][2]]
            floor_duct_dist_m = floor_duct_coords[0].abs + floor_duct_coords[1].abs
          else
            line = {
                start: floor_trunk_line[:start_point][:line][:int],
                end: floor_trunk_line[:end_point][:line][:int]
            }
            floor_duct_dist_m = short_dist_point_and_line(point: floor_tz[:tz_cent][:centroid], line: line).abs
            if floor_duct_dist_m.nil?
              floor_duct_dist_m = (line[:start][0] - floor_tz[:tz_cent][:centroid][0]).abs + (line[:start][1] - floor_tz[:tz_cent][:centroid][1]).abs
            end
          end
          if floor_duct_dist_m.round(2) > 0.1
            floor_duct_dist_ft = (OpenStudio.convert(floor_duct_dist_m, 'm', 'ft').get)
            branch_duct_sz = mech_table.select {|sz_range|
              hrv_air > sz_range['max_flow_range_m3pers'][0] && hrv_air <= sz_range['max_flow_range_m3pers'][1]
            }
            branch_duct_sz << mech_table[mech_table.size-1] if branch_duct_sz.empty?
            duct_comp_search = []
            duct_dia_in = branch_duct_sz[0]['duct_dia_inch']
            duct_surface_area = floor_duct_dist_ft*(duct_dia_in.to_f/12)*Math::PI
            duct_comp_search << {
                mat: 'Ductinsulation',
                unit: 'ft2',
                size: 1.5,
                mult: duct_surface_area
            }
            duct_comp_search << {
                mat: 'Ductwork-S',
                unit: 'L.F.',
                size: duct_dia_in,
                mult: floor_duct_dist_ft
            }
            hrv_branch_cost = get_comp_cost(cost_info: duct_comp_search)
            hrv_cost_tot += hrv_branch_cost*floor_tz[:tz_mult]
            floor_air_sys[:tz_dist] << {
                tz: floor_tz[:tz].nameString,
                tz_mult: floor_tz[:tz_mult],
                hrv_ret_dist_m: floor_duct_dist_m.round(1),
                hrv_ret_size_in: duct_dia_in.round(2),
                cost: hrv_branch_cost.round(2)
            }
          end
          air_system_totals = add_tz_to_air_sys(air_system: air_system, air_system_total: air_system_total, air_system_totals: air_system_totals, floor_tz: floor_tz)
        end
        hrv_dist_rep[floor_index][:air_systems] << floor_air_sys
      end
    end
    unless air_system_totals.empty?
      air_system_totals.each do |air_system|
        next if air_system[:hrv_air_m3ps].round(2) == 0
        # In addition to distance from floor to roof add 20' of duct from roof centre to box
        main_trunk_dist_ft = (OpenStudio.convert(air_system[:dist_to_roof_m], 'm', 'ft').get) + 20
        main_trunk_sz = mech_table.select {|sz_range|
          air_system[:hrv_air_m3ps] > sz_range['max_flow_range_m3pers'][0] && air_system[:hrv_air_m3ps] <= sz_range['max_flow_range_m3pers'][1]
        }
        main_trunk_sz << mech_table[mech_table.size-1] if main_trunk_sz.empty?
        duct_comp_search = []
        duct_dia_in = main_trunk_sz[0]['duct_dia_inch']
        duct_surf_area_ft2 = main_trunk_dist_ft*(duct_dia_in.to_f/12)*Math::PI
        duct_comp_search << {
            mat: 'Ductinsulation',
            unit: 'ft2',
            size: 1.5,
            mult: duct_surf_area_ft2
        }
        duct_comp_search << {
            mat: 'Ductwork-S',
            unit: 'L.F.',
            size: duct_dia_in,
            mult: main_trunk_dist_ft
        }
        main_trunk_cost = get_comp_cost(cost_info: duct_comp_search)
        hrv_cost_tot += main_trunk_cost
        hrv_dist_rep << {
            air_system: air_system[:air_system].nameString,
            hrv: air_system[:hrv_info][:hrv_data].nameString,
            hrv_building_trunk_length_m: air_system[:dist_to_roof_m].round(1),
            hrv_building_trunk_dia_in: duct_dia_in.round(2),
            cost: main_trunk_cost.round(2)
        }
      end
    end
    return hrv_cost_tot, hrv_dist_rep
  end

  def sort_tzs_by_air_system(hvac_floor:)
    floor_systems = []
    hvac_floor[:floor_tz].each do |floor_tz|
      air_sys = floor_tz[:sys_info]
      next if floor_tz[:hrv_info][:hrv_present] == false
      floor_tz[:tz_floor_ret_air_m3ps] >= floor_tz[:tz_floor_outdoor_air_m3ps] ? hrv_ret_air_m3ps = 0 : hrv_ret_air_m3ps = (floor_tz[:tz_floor_outdoor_air_m3ps] - floor_tz[:tz_floor_ret_air_m3ps]).abs
      if floor_systems.empty?
        floor_systems << {
            air_sys: air_sys,
            sys_hrv_flow_m3ps: hrv_ret_air_m3ps,
            num_tz: 1,
            tz_mult: floor_tz[:tz_mult],
            hrv_info: floor_tz[:hrv_info],
            floor_tz: [floor_tz]
        }
      else
        current_sys = floor_systems.select {|floor_sys| floor_sys[:air_sys] == air_sys}
        if current_sys.empty?
          floor_systems << {
              air_sys: air_sys,
              sys_hrv_flow_m3ps: hrv_ret_air_m3ps,
              num_tz: 1,
              tz_mult: floor_tz[:tz_mult],
              hrv_info: floor_tz[:hrv_info],
              floor_tz: [floor_tz]
          }
        else
          current_sys[0][:sys_hrv_flow_m3ps] += hrv_ret_air_m3ps
          current_sys[0][:num_tz] += 1
          current_sys[0][:tz_mult] += floor_tz[:tz_mult]
          current_sys[0][:floor_tz] << floor_tz
        end
      end
    end
    return floor_systems
  end

  def add_tz_to_air_sys(air_system:, air_system_total:, air_system_totals:, floor_tz:)
    if air_system_totals.empty?
      air_system_totals << {
          air_system: air_system[:air_sys],
          hrv_air_m3ps: air_system_total[:hrv_air_m3ps],
          dist_to_roof_m: air_system_total[:dist_to_roof_m],
          num_systems: air_system_total[:num_systems],
          hrv_info: air_system[:hrv_info],
          floor_tz: [floor_tz]
      }
    else
      curr_air_sys = air_system_totals.select {|air_sys| air_sys[:air_system] == air_system[:air_sys]}
      if curr_air_sys.empty?
        air_system_totals << {
            air_system: air_system[:air_sys],
            hrv_air_m3ps: air_system_total[:hrv_air_m3ps],
            dist_to_roof_m: air_system_total[:dist_to_roof_m],
            num_systems: air_system_total[:num_systems],
            hrv_info: air_system[:hrv_info],
            floor_tz: [floor_tz]
        }
      else
        curr_air_sys[0][:hrv_air_m3ps] += air_system_total[:hrv_air_m3ps]
        curr_air_sys[0][:dist_to_roof_m] = [curr_air_sys[0][:dist_to_roof_m], air_system_total[:dist_to_roof_m]].max
        curr_air_sys[0][:num_systems] += air_system_total[:num_systems]
        curr_air_sys[0][:floor_tz] << floor_tz
      end
    end
    return air_system_totals
  end

  def get_hrv_floor_trunk_cost(mech_table:, air_system:, floor_trunk_dist_m:)
    return 0 if air_system[:sys_hrv_flow_m3ps].round(2) == 0.0
    hrv_trunk_cost = 0
    duct_comp_search = []
    floor_trunk_dist = (OpenStudio.convert(floor_trunk_dist_m, 'm', 'ft').get)
    trunk_duct_sz = mech_table.select {|sz_range|
      air_system[:sys_hrv_flow_m3ps] > sz_range['max_flow_range_m3pers'][0] && air_system[:sys_hrv_flow_m3ps] <= sz_range['max_flow_range_m3pers'][1]
    }
    trunk_duct_sz << mech_table[mech_table.size-1] if trunk_duct_sz.empty?
    trunk_dia_in = (trunk_duct_sz[0]['duct_dia_inch'])
    duct_comp_search << {
        mat: 'Ductwork-S',
        unit: 'L.F.',
        size: trunk_dia_in,
        mult: floor_trunk_dist
    }
    trunk_area_sqrft = (trunk_dia_in.to_f/12)*Math::PI*floor_trunk_dist
    duct_comp_search << {
        mat: 'Ductinsulation',
        unit: 'ft2',
        size: 1.5,
        mult: trunk_area_sqrft
    }
    hrv_trunk_cost += get_comp_cost(cost_info: duct_comp_search)
    hrv_trunk_cost_rep = {
        duct_length_m: floor_trunk_dist_m.round(1),
        dia_in: trunk_dia_in.round(2),
        cost: hrv_trunk_cost.round(2)
    }
    return hrv_trunk_cost, hrv_trunk_cost_rep
  end

  def short_dist_point_and_line(point:, line:)
    line_eq = get_line_eq(a: line[:start], b: line[:end])
    if line_eq[:int] == 1 and line_eq[:inf] == true
      dist = point[0] - line_eq[:slope]
    elsif line_eq[:int] == 0 and line_eq[:inf] == true
      dist = nil
    else
      # Turn equation of line as:  y = slope*x + intercept
      # into:  a*x + b*y + c = 0
      # a = slope, b = -1, c = intercept
      a = line_eq[:slope]
      b = -1
      c = line_eq[:int]
      # Use dot product to get shortest distance from point to line
      dist = (a*point[0] + b*point[1] + c) / Math.sqrt(a**2 + b**2)
    end
    return dist
  end

  def hrv_cost(hrv_info:, airloop:)
    hrv_cost_tot = 0
    number_zones = 0
    duct_comp_search = []
    airloop.thermalZones.each do |tz|
      number_zones += tz.multiplier
    end
    duct_comp_search << {
        mat: 'Ductwork-Fitting',
        unit: 'each',
        size: 8,
        mult: number_zones
    }
    hrv_cost_tot += get_comp_cost(cost_info: duct_comp_search)
    hrv_size_cfm = (OpenStudio.convert(hrv_info[:hrv_size_m3ps], 'm^3/s', 'cfm').get)
    hrv_cost_tot += get_mech_costing(mech_name: 'ERV', size: hrv_size_cfm, terminal: hrv_info[:hrv_data])
    hrv_info[:return_cap_m3ps] >= hrv_info[:hrv_size_m3ps] ? hrv_return_flow_m3ps = 0.0 : hrv_return_flow_m3ps = hrv_info[:hrv_size_m3ps] - hrv_info[:return_cap_m3ps]
    unless hrv_return_flow_m3ps.round(2) == 0
      hrv_return_flow_cfm = (OpenStudio.convert(hrv_return_flow_m3ps, 'm^3/s', 'cfm').get)
      if hrv_return_flow_cfm < 800
        hrv_cost_tot += get_mech_costing(mech_name: 'FansDD-LP', size: hrv_return_flow_cfm, terminal: hrv_info[:hrv_data])
      else
        hrv_cost_tot += get_mech_costing(mech_name: 'FansBelt', size: hrv_return_flow_cfm, terminal: hrv_info[:hrv_data])
      end
    end
    return hrv_cost_tot
  end

  def add_heat_cool_to_report(equipment_info:, heat_cool_cost:, obj_type:, al_eq_reporting_info:)
    if al_eq_reporting_info.empty?
      al_eq_reporting_info << {
          eq_category: obj_type[3..-1],
          heating_fuel: equipment_info[:heating_fuel],
          cooling_type: equipment_info[:cooling_type],
          capacity_kw: equipment_info[:mech_capacity_kw].round(3),
          cost: heat_cool_cost.round(2)
      }
    else
      ahu_heat_cool = al_eq_reporting_info.select {|aloop|
        aloop[:eq_category] == obj_type[3..-1]
      }
      if ahu_heat_cool.empty?
        al_eq_reporting_info << {
            eq_category: obj_type[3..-1],
            heating_fuel: equipment_info[:heating_fuel],
            cooling_type: equipment_info[:cooling_type],
            capacity_kw: equipment_info[:mech_capacity_kw].round(3),
            cost: heat_cool_cost.round(2)
        }
      else
        ahu_heat_cool[0][:capacity_kw] += equipment_info[:capacity_kw].round(3)
        ahu_heat_cool[0][:cost] += heat_cool_cost.round(2)
      end
    end
  end
end