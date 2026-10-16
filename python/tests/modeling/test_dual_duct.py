import unittest

import btap.modeling as modeling
from tests.support import load_fixture, needs_sdk

SYSTEM = 'Dual-duct VAV with gas boiler and water-cooled chiller'


@needs_sdk
class TestDualDuct(unittest.TestCase):
    def fixture(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        return model, sorted_by_name(model.getThermalZones())

    def test_true_two_deck_topology_and_translation(self):
        import openstudio

        from btap.modeling.hvac import catalog_report

        model, zones = self.fixture()
        result = modeling.build_system(
            model, SYSTEM, zones, namer='necb_pipe_name')

        self.assertEqual(1, len(result.air_loops))
        air_loop = result.air_loops[0]
        self.assertTrue(air_loop.isDualDuct())
        self.assertEqual(2, len(air_loop.supplyOutletNodes()))
        self.assertEqual(len(zones), len(model.getAirTerminalDualDuctVAVs()))
        self.assertEqual(1, len(model.getCoilHeatingWaters()))
        self.assertEqual(1, len(model.getCoilCoolingWaters()))
        self.assertEqual(2, len(model.getBoilerHotWaters()))
        self.assertEqual(2, len(model.getChillerElectricEIRs()))
        self.assertIn('dual_duct|mixed|', air_loop.nameString())

        for terminal in model.getAirTerminalDualDuctVAVs():
            self.assertTrue(terminal.hotAirInletNode().is_initialized())
            self.assertTrue(terminal.coldAirInletNode().is_initialized())
            self.assertTrue(terminal.outletModelObject().is_initialized())
            self.assertTrue(terminal.isMaximumDamperAirFlowRateAutosized())
            self.assertAlmostEqual(
                0.3, terminal.zoneMinimumAirFlowFraction(), delta=1e-9)
        for zone in zones:
            sizing = zone.sizingZone()
            self.assertEqual(
                'SupplyAirTemperature',
                sizing.zoneHeatingDesignSupplyAirTemperatureInputMethod())
            self.assertAlmostEqual(
                35.0, sizing.zoneHeatingDesignSupplyAirTemperature(),
                delta=1e-9)

        managers = {
            manager.nameString(): manager
            for manager in model.getSetpointManagerScheduleds()
            if manager.nameString().startswith('Dual-Duct')
        }
        self.assertEqual(
            {'Dual-Duct Hot Deck Setpoint Manager',
             'Dual-Duct Cold Deck Setpoint Manager'},
            set(managers))
        self.assertAlmostEqual(
            35.0,
            managers['Dual-Duct Hot Deck Setpoint Manager']
            .schedule().to_ScheduleRuleset().get()
            .defaultDaySchedule().values()[0],
            delta=1e-9)
        self.assertAlmostEqual(
            13.0,
            managers['Dual-Duct Cold Deck Setpoint Manager']
            .schedule().to_ScheduleRuleset().get()
            .defaultDaySchedule().values()[0],
            delta=1e-9)

        diagram = catalog_report.air_loops(model)[0]
        parallel = [column for column in diagram['supply']
                    if column.get('parallel')]
        self.assertEqual(1, len(parallel))
        labels = {
            cell['label']
            for branch in parallel[0]['branches']
            for cell in branch
        }
        self.assertEqual(
            {'Hot-water heating coil', 'Chilled-water cooling coil'}, labels)

        workspace = openstudio.energyplus.ForwardTranslator().translateModel(model)
        self.assertEqual(
            len(zones),
            len(workspace.getObjectsByType(openstudio.IddObjectType(
                'AirTerminal:DualDuct:VAV'))))
        self.assertEqual(
            2, len(workspace.getObjectsByType(openstudio.IddObjectType(
                'AirLoopHVAC:ZoneSplitter'))))
        idf = str(workspace)
        self.assertIn('Dual-Duct Hot Deck Heating Coil', idf)
        self.assertIn('Dual-Duct Cold Deck Cooling Coil', idf)

    def test_foreign_dual_duct_is_classified_structurally(self):
        model, zones = self.fixture()
        result = modeling.build_system(model, SYSTEM, zones)
        result.air_loops[0].setName('Foreign Two Deck Air Handler')

        facts = modeling.characterize(model)
        group = next(group for group in facts['zone_groups']
                     if group['air_loop'])
        self.assertEqual('dual_duct_vav', group['terminal_type'])
        self.assertEqual('dual_duct_vav', group['family_guess'])
        self.assertTrue(group['heated'])
        self.assertTrue(group['cooled'])
        self.assertIn('NaturalGas', group['heating_energy_types'])
        self.assertIn('Electricity', group['cooling_energy_types'])

    def test_invalid_deck_temperatures_fail_before_replacement(self):
        from btap.modeling.hvac import catalog

        model, zones = self.fixture()
        modeling.build_system(
            model, 'PSZ RTU Electric and DX Coils and Electric Baseboard',
            zones)
        before = {str(obj.handle()) for obj in model.modelObjects()}

        with self.assertRaisesRegex(
                ValueError,
                'hot_deck_supply_air_temperature must exceed'):
            modeling.build_system(
                model, SYSTEM, zones, remove_existing=True,
                config={
                    'sizing': {
                        **catalog.resolve(SYSTEM)['sizing'],
                        'hot_deck_supply_air_temperature': 12.0,
                        'cold_deck_supply_air_temperature': 13.0,
                    },
                })

        self.assertEqual(before, {str(obj.handle()) for obj in model.modelObjects()})

    def test_missing_required_plant_fails_before_replacement(self):
        model, zones = self.fixture()
        modeling.build_system(
            model, 'PSZ RTU Electric and DX Coils and Electric Baseboard',
            zones)
        before = {str(obj.handle()) for obj in model.modelObjects()}

        with self.assertRaisesRegex(
                ValueError, 'requires needs_chiller=True'):
            modeling.build_system(
                model, SYSTEM, zones, remove_existing=True,
                config={'needs_chiller': False})

        self.assertEqual(
            before, {str(obj.handle()) for obj in model.modelObjects()})

    def test_subset_replacement_preserves_other_dual_duct_zones(self):
        model, zones = self.fixture()
        modeling.build_system(model, SYSTEM, zones)

        modeling.build_system(
            model, 'Baseboard electric', zones[:2], remove_existing=True)

        dual_loops = [loop for loop in model.getAirLoopHVACs()
                      if loop.isDualDuct()]
        self.assertEqual(1, len(dual_loops))
        self.assertEqual(
            {zone.nameString() for zone in zones[2:]},
            {zone.nameString() for zone in dual_loops[0].thermalZones()})
        self.assertEqual(3, len(model.getAirTerminalDualDuctVAVs()))
        self.assertEqual(2, len(model.getZoneHVACBaseboardConvectiveElectrics()))


if __name__ == '__main__':
    unittest.main()
