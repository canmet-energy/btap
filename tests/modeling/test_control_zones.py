"""Which zone controls a shared single-zone unit (phylroy, 2026-11-20).

A shared unit follows ONE zone, as a house's furnace serves every floor from
one thermostat. The user may choose that zone; otherwise `build_system` marks
the loop and `elect_control_zones` moves control, after a sizing run, to the
zone with the largest design heating load. The builder used to take
`zones[0]` and leave it: a five-zone shared unit then left 377 h of heating
unmet after three NECB capacity increases, and 0 h once elected.
"""

from __future__ import annotations

import tempfile
import unittest
import warnings

from tests.support import DDY, EPW, load_fixture, needs_engine, needs_sdk

SHARED = "PSZ RTU Gas and DX Coils and Hot Water Baseboard"
#: A row that STATES it is shared: the on-ramp builds it shared (D-101), so it
#: is the one that reaches the pipeline's election.
EXPLICITLY_SHARED = "Shared PSZ with gas boiler coils and hot water baseboard"
PER_ZONE = "PSZ-AC with gas coil"
MULTI_ZONE = "MZ BU RTU Electric Heating Coil Scroll Chiller and Electric Baseboard"


def _built(name, **kwargs):
    from btap import modeling
    from btap._compat import sorted_by_name
    model = load_fixture()
    zones = sorted_by_name(model.getThermalZones())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = modeling.build_system(model, name, zones, **kwargs)
    return model, zones, list(result.air_loops)


def _control_zones(loop):
    from btap.modeling.hvac import control_zones
    return sorted({control_zones._control_zone(c).nameString()
                   for c in control_zones.controls(loop)})


@needs_sdk
class TestWhatIsMarked(unittest.TestCase):

    def test_a_shared_unit_with_no_chosen_zone_is_marked_and_provisional(self):
        from btap.modeling.hvac import control_zones
        model, zones, loops = _built(SHARED)
        self.assertEqual(1, len(loops))
        self.assertTrue(control_zones.is_marked(loops[0]))
        self.assertEqual([zones[0].nameString()], _control_zones(loops[0]))

    def test_a_chosen_zone_is_not_marked(self):
        from btap.modeling.hvac import control_zones
        model = load_fixture()
        from btap import modeling
        from btap._compat import sorted_by_name
        zones = sorted_by_name(model.getThermalZones())
        loop = modeling.build_system(model, SHARED, zones, control_zone=zones[2]).air_loops[0]
        self.assertFalse(control_zones.is_marked(loop))
        self.assertEqual([zones[2].nameString()], _control_zones(loop))

    def test_one_unit_per_zone_has_nothing_to_elect(self):
        from btap.modeling.hvac import control_zones
        model, _, loops = _built(PER_ZONE)
        self.assertGreater(len(loops), 1)
        self.assertFalse(any(control_zones.is_marked(loop) for loop in loops))

    def test_a_multi_zone_system_has_no_control_zone_to_elect(self):
        from btap.modeling.hvac import control_zones
        model, _, loops = _built(MULTI_ZONE)
        self.assertFalse(any(control_zones.is_marked(loop) for loop in loops))

    def test_electing_without_sizing_results_is_refused(self):
        from btap import modeling
        model, _, _ = _built(SHARED)
        with self.assertRaisesRegex(ValueError, "needs sizing results"):
            modeling.elect_control_zones(model)

    def test_nothing_marked_needs_no_sizing(self):
        from btap import modeling
        model, _, _ = _built(PER_ZONE)
        self.assertEqual({}, modeling.elect_control_zones(model))


@needs_engine
class TestTheElection(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from btap import simulation
        cls.tmp = tempfile.TemporaryDirectory()
        cls.model, cls.zones, cls.loops = _built(SHARED)
        simulation.run(cls.model, run_dir=cls.tmp.name,
                       weather={"epw": str(EPW), "ddy": str(DDY)}, sizing_only=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_control_moves_to_the_largest_design_heating_load(self):
        from btap import modeling
        from btap._compat import opt
        from btap.audit import AuditLog
        loads = {z.nameString(): opt(z.autosizedHeatingDesignLoad()) for z in self.zones}
        largest = max(loads, key=loads.get)
        self.assertNotEqual(self.zones[0].nameString(), largest,
                            "the fixture must not elect the provisional zone, "
                            "or the test cannot see the move")
        audit = AuditLog()
        elected = modeling.elect_control_zones(self.model, audit=audit)
        self.assertEqual({self.loops[0].nameString(): largest}, elected)
        self.assertEqual([largest], _control_zones(self.loops[0]))
        entry = audit.entries[-1]
        self.assertEqual("decision", entry["level"])
        self.assertEqual(largest, entry["value"])
        self.assertEqual([self.zones[0].nameString()], entry["inputs"]["provisional"])


@needs_engine
class TestThePipelineElectsWhatItBuilds(unittest.TestCase):
    """The CALL SITE: `--hvac-system` builds a marked shared unit, and the
    pipeline elects its control zone after the proposed sizing run."""

    def test_the_proposed_is_elected_after_sizing(self):
        from btap._compat import sorted_by_name
        from btap._sdk import load_model
        from btap.codes import performance_compliance
        from btap.modeling.hvac import catalog_report
        with tempfile.TemporaryDirectory() as run_dir, warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = load_model(str(catalog_report.FIXTURE))
            spaces = {s.nameString(): ["Space Function", "Office enclosed > 25 m2"]
                      for s in sorted_by_name(model.getSpaces())}
            result = performance_compliance(
                model, code="necb2020", simulate="sizing", hdd=3890, run_dir=run_dir,
                weather={"epw": str(EPW), "ddy": str(DDY)},
                building={"storeys": 1},
                necb_loads={"space_type_map": spaces,
                            "hvac_system": EXPLICITLY_SHARED})
        entries = [e for e in result.audit.entries
                   if e["action"].startswith("shared unit controlled from the zone")]
        self.assertEqual(1, len(entries))
        self.assertEqual("proposed building", entries[0]["building"])


if __name__ == "__main__":
    unittest.main()


@needs_sdk
class TestTheRules(unittest.TestCase):

    def test_each_rule_is_recorded_on_the_loop(self):
        from btap.modeling.hvac import control_zones
        self.assertEqual({"heating", "cooling"}, set(control_zones.RULES))
        for name, mark in control_zones.RULES.items():
            with self.subTest(rule=name):
                model, _, loops = _built(SHARED, control_zone=name)
                self.assertEqual(mark, control_zones.marked_rule(loops[0]))

    def test_an_unknown_rule_is_refused(self):
        for name in ("warmest", "seasonal"):
            with self.subTest(rule=name), self.assertRaisesRegex(ValueError, "control zone rule"):
                _built(SHARED, control_zone=name)


@needs_engine
class TestTheCoolingRule(unittest.TestCase):

    def test_control_moves_to_the_largest_design_cooling_load(self):
        from btap import modeling, simulation
        from btap._compat import opt
        from btap.audit import AuditLog
        model, zones, loops = _built(SHARED, control_zone="cooling")
        with tempfile.TemporaryDirectory() as run_dir:
            simulation.run(model, run_dir=run_dir, sizing_only=True,
                           weather={"epw": str(EPW), "ddy": str(DDY)})
        cooling = {z.nameString(): opt(z.autosizedCoolingDesignLoad()) for z in zones}
        heating = {z.nameString(): opt(z.autosizedHeatingDesignLoad()) for z in zones}
        largest = max(cooling, key=cooling.get)
        self.assertNotEqual(max(heating, key=heating.get), largest,
                            "the fixture must elect different zones by heating and "
                            "by cooling, or the test cannot tell the rules apart")
        audit = AuditLog()
        self.assertEqual({loops[0].nameString(): largest},
                         modeling.elect_control_zones(model, audit=audit))
        self.assertEqual([largest], _control_zones(loops[0]))
        self.assertIn("largest design cooling load", audit.entries[-1]["action"])
