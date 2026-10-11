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
#: The part-load ratio the defect witness is quoted at. The floor that
#: shipped is NOT a free constant: the defect was putting the CARRIER's
#: own floor on the input axis, so it IS `CARRIER_LO` and is bound to it.
#: Sol (`205`, `207`) moved a free version to 0.75, updated the block to
#: what it then computed, and every test passed while the witness no
#: longer described the shipped defect.
DEFECT_PLR = 0.25
OLD_INPUT_FLOOR = CARRIER_LO
#: Slack for comparisons AGAINST a carrier edge. The seam root equals the
#: ceiling by construction, so its evaluation differs between platforms by
#: an ULP; CI saw 1.0000000000000002 where this host saw 1.0.
CARRIER_EPS = 1e-9
#: Below this PLR the Article's target falls under the carrier floor and is NOT
#: representable. D-102 records that as a declared gap; it is not a tolerance.
#: The region where the engine's PLF field can actually HOLD the transformed
#: Article target, as (from, to). It is NOT contiguous for heating, and
#: D-102's first version said it was: the exact target rises above the 1.0
#: ceiling from PLR 0.815 to full load, so there is a seam at EACH end.
#: Sol found this because the comparison below clipped the target to the
#: carrier before differencing, which cannot reveal that the carrier
#: truncates the target — the same shape as the 0.25 floor he refused.
#: CLOSED at the root: the target EQUALS the ceiling there, which is what
#: makes it the root, so the point is representable. The first version wrote
#: this half-open and asserted the endpoint was open — encoding the error
#: instead of detecting it (Sol, `191`).
#: Both ends are ROOTS, published to their digits. Fable (`198`) mutated the
#: heating floor from 0.1661 to 0.30 in this constant AND both shipped notes
#: and every test still passed: the upper seam was pinned to nine places
#: while the LOWER seams — the boundary of this decision's central finding —
#: were pinned to nothing. They were also rounded INWARD, which excludes the
#: worst sliver of the region and understated cooling as 12.645% where its
#: own root gives 12.663%.
REPRESENTABLE = {"heating": (0.16604619095565545, 0.8149996906315529),
                 "cooling": (0.17442759262761687, 1.0)}
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
UPPER_SEAM_WORST_SHORTFALL = {"heating": (0.9509, 0.8437)}
CLAMP_ACTIVE_FROM = {"heating": 0.953}
#: The fit error D-102 accepts where the mapping IS representable, per curve.
TOLERANCE_PERCENT = {"heating": 3.0, "cooling": 13.0}


def _poly(coef, x):
    return sum(k * x ** i for i, k in enumerate(coef))


def _raw_poly(kind, plr):
    """The shipped cubic BEFORE the engine's output clamps.

    `curve.evaluate()` returns the clamped value, so it cannot show where the
    polynomial itself crosses the ceiling — which is what the clamp onset IS.
    """
    import json

    from btap.codes.necb import _data_root

    data = json.loads((_data_root() / "necb2020" / "efficiencies.json")
                      .read_text(encoding="utf-8"))
    name = {"heating": "DXHEAT-REF-PLFFPLR",
            "cooling": "DXCOOL-REF-COOLPLFFPLR"}[kind]
    row = next(c for c in data["curves"]
               if isinstance(c, dict) and c.get("name") == name)
    c = [row["coeff_1"], row["coeff_2"], row["coeff_3"], row["coeff_4"]]
    return sum(k * plr ** i for i, k in enumerate(c))


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
                        want, CARRIER_HI + CARRIER_EPS,
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
                # And the figure this measures is PUBLISHED, so require every
                # surface to publish THIS one. Fable `202`: `worst` and `at`
                # were computed here and thrown away, so 12.663% -> 12.645%
                # and 0.181558 -> 0.1816 passed on D-102 and on both shipped
                # notes. A tolerance check proves the curve is close enough;
                # it says nothing about whether the documents quote the number
                # that was measured.

    def test_the_LOWER_seam_is_the_root_too(self):
        """The floor end of the declared gap, pinned like the ceiling end.

        D-102's central finding is the region below the carrier floor, and its
        boundary was the one number in this file pinned to nothing: Fable
        moved it from 0.1661 to 0.30 here and in both shipped notes and
        every test passed. It was also rounded INWARD, so the published
        cooling maximum was measured from inside its own region and came out
        12.645% where the root gives 12.663%.
        """
        for kind in sorted(REPRESENTABLE):
            with self.subTest(kind=kind):
                lo = REPRESENTABLE[kind][0]
                self.assertAlmostEqual(
                    CARRIER_LO, exact_plf(kind, lo), places=9,
                    msg=f"{kind}: the lower seam is the ROOT of "
                        "exact_plf(PLR) = 0.7, not a rounded neighbour")
                self.assertGreater(
                    exact_plf(kind, lo + 1e-6), CARRIER_LO,
                    f"{kind}: one micro-step above, the target clears the floor")
                self.assertLess(
                    exact_plf(kind, lo - 1e-6), CARRIER_LO,
                    f"{kind}: one micro-step below, it does not — so the "
                    "declared gap is open at this end as well")

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
                        worst, CARRIER_HI + CARRIER_EPS,
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
                # The root ITSELF is representable — equality, not exclusion
                # — so the gap is OPEN at this end. Asserting the endpoint was
                # open is the error Sol found in `191`.
                #
                # The tolerance is NOT decoration. This value is the root, so
                # it equals the ceiling BY CONSTRUCTION, and a quantity equal
                # by construction lands on either side of it in floating
                # point: it evaluated to exactly 1.0 on the development host
                # and to 1.0000000000000002 — one ULP high — on CI, where a
                # bare `assertLessEqual` failed. A strict inequality against a
                # value defined by equality is the bug, not the platform.
                self.assertLessEqual(
                    exact_plf(kind, seam), CARRIER_HI + CARRIER_EPS,
                    f"{kind}: the root is IN the representable set")
                self.assertLess(
                    exact_plf(kind, seam - 1e-6), CARRIER_HI,
                    f"{kind}: one micro-step below, the target still fits")
                self.assertGreater(
                    exact_plf(kind, seam + 1e-6), CARRIER_HI,
                    f"{kind}: one micro-step above, it does not — so the gap "
                    "is open at the root")
                # The full-load point is NOT in the gap. The Article's
                # coefficients sum to exactly 1, so EIR_FPLR(1.0) = 1 and the
                # target is exactly the ceiling there — the representable set
                # is DISCONNECTED, and describing it as a half-open region up
                # to the seam discards a point the Code and the carrier agree
                # on. Sol raised the isolated endpoint; this pins it.
                self.assertAlmostEqual(
                    1.0, sum(ARTICLE_EIR_FPLR[kind]), places=12,
                    msg=f"{kind}: the Article cubic is normalised at full load")
                self.assertAlmostEqual(
                    CARRIER_HI, exact_plf(kind, 1.0), places=12,
                    msg=f"{kind}: so the target is representable AT 1.0")
                peak, at = UPPER_SEAM_PEAK[kind]
                self.assertAlmostEqual(
                    peak, exact_plf(kind, at), places=5,
                    msg=f"{kind}: the peak excess, which D-102 now states only as a BOUND — less than a quarter of a percent — so this test is where the exact value lives")
                # (b) the coil can deliver AT MOST the ceiling here, and in
                # fact delivers LESS, because the polynomial under-runs the
                # target before the clamp is anywhere near active. An earlier
                # version of this test asserted the coil delivers exactly 1.0
                # and failed, which is how the distinction surfaced.
                worst, worst_at = UPPER_SEAM_WORST_SHORTFALL[kind]
                # Assert what is actually TRUE here, which is that the clamp is
                # NOT active at the peak: the polynomial reads 0.9951, below
                # the ceiling, so the shortfall is the fit's and not the
                # carrier's. The previous assertion — delivered <= ceiling —
                # could not fail under any product mutation, because the
                # polynomial is below the ceiling at this PLR whatever the
                # bound says, while its comment claimed a check it never
                # performed (Fable, `198`).
                self.assertLess(
                    curve.evaluate(at), CARRIER_HI - 1e-4,
                    f"{kind}: at the peak the polynomial sits BELOW the "
                    "ceiling, so the clamp is not what causes the shortfall "
                    "here — if this fails, the clamp has reached the peak and "
                    "the account of (b) versus (c) no longer holds")
                measured, m_at = 0.0, None
                for step in range(0, 201):
                    plr = seam + (1.0 - seam) * step / 200
                    want = exact_plf(kind, plr)
                    rel = abs(curve.evaluate(plr) - want) / want * 100.0
                    if rel > measured:
                        measured, m_at = rel, plr
                self.assertAlmostEqual(
                    worst, measured, places=3,
                    msg=f"{kind}: the shortfall across the seam region is "
                        f"{measured:.3f}% at PLR {m_at:.4f}; D-102 publishes "
                        f"{worst}%")
                # (c) and the clamp is a SEPARATE fact, active only up here
                # The onset is where the POLYNOMIAL crosses the ceiling, so
                # assert the crossing, not a neighbourhood. The previous
                # version bracketed at +/-0.01 and so admitted anything in
                # [0.943, 0.963) — Fable passed it 0.945 and 0.960 — while
                # D-102 publishes 0.953 to three decimals and the file's own
                # comments condemn exactly this shape for the upper seam.
                onset = CLAMP_ACTIVE_FROM[kind]
                self.assertAlmostEqual(
                    CARRIER_HI, _raw_poly(kind, onset), places=4,
                    msg=f"{kind}: {onset} is where the polynomial REACHES the "
                        "ceiling; this is the published onset")
                self.assertLess(
                    _raw_poly(kind, onset - 1e-3), CARRIER_HI,
                    f"{kind}: a millistep below, it has not reached it")
                self.assertGreater(
                    _raw_poly(kind, onset + 1e-3), CARRIER_HI,
                    f"{kind}: a millistep above, it has — so the clamp "
                    "becomes active HERE and not 0.01 either way")
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

    def test_the_EVIDENCE_BLOCK_is_computed(self):
        """D-102's one evidence block, RENDERED from the constants and compared
        whole.

        This replaces four guards that each chased the figures the previous
        review round had moved. Fable's `204` census ended that approach: 70
        figures in the body, 5 tied to a computation, ~55 tied to nothing —
        including the headline the decision exists for.

        The first version of THIS guard checked each field as a substring, and
        `206` showed four ways past it: swapping the witness's target and
        delivered values (which INVERTS the defect — a reference
        over-penalising instead of under-penalising — and still matches),
        renaming a row label, changing the quoted PLR, and appending a second
        stale block below the real one. A substring search cannot see
        structure, order, or duplication.

        So the whole block is rendered from the derived values and compared as
        one string, and the document must contain exactly one of them.
        """
        import pathlib as _p

        source = (_p.Path(__file__).resolve().parents[3]
                  / "docs" / "decisions" / "D-102.md")
        if not source.is_file():
            self.skipTest(f"{source} is not present in this layout")
        text = source.read_text(encoding="utf-8")

        # Count the FENCE, independently of whether its content already
        # looks like the expected block. Sol (`207`) appended a second valid
        # `text` fence whose first content line was blank and everything
        # passed: a count that keys on `representable set` being the first
        # characters cannot see a stale block that starts differently, which
        # is the one a careless edit would leave.
        fenced = re.findall(r"```text\n(.*?)```", text, re.S)
        self.assertEqual(
            1, len(fenced),
            f"D-102 must carry EXACTLY ONE fenced `text` block and carries "
            f"{len(fenced)}; a second is a copy that can go stale, and any "
            "search would read only one of them")
        blocks = [b for b in fenced if b.strip().startswith("representable set")]
        self.assertEqual(
            1, len(blocks),
            "that one block must be the evidence block, starting "
            "'representable set'")

        heat_lo, heat_hi = REPRESENTABLE["heating"]
        cool_lo, cool_hi = REPRESENTABLE["cooling"]
        # EVERY declared endpoint is derived, cooling's upper one included.
        # It used to be a free constant: Sol moved it to 0.9 in the constant
        # AND the block and all 8 tests passed, because the no-upper-seam
        # branch proves the target never EXCEEDS the ceiling through 1.0 and
        # never that the declared set REACHES 1.0 (`205`). Two independent
        # facts pin it — the engine's own input domain, and the Article cubic
        # being normalised there.
        for kind, hi in (("heating", heat_hi), ("cooling", cool_hi)):
            curve = self.coil_plf_curve(kind)
            if UPPER_SEAM[kind] is None:
                self.assertEqual(
                    curve.maximumValueofx(), hi,
                    f"{kind}: with no upper seam the representable set runs to "
                    "the engine's own input maximum, not to a free constant")
                self.assertAlmostEqual(
                    CARRIER_HI, exact_plf(kind, hi), places=9,
                    msg=f"{kind}: and the Article is normalised there, so the "
                        "target equals the ceiling at that endpoint")
        heat_worst, _ = self.measured_maximum("heating")
        cool_worst, _ = self.measured_maximum("cooling")
        target = exact_plf("heating", DEFECT_PLR)
        delivered = max(CARRIER_LO,
                        min(CARRIER_HI, _raw_poly("heating", OLD_INPUT_FLOOR)))
        as_applied = abs(delivered - target) / target * 100
        raw = abs(_raw_poly("heating", DEFECT_PLR) - target) / target * 100
        self.assertAlmostEqual(CARRIER_LO, exact_plf("heating", heat_lo), places=9)
        self.assertAlmostEqual(CARRIER_LO, exact_plf("cooling", cool_lo), places=9)
        self.assertAlmostEqual(CARRIER_HI, exact_plf("heating", heat_hi), places=9)

        expected = (
            f"representable set   heating  [{heat_lo}, {heat_hi}] union {{1.0}}\n"
            f"                    cooling  [{cool_lo}, {cool_hi}]\n"
            f"worst as applied    heating  {heat_worst:.3f}%    "
            f"cooling  {cool_worst:.3f}%\n"
            f"defect corrected    at PLR {DEFECT_PLR} the curve delivered "
            f"{delivered:.4f} against an Article\n"
            f"                    target of {target:.4f} \u2014 "
            f"{as_applied:.1f}% as applied, {raw:.1f}% raw"
        )
        def flat(s):
            return "\n".join(" ".join(x.split())
                              for x in s.strip().split("\n"))
        self.assertEqual(
            flat(expected), flat(blocks[0]),
            "the evidence block must be EXACTLY what the shipped curve and the "
            "Article cubic produce — every figure, every label, and the order "
            "of the witness's target and delivered values, which swapped "
            "inverts the defect this decision corrects")

    def measured_maximum(self, kind):
        """Worst as-applied relative error over the representable set."""
        lo, hi = REPRESENTABLE[kind]
        curve, worst, at = self.coil_plf_curve(kind), 0.0, None
        for i in range(20_001):
            plr = lo + (hi - lo) * i / 20_000
            want = exact_plf(kind, plr)
            rel = abs(curve.evaluate(plr) - want) / want * 100.0
            if rel > worst:
                worst, at = rel, plr
        return worst, at

    def test_the_note_ENDPOINTS_are_the_pinned_ones(self):
        """The endpoints kept in the notes as row data, tied to the constants.

        Sol's `203` directed keeping the exact endpoints in the curve notes —
        they are data about the row, unlike the maxima, which are adjudication
        evidence and now live only in the evidence block. But deleting the old
        region guard left them unpinned: changing NECB 2020's heating note
        lower root to `0.266046...` left every test green (`205`). A provenance
        hash detects changed BYTES; refreshing the manifest blesses the wrong
        sentence.

        This is one row-metadata contract, not a return to four evidence
        surfaces. It checks only the endpoints, and only that they are the
        same ones the seam tests derive.
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
                    notes, seam = row.get("notes") or "", UPPER_SEAM[kind]
                    lo, hi = REPRESENTABLE[kind]
                    wanted = (f"PLR [{lo}, {seam!r}] union {{1.0}}" if seam
                              else f"PLR [{lo}, {hi}]")
                    self.assertIn(
                        wanted, notes,
                        f"{edition}/{kind}: the note must state the pinned "
                        f"endpoints verbatim — {wanted}")
                    # Exactly ONE region statement per note. Fable (`208`)
                    # judged the substring defensible here — it is
                    # bracket-delimited with both endpoints in order, so no
                    # digit changes undetected — but a stale SECOND statement
                    # appended beside the pinned one would pass, which is the
                    # duplication shape this decision was corrected for twice.
                    self.assertEqual(
                        1, notes.count("PLR ["),
                        f"{edition}/{kind}: one region statement, not two — a "
                        "copy is a place to drift")

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
