"""Port of btap-audit/test/test_audit.rb — assertions verbatim.

The AuditLog `ruling:` axis: every entry can cite the adjudicated project
decision(s) (D-XX) that govern the code path, alongside the `article:` axis
that cites the code text itself. Untagged entries must stay identical to what
they were before the axis existed.
"""

import json
import re
import unittest

from btap.audit import AuditLog, emit_coverage


class TestAuditLog(unittest.TestCase):
    def setUp(self):
        self.audit = AuditLog()

    def test_ruling_is_stored_top_level(self):
        self.audit.decision("build", "reference system operates on the proposed operating schedule",
                            article="8.4.4.7.(1)", ruling="D-14")
        entry = self.audit.entries[0]
        self.assertEqual("D-14", entry["ruling"], "ruling lands at the TOP LEVEL of the entry")
        self.assertNotIn("inputs", entry, "ruling never leaks into inputs")

    def test_ruling_survives_every_level(self):
        self.audit.decision("build", "a decision", ruling="D-01")
        self.audit.info("build", "an info", ruling="D-02")
        self.audit.warn("build", "a warning", ruling="D-03")
        self.assertEqual(["D-01", "D-02", "D-03"], [e["ruling"] for e in self.audit.entries])

    def test_untagged_entries_are_unchanged(self):
        self.audit.decision("build", "untagged", article="8.4.4.1.(1)")
        entry = self.audit.entries[0]
        self.assertNotIn("ruling", entry,
                         "None ruling is compacted away — no schema drift for untagged entries")
        self.assertEqual(sorted(["step", "action", "article", "level"]), sorted(entry.keys()),
                         "building is None here and compacts away too")

    def test_multi_ruling_is_one_space_separated_string(self):
        self.audit.decision("reference", "air-leakage default applied", ruling="D-19 D-21")
        entry = self.audit.entries[0]
        self.assertEqual("D-19 D-21", entry["ruling"])
        self.assertEqual(["D-19", "D-21"], re.findall(r"\bD-\d{2}\b", entry["ruling"]),
                         "the documented consumer parse recovers both ids")

    def test_str_appends_ruling_after_the_article_segment(self):
        self.audit.decision("build", "did a thing", article="8.4.4.7.(1)", ruling="D-14")
        line = str(self.audit)
        self.assertIn("| per 8.4.4.7.(1)", line)
        self.assertIn("| ruling D-14", line)
        self.assertLess(line.index("| per 8.4.4.7.(1)"), line.index("| ruling D-14"),
                        "article segment comes first")

    def test_str_omits_the_segment_when_untagged(self):
        self.audit.decision("build", "did a thing", article="8.4.4.7.(1)")
        self.assertNotIn("ruling", str(self.audit))

    def test_to_json_carries_the_ruling(self):
        self.audit.decision("build", "did a thing", article="8.4.4.7.(1)", ruling="D-14")
        parsed = json.loads(self.audit.to_json())
        self.assertEqual("D-14", parsed[0]["ruling"])

    def test_warnings_and_building_stamp(self):
        with self.audit.with_building("proposed building"):
            self.audit.warn("build", "something SKIPPED")
            self.audit.info("build", "a note")
        self.audit.info("build", "outside the block")
        self.assertEqual(1, len(self.audit.warnings))
        self.assertEqual(["proposed building", "proposed building", None],
                         [e.get("building") for e in self.audit.entries])

    def test_str_line_shape_matches_ruby(self):
        """The fixed-width narrative line the checklist classifier parses —
        byte-identical to Ruby's format('[%-8s] %-13s %s', ...)."""
        self.audit.warn("efficiency", "boiler efficiency UNKNOWN",
                        target="Boiler 1", inputs={"fuel": "gas", "kw": 25.0},
                        value=0.8, evidence="OS:Boiler", article="8.4.4.9.(1)")
        self.assertEqual(
            "[warning ] efficiency    boiler efficiency UNKNOWN"
            " | target: Boiler 1 | inputs: fuel=gas, kw=25.0 | value: 0.8"
            " | evidence: OS:Boiler | per 8.4.4.9.(1)",
            str(self.audit))

    def test_with_building_is_nestable(self):
        with self.audit.with_building("proposed building"):
            with self.audit.with_building("reference building"):
                self.audit.info("build", "inner")
            self.audit.info("build", "restored")
        self.assertEqual(["reference building", "proposed building"],
                         [e["building"] for e in self.audit.entries])


class TestCoverageEmit(unittest.TestCase):
    COVERAGE = {
        "articles": [
            {"article": "8.4.4.7.", "title": "System selection", "status": "implemented",
             "how": "Table 8.4.4.7.-A"},
            {"article": "8.4.4.9.", "title": "Staged heating", "status": "partial",
             "how": "two stages", "gaps": "modulating burners"},
            {"article": "8.4.4.11.", "title": "Something unbuilt", "status": "not_implemented",
             "gaps": "everything"},
            {"article": "8.4.4.3.", "title": "Envelope carried over", "status": "satisfied_by_clone"},
            {"article": "8.4.4.20.", "title": "Service water heating", "status": "host_scope",
             "how": "Delegated to the shw domain"},
            {"article": "8.4.1.1. (HVAC)", "title": "Modeller inputs", "status": "partial",
             "gap_owner": "modeller", "how": "schedules read from the model",
             "gaps": "occupancy assumptions"},
        ]
    }

    def setUp(self):
        self.audit = AuditLog()

    def emit(self):
        self.audit.decision("build", "selected system 3", article="8.4.4.7.(1)")
        self.audit.decision("build", "fan power", article="8.4.4.7.(4); 8.4.4.18.(2)")
        self.audit.decision("build", "staged coil", article="8.4.4.9.(7)")
        self.audit.decision("build", "water-side economizer", article="5.2.2.9.(2)")  # non-8.4: never counted
        emit_coverage(self.COVERAGE, self.audit)
        return [e for e in self.audit.entries if e["step"] == "coverage"]

    def test_emits_one_entry_per_article_at_the_right_level(self):
        entries = self.emit()
        self.assertEqual(6, len(entries))
        self.assertEqual(["info", "warning", "warning", "info", "info", "info"],
                         [e["level"] for e in entries],
                         "partial/not_implemented warn; implemented/satisfied_by_clone/"
                         "host_scope inform; gap_owner modeller is an info scope note (D-09)")

    def test_citation_counts_are_prefix_matched(self):
        entries = self.emit()
        counts = {e["article"]: e["inputs"]["decisions_citing"] for e in entries}
        self.assertEqual(2, counts["8.4.4.7."], "both 8.4.4.7 citations counted")
        self.assertEqual(1, counts["8.4.4.9."])
        self.assertEqual(0, counts["8.4.4.11."])
        self.assertEqual(0, counts["8.4.1.1. (HVAC)"],
                         'the " (slice label)" suffix is stripped before matching')

    def test_status_and_gap_owner_land_in_inputs(self):
        entries = self.emit()
        partial = next(e for e in entries if e["article"] == "8.4.4.9.")
        self.assertEqual("partial", partial["inputs"]["status"])
        self.assertNotIn("gap_owner", partial["inputs"])
        modeller = next(e for e in entries if e["article"] == "8.4.1.1. (HVAC)")
        self.assertEqual("modeller", modeller["inputs"]["gap_owner"])
        self.assertIn("modeller scope", modeller["action"])
        self.assertIn("Modeller's responsibility: occupancy assumptions", modeller["action"])

    def test_action_text_carries_status_how_and_gaps(self):
        entries = self.emit()
        by_article = {e["article"]: e["action"] for e in entries}
        self.assertEqual("System selection — implemented: Table 8.4.4.7.-A",
                         by_article["8.4.4.7."])
        self.assertEqual("Staged heating — partial. Applied: two stages. Gaps: modulating burners",
                         by_article["8.4.4.9."])
        self.assertEqual("Something unbuilt — not implemented. Gaps: everything",
                         by_article["8.4.4.11."])
        self.assertEqual("Service water heating — host scope: Delegated to the shw domain",
                         by_article["8.4.4.20."])

    def test_none_coverage_is_a_no_op(self):
        emit_coverage(None, self.audit)
        self.assertEqual([], self.audit.entries)


if __name__ == "__main__":
    unittest.main()
