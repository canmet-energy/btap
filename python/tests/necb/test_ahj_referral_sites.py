"""Each wired referral cites on its OWN branch, and not on its exclusions.

Sol's `127` guards 3 and 4. The positive case proves the deciding entry carries
the id, its target and its article; the BOUNDARY NEGATIVE proves the excluded
branch carries nothing. The negatives matter as much as the positives: the
whole risk of site-owned applicability is a broad "this function ran" tag that
over-discloses, and `126` narrowed most of these questions precisely because
the unnarrowed version would have fired on cases the Code settles.
"""

from __future__ import annotations

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


if __name__ == "__main__":      # pragma: no cover
    unittest.main()
