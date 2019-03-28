module HVACRoutines

  # =============================================================================================================================
  def create_curve_biquadratic(model,coeffs)
    curve = OpenStudio::Model::CurveBiquadratic.new(model)
    curve.setCoefficient1Constant(coeffs[0].to_f)
    curve.setCoefficient2x(coeffs[1].to_f)
    curve.setCoefficient3xPOW2(coeffs[2].to_f)
    curve.setCoefficient4y(coeffs[3].to_f)
    curve.setCoefficient5yPOW2(coeffs[4].to_f)
    curve.setCoefficient6xTIMESY(coeffs[5].to_f)
    curve.setMinimumValueofx(coeffs[6].to_f)
    curve.setMaximumValueofx(coeffs[7].to_f)
    curve.setMinimumValueofy(coeffs[8].to_f)
    curve.setMaximumValueofy(coeffs[9].to_f)
    if coeffs.size == 12
      curve.setMinimumCurveOutput(coeffs[10])
      curve.setMaximumCurveOutput(coeffs[11])
    end
    return curve
  end

  # =============================================================================================================================
  def create_curve_cubic(model,coeffs)
    curve = OpenStudio::Model::CurveCubic.new(model)
    curve.setCoefficient1Constant(coeffs[0].to_f)
    curve.setCoefficient2x(coeffs[1].to_f)
    curve.setCoefficient3xPOW2(coeffs[2].to_f)
    curve.setCoefficient4xPOW3(coeffs[3].to_f)
    curve.setMinimumValueofx(coeffs[4].to_f)
    curve.setMaximumValueofx(coeffs[5].to_f)
    return curve
  end

  # =============================================================================================================================
  def create_curve_quadratic(model,coeffs)
    curve = OpenStudio::Model::CurveQuadratic.new(model)
    curve.setCoefficient1Constant(coeffs[0].to_f)
    curve.setCoefficient2x(coeffs[1].to_f)
    curve.setCoefficient3xPOW2(coeffs[2].to_f)
    curve.setMinimumValueofx(coeffs[3].to_f)
    curve.setMaximumValueofx(coeffs[4].to_f)
    return curve
  end

  # =============================================================================================================================
  def create_curve_multivariablelookuptable(model,info)
  # create a look up table
  # input 'info' is a 1-D array with all relevant information about the table.
  # info[0]: number of independent variables
  # info[1]: interpolation method
  # info[2]: number of interpolation points
  # info[3]: curve type represented by table
  # info[4]: normalization reference
  # info[5]: output unit type
  # info[6]-info.last: data for all points (x1,x2,x3,...,y) in the table. The end of the info array holds minimum and maximum 
  # information for each of the independent variables x1,x2,x3 ...   
    table = OpenStudio::Model::TableMultiVariableLookup.new(model,info[0].to_i)
    table.setInterpolationMethod(info[1])
    table.setNumberofInterpolationPoints(info[2].to_i)
    table.setCurveType(info[3])
    table.setTableDataFormat('SingleLineIndependentVariableWithMatrix')
    table.setNormalizationReference(info[4].to_f)
    table.setOutputUnitType(info[5])
    start_index_for_min_max_info = info.size-2*info[0].to_i
    table.setMinimumValueofX1(info[start_index_for_min_max_info].to_f)
    table.setMaximumValueofX1(info[start_index_for_min_max_info+1].to_f)
    number_points_data = (info.size-6-2*info[0].to_i)/2
    for index in 0..number_points_data-1
      if info[0].to_i == 1
        table.addPoint(info[6+2*index].to_f,info[6+2*index+1].to_f)
      end
    end
    return table
  end

  # =============================================================================================================================
  def get_curve(model,curve_name)
  # search curves data file and return curve object
  # The keys of the hash for the curve which start with 'data' are stored in a 1-D array that can be used to generate the curve
  # object. The value for the key 'form' is used to call the appropriate method to generate the curve.
  # make copy of curves data from json file
    curves_file = "#{File.dirname(__FILE__)}/curves.json"
    curves_data = JSON.parse(File.read(curves_file))
    curve_info = []
    form = nil
    curves_data['curves'].each do |curve_data|
      if curve_data['name'] == curve_name 
        form = curve_data['form']
        curve_data.each do |key,record|
          if key.to_s.split('_')[0] == 'data'
            record.to_s.split(',').each do |value|
              curve_info << value
            end
          end
        end
        break
      end
    end
    case form
    when 'Biquadratic'
      curve = create_curve_biquadratic(model,curve_info)
    when 'Quadratic'
      curve = create_curve_quadratic(model,curve_info)
    when 'MultiVariableLookupTable'
      curve = create_curve_multivariablelookuptable(model,curve_info)
    end
    return curve
  end
  
  # =============================================================================================================================
  def coilcoolingdxvariablespeedspeeddatavrf_get_performance_curves(model)
  # return performance curves for variable speed cooling dx coil
    # cooling capacity vs temperature curve
    curve_name = 'OpenStudio AirConditionerVariableRefrigerantFlow CCAPFT curve'
    ccapft_curve = get_curve(model,curve_name)
    ccapft_curve.setName(curve_name)
    # cooling capacity vs flow fraction curve
    curve_name = 'OpenStudio AirConditionerVariableRefrigerantFlow CCAPFFF curve'
    ccapfff_curve = get_curve(model,curve_name)
    ccapfff_curve.setName(curve_name)
    # cooling eir vs temperature curve
    curve_name = 'OpenStudio AirConditionerVariableRefrigerantFlow CEIRFT curve'
    ceirft_curve = get_curve(model,curve_name)
    ceirft_curve.setName(curve_name)
    # cooling eir vs flow fraction curve
    curve_name = 'OpenStudio AirConditionerVariableRefrigerantFlow CEIRFFF curve'
    ceirfff_curve = get_curve(model,curve_name)
    ceirfff_curve.setName(curve_name)
    return ccapft_curve,ccapfff_curve,ceirft_curve,ceirfff_curve
  end

  # =============================================================================================================================
  def coilcoolingdxvariablespeedvrf_set_performance_curves(model,coil)
  # return part-load fraction vs part-load ration curve for variable speed cooling coil
  # cooling plf vs plr curve
    curve_name = "OpenStudio AirConditionerVariableRefrigerantFlow CPLFFPLRLow_CPLFFPLR curve"
    cplffplr_curve = get_curve(model,curve_name)
    cplffplr_curve.setName(curve_name)
    coil.setEnergyPartLoadFractionCurve(cplffplr_curve)
    return coil
  end

  # =============================================================================================================================
  def coilheatingdxvariablespeedspeeddatavrf_get_performance_curves(model)
  # return performance curves for variable speed heating dx coil
    # heating capacity vs temperature curve
    curve_name = 'OpenStudio AirConditionerVariableRefrigerantFlow HCAPFT curve'
    hcapft_curve = get_curve(model,curve_name)
    hcapft_curve.setName(curve_name)
    # heating capacity vs flow fraction curve
    curve_name = 'OpenStudio AirConditionerVariableRefrigerantFlow HCAPFFF curve'
   hcapfff_curve = get_curve(model,curve_name)
    hcapfff_curve.setName(curve_name)
    # heating eir vs temperature curve
    curve_name = 'OpenStudio AirConditionerVariableRefrigerantFlow HEIRFT curve'
    heirft_curve = get_curve(model,curve_name)
    heirft_curve.setName(curve_name)
    # heating eir vs flow fraction curve
    curve_name = 'OpenStudio AirConditionerVariableRefrigerantFlow HEIRFFF curve'
    heirfff_curve = get_curve(model,curve_name)
    heirfff_curve.setName(curve_name)
    return hcapft_curve,hcapfff_curve,heirft_curve,heirfff_curve
  end

  # =============================================================================================================================
  def coilheatingdxvariablespeedvrf_set_performance_curves(model,coil)
  # return part-load fraction vs part-load ration curve for variable speed heating coil
    # heating part-load fraction ratio vs part-load ratio curve
    curve_name = "OpenStudio AirConditionerVariableRefrigerantFlow HPLFFPLRLow_HPLFFPLR curve"
    hplffplr_curve = get_curve(model,curve_name)
    hplffplr_curve.setName(curve_name)
    coil.setEnergyPartLoadFractionCurve(hplffplr_curve)
    return coil
  end

  # =============================================================================================================================
  def add_setpointmanageroutdoorairpretreat_erv(model,erv,oa_system)
    # add setpoint manager for outdoor air preheat
    spm_oa_pretreat = OpenStudio::Model::SetpointManagerOutdoorAirPretreat.new(model)
    spm_oa_pretreat.setMinimumSetpointTemperature(-99.0)
    spm_oa_pretreat.setMaximumSetpointTemperature(99.0)
    spm_oa_pretreat.setMinimumSetpointHumidityRatio(0.00001)
    spm_oa_pretreat.setMaximumSetpointHumidityRatio(1.0)
    mixed_air_node = oa_system.mixedAirModelObject.get.to_Node.get
    spm_oa_pretreat.setReferenceSetpointNode(mixed_air_node)
    spm_oa_pretreat.setMixedAirStreamNode(mixed_air_node)
    spm_oa_pretreat.setOutdoorAirStreamNode(oa_system.outboardOANode.get)
    return_air_node = oa_system.returnAirModelObject.get.to_Node.get
    spm_oa_pretreat.setReturnAirStreamNode(return_air_node)
    erv_outlet = erv.primaryAirOutletModelObject.get.to_Node.get
    spm_oa_pretreat.addToNode(erv_outlet)
  end

  # =============================================================================================================================
  def setup_air_sys_variablespeed(model,sys_objs,term_reheat_flag)
  # Scan system air loops and replace cooling coils with variable speed coils. Also specify a DX variable speed heating coil with a 
  # supplemental electric heating coil. A variable speed dx heating and cooling coils are used to represent a cold-climate roof-top 
  # unit.  
    # on-off schedules
    always_on = model.alwaysOnDiscreteSchedule
    always_off = model.alwaysOffDiscreteSchedule
    # remove existing coils and keep copies of supply fans
    sys_objs.each do |isys|
      sys_supply_fan = nil
      this_is_vav = false
      isys.supplyComponents.each do |icomp|
        if((icomp.to_CoilCoolingDXSingleSpeed.is_initialized) || (icomp.to_CoilHeatingElectric.is_initialized) ||
          (icomp.to_CoilHeatingElectric.is_initialized) || (icomp.to_CoilHeatingGas.is_initialized) ||
          (icomp.to_CoilHeatingWater.is_initialized) || (icomp.to_CoilCoolingWater.is_initialized))
          icomp.remove
        elsif((icomp.to_FanConstantVolume.is_initialized) || (icomp.to_FanVariableVolume.is_initialized))
          if icomp.to_FanConstantVolume.is_initialized
            sys_supply_fan = icomp.clone.to_FanConstantVolume.get
            icomp.remove
	      elsif icomp.to_FanVariableVolume.is_initialized 
            if icomp.name.to_s.include? 'Supply'
              sys_supply_fan = icomp.clone.to_FanVariableVolume.get
              icomp.remove
            end
            this_is_vav = true
          end
        end
      end
      if sys_supply_fan then sys_supply_fan.setName("#{isys.name} Supply Fan") end
      # DX cooling coil
      sys_clg_coil = OpenStudio::Model::CoilCoolingDXVariableSpeed.new(model)
      sys_clg_coil.setName("#{isys.name} VRF DX Clg Coil")
      sys_clg_coil = coilcoolingdxvariablespeedvrf_set_performance_curves(model,sys_clg_coil)
      ccapft_curve,ccapff_curve,ceirft_curve,ceirff_curve = coilcoolingdxvariablespeedspeeddatavrf_get_performance_curves(model)
      sys_clg_coil_speeddata1 = OpenStudio::Model::CoilCoolingDXVariableSpeedSpeedData.new(model,ccapft_curve,ccapff_curve,ceirft_curve,ceirff_curve)
      sys_clg_coil.addSpeed(sys_clg_coil_speeddata1)
      sys_clg_coil.setNominalSpeedLevel(1)
      sys_clg_coil.setBasinHeaterCapacity(1.0e-6)
      sys_clg_coil.setCrankcaseHeaterCapacity(1.0e-6)
      # Electric supplemental heating coil
      sys_elec_htg_coil = OpenStudio::Model::CoilHeatingElectric.new(model, always_on)
      sys_elec_htg_coil.setName("#{isys.name} Elec Htg Coil")	  
      # DX heating coil
      sys_dx_htg_coil = OpenStudio::Model::CoilHeatingDXVariableSpeed.new(model)
      sys_dx_htg_coil.setName("#{isys.name} VRF DX Htg Coil")
      hcapft_curve,hcapff_curve,heirft_curve,heirff_curve = coilheatingdxvariablespeedspeeddatavrf_get_performance_curves(model)
      sys_dx_htg_coil = coilheatingdxvariablespeedvrf_set_performance_curves(model,sys_dx_htg_coil)
      sys_dx_htg_coil_speed1 = OpenStudio::Model::CoilHeatingDXVariableSpeedSpeedData.new(model,hcapft_curve,hcapff_curve,heirft_curve,heirff_curve)
      sys_dx_htg_coil.addSpeed(sys_dx_htg_coil_speed1)
      sys_dx_htg_coil.setNominalSpeedLevel(1)
      sys_dx_htg_coil.setMinimumOutdoorDryBulbTemperatureforCompressorOperation(-20.0)
      sys_dx_htg_coil.setDefrostStrategy('resistive')
      sys_dx_htg_coil.setDefrostControl("timed")
      sys_dx_htg_coil.setResistiveDefrostHeaterCapacity(1.0e-6)
      sys_dx_htg_coil.setCrankcaseHeaterCapacity(1.0e-6)
      # System sizing parameters
      this_is_mau = false
      if isys.sizingSystem.typeofLoadtoSizeOn == 'VentilationRequirement' then this_is_mau = true end
      isys.sizingSystem.setCentralCoolingDesignSupplyAirTemperature(13.0)
      isys.sizingSystem.setCentralHeatingDesignSupplyAirTemperature(43.0)
      isys.sizingSystem.setCoolingDesignAirFlowMethod('DesignDay')
      isys.sizingSystem.setHeatingDesignAirFlowMethod('DesignDay')
      isys.sizingSystem.setSizingOption('NonCoincident')
      isys.sizingSystem.setCentralCoolingDesignSupplyAirHumidityRatio(0.0085)
      isys.sizingSystem.setCentralHeatingDesignSupplyAirHumidityRatio(0.0080)
      isys.sizingSystem.setSystemOutdoorAirMethod('ZoneSum')
      control_zone = isys.thermalZones.first
      sizing_zone = control_zone.sizingZone
      sizing_zone.setZoneCoolingDesignSupplyAirTemperature(13.0)
      sizing_zone.setZoneHeatingDesignSupplyAirTemperature(43.0)
      sizing_zone.setZoneCoolingSizingFactor(1.1)
      sizing_zone.setZoneHeatingSizingFactor(1.3)
      # attach new components to air loop
      sys_clg_coil.addToNode(isys.supplyOutletNode)
      sys_dx_htg_coil.addToNode(isys.supplyOutletNode)
      sys_elec_htg_coil.addToNode(isys.supplyOutletNode)
      # add setpoint manager for single zone systems
      if term_reheat_flag == 'Electric'
        sys_supply_fan.addToNode(isys.supplyOutletNode) 
          isys.thermalZones.each do |izone|
            izone.equipment.each do |icomp|
              if icomp.to_AirTerminalSingleDuctVAVReheat.is_initialized
                sys_supply_fan.addToNode(isys.supplyOutletNode) 
                spm = OpenStudio::Model::SetpointManagerWarmest.new(model)
                spm.setMinimumSetpointTemperature(13.0)
                spm.setMaximumSetpointTemperature(43.0)
                spm.addToNode(isys.supplyOutletNode) 
                if not icomp.to_AirTerminalSingleDuctVAVReheat.get.reheatCoil.to_CoilHeatingElectric.is_initialized
                term_unit = icomp.to_AirTerminalSingleDuctVAVReheat.get
                reheat_coil = term_unit.reheatCoil.to_CoilHeatingWater.get
                new_coil = OpenStudio::Model::CoilHeatingElectric.new(model, always_on)
                term_unit.setReheatCoil(new_coil)
                model.getCoilHeatingWaters.each do |icoil|
                  if icoil.name.to_s.strip == reheat_coil.name.to_s.strip
                    icoil.remove
                    break
                  end
                end
              end
            end
          end
	    end
      end
      # add new setpoint manager to outside air system as nodes might be out of date with e outdoor air setpoint manager
      oa_system = isys.airLoopHVACOutdoorAirSystem.get
      if isys.airLoopHVACOutdoorAirSystem.is_initialized
        isys.airLoopHVACOutdoorAirSystem.get.oaComponents.each do |icomp|
          if icomp.to_HeatExchangerAirToAirSensibleAndLatent.is_initialized
            erv = icomp.to_HeatExchangerAirToAirSensibleAndLatent.get
            add_setpointmanageroutdoorairpretreat_erv(model,erv,oa_system)
          end
        end
      end
    end
  end

  #=============================================================================================================================
  def remove_existing_htg_zone_units(model)
  # remove zonal heating units
    model.getThermalZones.each do |izone|
      if(izone.equipment.empty?) then next end
      izone.equipment.each do |icomp|
        if(icomp.to_ZoneHVACBaseboardConvectiveWater.is_initialized || 
           icomp.to_ZoneHVACBaseboardConvectiveElectric.is_initialized)
           icomp.remove
        end
      end
   end
    return model
  end

  # =============================================================================================================================
  def remove_existing_clg_zone_units(model)
  # remove existing zonal cooling units
    model.getThermalZones.each do |izone|
      if(izone.equipment.empty?) then next end
      izone.equipment.each do |icomp|
        if icomp.to_ZoneHVACPackagedTerminalAirConditioner.is_initialized then icomp.remove end
      end
    end
    return model
  end

  # =============================================================================================================================
  def setup_indoor_elec_baseboards(model)
  # setup zonal electric baseboards
    model.getThermalZones.each do |izone|
      if(izone.name.to_s.include? 'undefined') then next end
      zone_baseboard = OpenStudio::Model::ZoneHVACBaseboardConvectiveElectric.new(model)
      zone_baseboard.setName("#{izone.name} Elec Baseboard")
      zone_baseboard.addToThermalZone(izone)
    end
  end

  # =============================================================================================================================
  def remove_empty_plt_loops(model)
  # remove any empty plant loops including chilled water, hot-water, and condenser loops
    model.getPlantLoops.each do |iloop|
      this_is_hw_or_chw_or_cw_loop = false
      iloop.supplyComponents.each do |icomp|
        if(icomp.to_BoilerHotWater.is_initialized ||
           icomp.to_ChillerElectricEIR.is_initialized ||
           icomp.to_CoolingTowerSingleSpeed.is_initialized)
          this_is_hw_or_chw_or_cw_loop = true
          break
        end
      end
      if(this_is_hw_or_chw_or_cw_loop)
        demand_side_hxs = false
        iloop.demandComponents.each do |icomp|
          if(icomp.to_CoilHeatingWater.is_initialized || 
             icomp.to_CoilHeatingWaterBaseboard.is_initialized || 
             icomp.to_CoilCoolingWater.is_initialized)
            demand_side_hxs = true
            break
          end
        end
        if(!demand_side_hxs) then iloop.remove end
      end
    end
  end

  # =============================================================================================================================
  def set_air_sys_variable_speed_cop(model,input_htg_cop,input_clg_cop)
  # specify the COP for variable speed heating and cooling dx coils using Mitsubishi VRF data or input values

    # Mitsubishi VRF data
    clg_caps_puhy_lmu = [21.10,28.10,35.20,42.20,56.30,63.30,70.30,77.40,84.40,91.40,98.50,105.50] # units in 'kw'
    clg_cop_puhy_lmu =  [ 4.64, 4.40, 4.36, 4.07, 3.96, 3.85, 3.83, 3.95, 3.87, 3.85, 3.78,  3.78]
    clg_caps_puhy_kmu = [21.10,28.10,35.20,42.20,56.30,63.30,70.30,77.40,84.40,91.40,98.50,105.50] # units in 'kw'
    clg_cop_puhy_kmu =  [ 4.17, 4.01, 3.87, 3.87, 3.80, 3.75, 3.68, 3.80, 3.77, 3.68, 3.62,  3.55]

    htg_caps_puhy_lmu = [23.40,31.70,39.60,46.90,63.00,71.20,79.10,86.50,94.70,102.60,110.80,118.70]  # units in 'kw'
    htg_cop_puhy_lmu =  [ 4.27, 4.14, 4.02, 3.81, 3.71, 3.66, 3.65, 3.75, 3.67,  3.61,  3.53,  3.51]
    htg_caps_puhy_kmu = [23.40,31.70,39.60,46.90,63.00,71.20,79.10,86.50,94.70,102.60,110.80,118.70]  # units in 'kw'
    htg_cop_puhy_kmu =  [ 4.16, 4.24, 3.85, 3.93, 3.73, 3.70, 3.62, 3.74, 3.73,  3.57,  3.49,  3.35]

    clg_cap_puh_hp =    [21.10,28.10,42.20,56.30]  # units in 'kw'
    clg_cop_puh_hp =    [ 3.58, 3.22, 3.38, 3.13]
    htg_cap_puh_hp =    [23.40,31.70,46.90,63.30]  # units in 'kw'
    htg_cop_puh_hp =    [ 3.73, 3.47, 3.62, 3.37]

    clg_cap_mxz_nahz =  [5.28,6.45,8.32,10.55,12.31,14.07]  # units in 'kw'
    clg_cop_mxz_nahz =  [3.95,3.96,3.66, 4.11, 3.93, 3.52]
    htg_cap_mxz_nahz =  [6.45,7.33,8.38,13.19,14.07,15.83]  # units in 'kw'
    htg_cop_mxz_nahz =  [4.00,4.25,4.00, 3.95, 4.10, 3.75]

    # make up combined capacity and cop array from above data
    #clg_caps = [5.28,6.45,8.32,10.55,12.31,14.07,21.10,28.10,35.20,42.20,56.30,63.30,70.30,77.40,84.40,91.40,98.50,105.50]  # combine mxz_nahz and puh_lmu
    #clg_cops = [3.95,3.96,3.66, 4.11, 3.93, 3.52, 4.64, 4.40, 4.36, 4.07, 3.96, 3.85, 3.83, 3.95, 3.87, 3.85, 3.78,  3.78]  # combine mxz_nahz and puh_lmu
    #htg_caps = [6.45,7.33,8.38,13.19,14.07,15.83,23.40,31.70,39.60,46.90,63.00,71.20,79.10,86.50,94.70,102.60,110.80,118.70]  # combine mxz_nahz and puh_lmu
    #htg_cops = [4.00,4.25,4.00, 3.95, 4.10, 3.75, 4.27, 4.14, 4.02, 3.81, 3.71, 3.66, 3.65, 3.75, 3.67,  3.61,  3.53,  3.51]  # combine mxz_nahz and puh_lmu

    #clg_caps = [5.28,6.45,8.32,10.55,12.31,14.07,21.10,28.10,42.20,56.30]  # combine mxz_nahz and phu_hp
    #clg_cops = [3.95,3.96,3.66, 4.11, 3.93, 3.52, 3.58, 3.22, 3.38, 3.13]  # combine mxz_nahz and phu_hp
    #htg_caps = [6.45,7.33,8.38,13.19,14.07,15.83,23.40,31.70,46.90,63.30]  # combine mxz_nahz and phu_hp
    #htg_cops = [4.00,4.25,4.00, 3.95, 4.10, 3.75, 3.73, 3.47, 3.62, 3.37]  # combine mxz_nahz and phu_hp

    clg_caps = [5.28,6.45,8.32,10.55,12.31,14.07,21.10,28.10,42.20,56.30]  # combine mxz_nahz and phu_hp
    clg_cops = [3.95,3.96,3.66, 4.11, 3.93, 3.52, 3.58, 3.22, 3.38, 3.13]  # combine mxz_nahz and phu_hp
    htg_caps = [6.45,7.33,8.38,13.19,14.07,15.83,23.40,31.70,46.90,63.30]  # combine mxz_nahz and phu_hp
    htg_cops = [4.00,4.25,4.00, 3.95, 4.10, 3.75, 3.73, 3.47, 3.62, 3.37]  # combine mxz_nahz and phu_hp

    # Set COP for any 'CoilCoolingDX:VariableSpeed' and 'CoilHeatingVariableSpeed'
    clgdxcoils = model.getCoilCoolingDXVariableSpeeds
    clgdxcoils.each do |dxcoil|
      if input_clg_cop > 1.0
        cop = input_clg_cop
      else
        cap_int = 0
        coil_cap = dxcoil.grossRatedTotalCoolingCapacityAtSelectedNominalSpeedLevel.to_f/1000.0  # convert to kW
        clg_caps.each do |icap|
          if(coil_cap > icap) 
            cap_int += 1
          else
            break
          end
        end
        cap_int = [cap_int,clg_caps.size-1].min
        cop = clg_cops[cap_int]
      end
      dxcoil.speeds.each do |speed|
        speed.setReferenceUnitGrossRatedCoolingCOP(cop)
      end
    end
    htgdxcoils = model.getCoilHeatingDXVariableSpeeds
    htgdxcoils.each do |dxcoil|
      if input_htg_cop > 1.0
        cop = input_htg_cop
      else
        cap_int = 0
        coil_cap = dxcoil.ratedHeatingCapacityAtSelectedNominalSpeedLevel.to_f/1000.0  # convert to kW
        htg_caps.each do |icap|
          if(coil_cap > icap)
            cap_int += 1
          else
            break
          end
        end
        cap_int = [cap_int,htg_caps.size-1].min
        cop = htg_cops[cap_int]
      end
      dxcoil.speeds.each do |speed|
        speed.setReferenceUnitGrossRatedHeatingCOP(cop)
      end
    end
  end

  # =============================================================================================================================
  def set_air_sys_variable_speed_cap(model,air_sys_cap_siz_fr)
  # set capacity of variable speed dx cooling and heating coils. Updated capacity is design capacity multiplied by the factor 
  # 'air_sys_cap_siz_fr'.
    clgdxcoils = model.getCoilCoolingDXVariableSpeeds
    clgdxcoils.each do |dxcoil|
      nom_spd_cap = dxcoil.autosizedGrossRatedTotalCoolingCapacityAtSelectedNominalSpeedLevel.to_f
      dxcoil.setGrossRatedTotalCoolingCapacityAtSelectedNominalSpeedLevel(air_sys_cap_siz_fr*nom_spd_cap)
    end
    htgdxcoils = model.getCoilHeatingDXVariableSpeeds
    htgdxcoils.each do |dxcoil|
      nom_spd_cap = dxcoil.autosizedRatedHeatingCapacityAtSelectedNominalSpeedLevel.to_f
      dxcoil.setRatedHeatingCapacityAtSelectedNominalSpeedLevel(air_sys_cap_siz_fr*nom_spd_cap)
    end
  end

  # =============================================================================================================================
  def set_baseboard_cap(model,siz_fr)
  # update capacity of zonal electric baseboards. Updated capacity is the design capacity multiplied by the factor 'siz_fr'.
    baseboards = model.getZoneHVACBaseboardConvectiveElectrics
    baseboards.each do |zoneunit|
      new_cap = siz_fr*zoneunit.autosizedNominalCapacity.to_f
      zoneunit.setNominalCapacity(new_cap)
    end
  end
  
  # =============================================================================================================================
  def remove_air_loops(model)
  # remove all air loops from model
    air_loops = model.getAirLoopHVACs
    air_loops.each do |loop|
      loop.remove
    end
  end
  
end
