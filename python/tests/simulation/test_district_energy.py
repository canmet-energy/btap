"""Purchased heating reaches report.json in either medium (D-89, sixth amendment).

From OpenStudio 3.7 ``SqlFile.districtHeatingTotalEndUses`` is water PLUS steam
(``SqlFile_Impl::districtHeatingTotalEndUses`` returns
``addTwoOptionalDoubles(districtHeatingWaterTotalEndUses(),
districtHeatingSteamTotalEndUses())``), so ``runner.energy_results`` must ask
for it FIRST; the water-only accessor is only the fallback for an SDK without
the combined one. SDK-free: the accessors are faked, so these tests pin the
ORDER in which runner asks; the SDK's water-plus-steam arithmetic itself was
verified by reading the OpenStudio 3.11.0 source, not by this file.
"""

import unittest

from btap.simulation import runner

GJ = 1.0
KWH_PER_GJ = 277.8  # ruby_round(1 GJ x 277.777778, 1)


class _Optional:
    def __init__(self, value):
        self._value = value

    def is_initialized(self):
        return self._value is not None

    def get(self):
        return self._value


class _SqlWithCombinedAccessor:
    """What OpenStudio 3.11 exposes: combined, water and steam."""

    def districtHeatingTotalEndUses(self):
        return _Optional(1.0 * GJ)  # water 0.4 + steam 0.6

    def districtHeatingWaterTotalEndUses(self):
        return _Optional(0.4 * GJ)

    def districtHeatingSteamTotalEndUses(self):
        return _Optional(0.6 * GJ)


class _SqlWithoutCombinedAccessor:
    def districtHeatingWaterTotalEndUses(self):
        return _Optional(0.4 * GJ)


class TestDistrictHeatingCoversSteam(unittest.TestCase):
    NAMES = ["districtHeatingTotalEndUses", "districtHeatingWaterTotalEndUses"]

    def test_the_combined_accessor_is_asked_first(self):
        self.assertEqual(KWH_PER_GJ, runner._district(_SqlWithCombinedAccessor(), self.NAMES),
                         'water plus steam, not water alone')

    def test_the_water_accessor_is_only_the_fallback(self):
        self.assertEqual(111.1, runner._district(_SqlWithoutCombinedAccessor(), self.NAMES))

    def test_energy_results_asks_in_that_order(self):
        import inspect
        source = inspect.getsource(runner.energy_results)
        self.assertLess(source.index('"districtHeatingTotalEndUses"'),
                        source.index('"districtHeatingWaterTotalEndUses"'))


if __name__ == '__main__':
    unittest.main()
