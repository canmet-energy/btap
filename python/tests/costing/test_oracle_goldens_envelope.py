"""Leg-C: Python envelope costing vs the ORACLE's own frozen values (D-78).

Consumes btap-necb/test/goldens/oracle/costing_envelope.json — exported from
the PINNED openstudio-standards revision by scripts/export_oracle_goldens.rb
via the same probes the Ruby parity gates run (OracleProbes::Costing) — and
reproduces every value with the PORTED code, under the SAME tolerances the
Ruby gate (btap-necb/test/test_envelope_costing_parity.rb) uses:

- interpolations:            |Δ| < 1e-9
- construction_costs:        |Δ| < 0.011  (per-layer cent rounding)
- tb_material_quantities:    |Δ| < 1e-9, and identical key sets

This makes Python ≡ oracle DIRECTLY: a bug faithfully ported from Ruby fails
here even when Ruby↔Python and Ruby↔oracle each agree. The golden's dollars
were priced from the vendored PLACEHOLDER costs.csv (the package's own data/
copy — the default resolution), never licensed values.

The 'tbd_rsi' key SKIPS: reproducing it means running TBD on the fixture,
which needs the M7 bridge.
"""

import json
import unittest

from btap._compat import ruby_round, ruby_str
from tests.support import REPO_ROOT

GOLDEN = (REPO_ROOT / "btap-necb" / "test" / "goldens" / "oracle"
          / "costing_envelope.json")

# The exact probe inputs behind the golden keys (OracleProbes::Costing).
INTERPOLATE_POINT_SETS = (
    [[1.0, 10.0], [2.0, 20.0], [4.0, 30.0]],
    [[0.5, 100.0], [0.9, 90.0], [1.7, 260.0], [3.2, 410.0]],
    [[2.0, 55.5]],
)
INTERPOLATE_XS = (0.4, 0.5, 0.55, 0.99, 1.0, 1.5, 2.0, 3.05, 3.99, 4.0,
                  4.05, 4.2, 9.0)
TB_TALLIES = {"parapet": {"BTAP-ExteriorWall-SteelFramed-1 good": 100.0},
              "jamb": {"BTAP-ExteriorWall-SteelFramed-1 good": 50.0},
              "sill": {"BTAP-ExteriorWall-SteelFramed-1 good": 25.0},
              "rimjoist": {"BTAP-ExteriorWall-SteelFramed-1 good": 30.0},
              "transition": {"BTAP-ExteriorWall-SteelFramed-1 good": 500.0}}
CITY = "TORONTO"
PROVINCE = "ONTARIO"


def golden():
    with open(GOLDEN, encoding="utf-8") as f:
        return json.load(f)


class TestOracleGoldensEnvelope(unittest.TestCase):
    def test_interpolations_match_the_oracle(self):
        from btap.costing.envelope.interpolate import interpolate
        legacy_values = golden()["interpolations"]
        checked = set()
        mismatches = []
        for set_index, points in enumerate(INTERPOLATE_POINT_SETS):
            for x in INTERPOLATE_XS:
                key = f"{set_index}/{ruby_str(float(x))}"
                legacy_value = legacy_values[key]
                value = interpolate(x_y_array=[list(p) for p in points], x2=x).value
                checked.add(key)
                if abs(legacy_value - value) >= 1e-9:
                    mismatches.append((key, legacy_value, value))
        self.assertEqual(sorted(legacy_values), sorted(checked),
                         "every frozen interpolation reproduced (39 entries)")
        self.assertEqual([], mismatches,
                         f"interpolate mismatches vs oracle: {mismatches[:8]}")

    def test_construction_costs_match_the_oracle_every_candidate(self):
        from btap.costing.envelope import envelope_costs
        from btap.costing.envelope.database import Database
        legacy_costs = golden()["construction_costs"]
        database = Database()
        checked = set()
        mismatches = []

        for sheet, assemblies_by_name in database.constructions.items():
            for assembly in assemblies_by_name:
                candidates = database.construction_candidates(sheet, assembly)
                for rsi, construction in candidates.items():
                    key = f"{sheet}/{assembly}/{ruby_str(ruby_round(rsi, 3))}"
                    legacy_cost = legacy_costs[key]
                    cost = envelope_costs.construction_cost(
                        database, construction, PROVINCE, CITY)
                    checked.add(key)
                    # the Ruby gate's tolerance: per-layer cent rounding
                    if abs(legacy_cost - cost) >= 0.011:
                        mismatches.append((key, legacy_cost, cost))

        self.assertGreaterEqual(len(checked), 90,
                                "every candidate in every assembly catalog "
                                "compared (92 in the vendored catalogs)")
        self.assertEqual(sorted(legacy_costs), sorted(checked),
                         "the frozen keys and the catalogs walk the same set")
        self.assertEqual([], mismatches,
                         f"$ mismatches (key, oracle, port): {mismatches[:8]}")

    def test_tb_material_quantities_match_the_oracle(self):
        from btap.costing.envelope import thermal_bridging_costs
        from btap.costing.envelope.database import Database
        legacy_quantities = golden()["tb_material_quantities"]
        database = Database()
        quantities, _rows = thermal_bridging_costs.material_quantities(
            TB_TALLIES, database, None)
        for material_id, quantity in legacy_quantities.items():
            self.assertAlmostEqual(quantity, quantities[str(material_id)],
                                   delta=1e-9,
                                   msg=f"material {material_id} quantity")
        self.assertEqual(sorted(str(k) for k in legacy_quantities),
                         sorted(str(k) for k in quantities))

    @unittest.skip("needs TBD bridge (M7)")
    def test_tbd_rsi_matches_the_oracle(self):
        """The golden's 'tbd_rsi' surfaces/sub_surfaces were computed on a
        prescriptive-applied fixture whose uprated_Uo comes from TBD.process;
        reproducing them needs the M7 TBD bridge (tolerance there: 1e-6)."""


if __name__ == "__main__":
    unittest.main()
