"""Port of btap-necb/test/test_report_model_query.rb: ModelQuery — SDK ->
plain dicts for the renderer (one of the two SDK-touching renderer files,
with the assembler). Verifies envelope aggregation (incl. the SimpleGlazing
uFactor fallback) and nil-safety."""

import unittest

from btap.necb.report import model_query as MQ
from tests.necb.support import compliance_fixture, needs_sdk


@needs_sdk
class TestReportModelQuery(unittest.TestCase):
    def test_nil_model(self):
        self.assertIsNone(MQ.extract(None))

    def test_envelope_aggregation(self):
        model = compliance_fixture()
        data = MQ.extract(model)
        types = [s["type"] for s in data["envelope"]["surfaces"]]
        self.assertIn("Wall", types)
        self.assertIn("RoofCeiling", types)
        wall = next(s for s in data["envelope"]["surfaces"]
                    if s["type"] == "Wall")
        self.assertGreater(wall["area_m2"], 0)
        self.assertTrue(wall["avg_u_w_per_m2k"] is None
                        or wall["avg_u_w_per_m2k"] > 0)

    def test_simple_glazing_u_fallback(self):
        import openstudio

        model = compliance_fixture()
        glazing = openstudio.model.SimpleGlazing(model)
        glazing.setUFactor(2.4)
        glazing.setSolarHeatGainCoefficient(0.4)
        construction = openstudio.model.Construction(model)
        construction.insertLayer(0, glazing)
        surface = next(s for s in model.getSurfaces()
                       if s.outsideBoundaryCondition() == "Outdoors"
                       and s.surfaceType() == "Wall")
        surface.setConstruction(construction)
        u = MQ.construction_conductance(surface.construction())
        self.assertAlmostEqual(2.4, u, delta=0.2,
                               msg="SimpleGlazing constructions fall back to "
                                   "uFactor")


if __name__ == "__main__":
    unittest.main()
