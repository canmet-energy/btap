import unittest

from tests.support import needs_sdk


@needs_sdk
class TestModernDoas(unittest.TestCase):
    def test_builds_all_outdoor_air_dehumidification_and_reheat(self):
        import openstudio

        from btap.modeling.hvac.systems.base_system import BaseSystem
        from btap.modeling.hvac.systems.doas import build_dehumidifying_doas

        model = openstudio.model.Model()
        system = BaseSystem({
            'sizing': {
                'all_outdoor_air_in_cooling': True,
                'all_outdoor_air_in_heating': True,
                'type_of_load_to_size_on': 'VentilationRequirement',
            },
        })
        air_loop = build_dehumidifying_doas(
            system, model,
            system_name='Test Modern DOAS',
            namer='default',
            sys_abbr='modern_doas',
            supply_air_temperature=20.0,
            maximum_humidity_ratio=0.008,
            zone_heating='electric',
            zone_cooling='chilled_beam')

        self.assertEqual('Test Modern DOAS', air_loop.nameString())
        self.assertEqual(1, len(model.getCoilCoolingDXSingleSpeeds()))
        self.assertEqual(1, len(model.getCoilHeatingElectrics()))
        self.assertEqual(1, len(model.getAirLoopHVACOutdoorAirSystems()))

        controller = model.getControllerOutdoorAirs()[0]
        self.assertTrue(
            controller.minimumFractionofOutdoorAirSchedule().is_initialized())
        self.assertTrue(
            controller.maximumFractionofOutdoorAirSchedule().is_initialized())
        self.assertEqual('NoEconomizer', controller.getEconomizerControlType())

        managers = model.getSetpointManagerScheduleds()
        humidity = [manager for manager in managers
                    if manager.controlVariable() == 'MaximumHumidityRatio']
        temperature = [manager for manager in managers
                       if manager.controlVariable() == 'Temperature']
        self.assertEqual(1, len(humidity))
        self.assertEqual(1, len(temperature))
        self.assertEqual(
            model.getCoilCoolingDXSingleSpeeds()[0].outletModelObject().get().handle(),
            humidity[0].setpointNode().get().handle())
        self.assertEqual(
            air_loop.supplyOutletNode().handle(),
            temperature[0].setpointNode().get().handle())

    def test_rejects_invalid_moisture_input_before_mutation(self):
        import openstudio

        from btap.modeling.hvac.systems.base_system import BaseSystem
        from btap.modeling.hvac.systems.doas import build_dehumidifying_doas

        model = openstudio.model.Model()
        with self.assertRaisesRegex(ValueError, 'maximum_humidity_ratio'):
            build_dehumidifying_doas(
                BaseSystem({}), model,
                system_name='Invalid DOAS',
                namer='default',
                sys_abbr='modern_doas',
                supply_air_temperature=20.0,
                maximum_humidity_ratio=0.05,
                zone_heating='electric',
                zone_cooling='chilled_beam')

        self.assertEqual([], list(model.getAirLoopHVACs()))


if __name__ == '__main__':
    unittest.main()
