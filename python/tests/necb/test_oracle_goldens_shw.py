"""Leg-C: the ported SHW domain vs the ORACLE's own frozen values (D-78).

Consumes btap-necb/test/goldens/oracle/shw.json — exported from the PINNED
openstudio-standards revision by scripts/export_oracle_goldens.rb through the
same probes the Ruby parity gate runs (OracleProbes::Shw) — and reproduces
every value with the PORTED code, under the SAME tolerances the Ruby gate
(btap-necb/test/test_shw_shw_parity.rb) uses:

- tank_volume_m3:          |Δ| < 1e-9
- capacity_w:              |Δ| < capacity_w * 1e-6
- parasitic_w:             |Δ| < 1e-6
- fuel:                    equal
- water_use peak_flow_m3s: |Δ| < 1e-12, same spaces, same schedules
- efficiency / ua_w_k:     |Δ| < 1e-9
- plf_curve / parasitic_frac_to_tank: equal

This makes Python ≡ oracle DIRECTLY: a bug faithfully ported from Ruby fails
here even when Ruby↔Python and Ruby↔oracle each agree.

Golden shape (asserted, so a shrunken comparison fails loudly):
``swh`` carries 2 keys (heater + water_use, the latter 5 demanding spaces) and
``efficiencies`` 9 bins — one per OracleProbes::Shw::EFFICIENCY_CASES entry.

The oracle side is model_add_swh(swh_fueltype: 'NaturalGas', shw_scale: 1.0)
on the tagged fixture, and water_heater_mixed_apply_efficiency on a bare
WaterHeaterMixed per case.
"""

from __future__ import annotations

import json
import unittest

from btap._compat import ruby_str
from tests.necb.support import needs_sdk, tagged_model
from tests.support import REPO_ROOT

GOLDEN = REPO_ROOT / "btap-necb" / "test" / "goldens" / "oracle" / "shw.json"

# The exact probe inputs behind the golden keys (OracleProbes::Shw).
EFFICIENCY_CASES = (
    ("Electricity", 11_000, 0.200),   # electric small, low volume
    ("Electricity", 11_000, 0.300),   # electric small, >=270 L formula
    ("Electricity", 40_000, 0.300),   # electric large
    ("NaturalGas", 15_000, 0.100),    # gas 76-208 L (FHR 221 -> 193-284 bin)
    ("NaturalGas", 15_000, 0.150),    # gas 76-208 L (FHR 256)
    ("NaturalGas", 20_000, 0.300),    # gas 208-380 L (FHR 361 -> >=284 bin)
    ("NaturalGas", 25_000, 0.400),    # gas 22-30.5 kW row
    ("NaturalGas", 100_000, 0.500),   # large gas: Et + SL
    ("FuelOilNo2", 15_000, 0.150),    # oil follows the gas path (legacy)
)


def golden():
    with open(GOLDEN, encoding="utf-8") as f:
        return json.load(f)


def water_use_signatures(model):
    """Port of OracleProbes::Signatures.water_use_signatures (unrounded — the
    frozen side carries the rounding, the tolerance absorbs it)."""
    equipment = sorted(model.getWaterUseEquipments(),
                       key=lambda w: w.space().get().nameString())
    return [{"space": w.space().get().nameString(),
             "peak_flow_m3s": w.waterUseEquipmentDefinition().peakFlowRate(),
             "schedule": (w.flowRateFractionSchedule().get().nameString()
                          if w.flowRateFractionSchedule().is_initialized() else None)}
            for w in equipment]


def water_heater_efficiency_signature(heater):
    """Port of OracleProbes::Signatures.water_heater_efficiency_signature."""
    from btap._compat import opt
    return {"efficiency": opt(heater.heaterThermalEfficiency()),
            "ua_w_k": opt(heater.offCycleLossCoefficienttoAmbientTemperature()),
            "plf_curve": heater.partLoadFactorCurve().is_initialized(),
            "parasitic_frac_to_tank": heater.offCycleParasiticHeatFractiontoTank()}


@needs_sdk
class TestOracleGoldensSHW(unittest.TestCase):
    def test_the_golden_carries_the_shape_this_test_checks(self):
        data = golden()
        self.assertEqual(["efficiencies", "swh"], sorted(data))
        self.assertEqual(["heater", "water_use"], sorted(data["swh"]),
                         "swh: 2 keys")
        self.assertEqual(5, len(data["swh"]["water_use"]),
                         "five demanding spaces in the tagged fixture")
        self.assertEqual(9, len(data["efficiencies"]), "efficiencies: 9 bins")

    def test_demand_and_tank_match_the_oracle(self):
        from btap.necb import shw

        legacy_sig = golden()["swh"]

        model = tagged_model()
        shw.apply_shw(model, vintage="2020", fuel="NaturalGas")

        heaters = model.getWaterHeaterMixeds()
        self.assertIsNotNone(legacy_sig["heater"])
        self.assertTrue(heaters)
        heater = heaters[0]
        self.assertAlmostEqual(legacy_sig["heater"]["tank_volume_m3"],
                               heater.tankVolume().get(), delta=1e-9,
                               msg="tank volume (legacy peak-hour rule)")
        self.assertAlmostEqual(legacy_sig["heater"]["capacity_w"],
                               heater.heaterMaximumCapacity().get(),
                               delta=legacy_sig["heater"]["capacity_w"] * 1e-6,
                               msg="tank capacity")
        self.assertAlmostEqual(legacy_sig["heater"]["parasitic_w"],
                               heater.onCycleParasiticFuelConsumptionRate(),
                               delta=1e-6, msg="parasitic loss")
        self.assertEqual(legacy_sig["heater"]["fuel"], heater.heaterFuelType())

        legacy_wue = legacy_sig["water_use"]
        wue = water_use_signatures(model)
        self.assertEqual(len(legacy_wue), len(wue), "same demanding spaces")
        # Key-set equality BOTH directions: the frozen spaces and the built
        # spaces are the same set, so neither side can silently shrink.
        self.assertEqual(sorted(entry["space"] for entry in legacy_wue),
                         sorted(entry["space"] for entry in wue))
        for legacy_entry, entry in zip(legacy_wue, wue):
            self.assertEqual(legacy_entry["space"], entry["space"])
            self.assertAlmostEqual(legacy_entry["peak_flow_m3s"], entry["peak_flow_m3s"],
                                   delta=1e-12,
                                   msg=f"peak flow for {legacy_entry['space']}")
            self.assertEqual(legacy_entry["schedule"], entry["schedule"])

    def test_efficiency_every_bin_matches_the_oracle(self):
        import openstudio

        from btap.necb import shw

        legacy_bins = golden()["efficiencies"]
        checked = set()
        mismatches = []
        for fuel, capacity_w, volume_m3 in EFFICIENCY_CASES:
            model = openstudio.model.Model()
            heater = openstudio.model.WaterHeaterMixed(model)
            heater.setTankVolume(volume_m3)
            heater.setHeaterMaximumCapacity(capacity_w)
            heater.setHeaterFuelType(fuel)
            shw.apply_water_heater_efficiency(heater, vintage="2020")

            key = f"{fuel}/{capacity_w}/{ruby_str(volume_m3)}"
            legacy = legacy_bins[key]
            checked.add(key)
            signature = water_heater_efficiency_signature(heater)
            if (abs(legacy["efficiency"] - signature["efficiency"]) < 1e-9
                    and abs(legacy["ua_w_k"] - signature["ua_w_k"]) < 1e-9
                    and legacy["plf_curve"] == signature["plf_curve"]
                    and legacy["parasitic_frac_to_tank"]
                    == signature["parasitic_frac_to_tank"]):
                continue

            mismatches.append(
                f"{fuel} {capacity_w}W {volume_m3}m3: eff {legacy['efficiency']} vs "
                f"{signature['efficiency']}; UA {legacy['ua_w_k']} vs "
                f"{signature['ua_w_k']}; curve {legacy['plf_curve']}/"
                f"{signature['plf_curve']}")

        self.assertEqual(sorted(legacy_bins), sorted(checked),
                         "every frozen efficiency bin reproduced (9 entries), and no "
                         "bin checked that the golden does not hold")
        self.assertEqual([], mismatches,
                         "efficiency parity mismatches:\n" + "\n".join(mismatches))
