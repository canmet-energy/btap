import tempfile
import unittest

from tests.support import needs_sdk


def _schedule(model):
    import openstudio

    return openstudio.model.ScheduleConstant(model)


def _plant(model, name, loop_type):
    import openstudio

    loop = openstudio.model.PlantLoop(model)
    loop.setName(name)
    loop.sizingPlant().setLoopType(loop_type)
    return loop


def _heating_coil(model, class_name):
    import openstudio

    cls = getattr(openstudio.model, class_name)
    schedule = _schedule(model)
    if class_name == 'CoilHeatingLowTempRadiantConstFlow':
        return cls(model, schedule, schedule, schedule, schedule)
    if class_name == 'CoilHeatingLowTempRadiantVarFlow':
        return cls(model, schedule)
    return cls(model)


def _cooling_const_flow_coil(model):
    import openstudio

    schedule = _schedule(model)
    return openstudio.model.CoilCoolingLowTempRadiantConstFlow(
        model, schedule, schedule, schedule, schedule)


def _cooling_coil(model, class_name):
    import openstudio

    if class_name == 'CoilCoolingLowTempRadiantConstFlow':
        return _cooling_const_flow_coil(model)
    if class_name == 'CoilCoolingLowTempRadiantVarFlow':
        return openstudio.model.CoilCoolingLowTempRadiantVarFlow(
            model, _schedule(model))
    return getattr(openstudio.model, class_name)(model)


def _absorption_plant(model, name='Chilled Water'):
    import openstudio

    chilled = _plant(model, name, 'Cooling')
    condenser = _plant(model, 'Condenser', 'Condenser')
    generator = _plant(model, 'Generator', 'Heating')
    boiler = openstudio.model.BoilerHotWater(model)
    assert boiler.setFuelType('NaturalGas')
    assert generator.addSupplyBranchForComponent(boiler)
    chiller = openstudio.model.ChillerAbsorptionIndirect(model)
    assert chilled.addSupplyBranchForComponent(chiller)
    assert condenser.addDemandBranchForComponent(chiller)
    assert chiller.addToTertiaryNode(generator.demandInletNode())
    return chilled


def _zonal_equipment(model, class_name):
    import openstudio

    cls = getattr(openstudio.model, class_name)
    if class_name == 'ZoneHVACLowTempRadiantConstFlow':
        schedule = model.alwaysOnDiscreteSchedule()
        heating = _heating_coil(
            model, 'CoilHeatingLowTempRadiantConstFlow')
        cooling = _cooling_const_flow_coil(model)
        return cls(model, schedule, heating, cooling)
    if class_name == 'ZoneHVACLowTempRadiantVarFlow':
        schedule = model.alwaysOnDiscreteSchedule()
        control = _schedule(model)
        heating = _heating_coil(
            model, 'CoilHeatingLowTempRadiantVarFlow')
        cooling = openstudio.model.CoilCoolingLowTempRadiantVarFlow(
            model, control)
        return cls(model, schedule, heating, cooling)
    if class_name == 'ZoneHVACUnitVentilator':
        unit = cls(model)
        assert unit.setHeatingCoil(
            openstudio.model.CoilHeatingElectric(model))
        assert unit.setCoolingCoil(
            openstudio.model.CoilCoolingWater(model))
        return unit
    return cls(model)


def _terminal(model, class_name):
    import openstudio

    cls = getattr(openstudio.model, class_name)
    heating = openstudio.model.CoilHeatingWater(model)
    cooling = openstudio.model.CoilCoolingWater(model)
    if class_name == 'AirTerminalSingleDuctConstantVolumeFourPipeBeam':
        return cls(
            model,
            openstudio.model.CoilCoolingFourPipeBeam(model),
            openstudio.model.CoilHeatingFourPipeBeam(model))
    if class_name == 'AirTerminalSingleDuctConstantVolumeFourPipeInduction':
        terminal = cls(model, heating)
        assert terminal.setCoolingCoil(cooling)
        return terminal
    if class_name == 'AirTerminalSingleDuctParallelPIUReheat':
        return cls(
            model, _schedule(model),
            openstudio.model.FanConstantVolume(model),
            openstudio.model.CoilHeatingElectric(model))
    if class_name == 'AirTerminalSingleDuctSeriesPIUReheat':
        return cls(
            model, openstudio.model.FanConstantVolume(model),
            openstudio.model.CoilHeatingElectric(model))
    if class_name == 'AirTerminalSingleDuctVAVHeatAndCoolReheat':
        return cls(model, openstudio.model.CoilHeatingElectric(model))
    return cls(model)


@needs_sdk
class TestEveryAddedHeatingCoilIsLoadBearing(unittest.TestCase):
    CASES = (
        ('to_CoilHeatingDXVariableRefrigerantFlowFluidTemperatureControl',
         'CoilHeatingDXVariableRefrigerantFlowFluidTemperatureControl',
         'Electricity', True, False),
        ('to_CoilHeatingDesuperheater', 'CoilHeatingDesuperheater',
         'Electricity', False, True),
        ('to_CoilHeatingElectricMultiStage', 'CoilHeatingElectricMultiStage',
         'Electricity', False, True),
        ('to_CoilHeatingFourPipeBeam', 'CoilHeatingFourPipeBeam',
         'Electricity', True, True),
        ('to_CoilHeatingLowTempRadiantConstFlow',
         'CoilHeatingLowTempRadiantConstFlow', 'Electricity', True, True),
        ('to_CoilHeatingLowTempRadiantVarFlow',
         'CoilHeatingLowTempRadiantVarFlow', 'Electricity', True, True),
        ('to_CoilHeatingWaterBaseboardRadiant',
         'CoilHeatingWaterBaseboardRadiant', 'Electricity', True, True),
        ('to_CoilHeatingWaterToAirHeatPumpVariableSpeedEquationFit',
         'CoilHeatingWaterToAirHeatPumpVariableSpeedEquationFit',
         'Electricity', True, False),
    )

    def test_each_coil_changes_the_heating_and_election_facts(self):
        import openstudio

        from btap.modeling.hvac import classify

        for caster, class_name, fuel, expected_heat_pump, auxiliary in self.CASES:
            with self.subTest(class_name=class_name):
                model = openstudio.model.Model()
                coil = _heating_coil(model, class_name)
                self.assertIsNotNone(
                    classify._try_cast(coil, caster),
                    'precondition: the fixture is the SDK type under test')
                self.assertIn(
                    caster, [entry[0] for entry in classify.HEATING_COILS])

                plant_by_name = {}
                if caster in classify.HYDRONIC_HEATING_COIL_CASTS:
                    load = _plant(model, 'Air Source Hot Water', 'Heating')
                    plant_heat_pump = (
                        openstudio.model.HeatPumpAirToWaterHeating(model))
                    self.assertTrue(
                        load.addSupplyBranchForComponent(plant_heat_pump))
                    self.assertTrue(
                        load.addDemandBranchForComponent(coil))
                    plant_by_name = {
                        plant['name']: plant
                        for plant in classify.characterize(model)['plants']
                    }

                group = classify._base_group(['Zone'], None)
                self.assertTrue(classify._scan_heating_component(
                    group, coil, plant_by_name, class_name))
                self.assertTrue(group['heated'])
                self.assertIn(fuel, group['heating_energy_types'])
                self.assertEqual(expected_heat_pump, group['heat_pump'])
                if caster in classify.HYDRONIC_HEATING_COIL_CASTS:
                    self.assertEqual(['air'], group['heat_pump_sources'])

                if expected_heat_pump:
                    self.assertTrue(
                        caster in classify.DX_HEATING_CASTS
                        or caster in classify.HYDRONIC_HEATING_COIL_CASTS)
                if auxiliary:
                    self.assertIn(caster, classify.AUX_COIL_FUELS)
                    entry = classify._aux_coil_entry(
                        coil, plant_by_name)
                    self.assertIsNotNone(entry)
                    self.assertEqual(fuel, entry['fuel'])


@needs_sdk
class TestEveryAddedHydronicCoolingCoilIsLoadBearing(unittest.TestCase):
    CASES = (
        ('to_CoilCoolingFourPipeBeam', 'CoilCoolingFourPipeBeam'),
        ('to_CoilCoolingLowTempRadiantConstFlow',
         'CoilCoolingLowTempRadiantConstFlow'),
        ('to_CoilCoolingLowTempRadiantVarFlow',
         'CoilCoolingLowTempRadiantVarFlow'),
        ('to_CoilCoolingWaterPanelRadiant',
         'CoilCoolingWaterPanelRadiant'),
    )

    def test_each_coil_carries_its_absorption_plant_to_the_group(self):
        import openstudio

        from btap.modeling.hvac import classify

        for caster, class_name in self.CASES:
            with self.subTest(class_name=class_name):
                model = openstudio.model.Model()
                coil = _cooling_coil(model, class_name)
                self.assertIsNotNone(
                    classify._try_cast(coil, caster),
                    'precondition: the fixture is the SDK type under test')
                self.assertIn(caster, classify.HYDRONIC_COOLING_COILS)

                chilled = _absorption_plant(model)
                self.assertTrue(
                    chilled.addDemandBranchForComponent(coil))
                plant_by_name = {
                    plant['name']: plant
                    for plant in classify.characterize(model)['plants']
                }

                group = classify._base_group(['Zone'], None)
                self.assertTrue(classify._scan_cooling_component(
                    group, coil, plant_by_name, class_name))
                self.assertTrue(group['cooled'])
                self.assertEqual(
                    ['NaturalGas'], group['cooling_energy_types'])
                self.assertEqual(
                    ['Chilled Water'], group['cooling_plants'],
                    'the hydronic cast is the only route from this child '
                    'coil to its serving absorption plant')


@needs_sdk
class TestEveryAddedZonalTypeIsLoadBearing(unittest.TestCase):
    CASES = (
        ('to_ZoneHVACBaseboardRadiantConvectiveElectric',
         'ZoneHVACBaseboardRadiantConvectiveElectric',
         'baseboard', True, False, 'Electricity'),
        ('to_ZoneHVACBaseboardRadiantConvectiveWater',
         'ZoneHVACBaseboardRadiantConvectiveWater',
         'baseboard', True, False, 'Unknown'),
        ('to_ZoneHVACCoolingPanelRadiantConvectiveWater',
         'ZoneHVACCoolingPanelRadiantConvectiveWater',
         'radiant', False, True, 'Unknown'),
        ('to_ZoneHVACLowTempRadiantConstFlow',
         'ZoneHVACLowTempRadiantConstFlow',
         'radiant', True, True, 'Unknown'),
        ('to_ZoneHVACLowTempRadiantVarFlow',
         'ZoneHVACLowTempRadiantVarFlow',
         'radiant', True, True, 'Unknown'),
        ('to_ZoneHVACUnitVentilator', 'ZoneHVACUnitVentilator',
         'unit_ventilator', True, True, 'Electricity'),
        ('to_ZoneHVACEvaporativeCoolerUnit',
         'ZoneHVACEvaporativeCoolerUnit',
         'evap_cooler', False, True, 'Electricity'),
    )

    def test_each_zonal_type_conditions_the_zone(self):
        import openstudio

        from btap.modeling.hvac import classify

        for caster, class_name, kind, heated, cooled, fuel in self.CASES:
            with self.subTest(class_name=class_name):
                model = openstudio.model.Model()
                zone = openstudio.model.ThermalZone(model)
                unit = _zonal_equipment(model, class_name)
                self.assertIsNotNone(
                    classify._try_cast(unit, caster),
                    'precondition: the fixture is the SDK type under test')
                self.assertTrue(unit.addToThermalZone(zone))
                matching = [
                    equipment for equipment in zone.equipment()
                    if classify._try_cast(equipment, caster) is not None
                ]
                self.assertEqual(
                    [unit.handle()], [equipment.handle()
                                     for equipment in matching])

                group = classify.characterize(model)['zone_groups'][0]
                self.assertIn(kind, group['zonal_units'])
                self.assertEqual(heated, group['heated'])
                self.assertEqual(cooled, group['cooled'])
                fuels = (group['heating_energy_types'] if heated
                         else group['cooling_energy_types'])
                self.assertIn(fuel, fuels)

                if class_name.startswith(
                        'ZoneHVACBaseboardRadiantConvective'):
                    election = classify._zonal_heating_entries(unit, {})
                    self.assertEqual(1, len(election))
                    self.assertEqual(fuel, election[0]['fuel'])
                    self.assertEqual(
                        classify.BASEBOARD_VARIABLE,
                        election[0]['variable'])

                if class_name in (
                        'ZoneHVACLowTempRadiantConstFlow',
                        'ZoneHVACLowTempRadiantVarFlow',
                        'ZoneHVACUnitVentilator'):
                    registered = [
                        entry[0] for entry in classify.ZONAL_HEATING_UNITS]
                    self.assertIn(caster, registered)
                    self.assertTrue(classify._zonal_heating_coils(unit))


@needs_sdk
class TestEveryAddedTerminalTypeIsLoadBearing(unittest.TestCase):
    CASES = (
        ('to_AirTerminalDualDuctConstantVolume',
         'AirTerminalDualDuctConstantVolume',
         'dual_duct_cv', False, False),
        ('to_AirTerminalDualDuctVAVOutdoorAir',
         'AirTerminalDualDuctVAVOutdoorAir',
         'dual_duct_vav_outdoor_air', False, False),
        ('to_AirTerminalSingleDuctConstantVolumeFourPipeBeam',
         'AirTerminalSingleDuctConstantVolumeFourPipeBeam',
         'four_pipe_beam', True, True),
        ('to_AirTerminalSingleDuctConstantVolumeFourPipeInduction',
         'AirTerminalSingleDuctConstantVolumeFourPipeInduction',
         'four_pipe_induction', True, True),
        ('to_AirTerminalSingleDuctParallelPIUReheat',
         'AirTerminalSingleDuctParallelPIUReheat',
         'parallel_piu_reheat', True, False),
        ('to_AirTerminalSingleDuctSeriesPIUReheat',
         'AirTerminalSingleDuctSeriesPIUReheat',
         'series_piu_reheat', True, False),
        ('to_AirTerminalSingleDuctInletSideMixer',
         'AirTerminalSingleDuctInletSideMixer',
         'inlet_side_mixer', False, False),
        ('to_AirTerminalSingleDuctVAVHeatAndCoolNoReheat',
         'AirTerminalSingleDuctVAVHeatAndCoolNoReheat',
         'vav_heat_cool', False, False),
        ('to_AirTerminalSingleDuctVAVHeatAndCoolReheat',
         'AirTerminalSingleDuctVAVHeatAndCoolReheat',
         'vav_heat_cool_reheat', True, False),
    )

    def test_each_terminal_changes_the_air_side_facts(self):
        import openstudio

        from btap.modeling.hvac import classify

        for caster, class_name, kind, heated, cooled in self.CASES:
            with self.subTest(class_name=class_name):
                model = openstudio.model.Model()
                terminal = _terminal(model, class_name)
                self.assertIsNotNone(
                    classify._try_cast(terminal, caster),
                    'precondition: the fixture is the SDK type under test')
                group = classify._base_group(['Zone'], 'Air Loop')

                self.assertTrue(classify._terminal_facts(
                    group, terminal, {}))
                self.assertEqual(kind, group['terminal_type'])
                self.assertEqual(heated, group['heated'])
                self.assertEqual(cooled, group['cooled'])
                if kind in ('four_pipe_beam', 'four_pipe_induction'):
                    self.assertEqual(
                        'chilled_beam',
                        classify._structural_family_guess(group))

                if heated:
                    registered = [
                        entry[0] for entry in classify.ZONAL_HEATING_UNITS]
                    self.assertIn(caster, registered)
                    self.assertTrue(classify._zonal_heating_coils(terminal))


@needs_sdk
class TestEveryAddedPlantHeatPumpIsLoadBearing(unittest.TestCase):
    CASES = (
        ('to_HeatPumpAirToWaterHeating', 'HeatPumpAirToWaterHeating',
         'Heating', 'hot_water', 'Electricity'),
        ('to_HeatPumpAirToWaterCooling', 'HeatPumpAirToWaterCooling',
         'Cooling', 'chilled_water', 'Electricity'),
        ('to_HeatPumpAirToWaterFuelFiredHeating',
         'HeatPumpAirToWaterFuelFiredHeating',
         'Heating', 'hot_water', 'Propane'),
        ('to_HeatPumpAirToWaterFuelFiredCooling',
         'HeatPumpAirToWaterFuelFiredCooling',
         'Cooling', 'chilled_water', 'Propane'),
    )

    def test_air_to_water_modes_keep_their_side_source_and_fuel(self):
        import openstudio

        from btap.modeling.hvac import classify

        for caster, class_name, loop_type, expected_type, fuel in self.CASES:
            with self.subTest(class_name=class_name):
                model = openstudio.model.Model()
                loop = _plant(model, 'Load', loop_type)
                unit = getattr(openstudio.model, class_name)(model)
                if 'FuelFired' in class_name:
                    self.assertTrue(unit.setFuelType(fuel))
                self.assertTrue(loop.addSupplyBranchForComponent(unit))
                self.assertIsNotNone(
                    classify._try_cast(unit, caster),
                    'precondition: the fixture is the SDK type under test')
                self.assertIn(caster, classify.PLANT_HP_CASTS)

                facts = classify.characterize(model)['plants'][0]
                self.assertEqual(expected_type, facts['type'])
                self.assertEqual([fuel], facts['fuels'])
                self.assertTrue(facts['heat_pump'])
                self.assertEqual('air', facts['hp_source'])

    def test_unconnected_water_to_water_cooling_has_no_source_evidence(self):
        import openstudio

        from btap.modeling.hvac import classify

        model = openstudio.model.Model()
        loop = _plant(model, 'Chilled Water', 'Cooling')
        unit = openstudio.model.HeatPumpWaterToWaterEquationFitCooling(model)
        self.assertTrue(loop.addSupplyBranchForComponent(unit))
        caster = 'to_HeatPumpWaterToWaterEquationFitCooling'
        self.assertIsNotNone(classify._try_cast(unit, caster))
        self.assertIn(caster, classify.PLANT_HP_CASTS)

        facts = classify.characterize(model)['plants'][0]
        self.assertEqual('chilled_water', facts['type'])
        self.assertEqual(['cooling'], facts['heat_pump_modes'])
        self.assertIsNone(
            facts['hp_source'],
            'the type alone cannot establish water-loop versus external '
            'water-source service; D-37 keeps this source unclassified')

    def test_an_unpaired_cooling_side_is_recorded_separately(self):
        import openstudio

        from btap.modeling.hvac import classify

        model = openstudio.model.Model()
        loop = _plant(model, 'Chilled Water', 'Cooling')
        unit = openstudio.model.HeatPumpPlantLoopEIRCooling(model)
        unit.setName('Unpaired Cooling HP')
        self.assertTrue(unit.setCondenserType('AirSource'))
        self.assertTrue(loop.addSupplyBranchForComponent(unit))
        self.assertFalse(unit.companionHeatingHeatPump().is_initialized())

        facts = classify.characterize(model)['plants'][0]
        self.assertEqual([], facts['resolved_heat_pumps'])
        self.assertEqual(
            ['Unpaired Cooling HP'],
            facts['unpaired_cooling_heat_pumps'])
        self.assertEqual(
            [{'name': 'Unpaired Cooling HP', 'mode': 'cooling',
              'resolved': False, 'source': 'air', 'source_loop': None}],
            facts['heat_pump_contributors'])

    def test_a_heating_companion_establishes_the_other_side(self):
        import openstudio

        from btap.modeling.hvac import classify

        model = openstudio.model.Model()
        chilled = _plant(model, 'Chilled Water', 'Cooling')
        hot = _plant(model, 'Heat Pump Hot Water', 'Heating')
        cooling = openstudio.model.HeatPumpPlantLoopEIRCooling(model)
        cooling.setName('Paired Cooling HP')
        heating = openstudio.model.HeatPumpPlantLoopEIRHeating(model)
        self.assertTrue(cooling.setCondenserType('AirSource'))
        self.assertTrue(heating.setCondenserType('AirSource'))
        self.assertTrue(chilled.addSupplyBranchForComponent(cooling))
        self.assertTrue(hot.addSupplyBranchForComponent(heating))
        self.assertTrue(cooling.setCompanionHeatingHeatPump(heating))
        self.assertTrue(cooling.companionHeatingHeatPump().is_initialized())

        plants = {
            plant['name']: plant
            for plant in classify.characterize(model)['plants']
        }
        facts = plants['Chilled Water']
        self.assertEqual(['Paired Cooling HP'], facts['resolved_heat_pumps'])
        self.assertEqual([], facts['unpaired_cooling_heat_pumps'])
        self.assertEqual(
            [{'name': 'Paired Cooling HP', 'mode': 'cooling',
              'resolved': True, 'source': 'air', 'source_loop': None}],
            facts['heat_pump_contributors'])

    def test_central_heat_pump_marks_both_load_sides(self):
        import openstudio

        from btap.modeling.hvac import classify

        model = openstudio.model.Model()
        cooling = _plant(model, 'Cooling', 'Cooling')
        heating = _plant(model, 'Heating', 'Heating')
        source = _plant(model, 'Source', 'Condenser')
        unit = openstudio.model.CentralHeatPumpSystem(model)
        self.assertTrue(cooling.addSupplyBranchForComponent(unit))
        self.assertTrue(source.addDemandBranchForComponent(unit))
        self.assertTrue(unit.addToTertiaryNode(heating.supplyInletNode()))
        caster = 'to_CentralHeatPumpSystem'
        self.assertIsNotNone(classify._try_cast(unit, caster))
        self.assertIn(caster, classify.PLANT_HP_CASTS)

        plants = {
            plant['name']: plant
            for plant in classify.characterize(model)['plants']
        }
        self.assertEqual('chilled_water', plants['Cooling']['type'])
        self.assertEqual('hot_water', plants['Heating']['type'])
        self.assertTrue(plants['Cooling']['heat_pump'])
        self.assertTrue(plants['Heating']['heat_pump'])
        self.assertEqual('water_loop', plants['Cooling']['hp_source'])
        self.assertEqual('water_loop', plants['Heating']['hp_source'])

    def test_air_to_water_plant_reaches_the_served_zone(self):
        import openstudio

        from btap.modeling.hvac import classify

        model = openstudio.model.Model()
        zone = openstudio.model.ThermalZone(model)
        loop = _plant(model, 'Air Source Hot Water', 'Heating')
        heat_pump = openstudio.model.HeatPumpAirToWaterHeating(model)
        baseboard = (
            openstudio.model.ZoneHVACBaseboardRadiantConvectiveWater(model))
        self.assertTrue(loop.addSupplyBranchForComponent(heat_pump))
        self.assertTrue(loop.addDemandBranchForComponent(
            baseboard.heatingCoil()))
        self.assertTrue(baseboard.addToThermalZone(zone))

        group = classify.characterize(model)['zone_groups'][0]
        self.assertTrue(group['heated'])
        self.assertTrue(group['heat_pump'])
        self.assertEqual(['air'], group['heat_pump_sources'])


@needs_sdk
class TestChillerIdentityIsNotCollapsed(unittest.TestCase):
    def test_absorption_chillers_keep_generator_fuel(self):
        import openstudio

        from btap.modeling.hvac import classify

        for class_name, expected in (
                ('ChillerAbsorption', 'absorption'),
                ('ChillerAbsorptionIndirect', 'absorption_indirect')):
            with self.subTest(class_name=class_name):
                model = openstudio.model.Model()
                chilled = _plant(model, 'Chilled Water', 'Cooling')
                condenser = _plant(model, 'Condenser', 'Condenser')
                generator = _plant(model, 'Generator', 'Heating')
                boiler = openstudio.model.BoilerHotWater(model)
                self.assertTrue(boiler.setFuelType('NaturalGas'))
                self.assertTrue(
                    generator.addSupplyBranchForComponent(boiler))
                chiller = getattr(openstudio.model, class_name)(model)
                self.assertTrue(
                    chilled.addSupplyBranchForComponent(chiller))
                self.assertTrue(
                    condenser.addDemandBranchForComponent(chiller))
                self.assertTrue(chiller.addToTertiaryNode(
                    generator.demandInletNode()))
                self.assertTrue(chiller.generatorLoop().is_initialized())

                plant = next(
                    plant for plant in classify.characterize(model)['plants']
                    if plant['name'] == 'Chilled Water')
                self.assertEqual([expected], plant['chiller_types'])
                self.assertEqual(['NaturalGas'], plant['fuels'])

    def test_reformulated_eir_is_recognized_as_electric(self):
        import openstudio

        from btap.modeling.hvac import classify

        model = openstudio.model.Model()
        chilled = _plant(model, 'Chilled Water', 'Cooling')
        chiller = openstudio.model.ChillerElectricReformulatedEIR(model)
        self.assertTrue(chilled.addSupplyBranchForComponent(chiller))
        plant = classify.characterize(model)['plants'][0]
        self.assertEqual(['electric_reformulated_eir'],
                         plant['chiller_types'])
        self.assertEqual(['Electricity'], plant['fuels'])

    def test_ashrae205_is_recognized_as_electric(self):
        import openstudio

        from btap.modeling.hvac import classify

        model = openstudio.model.Model()
        chilled = _plant(model, 'Chilled Water', 'Cooling')
        with tempfile.NamedTemporaryFile(suffix='.cbor') as representation:
            representation.write(b'\xa0')
            representation.flush()
            external = openstudio.model.ExternalFile.getExternalFile(
                model, representation.name, False)
            self.assertTrue(external.is_initialized(),
                            'precondition: the CBOR is attached to the model')
            chiller = openstudio.model.ChillerElectricASHRAE205(
                external.get())
            self.assertTrue(chilled.addSupplyBranchForComponent(chiller))
            plant = classify.characterize(model)['plants'][0]

        self.assertEqual(['electric_ashrae205'], plant['chiller_types'])
        self.assertEqual(['Electricity'], plant['fuels'])


@needs_sdk
class TestDeliberateExclusionsStayExplicit(unittest.TestCase):
    def test_uncontrolled_terminal_alias_uses_the_canonical_cv_entry(self):
        import openstudio

        from btap.modeling.hvac import classify

        self.assertIs(
            openstudio.model.AirTerminalSingleDuctUncontrolled,
            openstudio.model.AirTerminalSingleDuctConstantVolumeNoReheat,
            'the deprecated name is an alias, not a separate concrete type')
        model = openstudio.model.Model()
        terminal = openstudio.model.AirTerminalSingleDuctUncontrolled(
            model, _schedule(model))
        self.assertIsNotNone(classify._try_cast(
            terminal,
            'to_AirTerminalSingleDuctConstantVolumeNoReheat'))
        group = classify._base_group(['Zone'], 'Air Loop')
        self.assertTrue(classify._terminal_facts(group, terminal, {}))
        self.assertEqual('cv', group['terminal_type'])

    def test_ventilation_diagnostics_and_dehumidification_are_not_systems(self):
        import openstudio

        from btap.modeling.hvac import classify

        for caster, class_name in (
                ('to_ZoneHVACIdealLoadsAirSystem',
                 'ZoneHVACIdealLoadsAirSystem'),
                ('to_ZoneHVACDehumidifierDX',
                 'ZoneHVACDehumidifierDX'),
                ('to_ZoneHVACEnergyRecoveryVentilator',
                 'ZoneHVACEnergyRecoveryVentilator')):
            with self.subTest(class_name=class_name):
                model = openstudio.model.Model()
                zone = openstudio.model.ThermalZone(model)
                unit = getattr(openstudio.model, class_name)(model)
                self.assertIsNotNone(
                    classify._try_cast(unit, caster),
                    'precondition: the omitted SDK type is present')
                self.assertTrue(unit.addToThermalZone(zone))
                self.assertNotIn(
                    caster, [entry[0] for entry in classify.ZONAL])

                group = classify.characterize(model)['zone_groups'][0]
                self.assertFalse(group['heated'])
                self.assertFalse(group['cooled'])


@needs_sdk
class TestTheHydronicCoolingCapacityKindsAreBOTHExercised(unittest.TestCase):
    """`HYDRONIC_COOLING_COILS` records a capacity KIND per cast, and nothing
    tested the `design_capacity` kind at all.

    Found while closing #176 item 2. Breaking that branch — in the shared
    extractor, or in either of the two copies it replaced — left every test in
    the inventory and plant-heat-pump modules green, so the refactor that
    merged the copies could not be shown to preserve anything.

    The precise claim, because the loose one is wrong: three base-tree test
    files DO construct `PanelRadiant` and `LowTempRadiantVarFlow` coils, and
    `test_chilled_beams.py:175` asserts `IsNone` for a beam. What none of them
    did is assert a capacity VALUE arrived through the registry's kind, which
    is the step a typo in a kind string would break (Fable, follow-up on
    #179).

    `autosized_load` has coverage through the four-pipe fan coil fixtures;
    `design_capacity` had none, and it is the kind that reads a DECLARED
    capacity rather than a sizing result, so it is the one that works without
    a simulation.
    """

    def test_a_declared_panel_radiant_capacity_reaches_design_cooling_kw(self):
        import openstudio

        from btap.modeling.hvac import classify

        model = openstudio.model.Model()
        zone = openstudio.model.ThermalZone(model)
        zone.setName('Zone')
        panel = (openstudio.model
                 .ZoneHVACCoolingPanelRadiantConvectiveWater(model))
        coil = panel.coolingCoil().to_CoilCoolingWaterPanelRadiant().get()
        self.assertTrue(coil.setCoolingDesignCapacityMethod('CoolingDesignCapacity'))
        self.assertTrue(coil.setCoolingDesignCapacity(8000.0))
        chilled = openstudio.model.PlantLoop(model)
        chilled.setName('Chilled Water')
        chilled.sizingPlant().setLoopType('Cooling')
        self.assertTrue(chilled.addDemandBranchForComponent(coil))
        self.assertTrue(panel.addToThermalZone(zone))

        group = classify.characterize(model)['zone_groups'][0]
        # Before the near-equality, because `assertAlmostEqual(8.0, None)`
        # raises `TypeError: unsupported operand type(s) for -` and the message
        # below never prints — so both mutations went red for the wrong reason
        # and a reader saw an arithmetic error instead of the claim (Fable,
        # follow-up on #179).
        self.assertIsNotNone(
            group['design_cooling_kw'],
            "the registry's `design_capacity` kind produced no capacity at "
            'all; the coil was recognised and its declared value dropped')
        self.assertAlmostEqual(
            8.0, group['design_cooling_kw'], places=6,
            msg="the registry's `design_capacity` kind must reach the zonal "
                'capacity total — 8000 W declared is 8 kW')
        self.assertTrue(
            group.get('cooling_capacity_complete', True),
            'a coil whose capacity IS readable must not mark the group '
            'incomplete')

    def test_the_kinds_the_registry_declares_are_the_ones_it_handles(self):
        """Every kind in the registry must be one the extractor implements.

        A typo in a kind string would otherwise fall through to None and
        silently drop that coil's capacity, which is the same silent-skip
        shape as an unmatched space type.
        """
        from btap.modeling.hvac import classify

        self.assertEqual(
            {None, 'autosized_load', 'design_capacity'},
            set(classify.HYDRONIC_COOLING_COILS.values()),
            'an unimplemented capacity kind drops the coil silently')


if __name__ == '__main__':
    unittest.main()
