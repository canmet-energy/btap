"""D-89 propagation: the part-load curve class the CODE selects travels from
the rule file to the reference boiler as an ``additionalProperties`` feature.

8.4.4.6.(1) (2025: 8.4.5.6.(1)) names "one gas-fired MODULATING boiler" for
purchased heating. That is the ONLY place the Code picks a part-load class, so
it is the only thing that propagates: a condensing boiler in the proposed does
NOT make the reference condensing (8.4.4.9.(4) transfers the energy TYPE, not
the equipment kind), which is why the negative test below is as load-bearing
as the positive one.

Why a feature ON the object rather than a value held in the builder: the
efficiency pass runs AGAIN after reference sizing (see btap/codes/CLAUDE.md,
"the second efficiency pass is a real trap" — a purchased-cooling chiller COP
shipped held-in-locals and reverted in every simulated run while its unit test,
asserting right after the build, stayed green). So the round-trip tests here
are not paranoia about the SDK: surviving clone and save/load is exactly what
makes the class reach the applier on the second pass.

The curve APPLICATION is not asserted here — that is the applier's side of the
D-89 interface. This file pins the contract between them: the feature key
``btap_part_load_curve_class`` carrying one of
``non_condensing | atmospheric | condensing | modulating | not_applicable``.
"""

import json
import re
import tempfile
import unittest
from pathlib import Path

import btap.codes.necb as necb_pkg
from tests.necb.support import load_raw_fixture, needs_sdk, proposed_with_hvac

FEATURE = "btap_part_load_curve_class"

#: The closed enum the feature may carry (the D-89 interface with the
#: efficiency applier). Spelled out here rather than imported so a silent
#: widening on either side of the interface fails a test.
CLASSES = {"non_condensing", "atmospheric", "condensing", "modulating",
           "not_applicable"}


def reference_rules(code):
    path = (Path(necb_pkg.__file__).parent / "data" / code / "reference_rules.json")
    return json.loads(path.read_text(encoding="utf-8"))


def classes(model):
    """The feature value on every BoilerHotWater, ``None`` where unset."""
    found = []
    for boiler in model.getBoilerHotWaters():
        value = boiler.additionalProperties().getFeatureAsString(FEATURE)
        found.append((boiler.nameString(),
                      value.get() if value.is_initialized() else None))
    return sorted(found)


def district_count(model):
    return sum(1 for o in model.modelObjects()
               if re.search("DistrictHeating", o.iddObjectType().valueName()))


def build_reference(model, code="necb2020", storeys=1):
    from btap.audit import AuditLog
    from btap.codes.necb import hvac

    audit = AuditLog()
    result = hvac.reference_hvac(model, code=code,
                                 building={"storeys": storeys}, audit=audit)
    return result.model, audit


def purchased_heating_proposed(system="Baseboard district hot water"):
    """A proposed carrying PURCHASED heating and no boiler — the premise
    8.4.4.6.(1) needs in order to have anything to represent."""
    import btap.modeling as modeling
    from btap._compat import sorted_by_name
    from btap.audit import AuditLog
    from btap.codes.necb import loads

    model = load_raw_fixture()
    loads.apply_loads(model, code="necb2020", audit=AuditLog())
    modeling.build_system(model, system, sorted_by_name(model.getThermalZones()))
    return model


class TestTheRuleDeclaresTheClass(unittest.TestCase):
    """No SDK needed: the class must come from DATA, not a Python literal, so
    that an edition naming a different class is a data change."""

    def test_both_editions_declare_the_modulating_class_on_the_rule(self):
        for code in ("necb2020", "necb2025"):
            rule = (reference_rules(code)["selection"]["special_rules"]
                    ["purchased_heating"])
            self.assertEqual("modulating", rule.get("part_load_curve_class"),
                             f"{code}: 8.4.4.6.(1)/8.4.5.6.(1) names a "
                             "MODULATING boiler; the class must be declared "
                             "on the rule, never inlined in Python")
            self.assertIn(rule["part_load_curve_class"], CLASSES)
            self.assertRegex(rule["text"], r"modulating",
                             f"{code}: the rule text is the evidence for the "
                             "class it declares")

    def test_no_other_selection_rule_declares_a_class(self):
        # Contract item 3: purchased heating is the ONLY propagation. A class
        # appearing anywhere else in the selection rules is a new propagation
        # path and has to be adjudicated, not absorbed.
        for code in ("necb2020", "necb2025"):
            blob = json.dumps(reference_rules(code)["selection"])
            self.assertEqual(
                1, blob.count("part_load_curve_class"),
                f"{code}: exactly one selection rule may name a part-load "
                "curve class (purchased heating, 8.4.4.6.(1))")

    def test_the_python_side_holds_no_class_literal(self):
        source = (Path(necb_pkg.__file__).parent / "hvac" / "reference.py") \
            .read_text(encoding="utf-8")
        for name in sorted(CLASSES):
            self.assertNotIn(
                f"'{name}'", source,
                f"reference.py must not name the {name!r} class as a literal "
                "— it reads the class from reference_rules.json")


@needs_sdk
class TestPurchasedHeatingPropagatesTheClass(unittest.TestCase):
    def test_the_reference_boilers_carry_the_modulating_feature(self):
        model = purchased_heating_proposed()
        self.assertEqual(1, district_count(model),
                         "the proposed must carry purchased heating")
        self.assertEqual(0, len(model.getBoilerHotWaters()),
                         "the proposed must have no boiler")

        reference, _ = build_reference(model)

        found = classes(reference)
        self.assertTrue(found, "the reference must grow a boiler")
        self.assertEqual([], [n for n, c in found if c != "modulating"],
                         f"every reference boiler must carry the modulating "
                         f"class: {found}")

    def test_the_selection_decision_carries_the_class_and_cites_D_89(self):
        _, audit = build_reference(purchased_heating_proposed())

        entries = [e for e in audit.entries
                   if str(e.get("action") or "") ==
                   "purchased heating energy -> represented by gas-fired "
                   "modulating boiler"]
        self.assertTrue(entries,
                        "the 8.4.4.6.(1) selection decision must be audited")
        for entry in entries:
            self.assertEqual(
                "modulating",
                (entry.get("inputs") or {}).get("part_load_curve_class"),
                f"the selection decision must record the class: {entry}")
            self.assertIn("D-89", str(entry.get("ruling") or ""),
                          f"the class propagation is D-89's ruling: {entry}")
            self.assertRegex(str(entry.get("article") or ""), r"8\.4\.[45]\.6")

    def test_the_build_decision_records_the_class_it_stamped(self):
        _, audit = build_reference(purchased_heating_proposed())

        built = [e for e in audit.entries
                 if str(e.get("action") or "") == "reference system built"]
        self.assertTrue(built, "the build decision must be audited")
        stamped = [e for e in built
                   if (e.get("inputs") or {}).get("boiler_part_load_curve_class")]
        self.assertTrue(stamped,
                        "a purchased-heating build must say which class it "
                        f"stamped: {[e.get('inputs') for e in built]}")
        for entry in stamped:
            self.assertEqual("modulating",
                             entry["inputs"]["boiler_part_load_curve_class"])

    def test_2025_propagates_the_same_way_under_its_own_article(self):
        _, audit = build_reference(purchased_heating_proposed(),
                                   code="necb2025")
        articles = [str(e.get("article") or "") for e in audit.entries
                    if str(e.get("action") or "").startswith(
                        "purchased heating energy")]
        self.assertTrue(articles)
        self.assertTrue(all("8.4.5.6" in a for a in articles),
                        f"2025 renumbers the sentence: {articles}")

    def test_every_group_layout_still_ends_with_gas_boilers_only(self):
        # The layout that hid the original bug (see
        # test_reference_rules.py::test_purchased_heating_is_replaced_whatever_
        # the_group_layout): `Baseboard district hot water` makes FIVE
        # single-zone groups and the builder rebuilds one at a time, so the
        # district loop can survive a partial teardown. Re-asserted HERE
        # because the class stamp is per-assignment: a layout that leaves an
        # un-stamped boiler behind would be invisible to the single-group test.
        for system in ("Baseboard district hot water",
                       "DOAS with fan coil air-cooled chiller with district "
                       "hot water"):
            with self.subTest(system=system):
                reference, _ = build_reference(
                    purchased_heating_proposed(system))

                self.assertEqual(0, district_count(reference),
                                 f"{system}: the reference must NOT keep "
                                 "purchased heating")
                self.assertEqual(
                    ["NaturalGas"],
                    sorted({b.fuelType() for b in reference.getBoilerHotWaters()}),
                    f"{system}: 8.4.4.6.(1)(a) names a GAS-fired boiler")
                found = classes(reference)
                self.assertTrue(found)
                self.assertEqual(
                    [], [n for n, c in found if c != "modulating"],
                    f"{system}: every boiler the reference built must carry "
                    f"the class: {found}")


@needs_sdk
class TestNothingElsePropagatesAClass(unittest.TestCase):
    def test_an_ordinary_gas_reference_carries_no_feature(self):
        # Contract item 3. The proposed here is an ordinary gas boiler: its
        # reference boiler's class is the EQUIPMENT ROW's business (the
        # applier's default), not something the selection may assert.
        reference, _ = build_reference(
            proposed_with_hvac("Baseboard gas boiler"))

        found = classes(reference)
        self.assertTrue(found, "the gas reference must have a boiler to check")
        self.assertEqual([], [n for n, c in found if c is not None],
                         f"no selection but purchased heating may stamp a "
                         f"class: {found}")

    def test_purchased_cooling_alone_stamps_the_chiller_and_not_the_boiler(self):
        # 8.4.4.6.(2) is the sibling sentence and the propagation PRECEDENT.
        # It names a chiller, not a boiler class — so a building whose
        # purchased energy is COOLING only must end with a stamped chiller and
        # an UNSTAMPED boiler. Without this the positive test above could be
        # satisfied by stamping every boiler in every purchased-energy run.
        import btap.modeling as modeling
        from btap._compat import sorted_by_name
        from btap.audit import AuditLog
        from btap.codes.necb import loads

        model = load_raw_fixture()
        loads.apply_loads(model, code="necb2020", audit=AuditLog())
        modeling.build_system(model,
                              "DOAS with fan coil district chilled water with boiler",
                              sorted_by_name(model.getThermalZones()))
        # 3 storeys -> Table 8.4.4.7.-A selects System 6, the chilled-water
        # reference, so the 8.4.4.6.(2) chiller representation is actually
        # built (the variant mockup uses the same override for the same
        # reason); System 3 would cool with DX and there would be no chiller
        # to compare the unstamped boiler against.
        reference, _ = build_reference(model, storeys=3)

        found = classes(reference)
        self.assertTrue(found, "this reference must have a boiler to check")
        self.assertEqual([], [n for n, c in found if c is not None],
                         f"purchased COOLING must not stamp a boiler class: "
                         f"{found}")
        self.assertTrue(
            [c for c in reference.getChillerElectricEIRs()
             if "btap_purchased_cooling_reference_cop"
             in c.additionalProperties().featureNames()],
            "the purchased-cooling precedent must still stamp its chiller — "
            "this test is only meaningful while that path still works")


@needs_sdk
class TestTheFeatureSurvivesTheSecondEfficiencyPass(unittest.TestCase):
    """The class must outlive a clone and a save/load round trip, because the
    efficiency pass re-runs on the SIZED model and reads the class back off
    the object. A value that did not survive these would revert to the generic
    default in every simulated run — the purchased-cooling COP bug exactly."""

    def setUp(self):
        self.reference, _ = build_reference(purchased_heating_proposed())
        self.before = classes(self.reference)
        self.assertTrue(self.before)
        self.assertEqual([], [n for n, c in self.before if c != "modulating"])

    def test_it_survives_a_model_clone(self):
        from btap.codes.necb.hvac.reference import _clone_model

        self.assertEqual(self.before, classes(_clone_model(self.reference)),
                         "the pipeline clones models; a class lost on clone "
                         "never reaches the applier")

    def test_it_survives_a_save_and_reload(self):
        from btap._sdk import load_model

        with tempfile.TemporaryDirectory() as dir:
            path = Path(dir) / "reference.osm"
            self.assertTrue(self.reference.save(str(path), True),
                            "the model must save")
            self.assertEqual(self.before, classes(load_model(path)),
                             "additionalProperties must round-trip through "
                             ".osm — the sizing run writes and re-reads the "
                             "model")

    def test_it_survives_the_efficiency_pass_itself(self):
        # The narrowest statement of the trap: apply_efficiencies a SECOND
        # time (what happens after reference sizing) must not clear the class.
        from btap.audit import AuditLog
        from btap.codes.necb import hvac

        hvac.apply_efficiencies(self.reference, code="necb2020",
                                audit=AuditLog())
        self.assertEqual(self.before, classes(self.reference),
                         "the second efficiency pass must not drop the class")


if __name__ == "__main__":
    unittest.main()
