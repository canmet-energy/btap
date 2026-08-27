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
from btap.necb import hvac
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
        hvac.apply_efficiencies(model, vintage='2020', audit=audit)

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
        hvac.apply_efficiencies(reference, vintage='2020', audit=audit, proposed=proposed)

        self.assertAlmostEqual(2000.0, ref_pump.ratedPowerConsumption().get(), delta=0.1,
                               msg='combined proposed intensity (100 W per L/s) x reference '
                                   'flow (20 L/s)')
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
        hvac.apply_efficiencies(reference, vintage='2020', audit=AuditLog(), proposed=proposed)
        self.assertAlmostEqual(600.0, pump.ratedPowerConsumption().get(), delta=0.1,
                               msg='120 W/(L/s) x 5 L/s')

    def test_undeterminable_proposed_pumps_warn_never_silent(self):
        proposed = openstudio.model.Model()
        loop_with_vsd_pump(proposed, 'Heating')  # autosized, no sql -> nothing readable

        reference = openstudio.model.Model()
        _, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.02)
        audit = AuditLog()
        hvac.apply_efficiencies(reference, vintage='2020', audit=audit, proposed=proposed)

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
        hvac.apply_efficiencies(reference, vintage='2020', audit=audit, proposed=proposed)

        self.assertTrue(any('NO Cooling-type loop pumps' in w['action'] for w in audit.warnings),
                        'missing loop-type correspondence warns')

    def test_2025_citations_renumbered(self):
        model = openstudio.model.Model()
        loop_with_vsd_pump(model, 'Heating', flow=0.01)
        audit = AuditLog()
        hvac.apply_efficiencies(model, vintage='2025', audit=audit)
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
        hvac.apply_efficiencies(reference, vintage='2020', audit=audit, proposed=proposed)

        # reference SWH pump untouched: no hard power, no riding-curve coefficients
        self.assertTrue(ref_swh_pump.ratedPowerConsumption().empty(),
                        'SWH circulator gets NO transferred power')
        self.assertAlmostEqual(0.0, ref_swh_pump.coefficient1ofthePartLoadPerformanceCurve(),
                               delta=1e-6)
        self.assertTrue(any(e['level'] == 'info' and 'service water heating loop' in e['action']
                            for e in audit.entries))
        # heating intensity clean of the SWH pump: 800 W / 10 L/s = 80 W/(L/s) x 20 L/s
        self.assertAlmostEqual(1600.0, ref_pump.ratedPowerConsumption().get(), delta=0.1,
                               msg='Heating intensity excludes the proposed SWH circulator')

    def test_transfer_reconciles_unphysical_inherited_head(self):
        proposed = openstudio.model.Model()
        # weak: 10 W/(L/s)
        loop_with_vsd_pump(proposed, 'Heating', flow=0.010, power=100.0)

        reference = openstudio.model.Model()
        # -> 10 W transferred
        _, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.001)
        # legacy SWH-scale head: flow x head / power >> motor eff
        ref_pump.setRatedPumpHead(1_927_540.0)
        audit = AuditLog()
        hvac.apply_efficiencies(reference, vintage='2020', audit=audit, proposed=proposed)

        power = ref_pump.ratedPowerConsumption().get()
        self.assertAlmostEqual(10.0, power, delta=0.1, msg='transferred power is authoritative')
        implied = 0.001 * ref_pump.ratedPumpHead() / power
        self.assertLessEqual(implied, ref_pump.motorEfficiency() + 1e-6,
                             'head reconciled so implied efficiency stays physical '
                             '(E+ fatal otherwise)')
        self.assertTrue(any('head reduced' in e['action'] for e in audit.warnings))

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
        hvac.apply_efficiencies(reference, vintage='2020', audit=audit, proposed=proposed)

        power = ref_pump.ratedPowerConsumption().get()
        self.assertAlmostEqual(450.0, power, delta=0.5,
                               msg='combined power clamped to 4.5 W/kW x 100 kW')
        implied = 0.020 * ref_pump.ratedPumpHead() / power
        self.assertLessEqual(implied, ref_pump.motorEfficiency() + 1e-6,
                             'clamped triple stays physical')
        decision = next((e for e in audit.entries
                         if str(e.get('article') or '') == '5.2.6.3.(1); 8.4.4.1.(2)'), None)
        self.assertIsNotNone(decision, 'clamp decision audited with both articles')
        self.assertEqual('Heating', decision['inputs']['system_type'])
        self.assertAlmostEqual(4000.0, decision['inputs']['before_w'], delta=1.0)

    def test_pump_power_cap_leaves_compliant_transfer_untouched(self):
        proposed = openstudio.model.Model()
        # 40 W/(L/s)
        loop_with_vsd_pump(proposed, 'Heating', flow=0.010, power=400.0)

        reference = openstudio.model.Model()
        # transfer -> 800 W
        ref_loop, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.020)
        self.add_boiler(ref_loop, 300.0)  # cap = 1350 W > 800 W
        audit = AuditLog()
        hvac.apply_efficiencies(reference, vintage='2020', audit=audit, proposed=proposed)

        self.assertAlmostEqual(800.0, ref_pump.ratedPowerConsumption().get(), delta=0.1,
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
            proposed, vintage='2020',
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
            proposed, vintage='2020',
            building={'storeys': 1,
                      'zone_types': {z.nameString(): 'Office - enclosed'
                                     for z in proposed.getThermalZones()}})
        self.assertTrue(any(e.get('article') == '8.4.3.2.(1)'
                            and 'default retained' in e['action']
                            for e in result.audit.entries))


if __name__ == '__main__':
    unittest.main()
