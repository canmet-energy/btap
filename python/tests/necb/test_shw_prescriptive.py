"""Section 6.2 prescriptive rules: the one the model can answer, and the honest
declaration of the ones it cannot.

Port of btap-necb/test/test_shw_prescriptive.rb.
"""

from __future__ import annotations

import unittest

from tests.necb.support import needs_sdk


@needs_sdk
class TestPrescriptive(unittest.TestCase):
    @property
    def P(self):
        from btap.necb.shw import prescriptive
        return prescriptive

    # spaces_w_dhw entries only need the two keys the rule reads.
    def sizing(self, *pairs):
        return {"spaces_w_dhw": [{"peak_flow_si": flow, "temperature_c": temp}
                                 for flow, temp in pairs]}

    def run_check(self, sizing_hash, water_heaters=1):
        import openstudio

        from btap.audit import AuditLog
        model = openstudio.model.Model()
        for _ in range(water_heaters):
            openstudio.model.WaterHeaterMixed(model)
        audit = AuditLog()
        result = self.P.check_booster_heaters(sizing_hash, model, audit)
        return result, audit

    def entry(self, audit):
        return next((e for e in audit.entries if e.get("article") == "6.2.5.1."), None)

    # 6.2.5.1 fires when the hot fraction is SMALL, which is the counterintuitive
    # direction: a mostly-hot system may run one plant, a minority hot load may not
    # drag the whole plant up with it.
    def test_minority_high_temperature_load_with_one_heater_is_a_violation(self):
        _, audit = self.run_check(self.sizing((1.0, 80.0), (9.0, 45.0)))  # 10% above 60 C
        e = self.entry(audit)
        self.assertEqual("warning", e["level"])
        self.assertRegex(e["action"], r"BOOSTER HEATER REQUIRED and NOT present",
                         "violations are SHOUTED — the checklist classifier is case-sensitive")
        self.assertAlmostEqual(0.1, e["inputs"]["high_temp_flow_fraction"], delta=1e-6)

    def test_majority_high_temperature_load_needs_no_booster(self):
        _, audit = self.run_check(self.sizing((9.0, 80.0), (1.0, 45.0)))  # 90% above 60 C
        e = self.entry(audit)
        self.assertEqual("decision", e["level"])
        self.assertRegex(e["action"], r"not required")

    # Exactly at 50% the sentence does NOT fire — it says "less than 50%".
    def test_the_boundary_is_not_a_violation(self):
        _, audit = self.run_check(self.sizing((5.0, 80.0), (5.0, 45.0)))
        self.assertEqual("decision", self.entry(audit)["level"],
                         '50% is not "less than 50%"')

    # 60 C exactly is not "higher than 60 C".
    def test_sixty_exactly_is_not_a_high_temperature_load(self):
        _, audit = self.run_check(self.sizing((1.0, 60.0), (9.0, 45.0)))
        self.assertRegex(self.entry(audit)["action"], r"vacuous")

    def test_no_load_above_sixty_makes_the_sentence_vacuous(self):
        _, audit = self.run_check(self.sizing((10.0, 55.0)))
        e = self.entry(audit)
        self.assertEqual("info", e["level"],
                         "a sentence with no subject is neither a pass nor a failure")
        self.assertRegex(e["action"], r"vacuous")

    # A second water heater is the model's only evidence that the required booster
    # exists, so it must not still be reported as missing.
    def test_a_second_water_heater_satisfies_the_requirement(self):
        _, audit = self.run_check(self.sizing((1.0, 80.0), (9.0, 45.0)), water_heaters=2)
        e = self.entry(audit)
        self.assertEqual("decision", e["level"])
        self.assertNotRegex(e["action"], r"NOT present")

    def test_no_demand_is_not_a_determination(self):
        result, audit = self.run_check({"spaces_w_dhw": []})
        self.assertIsNone(result)
        self.assertIsNone(self.entry(audit))

    # The clauses no model can answer must still be NAMED, or their silence reads
    # as "not applicable" when they very much apply.
    def test_unanswerable_clauses_are_declared_individually(self):
        from btap.audit import AuditLog
        audit = AuditLog()
        self.P.declare_field_verified(audit)
        for article in ("6.2.3.1.", "6.2.4.3.", "6.2.6.1.",
                        "6.2.6.2.", "6.2.7.1.", "6.2.7.2."):
            e = next((x for x in audit.entries if x.get("article") == article), None)
            self.assertIsNotNone(e, f"{article} must be declared, not silently absent")
            self.assertEqual("info", e["level"],
                             "a field-verified clause is not a modelling warning")
            self.assertRegex(e["action"], r"requires field or document verification")

    # The gem had no status whitelist, unlike envelope/hvac/loads/lighting — a
    # typo'd status would have passed CI and rendered as an em-dash in the report.
    def test_every_coverage_status_is_legal(self):
        from btap.necb import shw
        valid = ["implemented", "partial", "not_implemented",
                 "satisfied_by_clone", "host_scope"]
        for vintage in ("2020", "2025"):
            for art in shw.rules(vintage)["article_coverage"]["articles"]:
                self.assertIn(art["status"], valid,
                              f"{vintage} {art['article']}: illegal status")
                self.assertTrue(art.get("how") or art.get("gaps"),
                                f"{vintage} {art['article']}: needs how or gaps")
                if not art.get("gap_owner"):
                    continue

                self.assertEqual("modeller", art["gap_owner"],
                                 f"{vintage} {art['article']}: only 'modeller' is "
                                 "recognised by Coverage.emit")
