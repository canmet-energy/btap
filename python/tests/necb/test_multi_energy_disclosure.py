"""A dual-fuel proposed heating plant must not collapse SILENTLY.

8.4.4.9.(5) and 8.4.4.10.(4) require the reference building's heating and
cooling capacities to match the ratio of the proposed building's capacity
allocation per energy type. We do not do that, and the reason is a Code
conflict rather than an omission: 8.4.4.9.(6) configures a hydronic reference
plant as ONE single-stage boiler at or below 176 kW, TWO BOILERS OF EQUAL
CAPACITY (or a two-staged boiler) from 176 to 352 kW, and "a boiler"
modulating to 25% above that. Every band is singular or equal-split, so a
proposed 60/40 allocation cannot be represented without breaking (6) — which
we currently satisfy.

WHAT THE MEASUREMENT SHOWED, and it overturned two of my own estimates.
Each reference boiler autosizes to the FULL plant load (64,396 W each), not
half of it, and `SequentialLoad` means only the lead one fires. So:

  * the (6)(b) boiler-count departure is ENERGY-NEUTRAL — an annual run of
    the two-boiler reference and of a single-boiler reference both give
    158,219.4 kWh, identical to 0.1 kWh;
  * my earlier 10-32% "staging advantage" was wrong, because it assumed the
    pair SHARES load;
  * my earlier 5.3% "fuel-mix" figure was wrong too, because the electric
    boiler delivers no energy at all;
  * (5)(a)'s installed-capacity ratio therefore lands 50/50 and holds
    COINCIDENTALLY for an equal proposed split, failing for any other;
  * (5)(b)'s operating priority is the clause genuinely not addressed.

So the model is left alone and the CLAIMS are corrected. What these tests
pin is the DISCLOSURE: previously a dual-fuel plant became a gas reference with nothing
in the audit saying a Code requirement had been set aside, and a reader could
not tell. Coverage for (5) stays `partial`; nothing here claims compliance.

Sol's `110` ruling governs the shape: energy types stay distinct (no "fossil"
class), ratios come from CAPACITY rather than annual energy or device count,
and an unknown capacity is a visible unresolved case rather than a guessed
fraction.
"""

from __future__ import annotations

import unittest

from tests.support import needs_sdk


class _Fixture(unittest.TestCase):
    def _audit(self):
        from btap.audit import AuditLog

        return AuditLog()

    def _group(self, fuels, zones=("Zone 1",)):
        return {"zones": list(zones), "heating_energy_types": list(fuels)}

    def _facts(self, plants=()):
        # a FRESH dict each call: the per-plant dedupe state lives in `facts`,
        # so sharing one would hide the second warning rather than the
        # duplicate
        return {"plants": list(plants), "purchased_energy": {}}

    def _selection(self):
        return {"special_rules": {"purchased_heating": {
            "article": "8.4.4.6.(1)", "part_load_curve_class": "modulating"}}}

    def _call(self, group, facts):
        from btap.codes.necb.hvac import reference

        audit = self._audit()
        result = reference._reference_energy_type(
            group, self._selection(), facts, audit)
        warnings = [e for e in audit.entries
                    if e["level"] == "warning"
                    and "UNRESOLVED" in str(e.get("action"))]
        return result, warnings, audit


class TestTheCollapseIsDisclosed(_Fixture):
    def test_a_single_fuel_group_warns_about_nothing(self):
        """The control. Without it every assertion below could be vacuous."""
        (energy, _), warnings, _ = self._call(
            self._group(["NaturalGas"]), self._facts())
        self.assertEqual("gas", energy)
        self.assertEqual([], warnings)

    def test_an_UNSIZED_dual_fuel_plant_warns_that_the_ratio_is_unknown(self):
        """The reachable case: every multi-fuel plant in the corpus is
        autosized, and `--simulate none` never sizes at all."""
        plant = {"type": "hot_water", "fuels": ["NaturalGas", "Electricity"],
                 "fuel_capacities_w": {"NaturalGas": None,
                                       "Electricity": None}}
        (energy, _), warnings, _ = self._call(
            self._group(["NaturalGas", "Electricity"]), self._facts([plant]))
        self.assertEqual(1, len(warnings), "the collapse must be disclosed")
        entry = warnings[0]
        self.assertEqual("8.4.4.9.(5); 8.4.4.9.(6)(b)", entry["article"],
                         "both articles — the point is that they are not "
                         "reconciled with each other (Sol, `111`)")
        self.assertIn("NOT", entry["action"],
                      "it must not read as if either were satisfied")
        self.assertIn("energy-neutral", entry["action"],
                      "the (6)(b) departure was MEASURED as energy-neutral — "
                      "annual results identical at 158,219.4 kWh — and the "
                      "entry must say so rather than imply a penalty")
        self.assertIn("(5)(b)", entry["action"],
                      "clause (b) is the one genuinely not addressed")
        self.assertFalse(entry["inputs"]["reconciled"])
        self.assertIn("SequentialLoad", entry["inputs"]["operating_allocation"])
        self.assertIn("energy-neutral", entry["inputs"]["six_b_departure"])
        self.assertEqual("unavailable without sizing",
                         entry["inputs"]["proposed_capacity_shares"])
        self.assertEqual(["Electricity", "NaturalGas"],
                         entry["inputs"]["proposed_energy_types"])
        self.assertEqual("gas", energy, "behaviour is unchanged — only the "
                                        "disclosure is new")

    def test_a_SIZED_dual_fuel_plant_reports_the_shares(self):
        plant = {"type": "hot_water", "fuels": ["NaturalGas", "Electricity"],
                 "fuel_capacities_w": {"NaturalGas": 60_000.0,
                                       "Electricity": 40_000.0}}
        (energy, _), warnings, _ = self._call(
            self._group(["NaturalGas", "Electricity"]), self._facts([plant]))
        self.assertEqual(1, len(warnings))
        inputs = warnings[0]["inputs"]
        self.assertEqual({"Electricity": 0.4, "NaturalGas": 0.6},
                         inputs["proposed_capacity_shares"])
        self.assertEqual("gas", energy)

    def test_the_tiebreak_follows_CAPACITY_not_the_cascade_order(self):
        """The old cascade put gas first regardless. With a known allocation
        the LARGER proposed capacity decides, which is more defensible under
        8.4.4.9.(4) than a positional accident.

        Pre-emptive: unreachable with the current corpus, since no sample
        plant carries hard capacities.
        """
        plant = {"type": "hot_water", "fuels": ["NaturalGas", "Electricity"],
                 "fuel_capacities_w": {"NaturalGas": 30_000.0,
                                       "Electricity": 70_000.0}}
        (energy, _), warnings, _ = self._call(
            self._group(["NaturalGas", "Electricity"]), self._facts([plant]))
        self.assertEqual("electric", energy,
                         "electricity holds the larger capacity, so it is the "
                         "reference energy type")
        self.assertEqual({"Electricity": 0.7, "NaturalGas": 0.3},
                         warnings[0]["inputs"]["proposed_capacity_shares"])

    def test_oil_and_propane_stay_DISTINCT_from_natural_gas(self):
        """Sol's `110`: Division A 1.4.1.2 defines no 'fossil' equivalence
        class for this clause, so three fossil sources are three types."""
        plant = {"type": "hot_water",
                 "fuels": ["NaturalGas", "FuelOilNo2"],
                 "fuel_capacities_w": {"NaturalGas": 10_000.0,
                                       "FuelOilNo2": 90_000.0}}
        (_, _), warnings, _ = self._call(
            self._group(["NaturalGas", "FuelOilNo2"]), self._facts([plant]))
        self.assertEqual(1, len(warnings),
                         "two fossil sources are still MORE THAN ONE energy "
                         "type and must be disclosed")
        self.assertEqual(["FuelOilNo2", "NaturalGas"],
                         warnings[0]["inputs"]["proposed_energy_types"])

    def test_PURCHASED_energy_is_not_counted_as_a_second_type(self):
        """8.4.4.6. governs purchased energy with its own capacity-share rule
        against the building total, so it must not be forced into this
        per-system denominator (Sol's `110`)."""
        (_, _), warnings, _ = self._call(
            self._group(["Purchased"]), self._facts())
        self.assertEqual([], warnings)

    def test_a_PARTIALLY_sized_plant_reports_unknown(self):
        """One fuel sized and one autosized is NOT a known allocation.

        The all-autosized case alone did not pin this: with every capacity
        None the shares are empty and the zero-total check catches it anyway,
        so the `len(known) != len(watts)` guard survived mutation. A partial
        allocation is the input that distinguishes them.
        """
        # THREE fuels with TWO known. A two-fuel partial cannot distinguish
        # the `len(known) != len(watts)` guard from `len(known) < 2`, because
        # one known capacity fails both — the matrix survived removing the
        # former until this case existed.
        plant = {"type": "hot_water",
                 "fuels": ["NaturalGas", "Electricity", "FuelOilNo2"],
                 "fuel_capacities_w": {"NaturalGas": 60_000.0,
                                       "Electricity": 40_000.0,
                                       "FuelOilNo2": None}}
        (_, _), warnings, _ = self._call(
            self._group(["NaturalGas", "Electricity", "FuelOilNo2"]),
            self._facts([plant]))
        self.assertEqual(1, len(warnings))
        self.assertEqual("unavailable without sizing",
                         warnings[0]["inputs"]["proposed_capacity_shares"],
                         "a half-known allocation must not be reported as a "
                         "ratio — the missing half is not zero")

    def test_PURCHASED_returns_before_the_multi_energy_branch(self):
        """Purchased energy never reaches the disclosure, by construction.

        The purchased branch RETURNS first, which is why an explicit
        `!= 'Purchased'` filter below it was dead code — the matrix survived
        its removal. 8.4.4.6. owns purchased energy with its own capacity-share
        rule against the building total, so it must not be forced into this
        per-system count (Sol's `110`). What this pins is the ORDER."""
        (_, _), warnings, _ = self._call(
            self._group(["Purchased", "NaturalGas"]), self._facts())
        self.assertEqual(
            [], warnings,
            "purchased + one ordinary fuel is ONE ordinary energy type here; "
            "the purchased branch above already returned for it")

    def test_an_ambiguous_plant_match_reports_unknown_rather_than_guessing(self):
        """Two candidate plants means the allocation is not established."""
        plants = [{"type": "hot_water", "fuels": ["NaturalGas", "Electricity"],
                   "fuel_capacities_w": {"NaturalGas": 1.0,
                                         "Electricity": 1.0}},
                  {"type": "hot_water", "fuels": ["NaturalGas"],
                   "fuel_capacities_w": {"NaturalGas": 5.0}}]
        (_, _), warnings, _ = self._call(
            self._group(["NaturalGas", "Electricity"]), self._facts(plants))
        self.assertEqual(1, len(warnings))
        self.assertEqual("unavailable without sizing",
                         warnings[0]["inputs"]["proposed_capacity_shares"])


class TestTheWarningIsDeduplicated(_Fixture):
    """ONE warning per serving plant, not one per block it serves.

    The first version emitted five identical warnings on
    11-staged-boilers-gas-lead — one per thermal-block group. Five copies of
    one finding is noise, and Sol asked for the plant to be named and the
    warning deduplicated across the blocks it serves (`111`).
    """

    def test_one_plant_serving_five_blocks_warns_once(self):
        from btap.audit import AuditLog
        from btap.codes.necb.hvac import reference

        plant = {"name": "Hot Water Loop", "type": "hot_water",
                 "fuels": ["NaturalGas", "Electricity"],
                 "fuel_capacities_w": {"NaturalGas": None,
                                       "Electricity": None}}
        facts = self._facts([plant])
        audit = AuditLog()
        for block in range(5):
            reference._reference_energy_type(
                self._group(["NaturalGas", "Electricity"],
                            zones=(f"Zone {block}",)),
                self._selection(), facts, audit)
        warnings = [e for e in audit.entries
                    if e["level"] == "warning"
                    and "UNRESOLVED" in str(e.get("action"))]
        self.assertEqual(1, len(warnings),
                         f"one plant, one warning — got {len(warnings)}")
        self.assertEqual("Hot Water Loop", warnings[0]["target"],
                         "the warning must name the plant, not a zone list")

    def test_TWO_plants_warn_twice(self):
        """The control: dedupe must not swallow a genuinely second finding."""
        from btap.audit import AuditLog
        from btap.codes.necb.hvac import reference

        facts = self._facts([
            {"name": "Hot Water Loop A", "type": "hot_water",
             "fuels": ["NaturalGas", "Electricity"],
             "fuel_capacities_w": {"NaturalGas": None, "Electricity": None}},
        ])
        audit = AuditLog()
        reference._reference_energy_type(
            self._group(["NaturalGas", "Electricity"]), self._selection(),
            facts, audit)
        facts["plants"] = [
            {"name": "Hot Water Loop B", "type": "hot_water",
             "fuels": ["FuelOilNo2", "Electricity"],
             "fuel_capacities_w": {"FuelOilNo2": None, "Electricity": None}}]
        reference._reference_energy_type(
            self._group(["FuelOilNo2", "Electricity"]), self._selection(),
            facts, audit)
        warnings = [e for e in audit.entries
                    if e["level"] == "warning"
                    and "UNRESOLVED" in str(e.get("action"))]
        self.assertEqual(2, len(warnings))
        self.assertEqual({"Hot Water Loop A", "Hot Water Loop B"},
                         {w["target"] for w in warnings})


class TestTheAllocationIsRecordedByClassify(unittest.TestCase):
    @needs_sdk
    def test_a_dual_fuel_plant_carries_both_fuels_and_both_capacities(self):
        """`classify` is where the allocation comes from, so the survey must
        carry it — not just the fuel names it carried before."""
        import pathlib

        import openstudio

        from btap.modeling.hvac import classify

        corpus = pathlib.Path(
            "/tmp/claude-1000/-workspaces-openstudio-necb-gems/"
            "a100f076-cc34-4c32-b8b8-6d3f4c82e03f/scratchpad/lvr-corpus")
        osm = corpus / "11-staged-boilers-gas-lead.osm"
        if not osm.is_file():
            self.skipTest("sample corpus not generated in this environment")
        model = openstudio.osversion.VersionTranslator().loadModel(
            openstudio.toPath(str(osm))).get()
        facts = classify.characterize(model)
        hot = [p for p in facts["plants"] if p["type"] == "hot_water"]
        self.assertEqual(1, len(hot))
        self.assertEqual({"NaturalGas", "Electricity"}, set(hot[0]["fuels"]))
        self.assertIn("fuel_capacities_w", hot[0])
        self.assertEqual({"NaturalGas", "Electricity"},
                         set(hot[0]["fuel_capacities_w"]))
        self.assertTrue(
            all(v is None for v in hot[0]["fuel_capacities_w"].values()),
            "both boilers are autosized, so the allocation is UNKNOWN — the "
            "survey must say None rather than 0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
