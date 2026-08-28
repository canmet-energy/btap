"""Leg-C: the Python ENVELOPE domain vs the ORACLE's own frozen values (D-78).

Consumes the three envelope goldens under btap-necb/test/goldens/oracle/ —
exported from the PINNED openstudio-standards revision by
scripts/export_oracle_goldens.rb via the same probes the Ruby parity gates run
(OracleProbes::Envelope) — and reproduces every value with the PORTED code,
under the SAME tolerances the Ruby gates
(test_envelope_lookup_parity.rb / test_envelope_prescriptive_parity.rb /
test_envelope_data_integrity.rb) use:

- envelope_lookups.json    max_u 126 entries      |Δ| < 1e-9
                           max_fdwr 14 entries    |Δ| < 1e-9
                           srr_max                |Δ| < 1e-9
                           hdd18 1 entry          EXACT (assert_equal)
- envelope_prescriptive.json  conductances 9 entries  |Δ| <= 1e-3
                              fdwr                    |Δ| < 0.01
                              fixture / weather        the probe's own inputs
- envelope_u_table.json    outdoors 6 + ground 3 surface rows, structural
                           equality with the vendored 2020 u_values

This makes Python ≡ oracle DIRECTLY: a bug faithfully ported from Ruby fails
here even when Ruby↔Python and Ruby↔oracle each agree. Every comparison
asserts KEY-SET EQUALITY IN BOTH DIRECTIONS, so a shrunken comparison fails
loudly instead of silently checking fewer entries than the golden holds.

The costing golden's 'tbd_rsi' key is consumed in tests/costing (enabled
with M7); the envelope domain's TBD path runs through the pinned py-tbd
engine (see test_envelope_thermal_bridging.py).
"""

from __future__ import annotations

import json
import unittest

from tests.necb.support import EPW, load_raw_fixture, needs_sdk
from tests.support import REPO_ROOT

GOLDEN_DIR = REPO_ROOT / "btap-necb" / "test" / "goldens" / "oracle"

# The exact probe inputs behind the golden keys (OracleProbes::Envelope).
HDD_SWEEP = [0, 1500, 2999, 3000, 3999, 4000, 4001, 5500, 6999, 7000, 8000,
             9998, 9999, 12_000]
SURFACES = {"outdoors": ["wall", "roofceiling", "floor", "window", "skylight", "door"],
            "ground": ["wall", "roofceiling", "floor"]}


def golden(name):
    with open(GOLDEN_DIR / f"{name}.json", encoding="utf-8") as handle:
        return json.load(handle)


def attach_weather(model):
    """Ruby FixtureHelper#attach_weather! — the EPW half; the DDY design days
    matter only to EnergyPlus, never to HDD resolution or the prescriptive
    transform."""
    import openstudio

    epw = openstudio.EpwFile(openstudio.path(str(EPW)))
    openstudio.model.WeatherFile.setWeatherFile(model, epw)
    return model


def surface_conductances(model):
    """Port of OracleProbes::Signatures.surface_conductances — the signature
    builder used on BOTH sides, so gem and oracle values are comparable."""
    from btap._compat import opt, ruby_round, sorted_by_name

    out = {}
    for s in sorted_by_name(model.getSurfaces()):
        if s.outsideBoundaryCondition() not in ("Outdoors", "Ground", "Foundation"):
            continue
        if s.isGroundSurface() and s.surfaceType() == "Floor":
            continue
        construction = opt(s.construction())
        layered = None if construction is None else opt(construction.to_Construction())
        if layered is None:
            continue

        conductance = layered.thermalConductance()
        out[s.nameString()] = ruby_round(
            conductance.get() if conductance.is_initialized() else 0.0, 4)
    return out


@needs_sdk
class TestOracleGoldensEnvelope(unittest.TestCase):
    @property
    def n(self):
        from btap.necb import envelope
        return envelope

    # ------------------------------------------------------- envelope_lookups
    def test_max_u_matches_the_oracle_full_sweep(self):
        legacy_values = golden("envelope_lookups")["max_u"]
        checked = set()
        mismatches = []
        for boundary, surfaces in SURFACES.items():
            for surface in surfaces:
                for hdd in HDD_SWEEP:
                    key = f"{boundary}/{surface}/{hdd}"
                    legacy_u = legacy_values[key]
                    u = self.n.max_u(vintage="2020", surface=surface,
                                     boundary=boundary, hdd=hdd)
                    checked.add(key)
                    if abs(u - legacy_u) >= 1e-9:
                        mismatches.append((key, legacy_u, u))
        self.assertEqual(126, len(checked),
                         "(6 outdoors + 3 ground) surfaces x 14 HDD-sweep points")
        self.assertEqual(sorted(legacy_values), sorted(checked),
                         "the frozen keys and the sweep walk the same set")
        self.assertEqual([], mismatches,
                         f"max_u mismatches vs oracle: {mismatches[:8]}")

    def test_max_fdwr_matches_the_oracle_sweep(self):
        legacy_values = golden("envelope_lookups")["max_fdwr"]
        checked = set()
        mismatches = []
        for hdd in HDD_SWEEP:
            key = str(hdd)
            legacy_v = legacy_values[key]
            v = self.n.max_fdwr(vintage="2020", hdd=hdd)
            checked.add(key)
            if abs(v - legacy_v) >= 1e-9:
                mismatches.append((key, legacy_v, v))
        self.assertEqual(14, len(checked), "the 14-point HDD sweep")
        self.assertEqual(sorted(legacy_values), sorted(checked))
        self.assertEqual([], mismatches,
                         f"max_fdwr mismatches vs oracle: {mismatches}")

    def test_srr_max_matches_the_oracle(self):
        legacy_srr = golden("envelope_lookups")["srr_max"]
        self.assertAlmostEqual(legacy_srr, self.n.max_srr(vintage="2020"), delta=1e-9)

    def test_hdd18_matches_the_oracle(self):
        legacy_values = golden("envelope_lookups")["hdd18"]
        checked = set()
        for name, legacy_hdd in legacy_values.items():
            self.assertEqual(EPW.name, name,
                             "the golden's only HDD probe is the shared Toronto EPW")
            model = attach_weather(load_raw_fixture())
            hdd = self.n.climate.hdd18(model)
            checked.add(name)
            # Ruby's gate is assert_equal: the nearest-Table-C-1-city HDD is an
            # integer from the vendored table, never a computed float.
            self.assertEqual(legacy_hdd, hdd,
                             "nearest-Table-C-1-city HDD must match the oracle")
        self.assertEqual(sorted(legacy_values), sorted(checked))

    def test_lookups_golden_has_exactly_the_probed_sections(self):
        """Both directions at the top level too: a new probe section in the
        golden must not go unconsumed."""
        self.assertEqual(["hdd18", "max_fdwr", "max_u", "srr_max"],
                         sorted(golden("envelope_lookups")))

    # --------------------------------------------------- envelope_prescriptive
    def test_prescriptive_conductances_match_the_oracle(self):
        legacy = golden("envelope_prescriptive")
        legacy_c = legacy["conductances"]
        self.assertEqual("5ZoneNoHVAC.osm", legacy["fixture"],
                         "the probe ran on the shared fixture")
        self.assertEqual(EPW.name, legacy["weather"])

        # include_films=False — this is a MECHANISM-parity gate against legacy
        # apply_standard_construction_properties (BTAP, construction-only
        # conductance); the port's default is include_films=True (code-literal,
        # matching the OSut path the NECB2020 prototypes actually use).
        # PORT NOTE: the Ruby gate first calls the oracle's
        # std.model_add_constructions so both sides start from the same base
        # assemblies. That method is oracle-side only; the fixture's own
        # constructions reach the identical targets here because
        # include_films=False makes the target the table U itself, which
        # opaque_at_conductance solves for exactly.
        model = attach_weather(load_raw_fixture())
        self.n.apply_prescriptive(model, vintage="2020", include_films=False)
        c = surface_conductances(model)

        mismatches = [(name, legacy_c[name], c.get(name))
                      for name in legacy_c
                      if c.get(name) is None or abs(legacy_c[name] - c[name]) > 1e-3]
        self.assertEqual([], mismatches, f"conductance mismatches: {mismatches}")
        self.assertEqual(9, len(legacy_c),
                         "meaningful surface count compared (ground floors excluded "
                         "per D-32)")
        self.assertEqual(sorted(legacy_c), sorted(c),
                         "the frozen surfaces and the ported walk the same set")

    def test_prescriptive_fdwr_matches_the_oracle(self):
        from btap.modeling.envelope import geometry as Geometry

        legacy_fdwr = golden("envelope_prescriptive")["fdwr"]
        model = attach_weather(load_raw_fixture())
        self.n.apply_prescriptive(model, vintage="2020", apply_fdwr=True)
        census = Geometry.exposed_walls(model)
        self.assertAlmostEqual(
            legacy_fdwr, census["fdwr"], delta=0.01,
            msg="FDWR after mutation matches legacy apply_max_fdwr_nrcan")

    def test_prescriptive_golden_has_exactly_the_probed_sections(self):
        self.assertEqual(["conductances", "fdwr", "fixture", "note", "weather"],
                         sorted(golden("envelope_prescriptive")))

    # ------------------------------------------------------- envelope_u_table
    def test_u_table_matches_the_oracle(self):
        """The pinned oracle's own NECB2020
        surface_thermal_transmittance.json node — the Ruby suite's
        test_2020_matches_legacy_surface_thermal_transmittance, which needs the
        oracle checked out. Here it is the frozen probe output (D-78 Leg C)."""
        legacy = golden("envelope_u_table")
        u_values = self.n.rules("2020")["u_values"]

        self.assertEqual(sorted(legacy), sorted(u_values),
                         "same boundaries both directions")
        self.assertEqual(6, len(legacy["outdoors"]), "6 outdoors surface rows")
        self.assertEqual(3, len(legacy["ground"]), "3 ground surface rows")
        for boundary, surfaces in legacy.items():
            self.assertEqual(sorted(surfaces), sorted(u_values[boundary]),
                             f"{boundary}: same surface rows both directions")
            for surface, bins in surfaces.items():
                self.assertEqual(sorted(bins), sorted(u_values[boundary][surface]),
                                 f"{boundary}/{surface}: same HDD bins both directions")
        self.assertEqual(legacy, u_values,
                         "vendored 2020 U-values must equal legacy data structurally")


if __name__ == "__main__":
    unittest.main()
