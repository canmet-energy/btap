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
         'Unknown', False, True),
        ('to_CoilHeatingLowTempRadiantConstFlow',
         'CoilHeatingLowTempRadiantConstFlow', 'Unknown', False, True),
        ('to_CoilHeatingLowTempRadiantVarFlow',
         'CoilHeatingLowTempRadiantVarFlow', 'Unknown', False, True),
        ('to_CoilHeatingWaterBaseboardRadiant',
         'CoilHeatingWaterBaseboardRadiant', 'Unknown', False, True),
        ('to_CoilHeatingWaterToAirHeatPumpVariableSpeedEquationFit',
         'CoilHeatingWaterToAirHeatPumpVariableSpeedEquationFit',
         'Electricity', True, False),
    )

    def test_each_coil_changes_the_heating_and_election_facts(self):
        import openstudio

        from btap.modeling.hvac import classify

        for caster, class_name, fuel, heat_pump, auxiliary in self.CASES:
            with self.subTest(class_name=class_name):
                model = openstudio.model.Model()
                coil = _heating_coil(model, class_name)
                self.assertIsNotNone(
                    classify._try_cast(coil, caster),
                    'precondition: the fixture is the SDK type under test')
                self.assertIn(
                    caster, [entry[0] for entry in classify.HEATING_COILS])

                group = classify._base_group(['Zone'], None)
                self.assertTrue(classify._scan_heating_component(
                    group, coil, {}, class_name))
                self.assertTrue(group['heated'])
                self.assertIn(fuel, group['heating_energy_types'])
                self.assertEqual(heat_pump, group['heat_pump'])

                if heat_pump:
                    self.assertIn(caster, classify.DX_HEATING_CASTS)
                if auxiliary:
                    self.assertIn(caster, classify.AUX_COIL_FUELS)
                    self.assertIsNotNone(
                        classify._aux_coil_entry(coil, {}))


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

    def test_water_to_water_cooling_is_not_mislabeled_hot_water(self):
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
        self.assertEqual('water_loop', facts['hp_source'])

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


if __name__ == '__main__':
    unittest.main()
