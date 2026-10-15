import unittest

import btap.modeling as modeling
from tests.support import load_fixture, needs_sdk


@needs_sdk
class TestPlantTemperatureProfiles(unittest.TestCase):
    HOT = {
        'name': 'low_temperature_heating',
        'design_exit_temperature': 40.0,
        'design_temperature_difference': 5.0,
        'setpoint_temperature': 40.0,
    }
    TEMPERED = {
        'name': 'tempered_chilled_water',
        'design_exit_temperature': 15.0,
        'design_temperature_difference': 3.0,
        'setpoint_temperature': 15.0,
    }

    def setUp(self):
        import openstudio

        self.model = openstudio.model.Model()

    def test_legacy_defaults_remain_unstamped(self):
        from btap.modeling.hvac.systems import plant_loops

        hot = plant_loops.hot_water(self.model)
        chilled = plant_loops.chilled_water(self.model)

        self.assertEqual(82.0, hot.sizingPlant().designLoopExitTemperature())
        self.assertEqual(16.0, hot.sizingPlant().loopDesignTemperatureDifference())
        self.assertEqual(7.0, chilled.sizingPlant().designLoopExitTemperature())
        self.assertEqual(6.0, chilled.sizingPlant().loopDesignTemperatureDifference())
        self.assertIsNone(plant_loops.temperature_profile(hot))
        self.assertIsNone(plant_loops.temperature_profile(chilled))

    def test_matching_explicit_profiles_reuse_the_same_loops(self):
        from btap.modeling.hvac.systems import plant_loops

        hot = plant_loops.hot_water(self.model, profile=self.HOT)
        hot_again = plant_loops.hot_water(self.model, profile=dict(self.HOT))
        chilled = plant_loops.chilled_water(self.model, profile=self.TEMPERED)
        chilled_again = plant_loops.chilled_water(
            self.model, profile=dict(self.TEMPERED))

        self.assertEqual(hot.handle(), hot_again.handle())
        self.assertEqual(chilled.handle(), chilled_again.handle())
        self.assertEqual(40.0, hot.sizingPlant().designLoopExitTemperature())
        self.assertEqual(15.0, chilled.sizingPlant().designLoopExitTemperature())
        self.assertEqual(
            'low_temperature_heating',
            plant_loops.temperature_profile(hot)['name'])
        self.assertEqual(
            'tempered_chilled_water',
            plant_loops.temperature_profile(chilled)['name'])

    def test_different_profiles_do_not_share_or_reprogram_a_loop(self):
        from btap.modeling.hvac.systems import plant_loops

        first_profile = dict(self.TEMPERED)
        second_profile = {
            **self.TEMPERED,
            'name': 'warmer_tempered_chilled_water',
            'design_exit_temperature': 17.0,
            'setpoint_temperature': 17.0,
        }
        first = plant_loops.chilled_water(self.model, profile=first_profile)
        second = plant_loops.chilled_water(self.model, profile=second_profile)
        legacy = plant_loops.chilled_water(self.model)

        self.assertNotEqual(first.handle(), second.handle())
        self.assertNotEqual(first.handle(), legacy.handle())
        self.assertNotEqual(second.handle(), legacy.handle())
        self.assertEqual(15.0, first.sizingPlant().designLoopExitTemperature())
        self.assertEqual(17.0, second.sizingPlant().designLoopExitTemperature())
        self.assertEqual(7.0, legacy.sizingPlant().designLoopExitTemperature())

    def test_district_hot_water_reuse_is_profile_aware(self):
        from btap.modeling.hvac.systems import plant_loops

        first = plant_loops.hot_water(
            self.model, source='district', profile=self.HOT)
        second_profile = {
            **self.HOT,
            'name': 'warmer_district_heating',
            'design_exit_temperature': 45.0,
            'setpoint_temperature': 45.0,
        }
        second = plant_loops.hot_water(
            self.model, source='district', profile=second_profile)

        self.assertNotEqual(first.handle(), second.handle())
        self.assertEqual(40.0, first.sizingPlant().designLoopExitTemperature())
        self.assertEqual(45.0, second.sizingPlant().designLoopExitTemperature())

    def test_invalid_profile_fails_before_model_mutation(self):
        from btap.modeling.hvac.systems import plant_loops

        invalid = {**self.TEMPERED, 'design_temperature_difference': 0.0}
        with self.assertRaisesRegex(ValueError, 'design_temperature_difference'):
            plant_loops.chilled_water(self.model, profile=invalid)

        self.assertEqual([], list(self.model.getPlantLoops()))

    def test_dewpoint_reset_is_one_idempotent_translated_control(self):
        import openstudio

        from btap.modeling.hvac.systems import plant_loops

        zones = [openstudio.model.ThermalZone(self.model) for _ in range(2)]
        for index, zone in enumerate(zones, start=1):
            zone.setName(f'Dewpoint Zone {index}')
        loop = plant_loops.chilled_water(
            self.model, source='air_cooled', profile=self.TEMPERED)

        plant_loops.configure_dewpoint_reset(loop, zones[:1], margin=2.0)
        plant_loops.configure_dewpoint_reset(loop, zones, margin=2.0)

        self.assertEqual(
            3, len(self.model.getEnergyManagementSystemSensors()))
        self.assertEqual(
            1, len(self.model.getEnergyManagementSystemActuators()))
        self.assertEqual(
            1, len(self.model.getEnergyManagementSystemPrograms()))
        self.assertEqual(
            1, len(self.model.getEnergyManagementSystemProgramCallingManagers()))
        lines = self.model.getEnergyManagementSystemPrograms()[0].lines()
        self.assertTrue(any('@TdpFnWPb' in line for line in lines))
        self.assertTrue(any('+ 2' in line for line in lines))
        self.assertTrue(any('< 15' in line for line in lines))

        workspace = openstudio.energyplus.ForwardTranslator().translateModel(
            self.model)
        translated_sensors = workspace.getObjectsByType(
            openstudio.IddObjectType('EnergyManagementSystem:Sensor'))
        self.assertEqual(
            3, len(translated_sensors))
        self.assertIn(
            'Zone Mean Air Humidity Ratio',
            {sensor.getString(2).get() for sensor in translated_sensors})
        self.assertEqual(
            1, len(workspace.getObjectsByType(
                openstudio.IddObjectType('EnergyManagementSystem:Actuator'))))
        self.assertEqual(
            1, len(workspace.getObjectsByType(
                openstudio.IddObjectType('EnergyManagementSystem:Program'))))

    def test_dewpoint_reset_requires_an_explicit_profile(self):
        import openstudio

        from btap.modeling.hvac.systems import plant_loops

        zone = openstudio.model.ThermalZone(self.model)
        loop = plant_loops.chilled_water(
            self.model, source='air_cooled')
        with self.assertRaisesRegex(ValueError, 'explicit chilled-water profile'):
            plant_loops.configure_dewpoint_reset(loop, [zone], margin=2.0)

    def test_dewpoint_reset_uses_handle_identity_and_the_safest_margin(self):
        import openstudio

        from btap.modeling.hvac.systems import plant_loops

        first = openstudio.model.ThermalZone(self.model)
        first.setName('Zone-A')
        second = openstudio.model.ThermalZone(self.model)
        second.setName('Zone A')
        loop = plant_loops.chilled_water(
            self.model, source='air_cooled', profile=self.TEMPERED)

        plant_loops.configure_dewpoint_reset(loop, [first], margin=5.0)
        plant_loops.configure_dewpoint_reset(loop, [second], margin=2.0)

        self.assertEqual(
            3, len(self.model.getEnergyManagementSystemSensors()))
        lines = self.model.getEnergyManagementSystemPrograms()[0].lines()
        self.assertTrue(any('+ 5' in line for line in lines))

        plant_loops.remove_zones_from_dewpoint_reset(loop, [first])
        self.assertEqual(
            2, len(self.model.getEnergyManagementSystemSensors()))
        lines = self.model.getEnergyManagementSystemPrograms()[0].lines()
        self.assertTrue(any('+ 2' in line for line in lines))

        plant_loops.remove_zones_from_dewpoint_reset(loop, [second])
        self.assertEqual(
            0, len(self.model.getEnergyManagementSystemSensors()))
        self.assertEqual(
            0, len(self.model.getEnergyManagementSystemPrograms()))

    def test_public_builder_validates_plant_inputs_before_replacement(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(
            model, 'PSZ RTU Electric and DX Coils and Electric Baseboard',
            zones)
        before = {str(obj.handle()) for obj in model.modelObjects()}

        with self.assertRaisesRegex(
                ValueError, 'design_temperature_difference'):
            modeling.build_system(
                model, 'VAV chiller with gas boiler reheat', zones,
                remove_existing=True,
                config={
                    'chilled_water_profile': {
                        **self.TEMPERED,
                        'design_temperature_difference': 0.0,
                    },
                })

        self.assertEqual(
            before, {str(obj.handle()) for obj in model.modelObjects()})


if __name__ == '__main__':
    unittest.main()
