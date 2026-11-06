import unittest

import btap.modeling as modeling
from btap.modeling.hvac import performance
from tests.support import load_fixture, needs_sdk

ASHP = (
    'PSZ RTU ASHP with Electric and ASHP with Electric Supp. Heat Coils '
    'and Electric Baseboard'
)
MAU_PTAC = 'PSZ MAU Electric and DX Coils and Electric Baseboard with PTAC'
DX_PROFILE = {
    'dx_cooling_capacity_temperature_curve': 'DXCOOL-REF-COOLEIRFT',
    'dx_cooling_capacity_flow_curve': 'DXCOOL-REF-EIRFFLOW',
    'dx_cooling_eir_temperature_curve': 'DXCOOL-REF-CAPFT',
    'dx_cooling_eir_flow_curve': 'DXCOOL-REF-CAPFFLOW',
    'dx_cooling_part_load_fraction_curve': 'DXHEAT-REF-PLFFPLR',
    'dx_heating_capacity_temperature_curve': 'DXHEAT-REF-EIRFT',
    'dx_heating_capacity_flow_curve': 'DXHEAT-REF-PLFFPLR',
    'dx_heating_eir_temperature_curve': 'DXHEAT-REF-CAPFT',
    'dx_heating_eir_flow_curve': 'DXCOOL-REF-CAPFFLOW',
    'dx_heating_part_load_fraction_curve': 'DXHEAT-REF-CAPFFLOW',
}


class TestPerformanceProfileContract(unittest.TestCase):
    def test_defaults_pin_the_seventeen_profile_values(self):
        self.assertEqual({
            'dx_cooling_capacity_temperature_curve': 'DXCOOL-REF-CAPFT',
            'dx_cooling_capacity_flow_curve': 'DXCOOL-REF-CAPFFLOW',
            'dx_cooling_eir_temperature_curve': 'DXCOOL-REF-COOLEIRFT',
            'dx_cooling_eir_flow_curve': 'DXCOOL-REF-EIRFFLOW',
            'dx_cooling_part_load_fraction_curve':
                'DXCOOL-REF-COOLPLFFPLR',
            'dx_heating_capacity_temperature_curve': 'DXHEAT-REF-CAPFT',
            'dx_heating_capacity_flow_curve': 'DXHEAT-REF-CAPFFLOW',
            'dx_heating_eir_temperature_curve': 'DXHEAT-REF-EIRFT',
            'dx_heating_eir_flow_curve': 'DXHEAT-REF-EIRFFLOW',
            'dx_heating_part_load_fraction_curve': 'DXHEAT-REF-PLFFPLR',
            'vrf_rated_heating_cop': 4.0,
            'vrf_gross_rated_cooling_cop': 4.0,
            'window_ac_eer_btu_per_w_h': 8.5,
            'evaporative_cooler_design_effectiveness': 0.9,
            'plant_heating_heat_pump_minimum_part_load_ratio': 0.2,
            'plant_cooling_heat_pump_minimum_part_load_ratio': 0.2,
            'ptac_fan_pressure_rise_pa': 640.0,
        }, dict(performance.DEFAULT_PERFORMANCE_PROFILE))
        self.assertFalse(any(
            'unit_heater' in key
            for key in performance.DEFAULT_PERFORMANCE_PROFILE))

    def test_partial_overrides_are_validated_and_defaults_are_retained(self):
        profile = performance.resolve({'vrf_rated_heating_cop': 3.25})
        self.assertEqual(3.25, profile['vrf_rated_heating_cop'])
        self.assertEqual(
            'DXCOOL-REF-CAPFT',
            profile['dx_cooling_capacity_temperature_curve'])

        invalid = (
            ({'typo': 1.0}, 'unknown performance_profile key'),
            ({'vrf_rated_heating_cop': 0.0}, 'greater than zero'),
            ({'evaporative_cooler_design_effectiveness': 1.1},
             'between zero and one'),
            ({'dx_cooling_capacity_temperature_curve':
              'DXCOOL-REF-CAPFFLOW'}, 'must name a biquadratic'),
        )
        for values, message in invalid:
            with self.subTest(values=values):
                with self.assertRaisesRegex(ValueError, message):
                    performance.resolve(values)


@needs_sdk
class TestPerformanceProfileRouting(unittest.TestCase):
    @staticmethod
    def _model_and_zones():
        from btap._compat import sorted_by_name

        model = load_fixture()
        return model, sorted_by_name(model.getThermalZones())

    @staticmethod
    def _curve_names(coil):
        return (
            coil.totalCoolingCapacityFunctionOfTemperatureCurve().nameString(),
            coil.totalCoolingCapacityFunctionOfFlowFractionCurve().nameString(),
            coil.energyInputRatioFunctionOfTemperatureCurve().nameString(),
            coil.energyInputRatioFunctionOfFlowFractionCurve().nameString(),
            coil.partLoadFractionCorrelationCurve().nameString(),
        )

    @staticmethod
    def _heating_curve_names(coil):
        return (
            coil.totalHeatingCapacityFunctionofTemperatureCurve().nameString(),
            coil.totalHeatingCapacityFunctionofFlowFractionCurve().nameString(),
            coil.energyInputRatioFunctionofTemperatureCurve().nameString(),
            coil.energyInputRatioFunctionofFlowFractionCurve().nameString(),
            coil.partLoadFractionCorrelationCurve().nameString(),
        )

    def test_all_ten_dx_curve_names_reach_single_speed_coils(self):
        model, zones = self._model_and_zones()
        modeling.build_system(
            model, ASHP, zones, performance_profile=DX_PROFILE)

        cooling = model.getCoilCoolingDXSingleSpeeds()[0]
        heating = model.getCoilHeatingDXSingleSpeeds()[0]
        self.assertEqual((
            DX_PROFILE['dx_cooling_capacity_temperature_curve'],
            DX_PROFILE['dx_cooling_capacity_flow_curve'],
            DX_PROFILE['dx_cooling_eir_temperature_curve'],
            DX_PROFILE['dx_cooling_eir_flow_curve'],
            DX_PROFILE['dx_cooling_part_load_fraction_curve'],
        ), self._curve_names(cooling))
        self.assertEqual((
            DX_PROFILE['dx_heating_capacity_temperature_curve'],
            DX_PROFILE['dx_heating_capacity_flow_curve'],
            DX_PROFILE['dx_heating_eir_temperature_curve'],
            DX_PROFILE['dx_heating_eir_flow_curve'],
            DX_PROFILE['dx_heating_part_load_fraction_curve'],
        ), self._heating_curve_names(heating))

    def test_profile_reaches_every_multispeed_stage(self):
        model, zones = self._model_and_zones()
        modeling.build_system(
            model, ASHP, zones, config={'staged_coils': 2},
            performance_profile=DX_PROFILE)

        expected_cooling = (
            DX_PROFILE['dx_cooling_capacity_temperature_curve'],
            DX_PROFILE['dx_cooling_capacity_flow_curve'],
            DX_PROFILE['dx_cooling_eir_temperature_curve'],
            DX_PROFILE['dx_cooling_eir_flow_curve'],
            DX_PROFILE['dx_cooling_part_load_fraction_curve'],
        )
        expected_heating = (
            DX_PROFILE['dx_heating_capacity_temperature_curve'],
            DX_PROFILE['dx_heating_capacity_flow_curve'],
            DX_PROFILE['dx_heating_eir_temperature_curve'],
            DX_PROFILE['dx_heating_eir_flow_curve'],
            DX_PROFILE['dx_heating_part_load_fraction_curve'],
        )
        cooling = model.getCoilCoolingDXMultiSpeeds()[0]
        heating = model.getCoilHeatingDXMultiSpeeds()[0]
        for stage in cooling.stages():
            self.assertEqual(expected_cooling, (
                stage.totalCoolingCapacityFunctionofTemperatureCurve()
                    .nameString(),
                stage.totalCoolingCapacityFunctionofFlowFractionCurve()
                    .nameString(),
                stage.energyInputRatioFunctionofTemperatureCurve().nameString(),
                stage.energyInputRatioFunctionofFlowFractionCurve().nameString(),
                stage.partLoadFractionCorrelationCurve().nameString(),
            ))
        for stage in heating.stages():
            self.assertEqual(expected_heating, (
                stage.heatingCapacityFunctionofTemperatureCurve().nameString(),
                stage.heatingCapacityFunctionofFlowFractionCurve().nameString(),
                stage.energyInputRatioFunctionofTemperatureCurve().nameString(),
                stage.energyInputRatioFunctionofFlowFractionCurve().nameString(),
                stage.partLoadFractionCorrelationCurve().nameString(),
            ))

    def test_scalar_values_reach_each_supported_equipment_type(self):
        import openstudio

        model, zones = self._model_and_zones()
        modeling.build_system(
            model, 'VRF', zones,
            performance_profile={
                'vrf_rated_heating_cop': 3.1,
                'vrf_gross_rated_cooling_cop': 3.2,
            })
        vrf = model.getAirConditionerVariableRefrigerantFlows()[0]
        self.assertEqual(3.1, vrf.ratedHeatingCOP())
        self.assertEqual(3.2, vrf.grossRatedCoolingCOP())

        model, zones = self._model_and_zones()
        modeling.build_system(
            model, 'Window AC with baseboard electric', zones,
            performance_profile={'window_ac_eer_btu_per_w_h': 10.0})
        window_coil = (
            model.getZoneHVACPackagedTerminalAirConditioners()[0]
            .coolingCoil().to_CoilCoolingDXSingleSpeed().get())
        expected_cop = openstudio.convert(10.0, 'Btu/h', 'W').get()
        self.assertAlmostEqual(expected_cop, window_coil.ratedCOP())

        model, zones = self._model_and_zones()
        modeling.build_system(
            model, 'Direct evap coolers with baseboard electric', zones,
            performance_profile={
                'evaporative_cooler_design_effectiveness': 0.75})
        self.assertTrue(all(
            cooler.coolerDesignEffectiveness() == 0.75
            for cooler in model.getEvaporativeCoolerDirectResearchSpecials()))

        model, zones = self._model_and_zones()
        modeling.build_system(
            model, 'hs15_cawhp_fancoils', zones,
            performance_profile={
                'plant_heating_heat_pump_minimum_part_load_ratio': 0.31,
                'plant_cooling_heat_pump_minimum_part_load_ratio': 0.42,
            })
        self.assertEqual(
            0.31,
            model.getHeatPumpPlantLoopEIRHeatings()[0].minimumPartLoadRatio())
        self.assertEqual(
            0.42,
            model.getHeatPumpPlantLoopEIRCoolings()[0].minimumPartLoadRatio())

        model, zones = self._model_and_zones()
        modeling.build_system(
            model, MAU_PTAC, zones,
            performance_profile={'ptac_fan_pressure_rise_pa': 512.0})
        self.assertTrue(all(
            fan.pressureRise() == 512.0 for fan in model.getFanOnOffs()))

    def test_profile_propagates_into_composite_parts(self):
        model, zones = self._model_and_zones()
        modeling.build_system(
            model, 'DOAS with fan coil chiller with boiler', zones,
            performance_profile={
                'dx_cooling_capacity_temperature_curve':
                    'DXCOOL-REF-COOLEIRFT',
            })
        self.assertEqual(
            'DXCOOL-REF-COOLEIRFT',
            model.getCoilCoolingDXSingleSpeeds()[0]
                .totalCoolingCapacityFunctionOfTemperatureCurve().nameString())

    def test_an_invalid_profile_cannot_trigger_teardown(self):
        model, zones = self._model_and_zones()
        modeling.build_system(model, 'Forced air furnace', zones)
        handles = sorted(str(loop.handle()) for loop in model.getAirLoopHVACs())

        with self.assertRaisesRegex(
                ValueError, 'unknown performance_profile key'):
            modeling.replace_system(
                model, 'PSZ RTU Electric and DX Coils and Electric Baseboard',
                zones, performance_profile={'typo': 1.0})
        self.assertEqual(
            handles,
            sorted(str(loop.handle()) for loop in model.getAirLoopHVACs()))


if __name__ == '__main__':
    unittest.main()
