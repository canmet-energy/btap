"""The DX part-load-fraction curves must be equivalent to the Article AS THE
ENGINE EVALUATES THEM, not as their coefficients read.

`DXHEAT-REF-PLFFPLR` shipped with `minimum_independent_variable_1 = 0.7`,
which placed EnergyPlus's PLF FLOOR on the INPUT axis. Every part-load ratio
below 0.7 therefore evaluated at the 0.7 value and the cycling penalty
disappeared:

    PLR 0.25   Article target 0.8029   delivered 0.9877   (+23.0%)

The raw polynomial fits the Article to 1.8%, and the existing part-load probe
reported exactly that, because it evaluated coefficients and never the curve
`coils.py` installs. A verification that takes a cheaper path than runtime
cannot see a bound (Sol, `185`).

So every assertion here goes THROUGH `openstudio.model.CurveCubic`, built the
way the product builds it, and `evaluate()` applies the bounds.
"""

from __future__ import annotations

import json
import unittest

from btap.codes.necb import _data_root
from tests.support import needs_sdk

#: The Article's own EIR_FPLR cubics, per edition, and the PLR range they are
#: stated over. PLF = PLR / EIR_FPLR is the transform both curves realise.
ARTICLE = {
    "necb2020": {
        "DXHEAT-REF-PLFFPLR": ("8.4.5.7.(5)",
                               (0.0856522, 0.9388137, -0.1834361, 0.1589702)),
        "DXCOOL-REF-COOLPLFFPLR": ("8.4.5.4.(5)",
                                   (0.2012301, -0.0312175, 1.9504979, -1.1205105)),
    },
    "necb2025": {
        "DXHEAT-REF-PLFFPLR": ("8.4.6.7.(5)",
                               (0.0856522, 0.9388137, -0.1834361, 0.1589702)),
        "DXCOOL-REF-COOLPLFFPLR": ("8.4.6.4.(5)",
                                   (0.2012301, -0.0312175, 1.9504979, -1.1205105)),
    },
}
PLR_LO, PLR_HI = 0.25, 1.0
#: The polynomials are fits, so some residual is expected. 3% is well above
#: the 1.8% both curves achieve and far below the 23% a misplaced bound gave,
#: so it separates "a fit" from "a bound on the wrong axis".
TOLERANCE_PERCENT = 3.0


def article_plf(coefficients, plr):
    eir = sum(c * plr ** i for i, c in enumerate(coefficients))
    return plr / eir


@needs_sdk
class TestDxPartLoadFractionAsApplied(unittest.TestCase):
    def curve(self, edition, name):
        """The curve as the PRODUCT builds it, bounds included."""
        import openstudio

        data = json.loads(
            (_data_root() / edition / "efficiencies.json").read_text(encoding="utf-8"))
        spec = next(c for c in data["curves"]
                    if isinstance(c, dict) and c.get("name") == name)
        self.assertEqual("Cubic", spec["form"], f"{name} is no longer a cubic")
        model = openstudio.model.Model()
        curve = openstudio.model.CurveCubic(model)
        curve.setCoefficient1Constant(spec["coeff_1"])
        curve.setCoefficient2x(spec["coeff_2"])
        curve.setCoefficient3xPOW2(spec["coeff_3"])
        curve.setCoefficient4xPOW3(spec["coeff_4"])
        if spec.get("minimum_independent_variable_1") is not None:
            curve.setMinimumValueofx(spec["minimum_independent_variable_1"])
        if spec.get("maximum_independent_variable_1") is not None:
            curve.setMaximumValueofx(spec["maximum_independent_variable_1"])
        if spec.get("minimum_dependent_variable_output") is not None:
            curve.setMinimumCurveOutput(spec["minimum_dependent_variable_output"])
        if spec.get("maximum_dependent_variable_output") is not None:
            curve.setMaximumCurveOutput(spec["maximum_dependent_variable_output"])
        return spec, curve

    def test_as_applied_plf_tracks_the_article_over_its_whole_PLR_range(self):
        for edition, curves in sorted(ARTICLE.items()):
            for name, (article, coefficients) in sorted(curves.items()):
                with self.subTest(edition=edition, curve=name):
                    _spec, curve = self.curve(edition, name)
                    worst, at = 0.0, None
                    for step in range(0, 151):
                        plr = PLR_LO + (PLR_HI - PLR_LO) * step / 150
                        want = article_plf(coefficients, plr)
                        rel = abs(curve.evaluate(plr) - want) / want * 100.0
                        if rel > worst:
                            worst, at = rel, plr
                    self.assertLess(
                        worst, TOLERANCE_PERCENT,
                        f"{edition}/{name}: {worst:.2f}% from {article} at PLR "
                        f"{at:.3f} AS APPLIED. A bound on the wrong axis reads "
                        "as a good fit in the coefficients and a 23% error in "
                        "the engine")

    def test_the_PLF_floor_is_on_the_OUTPUT_axis_not_the_INPUT(self):
        """The specific defect, named so it cannot come back quietly.

        EnergyPlus floors PLF at 0.7. On the OUTPUT that is the floor. On the
        INPUT it silently freezes every part-load ratio below 0.7 at the 0.7
        value, which is where the cycling penalty went.
        """
        for edition, curves in sorted(ARTICLE.items()):
            for name in sorted(curves):
                with self.subTest(edition=edition, curve=name):
                    spec, _curve = self.curve(edition, name)
                    self.assertLessEqual(
                        spec["minimum_independent_variable_1"], PLR_LO,
                        f"{edition}/{name}: the curve must be evaluable over "
                        "the Article's own PLR range; a 0.7 input minimum is "
                        "the PLF floor on the wrong axis")
                    self.assertEqual(
                        0.7, spec["minimum_dependent_variable_output"],
                        f"{edition}/{name}: the 0.7 floor belongs HERE")

    def test_the_two_editions_ship_the_same_curve(self):
        for name in sorted(ARTICLE["necb2020"]):
            with self.subTest(curve=name):
                a, _ = self.curve("necb2020", name)
                b, _ = self.curve("necb2025", name)
                fields = ("coeff_1", "coeff_2", "coeff_3", "coeff_4",
                          "minimum_independent_variable_1",
                          "maximum_independent_variable_1",
                          "minimum_dependent_variable_output",
                          "maximum_dependent_variable_output")
                self.assertEqual(
                    {f: a.get(f) for f in fields}, {f: b.get(f) for f in fields},
                    f"{name} differs between editions; if that is intended it "
                    "needs an edition-qualified name, as D-89 does for the "
                    "modulating boiler")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
