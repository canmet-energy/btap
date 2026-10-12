"""Cooling attribution over the WHOLE catalogue, both directions.

8.4.1.2.(4) applies to "each thermal block ... for which mechanical cooling
is provided", so the determination needs to know which blocks those are. Three
defects in that one question reached review, each a single HVAC topology, each
passing a nine-model corpus, each costing a round:

    08-vrf                 0 of 5 cooled, so (4)(a) passed over an empty set
    unitary on an air loop  same, from the opposite cause, introduced by my
                            own fix for the first
    an air terminal's coil  claimed every block on its loop

A corpus of nine fixed models cannot find these. The SDK's topology space is
enumerable, so this test walks it: every system the catalogue can build, on
the shared five-zone fixture, 97 entries at the time of writing.

## The invariant

Two independent traversals of the same object graph must agree:

    OUTWARD   `_zone_mechanical_cooling` starts at each cooling object and
              resolves to the blocks it serves, via `sources()` and the
              containment accessors.
    INWARD    `_zone_cooling_inward` starts at each block and asks what
              serves it, via `targets()` from its equipment, terminal and
              air loop.

They use OPPOSITE edges, so a bug in either surfaces as a disagreement rather
than as a quiet wrong answer. Each of the three defects above is a
disagreement: the VRF coil resolves inward and not outward; the unitary
resolves inward and not outward; the terminal's coil resolves outward too
widely.

`cooling_attribution_disagreement` is product code, not test code, so the
invariant travels into every run rather than living only here (Sol's `227`).

This test is topology only — no sizing, no simulation — so it is fast enough
to run in the SDK lane rather than behind an engine.
"""
import json
import pathlib
import unittest

from btap.codes.necb import path
from tests.necb.support import needs_sdk

HVAC_DATA = (pathlib.Path(path.__file__).resolve().parents[2]
             / "modeling" / "hvac" / "data")
CATALOGUE = HVAC_DATA / "systems.json"
FIXTURE = HVAC_DATA / "5ZoneNoHVAC.osm"

#: The catalogue had this many entries when the lattice was first walked. A
#: floor, not an equality: adding a system should not fail this test, but
#: silently losing most of them must.
KNOWN_ENTRIES = 97

#: A SECOND axis, because the catalogue alone is not the whole lattice.
#:
#: `staged_coils` changes the TOPOLOGY rather than a capacity: multispeed
#: coils cannot sit bare on an air loop, so `psz.py` wraps them in an
#: `AirLoopHVACUnitarySystem`. That is the shape my own fix broke — a
#: `ZoneHVACComponent` subclass on an air loop, whose `thermalZone()` is
#: empty — and no catalogue entry reaches it, because the flag is set only by
#: the NECB reference rules (`reference_rules.json`, both editions,
#: 8.4.4.9.(7)/8.4.4.10.(8)).
#:
#: So the catalogue is necessary and not sufficient, and a lattice that
#: stopped at the catalogue would have missed the defect that cost the most.
#: Config options that change topology belong on this list.
TOPOLOGY_CONFIGS = (
    ("catalogue default", {}),
    ("staged coils (NECB reference, builds a unitary)", {"staged_coils": True}),
)

#: Config overrides that are only meaningful for ONE family, each flipping a
#: value the catalogue carries on one side only. `TOPOLOGY_CONFIGS` above is a
#: cross-product over every family, which is wrong for these: `cooling` exists
#: on exactly one catalogue row and `mau` on none at all, so a blanket
#: override would be asserting over families that never read the key.
#:
#: Every one of these ran and agreed before it was listed — they are COVERAGE,
#: not defects (Fable, `229` NB-4). The reason to list them anyway is the
#: reason the lattice exists: `staged_coils` is reachable only from the NECB
#: reference rules and never from the catalogue, and it was the single route
#: to a unitary system on an air loop. A flag the catalogue exercises on one
#: side only is the same shape of gap.
#:
#: Each entry is grounded in what the code actually reads, not guessed:
#: `furnace` carries `cooling: False` and `ventilation: True`; `wshp` carries
#: `ventilation: False`; `vrf` carries `zone_ventilation: True`; `psz` carries
#: `per_zone: True`; `fan_coils` reads `mau` with a default of True and has no
#: catalogue row for it; `ashp_baseboard` reads `vent_type` as a binary
#: against `'doas'`.
FAMILY_CONFIGS = (
    ("furnace", "cooling added to a heating-only furnace", {"cooling": True}),
    ("furnace", "ventilation removed", {"ventilation": False}),
    ("wshp", "ventilation added", {"ventilation": True}),
    ("vrf", "zone ventilation removed", {"zone_ventilation": False}),
    ("psz", "one unit for the group instead of per zone",
     {"per_zone": False}),
    ("fan_coils", "no makeup-air unit", {"mau": False}),
    ("ecm_ashp_baseboard", "ventilation that is not a DOAS",
     {"vent_type": "mau"}),
)


def _catalogue():
    return json.loads(CATALOGUE.read_text(encoding="utf-8"))["systems"]


@needs_sdk
class TestCoolingAttributionOverTheCatalogue(unittest.TestCase):
    def test_the_catalogue_is_big_enough_to_be_a_lattice(self):
        entries = _catalogue()
        self.assertGreaterEqual(
            len(entries), KNOWN_ENTRIES,
            f"the catalogue has {len(entries)} systems and had "
            f"{KNOWN_ENTRIES} when this test was written. If systems were "
            "removed, say so deliberately and lower the floor — a shrunken "
            "catalogue makes every assertion below weaker without failing")
        self.assertTrue(FIXTURE.is_file(), f"{FIXTURE} is the shared fixture")

    def test_every_catalogue_system_BUILDS_and_both_directions_agree(self):
        """The whole lattice, one subTest per system.

        A build failure is reported as a failure rather than skipped: a
        catalogue entry that cannot be built is a defect in the catalogue or
        the builder, and discovering it here is cheaper than in a run.
        """
        import openstudio

        import btap.modeling as modeling

        for entry in _catalogue():
            name = entry["name"]
            with self.subTest(system=name):
                loaded = openstudio.osversion.VersionTranslator().loadModel(
                    openstudio.toPath(str(FIXTURE)))
                self.assertTrue(loaded.is_initialized(),
                                f"{FIXTURE} must load")
                model = loaded.get()
                zones = sorted(model.getThermalZones(),
                               key=lambda z: z.nameString())
                modeling.build_system(model, name, zones)

                gap = path.cooling_attribution_disagreement(model)
                self.assertEqual(
                    {}, gap,
                    f"{name}: the two attribution directions disagree about "
                    f"{sorted(gap)} — {gap}. One of them is wrong for this "
                    "topology, and which one is exactly what is not known "
                    "from here")

                outward, unplaceable = path._zone_mechanical_cooling(model)
                self.assertEqual(
                    [], unplaceable,
                    f"{name}: these cooling objects could not be placed, so "
                    f"(4)(a)'s applicability is unknown: {unplaceable}")
                self.assertEqual(
                    len(model.getThermalZones()), len(outward),
                    f"{name}: one answer per thermal block")
                self.assertEqual(
                    path._mechanical_cooling(model), any(outward.values()),
                    f"{name}: the per-block map and the building-wide flag "
                    "disagree about whether ANY block is cooled — that "
                    "mismatch is what let a fully cooled building pass "
                    "(4)(a) vacuously")

    def test_the_topology_CONFIGS_agree_too(self):
        """The second axis: options that change topology, not capacity.

        `staged_coils` wraps the coils in an `AirLoopHVACUnitarySystem`
        because multispeed coils cannot sit bare on a loop. That container is
        a `ZoneHVACComponent` subclass with no `thermalZone()` when it is on
        a loop, which is exactly what my attribution fix mishandled — and no
        catalogue entry sets the flag, so the 97-system walk above cannot
        reach it.
        """
        import openstudio

        import btap.modeling as modeling

        families = {}
        for entry in _catalogue():
            families.setdefault(entry.get("family"), entry["name"])

        for label, config in TOPOLOGY_CONFIGS:
            for family, name in sorted(families.items()):
                with self.subTest(config=label, family=family):
                    loaded = openstudio.osversion.VersionTranslator().loadModel(
                        openstudio.toPath(str(FIXTURE)))
                    model = loaded.get()
                    zones = sorted(model.getThermalZones(),
                                   key=lambda z: z.nameString())
                    try:
                        modeling.build_system(model, name, zones,
                                              config=dict(config))
                    except Exception as error:            # noqa: BLE001
                        if not config:
                            raise
                        # A config a family does not accept is not a defect;
                        # the axis exists for the families that do.
                        self.skipTest(
                            f"{family} does not take {label}: "
                            f"{type(error).__name__}")
                    gap = path.cooling_attribution_disagreement(model)
                    self.assertEqual(
                        {}, gap,
                        f"{family} with {label}: the two directions "
                        f"disagree about {sorted(gap)} — {gap}")
                    outward, unplaceable = path._zone_mechanical_cooling(model)
                    self.assertEqual([], unplaceable, f"{family}/{label}")
                    self.assertEqual(
                        path._mechanical_cooling(model),
                        any(outward.values()),
                        f"{family} with {label}: per-block map and "
                        "building-wide flag disagree")

    def test_the_PER_FAMILY_config_flips_agree_too(self):
        """The third axis: a flag the catalogue carries on one side only.

        `TOPOLOGY_CONFIGS` is a cross-product over every family, which is the
        wrong shape for these — `cooling` exists on one catalogue row and
        `mau` on none, so a blanket override would assert over families that
        never read the key. Each entry here is paired with the one family
        whose code reads it (Fable, `229` NB-4).

        Unlike the `staged_coils` axis, none of these was hiding a defect:
        every one ran and agreed before it was listed. They are here because
        a flag exercised on one side only is the same SHAPE of gap that
        `staged_coils` turned out to be, and because a skip would otherwise
        be indistinguishable from a pass.

        **What this axis does and does not defend**, measured rather than
        assumed:

        ```text
        CONTROL                     1 passed, 7 subtests
        containment rung removed    1 passed, 7 subtests   <-- NOT caught
        inward walk emptied         7 FAILED
        ```

        None of these seven families builds a DOAS, so the OA-stream
        containment rung is out of their reach — that rung is defended by
        `test_a_DOAS_coil_resolves_at_EVERY_distance_from_its_OA_system`.
        What this axis defends is the forward/reverse invariant itself
        across topologies the catalogue does not reach. Saying which
        mutation it survives is the point: an axis credited with coverage it
        does not have is worse than no axis.
        """
        import openstudio

        import btap.modeling as modeling

        by_family = {}
        for entry in _catalogue():
            by_family.setdefault(entry.get("family"), entry["name"])

        exercised = 0
        for family, label, config in FAMILY_CONFIGS:
            with self.subTest(family=family, config=label):
                self.assertIn(
                    family, by_family,
                    f"{family} is named in FAMILY_CONFIGS and is not in the "
                    "catalogue — the override would assert over nothing")
                name = by_family[family]
                loaded = openstudio.osversion.VersionTranslator().loadModel(
                    openstudio.toPath(str(FIXTURE)))
                model = loaded.get()
                zones = sorted(model.getThermalZones(),
                               key=lambda z: z.nameString())
                modeling.build_system(model, name, zones,
                                      config=dict(config))
                exercised += 1
                gap = path.cooling_attribution_disagreement(model)
                self.assertEqual(
                    {}, gap,
                    f"{family} with {label}: the two directions disagree "
                    f"about {sorted(gap)} — {gap}")
                outward, unplaceable = path._zone_mechanical_cooling(model)
                self.assertEqual([], unplaceable, f"{family}/{label}")
                self.assertEqual(
                    path._mechanical_cooling(model), any(outward.values()),
                    f"{family} with {label}: per-block map and "
                    "building-wide flag disagree")

        # No `skipTest` above, deliberately. Each override is paired with the
        # family that reads it, so a build failure is a real finding rather
        # than an inapplicable combination — and a silent skip would make
        # this test pass while exercising nothing.
        self.assertEqual(
            len(FAMILY_CONFIGS), exercised,
            "every per-family override must have actually built")

    def test_the_unitary_shape_is_actually_REACHED_by_the_config_axis(self):
        """A guard on the axis: if `staged_coils` stopped producing a
        unitary, the axis above would pass while covering nothing.
        """
        import openstudio

        import btap.modeling as modeling

        psz = next(e["name"] for e in _catalogue()
                   if e.get("family") == "psz")
        loaded = openstudio.osversion.VersionTranslator().loadModel(
            openstudio.toPath(str(FIXTURE)))
        model = loaded.get()
        zones = sorted(model.getThermalZones(), key=lambda z: z.nameString())
        modeling.build_system(model, psz, zones,
                              config={"staged_coils": True})
        types = {o.iddObjectType().valueName() for o in model.modelObjects()}
        self.assertTrue(
            any("UnitarySystem" in name for name in types),
            "`staged_coils` must still build an AirLoopHVACUnitarySystem on "
            "the air loop; that container is the whole reason this axis "
            "exists, and without it the config subtests cover nothing new")

    def test_the_lattice_contains_the_shapes_that_broke_it(self):
        """A guard on the guard: the catalogue must still cover the three
        topologies that caused the defects, or this file has stopped being
        the reason to believe the attribution code.

        Named by family rather than by system name, because a system can be
        renamed and the topology is what matters.
        """
        families = {entry.get("family") for entry in _catalogue()}
        for family, why in (
            ("psz", "a unitary system on an air loop — `psz.py` calls it the "
                    "only SDK container that can host multispeed coils "
                    "there, and it is the shape my own fix broke"),
            ("vrf", "a VRF terminal unit, whose cooling coil the 3.11 SDK "
                    "does not link back to it — the family name is `vrf`, "
                    "not `doas_vrf`; I guessed and this test caught it"),
            ("fan_coils", "zone equipment holding its own cooling coil"),
            ("vav_reheat", "central chilled water reaching blocks through "
                           "terminals"),
        ):
            with self.subTest(family=family):
                self.assertIn(
                    family, families,
                    f"the catalogue no longer builds any `{family}` system, "
                    f"which covered {why}")


if __name__ == "__main__":
    unittest.main()


@needs_sdk
class TestTheUnresolvedBranchAndTheOracle(unittest.TestCase):
    """The branches that say "I do not know", and the comparison that finds them.

    Everything else in this file asserts a RESOLVED answer. Fable's `228`
    pointed out that every SDK-built assertion on `unplaceable` in the whole
    suite is `[]`, so `_reaches_no_topology` could `return True`
    unconditionally — declaring every cooling object detached — and 37 tests
    with 141 subtests stayed green. A branch no test fires is a branch no
    test defends.
    """

    def _doas(self, inboard=()):
        """A DOAS whose cooling coil is `inboard` components from the OAS.

        This is the shape that defeated the bounded source walk: an
        `AirLoopHVACOutdoorAirSystem` references only its controller and two
        port Connections, so each OA-stream component costs four hops. The
        coil ALONE resolved at depth four; with a fan and a heating coil
        inboard it sits at twelve.
        """
        import openstudio

        model = openstudio.model.Model()
        zone = openstudio.model.ThermalZone(model)
        zone.setName("Z1")
        loop = openstudio.model.AirLoopHVAC(model)
        loop.setName("AL1")
        terminal = (openstudio.model
                    .AirTerminalSingleDuctConstantVolumeNoReheat(
                        model, model.alwaysOnDiscreteSchedule()))
        loop.addBranchForZone(zone, terminal.to_StraightComponent().get())
        oa_system = openstudio.model.AirLoopHVACOutdoorAirSystem(
            model, openstudio.model.ControllerOutdoorAir(model))
        dedicated = (openstudio.model
                     .AirLoopHVACDedicatedOutdoorAirSystem(oa_system))
        dedicated.addAirLoop(loop)
        for make in inboard:
            make(model).addToNode(oa_system.outboardOANode().get())
        coil = openstudio.model.CoilCoolingWater(
            model, model.alwaysOnDiscreteSchedule())
        coil.setName("DOAS Cooling Coil")
        coil.addToNode(oa_system.outboardOANode().get())
        return model

    def test_a_DOAS_coil_resolves_at_EVERY_distance_from_its_OA_system(self):
        """Containment, not depth.

        With a bounded source walk the one-component case passed and the
        textbook case — a fan and a heating coil inboard of the cooling coil
        — was reported DETACHED, which made 8.4.1.2.(4)(a) vacuous and
        passed 900 unmet cooling hours (Fable, `228`).
        """
        import openstudio

        def fan(model):
            return openstudio.model.FanVariableVolume(
                model, model.alwaysOnDiscreteSchedule())

        def heating(model):
            return openstudio.model.CoilHeatingElectric(
                model, model.alwaysOnDiscreteSchedule())

        for label, inboard in (("the coil alone", ()),
                               ("a fan inboard", (fan,)),
                               ("a fan and a heating coil inboard",
                                (fan, heating)),
                               ("four components inboard",
                                (fan, heating, fan, heating))):
            with self.subTest(inboard=label):
                model = self._doas(inboard)
                cooling_map, unplaceable = path._zone_mechanical_cooling(model)
                self.assertEqual(
                    {"Z1": True}, cooling_map,
                    f"a DOAS cooling coil with {label} must place its block "
                    "regardless of how far it sits from the OA system")
                self.assertEqual([], unplaceable)

    def test_the_two_walks_AGREE_on_every_DOAS_distance(self):
        """The oracle is the independent witness, so it must be consulted.

        `cooling_attribution_disagreement` compares an outward walk from
        cooling objects against an inward walk from blocks. It reported
        `{'Z1': (False, True)}` on the defect above, in every probe — the
        finding was available to any run that asked.
        """
        import openstudio

        def fan(model):
            return openstudio.model.FanVariableVolume(
                model, model.alwaysOnDiscreteSchedule())

        for count in range(4):
            with self.subTest(inboard=count):
                model = self._doas((fan,) * count)
                self.assertEqual(
                    {}, path.cooling_attribution_disagreement(model),
                    "the two walks disagree about this DOAS, so one of them "
                    "is wrong and the block's cooling status is unknown")

    def test_a_DISAGREEMENT_makes_the_block_unplaceable_not_passing(self):
        """The runtime consequence, driven by a forced disagreement.

        This does not depend on any particular model defect: it asserts that
        when the two walks disagree, the deciding function treats the block
        as UNKNOWN. Before `228` the disagreement had no runtime caller at
        all, so a wrong outward walk became `cooling_vacuous` and passed.
        """
        unplaceable = []
        disagreement = {"Z1": (False, True)}
        for block in disagreement:
            if block not in unplaceable:
                unplaceable.append(block)
        report = {"proposed": {
            "zone_unmet_occupied_hours": {"Z1": {"heating": 1.0,
                                                 "cooling": 900.0}},
            "zone_mechanical_cooling": {"Z1": False},
            "mechanical_cooling": True,
            "unplaceable_cooling": sorted(unplaceable)}}
        status = path._unmet_status_8_4_4(report)
        self.assertFalse(status["cooling_known"],
                         "a block the two walks disagree about has an "
                         "UNKNOWN cooling status")
        self.assertFalse(status["cooling_vacuous"],
                         "an unknown cooling status is not a vacuous (4)(a)")
        self.assertFalse(status["all_ok"],
                         "900 unmet cooling hours must not pass because the "
                         "attribution could not be established")

    def test_a_genuinely_DETACHED_coil_is_still_detached(self):
        """The counterweight: the fix must not turn `detached` into unknown.

        A stray coil connected to no topology serves no block, so (4)(a)'s
        scope is KNOWN and excludes it (Sol, `224`). This is the control for
        the test above: without it, "make everything unresolved" would pass.
        """
        import openstudio

        model = openstudio.model.Model()
        openstudio.model.ThermalZone(model).setName("Z1")
        stray = openstudio.model.CoilCoolingWater(
            model, model.alwaysOnDiscreteSchedule())
        stray.setName("stray coil")
        cooling_map, unplaceable = path._zone_mechanical_cooling(model)
        self.assertEqual({"Z1": False}, cooling_map)
        self.assertEqual([], unplaceable,
                         "a detached coil is a known non-participant, not an "
                         "unresolved attribution")

    def test_an_object_that_REACHES_topology_but_places_no_block_is_unresolved(
            self):
        """The branch Fable's `228` mutation proved untested.

        `_reaches_no_topology` separates two different answers: an object
        connected to nothing serves no block, so (4)(a)'s scope is KNOWN and
        excludes it; an object that reaches real HVAC topology but resolves
        to no block is an attribution this tool could not make, which is
        UNKNOWN. Both end the loop, and only the second may appear in
        `unplaceable`.

        Every SDK-built assertion on `unplaceable` in this suite was `[]`, so
        `return True` at the top of that function — "everything is detached"
        — left 37 tests and 141 subtests green. These two fixtures are the
        ones that distinguish it: an orphan PTAC and an orphan unitary system
        each carry a fan and coils, so their graphs reach topology, while no
        thermal zone owns them.
        """
        import openstudio

        def orphan_ptac(model):
            fan = openstudio.model.FanOnOff(
                model, model.alwaysOnDiscreteSchedule())
            heating = openstudio.model.CoilHeatingElectric(
                model, model.alwaysOnDiscreteSchedule())
            cooling = openstudio.model.CoilCoolingDXSingleSpeed(model)
            unit = openstudio.model.ZoneHVACPackagedTerminalAirConditioner(
                model, model.alwaysOnDiscreteSchedule(), fan, heating,
                cooling)
            unit.setName("orphan PTAC")

        def orphan_unitary(model):
            unit = openstudio.model.AirLoopHVACUnitarySystem(model)
            unit.setSupplyFan(openstudio.model.FanOnOff(
                model, model.alwaysOnDiscreteSchedule()))
            unit.setCoolingCoil(
                openstudio.model.CoilCoolingDXSingleSpeed(model))
            unit.setHeatingCoil(openstudio.model.CoilHeatingElectric(
                model, model.alwaysOnDiscreteSchedule()))
            unit.setName("orphan unitary")

        for label, build in (("an orphan PTAC", orphan_ptac),
                             ("an orphan unitary system", orphan_unitary)):
            with self.subTest(fixture=label):
                model = openstudio.model.Model()
                openstudio.model.ThermalZone(model).setName("Z1")
                build(model)
                cooling_map, unplaceable = path._zone_mechanical_cooling(model)
                self.assertEqual({"Z1": False}, cooling_map)
                self.assertNotEqual(
                    [], unplaceable,
                    f"{label} reaches HVAC topology and places no block, so "
                    "its attribution is UNKNOWN and must be reported — "
                    "calling it detached asserts it cools nothing, which "
                    "this tool has not established")

    def test_the_two_answers_are_not_interchangeable(self):
        """Both directions, in one place, so neither can be collapsed.

        A single-sided assertion is satisfiable by a constant: "everything
        unresolved" passes the test above and "everything detached" passes
        the detached control. Only the pair pins the distinction.
        """
        import openstudio

        model = openstudio.model.Model()
        openstudio.model.ThermalZone(model).setName("Z1")
        bare = openstudio.model.CoilCoolingWater(
            model, model.alwaysOnDiscreteSchedule())
        bare.setName("bare coil")
        fan = openstudio.model.FanOnOff(
            model, model.alwaysOnDiscreteSchedule())
        unit = openstudio.model.ZoneHVACPackagedTerminalAirConditioner(
            model, model.alwaysOnDiscreteSchedule(), fan,
            openstudio.model.CoilHeatingElectric(
                model, model.alwaysOnDiscreteSchedule()),
            openstudio.model.CoilCoolingDXSingleSpeed(model))
        unit.setName("orphan PTAC")

        _cooling_map, unplaceable = path._zone_mechanical_cooling(model)
        self.assertEqual(
            ["Coil Cooling DX Single Speed 1"], unplaceable,
            "the PTAC's coil is unresolved and the bare coil is detached: "
            "exactly one of the two belongs in `unplaceable`, so neither "
            "answer can be a constant")

    def test_the_oracle_reads_TWO_sources_and_not_one_twice(self):
        """Independence is the whole value, so it is asserted, not assumed.

        Replacing the inward walk with the outward one —
        `inward = _zone_mechanical_cooling(model)[0]` — leaves an oracle that
        can never disagree with anything. It survived every other test in
        this file: 9 passed, 145 subtests, while the comparison had become
        worthless. Fable's `228` NB-1 made the weaker form of this point,
        that two walks I wrote agreeing is thin evidence; this is the
        stronger one, that nothing checked they were two walks at all.

        The test patches ONE side to a known-wrong answer. If the two sides
        came from the same call, the patch would not be consulted and the
        oracle would report agreement.
        """
        import unittest.mock

        import openstudio

        model = self._doas()
        outward, _unplaceable = path._zone_mechanical_cooling(model)
        self.assertEqual({"Z1": True}, outward,
                         "the fixture must be cooled for the patch below to "
                         "create a disagreement")
        del openstudio

        with unittest.mock.patch.object(path, "_zone_cooling_inward",
                                        return_value={"Z1": False}):
            disagreement = path.cooling_attribution_disagreement(model)

        self.assertEqual(
            {"Z1": (True, False)}, disagreement,
            "the oracle must read the INWARD walk as a separate source: if "
            "both sides come from `_zone_mechanical_cooling`, patching the "
            "inward walk changes nothing and the comparison can never "
            "disagree with the walk it is meant to check")


class TestAKnownExceedanceIsNotHiddenByAnUnknown(unittest.TestCase):
    """A known failure and an unresolved scope are two facts, not one.

    A block measured at 900 unmet cooling hours and KNOWN to be mechanically
    cooled disappeared from the audit behind "which blocks (4)(a) applies to
    cannot be established", because an unrelated stray coil elsewhere in the
    model was unplaceable (Fable, `229` NB-3). The verdict was right either
    way — both paths fail — so this is evidence, not arithmetic: an authority
    was told the sentence could not be determined when one of its blocks
    demonstrably failed it.

    Same defect class as Sol's `220`, where one warning spoke for two
    sentences and named the wrong one.
    """

    LIMIT = 100.0

    def _entries(self, rows, cooling_map, unplaceable):
        from btap.audit.log import AuditLog
        audit = AuditLog()
        report = {"proposed": {
            "zone_unmet_occupied_hours": rows,
            "zone_mechanical_cooling": cooling_map,
            "mechanical_cooling": True,
            "unplaceable_cooling": unplaceable,
            "total_site_kwh": 1.0}}
        path.evaluate_unmet_8_4_4(report, audit)
        return [e for e in audit.entries
                if "8.4.1.2.(4)" in str(e.get("article"))]

    def test_the_exceedance_is_stated_even_while_the_scope_is_unresolved(self):
        entries = self._entries(
            {"A": {"heating": 1.0, "cooling": 900.0},
             "B": {"heating": 1.0, "cooling": 2.0}},
            {"A": True, "B": True}, ["some stray coil"])
        actions = " | ".join(e["action"] for e in entries)
        self.assertIn(
            "EXCEED 100 h", actions,
            "block A is KNOWN cooled and measured at 900 h, so the "
            "exceedance is established on its own and must be stated — it "
            "does not depend on the part that could not be resolved")
        self.assertIn(
            "cannot be established", actions,
            "and the unresolved scope must STILL be disclosed; replacing "
            "one truth with the other is the defect, in either direction")
        failing = [e for e in entries if "EXCEED" in e["action"]]
        self.assertEqual(
            {"A": 900.0}, failing[0]["inputs"]["failing_blocks"],
            "and it must name WHICH block, not a count alone")

    def test_an_unresolved_scope_with_no_known_failure_invents_none(self):
        """The control: the new entry must not appear when nothing failed."""
        entries = self._entries(
            {"A": {"heating": 1.0, "cooling": 2.0},
             "B": {"heating": 1.0, "cooling": 3.0}},
            {"A": True, "B": True}, ["some stray coil"])
        actions = " | ".join(e["action"] for e in entries)
        self.assertNotIn("EXCEED 100 h", actions,
                         "no block exceeds the limit, so no exceedance may "
                         "be reported")
        self.assertIn("cannot be established", actions)

    def test_a_fully_resolved_failure_stays_a_DECISION(self):
        """The other control: the normal path is not downgraded to a warning.

        Without this, "always warn" would satisfy the test above.
        """
        entries = self._entries(
            {"A": {"heating": 1.0, "cooling": 900.0},
             "B": {"heating": 1.0, "cooling": 2.0}},
            {"A": True, "B": True}, [])
        self.assertEqual(
            1, len(entries),
            "a resolved model gets ONE entry for (4)(a), not a warning "
            "beside it")
        self.assertEqual("decision", entries[0]["level"],
                         "a determined sentence is a decision; only an "
                         "unresolved scope warns")
        self.assertIn("EXCEED 100 h", entries[0]["action"])


@needs_sdk
class TestReliefAirIsExhaustAndCoolsNothing(unittest.TestCase):
    """The case where the invariant's two walks agreed and were both wrong.

    A `CoilCoolingWater` on `oas.outboardReliefNode()` was attributed to
    every zone of the loop by BOTH walks, with `gap={}`. Relief air is
    exhausted — that coil conditions air leaving the building and cools no
    thermal block.

    The agreement was not evidence. The inward walk seeded
    `reliefComponents()` as well as `oaComponents()`, so independence had
    been traded for agreement in exactly one place and this is the case it
    hid (Fable, `229` NB-1). It failed CLOSED — an uncooled block's passive
    overheating hours got judged against (4)(a) — which is why it was
    non-blocking and not why it was acceptable.
    """

    def _with_coil_on(self, node_name, on_loop):
        import openstudio

        model = openstudio.model.Model()
        zone = openstudio.model.ThermalZone(model)
        zone.setName("Z1")
        loop = openstudio.model.AirLoopHVAC(model)
        loop.setName("AL1")
        terminal = (openstudio.model
                    .AirTerminalSingleDuctConstantVolumeNoReheat(
                        model, model.alwaysOnDiscreteSchedule()))
        loop.addBranchForZone(zone, terminal.to_StraightComponent().get())
        oa_system = openstudio.model.AirLoopHVACOutdoorAirSystem(
            model, openstudio.model.ControllerOutdoorAir(model))
        if on_loop:
            oa_system.addToNode(loop.supplyInletNode())
        else:
            dedicated = (openstudio.model
                         .AirLoopHVACDedicatedOutdoorAirSystem(oa_system))
            dedicated.addAirLoop(loop)
        coil = openstudio.model.CoilCoolingWater(
            model, model.alwaysOnDiscreteSchedule())
        coil.setName("coil")
        coil.addToNode(getattr(oa_system, node_name)().get())
        return model

    def test_a_RELIEF_side_coil_cools_no_block(self):
        for label, on_loop in (("a plain air loop", True),
                               ("a dedicated outdoor-air system", False)):
            with self.subTest(topology=label):
                model = self._with_coil_on("outboardReliefNode", on_loop)
                outward, unplaceable = path._zone_mechanical_cooling(model)
                self.assertEqual(
                    {"Z1": False}, outward,
                    f"{label}: a coil on the relief stream conditions air "
                    "leaving the building; attributing it to the loop's "
                    "zones judges an uncooled block against (4)(a)")
                self.assertEqual(
                    [], unplaceable,
                    "and it is PLACED — relief is a known answer, not an "
                    "unresolved attribution")

    def test_an_OA_side_coil_on_the_same_system_DOES_cool(self):
        """The control, and the reason this is not just "ignore the OAS".

        The same object on the OA stream of the same outdoor-air system
        serves every block the loop serves. Only the stream differs.
        """
        for label, on_loop in (("a plain air loop", True),
                               ("a dedicated outdoor-air system", False)):
            with self.subTest(topology=label):
                model = self._with_coil_on("outboardOANode", on_loop)
                outward, unplaceable = path._zone_mechanical_cooling(model)
                self.assertEqual({"Z1": True}, outward,
                                 f"{label}: an OA-stream coil conditions "
                                 "air entering the zones")
                self.assertEqual([], unplaceable)

    def test_the_two_walks_agree_about_relief_because_BOTH_are_right(self):
        """Agreement is only evidence when the walks are independent.

        The inward walk no longer seeds `reliefComponents()`, so it reaches
        this answer on its own rather than by being shaped to match.
        """
        for on_loop in (True, False):
            with self.subTest(on_loop=on_loop):
                model = self._with_coil_on("outboardReliefNode", on_loop)
                self.assertEqual(
                    {}, path.cooling_attribution_disagreement(model))
                self.assertEqual(
                    {"Z1": False}, path._zone_cooling_inward(model),
                    "the INWARD walk must reach 'not cooled' by itself")


@needs_sdk
class TestTheTopologyPatternMatchesBySubstring(unittest.TestCase):
    """`_TOPOLOGY_TYPES` over-matches, and the direction is what makes it safe.

    `AirLoopHVAC` also matches `AirLoopHVAC_ZoneSplitter`, `_ZoneMixer`,
    `_ReturnPlenum`, `_SupplyPlenum` and `_UnitarySystem`; `ZoneHVAC`
    matches `ZoneHVAC_EquipmentList` (Fable, `229` NB-5). 137 of the SDK's
    1429 IDD type names match.

    Every one of those IS topology, so the accident gives the right answer.
    This pins the SHAPES rather than the 137 names, which move with the SDK,
    and it pins the direction: a type matched in error makes an object
    UNRESOLVED rather than detached, and unresolved is the conservative
    answer — the reverse asserts that a coil cools nothing, which is the
    defect `224` found.
    """

    def test_every_stem_in_the_pattern_is_a_real_topology_stem(self):
        """The stems themselves, so a careless addition is visible."""
        stems = path._TOPOLOGY_TYPES.pattern.replace('"', "").split("|")
        self.assertEqual(
            ["AirLoopHVAC", "PlantLoop", "ThermalZone", "ZoneHVAC",
             "AirTerminal", "OutdoorAirSystem"],
            [s.strip() for s in stems],
            "the stem list is the whole of this heuristic; a new stem "
            "widens what counts as topology and needs saying out loud")

    def test_the_substring_matches_are_all_real_topology(self):
        """A coil behind each flagged type must RESOLVE, not be detached.

        These are the matches Fable named. If the pattern missed them the
        object would be called detached — asserting it cools nothing.
        """
        import openstudio

        model = openstudio.model.Model()
        zone = openstudio.model.ThermalZone(model)
        zone.setName("Z1")
        loop = openstudio.model.AirLoopHVAC(model)
        loop.setName("AL1")
        terminal = (openstudio.model
                    .AirTerminalSingleDuctConstantVolumeNoReheat(
                        model, model.alwaysOnDiscreteSchedule()))
        loop.addBranchForZone(zone, terminal.to_StraightComponent().get())
        coil = openstudio.model.CoilCoolingWater(
            model, model.alwaysOnDiscreteSchedule())
        coil.addToNode(loop.supplyOutletNode())

        # A loop serving a zone has a splitter and a mixer by construction,
        # so this model already contains the flagged types.
        present = {obj.iddObjectType().valueName()
                   for obj in model.modelObjects()}
        for flagged in ("OS_AirLoopHVAC_ZoneSplitter",
                        "OS_AirLoopHVAC_ZoneMixer",
                        "OS_ZoneHVAC_EquipmentList"):
            with self.subTest(type=flagged):
                self.assertIn(
                    flagged, present,
                    "this fixture is supposed to contain the flagged type")
                self.assertTrue(
                    path._TOPOLOGY_TYPES.search(flagged),
                    f"{flagged} matches by substring and IS topology — a "
                    "pattern that stopped matching it would call an object "
                    "behind it detached")

        outward, unplaceable = path._zone_mechanical_cooling(model)
        self.assertEqual({"Z1": True}, outward)
        self.assertEqual([], unplaceable)

    def test_an_over_match_makes_an_object_UNRESOLVED_not_detached(self):
        """The direction of error, asserted rather than assumed.

        `_reaches_no_topology` returning False routes an unplaceable object
        to `unplaceable` — a declared unknown — instead of silently
        excluding it from (4)(a)'s scope.
        """
        import openstudio

        model = openstudio.model.Model()
        openstudio.model.ThermalZone(model).setName("Z1")
        fan = openstudio.model.FanOnOff(
            model, model.alwaysOnDiscreteSchedule())
        unit = openstudio.model.ZoneHVACPackagedTerminalAirConditioner(
            model, model.alwaysOnDiscreteSchedule(), fan,
            openstudio.model.CoilHeatingElectric(
                model, model.alwaysOnDiscreteSchedule()),
            openstudio.model.CoilCoolingDXSingleSpeed(model))
        unit.setName("orphan PTAC")
        _outward, unplaceable = path._zone_mechanical_cooling(model)
        self.assertNotEqual(
            [], unplaceable,
            "the orphan PTAC reaches topology types and places no block, so "
            "the conservative answer is UNRESOLVED — being wrong in this "
            "direction costs a declared unknown, and being wrong in the "
            "other asserts that a coil cools nothing")
