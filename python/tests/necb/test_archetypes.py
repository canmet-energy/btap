"""Port of btap-necb/test/test_archetypes.rb: the NECB 2025 8.4.4 archetype
machinery — space mapping with model-derived areas (8.4.4.1.(3)), pro-rata
distribution (8.4.4.1.(4)), applicability refusals, the Table 8.4.4.2
conformance check and the normalization transform. All engine-free (SDK only
— the EUI path's model work needs no EnergyPlus until the annual run)."""

import tempfile
import unittest

from btap.audit import AuditLog
from btap.necb import eui_archetypes as A
from tests.necb.support import compliance_fixture, needs_sdk, proposed_with_hvac


def quiet():
    return AuditLog()


@needs_sdk
class TestArchetypes(unittest.TestCase):
    # -- mapping / areas -----------------------------------------------------

    def test_resolve_all_and_explicit_lists(self):
        model = compliance_fixture()
        resolved = A.resolve(model, {"Office": "all"}, audit=quiet())
        self.assertEqual(5, len(resolved["archetypes"]["Office"]["spaces"]))
        self.assertAlmostEqual(model.getBuilding().floorArea(),
                               resolved["archetypes"]["Office"]["area_m2"],
                               delta=0.01,
                               msg="areas come from the model, not the caller")
        self.assertEqual(0.0, resolved["unmapped"]["area_m2"])

        core = next(n for n in (s.nameString() for s in model.getSpaces())
                    if "Core" in n)
        resolved = A.resolve(model, {"School (K-12)": [core], "Office": "all"},
                             audit=quiet())
        self.assertEqual(1, len(resolved["archetypes"]["School (K-12)"]["spaces"]))
        self.assertEqual(4, len(resolved["archetypes"]["Office"]["spaces"]),
                         "'all' takes the unclaimed remainder")

    def test_resolve_rejects_bad_input(self):
        model = compliance_fixture()
        with self.assertRaises(ValueError):
            A.resolve(model, {"Casino": "all"}, audit=quiet())
        with self.assertRaises(ValueError):
            A.resolve(model, {"Office": ["No Such Space"]}, audit=quiet())
        with self.assertRaises(ValueError):
            A.resolve(model, {"Office": "all", "School (K-12)": "all"},
                      audit=quiet())
        core = next(n for n in (s.nameString() for s in model.getSpaces())
                    if "Core" in n)
        with self.assertRaises(ValueError) as ctx:
            A.resolve(model, {"Office": [core], "School (K-12)": [core]},
                      audit=quiet())
        self.assertIn("mapped to both", str(ctx.exception))

    def test_bet_areas_pro_rata_sums_to_model_total(self):
        # 8.4.4.1.(4): unmapped area distributed pro-rata; over-assignment is
        # impossible by construction (areas come from disjoint space sets).
        model = compliance_fixture()
        names = [s.nameString() for s in
                 sorted(model.getSpaces(), key=lambda s: -s.floorArea())]
        resolved = A.resolve(model, {"Office": names[:4]},
                             audit=quiet())  # 1 space unmapped
        self.assertGreater(resolved["unmapped"]["area_m2"], 0)
        areas = A.bet_areas(resolved, audit=quiet())
        self.assertAlmostEqual(resolved["total_area_m2"], sum(areas.values()),
                               delta=1e-6,
                               msg="BET areas sum to the model total after "
                                   "pro-rata (8.4.4.1.(4))")

    def test_applicability_refusals(self):
        model = compliance_fixture()
        all_mapped = A.resolve(model, {"Office": "all"}, audit=quiet())
        with self.assertRaises(ValueError):
            A.verify_applicability(all_mapped, hdd=9500, audit=quiet())

        smallest = min(model.getSpaces(),
                       key=lambda s: s.floorArea()).nameString()
        sparse = A.resolve(model, {"Office": [smallest]}, audit=quiet())
        with self.assertRaises(ValueError) as ctx:
            A.verify_applicability(sparse, hdd=3890, audit=quiet())
        self.assertIn("8.4.4.1.(1)", str(ctx.exception))

    # -- conformance + normalization ------------------------------------------

    def test_bare_model_is_not_conformant_with_named_mismatches(self):
        model = compliance_fixture()
        resolved = A.resolve(model, {"Office": "all"}, audit=quiet())
        check = A.conformance(model, resolved, vintage="2025", audit=quiet())
        self.assertFalse(check["conformant"])
        self.assertTrue(any("occupant density" in m for m in check["mismatches"]),
                        "names the density gap")
        self.assertTrue(any("receptacle" in m for m in check["mismatches"]),
                        "names the receptacle gap")

    def test_normalize_then_check_round_trip(self):
        # The strong one: normalize then conformance must agree — the check
        # and the transform are two views of the same Table 8.4.4.2 contract,
        # and this pins them together (a drift in either direction fails
        # here).
        import openstudio

        model = proposed_with_hvac()
        # seed SWH equipment so the L/h/occupant normalization has something
        # to set
        for space in model.getSpaces():
            definition = openstudio.model.WaterUseEquipmentDefinition(model)
            equipment = openstudio.model.WaterUseEquipment(definition)
            equipment.setName(f"{space.nameString()} SWH")
            equipment.setSpace(space)
        audit = quiet()
        resolved = A.resolve(model, {"Office": "all"}, audit=audit)
        A.normalize(model, resolved, vintage="2025", audit=audit)

        check = A.conformance(model,
                              A.resolve(model, {"Office": "all"}, audit=audit),
                              vintage="2025", audit=audit)
        self.assertTrue(
            check["conformant"],
            "normalize->check round trip failed: "
            + " | ".join(check["mismatches"][:5]))

        # spot-check the physical values against Table 8.4.4.2 (Office row)
        space = model.getSpaces()[0]
        self.assertAlmostEqual(1.0 / 25.0,
                               space.numberOfPeople() / space.floorArea(),
                               delta=1e-4, msg="Office: 25 m2/person")
        self.assertAlmostEqual(7.5,
                               space.electricEquipmentPowerPerFloorArea(),
                               delta=0.01, msg="Office: 7.5 W/m2 receptacle")
        zone = space.thermalZone().get()
        self.assertTrue(zone.thermostatSetpointDualSetpoint().is_initialized(),
                        "zone thermostat forced to the letter-A setpoints")

    def test_lighting_power_is_never_touched(self):
        import openstudio

        model = compliance_fixture()
        space_type = next(st for st in model.getSpaceTypes() if st.spaces())
        definition = openstudio.model.LightsDefinition(model)
        definition.setWattsperSpaceFloorArea(99.0)
        lights = openstudio.model.Lights(definition)
        lights.setSpaceType(space_type)

        space = model.getSpaces()[0]
        before = space.lightingPowerPerFloorArea()  # fixture + the hostile 99
        resolved = A.resolve(model, {"Office": "all"}, audit=quiet())
        A.normalize(model, resolved, vintage="2025", audit=quiet())

        self.assertAlmostEqual(
            before, space.lightingPowerPerFloorArea(), delta=0.01,
            msg="lighting power is the design under evaluation — "
                "normalization must not touch it")

    # -- pipeline integration (engine-free) ------------------------------------

    def test_eui_path_none_mode_normalizes_without_mutating_caller(self):
        from btap.necb import performance_compliance

        model = proposed_with_hvac()
        people_before = len(model.getPeoples())
        result = performance_compliance(
            model, vintage="2025", path="eui", simulate="none", hdd=3890,
            archetypes_map={"Office": "all"},
            run_dir=tempfile.mkdtemp(prefix="osnecb-euinone-"))

        self.assertEqual(people_before, len(model.getPeoples()),
                         "caller model never mutated")
        self.assertTrue(result.report["eui"]["normalized"])
        self.assertGreater(len(result.proposed_model.getPeoples()), 0,
                           "the RUN model carries the Table loads")
        self.assertAlmostEqual(
            result.proposed_model.getBuilding().floorArea() * 175,
            result.report["reference"]["building_energy_target_kwh"],
            delta=1.0)
        self.assertIsNone(result.compliant,
                          "no determination without an annual run")

    def test_supplement_not_computed_without_run_normalized(self):
        # The supplement's not-computed contract, unit-level (no E+): a
        # proposed that does not conform, without run_normalized, must yield
        # an explicit not-computed result with the mismatch list — never a
        # verdict.
        from btap.necb.compliance import eui_supplement_verdict

        model = proposed_with_hvac()
        audit = quiet()
        report = {"proposed": {"total_site_kwh": 100_000.0}}
        out = eui_supplement_verdict(
            model, {"archetypes": {"Office": "all"}}, 3890, report,
            tempfile.mkdtemp(prefix="osnecb-sup-"), None, "2025", audit)
        self.assertEqual(False, out["computed"])
        self.assertIn("does not conform", out["reason"])
        self.assertTrue(out["mismatches"])
        self.assertTrue(any("NOT COMPUTED" in w["action"]
                            for w in audit.warnings))


if __name__ == "__main__":
    unittest.main()
