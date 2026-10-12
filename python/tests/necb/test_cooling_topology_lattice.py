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
