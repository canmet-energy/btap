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
from btap.codes.necb.hvac.efficiency import (
    DEFAULT_PUMP_EFFICIENCY,
    _hydraulic_efficiency,
    _loop_role,
    _pump_cap_basis,
    _pump_characteristics_known,
    _pump_power_from_triple,
    _served_zone_names,
)
from tests.necb.hvac_helpers import load_fixture, sorted_zones
from tests.support import needs_sdk

RIDING = {'a': 0.227143, 'b': 1.178929, 'c': -0.41071, 'd': 0.47, 'e': 0.68}


def serve_zones(model, loop_, zones):
    """Give a loop a demand side, so it serves named thermal blocks.

    D-93 corresponds pumps between buildings by ROLE plus SERVED THERMAL
    BLOCKS, so a loop with no demand side corresponds to nothing and the
    transfer declines — correctly, but it makes a bare fixture untestable. A
    water baseboard per zone is the smallest demand side that reaches a zone
    through the same traversal the product code uses.
    """
    schedule = model.alwaysOnDiscreteSchedule()
    for name in zones:
        zone = openstudio.model.ThermalZone(model)
        zone.setName(name)
        # The product builders' own idiom (modeling/hvac/systems/baseboards.py):
        # a hot-water baseboard carries CoilHeatingWaterBaseboard, which is not
        # CoilHeatingWater.
        coil = openstudio.model.CoilHeatingWaterBaseboard(model)
        loop_.addDemandBranchForComponent(coil)
        baseboard = openstudio.model.ZoneHVACBaseboardConvectiveWater(model, schedule, coil)
        baseboard.addToThermalZone(zone)
    return loop_


def loop_with_vsd_pump(model, type_, flow=None, power=None, zones=('Block A',),
                       distribution_flow=None):
    """A plant loop with one variable-speed pump, serving `zones`.

    `distribution_flow` is the loop's own design flow — the denominator
    8.4.x.14.(3) divides by, counted once per fluid stream. It defaults to the
    pump's flow, which is what a single-pump loop sizes to; pass it explicitly
    where a fixture has pumps in series, because summing their rated flows is
    exactly the double-count D-93 exists to prevent.
    """
    loop_ = openstudio.model.PlantLoop(model)
    loop_.sizingPlant().setLoopType(type_)
    pump = openstudio.model.PumpVariableSpeed(model)
    if flow:
        pump.setRatedFlowRate(flow)
    if power:
        pump.setRatedPowerConsumption(power)
    pump.addToNode(loop_.supplyInletNode())
    if zones:
        serve_zones(model, loop_, zones)
    if distribution_flow or flow:
        loop_.setMaximumLoopFlowRate(distribution_flow or flow)
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

    def test_two_pumps_on_one_proposed_system_combine_over_its_distribution_flow(self):
        """Two pumps in one system, heads defaulted, so (3) governs the group.

        The denominator is the SYSTEM's distribution flow counted once — not
        the sum of the pumps' rated flows. In series they circulate the same
        water, and summing them would halve the intensity.
        """
        proposed = openstudio.model.Model()
        loop_, first = loop_with_vsd_pump(proposed, 'Heating', flow=0.010, power=800.0,
                                          zones=('Block A',), distribution_flow=0.015)
        second = openstudio.model.PumpVariableSpeed(proposed)
        second.setRatedFlowRate(0.005)
        second.setRatedPowerConsumption(700.0)
        second.addToNode(loop_.supplyInletNode())

        reference = openstudio.model.Model()
        _, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.020, zones=('Block A',))
        audit = AuditLog()
        hvac.apply_efficiencies(reference, code='necb2020', audit=audit, proposed=proposed)

        self.assertTrue(ref_pump.ratedPowerConsumption().empty(),
                        'the reference pump is left autosized for E+ to size')
        # 1500 W over the 15 L/s distribution flow = 100 W/(L/s) x 20 L/s
        self.assertAlmostEqual(2000.0, _pump_power_from_triple(ref_pump, 0.020), delta=0.1)
        decision = next(e for e in audit.entries if e.get('article') == '8.4.4.14.(3)')
        self.assertEqual(2, decision['inputs']['proposed_pumps'])
        self.assertAlmostEqual(100.0, decision['inputs']['proposed_w_per_l_s'], delta=0.01)
        self.assertAlmostEqual(15.0, decision['inputs']['distribution_flow_l_s'], delta=0.01,
                               msg='the system flow, counted once — not 10 + 5')

    def test_served_zones_reach_coils_held_inside_other_equipment(self):
        """Fable, PR #53. A water coil answers one of THREE accessors: zone
        equipment (`containingZoneHVACComponent`), an air loop's main branch
        (`airLoopHVAC`), or — inside a unitary system or a VAV reheat terminal —
        only `containingHVACComponent`. Checking the first two made a hot-water
        loop serving VAV reheat resolve to no zones at all, so an ordinary
        rooftop-with-hydronic-reheat building either declined loudly or, with a
        second loop present, reported a confident "one-to-one" for what is
        really an N:1 consolidation."""
        model = openstudio.model.Model()
        schedule = model.alwaysOnDiscreteSchedule()
        loop_ = openstudio.model.PlantLoop(model)
        loop_.sizingPlant().setLoopType('Heating')
        air_loop = openstudio.model.AirLoopHVAC(model)

        unitary_zone = openstudio.model.ThermalZone(model)
        unitary_zone.setName('Block U')
        held_coil = openstudio.model.CoilHeatingWater(model, schedule)
        loop_.addDemandBranchForComponent(held_coil)
        unitary = openstudio.model.AirLoopHVACUnitarySystem(model)
        unitary.setHeatingCoil(held_coil)
        unitary.setCoolingCoil(openstudio.model.CoilCoolingDXSingleSpeed(model))
        unitary.setSupplyFan(openstudio.model.FanOnOff(model, schedule))
        unitary.addToNode(air_loop.supplyOutletNode())
        air_loop.addBranchForZone(
            unitary_zone,
            openstudio.model.AirTerminalSingleDuctConstantVolumeNoReheat(
                model, schedule).to_StraightComponent())

        reheat_zone = openstudio.model.ThermalZone(model)
        reheat_zone.setName('Block R')
        reheat_coil = openstudio.model.CoilHeatingWater(model, schedule)
        loop_.addDemandBranchForComponent(reheat_coil)
        air_loop.addBranchForZone(
            reheat_zone,
            openstudio.model.AirTerminalSingleDuctVAVReheat(
                model, schedule, reheat_coil).to_StraightComponent())

        self.assertEqual({'Block U', 'Block R'}, _served_zone_names(loop_),
                         'a coil held inside other equipment still serves its zone')

    def test_sentence_2_conserves_electrical_power_across_unequal_motors(self):
        """The adjudicated equivalent motor efficiency, which nothing pinned.

        D-93 rules `η_m,ref = ΣS/ΣPₑ` — an electrical-weighted arithmetic mean —
        because a flow-weighted mean preserves shaft power while LEAKING
        electrical power, and electrical is what D-38's Part 5 cap binds. Every
        other (2) fixture sets the motor efficiencies equal, where all weightings
        collapse to the same answer, so regressing to the wrong one failed no
        test (Fable, PR #53). Unequal motors are the only shape that tells them
        apart.
        """
        proposed = openstudio.model.Model()
        loop_ = openstudio.model.PlantLoop(proposed)
        loop_.sizingPlant().setLoopType('Heating')
        serve_zones(proposed, loop_, ('Block A',))
        loop_.setMaximumLoopFlowRate(0.008)
        # Both triples must be physically possible, or the group falls to (3)
        # before (2) is reached — the validity check doing its job. At 4 L/s and
        # 150 kPa: 1000 W at 95 % implies 63.2 % hydraulic, 1200 W at 60 %
        # implies 83.3 %.
        for power, motor_eff in ((1000.0, 0.95), (1200.0, 0.60)):
            pump = openstudio.model.PumpVariableSpeed(proposed)
            pump.setRatedFlowRate(0.004)
            pump.setRatedPumpHead(150_000.0)
            pump.setMotorEfficiency(motor_eff)
            pump.setRatedPowerConsumption(power)
            pump.addToNode(loop_.supplyInletNode())

        reference = openstudio.model.Model()
        _, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.008, zones=('Block A',))
        audit = AuditLog()
        hvac.apply_efficiencies(reference, code='necb2020', audit=audit, proposed=proposed)

        decision = next(e for e in audit.entries if e.get('article') == '8.4.4.14.(2)')
        self.assertAlmostEqual(1670.0, decision['inputs']['combined_shaft_w'], delta=0.5)
        self.assertAlmostEqual(2200.0, decision['inputs']['combined_electrical_w'], delta=0.5)
        # ΣS/ΣPₑ = 1670/2200 = 0.7591, NOT the flow-weighted 0.7750
        self.assertAlmostEqual(0.7591, decision['inputs']['motor_efficiency'], delta=1e-3)
        self.assertAlmostEqual(2200.0, _pump_power_from_triple(ref_pump, 0.008), delta=0.5,
                               msg='electrical power is conserved; a flow-weighted mean gives 2154.8 W')

    def test_sentence_2_reproduces_the_codes_own_appendix_example(self):
        """A-8.4.4.14.(2)'s worked example, which nothing tested before.

        Three proposed pumps — 86 L/min @ 60 kPa @ 60 %, 78 @ 100 @ 50 %, 103 @
        120 @ 45 % — combining to 861 W of shaft power, and a reference pump at
        179.4 L/min (the flow 8.4.4.9.(6)(f) fixes from a 200 kW plant at a
        16 °C drop). The Article preserves the shaft watts ABSOLUTELY, so the
        smaller reference flow does not scale them down.

        This is the case D-11 got wrong: intensity x reference flow gives
        578.6 W, a third short of what the Code requires.
        """
        proposed = openstudio.model.Model()
        loop_ = openstudio.model.PlantLoop(proposed)
        loop_.sizingPlant().setLoopType('Heating')
        serve_zones(proposed, loop_, ('Block A',))
        loop_.setMaximumLoopFlowRate(267 / 60000.0)
        for flow_lpm, head_kpa, pump_eff in ((86, 60, 0.60), (78, 100, 0.50), (103, 120, 0.45)):
            pump = openstudio.model.PumpVariableSpeed(proposed)
            pump.setRatedFlowRate(flow_lpm / 60000.0)
            pump.setRatedPumpHead(head_kpa * 1000.0)
            pump.setDesignShaftPowerPerUnitFlowRatePerUnitHead(1.0 / pump_eff)
            pump.setMotorEfficiency(1.0)  # the note quotes SHAFT power
            pump.addToNode(loop_.supplyInletNode())

        reference = openstudio.model.Model()
        reference_flow = 179.4 / 60000.0
        _, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=reference_flow,
                                         zones=('Block A',))
        audit = AuditLog()
        hvac.apply_efficiencies(reference, code='necb2020', audit=audit, proposed=proposed)

        decision = next(e for e in audit.entries if e.get('article') == '8.4.4.14.(2)')
        self.assertAlmostEqual(861.11, decision['inputs']['combined_shaft_w'], delta=0.05,
                               msg="the note's 861 W")
        self.assertAlmostEqual(861.11, _pump_power_from_triple(ref_pump, reference_flow), delta=0.5,
                               msg='preserved ABSOLUTELY at the smaller reference flow')
        # Sol, DF-11: the note's own stated method is a flow-weighted mean,
        # which is 51.292 % — its published 54.2 % reproduces the published
        # 156.1 kPa but follows no stated method, and is reported as an erratum.
        self.assertAlmostEqual(0.51292, decision['inputs']['pump_efficiency'], delta=1e-4)
        self.assertAlmostEqual(147.72, ref_pump.ratedPumpHead() / 1000.0, delta=0.05)
        self.assertAlmostEqual(578.6, 861.11 / (267 / 60.0) * (179.4 / 60.0), delta=0.5,
                               msg="what D-11's superseded method would have given")

    def test_the_cap_and_the_curve_both_reach_a_demand_side_pump(self):
        """Sol, PR #53 P1 — a FALSE COMPLIANCE RESULT.

        D-93's collector was fixed to scan both plant sides, but the two older
        paths kept their own supply-only scans. A 100 W supply pump beside a
        10,000 W demand-side pump on a 100 kW loop therefore reported
        `combined_w=100` against a 450 W cap and was certified "within the
        maximum", while the demand pump kept all 10,000 W and never received
        its (4)-(5) riding curve.
        """
        model = openstudio.model.Model()
        loop_ = openstudio.model.PlantLoop(model)
        loop_.sizingPlant().setLoopType('Heating')
        self.add_boiler(loop_, 100.0)  # cap = 4.5 W/kW x 100 kW = 450 W
        supply = openstudio.model.PumpVariableSpeed(model)
        supply.setRatedFlowRate(0.004)
        supply.setRatedPowerConsumption(100.0)
        supply.addToNode(loop_.supplyInletNode())
        demand = openstudio.model.PumpVariableSpeed(model)
        demand.setRatedFlowRate(0.004)
        demand.setRatedPowerConsumption(10_000.0)
        self.assertTrue(demand.addToNode(loop_.demandInletNode()),
                        'precondition: the second pump really is on the demand side')

        audit = AuditLog()
        hvac.apply_efficiencies(model, code='necb2020', audit=audit)

        self.assertEqual([], [e for e in audit.entries
                              if 'within the Table 5.2.6.3 maximum' in e['action']],
                         'a 10,100 W loop is NEVER certified against a 450 W cap')
        clamp = next(e for e in audit.entries if 'exceeds Table 5.2.6.3' in e['action'])
        self.assertAlmostEqual(10_100.0, clamp['inputs']['before_w'], delta=1.0,
                               msg='the demand-side pump is counted')
        self.assertLess(demand.ratedPowerConsumption().get(), 500.0,
                        'and it is actually clamped, not merely reported')
        self.assertAlmostEqual(RIDING['a'], demand.coefficient1ofthePartLoadPerformanceCurve(),
                               delta=1e-6, msg='(4)-(5) reaches it too')

    def test_a_variable_speed_wshp_loop_is_classified_like_a_constant_speed_one(self):
        """Sol, PR #53 P2: three places carried their own partial list of
        water-to-air coil types, so a variable-speed WSHP loop read as plain hot
        water and took the Heating cap row instead of the water-source one."""
        model = openstudio.model.Model()
        loop_ = openstudio.model.PlantLoop(model)
        loop_.sizingPlant().setLoopType('Heating')
        coil = openstudio.model.CoilCoolingWaterToAirHeatPumpVariableSpeedEquationFit(model)
        loop_.addDemandBranchForComponent(coil)

        self.assertEqual('heat_pump_source', _loop_role(loop_))
        self.assertEqual('Water-source heat pump', _pump_cap_basis(loop_, 'Heating')[0])

    def test_a_secondary_pump_on_the_demand_side_is_counted(self):
        """Sol, PR #53 P1. A primary-secondary arrangement puts the primary
        pump on the supply side and the secondary on the DEMAND side. Scanning
        only the supply side found one pump where the system has two — which
        mistakes (2) for (1), and drops the secondary's power out of (3)
        entirely, on exactly the topology the Appendix example describes."""
        proposed = openstudio.model.Model()
        loop_, primary = loop_with_vsd_pump(proposed, 'Heating', flow=0.010, power=600.0,
                                            zones=('Block A',), distribution_flow=0.010)
        secondary = openstudio.model.PumpVariableSpeed(proposed)
        secondary.setRatedFlowRate(0.010)
        secondary.setRatedPowerConsumption(400.0)
        self.assertTrue(secondary.addToNode(loop_.demandInletNode()),
                        'precondition: the secondary pump really is on the demand side')

        reference = openstudio.model.Model()
        _, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.020, zones=('Block A',))
        audit = AuditLog()
        hvac.apply_efficiencies(reference, code='necb2020', audit=audit, proposed=proposed)

        decision = next(e for e in audit.entries if e.get('article') == '8.4.4.14.(3)'
                        and e['level'] == 'decision')
        self.assertEqual(2, decision['inputs']['proposed_pumps'],
                         'both pumps combine, not just the supply-side one')
        # (600 + 400) W over the 10 L/s stream = 100 W/(L/s) x 20 L/s
        self.assertAlmostEqual(2000.0, _pump_power_from_triple(ref_pump, 0.020), delta=0.1,
                               msg='the secondary\'s power is not dropped')

    def test_sentence_1_transfers_the_efficiency_the_proposed_actually_states(self):
        """Sol, PR #53 P1. A hard flow/head/power triple DEFINES the hydraulic
        efficiency, but the shaft-coefficient field on such a pump still holds
        the untouched default — so reading that field transferred 78 % where
        the proposed stated 50 %, turning 888.9 W into 569.8 W."""
        proposed = openstudio.model.Model()
        loop_, pump = loop_with_vsd_pump(proposed, 'Heating', flow=0.004, zones=('Block A',))
        pump.setRatedPumpHead(100_000.0)
        pump.setRatedPowerConsumption(0.004 * 100_000.0 / 0.5 / 0.9)  # implies exactly 50 %

        reference = openstudio.model.Model()
        _, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.004, zones=('Block A',))
        audit = AuditLog()
        hvac.apply_efficiencies(reference, code='necb2020', audit=audit, proposed=proposed)

        decision = next(e for e in audit.entries if e.get('article') == '8.4.4.14.(1)')
        self.assertAlmostEqual(0.5, decision['inputs']['pump_efficiency'], delta=1e-4,
                               msg='the stated efficiency, not the default field')
        self.assertAlmostEqual(888.9, _pump_power_from_triple(ref_pump, 0.004), delta=0.5,
                               msg='at equal flow, (1) reproduces the proposed power')

    def test_a_malformed_pump_in_a_group_never_crashes_the_determination(self):
        """Sol, PR #53 P1. A two-pump group holding 1000 W and -100 W reached
        sum() with a None and raised, terminating compliance processing. It must
        route to (3) or decline — never crash."""
        proposed = openstudio.model.Model()
        loop_, _ = loop_with_vsd_pump(proposed, 'Heating', flow=0.004, power=1000.0,
                                      zones=('Block A',), distribution_flow=0.004)
        for pump in proposed.getPumpVariableSpeeds():
            pump.setRatedPumpHead(100_000.0)
        broken = openstudio.model.PumpVariableSpeed(proposed)
        broken.setRatedFlowRate(0.004)
        broken.setRatedPumpHead(100_000.0)
        broken.setRatedPowerConsumption(-100.0)
        broken.addToNode(loop_.supplyInletNode())

        reference = openstudio.model.Model()
        _, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.004, zones=('Block A',))
        audit = AuditLog()
        hvac.apply_efficiencies(reference, code='necb2020', audit=audit, proposed=proposed)  # no raise

        self.assertTrue(any('no pump can draw' in w['action'] for w in audit.warnings),
                        'the malformed pump is named, never silently absorbed')
        self.assertTrue(any(e.get('article') == '8.4.4.14.(3)' and e['level'] == 'decision'
                            for e in audit.entries),
                        'an unreadable efficiency sends the group to (3) — the DECISION, not just\n                         the exclusion warning, which would satisfy this vacuously')

    def test_an_impossible_shaft_coefficient_is_not_a_known_efficiency(self):
        """A coefficient of 0.5 states a 200 % pump. 'Known' means defaulted,
        missing OR INVALID — validity decided by the same resolver that would
        transfer the value."""
        model = openstudio.model.Model()
        pump = openstudio.model.PumpVariableSpeed(model)
        pump.setRatedPumpHead(100_000.0)
        pump.setDesignShaftPowerPerUnitFlowRatePerUnitHead(0.5)
        self.assertIsNone(_hydraulic_efficiency(pump))
        self.assertEqual((True, False), _pump_characteristics_known(pump),
                         'head is stated; the efficiency it claims is not one a pump can have')

    def test_two_separate_proposed_systems_on_one_reference_loop_decline(self):
        """N:1 consolidation. The Code does not define correspondence across
        independently consolidated systems, so increment B declines and says
        why rather than inferring a whole-building intensity."""
        proposed = openstudio.model.Model()
        loop_with_vsd_pump(proposed, 'Heating', flow=0.010, power=800.0, zones=('Block A',))
        loop_with_vsd_pump(proposed, 'Heating', flow=0.005, power=700.0, zones=('Block B',))

        reference = openstudio.model.Model()
        _, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.020,
                                         zones=('Block A', 'Block B'))
        audit = AuditLog()
        hvac.apply_efficiencies(reference, code='necb2020', audit=audit, proposed=proposed)

        warning = next((w for w in audit.warnings if 'consolidated onto this one' in w['action']), None)
        self.assertIsNotNone(warning, 'the decline names the reason')
        self.assertIn('adjudicated separately', warning['action'])
        # The (4)-(5) riding curve still applies — it needs no correspondence.
        # What must NOT happen is a value transfer under (1), (2) or (3).
        self.assertEqual([], [e for e in audit.entries if e['level'] == 'decision'
                              and str(e.get('article') or '') in ('8.4.4.14.(1)', '8.4.4.14.(2)',
                                                                  '8.4.4.14.(3)')],
                         'nothing is transferred on a correspondence the Code does not define')

    def test_constant_speed_reference_pump_gets_transfer_but_no_curve(self):
        proposed = openstudio.model.Model()
        # 120 W/(L/s)
        loop_with_vsd_pump(proposed, 'Condenser', flow=0.010, power=1200.0)

        reference = openstudio.model.Model()
        loop_ = openstudio.model.PlantLoop(reference)
        loop_.sizingPlant().setLoopType('Condenser')
        serve_zones(reference, loop_, ('Block A',))
        loop_.setMaximumLoopFlowRate(0.005)
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

        warning = next((w for w in audit.warnings if 'NOT applied' in w['action']), None)
        self.assertIsNotNone(warning, 'undeterminable proposed pumps warn loudly')
        self.assertIn('distribution flow', warning['action'],
                      'and name what could not be determined')
        self.assertIn('circulate the same water', warning['action'],
                      'saying why the sum of the pumps\' own flows is not a substitute')
        self.assertTrue(ref_pump.ratedPowerConsumption().empty(),
                        'no transfer happened — autosizing retained')
        self.assertAlmostEqual(RIDING['a'], ref_pump.coefficient1ofthePartLoadPerformanceCurve(),
                               delta=1e-6, msg='Table curves still applied')

    def test_missing_loop_type_correspondence_warns(self):
        proposed = openstudio.model.Model()
        loop_with_vsd_pump(proposed, 'Heating', flow=0.010, power=800.0)

        reference = openstudio.model.Model()
        loop_with_vsd_pump(reference, 'Cooling', flow=0.02)  # no chilled-water loop in proposed
        audit = AuditLog()
        hvac.apply_efficiencies(reference, code='necb2020', audit=audit, proposed=proposed)

        warning = next((w for w in audit.warnings
                        if 'has no chilled_water loop' in w['action']), None)
        self.assertIsNotNone(warning, 'a missing counterpart warns')
        self.assertIn('not a Code value', warning['action'],
                      'and says the retained default is a modelling default, not a Code one')

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
        # weak: 10 W/(L/s), head left at the SDK default so (3) governs
        loop_with_vsd_pump(proposed, 'Heating', flow=0.010, power=100.0, zones=('Block A',))

        reference = openstudio.model.Model()
        _, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.001, zones=('Block A',))
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
        # The proposed pump's head is an SDK default, so (3) governs and the
        # split is a declared modelling choice — stated in the decision itself
        # rather than in a separate fallback note.
        decision = next(e for e in audit.entries if e.get('article') == '8.4.4.14.(3)'
                        and e['level'] == 'decision')
        self.assertIn('declared', decision['value'])
        self.assertIn('modelling split', decision['value'])

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

    def test_an_impossible_efficiency_sends_the_whole_group_to_sentence_3(self):
        """D-92 kept an impossible pump's power in a (2)-style total while
        dropping only its efficiency from the average. Sol overruled that
        (DF-11 increment B): (2) cannot preserve a combined shaft power it
        cannot compute, so the COMPLETE group takes (3) and the efficiency is a
        declared modelling split, not a blend of whatever happened to be valid.
        """
        proposed = openstudio.model.Model()
        loop_, _ = loop_with_vsd_pump(proposed, 'Heating', flow=0.010, power=1000.0,
                                      zones=('Block A',), distribution_flow=0.011)
        for pump in proposed.getPumpVariableSpeeds():
            pump.setRatedPumpHead(50_000.0)
        impossible = openstudio.model.PumpVariableSpeed(proposed)
        impossible.setRatedFlowRate(0.001)
        impossible.setRatedPowerConsumption(100.0)
        impossible.setRatedPumpHead(100_000.0)  # implies 111 % — no pump can do this
        impossible.addToNode(loop_.supplyInletNode())

        reference = openstudio.model.Model()
        _, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.020, zones=('Block A',))
        audit = AuditLog()
        hvac.apply_efficiencies(reference, code='necb2020', audit=audit, proposed=proposed)

        decision = next(e for e in audit.entries if e.get('article') == '8.4.4.14.(3)'
                        and e['level'] == 'decision')
        self.assertEqual(2, decision['inputs']['proposed_pumps'],
                         'both pumps combine under (3) — neither efficiency is inherited')
        self.assertAlmostEqual(DEFAULT_PUMP_EFFICIENCY,
                               1.0 / ref_pump.designShaftPowerPerUnitFlowRatePerUnitHead(), delta=1e-6,
                               msg='a declared physical split, not the valid pump\'s 55.6 %')
        # 1100 W over the 11 L/s distribution flow = 100 W/(L/s) x 20 L/s
        self.assertAlmostEqual(2000.0, _pump_power_from_triple(ref_pump, 0.020), delta=0.1)

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
        loop_, _ = loop_with_vsd_pump(proposed, 'Heating', flow=0.010, power=800.0,
                                      zones=('Block A',), distribution_flow=0.010)
        negative = openstudio.model.PumpVariableSpeed(proposed)
        negative.setRatedFlowRate(0.010)
        negative.setRatedPowerConsumption(-500.0)
        negative.addToNode(loop_.supplyInletNode())

        reference = openstudio.model.Model()
        _, ref_pump = loop_with_vsd_pump(reference, 'Heating', flow=0.020, zones=('Block A',))
        audit = AuditLog()
        hvac.apply_efficiencies(reference, code='necb2020', audit=audit, proposed=proposed)

        # 800 W over the 10 L/s distribution flow = 80 W/(L/s) x 20 L/s —
        # NOT (800-500)/10 = 30 W/(L/s)
        self.assertAlmostEqual(1600.0, _pump_power_from_triple(ref_pump, 0.020), delta=0.1,
                               msg='the malformed pump is excluded, not netted off')
        decision = next(e for e in audit.entries if e.get('article') == '8.4.4.14.(3)'
                        and e['level'] == 'decision')
        self.assertEqual(1, decision['inputs']['proposed_pumps'],
                         'and it is not counted among the pumps combined')
        self.assertTrue(any('no pump can draw' in w['action'] for w in audit.warnings),
                        'the exclusion is shouted, never silent')

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
