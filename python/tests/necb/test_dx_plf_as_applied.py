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

import re
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
#: The region where the engine's PLF field can actually HOLD the transformed
#: Article target, as (from, to). It is NOT contiguous for heating, and
#: D-102's first version said it was: the exact target rises above the 1.0
#: ceiling from PLR 0.815 to full load, so there is a seam at EACH end.
#: Sol found this because the comparison below clipped the target to the
#: carrier before differencing, which cannot reveal that the carrier
#: truncates the target — the same shape as the 0.25 floor he refused.
REPRESENTABLE = {"heating": (0.1661, 0.8149), "cooling": (0.1745, 1.0)}
REPRESENTABLE_FROM = {k: v[0] for k, v in REPRESENTABLE.items()}

#: Where the heating target crosses ABOVE what the field accepts. Pinned to
#: the digits so the seam cannot silently widen.
UPPER_SEAM = {"heating": 0.8149996906315529, "cooling": None}
#: Its peak excess over the ceiling, and where.
UPPER_SEAM_PEAK = {"heating": (1.002358, 0.9055)}
#: Three DIFFERENT things live in the top of this domain and D-102's first
#: version named only the last: (a) the Code's target exceeds the field's
#: ceiling from the seam to full load; (b) the shipped polynomial UNDER-delivers
#: against that target, worst at PLR 0.8437; (c) the engine's 1.0 clamp only
#: becomes active much higher, where the polynomial itself overshoots.
UPPER_SEAM_WORST_SHORTFALL = {"heating": (0.951, 0.8437)}
CLAMP_ACTIVE_FROM = {"heating": 0.953}
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
        for kind in sorted(REPRESENTABLE):
            with self.subTest(kind=kind):
                curve = self.coil_plf_curve(kind)
                lo, hi = REPRESENTABLE[kind]
                worst, at = 0.0, None
                for step in range(0, 201):
                    plr = lo + (hi - lo) * step / 200
                    # UNCLIPPED. Clipping the target to CARRIER_HI here is what
                    # hid the upper seam: a target trimmed to the bound being
                    # validated cannot show that the bound trims the target.
                    want = exact_plf(kind, plr)
                    self.assertLessEqual(
                        want, CARRIER_HI + 1e-9,
                        f"{kind}: PLR {plr:.4f} is inside the declared "
                        "representable region but its exact target exceeds the "
                        "carrier — the region bounds are wrong, not the curve")
                    rel = abs(curve.evaluate(plr) - want) / want * 100.0
                    if rel > worst:
                        worst, at = rel, plr
                self.assertLess(
                    worst, TOLERANCE_PERCENT[kind],
                    f"{kind}: {worst:.2f}% from the Article at PLR {at:.3f}, "
                    f"as the coil's own curve evaluates it")

    def test_above_the_carrier_CEILING_the_gap_is_DECLARED_too(self):
        """The seam at the OTHER end, which D-102's first version missed.

        The heating Article's transformed target rises ABOVE 1.0 over roughly
        the top fifth of the domain and returns to exactly 1.0 only at full
        load. EnergyPlus will not accept a part-load fraction over 1.0, so the
        reference delivers 1.0 there and the Code implies slightly more. The
        excess is small — 0.236 % at its peak — but it is a region the Code
        states and the carrier cannot hold, which is the same kind of thing as
        the floor and was disclosed only at the floor.

        Cooling has NO upper seam. Asserting its absence keeps the asymmetry
        deliberate rather than incidental.
        """
        for kind in sorted(REPRESENTABLE):
            with self.subTest(kind=kind):
                curve, seam = self.coil_plf_curve(kind), UPPER_SEAM[kind]
                if seam is None:
                    worst = max(exact_plf(kind, i / 1000.0)
                                for i in range(1, 1001))
                    self.assertLessEqual(
                        worst, CARRIER_HI + 1e-9,
                        f"{kind}: this curve is declared to have no upper "
                        f"seam, but its target reaches {worst:.6f}")
                    continue
                # The ROOT, not a bracket. Sol moved this constant from
                # 0.81499969 to 0.82 and every test stayed green, because a
                # +/-0.01 bracket proves only that the crossing is somewhere
                # in a 0.02-wide window — which is not what "pinned to the
                # digits" claims. The seam is where the exact target EQUALS
                # the ceiling, so assert that, then bracket it tightly enough
                # that the published digits are what passes.
                self.assertAlmostEqual(
                    CARRIER_HI, exact_plf(kind, seam), places=9,
                    msg=f"{kind}: the seam is the ROOT of "
                        "exact_plf(PLR) = 1.0; this is the published value")
                self.assertLess(
                    exact_plf(kind, seam - 1e-6), CARRIER_HI,
                    f"{kind}: one micro-step below, the target still fits")
                self.assertGreater(
                    exact_plf(kind, seam + 1e-6), CARRIER_HI,
                    f"{kind}: one micro-step above, it does not")
                peak, at = UPPER_SEAM_PEAK[kind]
                self.assertAlmostEqual(
                    peak, exact_plf(kind, at), places=5,
                    msg=f"{kind}: the peak excess D-102 publishes")
                # (b) the coil can deliver AT MOST the ceiling here, and in
                # fact delivers LESS, because the polynomial under-runs the
                # target before the clamp is anywhere near active. An earlier
                # version of this test asserted the coil delivers exactly 1.0
                # and failed, which is how the distinction surfaced.
                worst, worst_at = UPPER_SEAM_WORST_SHORTFALL[kind]
                self.assertLessEqual(curve.evaluate(at), CARRIER_HI + 1e-9, kind)
                measured, m_at = 0.0, None
                for step in range(0, 201):
                    plr = seam + (1.0 - seam) * step / 200
                    want = exact_plf(kind, plr)
                    rel = abs(curve.evaluate(plr) - want) / want * 100.0
                    if rel > measured:
                        measured, m_at = rel, plr
                self.assertAlmostEqual(
                    worst, measured, places=2,
                    msg=f"{kind}: the shortfall across the seam region is "
                        f"{measured:.3f}% at PLR {m_at:.4f}; D-102 publishes "
                        f"{worst}%")
                # (c) and the clamp is a SEPARATE fact, active only up here
                self.assertLess(
                    curve.evaluate(CLAMP_ACTIVE_FROM[kind] - 0.01), CARRIER_HI,
                    f"{kind}: below this the polynomial does not overshoot")
                self.assertAlmostEqual(
                    CARRIER_HI, curve.evaluate(1.0), places=6,
                    msg=f"{kind}: at full load the clamp removes the "
                        "polynomial's own 1.0077 overshoot")

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

    def test_the_PUBLISHED_region_matches_the_one_the_seams_define(self):
        """The shipped note must state the region the arithmetic actually has.

        This is the defect's SECOND form. The first revision declared the
        upper seam in D-102's prose while the curve notes and the
        accepted-error table still said heating was representable over
        `[0.1661, 1.0]` — the decision contradicting itself inside the same
        change, which Sol caught. Fixing an instance is not fixing the class,
        so the published interval is checked against the same constants the
        seam tests use.
        """
        import json

        from btap.codes.necb import _data_root

        NAMES = {"heating": "DXHEAT-REF-PLFFPLR",
                 "cooling": "DXCOOL-REF-COOLPLFFPLR"}
        for edition in ("necb2020", "necb2025"):
            data = json.loads((_data_root() / edition / "efficiencies.json")
                              .read_text(encoding="utf-8"))
            for kind, name in sorted(NAMES.items()):
                with self.subTest(edition=edition, kind=kind):
                    row = next(c for c in data["curves"]
                               if isinstance(c, dict) and c.get("name") == name)
                    shown = re.search(
                        r"representable region PLR \[([\d.]+), ([\d.]+)([)\]])",
                        row.get("notes") or "")
                    self.assertIsNotNone(
                        shown, f"{edition}/{kind}: the note must STATE its "
                               "representable region, or nothing keeps it honest")
                    self.assertAlmostEqual(
                        REPRESENTABLE[kind][0], float(shown.group(1)), places=4,
                        msg=f"{kind}: the note's lower bound")
                    seam = UPPER_SEAM[kind]
                    self.assertAlmostEqual(
                        seam if seam else 1.0, float(shown.group(2)), places=2,
                        msg=f"{kind}: the note says the region runs to "
                            f"{shown.group(2)}, but the seam puts it at "
                            f"{seam if seam else 1.0}")
                    self.assertEqual(
                        ")" if seam else "]", shown.group(3),
                        f"{kind}: a region ENDED by a seam is open at the top; "
                        "one that reaches full load is closed")

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
