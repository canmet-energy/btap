import unittest

import btap.modeling as modeling
from tests.support import load_fixture, needs_sdk

ELECTRIC_SCROLL = 'MZ BU RTU Electric Heating Coil Scroll Chiller and Electric Baseboard'
HW_CENTRIFUGAL = 'MZ BU RTU Hot Water Heating Coil Centrifugal Chiller and Hot Water Baseboard'
ROTARY_ERV = 'VAV chiller with gas boiler reheat and rotary ERV'
PLATE_HRV = 'PVAV with gas boiler reheat and plate HRV'


@needs_sdk
class TestVAVReheat(unittest.TestCase):
    def test_electric_vav_builds_full_plant_and_air_side(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, ELECTRIC_SCROLL, zones)

        # fixture has one story containing all zones -> one air loop
        self.assertEqual(1, len(result.air_loops))
        air_loop = result.air_loops[0]
        self.assertEqual(len(zones), len(air_loop.thermalZones()))

        # supply + return VAV fans with load-bearing names
        fans = model.getFanVariableVolumes()
        self.assertEqual(2, len(fans))
        self.assertTrue(any('Supply' in f.nameString() for f in fans))
        self.assertTrue(any('Return' in f.nameString() for f in fans))

        # chilled-water cooling coil on the CHW loop; electric heat (1 main + 5 reheat)
        self.assertEqual(1, len(model.getCoilCoolingWaters()))
        self.assertEqual(1 + len(zones), len(model.getCoilHeatingElectrics()))

        # chilled + condenser plant with named chillers and a cooling tower
        chillers = model.getChillerElectricEIRs()
        self.assertEqual(2, len(chillers))
        self.assertEqual(['Primary Chiller WaterCooled Scroll',
                          'Secondary Chiller WaterCooled Scroll'],
                         sorted(c.nameString() for c in chillers))
        self.assertEqual(1, len(model.getCoolingTowerSingleSpeeds()))
        self.assertEqual(2, len(model.getPlantLoops()),
                         'CHW + CW loops (no boiler for all-electric)')
        self.assertEqual(0, len(model.getBoilerHotWaters()))

        # VAV terminals with NECB minimums
        terminals = model.getAirTerminalSingleDuctVAVReheats()
        self.assertEqual(len(zones), len(terminals))
        for terminal in terminals:
            self.assertEqual(43.0, terminal.maximumReheatAirTemperature())
            self.assertEqual('Normal', terminal.damperHeatingAction())
            self.assertGreater(terminal.fixedMinimumAirFlowRate().get(), 0.0)

        # constant 13C supply-air setpoint
        spm = next((m for m in model.getSetpointManagerScheduleds()
                    if str(m.setpointNode().get().handle())
                    == str(air_loop.supplyOutletNode().handle())), None)
        self.assertIsNotNone(spm)

        # sizing: sparse sys6 block (13/13.1 SATs, 0.3 min flow ratio)
        s = air_loop.sizingSystem()
        self.assertEqual(13.0, s.centralCoolingDesignSupplyAirTemperature())
        self.assertEqual(13.1, s.centralHeatingDesignSupplyAirTemperature())
        ratio = s.centralHeatingMaximumSystemAirFlowRatio()
        if hasattr(ratio, 'is_initialized'):
            ratio = ratio.get()
        self.assertAlmostEqual(0.3, float(ratio), delta=1e-6)

    def test_hot_water_variant_builds_boiler_and_hydronic_coils(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, HW_CENTRIFUGAL, zones)

        self.assertEqual(2, len(model.getBoilerHotWaters()))
        self.assertEqual(3, len(model.getPlantLoops()), 'HW + CHW + CW')
        # 1 main + 5 reheat hot-water coils, all on the HW loop
        self.assertEqual(1 + len(zones), len(model.getCoilHeatingWaters()))
        self.assertEqual(len(zones), len(model.getZoneHVACBaseboardConvectiveWaters()))
        self.assertTrue(all('Centrifugal' in c.nameString()
                            for c in model.getChillerElectricEIRs()))

    def test_pipe_name_uses_sys6_token_order(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(model, ELECTRIC_SCROLL, zones,
                                       namer='necb_pipe_name')
        # sys6 legacy order: sh> BEFORE sc> (observed from legacy build)
        self.assertEqual('sys_6|mixed|shr>none|sh>c-e|sc>c-chw|ssf>vv|zh>b-e|zc>none|srf>vv|',
                         result.air_loops[0].nameString())

    def test_remove_existing_replaces_vav_with_psz(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, HW_CENTRIFUGAL, zones)
        self.assertTrue(len(model.getChillerElectricEIRs()))

        modeling.build_system(model, 'PSZ RTU Electric and DX Coils and Electric Baseboard',
                              zones, remove_existing=True)
        self.assertEqual(0, len(model.getChillerElectricEIRs()),
                         'chiller + condenser chain torn down')
        self.assertEqual(0, len(model.getCoolingTowerSingleSpeeds()))
        self.assertEqual(0, len(model.getBoilerHotWaters()))
        self.assertEqual(1, len(model.getAirLoopHVACs()))

    def test_opt_in_rotary_erv_is_connected_and_original_row_is_unchanged(self):
        import openstudio

        from btap._compat import sorted_by_name
        from btap.modeling.hvac import catalog
        from btap.modeling.hvac.systems.vav_reheat import add_energy_recovery

        original = load_fixture()
        original_zones = sorted_by_name(original.getThermalZones())
        original_result = modeling.build_system(
            original, 'VAV chiller with gas boiler reheat', original_zones)

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(
            model, ROTARY_ERV, zones, namer='necb_pipe_name')

        self.assertEqual(len(original_result.air_loops), len(result.air_loops))
        self.assertEqual(
            [len(loop.thermalZones()) for loop in original_result.air_loops],
            [len(loop.thermalZones()) for loop in result.air_loops])
        self.assertEqual(0, len(original.getHeatExchangerAirToAirSensibleAndLatents()))
        self.assertEqual(1, len(model.getHeatExchangerAirToAirSensibleAndLatents()))
        self.assertEqual(
            len(zones), len(model.getZoneHVACBaseboardConvectiveWaters()))

        exchanger = model.getHeatExchangerAirToAirSensibleAndLatents()[0]
        self.assertEqual('Rotary', exchanger.heatExchangerType())
        self.assertAlmostEqual(
            0.75, exchanger.sensibleEffectivenessat100HeatingAirFlow(),
            delta=1e-9)
        self.assertAlmostEqual(
            0.65, exchanger.latentEffectivenessat100CoolingAirFlow(),
            delta=1e-9)
        self.assertTrue(
            exchanger.latentEffectivenessofCoolingAirFlowCurve().is_initialized())
        self.assertEqual('ExhaustOnly', exchanger.frostControlType())
        self.assertAlmostEqual(-23.3, exchanger.thresholdTemperature(), delta=1e-9)
        self.assertTrue(exchanger.economizerLockout())
        self.assertTrue(exchanger.supplyAirOutletTemperatureControl())
        self.assertEqual(
            'catalog',
            exchanger.additionalProperties().getFeatureAsString(
                'btap_energy_recovery_source').get())

        oa_system = result.air_loops[0].airLoopHVACOutdoorAirSystem().get()
        self.assertIn(
            str(exchanger.handle()),
            {str(component.handle()) for component in oa_system.oaComponents()})
        self.assertIn(
            str(exchanger.handle()),
            {str(component.handle()) for component in oa_system.reliefComponents()})
        for connection in (
                exchanger.primaryAirInletModelObject(),
                exchanger.primaryAirOutletModelObject(),
                exchanger.secondaryAirInletModelObject(),
                exchanger.secondaryAirOutletModelObject()):
            self.assertTrue(connection.is_initialized())

        pretreat = model.getSetpointManagerOutdoorAirPretreats()
        self.assertEqual(1, len(pretreat))
        self.assertEqual(
            str(exchanger.primaryAirOutletModelObject().get().handle()),
            str(pretreat[0].setpointNode().get().handle()))
        self.assertEqual(
            'BypassWhenOAFlowGreaterThanMinimum',
            oa_system.getControllerOutdoorAir()
            .getHeatRecoveryBypassControlType().get())

        add_energy_recovery(
            model, oa_system, {
                **catalog.resolve(ROTARY_ERV),
                'sizing': {},
            }, name='duplicate probe')
        self.assertEqual(1, len(model.getHeatExchangerAirToAirSensibleAndLatents()))

        self.assertIn('shr>erv', result.air_loops[0].nameString())
        workspace = openstudio.energyplus.ForwardTranslator().translateModel(model)
        translated = workspace.getObjectsByType(openstudio.IddObjectType(
            'HeatExchanger:AirToAir:SensibleAndLatent'))
        self.assertEqual(1, len(translated))
        self.assertNotIn(', , , ,', str(translated[0]))

    def test_plate_hrv_is_sensible_only_and_tears_down(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(
            model, PLATE_HRV, zones, namer='necb_pipe_name')

        exchanger = model.getHeatExchangerAirToAirSensibleAndLatents()[0]
        self.assertEqual('Plate', exchanger.heatExchangerType())
        self.assertEqual(0.0, exchanger.latentEffectivenessat100HeatingAirFlow())
        self.assertIn('shr>hrv', result.air_loops[0].nameString())
        self.assertEqual(
            len(zones), len(model.getZoneHVACBaseboardConvectiveWaters()))
        self.assertEqual(4, len(model.getTableLookups()))
        self.assertEqual(4, len(model.getTableIndependentVariables()))

        modeling.build_system(
            model, 'PSZ RTU Electric and DX Coils and Electric Baseboard',
            zones, remove_existing=True)
        self.assertEqual(0, len(model.getHeatExchangerAirToAirSensibleAndLatents()))
        self.assertEqual(0, len(model.getSetpointManagerOutdoorAirPretreats()))
        self.assertEqual(0, len(model.getTableLookups()))
        self.assertEqual(0, len(model.getTableIndependentVariables()))

    def test_subset_replacement_preserves_erv_effectiveness_tables(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, ROTARY_ERV, zones)

        modeling.build_system(
            model, 'Baseboard electric', zones[:2], remove_existing=True)

        self.assertEqual(
            1, len(model.getHeatExchangerAirToAirSensibleAndLatents()))
        self.assertEqual(4, len(model.getTableLookups()))
        self.assertEqual(4, len(model.getTableIndependentVariables()))

    def test_invalid_erv_inputs_fail_before_replacement(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(
            model, 'PSZ RTU Electric and DX Coils and Electric Baseboard',
            zones)
        before = {str(obj.handle()) for obj in model.modelObjects()}

        with self.assertRaisesRegex(
                ValueError, 'erv_sensible_effectiveness must be at most 1.0'):
            modeling.build_system(
                model, ROTARY_ERV, zones, remove_existing=True,
                config={'erv_sensible_effectiveness': 1.1})

        self.assertEqual(before, {str(obj.handle()) for obj in model.modelObjects()})


if __name__ == '__main__':
    unittest.main()
