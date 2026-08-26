"""Smoke pins for the envelope port (constructions + geometry census).

btap-modeling has no Ruby test file for these — they are exercised by the
btap-necb envelope suites and the Leg-A parity gates, which arrive with M5.
These pins hold the port's behavior (naming/reuse conventions, the
conductance solve, the conditioned-space proxy) until those gates take over.
"""

import unittest

from tests.support import needs_sdk


@needs_sdk
class TestOpaqueAtConductance(unittest.TestCase):
    def model_with_wall_construction(self):
        import openstudio
        model = openstudio.model.Model()
        insulation = openstudio.model.StandardOpaqueMaterial(model)
        insulation.setName("insulation")
        insulation.setThickness(0.1)
        insulation.setConductivity(0.03)
        brick = openstudio.model.StandardOpaqueMaterial(model)
        brick.setName("brick")
        brick.setThickness(0.09)
        brick.setConductivity(0.8)
        construction = openstudio.model.Construction(model)
        construction.setName("Base Wall")
        construction.setLayers([brick, insulation])
        return model, construction

    def test_solves_to_the_target_and_names_by_convention(self):
        from btap._compat import opt
        from btap.modeling.envelope import constructions
        model, base = self.model_with_wall_construction()
        result = constructions.opaque_at_conductance(model, base, 0.278)
        self.assertEqual("Base Wall:U-0.278", result.nameString())
        self.assertAlmostEqual(0.278, opt(result.thermalConductance()), places=4)

    def test_reuses_by_name_and_never_mutates_the_base(self):
        from btap._compat import opt
        from btap.modeling.envelope import constructions
        model, base = self.model_with_wall_construction()
        base_conductance = opt(base.thermalConductance())
        first = constructions.opaque_at_conductance(model, base, 0.278)
        second = constructions.opaque_at_conductance(model, base, 0.278)
        self.assertEqual(str(first.handle()), str(second.handle()), "reused by name")
        self.assertAlmostEqual(base_conductance, opt(base.thermalConductance()), places=6,
                               msg="deep copy — the base construction must not move")

    def test_fenestration_builds_a_shared_simple_glazing(self):
        import openstudio
        from btap.modeling.envelope import constructions
        model = openstudio.model.Model()
        glazing = openstudio.model.SimpleGlazing(model)
        glazing.setSolarHeatGainCoefficient(0.42)
        base = openstudio.model.Construction(model)
        base.setName("Base Window")
        base.setLayers([glazing])
        result = constructions.fenestration_at_conductance(model, base, 1.9)
        self.assertEqual("Base Window:U=0.190 SHGC=0.420", result.nameString())
        self.assertEqual(1, len(result.layers()))
        again = constructions.fenestration_at_conductance(model, base, 1.9)
        self.assertEqual(str(result.handle()), str(again.handle()))


@needs_sdk
class TestExposedCensus(unittest.TestCase):
    def test_thermostats_gate_the_census(self):
        # The D-75 fact: zones without dual-setpoint thermostats are not
        # 'conditioned', so the census returns nothing on bare massing.
        import btap.modeling as modeling
        from btap.modeling.envelope import geometry
        import openstudio

        model = modeling.create(shape="rectangle", length=20, width=15,
                                storeys=1, below_grade_storeys=0)
        self.assertEqual(0, len(geometry.exposed_walls(model)["walls"]),
                         "no thermostats -> no conditioned walls")

        # Wizard output has spaces but NO thermal zones (faithful to legacy) —
        # zone + thermostat together are what 'conditioned' requires.
        for space in model.getSpaces():
            zone = openstudio.model.ThermalZone(model)
            space.setThermalZone(zone)
            thermostat = openstudio.model.ThermostatSetpointDualSetpoint(model)
            zone.setThermostatSetpointDualSetpoint(thermostat)
        census = geometry.exposed_walls(model)
        self.assertGreater(len(census["walls"]), 0)
        self.assertGreater(census["wall_area_m2"], 0)
        self.assertEqual(0.0, census["fdwr"], "wizard massing carries no windows")


if __name__ == "__main__":
    unittest.main()
