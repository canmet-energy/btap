import unittest

import btap.modeling as modeling
from tests.support import load_fixture, needs_sdk


@needs_sdk
class TestBoilerlessHotWaterReuse(unittest.TestCase):
    def test_the_catalogue_builder_completes_the_named_loop_at_its_call_site(self):
        import openstudio

        from btap._compat import sorted_by_name
        from btap.modeling.hvac.systems import plant_loops

        for fuel in ("NaturalGas", "Electricity"):
            with self.subTest(fuel=fuel):
                model = load_fixture()
                bare = openstudio.model.PlantLoop(model)
                bare.setName("Hot Water Loop")

                modeling.build_system(
                    model,
                    "Baseboard gas boiler",
                    sorted_by_name(model.getThermalZones()),
                    config={"boiler_fuel": fuel},
                )

                self.assertEqual(
                    [fuel, fuel],
                    plant_loops.boiler_fuels(bare),
                    "the builder call must finish the plant it adopted",
                )
                self.assertEqual(
                    1,
                    len(model.getPlantLoops()),
                    "completion preserves the named loop instead of orphaning it",
                )
                for baseboard in model.getZoneHVACBaseboardConvectiveWaters():
                    plant = baseboard.heatingCoil().plantLoop()
                    self.assertTrue(plant.is_initialized())
                    self.assertEqual(bare.handle(), plant.get().handle())

    def test_an_explicit_pair_finishes_the_loop_in_primary_secondary_order(self):
        import openstudio

        from btap.modeling.hvac.systems import plant_loops

        model = openstudio.model.Model()
        bare = openstudio.model.PlantLoop(model)
        bare.setName("Hot Water Loop")

        got = plant_loops.hot_water(
            model, fuel="NaturalGas", backup_fuel="Electricity"
        )

        self.assertEqual(bare.handle(), got.handle())
        self.assertEqual(
            ["NaturalGas", "Electricity"], plant_loops.boiler_fuels(got)
        )
        roles = {
            boiler.fuelType(): boiler.additionalProperties().getFeatureAsString(
                plant_loops.BOILER_PLANT_ROLE_FEATURE
            ).get()
            for boiler in model.getBoilerHotWaters()
        }
        self.assertEqual(
            {"NaturalGas": "primary", "Electricity": "secondary"}, roles
        )
        self.assertEqual(
            1,
            len(got.supplyComponents(
                openstudio.model.PumpVariableSpeed.iddObjectType()
            )),
        )
        self.assertEqual(
            2,
            len(got.supplyComponents(openstudio.model.PipeAdiabatic.iddObjectType())),
        )
        self.assertEqual(1, len(got.supplyOutletNode().setpointManagers()))
        self.assertEqual(16.0, got.sizingPlant().loopDesignTemperatureDifference())

    def test_replacing_missing_boilers_does_not_duplicate_loop_machinery(self):
        import openstudio

        from btap.modeling.hvac.systems import plant_loops

        model = openstudio.model.Model()
        loop = plant_loops.hot_water(model, reuse=False)
        for boiler in list(model.getBoilerHotWaters()):
            boiler.remove()

        got = plant_loops.hot_water(
            model, fuel="Electricity", backup_fuel="NaturalGas"
        )

        self.assertEqual(loop.handle(), got.handle())
        self.assertEqual(
            ["Electricity", "NaturalGas"], plant_loops.boiler_fuels(got)
        )
        self.assertEqual(
            1,
            len(got.supplyComponents(
                openstudio.model.PumpVariableSpeed.iddObjectType()
            )),
        )
        self.assertEqual(
            2,
            len(got.supplyComponents(openstudio.model.PipeAdiabatic.iddObjectType())),
        )
        self.assertEqual(1, len(got.supplyOutletNode().setpointManagers()))

    def test_the_district_builder_still_refuses_a_sourceless_named_loop(self):
        import openstudio

        from btap._compat import sorted_by_name
        from btap.modeling.hvac.systems import plant_loops

        model = load_fixture()
        bare = openstudio.model.PlantLoop(model)
        bare.setName("Hot Water Loop")

        modeling.build_system(
            model,
            "Baseboard district hot water",
            sorted_by_name(model.getThermalZones()),
        )

        self.assertFalse(plant_loops._district_heated(bare))
        self.assertEqual([], plant_loops.boiler_fuels(bare))
        district = [
            loop for loop in model.getPlantLoops()
            if plant_loops._district_heated(loop)
        ]
        self.assertEqual(1, len(district))
        self.assertNotEqual(bare.handle(), district[0].handle())
        for baseboard in model.getZoneHVACBaseboardConvectiveWaters():
            plant = baseboard.heatingCoil().plantLoop()
            self.assertTrue(plant.is_initialized())
            self.assertEqual(district[0].handle(), plant.get().handle())

    def test_an_excluded_named_loop_is_not_completed(self):
        import openstudio

        from btap._compat import sorted_by_name
        from btap.modeling.hvac.systems import plant_loops

        model = load_fixture()
        bare = openstudio.model.PlantLoop(model)
        bare.setName("Hot Water Loop")

        modeling.build_system(
            model,
            "Baseboard gas boiler",
            sorted_by_name(model.getThermalZones()),
            exclude_plants=(str(bare.handle()),),
        )

        self.assertEqual([], plant_loops.boiler_fuels(bare))
        boiler_loops = [
            loop for loop in model.getPlantLoops()
            if plant_loops.boiler_fuels(loop)
        ]
        self.assertEqual(1, len(boiler_loops))
        self.assertNotEqual(bare.handle(), boiler_loops[0].handle())
        self.assertEqual(
            ["NaturalGas", "NaturalGas"],
            plant_loops.boiler_fuels(boiler_loops[0]),
        )
        for baseboard in model.getZoneHVACBaseboardConvectiveWaters():
            plant = baseboard.heatingCoil().plantLoop()
            self.assertTrue(plant.is_initialized())
            self.assertEqual(boiler_loops[0].handle(), plant.get().handle())

    def test_a_named_loop_with_another_source_is_not_an_unfinished_shell(self):
        import openstudio

        from btap.modeling.hvac.systems import plant_loops

        model = openstudio.model.Model()
        heat_pump_loop = openstudio.model.PlantLoop(model)
        heat_pump_loop.setName("Hot Water Loop")
        heat_pump_loop.addSupplyBranchForComponent(
            openstudio.model.HeatPumpWaterToWaterEquationFitHeating(model)
        )

        got = plant_loops.hot_water(model, fuel="NaturalGas")

        self.assertNotEqual(heat_pump_loop.handle(), got.handle())
        self.assertEqual([], plant_loops.boiler_fuels(heat_pump_loop))
        self.assertEqual(
            ["NaturalGas", "NaturalGas"], plant_loops.boiler_fuels(got)
        )
        self.assertFalse(plant_loops.plant_is_hvac_candidate(heat_pump_loop))


if __name__ == "__main__":
    unittest.main()
