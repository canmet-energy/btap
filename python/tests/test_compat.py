"""The _compat contracts (D-79): each test pins the exact Ruby behaviour the
helper exists to reproduce. ruby_round was additionally fuzz-verified against
Ruby's Float#round on 19,154 generated cases at port time (zero mismatches)."""

import unittest

from btap._compat import (
    NullAudit,
    Raw,
    esc,
    opt,
    opt_or,
    ruby_float_str,
    ruby_round,
    ruby_str,
    sorted_by_name,
)


class TestRubyRound(unittest.TestCase):
    def test_half_rounds_away_from_zero_not_to_even(self):
        self.assertEqual(1, ruby_round(0.5))
        self.assertEqual(2, ruby_round(1.5))
        self.assertEqual(3, ruby_round(2.5))  # banker's would give 2
        self.assertEqual(-1, ruby_round(-0.5))
        self.assertEqual(-3, ruby_round(-2.5))
        self.assertEqual(0.13, ruby_round(0.125, 2))  # banker's would give 0.12

    def test_rounds_the_shortest_decimal_representation_like_ruby(self):
        # The double behind 2.675 is 2.67499...; Ruby (and this helper) still
        # round the printed value up. Python's round(2.675, 2) gives 2.67.
        self.assertEqual(2.68, ruby_round(2.675, 2))
        self.assertEqual(1.01, ruby_round(1.005, 2))
        self.assertEqual(0.14, ruby_round(0.135, 2))
        self.assertEqual(-2.68, ruby_round(-2.675, 2))

    def test_return_types_match_ruby_integer_float_split(self):
        self.assertIsInstance(ruby_round(3.7), int)
        self.assertIsInstance(ruby_round(3.7, 0), int)
        self.assertIsInstance(ruby_round(3.7, 1), float)
        self.assertEqual(3890.1, ruby_round(3890.05, 1))
        self.assertEqual(7, ruby_round(7, 3), "Integer#round(n>=0) is identity")


class TestOptionals(unittest.TestCase):
    class FakeOptional:
        def __init__(self, value=None):
            self._value = value

        def is_initialized(self):
            return self._value is not None

        def get(self):
            return self._value

    def test_opt_unwraps_or_none(self):
        self.assertEqual(42.0, opt(self.FakeOptional(42.0)))
        self.assertIsNone(opt(self.FakeOptional()))
        self.assertIsNone(opt(None))

    def test_opt_or_default(self):
        self.assertEqual(42.0, opt_or(self.FakeOptional(42.0), 7))
        self.assertEqual(7, opt_or(self.FakeOptional(), 7))


class TestNullAudit(unittest.TestCase):
    def test_absorbs_every_write_and_stays_empty(self):
        audit = NullAudit()
        audit.decision("build", "x", article="8.4.4.7.(1)")
        audit.info("build", "y")
        audit.warn("build", "z")
        with audit.with_building("proposed building"):
            audit.warn("build", "inside")
        self.assertEqual([], audit.entries)
        self.assertEqual([], audit.warnings)


class TestSortedByName(unittest.TestCase):
    class Named:
        def __init__(self, name):
            self._name = name

        def nameString(self):  # noqa: N802 — SDK camelCase
            return self._name

    def test_sorts_by_name_string(self):
        zones = [self.Named("Zone B"), self.Named("Zone A"), self.Named("Zone C")]
        self.assertEqual(["Zone A", "Zone B", "Zone C"],
                         [z.nameString() for z in sorted_by_name(zones)])


class TestHtmlEscape(unittest.TestCase):
    def test_exactly_rubys_four_substitutions(self):
        self.assertEqual("&amp;&lt;&gt;&quot;", esc('&<>"'))
        self.assertEqual("it's", esc("it's"), "apostrophe is NOT escaped (html.escape would)")
        self.assertEqual("25.0", esc(25.0), "values are stringified Ruby-style first")

    def test_raw_marker(self):
        self.assertEqual("<b>x</b>", Raw("<b>x</b>").html)


class TestRubyStr(unittest.TestCase):
    def test_scalars(self):
        self.assertEqual("", ruby_str(None))
        self.assertEqual("true", ruby_str(True))
        self.assertEqual("false", ruby_str(False))
        self.assertEqual("3890.0", ruby_str(3890.0))
        self.assertEqual("gas", ruby_str("gas"))

    def test_float_rendering_matches_ruby_to_s(self):
        self.assertEqual("1.0e+16", ruby_float_str(1e16))
        self.assertEqual("1.5e-05", ruby_float_str(1.5e-05))
        self.assertEqual("123456789.123", ruby_float_str(123456789.123))

    def test_arrays_render_like_ruby_array_to_s(self):
        self.assertEqual('[1, "a", 2.5, nil]', ruby_str([1, "a", 2.5, None]))


if __name__ == "__main__":
    unittest.main()


class TestRubyDivision(unittest.TestCase):
    """Ruby float division NEVER raises — the family-wide hazard found while
    porting the NECB lighting criteria, where dividing by a zero aperture
    area yields NaN and the ANDed comparison then correctly skips the
    inapplicable half. Python's ZeroDivisionError would turn that silent
    skip into a crash."""

    def test_division_by_zero_matches_ruby(self):
        import math
        from btap._compat import ruby_div
        self.assertEqual(math.inf, ruby_div(1.0, 0.0))
        self.assertEqual(-math.inf, ruby_div(-1.0, 0.0))
        self.assertTrue(math.isnan(ruby_div(0.0, 0.0)))
        self.assertEqual(-math.inf, ruby_div(1.0, -0.0), "signed zero, as Ruby")
        self.assertEqual(2.0, ruby_div(6.0, 3.0))

    def test_nan_comparison_is_false_as_in_ruby(self):
        from btap._compat import ruby_div
        self.assertFalse(ruby_div(0.0, 0.0) <= 0.006,
                         "NaN <= x is false in both languages — the skip criterion")


class TestRoundingNonFinite(unittest.TestCase):
    """Ruby: Infinity.round(2) == Infinity, NaN.round(4) == NaN, but
    .round with no digits must yield an Integer and so raises
    FloatDomainError. ruby_round used to raise InvalidOperation on infinity,
    which would crash any domain rounding a ruby_div result."""

    def test_non_finite_passes_through_with_digits(self):
        import math
        from btap._compat import ruby_round
        self.assertEqual(math.inf, ruby_round(math.inf, 2))
        self.assertEqual(-math.inf, ruby_round(-math.inf, 3))
        self.assertTrue(math.isnan(ruby_round(math.nan, 4)))

    def test_non_finite_to_integer_raises_like_ruby(self):
        import math
        from btap._compat import ruby_round
        for value in (math.inf, -math.inf, math.nan):
            with self.assertRaises(ValueError):
                ruby_round(value)
