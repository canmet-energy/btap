"""Issue #200 — disclose a supply-air setpoint that derives from ITSELF.

`SetpointManager:MixedAir` computes its target from a reference node minus fan
heat. Correct on an OA system's mixed-air node. Point two of them at each
other and the pair has no fixed point: every timestep subtracts fan heat
again, so the target runs away downward.

EnergyPlus reports this as WARNINGS, never an error. The run completes and the
numbers look plausible, which is the whole hazard — measured on the three
`gagetown_coldlake_Office_*` archetypes: supply-air mean -48.5 C, reported
setpoint below -1000 C, ~390,000 warnings, and about 19.5% of annual site
energy burned cooling against terminal reheat.

Those archetypes come from `measures/dnd_analysis` (`ColdLakeVintageMaker`) in
the legacy `canmet-energy/osruby`, which will NOT be fixed — this project is
meant to replace it. So the defect is permanent in any model regenerated from
that measure, and detection here is the only defence.

The fixtures are built in-process: this guard reads object REFERENCES, so a
constructed cycle is a faithful reproduction. (Contrast
`test_teardown_preserves_exhaust_fans.py`, where the hazard is emergent and
nine synthetic attempts failed to reproduce it.)
"""

from __future__ import annotations

import unittest

from tests.support import needs_sdk


@needs_sdk
class TestSetpointReferenceCycleGuard(unittest.TestCase):

    def setUp(self):
        import openstudio

        self.openstudio = openstudio
        self.model = openstudio.model.Model()
        self.always_on = openstudio.model.ScheduleConstant(self.model)
        self.always_on.setValue(1.0)

    def _loop_with_fan(self, name):
        """An air loop with a fan and an OA SYSTEM.

        The OA system is not decoration: a standalone `Node` cannot host a
        setpoint manager (`addToNode` returns False), so the mixed-air and
        relief nodes it creates are the only realistic places to put the
        second manager — which is also exactly where the real defect lives.
        """
        os = self.openstudio
        loop = os.model.AirLoopHVAC(self.model)
        loop.setName(name)
        fan = os.model.FanConstantVolume(self.model, self.always_on)
        fan.addToNode(loop.supplyInletNode())
        controller = os.model.ControllerOutdoorAir(self.model)
        oa_system = os.model.AirLoopHVACOutdoorAirSystem(self.model,
                                                         controller)
        oa_system.addToNode(loop.supplyInletNode())
        return loop, oa_system

    def _oa_nodes(self, oa_system):
        """The OA-system nodes that can actually HOST a setpoint manager.

        Measured, not assumed — of the four, only two accept one:

            mixed       Node 6             hosts_manager=True
            return      Node 1             hosts_manager=True
            relief      Relief Node        hosts_manager=False
            outdoorAir  Outboard OA Node   hosts_manager=False

        Including the relief node made the fixture's own `addToNode` assertion
        fail, which read as a guard failure until I checked.
        """
        from btap._compat import opt

        out = []
        for accessor in (oa_system.mixedAirModelObject,
                         oa_system.returnAirModelObject):
            obj = accessor()
            if obj.is_initialized():
                node = opt(obj).to_Node()
                if node.is_initialized():
                    out.append(node.get())
        return out

    def _mixed_air(self, sets, reference):
        """Attach FIRST, then set the reference.

        `SetpointManagerMixedAir::addToNode` OVERWRITES the reference setpoint
        node with the node being attached to. Setting the reference first
        silently loses it and leaves a one-node self-reference — which is how
        my first version of this test built 1-node cycles while believing it
        had built 2- and 3-node rings, and blamed the detector for reporting
        length 1.
        """
        os = self.openstudio
        manager = os.model.SetpointManagerMixedAir(self.model)
        self.assertTrue(manager.addToNode(sets),
                        f'{sets.nameString()} cannot host a setpoint manager')
        self.assertTrue(manager.setReferenceSetpointNode(reference))
        return manager

    def cycles(self):
        from btap.modeling.hvac.classify import _setpoint_reference_cycles

        return _setpoint_reference_cycles(self.model)

    def warnings_from_characterize(self):
        from btap.audit import AuditLog
        from btap.modeling.hvac import classify

        audit = AuditLog()
        classify.characterize(self.model, audit=audit)
        return [e for e in audit.warnings
                if 'DERIVES FROM ITSELF' in e['action']]

    # ---------------------------------------------------------------- cycles

    def test_a_two_node_cycle_is_detected(self):
        loop, oa = self._loop_with_fan('Broken VAV')
        outlet = loop.supplyOutletNode()
        other = self._oa_nodes(oa)[0]
        self._mixed_air(sets=outlet, reference=other)
        self._mixed_air(sets=other, reference=outlet)

        found = self.cycles()
        self.assertEqual(1, len(found), found)
        self.assertEqual('Broken VAV', found[0][0])
        self.assertIn(outlet.nameString(), found[0][1])

    def test_the_cycle_is_disclosed_as_an_audit_WARNING(self):
        """Never silent: the AuditLog contract is that warnings are reported."""
        loop, oa = self._loop_with_fan('Broken VAV')
        other = self._oa_nodes(oa)[0]
        self._mixed_air(sets=loop.supplyOutletNode(), reference=other)
        self._mixed_air(sets=other, reference=loop.supplyOutletNode())

        warnings = self.warnings_from_characterize()
        self.assertEqual(1, len(warnings))
        entry = warnings[0]
        self.assertEqual('Broken VAV', entry['target'])
        self.assertIn('->', entry['value'],
                      'the warning must name the cycle PATH, so a reader can '
                      'find the offending managers')
        self.assertEqual(2, entry['inputs']['cycle_length'])

    def test_the_action_text_is_SHOUTED(self):
        """`btap.audit` text is case-sensitive: violations are shouted so the
        report checklist classifier can tell them from passes."""
        loop, oa = self._loop_with_fan('Broken VAV')
        other = self._oa_nodes(oa)[0]
        self._mixed_air(sets=loop.supplyOutletNode(), reference=other)
        self._mixed_air(sets=other, reference=loop.supplyOutletNode())

        action = self.warnings_from_characterize()[0]['action']
        shouted = action.split(' — ')[0]
        self.assertEqual(shouted.upper(), shouted, action)

    # --------------------------------------------------------- NO false alarm

    def test_CONTROL_a_correct_mixed_air_arrangement_is_NOT_flagged(self):
        """The shape every working loop uses, and it must stay silent.

        A MixedAir manager on an OA-system node REFERENCING the supply outlet
        is correct and common — the four CV loops in those same archetypes do
        exactly this (nodes 92, 93, 94 -> ref 86). If this fires, the guard is
        useless because it condemns the normal case.
        """
        loop, oa = self._loop_with_fan('Healthy loop')
        outlet = loop.supplyOutletNode()
        for node in self._oa_nodes(oa):
            self._mixed_air(sets=node, reference=outlet)

        self.assertEqual([], self.cycles())
        self.assertEqual([], self.warnings_from_characterize())

    def test_CONTROL_a_loop_with_no_setpoint_manager_is_not_flagged(self):
        self._loop_with_fan('Bare loop')
        self.assertEqual([], self.cycles())

    def test_a_scheduled_manager_TERMINATES_the_chain(self):
        """The repair shape must read as clean.

        A `Scheduled` manager takes its target from a schedule, not from
        another node, so it ends the walk. This is what the archetypes carry
        after the fix: `Scheduled @ 13.0` on the VAV outlet.
        """
        os = self.openstudio
        loop, oa = self._loop_with_fan('Repaired VAV')
        outlet = loop.supplyOutletNode()
        target = os.model.ScheduleConstant(self.model)
        target.setValue(13.0)
        os.model.SetpointManagerScheduled(self.model, target).addToNode(outlet)
        for node in self._oa_nodes(oa):
            self._mixed_air(sets=node, reference=outlet)

        self.assertEqual([], self.cycles())

    def test_a_longer_cycle_is_also_detected(self):
        """Three managers in a ring. A check that only compared a node with
        its immediate reference would miss this, and the walk must not loop
        forever on it either."""
        loop, oa = self._loop_with_fan('Three-ring VAV')
        outlet = loop.supplyOutletNode()
        nodes = self._oa_nodes(oa)
        self.assertGreaterEqual(len(nodes), 2, 'need two real OA nodes')
        a, b = nodes[0], nodes[1]
        self._mixed_air(sets=outlet, reference=a)
        self._mixed_air(sets=a, reference=b)
        self._mixed_air(sets=b, reference=outlet)

        found = self.cycles()
        self.assertEqual(1, len(found))
        self.assertEqual(3, len(found[0][1]))


@needs_sdk
class TestTheGuardReachesItsREALCallers(unittest.TestCase):
    """A correct guard that nothing invokes is not a guard.

    `characterize` returns early when `audit is None`, so every caller must
    THREAD its audit. When this guard shipped, two of the three real callers
    did not — `btap.stock.hvac.hvac_section` and
    `btap.costing.hvac.report.classify_unmapped_loops` both ACCEPTED an audit
    and then called `characterize(model)` without it. The recipe writer was
    already threading the audit as far as `hvac_section`, which dropped it, so
    the guard was silent on exactly the path where a reader meets a hand-built
    archetype.

    These tests exercise the PUBLIC entry points rather than `characterize`,
    because testing the guard directly is what let that ship.
    """

    def _model_with_a_cycle(self):
        import openstudio

        model = openstudio.model.Model()
        sched = openstudio.model.ScheduleConstant(model)
        sched.setValue(1.0)
        loop = openstudio.model.AirLoopHVAC(model)
        loop.setName('Cyclic VAV')
        openstudio.model.FanConstantVolume(model, sched).addToNode(
            loop.supplyInletNode())
        oa = openstudio.model.AirLoopHVACOutdoorAirSystem(
            model, openstudio.model.ControllerOutdoorAir(model))
        oa.addToNode(loop.supplyInletNode())
        from btap._compat import opt

        mixed = opt(oa.mixedAirModelObject()).to_Node().get()
        outlet = loop.supplyOutletNode()
        for sets, reference in ((outlet, mixed), (mixed, outlet)):
            manager = openstudio.model.SetpointManagerMixedAir(model)
            manager.addToNode(sets)
            manager.setReferenceSetpointNode(reference)
        return model

    def _cycle_warnings(self, audit):
        return [e for e in audit.warnings
                if 'DERIVES FROM ITSELF' in e['action']]

    def test_the_recipe_WRITER_discloses_it(self):
        from btap.audit import AuditLog
        from btap.stock.hvac import hvac_section

        audit = AuditLog()
        hvac_section(self._model_with_a_cycle(), audit=audit)

        self.assertEqual(
            1, len(self._cycle_warnings(audit)),
            'hvac_section accepts an audit; it must PASS it to characterize, '
            'or the guard is silent on the recipe-writer path')

    def test_the_COSTING_loop_classifier_discloses_it(self):
        from btap.audit import AuditLog
        from btap.costing.hvac.report import classify_unmapped_loops

        audit = AuditLog()
        classify_unmapped_loops(self._model_with_a_cycle(), {}, audit=audit)

        self.assertEqual(1, len(self._cycle_warnings(audit)))

    def test_CONTROL_a_clean_model_stays_quiet_on_both_paths(self):
        import openstudio

        from btap.audit import AuditLog
        from btap.costing.hvac.report import classify_unmapped_loops
        from btap.stock.hvac import hvac_section

        def clean():
            model = openstudio.model.Model()
            sched = openstudio.model.ScheduleConstant(model)
            sched.setValue(1.0)
            loop = openstudio.model.AirLoopHVAC(model)
            loop.setName('Healthy')
            openstudio.model.FanConstantVolume(model, sched).addToNode(
                loop.supplyInletNode())
            return model

        for label, call in (
                ('hvac_section', lambda a: hvac_section(clean(), audit=a)),
                ('classify_unmapped_loops',
                 lambda a: classify_unmapped_loops(clean(), {}, audit=a))):
            with self.subTest(path=label):
                audit = AuditLog()
                call(audit)
                self.assertEqual([], self._cycle_warnings(audit))
