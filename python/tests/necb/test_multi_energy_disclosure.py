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


def allocation_records(audit):
    """The 8.4.x.9.(5) allocation disclosures — the AHJ-1 service-set scope."""
    return [e for e in audit.entries
            if e["level"] == "warning"
            and "UNRESOLVED" in str(e.get("action"))
            and "AHJ-1" in str(e.get("ahj") or "")]


def plant_records(audit):
    """The 8.4.x.9.(6) plant-cardinality disclosures — the AHJ-3 plant scope."""
    return [e for e in audit.entries
            if e["level"] == "warning"
            and "UNRESOLVED" in str(e.get("action"))
            and "AHJ-3" in str(e.get("ahj") or "")]


class _Fixture(unittest.TestCase):
    def _audit(self):
        from btap.audit import AuditLog

        return AuditLog()

    def _group(self, fuels, zones=("Zone 1",), serving=None):
        group = {"zones": list(zones), "heating_energy_types": list(fuels)}
        if serving is not None:
            # What `_blocks_of` stamps on each block view: the SERVICE SET the
            # block belongs to. The AHJ-1 allocation disclosure dedupes on it,
            # so a synthetic block split that omits it is not the real shape.
            group["_serving_zones"] = tuple(serving)
        return group

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
        # THE ALLOCATION RECORD ONLY. AHJ-3's plant-cardinality question is a
        # separate entry with its own scope since D-101 (Sol, `143`): AHJ-1
        # follows each proposed heating service and allocation choice, AHJ-3
        # follows the hydronic plant, and one plant can carry two service sets.
        # Every test in this file is about the allocation half; `plant_records`
        # below is the other one.
        return result, allocation_records(audit), audit


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
        blocks = tuple(f"Zone {n}" for n in range(5))
        for block in blocks:
            # Each call is one BLOCK VIEW of one service set, which is what
            # `_blocks_of` produces — so `_serving_zones` is set. Without it
            # these are five independent service sets, and under D-101 five
            # separate allocation choices legitimately disclose five times.
            reference._disclose_multi_energy(
                self._group(["NaturalGas", "Electricity"],
                            zones=(block,), serving=blocks),
                self._selection(), facts, audit)
        allocations = allocation_records(audit)
        self.assertEqual(
            1, len(allocations),
            f"one service choice, one allocation record — got {len(allocations)}")
        self.assertEqual(
            list(blocks), sorted(allocations[0]["target"].split(",")),
            "and it must name every affected block, not the plant: a plant "
            "name told a reader nothing about this question's reach")
        self.assertEqual(
            list(blocks), allocations[0]["inputs"]["affected_blocks"])

        plants = plant_records(audit)
        self.assertEqual(1, len(plants),
                         "the (6) cardinality question is asked ONCE of the plant")
        self.assertEqual("Hot Water Loop", plants[0]["target"],
                         "and THAT record is the one that names the plant")

    def test_TWO_service_sets_on_ONE_plant_give_two_allocations_and_one_plant_record(self):
        """Sol's `143`, the shape the combined entry could not express.

        Two independent proposed serving systems drawing on one dual-fuel
        hot-water plant are TWO 8.4.x.9.(5) allocation choices and ONE
        8.4.x.9.(6) plant-cardinality question. Keying both ids by plant
        emitted a single warning for all of it.
        """
        from btap.audit import AuditLog
        from btap.codes.necb.hvac import reference

        plant = {"name": "Hot Water Loop", "type": "hot_water",
                 "fuels": ["NaturalGas", "Electricity"],
                 "fuel_capacities_w": {"NaturalGas": None,
                                       "Electricity": None}}
        facts = self._facts([plant])
        audit = AuditLog()
        first = ("Zone 1", "Zone 2", "Zone 3")
        second = ("Zone 4", "Zone 5")
        for service_set in (first, second):
            for block in service_set:
                reference._disclose_multi_energy(
                    self._group(["NaturalGas", "Electricity"],
                                zones=(block,), serving=service_set),
                    self._selection(), facts, audit)
        allocations = allocation_records(audit)
        self.assertEqual(2, len(allocations),
                         "two service choices are two allocation records")
        self.assertEqual(
            [list(first), list(second)],
            sorted(sorted(e["inputs"]["affected_blocks"]) for e in allocations),
            "each names its OWN blocks")
        self.assertEqual(
            1, len(plant_records(audit)),
            "but the plant is asked once, however many systems draw on it")

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
        # DISTINCT ZONES, because the allocation record dedupes on the SERVICE
        # SET since D-101. Both calls used the default `Zone 1`, which under a
        # plant key were two findings and under a service key are one service
        # set asked twice — so the control now says what it means: two serving
        # systems, two plants, two of each record.
        reference._disclose_multi_energy(
            self._group(["NaturalGas", "Electricity"], zones=("Zone 1",)),
            self._selection(), facts, audit)
        facts["plants"] = [
            {"name": "Hot Water Loop B", "type": "hot_water",
             "fuels": ["FuelOilNo2", "Electricity"],
             "fuel_capacities_w": {"FuelOilNo2": None, "Electricity": None}}]
        reference._disclose_multi_energy(
            self._group(["FuelOilNo2", "Electricity"], zones=("Zone 2",)),
            self._selection(), facts, audit)
        self.assertEqual(2, len(allocation_records(audit)))
        self.assertEqual(
            ["Hot Water Loop A", "Hot Water Loop B"],
            sorted(e["target"] for e in plant_records(audit)),
            "two plants are two cardinality questions")
        # The old assertion here required the ALLOCATION warnings to name the
        # plants, which is the conflation D-101 removed: those records now name
        # their affected blocks, and the plant assertion above carries the
        # per-plant intent.


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


class TestTheEntryAssertsNothingAboutTheReferencePlant(_Fixture):
    """The entry must describe the PROPOSED plant and claim nothing about the
    reference one. Sol's `120`/`121` found FOUR reachable outcomes; since D-101
    there are THREE, because adoption is no longer among them — phased
    teardown plus the ungated plant reservation mean a built block cannot join
    a surviving proposed plant, and a `copy_proposed` block never reaches this
    disclosure at all (Sol, `160`):

    * it is torn down and REPLACED by a newly built plant of the selected
      variant, holding none of its devices;
    * it is torn down and not rebuilt, where the variant needs no boiler;
    * a hydronic plant results and the post-sizing staging pass acts on
      primary/secondary ROLE blind to fuel — preserving an equal pair in the
      two-boiler band, stubbing a recognised secondary below the
      single-boiler threshold, and doing nothing at all to a plant whose
      devices take no recognised role.

    Each earlier version of this class asserted one of those as general.
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
            "boiler_count": 3,
            "fuel_capacities_w": {"NaturalGas": None, "Electricity": None}}])
        _r, warnings, _a = self._call(group, facts)
        entry = warnings[0]
        self.assertNotIn("one boiler per energy type", entry["action"])
        self.assertNotIn("retains one boiler", entry["action"])
        self.assertEqual(3, entry["inputs"]["plant_boiler_count"],
                         "the BOILER COUNT is what distinguishes this from "
                         "'one per type'; the fuel set cannot")

    def _mixed(self):
        group = self._group(("Electricity", "NaturalGas"))
        facts = self._facts(plants=[{
            "type": "hot_water", "name": "Mixed Loop",
            "fuels": ["NaturalGas", "Electricity"],
            "boiler_count": 2,
            "fuel_capacities_w": {"NaturalGas": None, "Electricity": None}}])
        _r, warnings, _a = self._call(group, facts)
        return warnings[0]

    def test_the_PROSE_asserts_NOTHING_about_the_reference_plant(self):
        """Sol's `120`: my replacement text generalised samples 11/12 into
        cases where it is false — an equal pair in the two-boiler band IS
        preserved, a plant with no recognised role is not staged at all, and
        a heat-pump variant needing no boiler has the plant torn down. So the
        prose may state the possibilities and claim none of them."""
        entry = self._mixed()
        action = entry["action"]
        self.assertIn("PROPOSED heating system", action)
        self.assertIn("not established", action.lower())
        for overclaim in ("the reference ADOPTS", "is NOT carried through",
                          "need not be the one elected",
                          "retained rather than collapsed"):
            self.assertNotIn(overclaim, action,
                             f"{overclaim!r} is true of samples 11/12 only")

    def _outcome_text(self):
        return self._mixed()["inputs"]["live_capacity_outcome"]

    def test_the_outcome_is_declared_NOT_ESTABLISHED(self):
        out = self._outcome_text()
        self.assertIn("NOT ESTABLISHED", out)
        self.assertIn("blind to energy", out)

    def test_the_outcome_lists_the_TORN_DOWN_possibility(self):
        """A heat-pump variant with `needs_boiler: false` has the plant
        removed, so the reference plant may not exist at all."""
        self.assertIn("torn down", self._outcome_text())

    def test_the_outcome_lists_the_REPLACED_possibility(self):
        """Sol's `121`: a one-group mixed gas/electric loop was torn down and
        the selected gas variant built a DIFFERENT two-boiler NaturalGas
        plant, with no proposed handle on either boiler. "Adopted or absent"
        omitted that third case."""
        out = self._outcome_text()
        self.assertIn("DIFFERENT", out)
        self.assertIn("holding none of these devices", out)

    def test_the_outcome_lists_the_PRESERVED_band(self):
        """Measured: two role-labelled 200 kW boilers become 100/100 kW in the
        176-352 kW band, so an equal ratio IS carried through there."""
        self.assertIn("PRESERVED", self._outcome_text())

    def test_the_outcome_lists_the_NO_ROLE_case(self):
        """Measured: three generically-named 52 kW boilers keep 52/52/52,
        because `_plant_role` returns None unless there are exactly two."""
        self.assertIn("no recognised role", self._outcome_text())


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


class TestTheStagingOutcomeIsCONDITIONAL(unittest.TestCase):
    """Sol's `120` counterexamples, exercised. My corrected entry said the
    staging pass always discards the allocation; it does not.
    """

    @needs_sdk
    def _plant(self, specs, names=("Primary Boiler", "Secondary Boiler",
                                   "Third Boiler")):
        import openstudio

        from btap.audit import AuditLog
        from btap.codes.necb import hvac

        model = openstudio.model.Model()
        loop = openstudio.model.PlantLoop(model)
        loop.setName("Hot Water Loop")
        loop.sizingPlant().setLoopType("Heating")
        loop.setLoadDistributionScheme("SequentialLoad")
        made = []
        for i, (fuel, watts) in enumerate(specs):
            b = openstudio.model.BoilerHotWater(model)
            b.setName(names[i])
            b.setFuelType(fuel)
            b.setNominalCapacity(watts)
            loop.addSupplyBranchForComponent(b)
            made.append(b)
        hvac.apply_efficiencies(model, code="necb2020", audit=AuditLog())
        return [(b.fuelType(), b.nominalCapacity().get()) for b in made]

    @needs_sdk
    def test_an_equal_PAIR_in_the_two_boiler_band_is_PRESERVED(self):
        """200 kW each lands in the 176-352 kW band, where (6)(c) wants two
        equal boilers — so the 50/50 ratio survives, and the entry must not
        say the allocation is never carried through."""
        got = self._plant([("NaturalGas", 200_000.0),
                           ("Electricity", 200_000.0)])
        caps = [w for _f, w in got]
        self.assertTrue(all(w > 1.0 for w in caps),
                        f"neither is stubbed in this band; got {got}")
        self.assertAlmostEqual(caps[0], caps[1], delta=1.0,
                               msg=f"an EQUAL pair is preserved; got {got}")

    @needs_sdk
    def test_a_THREE_boiler_plant_takes_no_role_and_is_not_staged(self):
        """`_plant_role` returns None unless there are exactly two boilers, so
        every device keeps full capacity — NOT 'roles for only two', which is
        what my gap text claimed."""
        got = self._plant([("NaturalGas", 52_000.0),
                           ("Electricity", 52_000.0),
                           ("NaturalGas", 52_000.0)],
                          names=("Boiler A", "Boiler B", "Boiler C"))
        caps = [w for _f, w in got]
        self.assertTrue(all(w > 1.0 for w in caps),
                        f"no role recognised, so nothing is stubbed; got {got}")


@needs_sdk
class TestTheOutcomesAreReachableInABuiltModel(unittest.TestCase):
    """The outcome list names four possibilities; two were pinned only as
    PROSE.

    `..._lists_the_TORN_DOWN_possibility` and `..._the_REPLACED_possibility`
    assert the entry's TEXT contains certain words. Their docstrings state
    measured facts, but the evidence was Sol's manual probe in `121` recorded
    in a docstring — nothing in the suite built a model and looked. Same shape
    as asserting the HTML contains the new wording without asserting the
    withdrawn claim is gone.

    THREE outcomes are reachable in a built model, not four: REPLACED and TORN
    DOWN here, and the role-staging pair in
    `TestTheStagingOutcomeIsCONDITIONAL`. ADOPTION was removed from AHJ-1's
    outcome list on 2026-10-09 (Sol's `145`), because this disclosure fires
    only for a block whose heating was collapsed to one energy type — always an
    `action == "build"` assignment — and `_finalize` returns before the
    election and the disclosure for a `copy_proposed` block. The retention
    tests below therefore prove that `copy_proposed` CAN keep a proposed plant,
    which is true and separate, and no longer claim it as an AHJ-1 outcome.

    Two discriminators do NOT work, and both were tried first:

    - object NAMES. The reference's boilers are called `Primary Boiler` and
      `Secondary Boiler`, and so are the proposed's, because the builder uses
      conventional names. Name equality cannot tell adoption from a rebuild.
    - object HANDLES. The reference is a separate `Model`, so EVERY object has
      a new handle by construction, whether cloned or built.

    What works is a marker the builder would never produce.
    """

    MARKER = "PROPOSED MARKER"

    def _mixed_proposed(self, system="Baseboard gas boiler"):
        """A proposed model whose hot-water plant is dual-fuel, with every
        boiler marked so adoption is visible in the reference."""
        from .support import proposed_with_hvac

        proposed = proposed_with_hvac(system)
        boilers = sorted(proposed.getBoilerHotWaters(),
                         key=lambda b: b.nameString())
        if len(boilers) > 1:
            boilers[0].setFuelType("Electricity")
        for index, boiler in enumerate(boilers):
            boiler.setName("{} {}".format(self.MARKER, index))
        return proposed

    def _residential_mixed_proposed(self):
        """Residential four-pipe fan coils on a dual-fuel plant — adoption by
        the branch the Code actually provides.

        Until D-101 the ADOPTED outcome was reached with `Baseboard gas boiler`,
        a `build` group whose plant merely SURVIVED a per-assignment teardown
        long enough to be found again by name. Sol's `141`: "an `action ==
        'build'` plant must not be adopted merely because sequential teardown
        has kept it non-empty", and phased destruction removed that route.

        `copy_proposed` is the explicit retention branch. It needs a residential
        space type AND compatible cooling, so heating-only baseboards fall
        through to a System 1 build and only a cooled residential system
        reaches it. Measured on this fixture: the audit records "proposed
        system retained in reference (residential...)", both markers survive,
        and the plant keeps Electricity and NaturalGas.
        """
        from .support import proposed_with_hvac

        proposed = proposed_with_hvac("FPFC MAU DX Coils with Scroll Chiller")
        for space_type in proposed.getSpaceTypes():
            if space_type.spaces():
                space_type.setStandardsSpaceType("Dwelling unit")
        boilers = sorted(proposed.getBoilerHotWaters(),
                         key=lambda b: b.nameString())
        if len(boilers) > 1:
            boilers[0].setFuelType("Electricity")
        for index, boiler in enumerate(boilers):
            boiler.setName("{} {}".format(self.MARKER, index))
        return proposed

    def _reference_of(self, proposed):
        from btap.audit import AuditLog
        from btap.codes.necb import hvac

        audit = AuditLog()
        result = hvac.reference_hvac(proposed, code="necb2020",
                                     building={"storeys": 1}, audit=audit)
        return result.model, audit

    def test_copy_proposed_RETAINS_the_plant_but_raises_no_AHJ_1(self):
        """Measured on residential four-pipe fan coils with one boiler switched
        to Electricity: both markers survive into the reference, so
        `copy_proposed` genuinely retains the proposed plant with both fuels.

        What this does NOT show is an AHJ-1 outcome, and asserting that is the
        point of the test now. Sol's `143` and `145`: this fixture emits ZERO
        AHJ-1 records, because `_finalize` returns for a `copy_proposed` block
        before the single-fuel election and before `_disclose_multi_energy`.
        Preserving a multi-fuel system is not the non-conforming single-fuel
        substitution AHJ-1 describes, so `adopted` was removed from that
        entry's outcome list rather than being evidenced by this run.
        """
        proposed = self._residential_mixed_proposed()
        reference, _audit = self._reference_of(proposed)
        survived = [b.nameString() for b in reference.getBoilerHotWaters()
                    if self.MARKER in b.nameString()]
        self.assertEqual(
            2, len(survived),
            "both marked boilers should survive retention; got {}".format(
                [b.nameString() for b in reference.getBoilerHotWaters()]))
        self.assertEqual(
            [], [e for e in _audit.entries
                 if "AHJ-1" in str(e.get("ahj") or "")],
            "and this is NOT an AHJ-1 outcome: a retained block never reaches "
            "the election or the disclosure, so the entry must not list "
            "`adopted` among its possibilities")

    def test_the_RETAINED_reference_plant_keeps_BOTH_FUELS(self):
        """The direct refutation of the claim withdrawn over eight rounds.

        The SELECTION elects one energy type. On this configuration the
        reference plant that results carries `Electricity` AND `NaturalGas` —
        so "the reference elects ONE energy type" was false as a statement
        about final equipment, which is why the disclosure now separates
        selection from outcome.

        Re-pointed at the residential retention fixture with D-101, and
        RENAMED from `test_the_adopted_reference_RETAINS_BOTH_FUELS`: what it
        exercises is `copy_proposed` retention, which is not "adoption" in the
        sense AHJ-1's withdrawn outcome used — a retained block never reaches
        the election or the disclosure at all (Fable, `158` F3).
        """
        proposed = self._residential_mixed_proposed()
        reference, _audit = self._reference_of(proposed)
        fuels = {b.fuelType() for b in reference.getBoilerHotWaters()}
        self.assertEqual(
            {"Electricity", "NaturalGas"}, fuels,
            "the RETAINED reference plant carries both proposed fuels")

    def test_the_REPLACED_outcome_is_reachable(self):
        """Sol's `121` found this outcome by hand and "adopted or absent"
        omitted it. Pinned here: the reference holds TWO boilers and NEITHER
        carries the marker, so the proposed plant was torn down and a
        different one built.

        The sentence here used to say that the terminal type decides adoption
        versus replacement — `Baseboard gas boiler` adopted, `... and Hot Water
        Baseboard` replaced. That stopped being true on this branch: D-101
        phases destruction ahead of construction and reserves every surviving
        proposed plant, so a BUILT block is replaced either way, and
        re-measuring both variants on an oil-fired plant gives NaturalGas
        boilers for both (Fable, `158` F3).
        """
        proposed = self._mixed_proposed(
            "PSZ RTU Electric and DX Coils and Hot Water Baseboard")
        reference, _audit = self._reference_of(proposed)
        boilers = list(reference.getBoilerHotWaters())
        self.assertTrue(
            boilers, "this variant needs a boiler, so one must be built")
        self.assertEqual(
            [], [b.nameString() for b in boilers
                 if self.MARKER in b.nameString()],
            "no proposed boiler survives, so the plant was REPLACED; if a "
            "marker appears this configuration became 'adopted' instead")

    def test_the_TORN_DOWN_outcome_is_reachable(self):
        """A variant declaring `needs_boiler: false` leaves the reference with
        no boiler at all. 50 shipped variants declare it; this uses one."""
        proposed = self._mixed_proposed(
            "PSZ RTU Electric and DX Coils and Electric Baseboard")
        reference, _audit = self._reference_of(proposed)
        self.assertEqual(
            [], [b.nameString() for b in reference.getBoilerHotWaters()],
            "this variant needs no boiler, so the reference carries none")

    def test_the_variant_used_above_really_declares_needs_boiler_false(self):
        """The control. If the catalog entry changed, the test above would
        pass for the wrong reason — a reference with no boiler because the
        model never had one."""
        import json
        import pathlib

        import btap.modeling as modeling

        data = json.loads(
            (pathlib.Path(modeling.__file__).parent / "hvac" / "data"
             / "systems.json").read_text(encoding="utf-8"))
        free = {s.get("name") for s in data["systems"]
                if s.get("needs_boiler") is False}
        self.assertIn(
            "PSZ RTU Electric and DX Coils and Electric Baseboard", free)


class TestPurchasedEnergyDoesNotSuppressUNRELATEDGroups(_Fixture):
    """Sol's `120` blocker 4: the building-wide `purchased_energy.heating`
    flag suppressed the (5) diagnostic everywhere, so district heat on one
    primary system hid the finding for an unrelated gas+electric system.
    8.4.x.6 governs the purchased system's CORRESPONDING system, not every
    group.
    """

    def _selection(self):
        sel = super()._selection()
        sel["special_rules"]["heat_pump"] = {"article": "8.4.4.13.(1)-(2)"}
        return sel

    def test_an_unrelated_dual_fuel_group_still_warns(self):
        group = self._group(("NaturalGas", "Electricity"))
        facts = self._facts(plants=[{
            "type": "hot_water", "name": "Mixed Loop",
            "fuels": ["NaturalGas", "Electricity"], "boiler_count": 2,
            "fuel_capacities_w": {"NaturalGas": None, "Electricity": None}}])
        facts["purchased_energy"] = {"heating": True}   # elsewhere in the bldg
        _r, warnings, _a = self._call(group, facts)
        self.assertEqual(
            1, len(warnings),
            "purchased heat on another system must not hide this group's "
            "unresolved multi-energy allocation")

    def test_the_PURCHASED_group_itself_is_still_skipped(self):
        """The control: 8.4.x.6 really is the route for a group that uses it."""
        group = self._group(("Purchased", "Electricity"))
        facts = self._facts(plants=[])
        facts["purchased_energy"] = {"heating": True}
        _r, warnings, _a = self._call(group, facts)
        self.assertEqual([], warnings)


class TestTheSINGLEEnergyELECTIONIsNotAlwaysIdentical(_Fixture):
    """Sol's `121` blocker 2: my (4) coverage said the energy type is identical
    "for a SINGLE-energy heating system". It is not — the cascade maps
    FuelOilNo2 and PropaneGas to the GAS catalog variant.

    **This class tests the SELECTION only**, and its name and assertions say
    so. It calls `_reference_energy_type` and proves `energy == "gas"`; it
    never builds a reference. Its earlier wording said an oil-heated building
    "gets a natural-gas reference", which is a claim about final equipment
    that a selector test cannot support — and Sol's `125`.1 measured it false:
    an adopted oil plant keeps `FuelOilNo2`. The final-equipment claim is
    tested in `TestAnOILProposedBuildingsFinalREFERENCEFuel`.
    """

    def _elect(self, fuel):
        from btap.codes.necb.hvac import reference

        group = self._group((fuel,))
        energy, _curve = reference._reference_energy_type(
            group, self._selection(), self._facts(), self._audit())
        return energy

    def test_oil_and_propane_both_ELECT_the_gas_variant(self):
        """SELECTION, not final equipment. The catalog has no oil or propane
        variant, so both elect gas; what the resulting reference burns is a
        separate measurement."""
        self.assertEqual("gas", self._elect("FuelOilNo2"),
                         "no oil variant exists, so the election is gas")
        self.assertEqual("gas", self._elect("PropaneGas"))

    def test_the_sources_the_catalog_DOES_preserve(self):
        self.assertEqual("gas", self._elect("NaturalGas"))
        self.assertEqual("electric", self._elect("Electricity"))

    def test_an_ELECTRIC_group_elects_cleanly_without_the_fallback_warning(self):
        """Disabling the electricity branch still returns 'electric', because
        the final fallback does too — so the returned value alone cannot tell
        the two apart. What distinguishes them is the fallback's warning,
        which says no energy type was DETECTED. A mutation that survives on
        the return value is caught here."""
        from btap.codes.necb.hvac import reference

        audit = self._audit()
        energy, _curve = reference._reference_energy_type(
            self._group(("Electricity",)), self._selection(),
            self._facts(), audit)
        self.assertEqual("electric", energy)
        detected = [e for e in audit.entries
                    if "no proposed heating energy type detected"
                    in str(e.get("action"))]
        self.assertEqual(
            [], detected,
            "an Electricity-only group is DETECTED, so the fallback warning "
            "must not fire; if it does, the election branch is not running")

    def test_the_coverage_discloses_the_collapse_rather_than_claiming_identity(self):
        """The claim and the behaviour must agree, in BOTH editions."""
        import json
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2]
        for ed, a9 in (("necb2020", "8.4.4.9"), ("necb2025", "8.4.5.9")):
            d = json.loads((root / "btap" / "codes" / "necb" / "data" / ed
                            / "reference_rules.json").read_text(encoding="utf-8"))
            entry = next(a for a in d["article_coverage"]["articles"]
                         if str(a.get("article")) == f"{a9}.(4)")
            self.assertEqual("partial", entry["status"],
                             f"{ed}: (4) cannot be `implemented` while oil "
                             f"and propane collapse to gas")
            self.assertIn("PropaneGas", entry["gaps"])
            self.assertIn("FuelOilNo2", entry["gaps"])


@needs_sdk
class TestAnOILProposedBuildingsFinalREFERENCEFuel(unittest.TestCase):
    """The selection elects `gas` for oil, and so does the FINAL reference
    plant — now that replacement is phase-ordered.

    Sol's `125`.1 established BOTH outcomes, adopted and replaced, and this
    class pinned both. His `141` withdraws the adopted one for an
    `action == "build"` assignment: it existed only because teardown ran
    per assignment, so a plant shared by several blocks stayed non-empty long
    enough for the next block's builder to find and reuse it. "Do not preserve
    the newly observed adoption. It is caused by mutation order, not by a Code
    requirement" — and "`copy_proposed` is an explicit retention branch; a
    surviving plant discovered during mutation is not."

    Measured both ways after the fix: the zonal-baseboard fixture and the PSZ
    fixture now each give two NaturalGas boilers and zero proposed markers.
    Explicit retention still exists — that is `copy_proposed`, which the
    teardown closure excludes by construction.

    Reproduced here so the claim is a measurement rather than an inference
    from the selector. This is the twelfth overclaim on this branch: my fix
    for the eleventh wrote "a proposed oil system becomes a GAS reference",
    which is the selector's answer presented as the reference's — and it has
    become true of the final plant for a different reason than I wrote it.
    """

    MARKER = "PROPOSED MARKER"

    def _oil_reference(self, system):
        from btap.audit import AuditLog
        from btap.codes.necb import hvac

        from .support import proposed_with_hvac

        proposed = proposed_with_hvac(system)
        boilers = list(proposed.getBoilerHotWaters())
        self.assertTrue(boilers, "this fixture must have a proposed boiler")
        for index, boiler in enumerate(boilers):
            boiler.setFuelType("FuelOilNo2")
            boiler.setName("{} {}".format(self.MARKER, index))
        reference = hvac.reference_hvac(
            proposed, code="necb2020", building={"storeys": 1},
            audit=AuditLog()).model
        built = list(reference.getBoilerHotWaters())
        return ({b.fuelType() for b in built},
                sum(1 for b in built if self.MARKER in b.nameString()))

    def test_a_ZONAL_proposed_plant_is_REPLACED_not_adopted(self):
        """The outcome `125`.1 recorded as adoption, re-measured under
        phase-ordered replacement (`141`).

        A zonal baseboard proposed plant used to survive into the reference
        because its five single-zone assignments tore down one at a time and
        the loop never emptied. It is replaced now, like every other
        `action == "build"` plant, and the result no longer depends on which
        block is processed first."""
        fuels, kept = self._oil_reference("Baseboard gas boiler")
        self.assertEqual(0, kept,
                         "a build-action plant is replaced; adoption via "
                         "sequential teardown is the artifact `141` removed")
        self.assertEqual({"NaturalGas"}, fuels)

    def test_the_outcome_does_not_depend_on_BLOCK_ORDER(self):
        """Sol's gate 2: "Reversing a list of block assignments cannot be
        allowed to change the reference plant's fuel, equipment, or
        provenance." Block assignments follow the group's zone order, so
        reversing the proposed zones reverses them."""
        from btap.audit import AuditLog
        from btap.codes.necb import hvac

        from .support import proposed_with_hvac

        seen = []
        for reverse in (False, True):
            proposed = proposed_with_hvac("Baseboard gas boiler")
            for index, boiler in enumerate(proposed.getBoilerHotWaters()):
                boiler.setFuelType("FuelOilNo2")
                boiler.setName("{} {}".format(self.MARKER, index))
            if reverse:
                # Rename the zones so sorted order inverts, which inverts the
                # order blocks are selected and built in.
                zones = list(proposed.getThermalZones())
                for index, zone in enumerate(zones):
                    zone.setName("ZZ Reordered {}".format(len(zones) - index))
            reference = hvac.reference_hvac(
                proposed, code="necb2020", building={"storeys": 1},
                audit=AuditLog()).model
            built = list(reference.getBoilerHotWaters())
            seen.append((sorted({b.fuelType() for b in built}),
                         sum(1 for b in built if self.MARKER in b.nameString()),
                         len(built)))
        self.assertEqual(seen[0], seen[1],
                         "the reference plant's fuel, provenance and count "
                         "must not depend on block order: {}".format(seen))

    def test_a_REPLACED_plant_carries_NaturalGas_from_the_same_election(self):
        """The opposite outcome from the same `gas` election, which is why the
        election cannot stand in for the final fuel."""
        fuels, kept = self._oil_reference(
            "PSZ RTU Electric and DX Coils and Hot Water Baseboard")
        self.assertEqual(0, kept, "the plant is replaced, so no marker remains")
        self.assertEqual({"NaturalGas"}, fuels)


class TestAHJ5TheSourceLoopBoilerCountsAsAnEnergyType(_Fixture):
    """AHJ-5, ruled by Sol's `126`: a water-loop heat-pump group's heating
    SERVICE SET includes its source-loop boiler's fuel.

    Until that ruling this entry said NOTHING fires for the shape, and called
    it a hole. The group's own `heating_energy_types` carries only the
    compressor fuel, so the predicate saw one energy type and never
    disclosed (5). Sol: "classifying only the group-local compressor fuel and
    ignoring the source-loop heat is a predicate defect."
    """

    def _wshp(self, loop_fuels=("NaturalGas",), loop_name="Heat Pump Loop"):
        """An electric water-loop heat-pump group whose source loop burns
        `loop_fuels`, in the `facts` shape `classify` produces."""
        group = self._group(("Electricity",))
        group["heat_pump"] = True
        group["heat_pump_sources"] = ["water_loop"]
        group["heat_pump_source_loops"] = [loop_name]
        return {
            "zone_groups": [group],
            "plants": [{"name": loop_name, "type": "condenser",
                        "fuels": list(loop_fuels), "purchased": False,
                        "heat_pump": True, "hp_source_loop": True}],
            "purchased_energy": {"heating": False, "cooling": False},
        }

    def test_the_service_set_carries_BOTH_energy_types(self):
        from btap.codes.necb.hvac import reference

        facts = self._wshp()
        fuels, added = reference.service_set_heating_fuels(
            facts["zone_groups"][0], facts)
        self.assertEqual({"Electricity", "NaturalGas"}, fuels)
        self.assertEqual({"NaturalGas"}, added,
                         "the gas comes from the SOURCE LOOP, not the group")

    def test_the_group_is_now_a_multi_energy_serving_group(self):
        """The behaviour change. Before the ruling this returned nothing."""
        from btap.codes.necb.hvac import reference

        facts = self._wshp()
        self.assertEqual(
            1, len(reference.multi_energy_serving_groups(facts)),
            "an active fuel-fired source-loop boiler is a second energy type")

    def test_an_ELECTRIC_source_loop_is_still_single_energy(self):
        """The control. If everything fired, the test above would prove
        nothing — the predicate must still say no when there is one fuel."""
        from btap.codes.necb.hvac import reference

        facts = self._wshp(loop_fuels=("Electricity",))
        self.assertEqual([], reference.multi_energy_serving_groups(facts))

    def test_a_group_with_NO_source_loop_is_unaffected(self):
        """The second control: the ordinary path must not acquire fuels."""
        from btap.codes.necb.hvac import reference

        facts = self._wshp()
        facts["zone_groups"][0]["heat_pump_source_loops"] = []
        fuels, added = reference.service_set_heating_fuels(
            facts["zone_groups"][0], facts)
        self.assertEqual({"Electricity"}, fuels)
        self.assertEqual(set(), added)

    def test_a_loop_whose_name_does_not_match_adds_nothing(self):
        """Guards the join. If the name lookup silently missed, every test
        above would pass for a group that happens to be multi-fuel anyway."""
        from btap.codes.necb.hvac import reference

        facts = self._wshp()
        facts["plants"][0]["name"] = "Some Other Loop"
        fuels, added = reference.service_set_heating_fuels(
            facts["zone_groups"][0], facts)
        self.assertEqual({"Electricity"}, fuels)
        self.assertEqual(set(), added)

    def test_the_8_4_2_2_5_backup_exclusion_is_NOT_detected(self):
        """Stated as a limitation rather than implied. A genuinely redundant
        source with mutually exclusive controls MAY be excluded, nothing here
        inspects control schemes, and so a standby boiler is OVER-disclosed.
        That direction is deliberate: it over-reports a question rather than
        hiding one."""
        from btap.codes.necb.hvac import reference

        doc = reference.service_set_heating_fuels.__doc__ or ""
        self.assertIn("8.4.2.2.(5) exclusion is NOT detected", doc)
        self.assertIn("OVER-disclosed", doc)


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
        warned = allocation_records(audit)
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
        warned = allocation_records(audit)
        self.assertEqual(1, len(warned))
        self.assertEqual("8.4.5.9.(5); 8.4.5.9.(6)", warned[0]["article"])
        # The plant record cites the (6) sentence alone, in the same edition.
        self.assertEqual(["8.4.5.9.(6)"],
                         [e["article"] for e in plant_records(audit)])
        self.assertNotIn("8.4.4.", warned[0]["action"],
                         "a 2025 run must not cite a 2020 article to the AHJ")


if __name__ == "__main__":
    unittest.main(verbosity=2)
