"""8.4.4.14 (2025: 8.4.5.14) hydronic pump rules, applied by the efficiency
pass: Table 8.4.4.14. riding-curve coefficients + the below-D minimum-flow
clamp on every variable-speed pump (sentences (4)-(5)), and the (1)-(3)
combined W/(L/s) power transfer from a sized proposed model. All hostile
outcomes assert MODEL VALUES; unknowns must warn, never stay silent.

Also D-14 (8.4.3.2.(1)): reference air systems inherit the PROPOSED operating
schedule; zones with no proposed air system keep the builder default."""

from __future__ import annotations

import unittest

import openstudio

import btap.modeling as modeling
from btap.audit import AuditLog
from btap.codes.necb import hvac
from btap.codes.necb.hvac.efficiency import _pump_power_from_triple
from tests.necb.hvac_helpers import load_fixture, sorted_zones
from tests.support import needs_sdk

RIDING = {'a': 0.227143, 'b': 1.178929, 'c': -0.41071, 'd': 0.47, 'e': 0.68}


def loop_with_vsd_pump(model, type_, flow=None, power=None):
    loop_ = openstudio.model.PlantLoop(model)
    loop_.sizingPlant().setLoopType(type_)
    pump = openstudio.model.PumpVariableSpeed(model)
    if flow:
        pump.setRatedFlowRate(flow)
    if power:
        pump.setRatedPowerConsumption(power)
    pump.addToNode(loop_.supplyInletNode())
    return loop_, pump


@needs_sdk
class TestNecbPumpRules(unittest.TestCase):

    def test_riding_curve_coefficients_and_floor_applied(self):
        # the below-D floor approximation the code comment claims must actually hold
        poly_at_d = RIDING['a'] + RIDING['b'] * RIDING['d'] + RIDING['c'] * RIDING['d'] ** 2
        self.assertAlmostEqual(RIDING['e'], poly_at_d, delta=0.02,
                               msg='polynomial at D equals E within table rounding')

        model = openstudio.model.Model()
        _, pump = loop_with_vsd_pump(model, 'Cooling', flow=0.02)
        audit = AuditLog()
        hvac.apply_efficiencies(model, code='necb2020', audit=audit)

        self.assertAlmostEqual(RIDING['a'], pump.coefficient1ofthePartLoadPerformanceCurve(),
                               delta=1e-6)
        self.assertAlmostEqual(RIDING['b'], pump.coefficient2ofthePartLoadPerformanceCurve(),
                               delta=1e-6)
        self.assertAlmostEqual(RIDING['c'], pump.coefficient3ofthePartLoadPerformanceCurve(),
                               delta=1e-6)
        self.assertAlmostEqual(0.0, pump.coefficient4ofthePartLoadPerformanceCurve(), delta=1e-9)
        self.assertAlmostEqual(RIDING['d'] * 0.02, pump.minimumFlowRate(), delta=1e-9,
                               msg='below-D floor via min-flow clamp')
        self.assertTrue(any('8.4.4.14.(4)-(5)' in str(e.get('article') or '')
                            for e in audit.entries))
        self.assertTrue(any(e['level'] == 'info' and 'no proposed model supplied' in e['action']
                            for e in audit.entries),
                        'transfer skip is noted, never silent')

    def test_power_transfer_uses_combined_w_per_l_s_by_loop_type(self):
        proposed = openstudio.model.Model()
        loop_with_vsd_pump(proposed, 'Heating', flow=0.010, power=800.0)
        # combined: 1500 W / 15 L/s
        loop_with_vsd_pump(proposed, 'Heating', flow=0.005, power=700.0)

        reference = openstudio.model.Model()
        _, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.020)  # 20 L/s
        audit = AuditLog()
        hvac.apply_efficiencies(reference, code='necb2020', audit=audit, proposed=proposed)

        # D-92: power is not hard-set any more — head, shaft coefficient and
        # motor efficiency are stated and EnergyPlus derives the power. The
        # number it will derive is what this asserts.
        self.assertTrue(ref_pump.ratedPowerConsumption().empty(),
                        'the reference pump is left autosized for E+ to size')
        self.assertAlmostEqual(2000.0, _pump_power_from_triple(ref_pump, 0.020), delta=0.1,
                               msg='combined proposed intensity (100 W per L/s) x reference '
                                   'flow (20 L/s), derived from the triple')
        self.assertGreaterEqual(ref_pump.designShaftPowerPerUnitFlowRatePerUnitHead(), 1.0,
                                'a stated pump efficiency no pump could have is an E+ fatal')
        decision = next((e for e in audit.entries
                         if e.get('article') == '8.4.4.14.(1)-(3)'), None)
        self.assertIsNotNone(decision, 'transfer decision audited')
        self.assertEqual(2, decision['inputs']['proposed_pumps'],
                         'sentence (2): both pumps combined')
        self.assertAlmostEqual(100.0, decision['inputs']['proposed_w_per_l_s'], delta=0.01)

    def test_constant_speed_reference_pump_gets_transfer_but_no_curve(self):
        proposed = openstudio.model.Model()
        # 120 W/(L/s)
        loop_with_vsd_pump(proposed, 'Condenser', flow=0.010, power=1200.0)

        reference = openstudio.model.Model()
        loop_ = openstudio.model.PlantLoop(reference)
        loop_.sizingPlant().setLoopType('Condenser')
        pump = openstudio.model.PumpConstantSpeed(reference)
        pump.setRatedFlowRate(0.005)
        pump.addToNode(loop_.supplyInletNode())
        hvac.apply_efficiencies(reference, code='necb2020', audit=AuditLog(), proposed=proposed)
        self.assertAlmostEqual(600.0, _pump_power_from_triple(pump, 0.005), delta=0.1,
                               msg='120 W/(L/s) x 5 L/s')
        # "no curve" is structural, not an assertable value: PumpConstantSpeed
        # has no part-load coefficient fields for (4)-(5) to write.
        self.assertFalse(hasattr(pump, 'coefficient1ofthePartLoadPerformanceCurve'))

    def test_undeterminable_proposed_pumps_warn_never_silent(self):
        proposed = openstudio.model.Model()
        loop_with_vsd_pump(proposed, 'Heating')  # autosized, no sql -> nothing readable

        reference = openstudio.model.Model()
        _, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.02)
        audit = AuditLog()
        hvac.apply_efficiencies(reference, code='necb2020', audit=audit, proposed=proposed)

        self.assertTrue(any('NOT transferred' in w['action'] for w in audit.warnings),
                        'undeterminable proposed pumps warn loudly')
        self.assertTrue(ref_pump.ratedPowerConsumption().empty(),
                        'no transfer happened — autosizing retained')
        self.assertAlmostEqual(RIDING['a'], ref_pump.coefficient1ofthePartLoadPerformanceCurve(),
                               delta=1e-6, msg='Table curves still applied')

    def test_missing_loop_type_correspondence_warns(self):
        proposed = openstudio.model.Model()
        loop_with_vsd_pump(proposed, 'Heating', flow=0.010, power=800.0)

        reference = openstudio.model.Model()
        loop_with_vsd_pump(reference, 'Cooling', flow=0.02)  # no Cooling pumps in proposed
        audit = AuditLog()
        hvac.apply_efficiencies(reference, code='necb2020', audit=audit, proposed=proposed)

        self.assertTrue(any('NO Cooling-type loop pumps' in w['action'] for w in audit.warnings),
                        'missing loop-type correspondence warns')

    def test_2025_citations_renumbered(self):
        model = openstudio.model.Model()
        loop_with_vsd_pump(model, 'Heating', flow=0.01)
        audit = AuditLog()
        hvac.apply_efficiencies(model, code='necb2025', audit=audit)
        self.assertTrue(any('8.4.5.14.(4)-(5)' in str(e.get('article') or '')
                            for e in audit.entries),
                        '2025 cites the renumbered article')

    # Gas-variant sweep finding (D-27): the SWH circulator is OUTSIDE 8.4.4.14 —
    # transferring the space-heating intensity onto it (8 W vs a 1.9 MPa head)
    # implies >100% pump efficiency and is an E+ FATAL.
    def test_swh_loop_excluded_from_pump_rules_and_stats(self):
        proposed = openstudio.model.Model()
        loop_with_vsd_pump(proposed, 'Heating', flow=0.010, power=800.0)
        # a proposed SWH loop whose extreme intensity would poison the Heating stats
        swh_p, _ = loop_with_vsd_pump(proposed, 'Heating', flow=0.00002, power=500.0)
        openstudio.model.WaterHeaterMixed(proposed).addToNode(swh_p.supplyOutletNode())

        reference = openstudio.model.Model()
        _, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.020)
        ref_swh, ref_swh_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.00002)
        openstudio.model.WaterHeaterMixed(reference).addToNode(ref_swh.supplyOutletNode())
        audit = AuditLog()
        hvac.apply_efficiencies(reference, code='necb2020', audit=audit, proposed=proposed)

        # reference SWH pump untouched: no hard power, no riding-curve coefficients
        self.assertTrue(ref_swh_pump.ratedPowerConsumption().empty(),
                        'SWH circulator gets NO transferred power')
        self.assertAlmostEqual(0.0, ref_swh_pump.coefficient1ofthePartLoadPerformanceCurve(),
                               delta=1e-6)
        self.assertTrue(any(e['level'] == 'info' and 'service water heating loop' in e['action']
                            for e in audit.entries))
        # heating intensity clean of the SWH pump: 800 W / 10 L/s = 80 W/(L/s) x 20 L/s
        self.assertAlmostEqual(1600.0, _pump_power_from_triple(ref_pump, 0.020), delta=0.1,
                               msg='Heating intensity excludes the proposed SWH circulator')

    # D-92 replaced the repair with a statement. The pass writes head, shaft
    # coefficient and motor efficiency and leaves power autosized, so there is
    # no hard-set power for an inherited head to contradict: the legacy head is
    # OVERWRITTEN rather than reduced after the fact, and the E+ fatal
    # ("Calculated Pump Efficiency > 100%") is unreachable by construction.
    def test_unphysical_inherited_head_is_replaced_not_reconciled(self):
        proposed = openstudio.model.Model()
        # weak: 10 W/(L/s), and a triple implying 1790% total efficiency
        loop_with_vsd_pump(proposed, 'Heating', flow=0.010, power=100.0)

        reference = openstudio.model.Model()
        _, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.001)
        # legacy SWH-scale head: flow x head / power >> motor eff
        ref_pump.setRatedPumpHead(1_927_540.0)
        audit = AuditLog()
        hvac.apply_efficiencies(reference, code='necb2020', audit=audit, proposed=proposed)

        # 10 W/(L/s) x 1000 x 0.9 motor x 0.78 pump
        self.assertAlmostEqual(7020.0, ref_pump.ratedPumpHead(), delta=1.0,
                               msg='the legacy head is replaced by the stated one')
        self.assertAlmostEqual(10.0, _pump_power_from_triple(ref_pump, 0.001), delta=0.1,
                               msg='the intensity still lands on the reference flow')
        self.assertGreaterEqual(ref_pump.designShaftPowerPerUnitFlowRatePerUnitHead(), 1.0,
                                'the stated pump efficiency is one a pump can have')
        self.assertEqual([], [e for e in audit.warnings if 'head reduced' in e['action']],
                         'nothing to reconcile: no hard-set power was ever written')
        # the proposed pump could not state a usable efficiency, so (3) supplies
        # the basis and the physical split is declared, never silently assumed
        self.assertTrue(any('efficiency not usable' in e['action']
                            and e.get('article') == '8.4.4.14.(3)' for e in audit.entries),
                        'the fallback to a physical split is audited')

    @staticmethod
    def add_boiler(loop_, kw):
        boiler = openstudio.model.BoilerHotWater(loop_.model())
        boiler.setNominalCapacity(kw * 1000.0)
        loop_.addSupplyBranchForComponent(boiler)
        return boiler

    # D-38 (A3 ruled min-wins): a transferred intensity ABOVE the Table 5.2.6.3
    # cap is clamped to cap x the loop's peak thermal demand (heating: 4.5 W/kW),
    # with the head kept physical; the clamp is audited citing both articles.
    def test_pump_power_cap_clamps_transfer_above_cap(self):
        proposed = openstudio.model.Model()
        # 200 W/(L/s)
        loop_with_vsd_pump(proposed, 'Heating', flow=0.004, power=800.0)

        reference = openstudio.model.Model()
        # transfer -> 4000 W
        ref_loop, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.020)
        self.add_boiler(ref_loop, 100.0)  # cap = 4.5 x 100 = 450 W
        audit = AuditLog()
        hvac.apply_efficiencies(reference, code='necb2020', audit=audit, proposed=proposed)

        # D-92: the cap moves HEAD at constant efficiency, so the clamped pump
        # is exactly as physical as the unclamped one.
        self.assertAlmostEqual(450.0, _pump_power_from_triple(ref_pump, 0.020), delta=0.5,
                               msg='combined power clamped to 4.5 W/kW x 100 kW')
        self.assertGreaterEqual(ref_pump.designShaftPowerPerUnitFlowRatePerUnitHead(), 1.0,
                                'clamping does not invent an impossible efficiency')
        decision = next((e for e in audit.entries
                         if str(e.get('article') or '') == '5.2.6.3.(1); 8.4.4.1.(2)'), None)
        self.assertIsNotNone(decision, 'clamp decision audited with both articles')
        self.assertEqual('Heating', decision['inputs']['system_type'])
        self.assertAlmostEqual(4000.0, decision['inputs']['before_w'], delta=1.0)

    # Sol, PR #50 P1: every cap test above runs the transfer first, so all of
    # them see a pump D-92 has already normalized to PowerPerFlowPerPressure
    # with autosized power — the one shape where scaling head moves the power.
    # The cap is documented to apply "with or without a proposed model", and on
    # the other two power sources head is absent from E+'s sizing equation, so
    # a head-only clamp reported a reduction it never made.
    def capped_loop(self, mode, flow=0.020):
        """A 100 kW heating loop (cap = 4.5 W/kW x 100 kW = 450 W) whose pump
        draws 10 kW through the given power source, and NO proposed model."""
        model = openstudio.model.Model()
        loop_, pump = loop_with_vsd_pump(model, 'Heating', flow=flow)
        self.add_boiler(loop_, 100.0)
        if mode == 'hard':
            pump.setRatedPowerConsumption(10_000.0)
        elif mode == 'per_flow':
            pump.setDesignPowerSizingMethod('PowerPerFlow')
            pump.setDesignElectricPowerPerUnitFlowRate(10_000.0 / flow)
        return model, pump

    def test_cap_clamps_a_hard_set_pump_with_no_proposed_model(self):
        model, pump = self.capped_loop('hard')
        audit = AuditLog()
        hvac.apply_efficiencies(model, code='necb2020', audit=audit)

        self.assertAlmostEqual(450.0, _pump_power_from_triple(pump, 0.020), delta=0.5,
                               msg='the clamp reaches a hard-set power, not just the head')
        self.assertAlmostEqual(450.0, pump.ratedPowerConsumption().get(), delta=0.5,
                               msg='and it is the hard value E+ reads that moved')
        implied = 0.020 * pump.ratedPumpHead() / 450.0 / pump.motorEfficiency()
        self.assertLessEqual(implied, 1.0 + 1e-9,
                             'head scaled with power, so cutting it cannot imply >100% efficiency')

    def test_cap_clamps_a_power_per_flow_pump_with_no_proposed_model(self):
        model, pump = self.capped_loop('per_flow')
        audit = AuditLog()
        hvac.apply_efficiencies(model, code='necb2020', audit=audit)

        self.assertAlmostEqual(450.0, _pump_power_from_triple(pump, 0.020), delta=0.5,
                               msg='PowerPerFlow sizes from W/(m3/s); head is not in the equation')
        self.assertAlmostEqual(450.0 / 0.020, pump.designElectricPowerPerUnitFlowRate(), delta=1.0,
                               msg='so the intensity itself is what the clamp must move')

    def test_a_proposed_pump_stating_the_impossible_is_left_out_of_the_average(self):
        """Sol, PR #50 P2: validating only the aggregate lets an impossible pump
        hide inside a plausible mean — 55.6% averaged with 111.1% reads as 60.6%,
        and the reference inherits an efficiency no proposed pump has."""
        proposed = openstudio.model.Model()
        loop_ = openstudio.model.PlantLoop(proposed)
        loop_.sizingPlant().setLoopType('Heating')
        for flow, power, head in ((0.010, 1000.0, 50_000.0), (0.001, 100.0, 100_000.0)):
            p = openstudio.model.PumpVariableSpeed(proposed)
            p.setRatedFlowRate(flow)
            p.setRatedPowerConsumption(power)
            p.setRatedPumpHead(head)
            p.addToNode(loop_.supplyInletNode())

        reference = openstudio.model.Model()
        _, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.020)
        audit = AuditLog()
        hvac.apply_efficiencies(reference, code='necb2020', audit=audit, proposed=proposed)

        stated = 1.0 / ref_pump.designShaftPowerPerUnitFlowRatePerUnitHead()
        self.assertAlmostEqual(0.5556, stated, delta=1e-3,
                               msg='the valid pump alone supplies the efficiency (not the 60.6% blend)')
        self.assertGreaterEqual(ref_pump.designShaftPowerPerUnitFlowRatePerUnitHead(), 1.0)
        self.assertTrue(any('excluded from the flow-weighted split' in e['action']
                            and e.get('article') == '8.4.4.14.(3)' for e in audit.entries),
                        'the exclusion is declared, not silently applied')
        # (2) still combines every pump's power and flow — only the efficiency
        # of the impossible one is discarded.
        decision = next(e for e in audit.entries if e.get('article') == '8.4.4.14.(1)-(3)')
        self.assertEqual(2, decision['inputs']['proposed_pumps'])

    # Sol, PR #50 (residual risk): the SDK refuses a motor efficiency outside
    # (0,1], a non-positive shaft coefficient and a non-finite head — but it
    # ACCEPTS a negative head and a negative rated power. Those reach the cap as
    # negative watts, and because the clamp only fires ABOVE the cap, one
    # malformed pump can drag the combined power under it.
    def test_a_malformed_pump_cannot_certify_an_over_cap_loop(self):
        model = openstudio.model.Model()
        loop_, good = loop_with_vsd_pump(model, 'Heating', flow=0.020)  # 5,110 W, genuinely over cap
        bad = openstudio.model.PumpVariableSpeed(model)
        bad.setRatedFlowRate(0.020)
        bad.setRatedPumpHead(-179_352.0)  # -5,110 W: sums with the good pump to exactly zero
        bad.addToNode(loop_.supplyInletNode())
        self.add_boiler(loop_, 100.0)  # cap = 450 W
        audit = AuditLog()
        hvac.apply_efficiencies(model, code='necb2020', audit=audit)

        self.assertEqual([], [e for e in audit.entries
                              if 'within the Table 5.2.6.3 maximum' in e['action']],
                         'a loop whose combined power cannot be measured is NEVER certified compliant')
        warning = next((w for w in audit.warnings if 'cap NOT APPLIED' in w['action']), None)
        self.assertIsNotNone(warning, 'refusing to evaluate shouts — the cap really was not applied')
        self.assertIn(bad.nameString(), warning['action'], 'the offending pump is named')
        self.assertEqual('5.2.6.3.(1)', warning['article'])

    def test_a_negative_power_proposed_pump_is_left_out_of_the_combination(self):
        """A negative wattage must not subtract from the (2) combination, or the
        reference inherits an intensity lower than any proposed pump draws."""
        proposed = openstudio.model.Model()
        loop_ = openstudio.model.PlantLoop(proposed)
        loop_.sizingPlant().setLoopType('Heating')
        for flow, power in ((0.010, 800.0), (0.010, -500.0)):
            p = openstudio.model.PumpVariableSpeed(proposed)
            p.setRatedFlowRate(flow)
            p.setRatedPowerConsumption(power)
            p.addToNode(loop_.supplyInletNode())

        reference = openstudio.model.Model()
        _, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.020)
        audit = AuditLog()
        hvac.apply_efficiencies(reference, code='necb2020', audit=audit, proposed=proposed)

        # 800 W / 10 L/s = 80 W/(L/s) x 20 L/s — NOT (800-500)/20 = 15 W/(L/s)
        self.assertAlmostEqual(1600.0, _pump_power_from_triple(ref_pump, 0.020), delta=0.1,
                               msg='the malformed pump is excluded, not netted off')
        decision = next(e for e in audit.entries if e.get('article') == '8.4.4.14.(1)-(3)')
        self.assertEqual(1, decision['inputs']['proposed_pumps'],
                         'and it is not counted among the pumps combined')

    def test_pump_power_cap_leaves_compliant_transfer_untouched(self):
        proposed = openstudio.model.Model()
        # 40 W/(L/s)
        loop_with_vsd_pump(proposed, 'Heating', flow=0.010, power=400.0)

        reference = openstudio.model.Model()
        # transfer -> 800 W
        ref_loop, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.020)
        self.add_boiler(ref_loop, 300.0)  # cap = 1350 W > 800 W
        audit = AuditLog()
        hvac.apply_efficiencies(reference, code='necb2020', audit=audit, proposed=proposed)

        self.assertAlmostEqual(800.0, _pump_power_from_triple(ref_pump, 0.020), delta=0.1,
                               msg='below-cap transfer untouched (min-wins)')
        self.assertTrue(any(e['level'] == 'info'
                            and 'within the Table 5.2.6.3 maximum' in e['action']
                            for e in audit.entries),
                        'compliance is stated, never silent')


@needs_sdk
class TestNecbOperatingSchedules(unittest.TestCase):
    """D-14 (8.4.3.2.(1)): reference air systems inherit the PROPOSED operating
    schedule; zones with no proposed air system keep the builder default."""

    def test_reference_inherits_proposed_availability_schedule(self):
        proposed = load_fixture()
        zones = sorted_zones(proposed)
        modeling.build_system(
            proposed, 'PSZ RTU with exhaust Gas and DX Coils and Hot Water Baseboard', zones)
        sched = openstudio.model.ScheduleRuleset(proposed)
        sched.setName('Office Operation 6-18')
        sched.defaultDaySchedule().addValue(openstudio.Time(0, 6), 0.0)
        sched.defaultDaySchedule().addValue(openstudio.Time(0, 18), 1.0)
        sched.defaultDaySchedule().addValue(openstudio.Time(0, 24), 0.0)
        for loop in proposed.getAirLoopHVACs():
            loop.setAvailabilitySchedule(sched)

        result = hvac.reference_hvac(
            proposed, code='necb2020',
            building={'storeys': 1,
                      'zone_types': {z.nameString(): 'Office - enclosed'
                                     for z in proposed.getThermalZones()}})
        ref_loops = result.model.getAirLoopHVACs()
        self.assertTrue(len(ref_loops))
        for loop in ref_loops:
            self.assertEqual('Office Operation 6-18', loop.availabilitySchedule().nameString())
        self.assertTrue(any(e.get('article') == '8.4.3.2.(1)' and e['level'] == 'decision'
                            for e in result.audit.entries))
        # the 5.2.10.1 classification now sees the inherited schedule
        hours = hvac.annual_availability_hours(ref_loops[0])
        self.assertLess(hours, 8000, 'inherited 12h schedule classifies non-continuous')

    def test_no_proposed_air_system_keeps_default_with_note(self):
        proposed = load_fixture()
        # no air loops
        modeling.build_system(proposed, 'Baseboard gas boiler', sorted_zones(proposed))
        result = hvac.reference_hvac(
            proposed, code='necb2020',
            building={'storeys': 1,
                      'zone_types': {z.nameString(): 'Office - enclosed'
                                     for z in proposed.getThermalZones()}})
        self.assertTrue(any(e.get('article') == '8.4.3.2.(1)'
                            and 'default retained' in e['action']
                            for e in result.audit.entries))


if __name__ == '__main__':
    unittest.main()
