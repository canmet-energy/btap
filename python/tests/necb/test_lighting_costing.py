"""P4 gate: lighting fixture costing on real spaces — set matching, height bins,
zone multipliers, loud daylighting note, and the D-77 provider seam (the NECB
layer supplies the daylighted-area geometry btap.costing deliberately does not
own).

Port of btap-necb/test/test_lighting_costing.rb. Its last case
(``test_legacy_parity_led_2020``) is a Leg-A gate against the LIVE pinned
oracle and cannot run here; its Leg-C twin — the frozen ``lighting_costing``
golden — is asserted in test_oracle_goldens_lighting.py instead (D-78).
"""

import unittest

from tests.necb.support import load_raw_fixture, needs_sdk

CITY = "TORONTO"
PROVINCE = "ONTARIO"
OFFICE = ["Space Function", "Office enclosed > 25 m2"]


def costed_fixture_model(lights_type="NECB_Default"):
    from btap.necb import lighting, loads

    model = load_raw_fixture()
    map_ = {s.nameString(): list(OFFICE) for s in model.getSpaces()}
    loads.assign_space_types(model, map_, vintage="2020")
    lighting.apply_lights(model, vintage="2020", lights_type=lights_type)
    return model


@needs_sdk
class TestCosting(unittest.TestCase):
    def test_fixture_costing_end_to_end(self):
        from btap.audit import AuditLog
        from btap.necb import lighting

        audit = AuditLog()
        report = lighting.cost(costed_fixture_model(), vintage="2020",
                               city=CITY, province_state=PROVINCE, audit=audit)
        self.assertGreater(report.total, 0)
        self.assertEqual(5, len(report.lighting["space_report"]), "all five fixture spaces costed")
        for line in report.lighting["space_report"]:
            self.assertGreater(line["cost"], 0, line["space"])
            self.assertTrue(line["fixture_type"])
            self.assertGreater(line["height_avg_ft"], 0)
        total_from_lines = sum(line["cost"] for line in report.lighting["space_report"])
        self.assertAlmostEqual(report.total, total_from_lines, delta=0.1)
        self.assertTrue(any("no daylighting controls" in e["action"] for e in audit.entries))
        self.assertEqual(0, sum(1 for w in report.warnings if "regional adjustment" in w))

    def test_zone_multiplier_scales(self):
        from btap.necb import lighting

        base = lighting.cost(costed_fixture_model(), vintage="2020",
                             city=CITY, province_state=PROVINCE)
        scaled_model = costed_fixture_model()
        for z in scaled_model.getThermalZones():
            z.setMultiplier(2)
        scaled = lighting.cost(scaled_model, vintage="2020", city=CITY, province_state=PROVINCE)
        self.assertAlmostEqual(base.total * 2.0, scaled.total, delta=base.total * 0.01)

    def test_cfl_request_falls_back_to_led_only_2020_catalog(self):
        from btap.audit import AuditLog
        from btap.necb import lighting

        audit = AuditLog()
        cfl = lighting.cost(costed_fixture_model(lights_type="NECB_Default"),
                            vintage="2020", city=CITY, province_state=PROVINCE, audit=audit)
        led = lighting.cost(costed_fixture_model(lights_type="LED"),
                            vintage="2020", city=CITY, province_state=PROVINCE)
        self.assertAlmostEqual(led.total, cfl.total, delta=0.05,
                               msg="NECB2020 sets are LED-only; CFL-modeled lights cost through "
                                   "the same LED sets (why legacy forces LED)")
        self.assertTrue(any("carries only LED" in e["action"] for e in audit.entries))

    def test_daylighting_sensors_costed(self):
        from btap.audit import AuditLog
        from btap.necb import lighting

        model = costed_fixture_model()
        wall = next(s for s in model.getSurfaces()
                    if s.outsideBoundaryCondition() == "Outdoors" and s.surfaceType() == "Wall")
        wall.setWindowToWallRatio(0.3)
        audit = AuditLog()
        created = lighting.add_daylighting_controls(model, vintage="2020", audit=audit)
        self.assertGreaterEqual(created, 1, "a daylighted space got a control")
        control = model.getDaylightingControls()[0]
        self.assertEqual(400.0, control.illuminanceSetpoint(),
                         "office target illuminance from the space-type data")
        self.assertEqual("Stepped", control.lightingControlType())

        base = lighting.cost(costed_fixture_model(), vintage="2020",
                             city=CITY, province_state=PROVINCE)
        report = lighting.cost(model, vintage="2020", city=CITY, province_state=PROVINCE,
                               audit=audit)
        self.assertGreater(report.lighting["daylighting_sensor_cost"], 0,
                           "sensors costed (BOM 407/10/17/14)")
        self.assertGreater(report.total, base.total, "sensor cost adds to the fixture total")
        self.assertTrue(any("DAYLIGHTED-AREA fixture ratio" in e["action"] for e in audit.entries),
                        "sensor counts come from the legacy daylighted-area rule, not the whole zone")

    def test_the_necb_layer_supplies_the_provider_costing_refuses_to_guess(self):
        """The D-77 seam, asserted from this side: btap.costing RAISES when a
        model carries daylighting controls and no daylighted-area provider is
        given, and ``lighting.cost`` is what supplies one (the Ruby facade's
        ``kwargs[:daylighting_areas] ||= Daylighting.costing_area_provider``)."""
        from btap.costing.lighting import report as costing
        from btap.necb import lighting

        model = costed_fixture_model()
        wall = next(s for s in model.getSurfaces()
                    if s.outsideBoundaryCondition() == "Outdoors" and s.surfaceType() == "Wall")
        wall.setWindowToWallRatio(0.3)
        lighting.add_daylighting_controls(model, vintage="2020")

        with self.assertRaises(ValueError):
            costing.cost(model, vintage="2020", city=CITY, province_state=PROVINCE)

        report = lighting.cost(model, vintage="2020", city=CITY, province_state=PROVINCE)
        self.assertGreater(report.lighting["daylighting_sensor_cost"], 0)

    def test_legacy_parity_led_2020(self):
        """The Python Leg-A gate (enabled M8): Python lighting.cost vs the
        LIVE pinned oracle — not the frozen golden. The oracle value comes
        from a Ruby probe running the SAME OracleProbes recipe the Ruby
        parity gate runs, under BUNDLE_GEMFILE=legacy_pin/Gemfile; the
        tolerance is the Ruby gate's own (max of 0.1% and $0.05). Skips
        where the oracle is not bundled — LEGACY_PIN_REQUIRED=1 (the same
        flag the Ruby gates use) turns that skip into a failure, and CI's
        parity job (the one place the oracle exists) sets it. Its Leg-C
        twin is test_oracle_goldens_lighting.py's
        lighting_costing['led_2020_total'] assertion (D-78)."""
        import json
        import os
        import subprocess
        import tempfile
        from pathlib import Path

        from btap.necb import lighting
        from tests.support import REPO_ROOT

        probe = (Path(__file__).parent / "cross_language"
                 / "ruby_lighting_oracle_probe.rb")
        env = dict(os.environ)
        env.setdefault("BUNDLE_GEMFILE", str(REPO_ROOT / "legacy_pin"
                                             / "Gemfile"))
        # `bundle check` is the availability gate — the same one the Ruby
        # e2e suite uses: an oracle that is pinned but not checked out fails
        # it loudly ("not yet checked out"), and `bundle exec` would die in
        # gem_prelude before the probe even ran.
        check = subprocess.run(["bundle", "check"], capture_output=True,
                               text=True, env=env, cwd=str(REPO_ROOT))
        if check.returncode != 0:
            msg = ("legacy oracle not bundled — run under "
                   "BUNDLE_GEMFILE=legacy_pin/Gemfile after bundle install")
            if os.environ.get("LEGACY_PIN_REQUIRED") == "1":
                self.fail(msg)
            self.skipTest(msg)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "oracle.json"
            proc = subprocess.run(
                ["bundle", "exec", "ruby", str(probe), str(out)],
                capture_output=True, text=True, env=env,
                cwd=str(REPO_ROOT))
            if proc.returncode == 3:
                msg = ("legacy oracle bundle present but the probe could not "
                       "load it")
                if os.environ.get("LEGACY_PIN_REQUIRED") == "1":
                    self.fail(msg)
                self.skipTest(msg)
            self.assertEqual(0, proc.returncode,
                             f"oracle probe failed: {proc.stderr[-2000:]}")
            legacy_total = json.loads(
                out.read_text(encoding="utf-8"))["led_2020_total"]

        # NECB2020 template => the legacy coster forces LED
        report = lighting.cost(costed_fixture_model(lights_type="LED"),
                               vintage="2020", city=CITY,
                               province_state=PROVINCE)
        self.assertGreater(legacy_total, 0, "non-vacuous: the oracle costed")
        self.assertAlmostEqual(
            legacy_total, report.total,
            delta=max(abs(legacy_total) * 0.001, 0.05),
            msg="fixture-costing dollar parity vs the LIVE oracle "
                "cost_audit_lighting (LED/NECB2020 path)")


if __name__ == "__main__":
    unittest.main()
