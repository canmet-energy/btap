"""Port of btap-necb/test/test_report_units.rb: SDK-free renderer units —
HTML helpers, checklist derivation, charts, and the full-document render from
CANNED report/audit data (no models, no simulation).

The paired_bars golden is THE RUBY SUITE'S OWN golden file
(btap-necb/test/goldens/paired_bars.svg) consumed as-is — a cross-language
byte-equality gate, per the M3 catalog-report precedent."""

import re
import unittest
from pathlib import Path

from btap.audit import AuditLog
from btap.necb import decisions as Decisions
from btap.necb.compliance import ComplianceResult
from btap.necb.report import charts as Charts
from btap.necb.report import checklist as Checklist
from btap.necb.report import html as H
from btap.necb.report import render as render_report
from btap.necb.report import sections as Sections

RUBY_GOLDEN = (Path(__file__).resolve().parents[3] / "btap-necb" / "test"
               / "goldens" / "paired_bars.svg")


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
        "vintage": "2025", "hdd": 3890, "simulate": "annual", "annual": True,
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
        html = Sections.rulings_appendix(
            {"audit_entries": [{"step": "build", "action": "x",
                                "ruling": "D-99"}]})
        self.assertIn("D-99", html)
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


if __name__ == "__main__":
    unittest.main()
