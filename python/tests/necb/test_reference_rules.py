"""Port of btap-necb/test/test_reference_rules.rb: the reference-building
rules, each proved by a sample where the reference VISIBLY diverges from the
proposed.

These assert on the AUDIT DECISION, not on the energy numbers: the point is
which rule fired and what it decided, and an energy assertion would be a
brittle proxy for that. Everything here runs simulate='none' — no EnergyPlus
— except the two marked as needing an annual run, because the rules they
cover cannot fire without one.

The samples are the PYTHON-generated corpus (D-80 R2: Python-owned paths —
no packaging/windows read): python3 scripts/generate_samples.py
tests/generated/samples, or point BTAP_SAMPLES_DIR at an existing corpus
(.osm files are language-neutral, so a Ruby-generated corpus also works —
that cross-generator equivalence is exactly what the 2x2 matrix proves)."""

import os
import re
import tempfile
import unittest
from pathlib import Path

from btap.necb import performance_compliance
from tests.necb.support import (
    DDY,
    EPW,
    load_raw_fixture,
    needs_engine,
    needs_sdk,
)

SAMPLES = Path(os.environ.get(
    "BTAP_SAMPLES_DIR",
    Path(__file__).resolve().parents[1] / "generated" / "samples"))


def sample(test, slug):
    path = SAMPLES / f"{slug}.osm"
    if not path.exists():
        test.skipTest("sample not generated: run "
                      "python3 scripts/generate_samples.py tests/generated/samples "
                      "(or set BTAP_SAMPLES_DIR)")
    return str(path)


def compliance(test, slug, dir, **kwargs):
    return performance_compliance(sample(test, slug), vintage="2020",
                                  hdd=3890, simulate="none", run_dir=dir,
                                  **kwargs)


def article(result, prefix):
    return [e for e in result.audit.entries
            if str(e.get("article") or "").startswith(prefix)]


def said(entries, pattern):
    # The AuditLog schema names the text 'action', NOT 'message' — reading a
    # wrong key silently returns None and an assertion on it fails with a
    # misleading "the rule did not fire" when the rule fired perfectly well.
    return any(re.search(pattern, str(e.get("action") or ""))
               for e in entries)


def district_count(model):
    return sum(1 for o in model.modelObjects()
               if re.search("DistrictHeating", o.iddObjectType().valueName()))


@needs_sdk
class TestReferenceRules(unittest.TestCase):
    def test_purchased_heating_becomes_a_gas_boiler_in_the_reference(self):
        # 8.4.4.6.(1)(a): purchased heating "shall be represented by" a
        # gas-fired boiler. The proposed has a district object and NO boiler;
        # the reference must have the reverse. The sample is deliberately a
        # SINGLE-group system (the multi-group layout is pinned separately
        # below).
        with tempfile.TemporaryDirectory() as dir:
            r = compliance(self, "13-district-heating", dir)

            self.assertEqual(1, district_count(r.proposed_model),
                             "the proposed should carry district heating")
            self.assertEqual(0, len(r.proposed_model.getBoilerHotWaters()),
                             "the proposed should have no boiler")

            self.assertEqual(0, district_count(r.reference_model),
                             "the reference must NOT keep district heating")
            boilers = list(r.reference_model.getBoilerHotWaters())
            self.assertTrue(boilers, "the reference must grow a boiler")
            self.assertEqual(["NaturalGas"],
                             sorted({b.fuelType() for b in boilers}),
                             "8.4.4.6.(1)(a) names a GAS-fired boiler")

            self.assertTrue(article(r, "8.4.4.6"),
                            "the purchased-energy decision must be audited")

    def test_storey_count_flips_the_reference_system(self):
        # Table 8.4.4.7.-A splits General Area at 2 vs 3 above-ground
        # storeys. Two otherwise-identical buildings must select different
        # reference systems — one sample cannot show a flip, which is why
        # these are a pair.
        with tempfile.TemporaryDirectory() as dir:
            low = compliance(self, "14-general-2storey", f"{dir}/low")
            high = compliance(self, "15-general-3storey", f"{dir}/high")

            low_sel = " ".join(str(e.get("value") or "")
                               for e in article(low, "8.4.4.7"))
            high_sel = " ".join(str(e.get("value") or "")
                                for e in article(high, "8.4.4.7"))

            self.assertRegex(low_sel, r"System 3",
                             f"2 storeys should select System 3: {low_sel}")
            self.assertRegex(high_sel, r"System 6",
                             f"3 storeys should select System 6: {high_sel}")
            self.assertNotEqual(low_sel, high_sel)

    def test_the_storey_samples_declare_their_own_storey_count(self):
        # The storey count must come from the MODEL, so the samples stand
        # alone without the CLI's --storeys override.
        from btap._sdk import load_model

        for slug, expected in (("14-general-2storey", 2),
                               ("15-general-3storey", 3)):
            model = load_model(sample(self, slug))
            declared = (model.getBuilding()
                        .standardsNumberOfAboveGroundStories())
            self.assertTrue(declared.is_initialized(),
                            f"{slug} must declare its storey count")
            self.assertEqual(expected, declared.get())

    def test_mixed_fuel_plant_passes_through_unchanged_the_declared_gap(self):
        # 8.4.4.9.(5)/8.4.4.10.(4) multi-energy capacity ratios are a
        # DECLARED gap: the reference keeps a mixed-fuel plant unchanged
        # rather than apportioning it. Pinned so that implementing the clause
        # has to come here and say so.
        with tempfile.TemporaryDirectory() as dir:
            r = compliance(self, "11-staged-boilers-gas-lead", dir)

            def fuels(m):
                return sorted((b.nameString(), b.fuelType())
                              for b in m.getBoilerHotWaters())

            self.assertEqual(fuels(r.proposed_model), fuels(r.reference_model),
                             "while 8.4.4.9.(5) is unimplemented the "
                             "mixed-fuel plant should pass through as-is")
            reference_fuels = [f for _, f in fuels(r.reference_model)]
            self.assertIn("Electricity", reference_fuels)
            self.assertIn("NaturalGas", reference_fuels)

    def test_purchased_heating_is_replaced_whatever_the_group_layout(self):
        # The layout that hid the bug: `Baseboard district hot water` makes
        # FIVE single-zone groups, and the reference builder tears down and
        # rebuilds one group at a time; Teardown only drops a plant loop
        # whose demand side is empty, so the district loop always still
        # carried the other groups' coils and survived. It was then
        # re-adopted by a bare NAME match on 'Hot Water Loop' — so the
        # reference kept purchased heating while its energy type said gas.
        # Both layouts are asserted so the fix cannot regress on the shape
        # that is easy to miss.
        import btap.modeling as modeling
        from btap._compat import sorted_by_name
        from btap.audit import AuditLog
        from btap.necb import hvac, loads

        for system in ("Baseboard district hot water",
                       "DOAS with fan coil air-cooled chiller with district "
                       "hot water"):
            model = load_raw_fixture()
            loads.apply_loads(model, vintage="2020", audit=AuditLog())
            modeling.build_system(model, system,
                                  sorted_by_name(model.getThermalZones()))

            self.assertEqual(1, district_count(model),
                             f"{system}: the proposed should carry district "
                             "heating")

            reference = hvac.reference_hvac(
                model, vintage="2020", building={"storeys": 1},
                audit=AuditLog()).model

            self.assertEqual(0, district_count(reference),
                             f"{system}: 8.4.4.6.(1)(a) — the reference must "
                             "NOT keep purchased heating")
            self.assertEqual(
                ["NaturalGas"],
                sorted({b.fuelType()
                        for b in reference.getBoilerHotWaters()}),
                f"{system}: the reference must be heated by a gas boiler")


@needs_engine
class TestReferenceRulesAnnual(unittest.TestCase):
    """These need a real annual run; the rules cannot fire without one."""

    def test_auxiliary_fuel_election_runs_on_an_annual_run(self):
        # 8.4.4.13.(2)(g)/D-52. Proof that the ELECTION ran rather than the
        # structural 8.4.4.9.(4) proxy is the (g)(i)/(g)(ii) suffix plus the
        # ELECTED wording — NOT the elected fuel, which may legitimately
        # match what the proxy would have said.
        with tempfile.TemporaryDirectory() as dir:
            r = performance_compliance(
                sample(self, "16-ashp-electric-supp-hw-baseboard"),
                vintage="2020", hdd=3890,
                weather={"epw": str(EPW), "ddy": str(DDY)},
                simulate="annual",
                run_period={"begin_month": 1, "begin_day": 1, "end_month": 1,
                            "end_day": 7},
                building={"storeys": 1}, run_dir=dir)

            elected = article(r, "8.4.4.13.(2)(g)(")
            self.assertTrue(elected,
                            "the election should have run — only the bare "
                            "(g) proxy entry was emitted")
            self.assertTrue(
                said(elected, r"ELECTED from the proposed annual run"),
                "expected the ELECTED wording, which distinguishes the "
                "election from the proxy")

    def test_sentence_four_is_vacuous_without_mechanical_cooling(self):
        # 8.4.1.2.(4) is formally vacuous when the proposed has no mechanical
        # cooling — otherwise passive-overheating hours would be read as a
        # cooling-capacity shortfall. mechanical_cooling is only populated on
        # an annual run.
        with tempfile.TemporaryDirectory() as dir:
            r = performance_compliance(
                sample(self, "01-baseboard-gas"), vintage="2020", hdd=3890,
                weather={"epw": str(EPW), "ddy": str(DDY)},
                simulate="annual",
                run_period={"begin_month": 1, "begin_day": 1, "end_month": 1,
                            "end_day": 7},
                building={"storeys": 1}, run_dir=dir)

            self.assertEqual(False,
                             r.report["proposed"]["mechanical_cooling"])
            vacuous = [e for e in article(r, "8.4.1.2.(4)")
                       if re.search("vacuous", str(e.get("action") or ""))]
            self.assertTrue(vacuous,
                            "sentence (4) should be declared vacuous for a "
                            "heating-only proposed")


if __name__ == "__main__":
    unittest.main()
