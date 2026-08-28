"""Leg-C: Python envelope costing vs the ORACLE's own frozen values (D-78).

Consumes verification/oracle/goldens/costing_envelope.json — exported from
the PINNED openstudio-standards revision by verification/oracle/export_goldens.rb
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

- tbd_rsi:                   |Δ| < 1e-6, and identical key sets (both
  directions) — enabled with M7. The golden's values are TBD.rsi on a
  prescriptive-applied fixture; the Python side reproduces the model
  recipe (apply_prescriptive → 0.3 WWR on the first outdoors wall →
  apply_prescriptive again) and compares Quantify.rsi_of.
"""

import json
import unittest

from btap._compat import ruby_round, ruby_str
from tests.support import oracle_goldens_dir

GOLDEN = oracle_goldens_dir() / "costing_envelope.json"

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

    def test_tbd_rsi_matches_the_oracle(self):
        """The golden's 'tbd_rsi' surfaces/sub_surfaces are TBD.rsi values
        frozen from the pinned oracle on a prescriptive-applied fixture
        (export_oracle_goldens.rb: apply_prescriptive -> WWR 0.3 on the
        FIRST outdoors wall in SDK order -> apply_prescriptive again).
        Reproduced here with Quantify.rsi_of (surfaces WITH films,
        subsurfaces without — the exact TBD.rsi(lc, filmResistance) /
        TBD.rsi(lc, 0) split the probe used), enabled with M7."""
        from btap.audit import AuditLog
        from btap.costing.envelope.quantify import GROUND_BOUNDARIES, rsi_of
        from btap.necb import envelope
        from tests.necb.support import load_raw_fixture

        model = load_raw_fixture()
        envelope.apply_prescriptive(model, vintage="2020", hdd=3890,
                                    audit=AuditLog())
        wall = next(s for s in model.getSurfaces()
                    if s.outsideBoundaryCondition() == "Outdoors"
                    and s.surfaceType() == "Wall")
        wall.setWindowToWallRatio(0.3)
        envelope.apply_prescriptive(model, vintage="2020", hdd=3890,
                                    audit=AuditLog())

        legacy = golden()["tbd_rsi"]
        surfaces = {}
        for surface in sorted(model.getSurfaces(),
                              key=lambda x: x.nameString()):
            base = surface.construction()
            if base.is_initialized() and \
                    base.get().to_LayeredConstruction().is_initialized() and \
                    (surface.outsideBoundaryCondition() == "Outdoors"
                     or surface.outsideBoundaryCondition() in GROUND_BOUNDARIES):
                surfaces[surface.nameString()] = rsi_of(surface, film=True)
        sub_surfaces = {}
        for sub in sorted(model.getSubSurfaces(),
                          key=lambda x: x.nameString()):
            base = sub.construction()
            if base.is_initialized() and \
                    base.get().to_LayeredConstruction().is_initialized():
                sub_surfaces[sub.nameString()] = rsi_of(sub, film=False)

        # key sets, BOTH directions — a comparison that silently shrinks
        # would pass vacuously
        self.assertEqual(sorted(legacy["surfaces"]), sorted(surfaces))
        self.assertEqual(sorted(legacy["sub_surfaces"]), sorted(sub_surfaces))
        for name, rsi in legacy["surfaces"].items():
            self.assertAlmostEqual(rsi, surfaces[name], delta=1e-6,
                                   msg=f"surface {name} RSI")
        for name, rsi in legacy["sub_surfaces"].items():
            self.assertAlmostEqual(rsi, sub_surfaces[name], delta=1e-6,
                                   msg=f"sub surface {name} RSI")


if __name__ == "__main__":
    unittest.main()
