"""Port of btap-necb/test/test_report_units.rb: SDK-free renderer units —
HTML helpers, checklist derivation, charts, and the full-document render from
CANNED report/audit data (no models, no simulation).

The paired_bars golden is THE RUBY SUITE'S OWN golden file
(btap-necb/test/goldens/paired_bars.svg) consumed as-is — a cross-language
byte-equality gate, per the M3 catalog-report precedent."""

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from btap.audit import AuditLog
from btap.codes import decisions as Decisions
from btap.codes.compliance import ComplianceResult
from btap.codes.report import charts as Charts
from btap.codes.report import checklist as Checklist
from btap.codes.report import html as H
from btap.codes.report import render as render_report
from btap.codes.report import sections as Sections

# The Python-owned copy of the Ruby paired-bars golden — byte-identity with
# the gem-tree original is enforced by tests/test_fixture_drift.py until R6.
RUBY_GOLDEN = (Path(__file__).resolve().parents[1] / "fixtures"
               / "paired_bars.svg")


def canned_audit():
    audit = AuditLog()
    audit.decision("compliance",
                   "proposed does not exceed the building energy target",
                   inputs={"proposed_kwh": 90_000.0,
                           "reference_building_energy_target_kwh": 100_000.0},
                   value="margin 10000.0 kWh (10.0%)", article="8.4.1.2.(2)")
    audit.decision("compliance", "unmet heating hours EXCEED 100 h",
                   inputs={"proposed_h": 140.0, "reference_h": 20.0,
                           "limit_h": 100},
                   article="8.4.1.2.(3)", ruling="D-43")
    audit.decision("compliance",
                   "proposed ALSO meets the archetype-EUI building energy "
                   "target (8.4.4 path)",
                   inputs={"proposed_kwh": 90_000.0, "bet_kwh": 120_000.0},
                   article="8.4.4.1.(2)")
    # implemented — no checklist row (appendix-only)
    audit.info("coverage", "climatic data taken from model inputs",
               inputs={"status": "implemented", "decisions_citing": 3},
               article="8.4.2.3.")
    # implementing entry that covers the host_scope delegation below
    audit.info("coverage", "reference lighting applied (Part 4 allowance LPDs)",
               inputs={"status": "implemented", "decisions_citing": 2},
               article="8.4.4.5.")
    # host_scope COVERED by 8.4.4.5. above (prefix match) — no checklist row
    audit.info("coverage", "delegated to the lighting domain",
               inputs={"status": "host_scope", "decisions_citing": 0},
               article="8.4.4.5.(1)")
    # host_scope ORPHAN — nothing implements 8.4.4.20. -> warning checklist row
    audit.info("coverage", "delegated to the shw domain",
               inputs={"status": "host_scope", "decisions_citing": 0},
               article="8.4.4.20.")
    with audit.with_building("reference building"):
        audit.warn("efficiency",
                   "unsized DX coil skipped by capacity-binned lookup",
                   target="Coil 1", article="Table 5.2.12.1.")
        # two entries citing D-19 (fire count 2) + a multi-ruling string
        audit.decision("reference", "air-leakage default applied",
                       article="8.4.3.3.(3)", ruling="D-19 D-21")
        audit.decision("build",
                       "reference system operates on the proposed operating "
                       "schedule",
                       article="8.4.3.2.(1)", ruling="D-19")
    with audit.with_building("input model"):
        audit.warn("loads", "space with no space type assigned",
                   target="Space 9")
    return audit


def canned_report():
    return {
        "edition": "2025", "code": "necb2025", "code_label": "NECB 2025",
        "hdd": 3890, "simulate": "annual", "annual": True,
        "compliant": True, "percent_of_target": 90.0, "tier": 1,
        "ghg": {"percent_of_ghg_target": 24.0, "level": "B"},
        "eui_path": {"bet_kwh": 120_000.0, "compliant": True,
                     "percent_of_target": 75.0, "tier": 2,
                     "lines": [{"archetype": "Office", "area_m2": 600.0,
                                "eui_kwh_per_m2": 175, "kwh": 105_000.0}]},
        "proposed": {"total_site_kwh": 90_000.0, "electricity_kwh": 40_000.0,
                     "natural_gas_kwh": 50_000.0, "eui_kwh_per_m2": 150.0,
                     "floor_area_m2": 600.0, "ghg_kg_co2e": 11_566.0,
                     "end_uses_kwh": {"heating": 50_000.0, "cooling": 5_000.0,
                                      "fans": 8_000.0, "pumps": 2_000.0,
                                      "interior_lighting": 15_000.0,
                                      "interior_equipment": 10_000.0,
                                      "water_systems": 0.0},
                     "unmet_occupied_hours": {"heating": 12.0, "cooling": 40.0},
                     "cost": {"hvac": 100_000.0, "envelope": 250_000.0,
                              "total": 350_000.0}},
        "reference": {"total_site_kwh": 100_000.0, "electricity_kwh": 45_000.0,
                      "natural_gas_kwh": 55_000.0, "eui_kwh_per_m2": 166.7,
                      "ghg_kg_co2e": 48_190.0,
                      "end_uses_kwh": {"heating": 55_000.0, "cooling": 6_000.0,
                                       "fans": 9_000.0, "pumps": 2_500.0,
                                       "interior_lighting": 16_000.0,
                                       "interior_equipment": 10_000.0,
                                       "water_systems": 0.0},
                      "unmet_occupied_hours": {"heating": 20.0,
                                               "cooling": 35.0},
                      "cost": {"hvac": 90_000.0, "envelope": 240_000.0,
                               "total": 330_000.0}},
        "incremental_cost_proposed_vs_reference": 20_000.0,
        "warnings": ["unsized DX coil skipped by capacity-binned lookup"],
    }


def canned_result():
    return ComplianceResult(proposed_model=None, reference_model=None,
                            report=canned_report(), audit=canned_audit(),
                            compliant=True, run_dir=None)


class TestReportUnits(unittest.TestCase):
    def test_escaping(self):
        self.assertEqual("&lt;a href=&quot;x&quot;&gt;&amp;&lt;/a&gt;",
                         H.esc('<a href="x">&</a>'))
        html = H.table(["A"], [["<script>alert(1)</script>"]])
        self.assertNotIn("<script>", html)

    def test_fmt(self):
        self.assertEqual("12,345 kWh", H.fmt(12_345.2, unit="kWh", prec=0))
        self.assertEqual("—", H.fmt(None))
        self.assertEqual("0.347", H.fmt(0.3468, prec=3))

    def test_checklist_verdicts_respect_shouting_convention(self):
        rows = Checklist.rows(canned_audit().entries)
        by_article = {r.article: r for r in rows}
        self.assertEqual("pass", by_article["8.4.1.2.(2)"].glyph,
                         'lowercase "does not exceed" is a PASS')
        self.assertEqual("fail", by_article["8.4.1.2.(3)"].glyph,
                         "uppercase EXCEED is a FAIL")
        self.assertEqual("pass", by_article["8.4.4.1.(2)"].glyph)
        self.assertEqual("warning", by_article["Table 5.2.12.1."].glyph,
                         "warnings elevate")
        self.assertEqual(
            [r.article for r in
             sorted(rows, key=lambda r: Checklist.article_sort_key(r.article))],
            [r.article for r in rows], "rows are article-sorted")
        self.assertTrue(all(isinstance(r.audit_index, int) for r in rows),
                        "every row anchors an audit entry")

        html = Sections.checklist({"checklist_rows": rows,
                       "report": {"code_label": "NECB 2025"}})
        self.assertIn('class="checklist"', html)
        self.assertIn('class="checklist-statement"', html)
        self.assertIn('<span>Evidence</span>', html)
        self.assertNotIn("Measured values</th>", html,
                 "evidence stays visually attached to its determination")

        structured = Sections._checklist_statement_html(
            "Cooling — partial. Applied: staged DX. Gaps: terminal units.")
        self.assertIn('class="checklist-summary"', structured)
        self.assertIn('<span>Applied</span> staged DX.', structured)
        self.assertIn('<span>Gaps</span> terminal units.', structured)

    def test_coverage_reconciliation(self):
        rows = Checklist.rows(canned_audit().entries)
        orphan = next((r for r in rows if r.article == "8.4.4.20."), None)
        self.assertIsNotNone(
            orphan, "orphan host_scope delegation surfaces on the checklist")
        self.assertEqual("warning", orphan.glyph)
        self.assertIn("NOT covered", orphan.statement)
        self.assertIsNone(
            next((r for r in rows if r.article == "8.4.4.5.(1)"), None),
            "covered host_scope stays off the checklist")
        self.assertIsNone(
            next((r for r in rows if r.article == "8.4.2.3."), None),
            "implemented coverage emits no checklist row")
        self.assertIsNone(
            next((r for r in rows if r.article == "8.4.4.5."), None),
            "implemented coverage emits no checklist row")

        html = render_report(canned_result())
        self.assertIn("delegated — covered by another gem", html)
        self.assertIn("NOT covered in this run", html)
        self.assertIn("Technical implementation notes", html)
        self.assertIn("context, not additional requirements", html)

    def test_checklist_hides_cross_edition_coverage_history(self):
        entry = {
            "step": "coverage", "level": "warning",
            "article": "4.2.2.1.(10)-(15)",
            "action": ("Interior lighting controls — daylighting — partial. "
                       "Applied: follows the 2020/2025 code. The legacy NECB "
                       "2011 rule remains callable. Gaps: roof monitors."),
            "inputs": {"status": "partial"},
        }
        row = Checklist.rows([entry])[0]
        self.assertIn("Applied:", row.statement)
        self.assertIsNone(row.measured,
                  "internal coverage metadata is not measured evidence")
        html = Sections.checklist({"checklist_rows": [row],
                       "report": {"code_label": "NECB 2020"}})
        self.assertIn("<span>Applied</span> follows NECB 2020.", html)
        self.assertIn("<span>Gaps</span> roof monitors.", html)
        self.assertNotIn("2025", html)
        self.assertNotIn("2011", html)

        tier = Checklist.Row("na", "10.1.2.1. (Table verified identical 2020/2025)",
                     "energy performance Tier 1 achieved", None, 4)
        html = Sections.checklist({"checklist_rows": [tier],
                       "report": {"code_label": "NECB 2020"}})
        self.assertIn(">10.1.2.1.</a>", html)
        self.assertNotIn("2025", html)

    def test_coverage_status_modeller_scope_note(self):
        # D-09: a partial/not_implemented coverage entry flagged gap_owner
        # "modeller" renders as an info scope note, never a warning — and
        # never reaches the checklist. The flag must not soften anything else.
        entry = {"step": "coverage", "level": "info", "article": "8.4.2.3.",
                 "action": "Climatic Data — partial, modeller scope",
                 "inputs": {"status": "partial", "gap_owner": "modeller",
                            "decisions_citing": 2}}
        glyph, text = Sections.coverage_status(entry, set())
        self.assertEqual("info", glyph)
        self.assertEqual("modeller scope", text)
        self.assertEqual([], Checklist.rows([entry]),
                         "scope note stays off the checklist")

        glyph, _ = Sections.coverage_status({"inputs": {"status": "partial"}},
                                            set())
        self.assertEqual("warning", glyph, "unflagged partial still warns")
        glyph, _ = Sections.coverage_status(
            {"inputs": {"status": "not_implemented", "gap_owner": "engine"}},
            set())
        self.assertEqual("fail", glyph, 'only gap_owner "modeller" softens')
        glyph, _ = Sections.coverage_status(
            {"inputs": {"status": "implemented", "gap_owner": "modeller"}},
            set())
        self.assertEqual("pass", glyph, "flag is inert on implemented statuses")

    # -- rulings appendix (D-44) --------------------------------------------
    def test_rulings_appendix_renders_fired_decisions(self):
        entries = canned_audit().entries
        html = Sections.rulings_appendix({"audit_entries": entries})
        self.assertIn('id="rulings"', html)
        self.assertIn("Decisions and assumptions applied", html)
        # every id in the canned audit is listed...
        for id in ("D-19", "D-21", "D-43"):
            self.assertIn(id, html, f"{id} listed")
        # ...with its registry title and self-contained summary, not just the id
        self.assertIn(H.esc(Decisions.lookup("D-43")["title"]), html)
        self.assertIn(H.esc(Decisions.lookup("D-19")["summary"][:40]), html)
        # fire count: D-19 fired twice, D-21 once
        row = re.search(r"<tr><td>D-19</td>.*?</tr>", html, re.DOTALL).group(0)
        self.assertIn("<td>2</td>", row, "D-19 fire count is 2")
        row21 = re.search(r"<tr><td>D-21</td>.*?</tr>", html,
                          re.DOTALL).group(0)
        self.assertIn("<td>1</td>", row21, "D-21 fire count is 1")
        # anchor points at the FIRST firing entry, and that anchor exists
        first = next(i for i, e in enumerate(entries)
                     if "D-19" in str(e.get("ruling") or ""))
        self.assertIn(f'<a href="#audit-{first}">', html)
        self.assertIn(f'<tr id="audit-{first}">', render_report(canned_result()))
        # self-containment: the appendix never links out
        self.assertNotRegex(html, r'(src|href)\s*=\s*"https?://')

    def test_rulings_appendix_always_renders_with_a_placeholder(self):
        html = Sections.rulings_appendix(
            {"audit_entries": [{"step": "build", "action": "untagged"}]})
        self.assertIn('id="rulings"', html,
                      "section renders even with nothing to report")
        self.assertIn("No ruled code paths fired in this run.", html)

    def test_rulings_appendix_tolerates_an_unregistered_id(self):
        """`D-00` rather than `D-99`: D-99 is now a real decision, and
        D-01..D-99 are ALL taken, so `D-00` is the only remaining id that
        matches `^D-\\d{2}$` and is not registered. That the example had to
        move is the id grammar running out, not a quirk of this test."""
        html = Sections.rulings_appendix(
            {"audit_entries": [{"step": "build", "action": "x",
                                "ruling": "D-00"}]})
        self.assertIn("D-00", html)
        self.assertIn("not in registry", html)

    def test_building_stamp_traces_issues_to_their_model(self):
        audit = canned_audit()
        ref_warn = next(e for e in audit.entries if e.get("step") == "efficiency")
        input_warn = next(e for e in audit.entries if e.get("step") == "loads")
        verdict = next(e for e in audit.entries
                       if e.get("article") == "8.4.1.2.(2)")
        self.assertEqual("reference building", ref_warn["building"],
                         "warning stamped with its model")
        self.assertEqual("input model", input_warn["building"])
        self.assertIsNone(verdict.get("building"),
                          "cross-building verdicts carry no stamp")
        self.assertIsNone(audit.building,
                          "with_building restores the outer context")

        rows = Checklist.rows(audit.entries)
        self.assertEqual("reference building",
                         next(r for r in rows
                              if r.article == "Table 5.2.12.1.").building)

        html = render_report(canned_result())
        self.assertIn("bldg-reference", html, "reference chip rendered")
        self.assertIn("bldg-input", html, "input-model chip rendered")
        self.assertIn(">Applies to<", html,
                      "checklist/audit tables carry the Applies-to column")
        self.assertIn("building: reference building", str(audit),
                      "audit.txt narrative carries the stamp")

    def test_checklist_measured_values(self):
        row = next(r for r in Checklist.rows(canned_audit().entries)
                   if r.article == "8.4.1.2.(2)")
        self.assertIn("proposed_kwh: 90000.0", row.measured)

    def test_paired_bars_matches_the_ruby_golden_byte_for_byte(self):
        svg = Charts.paired_bars(
            [["Heating", 50_000.0, 55_000.0], ["Cooling", 5_000.0, 6_000.0]],
            unit="kWh", label="test chart")
        self.assertIn(H.PROPOSED_COLOR, svg)
        self.assertIn(H.REFERENCE_COLOR, svg)
        self.assertTrue(RUBY_GOLDEN.exists(),
                        f"the Ruby golden must exist: {RUBY_GOLDEN}")
        normalized = re.sub(r"\s+", " ", svg).strip()
        self.assertEqual(RUBY_GOLDEN.read_text(encoding="utf-8"), normalized,
                         "the Python chart drifted from the Ruby golden")

    def test_paired_bars_edge_cases(self):
        self.assertEqual("", Charts.paired_bars([], unit="kWh", label="x"))
        self.assertEqual("", Charts.paired_bars([["a", 0, 0]], unit="kWh",
                                                label="x"))
        solo = Charts.paired_bars([["a", 10.0, None]], unit="kWh", label="x")
        self.assertNotIn(H.REFERENCE_COLOR, solo,
                         "None reference renders proposed-only")

    def test_total_bars_target_line(self):
        svg = Charts.total_bars(
            [["Proposed", 90_000.0], ["Reference", 100_000.0]],
            targets=[["BET (8.4.4)", 120_000.0]])
        self.assertIn("stroke-dasharray", svg)
        self.assertIn("BET (8.4.4)", svg)

    def test_full_render_from_canned_data(self):
        html = render_report(canned_result(),
                             {"project_name": "Unit Test Tower",
                              "prepared_by": "A. Modeller"})
        self.assertIn("PERFORMANCE PATH: PASS", html)
        self.assertIn("EUI PATH (8.4.4): PASS", html)
        self.assertIn("TIER 1", html)
        self.assertIn("GHG LEVEL B", html)
        self.assertIn("Operational GHG emissions (NECB 2025 Part 11)", html)
        self.assertIn("LEVEL B", html)
        self.assertIn("Table 8.4.4.1", html)
        self.assertIn("Incremental cost", html)
        self.assertIn("Unit Test Tower", html)
        # every internal link resolves
        hrefs = set(re.findall(r'href="#([^"]+)"', html))
        ids = set(re.findall(r'id="([^"]+)"', html))
        missing = hrefs - ids
        self.assertEqual(set(), missing, f"dangling anchors: {missing}")
        # single-file guarantee: no external fetches of any kind. The loop
        # chooser adds ONE inline <script>, so allow an inline script but
        # forbid an external one (src=), and keep external stylesheets /
        # @import / url() forbidden.
        self.assertNotRegex(html, r'(src|href)\s*=\s*"https?://')
        self.assertNotRegex(html, r"<link\b")
        self.assertNotRegex(html, r"<script[^>]*\bsrc=")
        self.assertNotRegex(html, r"@import|url\(")

    def test_hvac_section_handles_nil_and_stub_bundles(self):
        # The HVAC section consumes btap.modeling's diagram bundles (plain
        # dicts) that the assembler computes off the SDK models. With
        # None/absent models it must render explanatory notes, never crash.
        stub = {"loops": [{"kind": "hot_water", "label": "Hot water loop",
                           "svg": '<svg width="10" height="10">'
                                  "<title>stub loop</title></svg>"}],
                "zone_equipment_svg": '<svg width="10" height="10">'
                                      "<title>stub zeq</title></svg>",
                "empty": False}
        # proposed present (stub), reference None (e.g. EUI path)
        html = Sections.hvac({"proposed_hvac": stub, "reference_hvac": None,
                              "audit_entries": []})
        self.assertIn("Proposed building systems", html)
        self.assertIn("Hot water loop", html)
        self.assertIn("stub loop", html)
        self.assertIn("Zone equipment", html)
        self.assertIn("Reference building systems", html)
        self.assertIn("No reference building on this path", html)

        # empty proposed bundle (no loops, no zone equipment) states so
        empty_html = Sections.hvac(
            {"proposed_hvac": {"loops": [], "zone_equipment_svg": None,
                               "empty": True},
             "reference_hvac": None, "audit_entries": []})
        self.assertIn("No central HVAC loops", empty_html)

        # keys entirely absent (report-only render) -> notes, no crash
        absent_html = Sections.hvac({"audit_entries": []})
        self.assertIn("HVAC systems", absent_html)
        self.assertIn("report-only mode", absent_html)

    def test_full_render_embeds_hvac_icon_defs_and_diagram_css(self):
        # The canned full render carries the reused diagram plumbing: the icon
        # <defs> are embedded once, DIAGRAM_CSS is in the stylesheet, and it
        # stays self-contained (icons are data-URIs, not url()/remote refs).
        html = render_report(canned_result())
        self.assertIn('<symbol id="icon-', html, "HVAC icon defs embedded once")
        self.assertIn("data:image/png;base64,", html,
                      "icons are self-contained data-URIs")
        self.assertRegex(html, r"\.diagram\s*\{[^}]*overflow-x:\s*auto",
                         "diagram scroll CSS present")
        self.assertRegex(html, r"\.diagram\s+svg\s*\{[^}]*width:\s*auto",
                         "intrinsic-size svg override present")
        # still self-contained: allow the one inline chooser <script>
        self.assertNotRegex(html, r"<link\b")
        self.assertNotRegex(html, r"<script[^>]*\bsrc=")
        self.assertNotRegex(html, r"@import|url\(")
        self.assertNotRegex(html, r'(src|href)\s*=\s*"https?://')

    def test_shortened_run_warns_loudly(self):
        report = {**canned_report(), "annual": False}
        result = ComplianceResult(proposed_model=None, reference_model=None,
                                  report=report, audit=canned_audit(),
                                  compliant=True, run_dir=None)
        self.assertIn("SHORTENED RUN PERIOD", render_report(result))

    def test_undetermined_run(self):
        report = {**canned_report(), "compliant": None, "annual": None}
        report.pop("tier")
        result = ComplianceResult(proposed_model=None, reference_model=None,
                                  report=report, audit=AuditLog(),
                                  compliant=None, run_dir=None)
        html = render_report(result)
        self.assertIn("UNDETERMINED", html)
        self.assertNotIn("PERFORMANCE PATH: PASS", html)


#: Text that would show if any part of a registry entry other than its title
#: and summary reached the report: markup, a link out, ruling-shaped ids and a
#: sentinel no committed text contains.
SENTINEL = "SCHEMA-2-METADATA-SENTINEL"
HOSTILE = ('<script>alert("x")</script> <a href="https://example.invalid">x</a> '
           "D-01 D-43 D-9999 " + SENTINEL)


def registry_variants(committed):
    """Rewrites of EVERY entry that keep its id, title, kind and summary."""
    def runtime_fields(entry):
        return {field: entry[field] for field in ("id", "title", "kind", "summary")}

    def requirements():
        return [{"id": "hostile_requirement", "label": HOSTILE, "decided": HOSTILE,
                 "sources": [
                     {"code": "necb", "edition": "2020", "role": "governing",
                      "references": [HOSTILE]},
                     {"code": "ashrae-62.1", "edition": "2016",
                      "role": "incorporated-reference", "references": [HOSTILE]},
                     {"code": "necb", "edition": "2030", "role": "related",
                      "references": [HOSTILE]}]}]

    def structured(entry):
        return dict(runtime_fields(entry), editions=["necb2025"],
                    requirements=requirements())

    def mutated(entry):
        changed = copy.deepcopy(entry)
        changed["editions"] = (["necb2020"] if entry.get("editions") == ["unverified"]
                               else ["unverified"])
        changed["articles"] = {"hostile": {"label": HOSTILE, "necb2020": [HOSTILE]}}
        changed["requirements"] = requirements()
        return dict(reversed(list(changed.items())))

    return {"structured": [structured(entry) for entry in committed],
            "runtime fields only": [runtime_fields(entry) for entry in committed],
            "mutated editions, articles and requirements":
                [mutated(entry) for entry in committed]}


class TestTheRulingsAppendixReadsOnlyTitleAndSummary(unittest.TestCase):
    """Schema 2 adds committee metadata -- ``requirements``, their ``sources``
    and ``decided``, and a derived ``editions`` -- that the compliance report
    does not render (docs/plans/DECISION_APPLICABILITY_PLAN.md). With the
    fired ids and their titles and summaries unchanged, no rewrite of that
    metadata may change one byte of the rulings appendix or of the report."""

    FIRED = ("D-19", "D-21", "D-43")

    @classmethod
    def setUpClass(cls):
        cls.committed = copy.deepcopy(Decisions.all_decisions())
        cls.appendix, cls.report = cls.rendered(cls.committed)

    @staticmethod
    def rendered(decisions):
        """``(rulings appendix, full report)`` with the registry read from a
        schema-2 FILE holding ``decisions``: the loader's own path."""
        with tempfile.TemporaryDirectory() as scratch:
            payload = {"_comment": ["fixture"], "schema": Decisions.SCHEMA,
                       "decisions": decisions}
            (Path(scratch) / "decisions.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(Decisions, "DATA_DIR", Path(scratch)), \
                    mock.patch.object(Decisions, "_all", None), \
                    mock.patch.object(Decisions, "_by_id", None):
                return (Sections.rulings_appendix(
                            {"audit_entries": canned_audit().entries}),
                        render_report(canned_result()))

    def with_entry(self, decision_id, **changes):
        return [dict(entry, **changes) if entry["id"] == decision_id else entry
                for entry in self.committed]

    def test_the_canned_run_fires_exactly_these_registered_rulings(self):
        fired = {decision_id for entry in canned_audit().entries
                 for decision_id in Decisions.ids_in(entry.get("ruling"))}
        self.assertEqual(set(self.FIRED), fired)
        registered = {entry["id"] for entry in self.committed}
        self.assertLessEqual(fired, registered)

    def test_the_file_backed_registry_renders_as_the_committed_one(self):
        self.assertEqual(
            Sections.rulings_appendix({"audit_entries": canned_audit().entries}),
            self.appendix)
        self.assertEqual(render_report(canned_result()), self.report)
        self.assertEqual(1, self.report.count(self.appendix))
        for decision_id in self.FIRED:
            self.assertIn("<td>{}</td>".format(decision_id), self.appendix)

    def test_requirements_sources_and_decided_never_reach_the_html(self):
        for name, decisions in registry_variants(self.committed).items():
            with self.subTest(variant=name):
                appendix, report = self.rendered(decisions)
                self.assertEqual(self.appendix, appendix)
                self.assertEqual(self.report, report)
                self.assertNotIn(SENTINEL, report)

    def test_a_fired_title_or_summary_does_change_the_html(self):
        """The control: the comparison above can fail, and the change it
        detects is confined to the appendix."""
        by_id = {entry["id"]: entry for entry in self.committed}
        for decision_id in self.FIRED:
            for field in ("title", "summary"):
                with self.subTest(decision=decision_id, field=field):
                    changed = by_id[decision_id][field] + " (amended)"
                    appendix, report = self.rendered(
                        self.with_entry(decision_id, **{field: changed}))
                    self.assertNotEqual(self.appendix, appendix)
                    self.assertIn(H.esc(changed), appendix)
                    self.assertEqual(1, report.count(appendix))
                    self.assertEqual(self.report, report.replace(appendix, self.appendix))

    def test_an_entry_that_did_not_fire_is_not_rendered(self):
        quiet = next(entry["id"] for entry in self.committed
                     if entry["id"] not in self.FIRED)
        self.assertEqual((self.appendix, self.report),
                         self.rendered(self.with_entry(quiet, title=HOSTILE,
                                                       summary=HOSTILE)))

    def test_a_fired_entry_missing_from_the_registry_is_named(self):
        appendix, _ = self.rendered([entry for entry in self.committed
                                     if entry["id"] != "D-43"])
        self.assertIn("not in registry", appendix)
        self.assertNotEqual(self.appendix, appendix)


#: The decisions converted to structured requirements (Phase C's 23 and Phase
#: D's 42), in id order.
#: tests/necb/test_decisions_registry_sync.py pins the same set as MIGRATED_IDS.
MIGRATED = ("D-02", "D-03", "D-04", "D-05", "D-06", "D-07", "D-09", "D-11",
            "D-12", "D-13", "D-14", "D-15", "D-17", "D-18", "D-19", "D-21",
            "D-22", "D-23", "D-24", "D-26", "D-27", "D-28", "D-31", "D-32",
            "D-34", "D-35", "D-37", "D-38", "D-39", "D-41", "D-42", "D-43",
            "D-45", "D-46", "D-47", "D-48", "D-49", "D-50", "D-51", "D-52",
            "D-53", "D-54", "D-55", "D-56", "D-57", "D-58", "D-59", "D-60",
            "D-61", "D-62", "D-63", "D-65", "D-74", "D-76", "D-85", "D-89",
            "D-90", "D-91", "D-92", "D-93", "D-97", "D-99", "D-100", "D-101",
            "D-102")


def migrated_audit():
    """The canned run plus one ruled decision for every migrated id."""
    audit = canned_audit()
    for decision_id in MIGRATED:
        audit.decision("reference", "migrated ruling applied",
                       target=decision_id, ruling=decision_id)
    return audit


def legacy_shaped(entry):
    """A structured entry put back in the per-code-id ``articles`` form the
    migrations replaced, keeping its id, title, kind, editions and summary."""
    if "requirements" not in entry:
        return entry
    articles = {}
    for requirement in entry["requirements"]:
        block = articles[requirement["id"]] = {"label": requirement["label"]}
        for source in requirement["sources"]:
            block[source["code"] + source["edition"]] = list(source["references"])
    return {"id": entry["id"], "title": entry["title"], "kind": entry["kind"],
            "articles": articles, "editions": list(entry["editions"]),
            "summary": entry["summary"]}


class TestTheMigratedDecisionsRenderAsTheirLegacyShape(unittest.TestCase):
    """The migrations (Phase C's 23 decisions, then Phase D's 42)
    changed how 65 decisions record their provisions and nothing a
    report reads. A run that fires every one of them renders the same rulings
    appendix and the same report whether the registry holds them structured,
    back in the per-code-id shape they replaced, or reduced to the fields the
    runtime reads."""

    @classmethod
    def setUpClass(cls):
        cls.committed = copy.deepcopy(Decisions.all_decisions())
        cls.by_id = {entry["id"]: entry for entry in cls.committed}
        cls.appendix, cls.report = cls.rendered(cls.committed)

    @staticmethod
    def rendered(decisions):
        """``(rulings appendix, full report)`` with the registry read from a
        schema-2 FILE holding ``decisions``: the loader's own path."""
        with tempfile.TemporaryDirectory() as scratch:
            payload = {"_comment": ["fixture"], "schema": Decisions.SCHEMA,
                       "decisions": decisions}
            (Path(scratch) / "decisions.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(Decisions, "DATA_DIR", Path(scratch)), \
                    mock.patch.object(Decisions, "_all", None), \
                    mock.patch.object(Decisions, "_by_id", None):
                result = ComplianceResult(
                    proposed_model=None, reference_model=None,
                    report=canned_report(), audit=migrated_audit(),
                    compliant=True, run_dir=None)
                return (Sections.rulings_appendix(
                            {"audit_entries": migrated_audit().entries}),
                        render_report(result))

    def test_the_registry_holds_exactly_these_structured_entries(self):
        structured = [entry["id"] for entry in self.committed
                      if "requirements" in entry]
        self.assertEqual(list(MIGRATED), structured)
        for decision_id in MIGRATED:
            self.assertNotIn("articles", self.by_id[decision_id])

    def test_the_run_fires_every_migrated_ruling(self):
        fired = {decision_id for entry in migrated_audit().entries
                 for decision_id in Decisions.ids_in(entry.get("ruling"))}
        self.assertEqual(set(MIGRATED) | {"D-19", "D-21", "D-43"}, fired)

    def test_the_file_backed_registry_renders_as_the_committed_one(self):
        result = ComplianceResult(proposed_model=None, reference_model=None,
                                  report=canned_report(), audit=migrated_audit(),
                                  compliant=True, run_dir=None)
        self.assertEqual(
            Sections.rulings_appendix({"audit_entries": migrated_audit().entries}),
            self.appendix)
        self.assertEqual(render_report(result), self.report)
        self.assertEqual(1, self.report.count(self.appendix))

    def test_each_migrated_ruling_renders_its_title_and_summary_only(self):
        self.assertNotIn("not in registry", self.appendix)
        for decision_id in MIGRATED:
            entry = self.by_id[decision_id]
            with self.subTest(decision=decision_id):
                self.assertEqual(1, self.appendix.count(
                    "<td>{}</td>".format(decision_id)))
                self.assertIn(H.esc(entry["title"]), self.appendix)
                self.assertIn(H.esc(entry["summary"]), self.appendix)
                for requirement in entry["requirements"]:
                    self.assertNotIn(H.esc(requirement["decided"]), self.report)

    def test_the_legacy_shape_and_the_runtime_fields_render_byte_identically(self):
        variants = {
            "legacy per-code-id articles":
                [legacy_shaped(entry) for entry in self.committed],
            "runtime fields only":
                [{field: entry[field] for field in ("id", "title", "kind", "summary")}
                 for entry in self.committed],
        }
        legacy = variants["legacy per-code-id articles"]
        self.assertEqual(
            list(MIGRATED),
            [entry["id"] for entry, old in zip(self.committed, legacy)
             if entry != old],
            "the legacy variant rewrites exactly the migrated entries")
        for name, decisions in variants.items():
            with self.subTest(variant=name):
                self.assertEqual((self.appendix, self.report),
                                 self.rendered(decisions))

    def test_a_migrated_title_or_summary_does_change_the_html(self):
        """The control: the comparison above can fail for every migrated id,
        and the change it detects is confined to the appendix."""
        for decision_id in MIGRATED:
            for field in ("title", "summary"):
                with self.subTest(decision=decision_id, field=field):
                    changed = self.by_id[decision_id][field] + " (amended)"
                    appendix, report = self.rendered(
                        [dict(entry, **{field: changed})
                         if entry["id"] == decision_id else entry
                         for entry in self.committed])
                    self.assertNotEqual(self.appendix, appendix)
                    self.assertIn(H.esc(changed), appendix)
                    self.assertEqual(1, report.count(appendix))
                    self.assertEqual(self.report,
                                     report.replace(appendix, self.appendix))


if __name__ == "__main__":
    unittest.main()
