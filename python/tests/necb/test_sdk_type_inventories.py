import tempfile
import unittest
from types import SimpleNamespace

from tests.support import needs_sdk


def _plant(model, name, loop_type):
    import openstudio

    loop = openstudio.model.PlantLoop(model)
    loop.setName(name)
    loop.sizingPlant().setLoopType(loop_type)
    return loop


def _select(facts):
    from btap.codes.necb import hvac

    zones = {
        zone
        for group in facts['zone_groups']
        for zone in group['zones']
    }
    return list(hvac.select_reference_systems(
        facts=facts,
        building={
            'storeys': 1,
            'zone_types': {zone: 'Hotel/Motel' for zone in zones},
        },
        code='necb2020'))


@needs_sdk
class TestNewTerminalFactsReachReferenceSelection(unittest.TestCase):
    def test_each_terminal_blocks_the_bare_dx_unitary_inference(self):
        import openstudio

        from btap.codes.necb.hvac import reference
        from btap.modeling.hvac import classify
        from tests.modeling.test_sdk_type_inventories import (
            TestEveryAddedTerminalTypeIsLoadBearing,
            _terminal,
        )

        for caster, class_name, kind, _heated, _cooled in (
                TestEveryAddedTerminalTypeIsLoadBearing.CASES):
            with self.subTest(class_name=class_name):
                model = openstudio.model.Model()
                terminal = _terminal(model, class_name)
                self.assertIsNotNone(
                    classify._try_cast(terminal, caster),
                    'precondition: the fixture is the SDK type under test')
                group = classify._base_group(['Zone'], 'Air Loop')
                group.update({'heated': True, 'cooled': True,
                              'loop_dx_cooling': True})
                self.assertTrue(classify._terminal_facts(
                    group, terminal, {}))
                self.assertEqual(kind, group['terminal_type'])

                self.assertIsNone(
                    reference._residential_cooling_route(group),
                    'a non-qualifying central terminal must take the '
                    'through-the-wall branch, not bare-DX copy_proposed')


@needs_sdk
class TestNewZonalFactsReachReferenceSelection(unittest.TestCase):
    def test_radiant_unit_ventilator_and_evaporative_units_are_not_copied(self):
        import openstudio

        from btap.modeling.hvac import classify
        from tests.modeling.test_sdk_type_inventories import (
            TestEveryAddedZonalTypeIsLoadBearing,
            _zonal_equipment,
        )

        for caster, class_name, _kind, _heated, cooled, _fuel in (
                TestEveryAddedZonalTypeIsLoadBearing.CASES):
            with self.subTest(class_name=class_name):
                model = openstudio.model.Model()
                zone = openstudio.model.ThermalZone(model)
                zone.setName('Zone')
                unit = _zonal_equipment(model, class_name)
                self.assertIsNotNone(classify._try_cast(unit, caster))
                self.assertTrue(unit.addToThermalZone(zone))
                if cooled and not class_name == 'ZoneHVACUnitVentilator':
                    baseboard = (
                        openstudio.model
                        .ZoneHVACBaseboardRadiantConvectiveElectric(model))
                    self.assertTrue(baseboard.addToThermalZone(zone))

                facts = classify.characterize(model)
                group = facts['zone_groups'][0]
                self.assertTrue(group['heated'],
                                'precondition: Table -A sees a heated block')
                assignments = _select(facts)
                self.assertEqual(1, len(assignments))
                self.assertEqual(
                    'through_the_wall' if cooled else 'build',
                    assignments[0].action,
                    'radiant, unit-ventilator and evaporative equipment are '
                    'conditioning facts, not identities on the residential '
                    'copy_proposed closed list')


@needs_sdk
class TestAirToWaterFactsReachTheArticle13Redirect(unittest.TestCase):
    CASES = (
        ('HeatPumpAirToWaterHeating', 'Heating', 'Electricity'),
        ('HeatPumpAirToWaterCooling', 'Cooling', 'Electricity'),
        ('HeatPumpAirToWaterFuelFiredHeating', 'Heating', 'Propane'),
        ('HeatPumpAirToWaterFuelFiredCooling', 'Cooling', 'Propane'),
    )

    def test_each_air_to_water_mode_selects_the_air_source_reference(self):
        import openstudio

        from btap.modeling.hvac import classify

        for class_name, loop_type, fuel in self.CASES:
            with self.subTest(class_name=class_name):
                model = openstudio.model.Model()
                zone = openstudio.model.ThermalZone(model)
                zone.setName('Zone')
                loop = _plant(model, 'Load Plant', loop_type)
                heat_pump = getattr(openstudio.model, class_name)(model)
                if 'FuelFired' in class_name:
                    self.assertTrue(heat_pump.setFuelType(fuel))
                self.assertTrue(
                    loop.addSupplyBranchForComponent(heat_pump))

                if loop_type == 'Heating':
                    terminal = (
                        openstudio.model
                        .ZoneHVACBaseboardRadiantConvectiveWater(model))
                    self.assertTrue(loop.addDemandBranchForComponent(
                        terminal.heatingCoil()))
                else:
                    terminal = (
                        openstudio.model
                        .ZoneHVACCoolingPanelRadiantConvectiveWater(model))
                    self.assertTrue(loop.addDemandBranchForComponent(
                        terminal.coolingCoil()))
                    baseboard = (
                        openstudio.model
                        .ZoneHVACBaseboardRadiantConvectiveElectric(model))
                    self.assertTrue(baseboard.addToThermalZone(zone))
                self.assertTrue(terminal.addToThermalZone(zone))

                facts = classify.characterize(model)
                group = facts['zone_groups'][0]
                plant = next(
                    plant for plant in facts['plants']
                    if plant['name'] == 'Load Plant')
                self.assertEqual([fuel], plant['fuels'])
                self.assertTrue(group['heat_pump'])
                self.assertEqual(['air'], group['heat_pump_sources'])

                assignments = _select(facts)
                self.assertEqual(1, len(assignments))
                self.assertEqual(
                    'hp', assignments[0].reference_system,
                    '8.4.4.13.(2)(a) redirects air-source plant heat pumps')


@needs_sdk
class TestUnclassifiedPlantHeatPumpSourceRedirects(unittest.TestCase):
    def test_water_to_water_type_without_a_source_loop_does_not_imply_wlhp(self):
        import openstudio

        from btap.modeling.hvac import classify

        model = openstudio.model.Model()
        zone = openstudio.model.ThermalZone(model)
        zone.setName('Zone')
        chilled = _plant(model, 'Chilled Water', 'Cooling')
        heat_pump = (
            openstudio.model.HeatPumpWaterToWaterEquationFitCooling(model))
        panel = (
            openstudio.model
            .ZoneHVACCoolingPanelRadiantConvectiveWater(model))
        baseboard = (
            openstudio.model
            .ZoneHVACBaseboardRadiantConvectiveElectric(model))
        self.assertTrue(
            chilled.addSupplyBranchForComponent(heat_pump))
        self.assertTrue(
            chilled.addDemandBranchForComponent(panel.coolingCoil()))
        self.assertTrue(panel.addToThermalZone(zone))
        self.assertTrue(baseboard.addToThermalZone(zone))

        facts = classify.characterize(model)
        group = facts['zone_groups'][0]
        plant = next(
            plant for plant in facts['plants']
            if plant['name'] == 'Chilled Water')
        self.assertIsNone(
            plant['hp_source'],
            'the type alone cannot distinguish an internal water loop from '
            'an external water source')
        self.assertTrue(group['heat_pump'])
        self.assertEqual(
            [], group['heat_pump_sources'],
            'D-37 represents a missing source fact as missing evidence, not '
            'as a water-loop classification')

        assignments = _select(facts)
        self.assertEqual(1, len(assignments))
        self.assertEqual(
            'hp', assignments[0].reference_system,
            'D-37 conservatively redirects a detected heat pump whose source '
            'cannot be classified')


@needs_sdk
class TestHydronicPumpInventoriesUseTheNewCoils(unittest.TestCase):
    def test_four_pipe_beam_coils_each_contribute_the_served_zone(self):
        import openstudio

        from btap.codes.necb.hvac import efficiency

        model = openstudio.model.Model()
        zone = openstudio.model.ThermalZone(model)
        zone.setName('Beam Zone')
        heating_coil = openstudio.model.CoilHeatingFourPipeBeam(model)
        cooling_coil = openstudio.model.CoilCoolingFourPipeBeam(model)
        terminal = (
            openstudio.model
            .AirTerminalSingleDuctConstantVolumeFourPipeBeam(
                model, cooling_coil, heating_coil))
        air_loop = openstudio.model.AirLoopHVAC(model)
        self.assertTrue(air_loop.addBranchForZone(zone, terminal))
        heating = _plant(model, 'Heating', 'Heating')
        cooling = _plant(model, 'Cooling', 'Cooling')
        self.assertTrue(
            heating.addDemandBranchForComponent(heating_coil))
        self.assertTrue(
            cooling.addDemandBranchForComponent(cooling_coil))

        for caster, loop in (
                ('to_CoilHeatingFourPipeBeam', heating),
                ('to_CoilCoolingFourPipeBeam', cooling)):
            with self.subTest(caster=caster):
                self.assertIn(caster, efficiency.ZONE_SERVING_WATER_COILS)
                self.assertEqual(
                    {'Beam Zone'}, efficiency._served_zone_names(loop),
                    'removing the caster must strand the loop with no served '
                    'thermal block')

    def test_ashrae205_tertiary_waits_for_energyplus_support(self):
        import openstudio

        from btap.codes.necb.hvac import efficiency

        model = openstudio.model.Model()
        chilled = _plant(model, 'Chilled Water', 'Cooling')
        heat_recovery = _plant(model, 'Heat Recovery', 'Heating')
        with tempfile.NamedTemporaryFile(suffix='.cbor') as representation:
            representation.write(b'\xa0')
            representation.flush()
            external = openstudio.model.ExternalFile.getExternalFile(
                model, representation.name, False)
            self.assertTrue(external.is_initialized())
            chiller = openstudio.model.ChillerElectricASHRAE205(
                external.get())
            self.assertTrue(
                chilled.addSupplyBranchForComponent(chiller))
            self.assertFalse(
                chiller.addToTertiaryNode(
                    heat_recovery.demandInletNode()),
                'precondition: SDK 3.11 refuses the unsupported connection')
            self.assertFalse(chiller.heatRecoveryLoop().is_initialized())

            caster = 'to_ChillerElectricASHRAE205'
            self.assertTrue(getattr(chiller, caster)().is_initialized())
            self.assertIn(caster, efficiency.TERTIARY_LOAD_CASTS)
            self.assertFalse(
                chiller.isHeatRecoverySupportedByEnergyplus,
                'precondition: SDK 3.11 cannot translate this connection')
            self.assertEqual(
                (chilled,), efficiency._load_loops(chiller),
                'the primary load loop counts, but type identity must not '
                'invent an unsupported heat-recovery load loop')

    def test_chiller_heater_performance_is_not_treated_as_equipment(self):
        import openstudio

        from btap.codes.necb.hvac import efficiency
        from btap.modeling.hvac import classify

        model = openstudio.model.Model()
        performance = (
            openstudio.model.ChillerHeaterPerformanceElectricEIR(model))
        caster = 'to_ChillerHeaterPerformanceElectricEIR'
        self.assertTrue(getattr(performance, caster)().is_initialized(),
                        'precondition: the performance object exists')
        self.assertNotIn(caster, classify.ELECTRIC_CHILLER_CASTS)
        self.assertNotIn(caster, classify.ABSORPTION_CHILLER_CASTS)
        self.assertNotIn(caster, efficiency.TERTIARY_LOAD_CASTS)


@needs_sdk
class TestAbsorptionRecognitionWithholdsAnUnsupportedTarget(unittest.TestCase):
    @staticmethod
    def _model(served, model=None):
        import openstudio

        model = model or openstudio.model.Model()
        chilled = _plant(model, 'Chilled Water', 'Cooling')
        condenser = _plant(model, 'Condenser', 'Condenser')
        generator = _plant(model, 'Generator', 'Heating')
        boiler = openstudio.model.BoilerHotWater(model)
        assert boiler.setFuelType('NaturalGas')
        assert generator.addSupplyBranchForComponent(boiler)
        chiller = openstudio.model.ChillerAbsorptionIndirect(model)
        assert chilled.addSupplyBranchForComponent(chiller)
        assert condenser.addDemandBranchForComponent(chiller)
        assert chiller.addToTertiaryNode(generator.demandInletNode())

        if served:
            zones = list(model.getThermalZones())
            zone = zones[0] if zones else openstudio.model.ThermalZone(model)
            if not zones:
                zone.setName('Zone')
            panel = (
                openstudio.model
                .ZoneHVACCoolingPanelRadiantConvectiveWater(model))
            assert chilled.addDemandBranchForComponent(panel.coolingCoil())
            assert panel.addToThermalZone(zone)
        return model

    @classmethod
    def _facts(cls, served):
        from btap.modeling.hvac import classify

        model = cls._model(served)
        return classify.characterize(model)

    def test_only_a_serving_absorption_plant_is_a_target_limitation(self):
        from btap.codes.necb.hvac import reference

        served = reference._reference_target_limitations(
            self._facts(served=True))
        orphan = reference._reference_target_limitations(
            self._facts(served=False))
        self.assertEqual(
            ['absorption_chiller_reference_not_supported'],
            [cause['reason'] for cause in served])
        self.assertEqual('Chilled Water', served[0]['plants'][0]['plant'])
        self.assertEqual(
            [], orphan,
            'an orphan absorption object does not serve a thermal block and '
            'cannot invalidate its reference target')

    def test_each_new_hydronic_child_coil_keeps_the_refusal_reachable(self):
        import openstudio

        from btap.codes.necb.hvac import reference
        from btap.modeling.hvac import classify
        from tests.modeling.test_sdk_type_inventories import (
            _absorption_plant,
            _terminal,
            _zonal_equipment,
        )

        cases = (
            ('to_CoilCoolingFourPipeBeam',
             'AirTerminalSingleDuctConstantVolumeFourPipeBeam'),
            ('to_CoilCoolingLowTempRadiantConstFlow',
             'ZoneHVACLowTempRadiantConstFlow'),
            ('to_CoilCoolingLowTempRadiantVarFlow',
             'ZoneHVACLowTempRadiantVarFlow'),
            ('to_CoilCoolingWaterPanelRadiant',
             'ZoneHVACCoolingPanelRadiantConvectiveWater'),
        )
        for caster, class_name in cases:
            with self.subTest(class_name=class_name):
                model = openstudio.model.Model()
                zone = openstudio.model.ThermalZone(model)
                zone.setName('Zone')
                if class_name.startswith('AirTerminal'):
                    unit = _terminal(model, class_name)
                    air_loop = openstudio.model.AirLoopHVAC(model)
                    self.assertTrue(
                        air_loop.addBranchForZone(zone, unit))
                else:
                    unit = _zonal_equipment(model, class_name)
                    self.assertTrue(unit.addToThermalZone(zone))

                coil = classify._zonal_child_coil(unit, 'cool')
                self.assertIsNotNone(
                    classify._try_cast(coil, caster),
                    'precondition: this parent carries the exact hydronic '
                    'child type under test')
                chilled = _absorption_plant(model)
                self.assertTrue(
                    chilled.addDemandBranchForComponent(coil))

                facts = classify.characterize(model)
                group = facts['zone_groups'][0]
                self.assertEqual(
                    ['Chilled Water'], group['cooling_plants'],
                    'the child cast is the only route to the serving plant')
                limitations = reference._reference_target_limitations(facts)
                self.assertEqual(
                    ['absorption_chiller_reference_not_supported'],
                    [cause['reason'] for cause in limitations],
                    'dropping this cast must not bypass the absorption '
                    'no-determination gate')

    def test_the_performance_path_carries_the_limitation_to_the_verdict(self):
        from btap.codes import compliance
        from tests.necb.hvac_helpers import load_fixture

        model = self._model(served=True, model=load_fixture())
        zone_types = {
            zone.nameString(): 'Hotel/Motel'
            for zone in model.getThermalZones()
        }
        with tempfile.TemporaryDirectory(prefix='absorption-target-') as run_dir:
            result = compliance.performance_compliance(
                model, code='necb2020', simulate='none', hdd=4000,
                building={'storeys': 1, 'zone_types': zone_types},
                run_dir=run_dir)

        self.assertIsNone(result.compliant)
        self.assertEqual(
            'no_determination',
            result.report['compliance_determination'])
        self.assertEqual(
            'absorption_chiller_reference_not_supported',
            result.report['no_determination']['detail']['reason'])

    def test_the_limitation_produces_per_edition_no_determination(self):
        from btap.audit import AuditLog
        from btap.codes.necb import path
        from btap.codes.necb.hvac import reference

        limitations = reference._reference_target_limitations(
            self._facts(served=True))
        expected = {
            'necb2020': '8.4.4.10.(6)(f)',
            'necb2025': '8.4.5.10.(6)(f)',
        }
        for code, article in expected.items():
            with self.subTest(code=code):
                run = SimpleNamespace(
                    state={}, compliant=True,
                    report={'compliance_determination': 'pass'},
                    audit=AuditLog())
                path._record_reference_limitations(run, limitations)
                path._refuse_determination(
                    run, run.state['target_not_established'], code)

                self.assertIsNone(run.compliant)
                self.assertEqual(
                    'no_determination',
                    run.report['compliance_determination'])
                block = run.report['no_determination']
                self.assertEqual(article, block['article'])
                self.assertNotIn(
                    'ruling', block,
                    'this is an acknowledged implementation gap, not an '
                    'adjudicated reinterpretation of the Code')
                self.assertEqual('AHJ-24', block['ahj'])
                self.assertIn('absorption', block['reason'])
                self.assertEqual(article, run.audit.entries[-1]['article'])
                self.assertEqual('AHJ-24', run.audit.entries[-1]['ahj'])


if __name__ == '__main__':
    unittest.main()
