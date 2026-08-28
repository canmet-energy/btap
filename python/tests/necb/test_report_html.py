"""Port of btap-necb/test/test_report_html.rb: whole-document render from a
REAL pipeline result (sizing mode — fast), plus the report_html hook. The
canned-data render lives in test_report_units.py."""

import os
import re
import tempfile
import unittest
from pathlib import Path

from btap.necb import performance_compliance
from btap.necb import report as report_renderer
from tests.necb.support import (
    DDY,
    EPW,
    needs_engine,
    proposed_with_hvac,
    zone_types_for,
)


def weather():
    return {"epw": str(EPW), "ddy": str(DDY)}


def building_for(model):
    return {"storeys": 1, "zone_types": zone_types_for(model),
            "winter_design_temp_c": -20}


@needs_engine
class TestReportHTML(unittest.TestCase):
    def test_sizing_mode_render_with_real_models(self):
        dir = tempfile.mkdtemp(prefix="osnecb-rpt-")
        proposed = proposed_with_hvac()
        result = performance_compliance(
            proposed, vintage="2020", simulate="sizing", weather=weather(),
            building=building_for(proposed), run_dir=dir)

        html = report_renderer.render(
            result, {"project_name": "Sizing Fixture",
                     "address": "123 Test St, Toronto ON"})
        self.assertIn("UNDETERMINED", html,
                      "sizing mode makes no compliance determination")
        self.assertIn("NECB 2020 Energy Code Compliance Report", html)
        self.assertIn("Sizing Fixture", html)
        # real models flow through model_query: envelope chart renders
        self.assertIn("Area-weighted average U-value", html,
                      "envelope chart from the real model")
        # HVAC diagrams come from btap.modeling's loop-diagram engine: the
        # icon <defs> are embedded once and both buildings render.
        self.assertIn('<symbol id="icon-', html, "modeling icon defs embedded")
        self.assertIn("Proposed building systems", html)
        self.assertIn("Reference building systems", html)
        self.assertGreaterEqual(html.count('class="diagram"'), 2,
                                "proposed + reference loop diagrams present")
        # a boiler-served proposed system references the embedded icons
        self.assertIn('<use href="#icon-', html,
                      "diagram cells reference embedded OS App icons")
        # loops are shown in an OpenStudio-App-style per-building dropdown
        # chooser: one <select> per building, one panel per loop, and
        # air-loop options are zone-labelled.
        self.assertGreaterEqual(html.count('class="loop-select"'), 2,
                                "proposed + reference loop selects")
        self.assertIn('class="loop-panel"', html, "per-loop panels present")
        self.assertRegex(html, r'<option value="[^"]*">Air loop — ',
                         "air-loop option is zone-labelled")
        self.assertGreaterEqual(html.count("<svg"), 3,
                                "charts + diagrams + icon defs")
        self.assertIn("Full audit trail", html)
        # anchors resolve; no external references
        hrefs = set(re.findall(r'href="#([^"]+)"', html))
        ids = set(re.findall(r'id="([^"]+)"', html))
        self.assertEqual(set(), hrefs - ids,
                         "every checklist/audit anchor resolves")
        self.assertNotRegex(html, r'(src|href)\s*=\s*"https?://')
        # the loop chooser uses ONE inline script; still no external
        # stylesheet or external (src=) script — single-file guarantee holds.
        self.assertNotRegex(html, r"<link\b")
        self.assertNotRegex(html, r"<script[^>]*\bsrc=")

    def test_annual_2025_both_paths_report(self):
        # The full AHJ document: 2025 week run, BOTH compliance paths
        # (8.4.1.2 performance + 8.4.4 archetype-EUI supplement), Part 11
        # GHG, tiers.
        dir = tempfile.mkdtemp(prefix="osnecb-rpt2025-")
        proposed = proposed_with_hvac()
        result = performance_compliance(
            proposed, vintage="2025", simulate="annual", weather=weather(),
            building=building_for(proposed), run_dir=dir,
            run_period={"begin_month": 1, "begin_day": 1, "end_month": 1,
                        "end_day": 7},
            province_state="ONTARIO",
            eui_supplement={"archetypes": {"Office": "all"},
                            "run_normalized": True},
            report_html=True,
            report_options={"project_name": "E2E Fixture Building",
                            "address": "Toronto, ON",
                            "prepared_by": "btap test suite"})

        path = os.path.join(dir, "compliance_report.html")
        self.assertTrue(os.path.exists(path))
        html = Path(path).read_text(encoding="utf-8")
        self.assertRegex(html, r"PERFORMANCE PATH: (PASS|FAIL)",
                         "8.4.1.2 verdict rendered")
        self.assertRegex(html, r"EUI PATH \(8\.4\.4\): (PASS|FAIL)",
                         "8.4.4 supplement verdict rendered")
        self.assertTrue(result.report["eui_path"]["computed"],
                        "supplement computed via the normalized run")
        self.assertIn("normalized", result.report["eui_path"]["basis"],
                      "verdict basis names the Table-8.4.4.2-normalized run")
        self.assertIn("proposed_eui_normalized", result.report,
                      "the second (normalized) annual result is stored")
        self.assertIn("Operational GHG emissions (NECB 2025 Part 11)", html)
        self.assertIn("Table 8.4.4.1", html, "BET line table present")
        self.assertIn("SHORTENED RUN PERIOD", html, "week run flagged loudly")
        self.assertIn("eui_path", result.report,
                      "supplement stored in the report dict")
        hrefs = set(re.findall(r'href="#([^"]+)"', html))
        ids = set(re.findall(r'id="([^"]+)"', html))
        self.assertEqual(set(), hrefs - ids)

    def test_report_html_hook_writes_file(self):
        dir = tempfile.mkdtemp(prefix="osnecb-rpthook-")
        proposed = proposed_with_hvac()
        result = performance_compliance(
            proposed, vintage="2020", simulate="sizing", weather=weather(),
            building=building_for(proposed), run_dir=dir,
            report_html=True, report_options={"project_name": "Hook Test"})

        path = os.path.join(result.run_dir, "compliance_report.html")
        self.assertTrue(os.path.exists(path),
                        "report_html=True writes compliance_report.html")
        self.assertIn("Hook Test", Path(path).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
