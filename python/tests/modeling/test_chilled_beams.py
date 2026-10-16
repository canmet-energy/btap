import unittest

import btap.modeling as modeling
from tests.support import load_fixture, needs_sdk

ACTIVE = 'DOAS with active chilled beams and electric baseboards'
PASSIVE = 'DOAS with passive chilled beams and electric baseboards'
REPLACEMENT = 'PSZ RTU Electric and DX Coils and Electric Baseboard'


@needs_sdk
class TestChilledBeams(unittest.TestCase):
    def fixture(self, limit=None):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        return model, zones if limit is None else zones[:limit]

    def test_active_beam_object_graph_and_translation(self):
        import openstudio

        from btap.modeling.hvac import catalog_report
        from btap.modeling.hvac.systems import plant_loops

        model, zones = self.fixture()
        result = modeling.build_system(model, ACTIVE, zones)

        self.assertEqual('chilled_beams', result.family)
        self.assertEqual(1, len(result.air_loops))
        self.assertEqual(len(zones), len(
            model.getAirTerminalSingleDuctConstantVolumeCooledBeams()))
        self.assertEqual(len(zones), len(model.getCoilCoolingCooledBeams()))
        self.assertEqual(
            0, sum(
                obj.iddObjectType().valueName()
                == 'OS_AirTerminal_SingleDuct_Uncontrolled'
                for obj in model.modelObjects()),
            'the cooled-beam terminal is itself the DOAS terminal')
        self.assertTrue(all(
            terminal.cooledBeamType() == 'Active'
            for terminal
            in model.getAirTerminalSingleDuctConstantVolumeCooledBeams()))
        self.assertTrue(all(
            terminal.designInletWaterTemperature() == 15.0
            and terminal.designOutletWaterTemperature() == 18.0
            and terminal.isSupplyAirVolumetricFlowRateAutosized()
            and terminal.isMaximumTotalChilledWaterVolumetricFlowRateAutosized()
            for terminal
            in model.getAirTerminalSingleDuctConstantVolumeCooledBeams()))
        self.assertEqual(
            len(zones), len(model.getZoneHVACBaseboardConvectiveElectrics()))
        self.assertEqual(1, len(model.getCoilCoolingDXSingleSpeeds()))
        self.assertEqual(1, len(model.getChillerElectricEIRs()))

        chilled_loop = next(
            loop for loop in model.getPlantLoops()
            if plant_loops.temperature_profile(loop) is not None)
        self.assertEqual(
            'tempered_chilled_water',
            plant_loops.temperature_profile(chilled_loop)['name'])
        self.assertTrue(all(
            coil.plantLoop().is_initialized()
            and coil.plantLoop().get().handle() == chilled_loop.handle()
            for coil in model.getCoilCoolingCooledBeams()))
        self.assertEqual(
            len(zones) + 1, len(model.getEnergyManagementSystemSensors()))

        terminal_fact = catalog_report.zone_terminal(zones[0])
        self.assertEqual('Active chilled-beam terminal', terminal_fact['label'])
        zone_coil = next(
            coil for coil in model.getCoilCoolingCooledBeams()
            if zones[0].nameString() in coil.nameString())
        demand = catalog_report.demand_cell(zone_coil)
        self.assertIn('Cooled-beam cooling coil', demand['label'])
        self.assertIn(zones[0].nameString(), demand['label'])

        workspace = openstudio.energyplus.ForwardTranslator().translateModel(
            model)
        self.assertEqual(
            len(zones),
            len(workspace.getObjectsByType(openstudio.IddObjectType(
                'AirTerminal:SingleDuct:ConstantVolume:CooledBeam'))))

    def test_passive_mode_and_pipe_name(self):
        model, zones = self.fixture(limit=2)
        result = modeling.build_system(
            model, PASSIVE, zones, namer='necb_pipe_name')

        self.assertTrue(all(
            terminal.cooledBeamType() == 'Passive'
            for terminal
            in model.getAirTerminalSingleDuctConstantVolumeCooledBeams()))
        self.assertEqual(
            'chilled_beam|doas|shr>none|sc>dx|sh>c-e|ssf>cv|'
            'zh>b-e|zc>chilled_beam|srf>none|',
            result.air_loops[0].nameString())

    def test_invalid_override_fails_before_teardown_or_plant_creation(self):
        model, zones = self.fixture(limit=2)
        modeling.build_system(model, REPLACEMENT, zones)
        before = {str(obj.handle()) for obj in model.modelObjects()}

        with self.assertRaisesRegex(
                ValueError, 'must exceed inlet temperature'):
            modeling.build_system(
                model, ACTIVE, zones, remove_existing=True,
                config={'beam_design_outlet_water_temperature': 14.0})

        self.assertEqual(
            before, {str(obj.handle()) for obj in model.modelObjects()})

    def test_subset_replacement_cleans_beam_coils_controls_and_plant(self):
        model, zones = self.fixture(limit=2)
        modeling.build_system(model, ACTIVE, zones)

        modeling.build_system(
            model, REPLACEMENT, [zones[0]], remove_existing=True)
        self.assertEqual(
            1, len(model.getAirTerminalSingleDuctConstantVolumeCooledBeams()))
        self.assertEqual(1, len(model.getCoilCoolingCooledBeams()))
        self.assertEqual(2, len(model.getEnergyManagementSystemSensors()))
        self.assertEqual(1, len(model.getChillerElectricEIRs()))

        modeling.build_system(
            model, REPLACEMENT, [zones[1]], remove_existing=True)
        self.assertEqual(
            0, len(model.getAirTerminalSingleDuctConstantVolumeCooledBeams()))
        self.assertEqual(0, len(model.getCoilCoolingCooledBeams()))
        self.assertEqual(0, len(model.getEnergyManagementSystemSensors()))
        self.assertEqual(0, len(model.getEnergyManagementSystemPrograms()))
        self.assertEqual(0, len(model.getChillerElectricEIRs()))

    def test_teardown_removes_stranded_modern_hydronic_coils(self):
        import openstudio

        from btap.modeling.hvac import teardown

        model, zones = self.fixture(limit=1)
        loop = openstudio.model.PlantLoop(model)
        control = openstudio.model.ScheduleConstant(model)
        control.setValue(22.0)
        beam = openstudio.model.CoilCoolingCooledBeam(model)
        radiant_heating = openstudio.model.CoilHeatingLowTempRadiantVarFlow(
            model, control)
        radiant_cooling = openstudio.model.CoilCoolingLowTempRadiantVarFlow(
            model, control)
        for coil in (beam, radiant_heating, radiant_cooling):
            loop.addDemandBranchForComponent(coil)

        teardown.remove_hvac_from_zones(model, zones)

        self.assertEqual([], list(model.getCoilCoolingCooledBeams()))
        self.assertEqual(
            [], list(model.getCoilHeatingLowTempRadiantVarFlows()))
        self.assertEqual(
            [], list(model.getCoilCoolingLowTempRadiantVarFlows()))
        self.assertEqual([], list(model.getPlantLoops()))

    def test_foreign_beam_topology_is_classified_structurally(self):
        model, zones = self.fixture(limit=2)
        result = modeling.build_system(model, ACTIVE, zones)
        result.air_loops[0].setName('Imported Modern DOAS')

        facts = modeling.characterize(model)
        group = next(group for group in facts['zone_groups']
                     if group['air_loop'] == 'Imported Modern DOAS')
        self.assertIsNone(group['catalog_name'])
        self.assertEqual('chilled_beam', group['terminal_type'])
        self.assertEqual('chilled_beam', group['family_guess'])
        self.assertTrue(group['heated'])
        self.assertTrue(group['cooled'])
        self.assertIn('Electricity', group['heating_energy_types'])
        self.assertIn('Electricity', group['cooling_energy_types'])
        self.assertIsNone(group['design_cooling_kw'])


if __name__ == '__main__':
    unittest.main()
