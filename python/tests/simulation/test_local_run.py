"""Real end-to-end LOCAL EnergyPlus runs through the Python Local backend
(in-process ForwardTranslator + the provisioned engine) — the port of
test_local_run.rb, plus the M2 decisive gate: the same model run by the RUBY
gem (via the openstudio CLI) and by this port must produce equivalent
results under the Leg-B differ rules.

The plain-Python annual tests use the bare fixture (thermostats, no
systems — EnergyPlus free-floats the zones and the parse surface is
identical); the cross-language class below carries a REAL HVAC system built
by each language's own btap-modeling port (added when M3 landed it)."""

import pathlib
import shutil
import tempfile
import unittest
from pathlib import Path

from btap.simulation import run, runner
from tests.support import DDY, EPW, load_fixture, needs_engine, needs_sdk


def week():
    return {"begin_month": 1, "begin_day": 1, "end_month": 1, "end_day": 7}


@needs_engine
class TestLocalRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_sizing_only_run_of_bare_fixture(self):
        # Sizing needs no HVAC: attach weather, run a design-day-only pass on
        # the bare fixture (which carries thermostats), confirm a clean SQL.
        target = str(Path(self.tmp.name) / "sizing")
        result = run(load_fixture(), run_dir=target,
                     weather={"epw": str(EPW), "ddy": str(DDY)}, sizing_only=True)

        self.assertTrue(result.is_clean(), "sizing run should complete cleanly")
        self.assertTrue((Path(target) / "run" / "eplusout.sql").is_file())
        self.assertEqual(str(Path(target) / "run"), result.run_dir)
        self.assertIsNone(result.energy, "sizing_only run reports no energy")
        self.assertIsNone(result.unmet_hours, "sizing_only run reports no unmet hours")

    def test_short_annual_run_parses_results(self):
        target = str(Path(self.tmp.name) / "annual")
        result = run(load_fixture(), run_dir=target,
                     weather={"epw": str(EPW), "ddy": str(DDY)}, run_period=week())

        self.assertTrue(result.is_clean(), "annual run should complete cleanly")
        energy = result.energy
        self.assertIsInstance(energy, dict)
        for key in ("total_site_kwh", "electricity_kwh", "natural_gas_kwh",
                    "floor_area_m2", "end_uses_kwh"):
            self.assertIn(key, energy)
        for key in ("heating", "cooling", "fans", "pumps", "interior_lighting",
                    "interior_equipment", "water_systems"):
            self.assertIn(key, energy["end_uses_kwh"])
        self.assertGreater(energy["floor_area_m2"], 0)

        unmet = result.unmet_hours
        self.assertIsInstance(unmet, dict)
        self.assertIn("heating", unmet)
        self.assertIn("cooling", unmet)

        zones = runner.zone_unmet_occupied_hours(
            # the SQL is attached to the model run() used internally; re-run
            # the parse through the public seam on a fresh handle
            self._model_with_sql(target))
        self.assertIsInstance(zones, dict)

    def _model_with_sql(self, target):
        import openstudio
        model = load_fixture()
        model.setSqlFile(openstudio.SqlFile(
            openstudio.path(str(Path(target) / "run" / "eplusout.sql"))))
        return model

    def test_run_directory_containing_a_space_still_simulates(self):
        # THE quoting regression the Ruby gem paid for: ARGV-form execution
        # means a path with spaces (the Windows norm) cannot split.
        target = str(Path(self.tmp.name) / "a directory with spaces" / "run")
        model = load_fixture()
        runner.attach_weather(model, epw=str(EPW), ddy=str(DDY))
        out_dir = runner.run_energyplus(model, target, sizing_only=True)

        self.assertTrue((Path(out_dir) / "eplusout.sql").is_file(), "no SQL — the path split")
        self.assertTrue(runner.is_clean_run(out_dir))
        self.assertTrue((Path(target) / "cli.log").is_file(), "cli.log landed outside the run dir")

if __name__ == "__main__":
    unittest.main()

class TestDesignDayAuditTellsTheTruth(unittest.TestCase):
    """D-25's audit entry must not claim a filter that did not happen.

    `attach_weather` keeps only the annual-extreme design days — unless NONE of
    them match, in which case it deliberately keeps the whole DDY rather than
    none. The first version of the entry asserted "filtered to the annual
    extremes ... sized on the 99.6% heating and 0.4% cooling days only"
    unconditionally, so on that supported fallback it stated a false modelling
    assumption in a document an AHJ reads — while its own `inputs` recorded
    `kept_all_as_fallback: true` and a kept-count equal to the whole file.
    Sol reproduced it by renaming the three matching days in the shipped Toronto
    DDY (`084`).
    """

    KEEP_PATTERNS = (r"Htg 99.6. Condns DB", r"Clg .4% Condns DB=>MWB",
                     r"Clg 0.4% Condns DB=>MCWB", r"Clg .4. Condns WB=>MDB")

    def _ddy_with_no_extremes(self):
        """The shipped DDY with every annual-extreme NAME made non-matching."""
        import re

        text = pathlib.Path(DDY).read_text(encoding="latin-1")
        out = []
        for line in text.splitlines(keepends=True):
            if any(re.search(p, line) for p in self.KEEP_PATTERNS):
                line = line.replace("Htg 99.6%", "Htg Ordinary") \
                           .replace("Clg .4%", "Clg Ordinary") \
                           .replace("Clg 0.4%", "Clg Ordinary")
            out.append(line)
        directory = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = directory / "no-extremes.ddy"
        path.write_text("".join(out), encoding="latin-1")
        return path

    @needs_sdk
    def test_the_normal_path_says_it_filtered(self):
        from btap.audit import AuditLog

        audit = AuditLog()
        model = load_fixture()
        runner.attach_weather(model, epw=str(EPW), ddy=str(DDY), audit=audit)
        entry = next(e for e in audit.entries if e.get("ruling") == "D-25")
        self.assertFalse(entry["inputs"]["kept_all_as_fallback"])
        self.assertIn("filtered to the annual extremes", entry["action"])
        self.assertLess(entry["inputs"]["design_days_kept"],
                        entry["inputs"]["design_days_in_file"],
                        "the normal path must keep FEWER than the file holds")

    @needs_sdk
    def test_the_FALLBACK_path_does_not_claim_a_filter(self):
        from btap.audit import AuditLog

        ddy = self._ddy_with_no_extremes()
        audit = AuditLog()
        model = load_fixture()
        runner.attach_weather(model, epw=str(EPW), ddy=str(ddy), audit=audit)
        entry = next(e for e in audit.entries if e.get("ruling") == "D-25")
        inputs = entry["inputs"]
        self.assertTrue(inputs["kept_all_as_fallback"],
                        "precondition: this DDY must trigger the fallback")
        self.assertEqual(inputs["design_days_kept"], inputs["design_days_in_file"],
                         "the fallback keeps the WHOLE file")
        # the claim must match the evidence
        self.assertIn("FULL file was retained", entry["action"])
        self.assertNotIn("0.4% cooling days only", entry["action"])
        self.assertNotIn("filtered to the annual extremes", entry["action"])

    def _ddy_with_only(self, kind):
        """The shipped DDY with ONE kind of annual extreme left matching.

        The third state Fable found: `fell_back = not extremes` is a TOTAL-miss
        test, so a partial match left the filtered text claiming "the 99.6%
        heating AND 0.4% cooling days" while only one kind was attached.
        """
        import re

        drop = r"Clg" if kind == "heating" else r"Htg"
        text = pathlib.Path(DDY).read_text(encoding="latin-1")
        out = []
        for line in text.splitlines(keepends=True):
            if re.search(drop, line) and any(
                    re.search(p, line) for p in self.KEEP_PATTERNS):
                line = (line.replace("Htg 99.6%", "Htg Ordinary")
                            .replace("Clg .4%", "Clg Ordinary")
                            .replace("Clg 0.4%", "Clg Ordinary"))
            out.append(line)
        directory = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = directory / f"only-{kind}.ddy"
        path.write_text("".join(out), encoding="latin-1")
        return path

    @needs_sdk
    def test_a_PARTIAL_match_does_not_claim_the_kind_it_lacks(self):
        """Fable's L1. The state between 'all matched' and 'none matched'."""
        from btap.audit import AuditLog

        ddy = self._ddy_with_only("heating")
        audit = AuditLog()
        model = load_fixture()
        runner.attach_weather(model, epw=str(EPW), ddy=str(ddy), audit=audit)
        entry = next(e for e in audit.entries if e.get("ruling") == "D-25"
                     and e["level"] == "decision")
        inputs = entry["inputs"]
        self.assertFalse(inputs["kept_all_as_fallback"],
                         "precondition: this is NOT the total-miss fallback")
        self.assertGreater(inputs["design_days_kept_heating"], 0,
                           "precondition: a heating extreme must have matched")
        self.assertEqual(0, inputs["design_days_kept_cooling"],
                         "precondition: no cooling extreme may have matched")
        self.assertNotIn("0.4% cooling days only", entry["action"],
                         "it must not claim a cooling day it does not have")
        self.assertIn("NO COOLING", entry["action"])

    @needs_sdk
    def test_a_PARTIAL_match_warns_because_sizing_is_affected(self):
        """Warnings are never silent, and this one has a sizing consequence."""
        from btap.audit import AuditLog

        ddy = self._ddy_with_only("heating")
        audit = AuditLog()
        model = load_fixture()
        runner.attach_weather(model, epw=str(EPW), ddy=str(ddy), audit=audit)
        warnings = [e for e in audit.entries if e["level"] == "warning"
                    and e.get("ruling") == "D-25"]
        self.assertEqual(1, len(warnings),
                         "a missing design condition must warn, not only record")
        self.assertIn("autosize", warnings[0]["action"])

    @needs_sdk
    def test_every_path_says_replaced_not_appended(self):
        """Fable's L3: the clause holds in all three states, and a modeller who
        supplied their own design days is most likely to have it wrong."""
        from btap.audit import AuditLog

        cases = {"normal": DDY,
                 "fallback": None,       # filled below
                 "partial": None}
        cases["fallback"] = self._ddy_with_no_extremes()
        cases["partial"] = self._ddy_with_only("heating")
        for label, ddy in cases.items():
            with self.subTest(state=label):
                audit = AuditLog()
                runner.attach_weather(load_fixture(), epw=str(EPW),
                                      ddy=str(ddy), audit=audit)
                entry = next(e for e in audit.entries
                             if e.get("ruling") == "D-25"
                             and e["level"] == "decision")
                self.assertIn("replaced, not appended", entry["action"])

    @needs_sdk
    def test_the_discarded_count_is_real(self):
        """Fable's L4: `design_days_discarded` always-0 SURVIVED mutation.

        The entry's own rationale is that it states the inputs it is evidenced
        by, so a count that could silently go to zero is not evidence.
        """
        from btap.audit import AuditLog

        model = load_fixture()
        # give the model design days to discard, which is the only way the
        # count can be non-trivially exercised
        runner.attach_weather(model, epw=str(EPW), ddy=str(DDY))
        before = len(model.getDesignDays())
        self.assertGreater(before, 0, "precondition: the model now has days")

        audit = AuditLog()
        runner.attach_weather(model, epw=str(EPW), ddy=str(DDY), audit=audit)
        entry = next(e for e in audit.entries if e.get("ruling") == "D-25"
                     and e["level"] == "decision")
        self.assertEqual(before, entry["inputs"]["design_days_discarded"],
                         "the discarded count must equal what was there")

    def _ddy_with_a_monthly_cooling_day(self):
        """The shipped DDY plus a MONTHLY cooling day spelled like the annual.

        Toronto's DDY carries no monthly days, so the leak cannot be observed
        on it — it has to be constructed. The added day differs from the annual
        0.4% day only in its `Ann` -> `JUL` token, which is precisely what the
        unanchored patterns failed to constrain.
        """
        import re

        text = pathlib.Path(DDY).read_text(encoding="latin-1")
        # lift the annual 0.4% cooling object and re-emit it as a July day
        objects = re.split(r"\n(?=SizingPeriod:DesignDay)", text)
        annual = next(o for o in objects
                      if re.search(r"Ann Clg .4% Condns DB=>MWB", o))
        monthly = annual.replace("Ann Clg .4% Condns DB=>MWB",
                                 "JUL Clg .4% Condns DB=>MWB")
        directory = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = directory / "with-monthly.ddy"
        path.write_text(text + "\n" + monthly, encoding="latin-1")
        return path

    @needs_sdk
    def test_the_filter_excludes_MONTHLY_cooling_days(self):
        """Fable's L2, exercised through `attach_weather` itself.

        Without the `\\bAnn\\b` anchor the patterns matched on the condition
        substring alone and never constrained the Ann/JUN/JUL token, so a DDY
        spelling its monthly days the same way after the period marker kept all
        of them — the tower-UA hazard the code's own comment names (a January
        cooling day's ~2 C wet-bulb). Measured across every `.ddy` on disk: 16
        CZ2010 files kept 8 of 9 days, SIX of them monthly.

        An earlier version of this test grepped the source for the anchor and
        then matched its OWN copy of the pattern list. A mutation that dropped
        the anchor from one entry SURVIVED it, because the string still
        appeared elsewhere in the file and the real filter was never run. So
        this attaches a constructed DDY and inspects the ATTACHED days.
        """
        from btap.audit import AuditLog

        ddy = self._ddy_with_a_monthly_cooling_day()
        audit = AuditLog()
        model = load_fixture()
        runner.attach_weather(model, epw=str(EPW), ddy=str(ddy), audit=audit)
        attached = sorted(dd.nameString() for dd in model.getDesignDays())

        monthly = [n for n in attached if "JUL" in n]
        self.assertEqual(
            [], monthly,
            f"a monthly cooling day was attached: {monthly} — the filter must "
            f"keep annual extremes only (attached: {attached})")
        self.assertTrue(any("Ann Clg .4% Condns DB=>MWB" in n
                            for n in attached),
                        "precondition: the ANNUAL 0.4% day must still be kept, "
                        "or this test would pass by filtering everything")

        entry = next(e for e in audit.entries if e.get("ruling") == "D-25"
                     and e["level"] == "decision")
        self.assertNotIn("JUL", entry["value"],
                         "the audit value must not list a monthly day either")

    @needs_sdk
    def test_a_PARTIAL_match_the_OTHER_WAY_names_heating(self):
        """Fable's M1: the ternary's other arm was never exercised.

        All three partial tests used `_ddy_with_only("heating")` — the
        MISSING-COOLING sub-state — so `missing = "cooling" if not kept_cooling
        else "heating"` was pinned on one arm, and hardcoding it to `"cooling"`
        SURVIVED mutation. If that arm broke, a DDY with a cooling extreme and
        no heating one would announce "NO COOLING design day matched" and warn
        that COOLING equipment autosizes without a design condition, while the
        actual gap is heating: a false AHJ-facing claim naming the WRONG KIND.

        No baseline can ever catch this — the partial branch is unreachable in
        the corpus by construction — so these assertions are the only thing
        holding the text true.
        """
        from btap.audit import AuditLog

        ddy = self._ddy_with_only("cooling")
        audit = AuditLog()
        model = load_fixture()
        runner.attach_weather(model, epw=str(EPW), ddy=str(ddy), audit=audit)

        entry = next(e for e in audit.entries if e.get("ruling") == "D-25"
                     and e["level"] == "decision")
        inputs = entry["inputs"]
        self.assertFalse(inputs["kept_all_as_fallback"],
                         "precondition: not the total-miss fallback")
        self.assertEqual(0, inputs["design_days_kept_heating"],
                         "precondition: no heating extreme may have matched")
        self.assertGreater(inputs["design_days_kept_cooling"], 0,
                           "precondition: a cooling extreme must have matched")

        self.assertIn("NO HEATING", entry["action"],
                      "the missing kind is HEATING here, not cooling")
        self.assertNotIn("NO COOLING", entry["action"])

        warnings = [e for e in audit.entries if e["level"] == "warning"
                    and e.get("ruling") == "D-25"]
        self.assertEqual(1, len(warnings))
        self.assertIn("heating", warnings[0]["action"],
                      "the warning must name the kind that is actually absent")
        self.assertNotIn("cooling equipment", warnings[0]["action"])

    @needs_sdk
    def test_the_FALLBACK_per_kind_counts_describe_what_was_attached(self):
        """Fable's M2: nothing asserted the per-kind counts on the fallback.

        The counts are computed AFTER the fallback substitutes the whole file,
        so on a fallback they must describe the whole file. Moving them back
        above the substitution no longer crashes — the `partial` guard makes
        `missing` unreachable there — but it WOULD report
        `heating=0, cooling=0` while 78 days are attached: a false evidence
        pair in the one state whose entire point is that everything was kept.

        This is also what makes the matrix row claiming to catch that mutation
        meaningful again; without this assertion the row reported a difference
        it could no longer detect.
        """
        from btap.audit import AuditLog

        ddy = self._ddy_with_no_extremes()
        audit = AuditLog()
        model = load_fixture()
        runner.attach_weather(model, epw=str(EPW), ddy=str(ddy), audit=audit)
        entry = next(e for e in audit.entries if e.get("ruling") == "D-25"
                     and e["level"] == "decision")
        inputs = entry["inputs"]
        self.assertTrue(inputs["kept_all_as_fallback"],
                        "precondition: this DDY must trigger the fallback")

        heating = inputs["design_days_kept_heating"]
        cooling = inputs["design_days_kept_cooling"]
        self.assertGreater(heating + cooling, 0,
                           "the fallback attached the WHOLE file, so the "
                           "per-kind counts cannot both be zero — reporting "
                           "0/0 beside a kept count of 78 is a false evidence "
                           "pair")
        # They do NOT sum to the total, and an earlier version of this test
        # wrongly asserted that they do. The shipped Toronto DDY's 78 days are
        # 4 `Htg`, 12 `Clg`, 2 `Hum_n` (humidity) and 60 MONTH-NAMED days
        # (`January .4% Condns DB=>MCWB`), so most attached days are neither
        # heating nor cooling by name. The counts are a floor on each kind,
        # not a partition of the file.
        self.assertLessEqual(
            heating + cooling, inputs["design_days_kept"],
            "a per-kind count cannot exceed what was attached")
        self.assertGreater(heating, 0, "the file carries Htg design days")
        self.assertGreater(cooling, 0, "the file carries Clg design days")
