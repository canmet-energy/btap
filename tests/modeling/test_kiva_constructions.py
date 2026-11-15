import unittest

from tests.support import needs_sdk


def _floor(model, construction, name="Ground Floor"):
    import openstudio

    space = openstudio.model.Space(model)
    points = openstudio.Point3dVector()
    for x, y in ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)):
        points.append(openstudio.Point3d(x, y, 0.0))
    floor = openstudio.model.Surface(points, model)
    floor.setName(name)
    floor.setSurfaceType("Floor")
    floor.setSpace(space)
    floor.setOutsideBoundaryCondition("Ground")
    floor.setConstruction(construction)
    return floor


def _construction(model, finish):
    import openstudio

    concrete = openstudio.model.StandardOpaqueMaterial(
        model, "Rough", 0.1, 1.8, 2300.0, 900.0)
    construction = openstudio.model.Construction(model)
    construction.setName("Slab with finish")
    construction.setLayers([finish, concrete])
    return construction


@needs_sdk
class TestKivaCompatibleConstructions(unittest.TestCase):
    def test_cp02_uses_sourced_carpet_properties_and_preserves_the_submission(self):
        import openstudio

        from btap.modeling.envelope import constructions

        model = openstudio.model.Model()
        carpet = openstudio.model.MasslessOpaqueMaterial(model)
        carpet.setName("CP02 CARPET PAD")
        carpet.setRoughness("VeryRough")
        carpet.setThermalResistance(0.2165)
        carpet.setThermalAbsorptance(0.91)
        carpet.setSolarAbsorptance(0.72)
        carpet.setVisibleAbsorptance(0.83)
        original = _construction(model, carpet)
        converted_floor = _floor(model, original, "Converted")
        untouched_floor = _floor(model, original, "Untouched")

        self.assertEqual(
            [], constructions.kiva_legalization_blockers(converted_floor),
            "the read-only preflight must recognize the same sourced carpet "
            "that the writer can replace",
        )
        self.assertEqual(
            original.handle(), converted_floor.construction().get().handle(),
            "eligibility inspection must not clone or assign a construction",
        )
        change = constructions.kiva_legal(model, converted_floor)

        self.assertIsNotNone(change)
        converted = converted_floor.construction().get().to_Construction().get()
        self.assertNotEqual(original.handle(), converted.handle())
        self.assertEqual(original.handle(), untouched_floor.construction().get().handle())
        self.assertAlmostEqual(
            change["resistance_before_m2k_w"],
            change["resistance_after_m2k_w"],
            delta=1e-12,
        )
        replacement = converted.layers()[0].to_StandardOpaqueMaterial().get()
        self.assertAlmostEqual(
            constructions.KIVA_CARPET_CONDUCTIVITY_W_MK,
            replacement.thermalConductivity(),
            delta=1e-12,
        )
        self.assertAlmostEqual(
            constructions.KIVA_CARPET_DENSITY_KG_M3,
            replacement.density(),
            delta=1e-12,
        )
        self.assertAlmostEqual(
            constructions.KIVA_CARPET_SPECIFIC_HEAT_J_KGK,
            replacement.specificHeat(),
            delta=1e-12,
        )
        self.assertAlmostEqual(
            0.2165,
            replacement.thickness() / replacement.thermalConductivity(),
            delta=1e-12,
        )
        self.assertEqual("VeryRough", replacement.roughness())
        self.assertAlmostEqual(0.91, replacement.thermalAbsorptance(), delta=1e-12)
        self.assertAlmostEqual(0.72, replacement.solarAbsorptance(), delta=1e-12)
        self.assertAlmostEqual(0.83, replacement.visibleAbsorptance(), delta=1e-12)
        self.assertEqual(
            carpet.handle(),
            original.layers()[0].handle(),
            "the submitted construction remains intact for every other surface",
        )

    def test_unknown_massless_layers_and_air_gaps_are_not_given_carpet_properties(self):
        import openstudio

        from btap.modeling.envelope import constructions, foundations

        for label in ("unknown no-mass", "air gap"):
            with self.subTest(layer=label):
                model = openstudio.model.Model()
                if label == "unknown no-mass":
                    finish = openstudio.model.MasslessOpaqueMaterial(model)
                else:
                    finish = openstudio.model.AirGap(model)
                finish.setName("Unknown finish")
                finish.setThermalResistance(0.2)
                construction = _construction(model, finish)
                floor = _floor(model, construction)

                blockers = constructions.kiva_legalization_blockers(floor)
                self.assertTrue(blockers)
                self.assertTrue(
                    any("no sourced Kiva-compatible replacement" in reason
                        for reason in blockers),
                    blockers,
                )
                self.assertIsNone(constructions.kiva_legal(model, floor))
                self.assertEqual(
                    construction.handle(), floor.construction().get().handle())
                result = foundations.create_kiva_foundation(model, floor)
                self.assertFalse(result["created"])
                self.assertTrue(
                    any("not a standard opaque material" in reason
                        for reason in result["refusals"]),
                    result["refusals"],
                )


if __name__ == "__main__":
    unittest.main()
