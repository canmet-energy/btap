module BTAPMeasureHelper
  ###################Helper functions

  # define the arguments that the user will input
  def arguments(model)
    args = OpenStudio::Measure::OSArgumentVector.new

    if true == @use_json_package
      #Set up package version of input.
      json_default = {}
      @measure_interface_detailed.each do |argument|
        json_default[argument['name']] = argument["default_value"]
      end
      default = JSON.pretty_generate(json_default)
      arg = OpenStudio::Ruleset::OSArgument.makeStringArgument('json_input', true)
      arg.setDisplayName('Contains a json version of the input as a single package.')
      arg.setDefaultValue(default)
      args << arg
    else
      # Conductances for all surfaces and subsurfaces.
      @measure_interface_detailed.each do |argument|
        arg = nil
        statement = nil
        case argument['type']
        when "String"
          arg = OpenStudio::Ruleset::OSArgument.makeStringArgument(argument['name'], argument['is_required'])
          arg.setDisplayName(argument['display_name'])
          arg.setDefaultValue(argument['default_value'].to_s)

        when "Double"
          arg = OpenStudio::Ruleset::OSArgument.makeDoubleArgument(argument['name'], argument['is_required'])
          arg.setDisplayName("#{argument['display_name']}")
          arg.setDefaultValue("#{argument['default_value']}".to_f)

        when "Choice"
          arg = OpenStudio::Measure::OSArgument.makeChoiceArgument(argument['name'], argument['choices'], argument['is_required'])
          arg.setDisplayName(argument['display_name'])
          arg.setDefaultValue(argument['default_value'].to_s)
          puts arg.defaultValueAsString

        when "Bool"
          arg = OpenStudio::Measure::OSArgument.makeBoolArgument(argument['name'], argument['is_required'])
          arg.setDisplayName(argument['display_name'])
          arg.setDefaultValue(argument['default_value'])


        when "StringDouble"
          if @use_string_double == false
            arg = OpenStudio::Ruleset::OSArgument.makeDoubleArgument(argument['name'], argument['is_required'])
            arg.setDefaultValue(argument['default_value'].to_f)
          else
            arg = OpenStudio::Ruleset::OSArgument.makeStringArgument(argument['name'], argument['is_required'])
            arg.setDefaultValue(argument['default_value'].to_s)
          end
          arg.setDisplayName(argument['display_name'])
        end
        args << arg
      end
    end
    return args
  end

  #returns a hash of the user inputs for you to use in your measure.
  def get_hash_of_arguments(user_arguments, runner)
    values = {}
    if @use_json_package
      return JSON.parse(runner.getStringArgumentValue('json_input', user_arguments))
    else

      @measure_interface_detailed.each do |argument|

        case argument['type']
        when "String", "Choice"
          values[argument['name']] = runner.getStringArgumentValue(argument['name'], user_arguments)
        when "Double"
          values[argument['name']] = runner.getDoubleArgumentValue(argument['name'], user_arguments)
        when "Bool"
          values[argument['name']] = runner.getBoolArgumentValue(argument['name'], user_arguments)
        when "StringDouble"
          value = nil
          if @use_string_double == false
            value = (runner.getDoubleArgumentValue(argument['name'], user_arguments).to_f)
          else
            value = runner.getStringArgumentValue(argument['name'], user_arguments)
            if valid_float?(value)
              value = value.to_f
            end
          end
          values[argument['name']] = value
        end
      end
    end
    return values
  end

  # boilerplate that validated ranges of inputs.
  def validate_and_get_arguments_in_hash(model, runner, user_arguments)
    return_value = true
    values = get_hash_of_arguments(user_arguments, runner)
    # use the built-in error checking
    if !runner.validateUserArguments(arguments(model), user_arguments)
      runner_register(runner, 'Error', "validateUserArguments failed... Check the argument definition for errors.")
      return_value = false
    end

    # Validate arguments
    errors = ""
    @measure_interface_detailed.each do |argument|
      case argument['type']
      when "Double"
        value = values[argument['name']]
        if (not argument["max_double_value"].nil? and value.to_f > argument["max_double_value"].to_f) or
            (not argument["min_double_value"].nil? and value.to_f < argument["min_double_value"].to_f)
          error = "#{argument['name']} must be between #{argument["min_double_value"]} and #{argument["max_double_value"]}. You entered #{value.to_f} for this #{argument['name']}.\n Please enter a value withing the expected range.\n"
          errors << error
        end
      when "StringDouble"
        value = values[argument['name']]
        if (not argument["valid_strings"].include?(value)) and (not valid_float?(value))
          error = "#{argument['name']} must be a string that can be converted to a float, or one of these #{argument["valid_strings"]}. You have entered #{value}\n"
          errors << error
        elsif (not argument["max_double_value"].nil? and value.to_f > argument["max_double_value"]) or
            (not argument["min_double_value"].nil? and value.to_f < argument["min_double_value"])
          error = "#{argument['name']} must be between #{argument["min_double_value"]} and #{argument["max_double_value"]}. You entered #{value} for #{argument['name']}. Please enter a stringdouble value in the expected range.\n"
          errors << error
        end
      end
    end
    #If any errors return false, else return the hash of argument values for user to use in measure.
    if errors != ""
      runner.registerError(errors)
      return false
    end
    return values
  end

  # Helper method to see if str is a valid float.
  def valid_float?(str)
    !!Float(str) rescue false
  end

  def set_up_clg_coil(model,doas_clg_coil)
    clg_cap_f_of_temp = OpenStudio::Model::CurveBiquadratic.new(model)
    clg_cap_f_of_temp.setCoefficient1Constant(0.942587793)
    clg_cap_f_of_temp.setCoefficient2x(0.009543347)
    clg_cap_f_of_temp.setCoefficient3xPOW2(0.000683770)
    clg_cap_f_of_temp.setCoefficient4y(-0.011042676)
    clg_cap_f_of_temp.setCoefficient5yPOW2(0.000005249)
    clg_cap_f_of_temp.setCoefficient6xTIMESY(-0.000009720)
    clg_cap_f_of_temp.setMinimumValueofx(17.0)
    clg_cap_f_of_temp.setMaximumValueofx(22.0)
    clg_cap_f_of_temp.setMinimumValueofy(13.0)
    clg_cap_f_of_temp.setMaximumValueofy(46.0)

    clg_cap_f_of_flow = OpenStudio::Model::CurveQuadratic.new(model)
    clg_cap_f_of_flow.setCoefficient1Constant(0.8)
    clg_cap_f_of_flow.setCoefficient2x(0.2)
    clg_cap_f_of_flow.setCoefficient3xPOW2(0.0)
    clg_cap_f_of_flow.setMinimumValueofx(0.5)
    clg_cap_f_of_flow.setMaximumValueofx(1.5)

    energy_input_ratio_f_of_temp = OpenStudio::Model::CurveBiquadratic.new(model)
    energy_input_ratio_f_of_temp.setCoefficient1Constant(0.342414409)
    energy_input_ratio_f_of_temp.setCoefficient2x(0.034885008)
    energy_input_ratio_f_of_temp.setCoefficient3xPOW2(-0.000623700)
    energy_input_ratio_f_of_temp.setCoefficient4y(0.004977216)
    energy_input_ratio_f_of_temp.setCoefficient5yPOW2(0.000437951)
    energy_input_ratio_f_of_temp.setCoefficient6xTIMESY(-0.000728028)
    energy_input_ratio_f_of_temp.setMinimumValueofx(17.0)
    energy_input_ratio_f_of_temp.setMaximumValueofx(22.0)
    energy_input_ratio_f_of_temp.setMinimumValueofy(13.0)
    energy_input_ratio_f_of_temp.setMaximumValueofy(46.0)

    energy_input_ratio_f_of_flow = OpenStudio::Model::CurveQuadratic.new(model)
    energy_input_ratio_f_of_flow.setCoefficient1Constant(1.1552)
    energy_input_ratio_f_of_flow.setCoefficient2x(-0.1808)
    energy_input_ratio_f_of_flow.setCoefficient3xPOW2(0.0256)
    energy_input_ratio_f_of_flow.setMinimumValueofx(0.5)
    energy_input_ratio_f_of_flow.setMaximumValueofx(1.5)

    part_load_fraction = OpenStudio::Model::CurveQuadratic.new(model)
    part_load_fraction.setCoefficient1Constant(0.85)
    part_load_fraction.setCoefficient2x(0.15)
    part_load_fraction.setCoefficient3xPOW2(0.0)
    part_load_fraction.setMinimumValueofx(0.0)
    part_load_fraction.setMaximumValueofx(1.0)

    doas_clg_coil.setTotalCoolingCapacityFunctionOfTemperatureCurve(clg_cap_f_of_temp)
    doas_clg_coil.setTotalCoolingCapacityFunctionOfFlowFractionCurve(clg_cap_f_of_flow)
    doas_clg_coil.setEnergyInputRatioFunctionOfTemperatureCurve(energy_input_ratio_f_of_temp)
    doas_clg_coil.setEnergyInputRatioFunctionOfFlowFractionCurve(energy_input_ratio_f_of_flow)
    doas_clg_coil.setPartLoadFractionCorrelationCurve(part_load_fraction)
    doas_clg_coil.autosizeRatedTotalCoolingCapacity
    doas_clg_coil.autosizeRatedAirFlowRate
    doas_clg_coil.autosizeRatedSensibleHeatRatio 
    doas_clg_coil.setRatedCOP(4)
    doas_clg_coil.setAvailabilitySchedule(model.alwaysOnDiscreteSchedule)
  end

  def set_up_htg_coil(model, doas_htg_coil)

    htg_cap_f_of_temp = OpenStudio::Model::CurveCubic.new(model)
    htg_cap_f_of_temp.setCoefficient1Constant(0.758746)
    htg_cap_f_of_temp.setCoefficient2x(0.027626)
    htg_cap_f_of_temp.setCoefficient3xPOW2(0.000148716)
    htg_cap_f_of_temp.setCoefficient4xPOW3(0.0000034992)
    htg_cap_f_of_temp.setMinimumValueofx(-20.0)
    htg_cap_f_of_temp.setMaximumValueofx(20.0)

    htg_cap_f_of_flow = OpenStudio::Model::CurveCubic.new(model)
    htg_cap_f_of_flow.setCoefficient1Constant(0.84)
    htg_cap_f_of_flow.setCoefficient2x(0.16)
    htg_cap_f_of_flow.setCoefficient3xPOW2(0.0)
    htg_cap_f_of_flow.setCoefficient4xPOW3(0.0)
    htg_cap_f_of_flow.setMinimumValueofx(0.5)
    htg_cap_f_of_flow.setMaximumValueofx(1.5)

    htg_energy_input_ratio_f_of_temp = OpenStudio::Model::CurveCubic.new(model)
    htg_energy_input_ratio_f_of_temp.setCoefficient1Constant(1.19248)
    htg_energy_input_ratio_f_of_temp.setCoefficient2x(-0.0300438)
    htg_energy_input_ratio_f_of_temp.setCoefficient3xPOW2(0.00103745)
    htg_energy_input_ratio_f_of_temp.setCoefficient4xPOW3(-0.000023328)
    htg_energy_input_ratio_f_of_temp.setMinimumValueofx(-20.0)
    htg_energy_input_ratio_f_of_temp.setMaximumValueofx(20.0)

    htg_energy_input_ratio_f_of_flow = OpenStudio::Model::CurveQuadratic.new(model)
    htg_energy_input_ratio_f_of_flow.setCoefficient1Constant(1.3824)
    htg_energy_input_ratio_f_of_flow.setCoefficient2x(-0.4336)
    htg_energy_input_ratio_f_of_flow.setCoefficient3xPOW2(0.0512)
    htg_energy_input_ratio_f_of_flow.setMinimumValueofx(0.0)
    htg_energy_input_ratio_f_of_flow.setMaximumValueofx(1.0)

    htg_part_load_fraction = OpenStudio::Model::CurveQuadratic.new(model)
    htg_part_load_fraction.setCoefficient1Constant(0.75)
    htg_part_load_fraction.setCoefficient2x(0.25)
    htg_part_load_fraction.setCoefficient3xPOW2(0.0)
    htg_part_load_fraction.setMinimumValueofx(0.0)
    htg_part_load_fraction.setMaximumValueofx(1.0)

    doas_htg_coil.setTotalHeatingCapacityFunctionofTemperatureCurve(htg_cap_f_of_temp)
    doas_htg_coil.setTotalHeatingCapacityFunctionofFlowFractionCurve(htg_cap_f_of_flow)
    doas_htg_coil.setEnergyInputRatioFunctionofTemperatureCurve(htg_energy_input_ratio_f_of_temp) 
    doas_htg_coil.setEnergyInputRatioFunctionofFlowFractionCurve(htg_energy_input_ratio_f_of_flow) 
    doas_htg_coil.setPartLoadFractionCorrelationCurve(htg_part_load_fraction)
    doas_htg_coil.autosizeRatedTotalHeatingCapacity 
    doas_htg_coil.autosizeRatedAirFlowRate
    doas_htg_coil.setRatedCOP(3)
  end # end of def set_up_htg_coil(model, doas_htg_coil)

  def set_up_vav_fan(model,doas_fan)
    doas_fan.setFanEfficiency(0.8)
    doas_fan.setPressureRise(75) # Pa #ML This number is a guess; zone equipment pretending to be a DOAS
    doas_fan.autosizeMaximumFlowRate
    doas_fan.setFanPowerMinimumFlowFraction(0.6)
    doas_fan.setMotorEfficiency(0.9)
    doas_fan.setMotorInAirstreamFraction(1.0)
    doas_fan.setFanPowerCoefficient1(0.35071223)
    doas_fan.setFanPowerCoefficient2(0.30850535)
    doas_fan.setFanPowerCoefficient3(-0.54137364)
    doas_fan.setFanPowerCoefficient4(0.87198823)
    doas_fan.setFanPowerCoefficient5(0)
  end #set_up_vav_fan(model,doas_fan)

  def createPrimaryAirLoops(model, runner)
    
    #Get the zones that are connected to an air loop with an outdoor air system
    airloops = model.getAirLoopHVACs
    zones_done = []
    airloops.each do |airloop|
      airloop.supplyComponents.each do |supplyComponent|
        if supplyComponent.to_AirLoopHVACOutdoorAirSystem.is_initialized
          airloop_oas_sys = supplyComponent.to_AirLoopHVACOutdoorAirSystem.get
          
          #record zones
          airloop.thermalZones.each do |zone|
            if not zones_done.include?(zone)
              zones_done << zone
            end
          end
        end
      end
    end

    #For those zones, create and set the air loop
    zones_done.each do |zone|
      airloop_comps = []
      #create air loop
      doas_airloop = OpenStudio::Model::AirLoopHVAC.new(model) #create the air loop
      doas_airloop.setName("#{zone.name} doas loop")
      #set air loop sizing
      doas_airloop_sizing = doas_airloop.sizingSystem
      doas_airloop_sizing.setTypeofLoadtoSizeOn('VentilationRequirement')
      doas_airloop_sizing.autosizeDesignOutdoorAirFlowRate
      doas_airloop_sizing.setMinimumSystemAirFlowRatio(1.0)
      doas_airloop_sizing.setPreheatDesignTemperature(7.0)
      doas_airloop_sizing.setPreheatDesignHumidityRatio(0.008)
      doas_airloop_sizing.setPrecoolDesignTemperature(13.0)
      doas_airloop_sizing.setPrecoolDesignHumidityRatio(0.008)
      doas_airloop_sizing.setCentralCoolingDesignSupplyAirTemperature(24)
      doas_airloop_sizing.setCentralHeatingDesignSupplyAirTemperature(21)
      doas_airloop_sizing.setSizingOption('NonCoincident')
      doas_airloop_sizing.setAllOutdoorAirinCooling(true)
      doas_airloop_sizing.setAllOutdoorAirinHeating(true)
      doas_airloop_sizing.setCentralCoolingDesignSupplyAirHumidityRatio(0.0085)
      doas_airloop_sizing.setCentralHeatingDesignSupplyAirHumidityRatio(0.0080)
      doas_airloop_sizing.setCoolingDesignAirFlowMethod('DesignDay')
      doas_airloop_sizing.setCoolingDesignAirFlowRate(0.0)
      doas_airloop_sizing.setHeatingDesignAirFlowMethod('DesignDay')
      doas_airloop_sizing.setHeatingDesignAirFlowRate(0.0)
      doas_airloop_sizing.setSystemOutdoorAirMethod('VentilationRateProcedure')             
      #create air loop components
      always_on = model.alwaysOnDiscreteSchedule
      doas_htg_coil = OpenStudio::Model::CoilHeatingDXSingleSpeed.new(model)
      airloop_comps << doas_htg_coil
      set_up_htg_coil(model,doas_htg_coil)

      doas_fan = OpenStudio::Model::FanVariableVolume.new(model, always_on)
      airloop_comps << doas_fan
      set_up_vav_fan(model,doas_fan)

      doas_clg_coil = OpenStudio::Model::CoilCoolingDXSingleSpeed.new(model)
      set_up_clg_coil(model,doas_clg_coil)
      airloop_comps << doas_clg_coil

      doas_oa_controller = OpenStudio::Model::ControllerOutdoorAir.new(model)
      doas_oa_controller.autosizeMinimumOutdoorAirFlowRate
      doas_oa_controller.autosizeMaximumOutdoorAirFlowRate
      doas_oa_controller.setMinimumFractionofOutdoorAirSchedule(always_on)
      doas_oa_controller.setMaximumFractionofOutdoorAirSchedule(always_on)
      doas_oa_controller.setHeatRecoveryBypassControlType('BypassWhenOAFlowGreaterThanMinimum')
      doas_oa_controller.setEconomizerControlType("NoEconomizer")

      doas_oasys = OpenStudio::Model::AirLoopHVACOutdoorAirSystem.new(model, doas_oa_controller)
      airloop_comps << doas_oasys
      #add comps to loop
      airloop_supply_inlet = doas_airloop.supplyInletNode
      airloop_comps.each do |airloop_comp|
        airloop_comp.addToNode(airloop_supply_inlet)
      end

      doas_vav_term = OpenStudio::Model::AirTerminalSingleDuctVAVHeatAndCoolNoReheat.new(model)
      doas_vav_term.setName("#{zone.name.to_s} doas vav terminal")
      doas_vav_term.setAvailabilitySchedule(always_on)
      doas_vav_term.autosizeMaximumAirFlowRate
      doas_vav_term.setZoneMinimumAirFlowFraction(0.3)
      doas_airloop.addBranchForZone(zone,doas_vav_term.to_StraightComponent)
         
      #Get the corresponding equipment list for the zone and add the doas terminal as the first equipment
      model.getZoneHVACEquipmentLists.each do |zoneHVACEquipmentList|
        new_eqp_clg_order=[]
        new_eqp_htg_order=[]

        if zoneHVACEquipmentList.thermalZone == zone
         
          #determine the new htg/cooling order by placing doas_vav_term into a temporary variable (e.g. new_eqp_clg_order), append the original eqp in clg/htg order, and use the variable to set the new order
          
          new_eqp_clg_order[0] = doas_vav_term
          
          zoneHVACEquipmentList.equipmentInCoolingOrder.each do |eqp|
           
            zoneHVACEquipmentList.removeEquipment(eqp)
            if eqp == doas_vav_term

            else
              new_eqp_clg_order << eqp
            end
          
          end
          
          new_eqp_htg_order[0] = doas_vav_term
          zoneHVACEquipmentList.equipmentInHeatingOrder.each do |eqp|
            zoneHVACEquipmentList.removeEquipment(eqp)
            if eqp == doas_vav_term

            else
              new_eqp_htg_order << eqp
            end
          end


          
          #set the new heating cooling order 
          new_eqp_clg_order.each do |eqp|
           
            zoneHVACEquipmentList.addEquipment(eqp)
          end

          zoneHVACEquipmentList.equipmentInCoolingOrder.each do |eqp|
           
          end

          new_eqp_htg_order.each do|eqp|
            
            zoneHVACEquipmentList.addEquipment(eqp)
          end
          zoneHVACEquipmentList.equipmentInCoolingOrder.each do |eqp|
            
          end
        end#if zoneHVACEquipmentList.thermalZone == zone
      end #model.getZoneHVACEquipmentLists.each do |zoneHVACEquipmentList|

      model.getZoneHVACEquipmentLists.each do |zoneHVACEquipmentList|
        if zoneHVACEquipmentList.thermalZone == zone
          
          zoneHVACEquipmentList.equipmentInCoolingOrder.each do |eqp|
            
          end
        end
      end
    end #zones_done.each do |zone|

    
    return true
  end #end of createPrimaryAirLoops


  def set_up_erv(model,zone,airloop_oas_sys)

    #get the vent req
    vent_flow = -999
    vent1 = -999
    vent2= -999
    airloop_oas_sys
    if airloop_oas_sys.getControllerOutdoorAir.autosizedMinimumOutdoorAirFlowRate.is_initialized
      vent_flow = airloop_oas_sys.getControllerOutdoorAir.autosizedMinimumOutdoorAirFlowRate.get.to_f
    else
      dsoa = zone.spaces[0].designSpecificationOutdoorAir
      if dsoa.is_initialized
        dsoa = dsoa.get
        vent1 = dsoa.outdoorAirFlowperFloorArea
        vent2 = dsoa.outdoorAirFlowperPerson
      end
    end
    #get air loop fan sched
    airloop = airloop_oas_sys.airLoop.get
    erv_sch = airloop.availabilitySchedule
    #create erv related objects
    erv_controller = OpenStudio::Model::ZoneHVACEnergyRecoveryVentilatorController.new(model)
    erv_hx = OpenStudio::Model::HeatExchangerAirToAirSensibleAndLatent.new(model)
    erv_fan_onoff_sup = OpenStudio::Model::FanOnOff.new(model)
    erv_fan_onoff_exh = OpenStudio::Model::FanOnOff.new(model)
  
    #define fan on off performances
    erv_fan_onoff_sup.setName("#{zone.name} erv sup fan")
    erv_fan_onoff_sup.setAvailabilitySchedule(model.alwaysOnDiscreteSchedule)
    erv_fan_onoff_sup.setFanEfficiency(0.75)
    erv_fan_onoff_sup.setMotorEfficiency(0.9)
    erv_fan_onoff_sup.setMotorInAirstreamFraction(1.0)
    erv_fan_onoff_sup.setPressureRise(200)
    erv_fan_onoff_exh.setName("#{zone.name} erv exh fan")
    erv_fan_onoff_exh.setAvailabilitySchedule(model.alwaysOnDiscreteSchedule)
    erv_fan_onoff_exh.setFanEfficiency(0.75)
    erv_fan_onoff_exh.setMotorEfficiency(0.9)
    erv_fan_onoff_exh.setMotorInAirstreamFraction(1.0)
    erv_fan_onoff_exh.setPressureRise(200)

    #define hx parameters 
    erv_hx.setName("#{zone.name} erv hx")
    erv_hx.setAvailabilitySchedule(model.alwaysOnDiscreteSchedule)
    erv_hx.setEconomizerLockout(false)
    erv_hx.setFrostControlType("ExhaustAirRecirculation")
    erv_hx.setHeatExchangerType("Rotary")
    erv_hx.setInitialDefrostTimeFraction(0.167)
    erv_hx.setRateofDefrostTimeFractionIncrease(0.012)
    erv_hx.setLatentEffectivenessat100CoolingAirFlow(0.75)
    erv_hx.setLatentEffectivenessat100HeatingAirFlow(0.75)
    erv_hx.setLatentEffectivenessat75CoolingAirFlow(0.75)
    erv_hx.setLatentEffectivenessat75HeatingAirFlow(0.75)
    erv_hx.setThresholdTemperature(-23.3) #btap number, seems low

    #define erv controller
    erv_controller.setName("#{zone.name} erv contr")
    erv_controller.setTemperatureHighLimit(19)
    erv_controller.setTemperatureLowLimit(13)
    erv_controller.setExhaustAirTemperatureLimit("NoExhaustAirTemperatureLimit")
    erv_controller.setExhaustAirEnthalpyLimit("NoExhaustAirEnthalpyLimit")
    erv_controller.setTimeofDayEconomizerFlowControlSchedule(model.alwaysOffDiscreteSchedule)
    erv_controller.setHighHumidityControlFlag(false)
    electronicEnthalpyCurveA = OpenStudio::Model::CurveCubic.new(model)
    electronicEnthalpyCurveA.setCoefficient1Constant(0.01342704)
    electronicEnthalpyCurveA.setCoefficient2x(-0.00047892)
    electronicEnthalpyCurveA.setCoefficient3xPOW2(0.000053352)
    electronicEnthalpyCurveA.setCoefficient4xPOW3(-0.0000018103)
    electronicEnthalpyCurveA.setMinimumValueofx(16.6)
    electronicEnthalpyCurveA.setMaximumValueofx(29.13)
    erv_controller.setElectronicEnthalpyLimitCurve(electronicEnthalpyCurveA)
    
    #set up erv 
    erv = OpenStudio::Model::ZoneHVACEnergyRecoveryVentilator.new(model,erv_hx,erv_fan_onoff_sup,erv_fan_onoff_exh)
    erv.setName("#{zone.name} erv doas")
    erv.setAvailabilitySchedule(erv_sch)
    erv.setController(erv_controller)
    if not vent_flow == -999
      erv_fan_onoff_sup.setMaximumFlowRate(vent_flow)
      erv_fan_onoff_exh.setMaximumFlowRate(vent_flow)
      erv.setSupplyAirFlowRate(vent_flow)
      erv.setExhaustAirFlowRate(vent_flow)
    else
      erv_fan_onoff_sup.autosizeMaximumFlowRate
      erv_fan_onoff_exh.autosizeMaximumFlowRate
      erv.autosizeSupplyAirFlowRate 
      erv.autosizeExhaustAirFlowRate 
      erv.setVentilationRateperUnitFloorArea(vent1)
      erv.setVentilationRateperOccupant(vent2)

    end


    #include doas in zone equip list
    model.getZoneHVACEquipmentLists.each do |zoneHVACEquipmentList|
      list_of_eqp = []
      eqp_clg_priority = []
      eqp_htg_priority = []
      if zoneHVACEquipmentList.thermalZone == zone

        list_of_eqp = zoneHVACEquipmentList.equipment
        list_of_eqp.each do|eqp|
          eqp_clg_priority << zoneHVACEquipmentList.coolingPriority(eqp)
          eqp_htg_priority << zoneHVACEquipmentList.heatingPriority(eqp)
          zoneHVACEquipmentList.removeEquipment(eqp)
          
        end
        #reconstruct clg order
        #zoneHVACEquipmentList.addEquipment(erv.to_ModelObject.get)
        erv.addToThermalZone(zone)
        list_of_eqp.each_with_index do |eqp,index|
          clg  = eqp_clg_priority[index]+1
          htg = eqp_htg_priority[index]+1
          zoneHVACEquipmentList.addEquipment(eqp)
   
        end

      end
    end

    return erv
  end

  def set_up_doas(model, zone, airloop_oas_sys)
    
    #add ERV
    erv = set_up_erv(model,zone,airloop_oas_sys)

    #adjust relevant equipment 
    #set existing AirLoopHVACOutdoorAirSystem controller to 0 outdoor flow
    airloop_oas_sys.getControllerOutdoorAir.setMaximumOutdoorAirFlowRate(0.0)
    airloop_oas_sys.getControllerOutdoorAir.setMinimumOutdoorAirFlowRate(0.0)  
    #adjust terminals if needed (changing setpoint manager)
    zone_term = zone.airLoopHVACTerminal.get #terminal will be defined since the zone is an air loop
    if zone_term.to_AirTerminalSingleDuctVAVReheat.is_initialized or zone_term.to_AirTerminalSingleDuctVAVHeatAndCoolReheat.is_initialized or zone_term.to_AirTerminalSingleDuctVAVHeatAndCoolNoReheat.is_initialized #change setpoint manager for vav terminals
      if zone_term.to_AirTerminalSingleDuctVAVReheat.is_initialized
        zone_term.to_AirTerminalSingleDuctVAVReheat.get.setZoneMinimumAirFlowMethod("Constant")
        zone_term.to_AirTerminalSingleDuctVAVReheat.get.setConstantMinimumAirFlowFraction(0.05)
      elsif zone_term.to_AirTerminalSingleDuctVAVHeatAndCoolNoReheat.is_initialized
        zone_term.to_AirTerminalSingleDuctVAVHeatAndCoolNoReheat.get.setZoneMinimumAirFlowFraction(0.05)
      end
      airloop = airloop_oas_sys.airLoop.get
      sup_node = airloop.supplyOutletNode
      stp_mg = sup_node.to_Node.get.setpointManagers[0]
      if stp_mg.to_SetpointManagerScheduled.is_initialized 
        stp_mg.remove
        new_setpoint_manager_warmest = OpenStudio::Model::SetpointManagerWarmest.new(model) 	
        new_setpoint_manager_warmest.setName("#{sup_node.name} SAT stpmanager")
        new_setpoint_manager_warmest.setControlVariable("Temperature")
        new_setpoint_manager_warmest.setMinimumSetpointTemperature(12)
        new_setpoint_manager_warmest.setMaximumSetpointTemperature(35)
        new_setpoint_manager_warmest.setStrategy("MaximumTemperature")
        new_setpoint_manager_warmest.addToNode(sup_node)
    
      end
    end
    #set erv schedule to existing air loop hvac sched
      




  end #set_up_doas(model, zones_done, airloop_oas_sys)


end

module BTAPMeasureTestHelper
  ##### Helper methods Do notouch unless you know the consequences.

  #Boiler plate to default values and number of arguments against what is in your test's setup method.
  def test_arguments_and_defaults
    [true, false].each do |json_input|
      [true, false].each do |string_double|
        @use_json_package = json_input
        @use_string_double = string_double

        # Create an instance of the measure
        measure = get_measure_object()
        measure.use_json_package = @use_json_package
        measure.use_string_double = @use_string_double
        model = OpenStudio::Model::Model.new

        # Create an instance of a runner
        runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)

        # Test arguments and defaults
        arguments = measure.arguments(model)
        #convert whatever the input was into a hash. Then test.

        #check number of arguments.
        if @use_json_package
          assert_equal(@measure_interface_detailed.size, JSON.parse(arguments[0].defaultValueAsString).size, "The measure should have #{@measure_interface_detailed.size} but actually has #{arguments.size}. Here the the arguement expected #{JSON.pretty_generate(@measure_interface_detailed) } \n and this is the actual \n  #{JSON.pretty_generate(arguments[0])}")
        else
          assert_equal(@measure_interface_detailed.size, arguments.size, "The measure should have #{@measure_interface_detailed.size} but actually has #{arguments.size}. Here the the arguement expected #{@measure_interface_detailed} and this is the actual #{arguments}")
          (@measure_interface_detailed).each_with_index do |argument_expected, index|
            assert_equal(argument_expected['name'], arguments[index].name, "Measure argument name of #{argument_expected['name']} was expected, but got #{arguments[index].name} instead.")
            assert_equal(argument_expected['display_name'], arguments[index].displayName, "Display name for argument #{argument_expected['name']} was expected to be #{argument_expected['display_name']}, but got #{arguments[index].displayName} instead.")
            case argument_type(arguments[index])
            when "String", "Choice"
              assert_equal(argument_expected['default_value'].to_s, arguments[index].defaultValueAsString, "The default value for argument #{argument_expected['name']} was #{argument_expected['default_value']}, but actual was #{arguments[index].defaultValueAsString}")
            when "Double", "Integer"
              assert_equal(argument_expected['default_value'].to_f, arguments[index].defaultValueAsDouble.to_f, "The default value for argument #{argument_expected['name']} was #{argument_expected['default_value']}, but actual was #{arguments[index].defaultValueAsString}")
            when "Bool"
              assert_equal(argument_expected['default_value'], arguments[index].defaultValueAsBool, "The default value for argument #{argument_expected['name']} was #{argument_expected['default_value']}, but actual was #{arguments[index].defaultValueAsString}")
            end
          end
        end
      end
    end
  end

  # Test argument ranges.
  def test_argument_ranges
    model = OpenStudio::Model::Model.new
    standard = Standard.build('NECB2015')
    standard.model_add_design_days_and_weather_file(model, nil, 'CAN_AB_Edmonton.Intl.AP.711230_CWEC2016.epw')

    [true, false].each do |json_input|
      [true, false].each do |string_double|
        @use_json_package = json_input
        @use_string_double = string_double
        (@measure_interface_detailed).each_with_index do |argument|
          if argument['type'] == 'Double' or argument['type'] == 'StringDouble'
            puts "testing range for #{argument['name']} "
            #Check over max
            if not argument['max_double_value'].nil?
              puts "testing max limit"
              input_arguments = @good_input_arguments.clone
              over_max_value = argument['max_double_value'].to_f + 1.0
              over_max_value = over_max_value.to_s if argument['type'].downcase == "StringDouble".downcase
              input_arguments[argument['name']] = over_max_value
              puts "Testing argument #{argument['name']} max limit of #{argument['max_double_value']}"
              input_arguments = {'json_input' => JSON.pretty_generate(input_arguments)} if @use_json_package
              runner = run_measure(input_arguments, model)
              assert(runner.result.value.valueName != 'Success', "Checks did not stop a lower than limit value of #{over_max_value} for #{argument['name']}")
              puts "Success: Testing argument #{argument['name']} max limit of #{argument['max_double_value']}"
            end
            #Check over max
            if not argument['min_double_value'].nil?
              puts "testing min limit"
              input_arguments = @good_input_arguments.clone
              over_min_value = argument['min_double_value'].to_f - 1.0
              over_min_value = over_max_value.to_s if argument['type'].downcase == "StringDouble".downcase
              input_arguments[argument['name']] = over_min_value
              puts "Testing argument #{argument['name']} min limit of #{argument['min_double_value']}"
              input_arguments = {'json_input' => JSON.pretty_generate(input_arguments)} if @use_json_package
              runner = run_measure(input_arguments, model)
              assert(runner.result.value.valueName != 'Success', "Checks did not stop a lower than limit value of #{over_min_value} for #{argument['name']}")
              puts "Success:Testing argument #{argument['name']} min limit of #{argument['min_double_value']}"
            end

          end
          if (argument['type'] == 'StringDouble') and (not argument["valid_strings"].nil?) and @use_string_double
            input_arguments = @good_input_arguments.clone
            input_arguments[argument['name']] = SecureRandom.uuid.to_s
            puts "Testing argument #{argument['name']} min limit of #{argument['min_double_value']}"
            input_arguments = {'json_input' => JSON.pretty_generate(input_arguments)} if @use_json_package
            runner = run_measure(input_arguments, model)
            assert(runner.result.value.valueName != 'Success', "Checks did not stop a lower than limit value of #{over_min_value} for #{argument['name']}")
          end
        end
      end
    end
  end

  # helper method to create necb archetype as a starting point for testing.
  def create_necb_protype_model(building_type, climate_zone, epw_file, template)

    osm_directory = "#{Dir.pwd}/output/#{building_type}-#{template}-#{climate_zone}-#{epw_file}"
    FileUtils.mkdir_p (osm_directory) unless Dir.exist?(osm_directory)
    #Get Weather climate zone from lookup
    weather = BTAP::Environment::WeatherFile.new(epw_file)
    #create model
    building_name = "#{template}_#{building_type}"

    prototype_creator = Standard.build(template)
    model = prototype_creator.model_create_prototype_model(
        epw_file: epw_file,
        sizing_run_dir: osm_directory,
        debug: @debug,
        template: template,
        building_type: building_type)

    #set weather file to epw_file passed to model.
    weather.set_weather_file(model)
    return model
  end

  # Custom way to run the measure in the test.
  def run_measure(input_arguments, model)

    # This will create a instance of the measure you wish to test. It does this based on the test class name.
    measure = get_measure_object()
    measure.use_json_package = @use_json_package
    measure.use_string_double = @use_string_double
    # Return false if can't
    return false if false == measure
    arguments = measure.arguments(model)
    argument_map = OpenStudio::Measure.convertOSArgumentVectorToMap(arguments)
    runner = OpenStudio::Measure::OSRunner.new(OpenStudio::WorkflowJSON.new)
    #Check if

    # Set the arguements in the argument map use json or real arguments.
    if @use_json_package
      argument = arguments[0].clone
      assert(argument.setValue(input_arguments['json_input']), "Could not set value for 'json_input' to #{input_arguments['json_input']}")
      argument_map['json_input'] = argument
    else
      input_arguments.each_with_index do |(key, value), index|
        argument = arguments[index].clone
        if argument_type(argument) == "Double"
          #forces it to a double if it is a double.
          assert(argument.setValue(value.to_f), "Could not set value for #{key} to #{value}")
        else
          assert(argument.setValue(value.to_s), "Could not set value for #{key} to #{value}")
        end
        argument_map[key] = argument
      end
    end
    #run the measure
    measure.run(model, runner, argument_map)
    runner.result
    return runner
  end


  #Fancy way of getting the measure object automatically.
  def get_measure_object()
    measure_class_name = self.class.name.to_s.match(/(BTAP.*)(\_Test)/i).captures[0]
    measure = nil
    eval "measure = #{measure_class_name}.new"
    if measure.nil?
      puts "Measure class #{measure_class_name} is invalid. Please ensure the test class name is of the form 'MeasureName_Test' "
      return false
    end
    return measure
  end

  #Determines the OS argument type dynamically.
  def argument_type(argument)
    case argument.type.value
    when 0
      return "Bool"
    when 1 #Double
      return "Double"
    when 2 #Quantity
      return "Quantity"
    when 3 #Integer
      return "Integer"
    when 4
      return "String"
    when 5 #Choice
      return "Choice"
    when 6 #Path
      return "Path"
    when 7 #Separator
      return "Separator"
    else
      return "Blah"
    end
  end

  # Valid float helper.
  def valid_float?(str)
    !!Float(str) rescue false
  end

  #Method does a deep copy of a model.
  def copy_model(model)
    copy_model = OpenStudio::Model::Model.new
    # remove existing objects from model
    handles = OpenStudio::UUIDVector.new
    copy_model.objects.each do |obj|
      handles << obj.handle
    end
    copy_model.removeObjects(handles)
    # put contents of new_model into model_to_replace
    copy_model.addObjects(model.toIdfFile.objects)
    return copy_model
  end

end
