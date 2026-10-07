"""The 8.4.x.9.(5) multi-energy heating disclosure.

The tool ELECTS one reference heating energy type and never computes the
proposed capacity-ratio allocation that 8.4.4.9.(5)/8.4.5.9.(5) requires.
This module pins the DISCLOSURE of that gap, not a fix for it: coverage for
(5) stays `not_implemented` and (6) is `partial`.

Five review rounds shaped these tests, and every one of them blocked on the
same thing — the audit entry asserting a mechanism the model had not
established:

  * a gas-only plant described as holding one boiler per energy type;
  * "the ratio is NOT met", when a reference may carry capacity for a
    non-elected type through an air-loop coil or heat pump, so the honest
    statement is NOT VERIFIED in either direction;
  * a plant covering only PART of a serving group having its fuels reported
    as the group's whole allocation, dropping the others from the
    denominator;
  * `(6)(b)` cited without any capacity to establish which of (6)(b)/(c)/(d)
    applies;
  * "the reference retains one boiler per energy type", when the reference
    ADOPTS the proposed plant with its own device count and the post-sizing
    staging pass then sets live capacity by primary/secondary ROLE, blind to
    fuel — the committed baselines show the reference secondary at
    `capacity_kw: 0.0` against a real design capacity.

So nothing here asserts an energy result or a (6) subclause as a general
property. The one measurement that exists is provenance for a single sample,
edition and model state, and it is gated so it cannot travel to another
edition.
"""

from __future__ import annotations

import unittest

from btap.audit import AuditLog
from btap.codes.necb.hvac import reference
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
        return {"special_rules": {
            "purchased_heating": {"article": "8.4.4.6.(1)",
                                  "part_load_curve_class": "modulating"},
            "heat_pump": {"article": "8.4.4.13.(1)-(2) + Table 8.4.4.13"}}}

    def _call(self, group, facts):
        from btap.codes.necb.hvac import reference

        audit = self._audit()
        selection = self._selection()
        result = reference._reference_energy_type(group, selection, facts, audit)
        # `_finalize` calls these two in sequence, and the disclosure now runs
        # on EVERY election path rather than only this one (Sol, `114`.2).
        reference._disclose_multi_energy(group, selection, facts, audit)
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
        self.assertEqual("8.4.4.9.(5); 8.4.4.9.(6)", entry["article"],
                         "both sentences — but (6) WITHOUT a subclause, "
                         "because which of (6)(b)/(c)/(d) applies depends on "
                         "a reference plant capacity that does not exist at "
                         "selection time (Sol, `114`.4)")
        self.assertIn("NEITHER", entry["action"],
                      "it must not read as if either were satisfied")
        self.assertIn("ONE BOILER PLANT", entry["action"],
                      "this plant really does carry both fuels")
        self.assertNotIn(
            "energy-neutral", entry["action"],
            "the measurement belongs in `inputs` as provenance for samples "
            "11/12, NOT asserted in prose about an arbitrary model (Sol, "
            "`113`)")
        self.assertIn("NOT a property of this model",
                      entry["inputs"]["fixture_measurement"])
        self.assertFalse(entry["inputs"]["reconciled"])
        self.assertEqual(["Electricity", "NaturalGas"],
                         entry["inputs"]["plant_energy_types"])
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

    def test_a_known_allocation_does_NOT_change_the_elected_energy_type(self):
        """The capacity-dominant election is NOT part of this change.

        It flips the reference's whole system type for a sized
        electric-dominant plant — sample 12's reference becomes electric
        baseboards with no boiler plant — and no frozen scenario exercises
        it. Sol's `113` asked for it to be separated from disclosure-only
        work rather than verified in passing, so it lives on its own branch
        with its own fixture and freeze. Here the cascade still decides.
        """
        plant = {"type": "hot_water", "fuels": ["NaturalGas", "Electricity"],
                 "fuel_capacities_w": {"NaturalGas": 30_000.0,
                                       "Electricity": 70_000.0}}
        (energy, _), warnings, _ = self._call(
            self._group(["NaturalGas", "Electricity"]), self._facts([plant]))
        self.assertEqual("gas", energy,
                         "disclosure does not change the election — the "
                         "cascade's gas preference still stands")
        self.assertEqual({"Electricity": 0.7, "NaturalGas": 0.3},
                         warnings[0]["inputs"]["proposed_capacity_shares"],
                         "the shares are still REPORTED, which is the whole "
                         "point of the disclosure")

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
        # Two candidates means no identified serving plant, so nothing may be
        # claimed about boilers per energy type — the generic entry, which
        # carries no shares key at all rather than a guessed one.
        self.assertNotIn("ONE BOILER PLANT", warnings[0]["action"])
        self.assertNotIn("proposed_capacity_shares", warnings[0]["inputs"])
        self.assertEqual("8.4.4.9.(5)", warnings[0]["article"])


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
            reference._disclose_multi_energy(
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
        reference._disclose_multi_energy(
            self._group(["NaturalGas", "Electricity"]), self._selection(),
            facts, audit)
        facts["plants"] = [
            {"name": "Hot Water Loop B", "type": "hot_water",
             "fuels": ["FuelOilNo2", "Electricity"],
             "fuel_capacities_w": {"FuelOilNo2": None, "Electricity": None}}]
        reference._disclose_multi_energy(
            self._group(["FuelOilNo2", "Electricity"]), self._selection(),
            facts, audit)
        warnings = [e for e in audit.entries
                    if e["level"] == "warning"
                    and "UNRESOLVED" in str(e.get("action"))]
        self.assertEqual(2, len(warnings))
        self.assertEqual({"Hot Water Loop A", "Hot Water Loop B"},
                         {w["target"] for w in warnings})


#: Sample 16's real shape, from `classify.characterize` on the generated
#: fixture: ONE zone group of five zones using Electricity + NaturalGas, an
#: air-source heat pump, and a GAS-ONLY hot-water plant. Written as a literal
#: so the case runs without the generated corpus.
_ASHP_MIXED_FACTS = {
    "zone_groups": [{
        "zones": [f"Thermal Zone {i}" for i in range(1, 6)],
        "air_loop": "PSZ RTU ASHP with Electric and ASHP with Electric "
                    "Supp. Heat Coils and Hot Water Baseboard | Thermal Zone 1",
        "family": "psz",
        "catalog_name": "PSZ RTU ASHP with Electric and ASHP with Electric "
                        "Supp. Heat Coils and Hot Water Baseboard",
        "family_guess": "central_doas_or_cv",
        "heated": True,
        "cooled": True,
        "heating_energy_types": ["Electricity", "NaturalGas"],
        "cooling_energy_types": ["Electricity"],
        "heat_pump": True,
        "heat_pump_sources": ["air"],
        "heat_pump_source_loops": [],
        "terminal_type": "cv",
        "zonal_units": ["baseboard"],
        "loop_dx_cooling": True,
        "design_cooling_kw": None,
        "dcv": False,
        "system_outdoor_air_method": "ZoneSum",
        "evidence": [],
    }],
    "plants": [{"name": "Hot Water Loop", "type": "hot_water",
                "fuels": ["NaturalGas"],
                "fuel_capacities_w": {"NaturalGas": None},
                "purchased": False, "heat_pump": False}],
    "purchased_energy": {},
    "built_by_gem": False,
}


class TestTheDisclosureSurvivesTheHeatPumpPath(unittest.TestCase):
    """Sol's `114`.2: an ANNUAL heat-pump election bypassed the diagnostic.

    `_finalize` calls `_reference_energy_type` only when
    `heat_pump_aux_energy_type` returns None, so a mixed ASHP group with
    annual data got the 8.4.4.13.(2)(g) election and NO (5) disclosure.

    MY FIRST VERSION OF THIS TEST DID NOT REACH THAT BRANCH (Sol, `115`). It
    passed `{"groups": {zone: {"hp_j":, "terminal_j":}}}`, but
    `heat_pump_aux_energy_type` reads `annual["loops"][air_loop]` with
    `hp_j` and `aux: [{"fuel":, "j":}]`, plus `annual["zones"][zone]`. With
    the wrong shape the election fell through to the structural proxy and
    emitted "no terminal or auxiliary heating energy" — so the test would
    have PASSED with the disclosure moved back inside the election branch,
    which is exactly the bug it claims to pin.

    The discriminator is the (2)(g) DECISION count, not just the warning
    count: the annual case must show the election firing AND the disclosure
    surviving it.
    """

    def _run(self, proposed_annual):
        import copy

        facts = copy.deepcopy(_ASHP_MIXED_FACTS)
        audit = AuditLog()
        out = reference.select_reference_systems(
            facts=facts, building={"storeys": 1}, code="necb2020",
            audit=audit, proposed_annual=proposed_annual)
        elections = [e for e in audit.entries
                     if "(2)(g)" in str(e.get("article", ""))
                     and e["level"] == "decision"]
        warnings = [e for e in audit.entries
                    if "UNRESOLVED" in str(e.get("action"))
                    and "ENERGY TYPE" in str(e.get("action"))]
        return sorted({a.energy_type for a in out}), elections, warnings

    def test_the_ANNUAL_heat_pump_election_fires_AND_still_discloses(self):
        loop = _ASHP_MIXED_FACTS["zone_groups"][0]["air_loop"]
        annual = {"loops": {loop: {"hp_j": 80e9,
                                   "aux": [{"fuel": "Electricity",
                                            "j": 20e9}]}},
                  "zones": {}}
        variants, elections, warnings = self._run(annual)
        # 80/(80+20) = 80% of the blocks' annual heating, over the 33%
        # proviso, so sentence (g) elects the largest auxiliary fuel.
        self.assertEqual(1, len(elections),
                         "the 8.4.4.13.(2)(g) election must actually FIRE — "
                         "otherwise this case is the structural path in "
                         "disguise and pins nothing")
        self.assertEqual("electric", elections[0].get("value"))
        self.assertEqual(["electric"], variants,
                         "the elected auxiliary fuel picks the variant")
        self.assertEqual(1, len(warnings),
                         "and the (5) disclosure must survive that election")

    def test_the_structural_path_is_the_separate_control(self):
        variants, elections, warnings = self._run(None)
        self.assertEqual(0, len(elections), "no annual data, no election")
        self.assertEqual(["gas"], variants, "the 8.4.4.9.(4) proxy decides")
        self.assertEqual(1, len(warnings))


class TestTheEntryDescribesTheADOPTEDPlant(_Fixture):
    """Fable's `117` B1: the entry said "the reference retains one boiler per
    energy type", and the reference does no such thing.

    It ADOPTS the proposed hot-water plant whole — a three-boiler proposed
    plant gives a three-boiler reference — and then the post-sizing staging
    pass sets the plant's live capacity by primary/secondary ROLE, blind to
    fuel, driving a secondary under the single-boiler threshold to ~0 W. So
    the installed allocation is NOT carried into the annual reference, and
    the surviving fuel need not be the elected one. Confirmed in the
    repository's own committed baselines, where the reference building's
    Secondary Boiler carries `capacity_kw: 0.0` against a
    `design_capacity_kw` of 64.4 or 83.6.
    """

    def _selection(self):
        sel = super()._selection()
        sel["special_rules"]["heat_pump"] = {"article": "8.4.4.13.(1)-(2)"}
        return sel

    def test_a_THREE_boiler_plant_is_not_described_as_one_per_type(self):
        group = self._group(("Electricity", "NaturalGas"))
        facts = self._facts(plants=[{
            "type": "hot_water", "name": "Three Boiler Loop",
            "fuels": ["NaturalGas", "Electricity"],
            "heating_device_count": 3,
            "fuel_capacities_w": {"NaturalGas": None, "Electricity": None}}])
        _r, warnings, _a = self._call(group, facts)
        entry = warnings[0]
        self.assertNotIn("one boiler per energy type", entry["action"])
        self.assertNotIn("retains one boiler", entry["action"])
        self.assertEqual(3, entry["inputs"]["plant_heating_devices"],
                         "the DEVICE COUNT is what distinguishes this from "
                         "'one per type'; the fuel set cannot")

    def _mixed(self):
        group = self._group(("Electricity", "NaturalGas"))
        facts = self._facts(plants=[{
            "type": "hot_water", "name": "Mixed Loop",
            "fuels": ["NaturalGas", "Electricity"],
            "heating_device_count": 2,
            "fuel_capacities_w": {"NaturalGas": None, "Electricity": None}}])
        _r, warnings, _a = self._call(group, facts)
        return warnings[0]

    def test_the_PROSE_states_the_fuel_blind_staging(self):
        entry = self._mixed()
        self.assertIn("ADOPTS", entry["action"])
        self.assertIn("BLIND to energy type", entry["action"])
        self.assertIn("need not be the one elected", entry["action"])
        self.assertNotIn(
            "retained rather than collapsed", entry["action"].lower(),
            "the staging pass collapses it on every run — the opposite")

    def test_the_INPUTS_record_the_role_basis_separately(self):
        rule = self._mixed()["inputs"]["live_capacity_rule"]
        self.assertIn("primary/secondary ROLE", rule)
        self.assertIn("blind to energy type", rule)
        self.assertNotIn("proposed allocation: a", rule)


class TestTheStagingPassIsFuelBLIND(unittest.TestCase):
    """The mechanism the entry now describes, exercised rather than asserted.

    Fable's `117` found the entry claiming the reference "retains one boiler
    per energy type". What actually happens is that the post-sizing staging
    pass sets the plant's live capacity by primary/secondary ROLE — builder
    feature, then device NAME, then supply order — and blind to fuel, driving
    a secondary below the single-boiler threshold to ~0 W.

    Reading the frozen baselines would show the same thing, but it would be
    testing an artifact: a wrongly regenerated baseline would agree with a
    wrongly behaving pass. This drives the pass itself.
    """

    @needs_sdk
    def _staged(self, primary_fuel, secondary_fuel):
        import openstudio

        from btap.audit import AuditLog
        from btap.codes.necb import hvac

        model = openstudio.model.Model()
        loop = openstudio.model.PlantLoop(model)
        loop.setName("Hot Water Loop")
        loop.sizingPlant().setLoopType("Heating")
        loop.setLoadDistributionScheme("SequentialLoad")
        made = {}
        for role, fuel in (("Primary", primary_fuel),
                           ("Secondary", secondary_fuel)):
            b = openstudio.model.BoilerHotWater(model)
            b.setName(f"{role} Boiler")
            b.setFuelType(fuel)
            b.setNominalCapacity(52_000.0)      # one plant, well under 176 kW
            loop.addSupplyBranchForComponent(b)
            made[role] = b
        hvac.apply_efficiencies(model, code="necb2020", audit=AuditLog())
        return {r: (b.fuelType(), b.nominalCapacity().get())
                for r, b in made.items()}

    @needs_sdk
    def test_the_SECONDARY_is_zeroed_whichever_fuel_it_carries(self):
        gas_lead = self._staged("NaturalGas", "Electricity")
        elec_lead = self._staged("Electricity", "NaturalGas")
        for label, got in (("gas-led", gas_lead), ("electric-led", elec_lead)):
            primary_fuel, primary_w = got["Primary"]
            secondary_fuel, secondary_w = got["Secondary"]
            self.assertGreater(primary_w, 1.0,
                               f"{label}: the primary keeps its capacity")
            self.assertLess(
                secondary_w, 1.0,
                f"{label}: the secondary is driven to ~0 W, so the installed "
                f"allocation is NOT carried through — got {secondary_w}")
        # The discriminating part: the surviving fuel follows the ROLE, not
        # the energy type, so flipping the fuels flips which fuel survives.
        self.assertEqual("NaturalGas", gas_lead["Primary"][0])
        self.assertEqual("Electricity", elec_lead["Primary"][0],
                         "fuel-blind: an electric primary survives just as a "
                         "gas primary does, which is why the surviving fuel "
                         "need not be the elected reference energy type")


class TestTheEditionComesFromTheManifest(unittest.TestCase):
    """Fable's `117` O4: deriving the subsection from the heat-pump article
    had a SILENT 2020 fallback, so a 2025 run with a missing or malformed
    heat-pump rule value would cite 2020 to the AHJ without a word."""

    def test_a_MALFORMED_heat_pump_article_does_not_silently_mean_2020(self):
        from btap.codes import resolve

        broken = {"special_rules": {"heat_pump": {"article": "Table"}}}
        # with the ruleset in hand the manifest registry decides
        for code, want in (("necb2020", "8.4.4"), ("necb2025", "8.4.5")):
            ratio, _ = reference.multi_energy_articles(broken, resolve(code))
            self.assertTrue(
                ratio.startswith(want),
                f"{code} must cite {want}.9.(5) from the manifest's "
                f"reference_subsection, not a derived guess; got {ratio}")


class TestTheDedupeStateIsCallSCOPED(unittest.TestCase):
    """Fable's `117` O5: the seen-set was written into the caller's `facts`,
    which `select_reference_systems` documents as pure input — so a second
    call on the same dict emitted no disclosure at all."""

    def test_two_calls_on_ONE_facts_dict_each_disclose(self):
        import copy

        facts = copy.deepcopy(_ASHP_MIXED_FACTS)
        counts = []
        for _ in range(2):
            audit = AuditLog()
            reference.select_reference_systems(
                facts=facts, building={"storeys": 1}, code="necb2020",
                audit=audit, proposed_annual=None)
            counts.append(len([e for e in audit.entries
                               if "UNRESOLVED" in str(e.get("action"))
                               and "ENERGY TYPE" in str(e.get("action"))]))
        self.assertEqual([1, 1], counts,
                         "the dedupe must not persist across calls")
        self.assertNotIn("_multi_energy_warned", facts,
                         "and must not be written into the caller's dict")


class TestTheDisclosureDoesNotOVERSTATE(_Fixture):
    """Sol's `114`.1/.3/.4 — three distinct overstatements, one entry."""

    def _selection(self):
        sel = super()._selection()
        sel["special_rules"]["heat_pump"] = {"article": "8.4.4.13.(1)-(2)"}
        return sel

    def test_a_plant_covering_PART_of_the_group_keeps_shares_unresolved(self):
        """A gas+oil plant under an {Electricity, gas, oil} group was taking
        the specific branch and reporting shares of {gas: .6, oil: .4} —
        electricity dropped out of the DENOMINATOR entirely."""
        group = self._group(("Electricity", "NaturalGas", "FuelOilNo2"))
        facts = self._facts(plants=[{
            "type": "hot_water", "name": "Gas+Oil Loop",
            "fuels": ["NaturalGas", "FuelOilNo2"],
            "fuel_capacities_w": {"NaturalGas": 60_000.0,
                                  "FuelOilNo2": 40_000.0}}])
        _r, warnings, _a = self._call(group, facts)
        self.assertEqual(1, len(warnings))
        entry = warnings[0]
        self.assertNotIn("ONE BOILER PLANT", entry["action"],
                         "the plant does not account for the whole group")
        self.assertNotIn("proposed_capacity_shares", entry["inputs"],
                         "a plant-only split is NOT the group's allocation")
        self.assertIn("UNRESOLVED", entry["inputs"]["group_shares"])
        self.assertEqual(["FuelOilNo2", "NaturalGas"],
                         entry["inputs"]["plant_energy_types"])

    def test_the_entry_says_NOT_VERIFIED_rather_than_NOT_MET(self):
        """Sample 16's reference DOES carry electric ASHP heating stages, so
        "the other types carry no reference capacity" and "the ratio is NOT
        met" were both false. The tool does not compute the allocation, so
        the honest statement is that it is not verified either way."""
        group = self._group(("Electricity", "NaturalGas"))
        facts = self._facts(plants=[{
            "type": "hot_water", "name": "Gas Only Loop",
            "fuels": ["NaturalGas"],
            "fuel_capacities_w": {"NaturalGas": 50_000.0}}])
        _r, warnings, _a = self._call(group, facts)
        action = warnings[0]["action"]
        self.assertIn("NOT VERIFIED", action)
        for false_claim in ("is NOT met", "no reference capacity",
                            "carry no reference"):
            self.assertNotIn(false_claim, action)

    def test_no_6_SUBCLAUSE_is_cited_without_a_capacity_band(self):
        """(6)(b) is the <=176 kW subclause. (6)(c) covers 176-352 and (6)(d)
        above that. Which applies depends on the REFERENCE plant capacity,
        which does not exist at selection time, so citing (6)(b) asserted a
        band nothing had established."""
        group = self._group(("Electricity", "NaturalGas"))
        facts = self._facts(plants=[{
            "type": "hot_water", "name": "Mixed Loop",
            "fuels": ["NaturalGas", "Electricity"],
            "fuel_capacities_w": {"NaturalGas": None, "Electricity": None}}])
        _r, warnings, _a = self._call(group, facts)
        entry = warnings[0]
        self.assertEqual("8.4.4.9.(5); 8.4.4.9.(6)", entry["article"])
        for subclause in ("(6)(b)", "(6)(c)", "(6)(d)"):
            self.assertNotIn(subclause, entry["article"])
            self.assertNotIn(subclause, entry["action"])
        self.assertIn("NOT ESTABLISHED",
                      entry["inputs"]["boiler_count_subclause"])

    def test_the_measurement_does_NOT_travel_to_another_edition(self):
        """Sol's `114`: "Do not attach the 2020 experiment to a 2025 runtime
        audit as though it verifies that model." The repo's own
        edition-independence test says the same thing about the snapshots.
        """
        group = self._group(("Electricity", "NaturalGas"))
        facts = self._facts(plants=[{
            "type": "hot_water", "name": "Mixed Loop",
            "fuels": ["NaturalGas", "Electricity"],
            "fuel_capacities_w": {"NaturalGas": None, "Electricity": None}}])
        audit = AuditLog()
        reference._disclose_multi_energy(
            group,
            {"special_rules": {
                "purchased_heating": {"article": "8.4.5.6.(1)",
                                      "part_load_curve_class": "modulating"},
                "heat_pump": {"article": "8.4.5.13.(1)-(2) + Table 8.4.5.13"}}},
            facts, audit)
        entry = [e for e in audit.entries
                 if "UNRESOLVED" in str(e.get("action"))][0]
        measured = entry["inputs"]["fixture_measurement"]
        self.assertIn("NONE for this edition", measured)
        for leaked in ("158,219.4", "157,602.8", "sample 11", "necb2020"):
            self.assertNotIn(leaked, measured,
                             f"{leaked!r} belongs to the other edition")

    def test_the_measurement_names_its_sample_and_does_not_say_unchanged(self):
        """`114`: I had written that the annual result was "unchanged at the
        legacy gem's 0.5 sizing factor". It was not — it changed by
        -616.6 kWh. What was unchanged is that the secondary never fired."""
        group = self._group(("Electricity", "NaturalGas"))
        facts = self._facts(plants=[{
            "type": "hot_water", "name": "Mixed Loop",
            "fuels": ["NaturalGas", "Electricity"],
            "fuel_capacities_w": {"NaturalGas": None, "Electricity": None}}])
        _r, warnings, _a = self._call(group, facts)
        measured = warnings[0]["inputs"]["fixture_measurement"]
        self.assertIn("sample 11 only", measured)
        self.assertIn("necb2020", measured)
        self.assertIn("157,602.8", measured, "the 0.5 result must be stated")
        self.assertIn("-616.6", measured, "and named as a CHANGE")
        self.assertIn("never fired", measured)
        self.assertNotIn("unchanged at", measured)
        # Fable's `117` O1: the "two boilers" model was the SIZING-RUN INPUT
        # with both boilers autosized, not the annual reference the pipeline
        # builds, where the staging pass has already zeroed the secondary.
        self.assertIn("FED TO THE SIZING RUN", measured)
        self.assertIn("NOT the model the annual pipeline runs", measured)


def _plant(model, fuels, capacity_w=None, name="Hot Water Loop"):
    """A hot-water plant with one boiler per named fuel, BUILT not loaded.

    The previous fixture read an OSM out of an absolute scratchpad path and
    `skipTest`-ed when it was absent, so it never ran on CI — a check that
    cannot fail (Sol, `113`).
    """
    import openstudio

    loop = openstudio.model.PlantLoop(model)
    loop.setName(name)
    loop.sizingPlant().setLoopType("Heating")
    loop.setLoadDistributionScheme("SequentialLoad")
    boilers = []
    for i, fuel in enumerate(fuels):
        boiler = openstudio.model.BoilerHotWater(model)
        boiler.setName(f"{name} Boiler {i + 1}")
        boiler.setFuelType(fuel)
        if capacity_w is not None and capacity_w[i] is not None:
            boiler.setNominalCapacity(capacity_w[i])
        loop.addSupplyBranchForComponent(boiler)
        boilers.append(boiler)
    return loop, boilers


class TestTheGenericEntryDedupesByServingGROUP(_Fixture):
    """Sol's `113`: "Deduplicate by the actual serving system rather than by
    any plant sharing one fuel."

    Two distinct mixed serving groups can both intersect ONE gas-only plant.
    Each is its own serving system and each is its own unresolved finding, so
    keying the dedupe on that shared plant would report one and silently drop
    the other. A survived mutation is what showed this was unpinned.
    """

    def _selection(self):
        sel = super()._selection()
        sel["special_rules"]["heat_pump"] = {"article": "8.4.4.13.(1)-(2)"}
        return sel

    def test_two_mixed_groups_sharing_one_GAS_ONLY_plant_warn_twice(self):
        from btap.codes.necb.hvac import reference

        gas_only = {"type": "hot_water", "name": "Shared Gas Loop",
                    "fuels": ["NaturalGas"],
                    "fuel_capacities_w": {"NaturalGas": 50_000.0}}
        facts = self._facts(plants=[gas_only])      # ONE facts dict: shared state
        audit = self._audit()
        for zones in (("North 1", "North 2"), ("South 1", "South 2")):
            reference._disclose_multi_energy(
                self._group(("NaturalGas", "Electricity"), zones=zones),
                self._selection(), facts, audit)
        warnings = [e for e in audit.entries
                    if "UNRESOLVED" in str(e.get("action"))]
        self.assertEqual(
            2, len(warnings),
            "each serving GROUP is its own finding; keying on the shared "
            "single-fuel plant drops the second")
        self.assertEqual({"North 1,North 2", "South 1,South 2"},
                         {e["target"] for e in warnings})

    def test_two_groups_with_NO_identified_plant_still_warn_twice(self):
        """The ambiguous/no-plant path puts `None` in the plant name, so a
        plant-keyed dedupe collapses every such group into one entry."""
        from btap.codes.necb.hvac import reference

        facts = self._facts(plants=[])              # nothing to match at all
        audit = self._audit()
        for zones in (("A",), ("B",)):
            reference._disclose_multi_energy(
                self._group(("NaturalGas", "Electricity"), zones=zones),
                self._selection(), facts, audit)
        warnings = [e for e in audit.entries
                    if "UNRESOLVED" in str(e.get("action"))]
        self.assertEqual(2, len(warnings))
        self.assertEqual({"A", "B"}, {e["target"] for e in warnings})


class TestTheAllocationIsRecordedByClassify(unittest.TestCase):
    @needs_sdk
    def test_a_dual_fuel_plant_carries_both_fuels_and_both_capacities(self):
        """`classify` is where the allocation comes from, so the survey must
        carry it — not just the fuel names it carried before."""
        import openstudio

        from btap.modeling.hvac import classify

        model = openstudio.model.Model()
        _plant(model, ("NaturalGas", "Electricity"))
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

    @needs_sdk
    def test_a_SIZED_60_40_plant_reports_those_shares_not_a_guess(self):
        """Sol's `113` asked for an explicit UNEQUAL split, because a 50/50
        one cannot distinguish a real allocation from the autosizing default
        that gives every parallel boiler the whole load."""
        import openstudio

        from btap.modeling.hvac import classify

        model = openstudio.model.Model()
        _plant(model, ("NaturalGas", "Electricity"),
               capacity_w=(60_000.0, 40_000.0))
        facts = classify.characterize(model)
        hot = [p for p in facts["plants"] if p["type"] == "hot_water"][0]
        self.assertEqual({"NaturalGas": 60_000.0, "Electricity": 40_000.0},
                         hot["fuel_capacities_w"])

        group = {"zones": ["Zone 1"],
                 "heating_energy_types": ["NaturalGas", "Electricity"]}
        audit = AuditLog()
        reference._disclose_multi_energy(
            group,
            {"special_rules": {"purchased_heating": {
                "article": "8.4.4.6.(1)", "part_load_curve_class": "modulating"},
                "heat_pump": {"article": "8.4.4.13.(1)-(2)"}}},
            {"plants": facts["plants"], "purchased_energy": {}}, audit)
        warned = [e for e in audit.entries
                  if "UNRESOLVED" in str(e.get("action"))]
        self.assertEqual(1, len(warned))
        self.assertEqual({"NaturalGas": 0.6, "Electricity": 0.4},
                         warned[0]["inputs"]["proposed_capacity_shares"])


class TestTheWarningDoesNotOVERCLAIM(_Fixture):
    """Sol's `113` blocker 1: the specific boiler statements were being made
    about groups that have NO dual-fuel plant. Samples 16/17/18 have a
    GAS-ONLY hot-water plant plus electric heating elsewhere in the group,
    and the committed audits claimed two boilers, SequentialLoad, a 50/50
    match and a measured energy result for all three.
    """

    def _selection(self):
        sel = super()._selection()
        sel["special_rules"]["heat_pump"] = {"article": "8.4.4.13.(1)-(2)"}
        return sel

    def test_a_GAS_ONLY_plant_in_a_mixed_group_makes_no_boiler_claim(self):
        group = self._group(("NaturalGas", "Electricity"))
        facts = self._facts(plants=[{"type": "hot_water",
                                     "name": "Gas Only Loop",
                                     "fuels": ["NaturalGas"],
                                     "fuel_capacities_w": {"NaturalGas": 50_000.0}}])
        _result, warnings, _audit = self._call(group, facts)
        self.assertEqual(1, len(warnings), "the group is still unresolved")
        action = warnings[0]["action"]
        for forbidden in ("BOILER PLANT", "boiler per energy type",
                          "SequentialLoad", "energy-neutral", "158,219.4"):
            self.assertNotIn(
                forbidden, action,
                f"a gas-only plant cannot support the claim {forbidden!r}")
        self.assertIn("NOT VERIFIED", action)
        self.assertEqual(["NaturalGas"],
                         warnings[0]["inputs"]["plant_energy_types"])
        self.assertEqual("8.4.4.9.(5)", warnings[0]["article"],
                         "(6)(b) is a BOILER-COUNT article and must not be "
                         "cited where no boiler count is at issue")

    def test_a_TRUE_dual_fuel_plant_still_gets_the_specific_entry(self):
        group = self._group(("NaturalGas", "Electricity"))
        facts = self._facts(plants=[{"type": "hot_water",
                                     "name": "Mixed Loop",
                                     "fuels": ["NaturalGas", "Electricity"],
                                     "fuel_capacities_w": {"NaturalGas": None,
                                                           "Electricity": None}}])
        _result, warnings, _audit = self._call(group, facts)
        self.assertEqual(1, len(warnings))
        self.assertIn("ONE BOILER PLANT", warnings[0]["action"])
        self.assertEqual("8.4.4.9.(5); 8.4.4.9.(6)", warnings[0]["article"])
        self.assertIn(
            "NOT a property of this model",
            warnings[0]["inputs"]["fixture_measurement"],
            "the measurement is provenance for samples 11/12, never a claim "
            "about the model in hand")

    def test_the_2025_edition_cites_2025_articles(self):
        group = self._group(("NaturalGas", "Electricity"))
        facts = self._facts(plants=[{"type": "hot_water",
                                     "name": "Mixed Loop",
                                     "fuels": ["NaturalGas", "Electricity"],
                                     "fuel_capacities_w": {"NaturalGas": None,
                                                           "Electricity": None}}])
        audit = AuditLog()
        reference._disclose_multi_energy(
            group,
            {"special_rules": {
                "purchased_heating": {"article": "8.4.5.6.(1)",
                                      "part_load_curve_class": "modulating"},
                "heat_pump": {"article": "8.4.5.13.(1)-(2) + Table 8.4.5.13"}}},
            facts, audit)
        warned = [e for e in audit.entries
                  if "UNRESOLVED" in str(e.get("action"))]
        self.assertEqual(1, len(warned))
        self.assertEqual("8.4.5.9.(5); 8.4.5.9.(6)", warned[0]["article"])
        self.assertNotIn("8.4.4.", warned[0]["action"],
                         "a 2025 run must not cite a 2020 article to the AHJ")


if __name__ == "__main__":
    unittest.main(verbosity=2)
