"""Each wired referral cites on its OWN branch, and not on its exclusions.

Sol's `127` guards 3 and 4. The positive case proves the deciding entry carries
the id, its target and its article; the BOUNDARY NEGATIVE proves the excluded
branch carries nothing. The negatives matter as much as the positives: the
whole risk of site-owned applicability is a broad "this function ran" tag that
over-discloses, and `126` narrowed most of these questions precisely because
the unnarrowed version would have fired on cases the Code settles.
"""

from __future__ import annotations

import re
import unittest

from .support import needs_sdk


def _citations(audit, ident):
    """Entries whose `ahj` field cites `ident`."""
    return [e for e in audit.entries
            if ident in str(e.get("ahj") or "").split()]


class TestAHJ11SystemFiveHeatingPresence(unittest.TestCase):
    """AHJ-11: Sentence (5) requires identical heating presence while Table -B's
    System 5 cell says "None".

    The positive branch is the tool KEEPING heating on a heated proposed block.
    The exclusion is an UNHEATED block, where honouring the table's "None" is
    text-consistent and raises no question at all.
    """

    def _assignment(self, heated, code="necb2020"):
        """Driven through `_finalize`, the real call site.

        Not through an extracted helper: four bugs on this branch have survived
        helper-only tests before, because a helper can be correct while nothing
        calls it. `_finalize` is where the System-5 presence decision actually
        happens.
        """
        from btap.audit import AuditLog
        from btap.codes import resolve
        from btap.codes.necb.hvac import reference

        audit = AuditLog()
        group = {"zones": ["Zone 7"], "heated": heated, "cooled": True,
                 "heating_energy_types": ["NaturalGas"] if heated else [],
                 "heat_pump_source_loops": [], "heat_pump": False,
                 "heat_pump_sources": [], "terminal_type": "none",
                 "zonal_units": [], "design_cooling_kw": 10.0,
                 "cooling_energy_types": ["Electricity"],
                 "air_loop": "AirLoop 7", "family": "fan_coils",
                 "loop_dx_cooling": False}

        # The REAL dataclass, not a stand-in: a hand-rolled object grows
        # whatever attributes the code happens to touch, so it drifts toward
        # the implementation's assumptions and stops catching shape errors.
        assignment = reference.Assignment(
            zones=list(group["zones"]), category="fan_coils",
            reference_system=5, catalog_name=None,
            config={"heating": "hot_water", "needs_boiler": True},
            energy_type=None, action="build")

        ruleset = resolve(code)
        rules_data = ruleset.rules("hvac")
        selection = rules_data["selection"]
        facts = {"zone_groups": [group], "plants": [],
                 "purchased_energy": {"heating": False, "cooling": False}}
        reference._finalize(assignment, group,
                            rules_data["system_definitions"], selection,
                            facts, audit, hp_rules=rules_data[
                                "heat_pump_reference"],
                            ruleset=ruleset, disclosed=set())
        return assignment, audit

    def test_a_HEATED_block_cites_AHJ_11(self):
        _assignment, audit = self._assignment(heated=True)
        cited = _citations(audit, "AHJ-11")
        self.assertEqual(1, len(cited), audit.entries)
        entry = cited[0]
        self.assertEqual("Zone 7", entry["target"])
        self.assertIn("8.4.4.1.(5)", entry["article"])
        self.assertEqual("D-39", entry["ruling"],
                         "the project reading travels beside the referral")

    def test_the_citation_names_THIS_edition_s_articles(self):
        """These were hardcoded to 2020's numbering, so a necb2025 run told an
        authority its condition came from 8.4.4.1.(5) and Table 8.4.4.7.-B —
        the OTHER edition's articles (Sol, `129`.5). The same article number
        naming a different requirement per edition is the collision the
        repository contract warns about, and it had reached product output.
        """
        for code, own, foreign in (("necb2020", "8.4.4", "8.4.5"),
                                   ("necb2025", "8.4.5", "8.4.4")):
            with self.subTest(code):
                _a, audit = self._assignment(heated=True, code=code)
                article = _citations(audit, "AHJ-11")[0]["article"]
                self.assertIn(f"{own}.1.(5)", article)
                self.assertIn(f"Table {own}.7.-B", article)
                self.assertNotIn(foreign, article,
                                 "no other edition's numbering may appear")

    def test_the_prose_says_heating_is_BUILT_not_merely_kept(self):
        """D-39's wording said "the existing two-pipe changeover heating is
        kept" and "no system invented". Both false: the tool constructs a
        hot-water loop, a boiler and heating coils inside a FOUR-PIPE fan-coil
        surrogate (Sol, `129`.4). An authority told that nothing was invented
        would be misled about what it is approving."""
        _a, audit = self._assignment(heated=True)
        action = _citations(audit, "AHJ-11")[0]["action"]
        self.assertIn("BUILT", action)
        self.assertIn("does not select the topology", action)
        for false_claim in ("existing two-pipe changeover heating is kept",
                            "no system invented"):
            self.assertNotIn(false_claim, action)

    def test_an_UNHEATED_block_cites_NOTHING(self):
        """The boundary negative. Honouring the table on an unheated block is
        what the text says, so there is no question to refer."""
        _assignment, audit = self._assignment(heated=False)
        self.assertEqual([], _citations(audit, "AHJ-11"),
                         "an unheated System 5 reference is text-consistent")
        self.assertEqual(
            [], [e for e in audit.entries if e.get("ahj")],
            "and it raises no other register question either")

    def test_the_unheated_branch_still_DID_something(self):
        """Guards the negative: if the helper had simply not run, the test
        above would pass for the wrong reason."""
        assignment, audit = self._assignment(heated=False)
        self.assertEqual("none", assignment.config["heating"])
        self.assertFalse(assignment.config["needs_boiler"])
        self.assertTrue(audit.entries, "the decision is still recorded")


class TestAHJ14BoilerPartLoadClass(unittest.TestCase):
    """AHJ-14: which part-load class an ordinary fuel-fired boiler takes.

    Sol's `126` narrowed it to equipment for which NO provision elects a class.
    Tested at the narrowing itself rather than through a built boiler, because
    the question is exactly "where did this class come from" and that is the
    helper's whole input. The citation's presence AT the efficiency entry is
    held by the AST gate in `test_ahj_citations.py`.
    """

    def _ahj(self, klass, source):
        from btap.codes.necb.hvac import efficiency

        return efficiency._boiler_class_ahj(klass, source)

    def test_a_ROW_DEFAULT_combustion_class_cites_AHJ_14(self):
        for klass in ("non_condensing", "atmospheric", "condensing"):
            with self.subTest(klass):
                self.assertEqual("AHJ-14", self._ahj(klass, "row"))

    def test_a_class_ELECTED_BY_A_PROVISION_cites_nothing(self):
        """A purchased boiler is explicitly modulating under Article 6, so the
        Code decided it and there is nothing to refer."""
        for klass in ("non_condensing", "condensing", "modulating"):
            with self.subTest(klass):
                self.assertIsNone(self._ahj(klass, "reference selection"))

    def test_the_MODULATING_class_cites_nothing(self):
        """What the Code names above 352 kW. A row carrying it was decided by
        the Code; applying a NON-modulating class up there would be a tool
        defect, not this referral."""
        self.assertIsNone(self._ahj("modulating", "row"))

    def test_NOT_APPLICABLE_cites_nothing(self):
        """No combustion part-load factor to classify — electric among it."""
        self.assertIsNone(self._ahj("not_applicable", "row"))

    def test_an_unknown_class_cites_nothing(self):
        """Fail closed: an unrecognised class is a data error, and inventing a
        referral for it would dress a defect as an interpretation."""
        self.assertIsNone(self._ahj("something_new", "row"))

    def test_the_vocabulary_this_narrowing_relies_on_still_exists(self):
        """Guards every negative above. If `PART_LOAD_CLASSES` were renamed,
        the exclusions would silently stop matching and the narrowing would
        quietly admit everything or nothing."""
        from btap.codes.necb.hvac import efficiency

        self.assertEqual(
            ("non_condensing", "atmospheric", "condensing", "modulating",
             "not_applicable"),
            efficiency.PART_LOAD_CLASSES)


@needs_sdk
class TestAHJ14OnRealBoilerPlants(unittest.TestCase):
    """Sol's `128` found three defects my helper-only tests could not see.

    They called `_boiler_class_ahj` directly, which proved the narrowing's
    logic and nothing about whether a real boiler ever reaches it with the
    right inputs. A 400 kW boiler was taking the row's `non_condensing` class —
    a MODELLING defect, not just a citation one — because the Code's election
    at (6)(d) had never been applied to the class at all.
    """

    def _plant(self, watts, names=("Primary Boiler", "Secondary Boiler")):
        import openstudio

        from btap.audit import AuditLog
        from btap.codes.necb import hvac

        model = openstudio.model.Model()
        loop = openstudio.model.PlantLoop(model)
        loop.setName("Hot Water Loop")
        loop.sizingPlant().setLoopType("Heating")
        for name in names:
            boiler = openstudio.model.BoilerHotWater(model)
            boiler.setName(name)
            boiler.setFuelType("NaturalGas")
            boiler.setNominalCapacity(watts)
            loop.addSupplyBranchForComponent(boiler)
        audit = AuditLog()
        hvac.apply_efficiencies(model, code="necb2020", audit=audit)
        return audit

    @staticmethod
    def _cited(audit):
        return [(str(e.get("target")), (e.get("inputs") or {}).get("capacity_kw"))
                for e in audit.entries
                if "AHJ-14" in str(e.get("ahj") or "").split()]

    @staticmethod
    def _classes(audit):
        return {str(e.get("target")): ((e.get("inputs") or {}).get(
                    "part_load_curve_class"),
                    (e.get("inputs") or {}).get("class_source"))
                for e in audit.entries
                if (e.get("inputs") or {}).get("part_load_curve_class")
                and "boiler" in str(e.get("action"))}

    def test_above_352_kW_the_CODE_elects_modulating(self):
        """The modelling fix. (6)(d) names a modulating boiler up here, and the
        class resolution was reading the unchanged catalogue row."""
        classes = self._classes(self._plant(400_000.0))
        self.assertEqual(("modulating", "reference selection"),
                         classes["Primary Boiler"])

    def test_above_352_kW_raises_NO_referral(self):
        """A class the Code elected is not an unresolved local default."""
        self.assertEqual([], self._cited(self._plant(400_000.0)))

    def test_an_ORDINARY_boiler_raises_the_referral_on_the_ACTIVE_one_only(self):
        """52 kW: (6)(b) wants ONE single-stage boiler, so the second object is
        stood down to 0.001 W and is an implementation device, not a second
        normative question."""
        cited = self._cited(self._plant(52_000.0))
        self.assertEqual([("Primary Boiler", 52.0)], cited)

    def test_the_176_to_352_band_names_BOTH_active_boilers(self):
        """Two equal active boilers are two live choices, which is why the
        suppression test above cannot simply assert "one condition"."""
        cited = self._cited(self._plant(250_000.0))
        self.assertEqual([("Primary Boiler", 125.0),
                          ("Secondary Boiler", 125.0)], cited)

    def test_crossing_DOWN_out_of_the_band_clears_the_forced_class(self):
        """A stale forced class would outlive the band that justified it: one
        pass reads the proposed's sizing, the next the reference's."""
        import openstudio

        from btap.audit import AuditLog
        from btap.codes.necb import hvac
        from btap.codes.necb.hvac import efficiency

        model = openstudio.model.Model()
        loop = openstudio.model.PlantLoop(model)
        loop.setName("Hot Water Loop")
        loop.sizingPlant().setLoopType("Heating")
        boiler = openstudio.model.BoilerHotWater(model)
        boiler.setName("Primary Boiler")
        boiler.setFuelType("NaturalGas")
        boiler.setNominalCapacity(400_000.0)
        loop.addSupplyBranchForComponent(boiler)
        hvac.apply_efficiencies(model, code="necb2020", audit=AuditLog())
        self.assertTrue(efficiency._forced_modulating(boiler),
                        "the 400 kW pass must have stamped it")

        boiler.setNominalCapacity(52_000.0)
        hvac.apply_efficiencies(model, code="necb2020", audit=AuditLog())
        self.assertFalse(
            efficiency._forced_modulating(boiler),
            "falling below the band must clear the class the band forced")


class TestAHJ14DoesNotMultiplyAcrossPASSES(unittest.TestCase):
    """Sol's `128`.3: the full-year baseline showed FOUR conditions where there
    was one live choice, because the efficiency pass runs twice."""

    def test_two_passes_over_one_boiler_are_ONE_condition(self):
        from btap.audit import AuditLog
        from btap.codes.necb import path as necb_path

        class _Run:
            pass

        run = _Run()
        run.report = {"annual": True, "code": "necb2020"}
        run.ruleset = type("_R", (), {"code": "necb2020"})()
        audit = AuditLog()
        for _pass in (1, 2):
            for name in ("Primary Boiler", "Secondary Boiler"):
                audit.decision("efficiency", "boiler efficiency applied",
                               target=name, article="8.4.5.2.", ahj="AHJ-14")
        necb_path._resolve_ahj_conditions(run, audit)

        self.assertEqual(
            4, sum(1 for e in audit.entries if e.get("ahj")),
            "the audit history is KEPT — only the derived set collapses")
        reason = run.report["compliance_determination_reason"]
        self.assertEqual(
            [("AHJ-14", "Primary Boiler"), ("AHJ-14", "Secondary Boiler")],
            [(c["id"], c["target"]) for c in reason["conditions"]])
        self.assertEqual([("AHJ-14", 2)],
                         [(e["id"], e["count"])
                          for e in run.report["ahj_applied"]])
        # ONE approval line, because the banner is once per id — the two
        # boilers are listed inside it (Sol's `128`.3). The conditions above
        # still record both, which is the distinction.
        self.assertEqual(1, len(reason["ahj_must_approve"]))
        self.assertIn("Primary Boiler", reason["ahj_must_approve"][0])
        self.assertIn("Secondary Boiler", reason["ahj_must_approve"][0])


class TestAHJ15DispatchPriority(unittest.TestCase):
    """AHJ-15: whether 8.4.x.9.(3) governs dispatch PRIORITY at all.

    Sol's `126` narrowed it to the case where Article 9.(5)(b) does NOT already
    prescribe the proposed multi-energy priority — where it does, the priority
    is carried over rather than chosen by us, and there is nothing to refer.
    `127` adds that a zero-capacity component is not a second competing path.

    Tested at the narrowing, because the (5)(b) fact is CARRIED IN from the
    selection: the dispatch site knows the final topology but not the proposed
    group's energy types, and rediscovering them there would rebuild the
    duplicated predicate D-100 removed.
    """

    def _ahj(self, prescribed, ordered=("Zone 1",), zeroed=()):
        from btap.codes.necb.hvac import reference

        return reference._dispatch_ahj(prescribed, list(ordered), list(zeroed))

    def test_a_chosen_priority_cites_AHJ_15(self):
        self.assertEqual("AHJ-15", self._ahj(False))

    def test_a_priority_PRESCRIBED_by_5b_cites_nothing(self):
        """A multi-energy service set carries its proposed priority over, so
        the tool is not choosing and there is no question to refer."""
        self.assertIsNone(self._ahj(True))

    def test_a_zone_whose_baseboard_is_ZERO_capacity_cites_nothing(self):
        """Not a second path competing for the load."""
        self.assertIsNone(self._ahj(False, ordered=("Zone 1",),
                                    zeroed=("Zone 1",)))

    def test_a_MIX_still_cites_for_the_live_zones(self):
        """One zeroed zone must not suppress the question for a zone where both
        components really do compete."""
        self.assertEqual("AHJ-15",
                         self._ahj(False, ordered=("Zone 1", "Zone 2"),
                                   zeroed=("Zone 1",)))

    def test_NO_in_scope_zone_cites_nothing(self):
        """The dispatch pass runs on System 3/4 and finds nothing to order."""
        self.assertIsNone(self._ahj(False, ordered=()))

    def test_a_VISIBLY_zero_baseboard_is_detected_and_unknown_is_not(self):
        """`_visibly_zero_capacity` must treat UNKNOWN as present. An autosized
        component has no capacity before sizing, and reading that as zero would
        silently drop AHJ-15 on the ordinary unsized path — under-disclosing,
        which is the direction that hides things."""
        import openstudio

        from btap.codes.necb.hvac import reference

        model = openstudio.model.Model()
        zeroed = openstudio.model.ZoneHVACBaseboardConvectiveElectric(model)
        zeroed.setNominalCapacity(0.0)
        self.assertTrue(reference._visibly_zero_capacity(zeroed))

        autosized = openstudio.model.ZoneHVACBaseboardConvectiveElectric(model)
        autosized.autosizeNominalCapacity()
        self.assertFalse(reference._visibly_zero_capacity(autosized),
                         "unknown is not zero")

        real = openstudio.model.ZoneHVACBaseboardConvectiveElectric(model)
        real.setNominalCapacity(1500.0)
        self.assertFalse(reference._visibly_zero_capacity(real))


class TestAHJ12HumidificationPresence(unittest.TestCase):
    """AHJ-12: whether reference humidification is PRESENT at all.

    Sol's `126` reframed it: Note (1) clearly governs the energy SOURCE once
    humidification exists, and the live question is the Code's silence on
    presence. `127` places the citation on the FINAL per-system outcome —
    rebuilt, deliberately omitted, or impossible to rebuild — and excludes a
    reference topology whose identity independently settles it.

    Tested by reading the citation sites in the humidification path, because
    each branch is one line of a single function and the AST gate already
    proves the ids resolve. The exclusion is the point: four outcomes cite and
    the fifth must not.
    """

    def _segment(self):
        import pathlib as _pathlib

        from btap.codes.necb.hvac import reference

        source = _pathlib.Path(reference.__file__).read_text(encoding="utf-8")
        return source[source.index("def _rebuild_humidification"):
                      source.index("def _elect_humidifier_kind")]

    def test_the_four_PRESENCE_CHOICE_outcomes_cite_AHJ_12(self):
        """Rebuilt on a replaced topology, omitted for want of a carrying
        loop, refused by the SDK, and inert for want of humidity control."""
        self.assertEqual(4, self._segment().count("ahj='AHJ-12'"))

    def test_the_RETAINED_branch_cites_nothing(self):
        """The boundary negative. Where the reference kept the proposed loop,
        its identity settles presence and no choice was made."""
        segment = self._segment()
        marker = "retained on this reference loop"
        self.assertIn(marker, segment, "the retained branch still exists")
        after = segment.split(marker, 1)[1].split("continue", 1)[0]
        self.assertNotIn("ahj", after,
                         "a topology that settles presence raises no question")

    def test_the_exclusion_is_explained_where_it_is_made(self):
        """A missing citation looks identical to a forgotten one, so the
        reason has to sit at the site — this is the failure mode the
        site-owned design trades for removing a duplicated predicate."""
        segment = self._segment()
        self.assertIn("NO AHJ-12 here", segment)
        self.assertIn("independently", segment)


class TestAHJ2TheAnnualEnergyBasis(unittest.TestCase):
    """AHJ-2: what basis 8.4.x.13.(2)(g) compares.

    Sol's `126` narrowed this hard. Article 13 and Article 9 operate
    CONCURRENTLY — 13.(2)(f) bases capacity on the peak load *and* the
    requirements of the other subsections, and Article 13 nowhere says Article 9
    stops applying — so the referral is not "which article wins". What remains
    live is the undefined ANNUAL-ENERGY BASIS: (2)(g) says "largest annual
    energy use" and a 33% share without saying whether the comparison is
    source/input energy or delivered heat, and Division A defines consumption
    only at the whole-building aggregate.

    `127` places the citation where that comparison is actually MADE, and
    excludes the two branches where it is not.
    """

    HP_RULES = {"aux_energy_type_threshold_fraction": 0.33}

    def _elect(self, annual):
        from btap.audit import AuditLog
        from btap.codes.necb.hvac import reference

        group = {"zones": ["Zone 1"], "air_loop": "AirLoop 1",
                 "heating_energy_types": ["Electricity"],
                 "heat_pump": True, "heat_pump_sources": ["air"],
                 "heat_pump_source_loops": []}
        facts = {"zone_groups": [group], "plants": [],
                 "purchased_energy": {"heating": False, "cooling": False}}
        audit = AuditLog()
        reference.heat_pump_aux_energy_type(
            group, facts, self.HP_RULES, annual, audit)
        return audit

    @staticmethod
    def _cited(audit):
        return [e for e in audit.entries
                if "AHJ-2" in str(e.get("ahj") or "").split()]

    def test_the_33_percent_comparison_cites_AHJ_2(self):
        """Real annual data, heat-pump share BELOW the proviso: the comparison
        was made, so its basis is the live question."""
        audit = self._elect({
            "loops": {"AirLoop 1": {"hp_j": 10e9,
                                    "aux": [{"fuel": "NaturalGas", "j": 90e9}]}},
            "zones": {}})
        cited = self._cited(audit)
        self.assertEqual(1, len(cited), [e.get("action") for e in audit.entries])
        self.assertIn("8.4.4.13.(2)", cited[0]["article"])
        self.assertEqual("D-52", cited[0]["ruling"])

    def test_the_largest_aux_ELECTION_cites_AHJ_2(self):
        """Share ABOVE the proviso, so (2)(g) elects the largest annual
        auxiliary energy type — the same undefined basis, used the other way."""
        audit = self._elect({
            "loops": {"AirLoop 1": {"hp_j": 90e9,
                                    "aux": [{"fuel": "NaturalGas", "j": 10e9}]}},
            "zones": {}})
        self.assertEqual(1, len(self._cited(audit)),
                         [e.get("action") for e in audit.entries])

    def test_NO_annual_data_cites_nothing(self):
        """The boundary negative that matters most. A `none` or `sizing` run has
        no annual data, and that is a MODE limitation — not a question an
        authority can settle (Sol, `127`)."""
        audit = self._elect(None)
        self.assertEqual([], self._cited(audit))
        self.assertTrue(audit.entries, "but the absence is still recorded")

    def test_NO_auxiliary_energy_cites_nothing(self):
        """With nothing for the comparison to weigh, no basis question arises."""
        audit = self._elect({"loops": {"AirLoop 1": {"hp_j": 10e9, "aux": []}},
                             "zones": {}})
        self.assertEqual([], self._cited(audit))

    def test_both_exclusions_are_EXPLAINED_at_the_site(self):
        """Same reason as AHJ-12's: a missing citation looks identical to a
        forgotten one, so the silence has to be deliberate on its face."""
        import pathlib as _pathlib

        from btap.codes.necb.hvac import reference

        source = _pathlib.Path(reference.__file__).read_text(encoding="utf-8")
        segment = source[source.index("def heat_pump_aux_energy_type"):
                         source.index("def _election_scope")]
        self.assertEqual(2, segment.count("NO AHJ-2"))
        self.assertIn("MODE limitation", segment)


@needs_sdk
class TestAHJ10CornerBlockGrouping(unittest.TestCase):
    """AHJ-10: which facade a CORNER block is assigned to.

    The register used to claim this choice was audited. It was NOT — Sol's
    `127` traced the deciding code to `VAVReheat._dominant_orientation`, which
    has no audit object, and the later merge entry records neither the corner
    block's identity nor the elected facade.

    The fix is the metadata handoff Sol specified, and these tests check BOTH
    halves of it: that the generic builder records what it measured and
    elected, and that it learns nothing about NECB while doing so.
    """

    @staticmethod
    def _wall(space, points):
        import openstudio

        vertices = openstudio.Point3dVector()
        for x, y, z in points:
            vertices.append(openstudio.Point3d(x, y, z))
        surface = openstudio.model.Surface(vertices, space.model())
        surface.setSpace(space)
        surface.setSurfaceType("Wall")
        surface.setOutsideBoundaryCondition("Outdoors")
        return surface

    def _model_with_a_corner(self):
        """One zone with NORTH and EAST exterior walls, one with SOUTH only."""
        import openstudio

        model = openstudio.model.Model()
        made = []
        for name, walls in (
                ("Corner Block", [[(0, 10, 0), (10, 10, 0), (10, 10, 3), (0, 10, 3)],
                                  [(10, 10, 0), (10, 0, 0), (10, 0, 3), (10, 10, 3)]]),
                ("Single Facade Block", [[(10, 0, 0), (0, 0, 0), (0, 0, 3),
                                          (10, 0, 3)]])):
            space = openstudio.model.Space(model)
            space.setName(f"{name} Space")
            zone = openstudio.model.ThermalZone(model)
            zone.setName(name)
            space.setThermalZone(zone)
            for points in walls:
                self._wall(space, points)
            made.append(zone)
        return model, made

    def _evidence(self):
        from btap.modeling.geometry import helpers
        from btap.modeling.hvac.systems import vav_reheat

        model, zones = self._model_with_a_corner()
        builder = vav_reheat.VAVReheat({"sys_abbr": "sys6",
                                        "family": "vav_reheat"})
        real = helpers.above_ground_storeys
        # The facade split only runs ABOVE four storeys, which is itself one of
        # Sol's exclusions; this forces the branch under test.
        vav_reheat.helpers.above_ground_storeys = lambda _model: 5
        try:
            builder._zone_groups(model, zones)
        finally:
            vav_reheat.helpers.above_ground_storeys = real
        return builder.grouping_evidence

    def test_the_builder_records_what_it_MEASURED_and_ELECTED(self):
        """The COUNT of orientations is the property, not which ones. Which
        compass bin a wall lands in follows its vertex winding, and asserting a
        letter would pin my own winding assumption rather than the behaviour —
        the first version of this test did exactly that and failed on it."""
        evidence = {record["zone"]: record for record in self._evidence()}
        corner = evidence["Corner Block"]
        self.assertEqual(2, len(corner["facade_areas_m2"]),
                         f"two orientations carry wall area: {corner}")
        self.assertIn(corner["elected"], corner["facade_areas_m2"],
                      "the elected facade is one it actually has")
        self.assertIn("N/E/S/W", corner["tie_break"],
                      "the tie-break rule travels with the evidence")
        self.assertTrue(all(area > 0 for area
                            in corner["facade_areas_m2"].values()))

    def test_a_SINGLE_facade_block_is_not_a_corner(self):
        """The boundary negative: one orientation is unambiguous, so Note (3)
        decides it and no question arises."""
        evidence = {record["zone"]: record for record in self._evidence()}
        single = evidence["Single Facade Block"]
        self.assertEqual(1, len(single["facade_areas_m2"]),
                         f"one orientation only: {single}")
        self.assertEqual(single["elected"],
                         next(iter(single["facade_areas_m2"])))

    def test_the_GENERIC_builder_learns_no_NECB_ids(self):
        """The constraint that made this a handoff instead of a citation:
        `btap.modeling` is the code-family-neutral layer and may not carry NECB
        articles or register ids (Sol, `127`)."""
        import pathlib as _pathlib
        import re as _re

        from btap.modeling.hvac.systems import vav_reheat

        source = _pathlib.Path(vav_reheat.__file__).read_text(encoding="utf-8")
        self.assertEqual([], _re.findall(r"\bAHJ-\d+\b", source))
        self.assertNotIn("ahj=", source)
        self.assertIn("grouping_evidence", source,
                      "it records evidence, and nothing more")


@needs_sdk
class TestAHJ15IsComputedPerASSIGNMENT(unittest.TestCase):
    """Fable's `131` F1. The (5)(b) fact was read from `group`, which the
    assignment loop never binds — its only binding is the DCV capture loop far
    above — so EVERY assignment got whichever zone group iterated last.

    He reproduced both directions through the real build: four single-fuel
    System 3 zones lost the citation they are owed when a multi-fuel zonal
    group iterated last, and a multi-fuel zone carried AHJ-1 and AHJ-15
    together — the claim that its priority IS prescribed by (5)(b) and the
    claim that it is not — when it iterated first.

    The frozen corpus cannot see it: every sample carries one fuel set across
    all its zones, so the last group's flag happens to be every group's flag.
    """

    def _dispatch_calls(self, systems):
        """Every `_apply_zone_dispatch` call and the flag it received."""
        import btap.modeling as modeling
        from btap._compat import sorted_by_name
        from btap.audit import AuditLog
        from btap.codes.necb import hvac
        from btap.codes.necb.hvac import reference

        from .support import compliance_fixture

        seen = []
        real = reference._apply_zone_dispatch

        def spy(zones, system, code, audit, priority_prescribed=False):
            seen.append((tuple(z.nameString() for z in zones),
                         priority_prescribed))
            return real(zones, system, code, audit,
                        priority_prescribed=priority_prescribed)

        reference._apply_zone_dispatch = spy
        try:
            model = compliance_fixture()
            zones = sorted_by_name(model.getThermalZones())
            for name, slice_ in systems:
                modeling.build_system(model, name, zones[slice_])
            hvac.reference_hvac(model, code="necb2020",
                                building={"storeys": 1}, audit=AuditLog())
        finally:
            reference._apply_zone_dispatch = real
        return seen

    def test_assignments_with_DIFFERENT_fuel_sets_get_different_flags(self):
        """The property the stale variable destroyed. A multi-fuel group's
        priority IS prescribed by (5)(b); a single-fuel group's is not, and it
        is owed the citation."""
        calls = self._dispatch_calls([
            # gas coil + electric baseboard: multi-fuel, so (5)(b) prescribes
            ("PSZ RTU Gas and DX Coils and Electric Baseboard", slice(0, 3)),
            # electric only: single-fuel, so nothing prescribes the priority
            ("Baseboard electric", slice(3, None)),
        ])
        self.assertGreater(len(calls), 1, "more than one assignment is needed")
        flags = {flag for _zones, flag in calls}
        self.assertEqual(
            {True, False}, flags,
            "every assignment received the same flag, which is the stale-"
            "variable bug: {}".format(calls))

    def test_each_call_sees_its_OWN_zones(self):
        """Guards the spy: if the calls all carried the same zone set, the
        test above could pass while the flags were still shared."""
        calls = self._dispatch_calls([
            ("PSZ RTU Gas and DX Coils and Electric Baseboard", slice(0, 3)),
            ("Baseboard electric", slice(3, None)),
        ])
        zone_sets = {zones for zones, _flag in calls}
        self.assertEqual(len(calls), len(zone_sets),
                         "each assignment dispatches its own zones")


@needs_sdk
class TestASupersededConditionDoesNotSTAND(unittest.TestCase):
    """Fable's `131` F3. The condition set deduped by (id, target) keeping the
    last CITING entry — which is only right when the final pass cites.

    When the second pass re-made the same choice WITHOUT citing, because the
    Code had elected the class or the boiler was stood down, nothing overwrote
    the first-pass record. A 400 kW primary was presented to an authority as an
    unresolved local default while its own final audit entry said
    `modulating, reference selection`.

    Reachable because pass 1 reads the PROPOSED's sizing and pass 2 the
    REFERENCE's, so a plant near 176 or 352 kW crosses the band between them —
    D-90's own comment says so. The frozen scenario sits at 52 kW on both
    passes and cannot see it.
    """

    def _two_passes(self, first_w, second_w):
        import openstudio

        from btap.audit import AuditLog
        from btap.codes.necb import hvac
        from btap.codes.necb import path as necb_path

        model = openstudio.model.Model()
        loop = openstudio.model.PlantLoop(model)
        loop.setName("Hot Water Loop")
        loop.sizingPlant().setLoopType("Heating")
        for name in ("Primary Boiler", "Secondary Boiler"):
            boiler = openstudio.model.BoilerHotWater(model)
            boiler.setName(name)
            boiler.setFuelType("NaturalGas")
            boiler.setNominalCapacity(first_w)
            loop.addSupplyBranchForComponent(boiler)

        audit = AuditLog()
        hvac.apply_efficiencies(model, code="necb2020", audit=audit)
        for boiler in model.getBoilerHotWaters():
            boiler.setNominalCapacity(second_w)
        hvac.apply_efficiencies(model, code="necb2020", audit=audit)

        class _Run:
            pass

        run = _Run()
        run.report = {"annual": True, "code": "necb2020"}
        run.ruleset = type("_R", (), {"code": "necb2020"})()
        necb_path._resolve_ahj_conditions(run, audit)
        reason = run.report.get("compliance_determination_reason") or {}
        return (run.report.get("compliance_determination"),
                [(c["id"], c["target"]) for c in reason.get("conditions", [])])

    def test_crossing_UP_out_of_the_band_RETIRES_the_condition(self):
        """The defect. The Code elects `modulating` above 352 kW, so the
        question is answered and the first pass's citation must not survive."""
        determination, conditions = self._two_passes(250_000.0, 400_000.0)
        self.assertEqual([], conditions)
        self.assertEqual("code", determination)

    def test_crossing_DOWN_into_the_band_still_CITES(self):
        """The control that keeps the fix from being mere suppression."""
        determination, conditions = self._two_passes(400_000.0, 52_000.0)
        self.assertEqual([("AHJ-14", "Primary Boiler")], conditions)
        self.assertEqual("conditional", determination)

    def test_an_unchanged_ordinary_plant_still_cites_ONCE(self):
        determination, conditions = self._two_passes(52_000.0, 52_000.0)
        self.assertEqual([("AHJ-14", "Primary Boiler")], conditions)
        self.assertEqual("conditional", determination)

    def test_an_equal_ACTIVE_pair_still_names_BOTH(self):
        """Supersession must not collapse two live choices into one."""
        _determination, conditions = self._two_passes(250_000.0, 250_000.0)
        self.assertEqual([("AHJ-14", "Primary Boiler"),
                          ("AHJ-14", "Secondary Boiler")], conditions)


@needs_sdk
class TestTheStoreysOverrideReachesTheBUILDER(unittest.TestCase):
    """Fable's `131` F2. The two halves of the System 6 grouping disagreed.

    The selector reads `building['storeys']` — the `--storeys` override — while
    `VAVReheat` reads `helpers.above_ground_storeys(model)`, which falls back to
    a BuildingStory count and then to 1. Nothing wrote the override onto a
    model, so a building the selector had just classified as MORE than four
    storeys was GROUPED as one: one whole-building VAV, no facade split, no
    Note (3) corner assignment, no AHJ-10.

    The missing citation is the smaller half. `pipeline.py`'s own preflight
    warns that the fallback "would silently treat the building as ONE storey",
    and with the override supplied it did exactly that one layer down.
    """

    def _reference(self, declare_on_model, declared=6):
        import btap.modeling as modeling
        from btap._compat import sorted_by_name
        from btap.audit import AuditLog
        from btap.codes.necb import hvac

        from .support import compliance_fixture

        model = compliance_fixture()
        zones = sorted_by_name(model.getThermalZones())
        # A two-facade CORNER block: fold zone 3's spaces into zone 2.
        for space in list(zones[2].spaces()):
            space.setThermalZone(zones[1])
        modeling.build_system(
            model, "PSZ RTU Gas and DX Coils and Electric Baseboard",
            [z for z in model.getThermalZones() if z.spaces()])
        if declare_on_model:
            model.getBuilding().setStandardsNumberOfAboveGroundStories(6)
        elif declared != 6:
            # G4's shape: the model DECLARES a contradicting count.
            model.getBuilding().setStandardsNumberOfAboveGroundStories(declared)
        audit = AuditLog()
        result = hvac.reference_hvac(model, code="necb2020",
                                     building={"storeys": 6}, audit=audit)
        cited = [entry.get("target") for entry in audit.entries
                 if "AHJ-10" in str(entry.get("ahj") or "").split()]
        return model, result, cited

    def test_the_OVERRIDE_ALONE_reaches_the_facade_split(self):
        """Fable's failing case. Before the fix this produced one air loop and
        no citation."""
        _model, result, cited = self._reference(declare_on_model=False)
        self.assertTrue(cited, "the corner block must be cited")
        self.assertGreater(
            len(result.model.getAirLoopHVACs()), 1,
            "more than four storeys means a facade SPLIT, not one "
            "whole-building VAV")

    def test_a_DECLARED_count_behaves_identically(self):
        """The control: same model, same selection, same corner block."""
        _model, result, cited = self._reference(declare_on_model=True)
        self.assertTrue(cited)
        self.assertGreater(len(result.model.getAirLoopHVACs()), 1)

    def test_the_PROPOSED_model_is_not_edited(self):
        """The caller's model is not ours to change — the premise is stamped on
        the REFERENCE clone only."""
        from btap.modeling.geometry import helpers

        model, _result, _cited = self._reference(declare_on_model=False)
        self.assertEqual(1, helpers.above_ground_storeys(model),
                         "the proposed model keeps whatever it said")

    def test_the_override_WINS_over_a_declared_count_and_says_so(self):
        """Fable's `133` G4 reversed this. The first version skipped a model
        that declared its own count, calling it deference — and that
        reproduced F2 exactly: `declared=2, --storeys 6` selected on 6 and
        GROUPED on 2, one whole-building VAV, no citation, no audit entry.

        It was not deference. `_building_info` already lets the override win in
        the selector, so skipping the stamp just moved the split's roles
        around. Deference would mean refusing the override in the selector too.
        """
        import openstudio

        from btap.audit import AuditLog
        from btap.codes.necb.hvac import reference

        model = openstudio.model.Model()
        model.getBuilding().setStandardsNumberOfAboveGroundStories(3)
        audit = AuditLog()
        reference._reconcile_declared_storeys(model, {"storeys": 9}, audit)
        self.assertEqual(
            9, model.getBuilding().standardsNumberOfAboveGroundStories().get(),
            "the override wins in the builder as it does in the selector")
        warnings = [e for e in audit.entries if e.get("level") == "warning"]
        self.assertEqual(1, len(warnings),
                         "holding two storey counts silently breaks the audit "
                         "contract whichever number wins")
        self.assertIn(9, warnings[0]["inputs"].values())
        self.assertIn(3, warnings[0]["inputs"].values(),
                      "the warning must name BOTH numbers")

    def test_an_AGREEING_declared_count_warns_about_nothing(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.codes.necb.hvac import reference

        model = openstudio.model.Model()
        model.getBuilding().setStandardsNumberOfAboveGroundStories(4)
        audit = AuditLog()
        reference._reconcile_declared_storeys(model, {"storeys": 4}, audit)
        self.assertEqual([], [e for e in audit.entries
                              if e.get("level") == "warning"])

    def test_a_CONTRADICTED_count_still_reaches_the_facade_split(self):
        """G4's row 2, end to end: the symptom F2 fixed must not come back."""
        _model, result, cited = self._reference(declare_on_model=False,
                                                declared=2)
        self.assertTrue(cited, "the corner block is still cited")
        self.assertGreater(len(result.model.getAirLoopHVACs()), 1)


class TestTheReportAPPENDIXShowsEveryFiredDisposition(unittest.TestCase):
    """Sol's `127` guard 6, which Fable's `131` F7 found unmet: nothing in the
    report package read `ahj_applied`, so a `ruled` or `tool-gap` citation
    reached `report.json` and the audit text and went no further. The HTML
    report is the AHJ-facing artifact; a reader of it saw none of them.
    """

    def _appendix(self, entries):
        from btap.codes.report import sections

        return sections.ahj_appendix({"audit_entries": entries,
                                      "report": {}, "options": {}})

    def test_a_RULED_citation_is_shown_though_it_changes_no_verdict(self):
        """The non-conditional statuses are the POINT of the table. AHJ-5 fires
        15 times in the frozen corpus and had no reader-facing surface."""
        html = self._appendix([{"step": "selection", "ahj": "AHJ-5"}])
        self.assertIn("AHJ-5", html)
        self.assertIn("ruled", html)
        self.assertIn("settled", html)

    def test_a_TOOL_GAP_citation_is_shown_and_named_as_a_defect(self):
        html = self._appendix([{"step": "build", "ahj": "AHJ-18"}])
        self.assertIn("AHJ-18", html)
        self.assertIn("tool-gap", html)
        self.assertIn("defect in this tool", html)

    def test_an_APPROVAL_REQUIRED_citation_says_it_bears_on_the_verdict(self):
        html = self._appendix([{"step": "efficiency", "ahj": "AHJ-14"}])
        self.assertIn("AHJ-14", html)
        self.assertIn("YES", html)

    def test_the_appendix_COUNTS_repeated_applications(self):
        html = self._appendix([{"step": "a", "ahj": "AHJ-5"},
                               {"step": "b", "ahj": "AHJ-5"},
                               {"step": "c", "ahj": "AHJ-5"}])
        self.assertIn(">3<", html, "three applications are reported as three")

    def test_a_run_citing_NOTHING_says_so_rather_than_rendering_an_empty_table(self):
        html = self._appendix([{"step": "selection", "ruling": "D-52"}])
        self.assertIn("no referred or otherwise dispositioned", html)

    def test_the_appendix_is_IN_the_rendered_report(self):
        """The section function existing is not the same as it being rendered —
        F7 was precisely a renderer that never called it."""
        from btap.codes.report import sections

        self.assertIn("ahj_appendix", sections.ORDER)
        self.assertLess(sections.ORDER.index("ahj_appendix"),
                        sections.ORDER.index("audit_appendix"),
                        "the dispositions are read before the raw audit trail")


@needs_sdk
class TestEveryCitedArticleExistsInITSEdition(unittest.TestCase):
    """Fable's `133` G3 replaced my own gate, which rested on a false premise.

    The first version asserted that a necb2025 run cites no `8.4.4.x` article,
    "always wrong" in 2025. It is not: `8.4.4.1` and `8.4.4.2` ARE NECB 2025's
    archetype-EUI articles and every 2025 run cites them correctly from
    coverage. My gate passed only because its fixture never reached them, and
    moved to the pipeline it would have failed on TRUE citations. It also
    declined to check 2020 at all, on the correct observation that 2020
    legitimately cites 8.4.5.x curve tables — leaving that direction unguarded.

    Membership in the edition's OWN snapshot is the property that actually
    holds, in both directions: every Section 8.4 article a run cites must exist
    in `data/<code>/coverage/articles_8_4.json`. It needs no judgement about
    which subsection means what in which edition.
    """

    def _snapshot_articles(self, code):
        import json

        from btap.codes import necb

        path = (necb._data_root() / code / "coverage" / "articles_8_4.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        articles = data["articles"]
        return set(articles) if isinstance(articles, dict) else {
            str(entry) for entry in articles}

    #: A DELIBERATE cross-edition reference, e.g. `8.4.4.3./8.4.5.3.`. Prose
    #: that explains where a requirement lands in EITHER edition names both
    #: numbers on purpose, so one of them is always absent from the running
    #: edition's snapshot and is not a miscitation. NECB 2025's air-barrier
    #: coverage row says "the leakage RATE is applied to the model (see
    #: 8.4.2.9. and 8.4.4.3./8.4.5.3.)" — I filed that as a normative question
    #: for Sol and Fable's `135` H2 showed it is nothing of the kind.
    #:
    #: Only the PAIRED form is forgiven, and only when its partner IS in the
    #: snapshot. A lone foreign number still fails.
    PAIRED = re.compile(r"(8\.4\.\d+\.\d+)\.?/(8\.4\.\d+\.\d+)")

    def _cited_articles(self, entries):
        """Every `8.4.x.y` token in the fields that reach a reader, minus the
        half of a cross-edition pair that belongs to the other edition."""
        seen, paired = set(), set()
        for entry in entries:
            blob = " ".join(str(entry.get(field) or "") for field
                            in ("article", "action", "value", "evidence"))
            for left, right in self.PAIRED.findall(blob):
                paired.add((left, right))
            for token in re.findall(r"8\.4\.\d+\.\d+", blob):
                seen.add(token)
        return seen, paired

    def _foreign(self, entries, known):
        """Cited articles absent from `known`, forgiving a cross-edition pair
        whose OTHER half is present."""
        cited, paired = self._cited_articles(entries)
        forgiven = {other for left, right in paired
                    for one, other in ((left, right), (right, left))
                    if one in known and other not in known}
        return {a for a in cited if a not in known} - forgiven

    def _run(self, code):
        import btap.modeling as modeling
        from btap._compat import sorted_by_name
        from btap.audit import AuditLog
        from btap.codes.necb import hvac

        from .support import compliance_fixture

        system = ("MZ BU RTU Hot Water Heating Coil Scroll Chiller and "
                  "Hot Water Baseboard")
        model = compliance_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, system, zones[:3])
        modeling.build_system(model, system, zones[3:])
        audit = AuditLog()
        hvac.reference_hvac(model, code=code, building={"storeys": 6},
                            audit=audit)
        hvac.apply_efficiencies(model, code=code, audit=audit)
        hvac.apply_economizer_thresholds(model, audit=audit, code=code)
        return audit.entries

    @property
    def PENDING_SOL_136(self):
        """ONE list, owned by the frozen sweep.

        It lived here too until the sweep became a test of its own, and two
        copies of "known wrong, not fixed" is precisely the drift that list
        exists to prevent. The evidence and the referral live with it.
        """
        from tests.test_frozen_article_membership import PENDING_SOL_136

        return PENDING_SOL_136

    def test_both_editions_cite_only_their_own_articles(self):
        for code in ("necb2020", "necb2025"):
            with self.subTest(code):
                entries = self._run(code)
                self.assertGreater(len(entries), 40,
                                   "the run must be substantial")
                known = self._snapshot_articles(code)
                cited, _paired = self._cited_articles(entries)
                self.assertTrue(cited, "the probe must find citations at all")
                foreign = sorted(self._foreign(entries, known))
                self.assertEqual(
                    [], foreign,
                    "{} cited articles absent from its own snapshot: "
                    "{}".format(code, foreign))

    def test_the_full_pipeline_cites_only_its_own_articles(self):
        """The fixture above reaches the HVAC sites. This runs the REAL
        pipeline, which is where Fable's `133` G3 found five sites my first
        gate's fixture never touched — the frozen corpus saw them and the
        fixture did not.
        """
        import tempfile

        import btap.modeling as modeling
        from btap._compat import sorted_by_name
        from btap.codes import performance_compliance

        from .support import compliance_fixture

        for code in ("necb2020", "necb2025"):
            with self.subTest(code):
                model = compliance_fixture()
                modeling.build_system(
                    model, "PSZ RTU Gas and DX Coils and Electric Baseboard",
                    sorted_by_name(model.getThermalZones()))
                with tempfile.TemporaryDirectory() as run_dir:
                    result = performance_compliance(
                        model, code=code, simulate="none", run_dir=run_dir,
                        hdd=4000, building={"storeys": 1})
                known = self._snapshot_articles(code)
                foreign = self._foreign(result.audit.entries, known)
                unexpected = sorted(foreign - self.PENDING_SOL_136[code])
                self.assertEqual(
                    [], unexpected,
                    "{} cited articles absent from its own snapshot and not "
                    "among the declared normative referrals: {}".format(
                        code, unexpected))
                # And the declared ones must still BE there: if a referral is
                # settled the list must shrink deliberately, not silently.
                self.assertEqual(
                    self.PENDING_SOL_136[code], foreign & self.PENDING_SOL_136[code],
                    "a declared referral stopped firing; settle it in the list")

    def test_the_probe_has_TEETH(self):
        """Absence of output is not evidence. A deliberately foreign citation
        must be caught, or the test above proves nothing."""
        known = self._snapshot_articles("necb2025")
        foreign = sorted(self._foreign([
            {"article": "8.4.4.12.; 5.2.2.7.(1)"},          # G3's real one
            {"action": "the structural 8.4.4.9.(4) proxy"},  # G3's real one
        ], known))
        self.assertEqual(["8.4.4.12", "8.4.4.9"], foreign,
                         "the sweep must see a 2020 article on a 2025 snapshot")

    def test_a_cross_edition_PAIR_is_forgiven_but_a_lone_number_is_not(self):
        """H2's rule, both directions."""
        known = self._snapshot_articles("necb2025")
        self.assertEqual(
            set(), self._foreign([{"action": "see 8.4.2.9. and 8.4.4.3./8.4.5.3."}],
                                 known),
            "a pair whose other half is in the snapshot is deliberate")
        self.assertEqual(
            {"8.4.4.3"},
            self._foreign([{"action": "see 8.4.4.3. alone"}], known),
            "the same number ALONE is still a miscitation")

class TestNo2020ArticleReachesA2025Run(unittest.TestCase):
    """The class Sol's `129`.5 called a defect and Fable's `131` F6 found in
    four more places: a 2020 article number written as a LITERAL in action
    text, on a run whose `article=` field is correctly 2025.

    It reaches an authority. The resolver quotes the deciding entry's action
    verbatim as the condition `detail`, so a conditional 2025 run handed over a
    number that in NECB 2025 names the archetype-EUI subsection entirely.

    Checked by RUNNING both editions rather than scanning the source, because a
    computed citation can be wrong too and a literal in a docstring is
    harmless. The direction is deliberately one-way: NECB 2020 legitimately
    cites 8.4.5.x for its part-load curve tables (Sol's `128` quotes
    Table 8.4.5.2.-A for 2020 boilers), so a 2020 run carrying an 8.4.5 number
    proves nothing. A 2025 run carrying an 8.4.4 number is always wrong.
    """

    def test_no_entry_on_a_2025_run_cites_the_2020_subsection(self):
        import re

        import btap.modeling as modeling
        from btap._compat import sorted_by_name
        from btap.audit import AuditLog
        from btap.codes.necb import hvac

        from .support import compliance_fixture

        system = ("MZ BU RTU Hot Water Heating Coil Scroll Chiller and "
                  "Hot Water Baseboard")
        model = compliance_fixture()
        zones = sorted_by_name(model.getThermalZones())
        # Two multizone groups above four storeys, so the D-28 merge, the
        # Note (3) grouping and the humidification capture all fire.
        modeling.build_system(model, system, zones[:3])
        modeling.build_system(model, system, zones[3:])
        audit = AuditLog()
        hvac.reference_hvac(model, code="necb2025", building={"storeys": 6},
                            audit=audit)
        hvac.apply_efficiencies(model, code="necb2025", audit=audit)

        self.assertGreater(len(audit.entries), 40, "the run must be substantial")
        offenders = []
        for entry in audit.entries:
            blob = "{} {} {}".format(entry.get("action"), entry.get("article"),
                                     entry.get("value"))
            for hit in re.findall(r"8\.4\.4\.[0-9][0-9.\-A-B()]*", blob):
                offenders.append((hit, str(entry.get("action"))[:60]))
        self.assertEqual(
            [], offenders,
            "a necb2025 run cited the 2020 reference subsection: {}".format(
                offenders[:6]))


class TestTheCLICanReachAHJ11(unittest.TestCase):
    """Fable's `131` F9: `compliance_kwargs` built `building` from `--storeys`
    alone and no option offered refrigerated zones, so every CLI run took the
    "ASSUMED non-refrigerated" branch. The register discloses AHJ-11 to a
    reader who, through `btap-compliance`, could never meet it.

    The model cannot express refrigerated space, which is why the override
    exists; leaving it API-only made the referral unreachable for the surface
    most users have. Sol's rule is that a tool gap is a defect to close.
    """

    def _building(self, argv):
        from btap.codes import cli

        namespace = cli.build_parser().parse_args(argv)
        options = {"code": "necb2020", "run_dir": "/tmp/x", "simulate": "annual",
                   "report_options": {}, "model": "b.osm", "report_html": None}
        options.update({key: value for key, value
                        in vars(namespace).items() if value is not None})
        _model, kwargs = cli.compliance_kwargs(options)
        return kwargs.get("building")

    def test_the_option_reaches_the_building_data(self):
        self.assertEqual(
            {"refrigerated_zones": ["Cooler 1", "Freezer 2"]},
            self._building(["--refrigerated-zones", "Cooler 1, Freezer 2"]),
            "names are split on commas and stripped")

    def test_it_does_not_DISPLACE_the_storeys_override(self):
        """`building` was assigned, not built up, so a second key would have
        dropped the first."""
        self.assertEqual(
            {"storeys": 6, "refrigerated_zones": ["Cooler 1"]},
            self._building(["--storeys", "6", "--refrigerated-zones", "Cooler 1"]))

    def test_storeys_alone_is_unchanged(self):
        self.assertEqual({"storeys": 3}, self._building(["--storeys", "3"]))

    def test_neither_passes_no_building_data(self):
        self.assertIsNone(self._building([]))

    def test_it_is_in_the_help(self):
        from btap.codes import cli

        self.assertIn("--refrigerated-zones", cli.build_parser().format_help())


class TestAnInputLessEntryIsNeverSUPERSEDED(unittest.TestCase):
    """Fable's `133` G1, and the worst defect of the round because MY OWN fix
    for F3 introduced it.

    Supersession keyed on (step, target, input FIELDS). AHJ-11's System 5
    decision records no inputs, so its identity collapsed to (step, target),
    and the purchased-cooling decision emitted after it on the same zones —
    also input-less — "re-made the choice" and retired the referral. A heated
    refrigerated block on district cooling reported `code` with NO conditions:
    the silent drop this entire axis exists to prevent.

    An empty field set is not an identity, it is the absence of one. Treating
    absence as a match is what let two unrelated decisions collide. AHJ-16's
    five input-less warns carried the same fragility without colliding yet.
    """

    def _resolve(self, audit, code="necb2025"):
        from btap.codes.necb import path as necb_path

        class _Run:
            pass

        run = _Run()
        run.report = {"annual": True, "code": code}
        run.ruleset = type("_R", (), {"code": code})()
        necb_path._resolve_ahj_conditions(run, audit)
        reason = run.report.get("compliance_determination_reason") or {}
        return (run.report.get("compliance_determination"),
                [(c["id"], c["target"]) for c in reason.get("conditions", [])])

    def _g1_audit(self):
        from btap.audit import AuditLog

        audit = AuditLog()
        # The real pair, in the real order, from `_finalize`.
        audit.decision(
            "selection",
            "System 5 reference MODELS HEATING in the two-pipe surrogate",
            target="Thermal Zone 1,Thermal Zone 2",
            article="8.4.5.1.(5)", ruling="D-39", ahj="AHJ-11")
        audit.decision(
            "selection",
            "purchased cooling energy -> represented by air-cooled electric "
            "chiller",
            target="Thermal Zone 1,Thermal Zone 2", article="8.4.5.1.(3)")
        return audit

    def test_the_AHJ11_referral_survives_a_later_input_less_decision(self):
        determination, conditions = self._resolve(self._g1_audit())
        self.assertEqual([("AHJ-11", "Thermal Zone 1,Thermal Zone 2")],
                         conditions,
                         "the referral fired and must not be thrown away")
        self.assertEqual("conditional", determination)

    def test_it_holds_for_necb2020_too(self):
        determination, conditions = self._resolve(self._g1_audit(),
                                                  code="necb2020")
        self.assertEqual(1, len(conditions))
        self.assertEqual("conditional", determination)

    def test_an_input_less_warn_is_not_retired_either(self):
        """AHJ-16's shape: five input-less warns on one target and step."""
        from btap.audit import AuditLog

        audit = AuditLog()
        audit.warn("efficiency", "pump power transfer DECLINED",
                   target="Hot Water Loop", article="8.4.5.14.(1)",
                   ruling="D-11", ahj="AHJ-16")
        audit.decision("efficiency", "something else about the same loop",
                       target="Hot Water Loop", article="8.4.5.14.(2)")
        _determination, conditions = self._resolve(audit)
        self.assertEqual([("AHJ-16", "Hot Water Loop")], conditions)

    def test_the_RULING_also_separates_two_input_bearing_decisions(self):
        """The second guard. Two different decisions that happen to record the
        same field names stay distinct when their rulings differ."""
        from btap.audit import AuditLog

        audit = AuditLog()
        audit.decision("selection", "first choice", target="Zone 1",
                       inputs={"value": 1}, ruling="D-39", ahj="AHJ-11")
        audit.decision("selection", "a DIFFERENT choice, same field name",
                       target="Zone 1", inputs={"value": 2}, ruling="D-52")
        _determination, conditions = self._resolve(audit)
        self.assertEqual([("AHJ-11", "Zone 1")], conditions,
                         "a different ruling is a different choice")


class TestTheAppendixBearingComesFromTheRUN(unittest.TestCase):
    """Fable's `133` G2, on the surface F7 created one round earlier.

    The Bearing column was derived from the REGISTER STATUS alone, so it said
    "this run's determination is conditional on it" on runs that reached no
    determination at all — every `--simulate none|sizing --report-html` run of
    an ordinary gas building, badged UNDETERMINED, with rows underneath
    asserting a conditional determination. And the register and README prose I
    wrote vouched for the column, which is the F4 pattern again.

    The determination owns that judgement. The renderer reads
    `compliance_determination` and the resolver's own `ahj_ids` instead of
    re-deriving either.
    """

    def _rows(self, report, entries):
        import re

        from btap.codes.report import sections

        html = sections.ahj_appendix({"report": report,
                                      "audit_entries": entries,
                                      "options": {}})
        return dict(re.findall(
            r"(AHJ-\d+)</td>.*?(YES[^<]*|not applicable[^<]*|no —[^<]*)",
            html, re.S))

    def test_a_run_with_NO_determination_claims_none(self):
        """The defect. A sizing or none run has nothing to be conditional on."""
        rows = self._rows({}, [{"step": "efficiency", "ahj": "AHJ-14"}])
        self.assertIn("not applicable", rows["AHJ-14"])
        self.assertNotIn("YES", rows["AHJ-14"])

    def test_a_CONDITIONAL_run_says_YES_for_the_id_it_is_conditional_on(self):
        report = {"compliance_determination": "conditional",
                  "compliance_determination_reason": {"ahj_ids": ["AHJ-14"]}}
        rows = self._rows(report, [{"step": "efficiency", "ahj": "AHJ-14"}])
        self.assertIn("YES", rows["AHJ-14"])

    def test_a_cited_id_the_resolver_SUPERSEDED_does_not_claim_YES(self):
        """F3's own case: the audit keeps the citation, the determination is
        `code`, and the appendix must not contradict it."""
        report = {"compliance_determination": "code",
                  "compliance_determination_reason": {}}
        rows = self._rows(report, [{"step": "efficiency", "ahj": "AHJ-14"}])
        self.assertIn("superseded", rows["AHJ-14"])
        self.assertNotIn("YES", rows["AHJ-14"])

    def test_the_non_conditional_statuses_are_unaffected_by_the_run(self):
        """A `ruled` or `tool-gap` row says the same thing either way — those
        never depended on the determination."""
        for report in ({}, {"compliance_determination": "conditional",
                            "compliance_determination_reason": {
                                "ahj_ids": ["AHJ-14"]}}):
            rows = self._rows(report, [{"step": "a", "ahj": "AHJ-5"},
                                       {"step": "b", "ahj": "AHJ-18"}])
            self.assertIn("settled", rows["AHJ-5"])
            self.assertIn("defect in this tool", rows["AHJ-18"])


class TestTheSharedChoicePhraseMatchesTheSTATUS(unittest.TestCase):
    """Fable's `133` G5: one sentence served every status, so an AHJ-1 line
    read "which the text DECIDES ... this same unresolved election" in a
    single breath. An alternative solution is not an unresolved question — it
    is a requirement the text settles and this tool does not meet."""

    def _line(self, ident, count):
        from btap.audit import AuditLog
        from btap.codes.necb import path as necb_path

        audit = AuditLog()
        for index in range(count):
            audit.decision("x", f"choice {index}", target=f"Zone {index}",
                           inputs={"k": index}, ahj=ident)

        class _Run:
            pass

        run = _Run()
        run.report = {"annual": True, "code": "necb2020"}
        run.ruleset = type("_R", (), {"code": "necb2020"})()
        necb_path._resolve_ahj_conditions(run, audit)
        reason = run.report.get("compliance_determination_reason") or {}
        return (reason.get("ahj_must_approve") or [""])[0]

    def test_an_alternative_solution_is_a_DEPARTURE_not_an_election(self):
        line = self._line("AHJ-1", 5)
        self.assertIn("this same departure", line)
        self.assertNotIn("unresolved election", line)

    def test_a_referral_is_still_an_unresolved_election(self):
        line = self._line("AHJ-14", 3)
        self.assertIn("this same unresolved election", line)

    def test_a_single_site_still_quotes_its_own_account(self):
        """F8's rule is unchanged: one site means one site's words."""
        line = self._line("AHJ-14", 1)
        self.assertNotIn("choices above", line)


if __name__ == "__main__":      # pragma: no cover
    unittest.main()
