"""The DX part-load-fraction curves, evaluated THROUGH THE PRODUCT, must match
the Article where EnergyPlus can carry it — and the gap must be named where it
cannot.

Two verification failures produced this file, one inside the fix for the other.

**The first.** `DXHEAT-REF-PLFFPLR` shipped with
`minimum_independent_variable_1 = 0.7`, putting EnergyPlus's PLF floor on the
INPUT axis, so every part-load ratio below 0.7 evaluated at the 0.7 value and
the cycling penalty disappeared — 23.0% from the Article as applied, while
`test_hvac_part_load_curves.py` reported 1.8% because it evaluates raw
COEFFICIENTS and the defect lived in a BOUND.

**The second was mine.** The replacement test read the JSON row and built its
own `CurveCubic`. It was a SECOND IMPLEMENTATION of the path it claimed to
test: Sol killed `set_limits()`'s output-bound writer and every assertion
still passed, and two data mutations survived with it (Sol, `187`).

So nothing here constructs a curve. Every assertion builds a real coil through
`btap.modeling.hvac.components.coils`, reads the curve the COIL carries, and
evaluates it — which is the only arrangement that can see a bound the product
fails to write.
"""

from __future__ import annotations

import unittest

from tests.support import needs_sdk

#: The Article's own EIR_FPLR cubic. `PLF = PLR / EIR_FPLR` is the mapping
#: D-102 adopts; the Code states EIR_FPLR and says nothing about EnergyPlus's
#: PLF field or its bounds.
ARTICLE_EIR_FPLR = {
    "heating": (0.0856522, 0.9388137, -0.1834361, 0.1589702),
    "cooling": (0.2012301, -0.0312175, 1.9504979, -1.1205105),
}
#: EnergyPlus constrains its cycling PLF carrier to [0.7, 1.0] and samples the
#: field over 0.0-1.0 (`DXCoils.cc`, 25.2.0). Neither bound is in the Code.
CARRIER_LO, CARRIER_HI = 0.7, 1.0
#: Below this PLR the Article's target falls under the carrier floor and is NOT
#: representable. D-102 records that as a declared gap; it is not a tolerance.
REPRESENTABLE_FROM = {"heating": 0.1661, "cooling": 0.1745}
#: The fit error D-102 accepts where the mapping IS representable, per curve.
TOLERANCE_PERCENT = {"heating": 3.0, "cooling": 13.0}


def exact_plf(kind, plr):
    eir = sum(c * plr ** i for i, c in enumerate(ARTICLE_EIR_FPLR[kind]))
    return plr / eir


@needs_sdk
class TestDxPartLoadFractionAsApplied(unittest.TestCase):
    def coil_plf_curve(self, kind):
        """The PLF curve the PRODUCT leaves on a real coil after its own pass.

        Three stages matter and only the last is the answer:

        1. `coils.py` builds the coil with `btap.modeling`'s own
           `data/curves.json`, which still carries `min_x = 0.7` and NO output
           bounds — modeling cannot read NECB data under D-77;
        2. `efficiency.apply` replaces that curve with the edition's, but
           RETURNS EARLY on an unsized coil ("DX heating capacity unavailable
           (model not sized?)"), so a bare coil silently keeps stage 1;
        3. only a coil with a capacity reaches the NECB curve.

        A probe that stops at stage 1 or 2 reads modeling's default and
        concludes the NECB data never arrives. I made that mistake before
        checking the early return.
        """
        import openstudio

        from btap.codes.necb.hvac import efficiency
        from btap.modeling.hvac.components import coils

        model = openstudio.model.Model()
        schedule = openstudio.model.ScheduleConstant(model)
        schedule.setValue(1.0)
        if kind == "heating":
            coil = coils.dx_heating_single_speed(model, schedule)
            coil.setRatedTotalHeatingCapacity(20000.0)
            coil.setRatedAirFlowRate(1.0)
            coil.setRatedCOP(3.0)
        else:
            coil = coils.dx_cooling_single_speed(model, schedule)
            coil.setRatedTotalCoolingCapacity(20000.0)
            coil.setRatedSensibleHeatRatio(0.75)
            coil.setRatedAirFlowRate(1.0)
            coil.setRatedCOP(3.0)
        efficiency.apply(model, code="necb2020")
        return coil.partLoadFractionCorrelationCurve().to_CurveCubic().get()

    def test_the_product_writes_all_four_bounds(self):
        """The mutation that survived last time: killing the output writer.

        A curve with no declared output bounds evaluates to 1.0077 at full
        load and has no floor at all, and no numeric comparison starting
        above the floor can notice.
        """
        for kind in sorted(ARTICLE_EIR_FPLR):
            with self.subTest(kind=kind):
                curve = self.coil_plf_curve(kind)
                self.assertEqual(0.0, curve.minimumValueofx(),
                                 f"{kind}: the engine samples from 0.0; a higher "
                                 "input floor is an unsourced clamp (Sol, `187`)")
                self.assertEqual(1.0, curve.maximumValueofx(), kind)
                # The SDK is asymmetric here: the INPUT bounds come back as
                # plain floats and the OUTPUT bounds as Optionals, so an
                # `assertEqual` against the raw accessor compares a float to
                # an Optional and fails even when the value is right.
                lo_out, hi_out = curve.minimumCurveOutput(), curve.maximumCurveOutput()
                self.assertTrue(
                    lo_out.is_initialized() and hi_out.is_initialized(),
                    f"{kind}: the product must write BOTH output bounds; "
                    "killing that writer is the mutation that survived before")
                self.assertEqual(
                    CARRIER_LO, lo_out.get(),
                    f"{kind}: the engine's PLF floor belongs HERE, on the "
                    "OUTPUT axis")
                self.assertEqual(
                    CARRIER_HI, hi_out.get(),
                    f"{kind}: the upper bound removes a real 1.0077 full-load "
                    "overshoot, so its absence is not cosmetic")

    def test_as_applied_matches_the_article_where_the_carrier_can_hold_it(self):
        for kind, floor in sorted(REPRESENTABLE_FROM.items()):
            with self.subTest(kind=kind):
                curve = self.coil_plf_curve(kind)
                worst, at = 0.0, None
                for step in range(0, 201):
                    plr = floor + (1.0 - floor) * step / 200
                    want = min(exact_plf(kind, plr), CARRIER_HI)
                    rel = abs(curve.evaluate(plr) - want) / want * 100.0
                    if rel > worst:
                        worst, at = rel, plr
                self.assertLess(
                    worst, TOLERANCE_PERCENT[kind],
                    f"{kind}: {worst:.2f}% from the Article at PLR {at:.3f}, "
                    f"as the coil's own curve evaluates it")

    def test_below_the_carrier_floor_the_gap_is_DECLARED_not_hidden(self):
        """The region D-102 may not call verified.

        As PLR approaches zero the Article's EIR cubic keeps its non-zero
        intercept, so the exact PLF tends to zero while EnergyPlus will not
        accept a value under 0.7. Starting a tolerance at 0.25 renamed that
        out of scope; this asserts it exists and is bounded by the floor.
        """
        for kind, floor in sorted(REPRESENTABLE_FROM.items()):
            with self.subTest(kind=kind):
                curve = self.coil_plf_curve(kind)
                self.assertAlmostEqual(
                    CARRIER_LO, curve.evaluate(floor / 2.0), places=6,
                    msg=f"{kind}: under the floor the carrier can only deliver "
                        "0.7, which is the declared gap")
                self.assertLess(
                    exact_plf(kind, floor / 2.0), CARRIER_LO,
                    f"{kind}: and the Article's own target there IS below the "
                    "floor — if this fails the floor is no longer the reason")

    def test_both_editions_ship_the_same_curve(self):
        """One curve per quantity, or it needs an edition-qualified name as
        D-89's modulating boiler has."""
        import json

        from btap.codes.necb import _data_root

        for name in ("DXHEAT-REF-PLFFPLR", "DXCOOL-REF-COOLPLFFPLR"):
            with self.subTest(curve=name):
                rows = []
                for edition in ("necb2020", "necb2025"):
                    data = json.loads((_data_root() / edition / "efficiencies.json")
                                      .read_text(encoding="utf-8"))
                    row = next(c for c in data["curves"]
                               if isinstance(c, dict) and c.get("name") == name)
                    rows.append({k: v for k, v in row.items() if k != "notes"})
                self.assertEqual(rows[0], rows[1],
                                 f"{name} differs between editions")

    def test_every_curve_note_cites_D_102(self):
        """The runtime ruling lives in the decision, and the data points at it."""
        import json

        from btap.codes.necb import _data_root

        for edition in ("necb2020", "necb2025"):
            data = json.loads((_data_root() / edition / "efficiencies.json")
                              .read_text(encoding="utf-8"))
            for name in ("DXHEAT-REF-PLFFPLR", "DXCOOL-REF-COOLPLFFPLR"):
                with self.subTest(edition=edition, curve=name):
                    row = next(c for c in data["curves"]
                               if isinstance(c, dict) and c.get("name") == name)
                    self.assertIn("D-102", row.get("notes") or "",
                                  f"{edition}/{name}: a bound choice the Code "
                                  "does not make must cite its decision")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
