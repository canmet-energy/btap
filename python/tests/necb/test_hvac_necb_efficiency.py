"""P3 gate (standalone half): hvac.apply_efficiencies sets Table 5.2.12.1 values on a
hard-sized model. The other half is the scratchpad parity harness vs legacy
model_apply_hvac_efficiency_standard (0 mismatches on sys3/sys6/ref-HP)."""

from __future__ import annotations

import re
import unittest

import btap.modeling as modeling
from btap._compat import sorted_by_name
from btap.audit import AuditLog
from btap.codes.necb import hvac
from tests.necb.hvac_helpers import load_fixture, sorted_zones
from tests.support import needs_sdk


@needs_sdk
class TestNecbEfficiency(unittest.TestCase):

    def test_boiler_chiller_dx_gas_values_and_audit(self):
        model = load_fixture()
        modeling.build_system(
            model, 'MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard',
            sorted_zones(model))
        for b in model.getBoilerHotWaters():
            b.setNominalCapacity(100_000.0)  # 100 kW < 176 kW
        for c in model.getChillerElectricEIRs():
            c.setReferenceCapacity(200_000.0)  # ~57 tons: first scroll bin

        audit = AuditLog()
        hvac.apply_efficiencies(model, code='necb2020', audit=audit)

        # NECB 2020 gas boiler < 300 kBtu/hr: 0.90 AFUE -> thermal efficiency 0.90
        primary = next(b for b in model.getBoilerHotWaters() if 'Primary' in b.nameString())
        secondary = next(b for b in model.getBoilerHotWaters() if 'Secondary' in b.nameString())
        self.assertAlmostEqual(0.90, primary.nominalThermalEfficiency(), delta=1e-6)
        # < 176 kW: primary keeps capacity, secondary parked at 0.001 W (legacy staging rule)
        self.assertAlmostEqual(100_000.0, primary.nominalCapacity().get(), delta=1.0)
        self.assertAlmostEqual(0.001, secondary.nominalCapacity().get(), delta=1e-6)
        # D-89: the curve is the one this boiler's part-load CLASS names, not a
        # single curve given to every row
        self.assertTrue(primary.normalizedBoilerEfficiencyCurve().is_initialized())
        self.assertRegex(primary.normalizedBoilerEfficiencyCurve().get().nameString(),
                         r'BOILER-PLF-NONCONDENSING')
        self.assertEqual('EnteringBoiler',
                         primary.efficiencyCurveTemperatureEvaluationVariable().get())

        # Water-cooled scroll chiller 200 kW (~57 tons, 0-75 ton bin): 0.77927 kW/ton
        chiller = sorted_by_name(model.getChillerElectricEIRs())[0]
        self.assertAlmostEqual(3.517 / 0.77927, chiller.referenceCOP(), delta=1e-3)
        self.assertEqual('LeavingSetpointModulated', chiller.chillerFlowMode())
        self.assertAlmostEqual(0.25, chiller.minimumPartLoadRatio(), delta=1e-6)
        self.assertRegex(chiller.coolingCapacityFunctionOfTemperature().nameString(), r'CAPFT')

        # every decision carries a code citation: Table 5.2.12 minimums, or the
        # 8.4.4.11/13/14/17 plant/pump/fan articles the pass also applies
        decisions = [e for e in audit.entries
                     if e['step'] == 'efficiency' and e['level'] == 'decision']
        self.assertTrue(decisions)
        uncited = next((e for e in decisions
                        if not re.search(r'5\.2\.12|8\.4\.[45]\.1[1-9]', str(e.get('article') or ''))),
                       None)
        self.assertTrue(all(re.search(r'5\.2\.12|8\.4\.[45]\.1[1-9]', str(e.get('article') or ''))
                            for e in decisions),
                        f"uncited decision: {uncited.get('action') if uncited else None}")

    def test_chiller_audit_states_the_cop_that_was_applied(self):
        """The COP is the determination an AHJ reads, so it belongs in the audit
        VALUE even though the model NAME carries only the compact kW/ton form."""
        model = load_fixture()
        modeling.build_system(
            model, 'MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard',
            sorted_zones(model))
        for c in model.getChillerElectricEIRs():
            c.setReferenceCapacity(200_000.0)

        audit = AuditLog()
        hvac.apply_efficiencies(model, code='necb2020', audit=audit)

        entry = next(e for e in audit.entries if e['action'] == 'chiller efficiency applied')
        chiller = sorted_by_name(model.getChillerElectricEIRs())[0]
        self.assertIn(f'COP {round(chiller.referenceCOP(), 2)}', entry['value'])
        self.assertIn('kW/ton', entry['value'])
        self.assertRegex(chiller.nameString(), r'kW/ton$')

    def test_dx_and_gas_coil_and_ashp(self):
        model = load_fixture()
        modeling.build_system(model, 'PSZ RTU Gas and DX Coils and Electric Baseboard',
                              sorted_zones(model))
        for c in model.getCoilCoolingDXSingleSpeeds():
            c.setRatedTotalCoolingCapacity(15_000.0)
        for c in model.getCoilHeatingGass():
            c.setNominalCapacity(20_000.0)

        hvac.apply_efficiencies(model, code='necb2020')

        # gas heat on the loop -> 'All Other' heating type; 15 kW (~51 kBtu/hr) bin
        coil = sorted_by_name(model.getCoilCoolingDXSingleSpeeds())[0]
        cop = coil.ratedCOP()
        cop = cop.get() if hasattr(cop, 'is_initialized') else cop
        self.assertGreater(cop, 2.5)
        self.assertRegex(coil.nameString(), r'SEER|EER')
        # Exact value, hand-derived the same way as the ASHP heating COP below:
        # necb2020/efficiencies.json's unitary_acs table, AirCooled/All Other/Single
        # Package, 0-65000 Btu/hr bin (15 kW = ~51,182 Btu/hr) declares SEER 15.0;
        # seer_to_cop_no_fan(seer) = -0.0076*seer^2 + 0.3796*seer (efficiency.py).
        self.assertAlmostEqual((-0.0076 * 15.0 * 15.0) + (0.3796 * 15.0), cop, delta=1e-6,
                               msg='15.0 SEER (0-65 kBtu/hr AirCooled/All Other/Single Package '
                                   'bin) -> COP 3.984')
        self.assertRegex(coil.nameString(), r'15\.0SEER')

        gas = sorted_by_name(model.getCoilHeatingGass())[0]
        # NECB 2020 furnace >= 0.95 AFUE band
        self.assertGreaterEqual(gas.gasBurnerEfficiency(), 0.90)
        self.assertTrue(gas.partLoadFractionCorrelationCurve().is_initialized())

        # ASHP pair: heating COP from heat_pumps_heating
        model2 = load_fixture()
        modeling.build_system(
            model2,
            'PSZ RTU ASHP with Electric and ASHP with Electric Supp. Heat Coils and '
            'Electric Baseboard', sorted_zones(model2))
        for c in model2.getCoilCoolingDXSingleSpeeds():
            c.setRatedTotalCoolingCapacity(12_000.0)
        for c in model2.getCoilHeatingDXSingleSpeeds():
            c.setRatedTotalHeatingCapacity(12_000.0)
        hvac.apply_efficiencies(model2, code='necb2020')
        hp = sorted_by_name(model2.getCoilHeatingDXSingleSpeeds())[0]
        # 7.4 HSPF -> -0.0296*7.4^2 + 0.7134*7.4 = 3.658
        self.assertAlmostEqual(3.658, hp.ratedCOP(), delta=0.01)

    def test_unsized_model_warns_never_silent(self):
        model = load_fixture()
        modeling.build_system(model, 'PSZ RTU Gas and DX Coils and Electric Baseboard',
                              sorted_zones(model))
        audit = AuditLog()
        hvac.apply_efficiencies(model, code='necb2020', audit=audit)
        self.assertTrue(any('not sized' in w['action'] for w in audit.warnings))

    def test_a_pass_that_will_be_followed_by_sizing_does_NOT_warn(self):
        """The complement of `test_unsized_model_warns_never_silent`.

        The reference build runs this pass TWICE: once in `_reference_hvac`
        before the model is sized, and again in `_size_reference` after. Every
        capacity-binned determination is made by the second pass — measured on
        two archetypes, the first emitted 78 and 194 capacity warnings and made
        0 and 1 decisions, while the second made 80 and 195.

        So the first pass was reporting the expected pre-sizing state as a
        finding: 1,166 false warnings across 26 archetypes, 194 of them in the
        Compliance checklist an AHJ reads first, each saying "model not sized?"
        of a model that was about to be sized, and was.

        The control is the sibling test: with no sizing to follow, the SAME
        model must still warn, because then this pass is the only disclosure
        there will be.
        """
        model = load_fixture()
        modeling.build_system(model, 'PSZ RTU Gas and DX Coils and Electric Baseboard',
                              sorted_zones(model))
        audit = AuditLog()
        hvac.apply_efficiencies(model, code='necb2020', audit=audit,
                                sizing_follows=True)
        offenders = [w['action'] for w in audit.warnings
                     if 'not sized' in w['action']
                     or 'capacity unavailable' in w['action']]
        self.assertEqual(
            [], offenders,
            'a pass whose determinations are redone after sizing must not '
            'report the pre-sizing state as a finding')

    def test_the_sizing_guard_withholds_the_WARNING_not_the_WORK(self):
        """Pins the three flow fixes, which no test caught.

        Fable's `302` found my guards had changed CONTROL FLOW, not just the
        warning: `_apply_vrf` returned twice where main fell through to its
        heating branch, and `_align_heat_pump_heating_capacity` returned where
        main continued, abandoning every later air loop. He proved it with hand
        probes — a VRF with hard-sized heating took COP 3.3 on main and 3.5 on
        my head. His `303` then noted the fixes were pinned by that probe
        alone: reverting either guard passed every test in the suite (37 and
        153 passed).

        Nothing in the frozen corpus exercises these shapes, which is why
        neither the corpus nor any focused test could catch them. So the probe
        becomes a test: a VRF whose capacities are HARD-SET is unaffected by
        the pre-sizing guard, because nothing about it is unavailable. The
        guard must withhold the warning and not the work.
        """
        model = load_fixture()
        modeling.build_system(model, 'VRF', sorted_zones(model))
        unit = model.getAirConditionerVariableRefrigerantFlows()[0]
        # The shape that reaches the guard: COOLING capacity left autosized on
        # a model with no sql, so its table row cannot be resolved, while
        # HEATING is hard-set and its row CAN. Hard-setting both (my first
        # attempt) never enters the branch at all and the test passed with the
        # bug restored — 15 passed either way.
        unit.autosizeGrossRatedTotalCoolingCapacity()
        unit.setGrossRatedHeatingCapacity(20_000.0)
        unit.setRatedHeatingCOP(5.0)

        audit = AuditLog()
        hvac.apply_efficiencies(model, code='necb2020', audit=audit,
                                sizing_follows=True)

        self.assertNotAlmostEqual(
            5.0, unit.ratedHeatingCOP(), delta=0.01,
            msg='an unresolvable COOLING row must not skip the HEATING '
                'branch: main fell through to it, so returning left the '
                'authored 5.0 COP in place')
        offenders = [w['action'] for w in audit.warnings
                     if 'capacity unavailable' in w['action']]
        self.assertEqual([], offenders,
                         'and the pre-sizing warning is still withheld')

    def test_air_source_vrf_uses_table_i_minimums_and_audits(self):
        model = load_fixture()
        modeling.build_system(model, 'VRF', sorted_zones(model))
        unit = model.getAirConditionerVariableRefrigerantFlows()[0]
        unit.setGrossRatedTotalCoolingCapacity(20_000.0)
        unit.setGrossRatedHeatingCapacity(20_000.0)
        unit.setGrossRatedCoolingCOP(5.0)
        unit.setRatedHeatingCOP(5.0)

        audit = AuditLog()
        hvac.apply_efficiencies(model, code='necb2020', audit=audit)

        self.assertAlmostEqual(hvac.efficiency.eer_to_cop_no_fan(10.8, 20_000.0),
                               unit.grossRatedCoolingCOP(), delta=1e-6)
        self.assertAlmostEqual(3.30, unit.ratedHeatingCOP(), delta=1e-6)
        self.assertTrue(any(entry['action'] == 'VRF minimum efficiency applied'
                            and entry.get('article') == 'Table 5.2.12.1.-I'
                            and entry.get('ruling') == 'D-85'
                            for entry in audit.entries))

    @staticmethod
    def _vrf_unit(model, *, heating):
        """An air-cooled VRF outdoor unit serving one terminal.

        heating=False removes the terminal's VRF DX heating coil, which is the
        only way the classic SDK objects express a cooling-only VRF — the
        4-argument terminal constructor REQUIRES a CoilHeatingDXVariableRefrigerantFlow.
        """
        import openstudio

        unit = openstudio.model.AirConditionerVariableRefrigerantFlow(model)
        unit.setCondenserType('AirCooled')
        terminal = openstudio.model.ZoneHVACTerminalUnitVariableRefrigerantFlow(model)
        unit.addTerminal(terminal)
        if not heating:
            terminal.heatingCoil().get().remove()
        return unit

    def test_cooling_only_vrf_uses_table_i_air_conditioner_row(self):
        import openstudio

        model = openstudio.model.Model()
        unit = self._vrf_unit(model, heating=False)
        unit.setGrossRatedTotalCoolingCapacity(20_000.0)
        unit.setGrossRatedCoolingCOP(5.0)

        audit = AuditLog()
        hvac.apply_efficiencies(model, code='necb2020', audit=audit)

        self.assertAlmostEqual(hvac.efficiency.eer_to_cop_no_fan(11.2, 20_000.0),
                               unit.grossRatedCoolingCOP(), delta=1e-6)
        decision = next(entry for entry in audit.entries
                        if entry['action'] == 'VRF minimum efficiency applied')
        self.assertEqual('air_conditioner', decision['inputs']['equipment_class'])

    def test_vrf_with_a_heating_coil_takes_the_heat_pump_rows(self):
        import openstudio

        model = openstudio.model.Model()
        unit = self._vrf_unit(model, heating=True)
        unit.setGrossRatedTotalCoolingCapacity(20_000.0)
        unit.setGrossRatedHeatingCapacity(20_000.0)

        audit = AuditLog()
        hvac.apply_efficiencies(model, code='necb2020', audit=audit)

        decision = next(entry for entry in audit.entries
                        if entry['action'] == 'VRF minimum efficiency applied')
        self.assertEqual('heat_pump', decision['inputs']['equipment_class'])
        # the HP row, NOT the air-conditioner row that the same capacity would hit
        self.assertAlmostEqual(hvac.efficiency.eer_to_cop_no_fan(10.8, 20_000.0),
                               unit.grossRatedCoolingCOP(), delta=1e-6)
        self.assertAlmostEqual(3.3, unit.ratedHeatingCOP(), delta=1e-9)

    def test_terminal_less_vrf_is_indeterminate_and_says_so(self):
        """The reference transform strips terminals; the class cannot then be
        read from the model, and guessing would drop the heating minimum."""
        import openstudio

        model = openstudio.model.Model()
        unit = openstudio.model.AirConditionerVariableRefrigerantFlow(model)
        unit.setCondenserType('AirCooled')
        unit.setGrossRatedTotalCoolingCapacity(20_000.0)
        unit.setGrossRatedCoolingCOP(5.0)

        audit = AuditLog()
        hvac.apply_efficiencies(model, code='necb2020', audit=audit)

        self.assertAlmostEqual(5.0, unit.grossRatedCoolingCOP(), delta=1e-9,
                               msg='no Table-I row may be applied without evidence of the class')
        self.assertFalse(any(entry['action'] == 'VRF minimum efficiency applied'
                             for entry in audit.entries))
        warning = next(entry for entry in audit.warnings
                       if 'serves no terminals' in entry['action'])
        self.assertEqual('D-85', warning['ruling'])

    def test_small_vrf_uses_table_i_seasonal_minimums(self):
        model = load_fixture()
        modeling.build_system(model, 'VRF', sorted_zones(model))
        unit = model.getAirConditionerVariableRefrigerantFlows()[0]
        unit.setGrossRatedTotalCoolingCapacity(12_000.0)
        unit.setGrossRatedHeatingCapacity(12_000.0)
        unit.setGrossRatedCoolingCOP(1.0)
        unit.setRatedHeatingCOP(1.0)

        hvac.apply_efficiencies(model, code='necb2020')

        self.assertAlmostEqual(hvac.efficiency.seer_to_cop_no_fan(15.0),
                               unit.grossRatedCoolingCOP(), delta=1e-6)
        self.assertAlmostEqual(hvac.efficiency.hspf_to_cop_no_fan(7.8),
                               unit.ratedHeatingCOP(), delta=1e-6)

    def test_small_2025_vrf_with_unknown_phase_uses_c656_and_discloses(self):
        import openstudio

        model = openstudio.model.Model()
        unit = self._vrf_unit(model, heating=True)
        unit.setGrossRatedTotalCoolingCapacity(12_000.0)
        unit.setGrossRatedHeatingCapacity(12_000.0)
        unit.setGrossRatedCoolingCOP(1.0)
        unit.setRatedHeatingCOP(1.0)
        audit = AuditLog()

        hvac.apply_efficiencies(model, code='necb2025', audit=audit)

        self.assertAlmostEqual(
            hvac.efficiency.seer_to_cop_no_fan(15.0),
            unit.grossRatedCoolingCOP(),
            delta=1e-6,
        )
        self.assertAlmostEqual(
            hvac.efficiency.hspf_to_cop_no_fan(7.8),
            unit.ratedHeatingCOP(),
            delta=1e-6,
        )
        disclosure = next(
            entry for entry in audit.entries
            if entry.get('ruling') == 'D-104')
        self.assertEqual('info', disclosure['level'])
        self.assertEqual(
            ['cooling', 'heating'],
            disclosure['inputs']['applicable_modes'])
        self.assertEqual(
            'CSA C656',
            disclosure['inputs']['selected_test_standard'])
        self.assertEqual(
            'DOE 10 CFR, Part 430, Subpart B, Appendix M1',
            disclosure['inputs']['not_applied_test_standard'])
        self.assertEqual(14.3, disclosure['inputs']['not_applied_seer2'])
        self.assertEqual(6.6, disclosure['inputs']['not_applied_hspf2'])

    def test_vrf_phase_disclosure_is_driven_by_data_not_edition_id(self):
        import openstudio

        from btap.codes import resolve

        base = resolve('necb2025')

        class FutureRuleset:
            id = 'necb2099'

            def __getattr__(self, name):
                return getattr(base, name)

        model = openstudio.model.Model()
        unit = self._vrf_unit(model, heating=True)
        unit.setGrossRatedTotalCoolingCapacity(12_000.0)
        unit.setGrossRatedHeatingCapacity(12_000.0)
        audit = AuditLog()

        hvac.efficiency._apply(model, FutureRuleset(), audit=audit)

        disclosures = [
            entry for entry in audit.entries
            if entry.get('ruling') == 'D-104'
        ]
        self.assertEqual(1, len(disclosures))
        self.assertEqual(
            ['cooling', 'heating'],
            disclosures[0]['inputs']['applicable_modes'])

    def test_m1_metrics_are_not_converted_by_pre_m1_regressions(self):
        self.assertIsNone(hvac.efficiency.dx_cooling_cop({
            'minimum_seasonal_energy_efficiency_ratio_2': 14.3,
        }))
        self.assertIsNone(hvac.efficiency.dx_cooling_cop({
            'minimum_energy_efficiency_ratio_2': 11.0,
        }))
        self.assertIsNone(hvac.efficiency.dx_heating_cop({
            'minimum_heating_seasonal_performance_factor_2': 6.6,
        }, 12_000.0))

    def test_unsized_vrf_warns_with_table_i_citation(self):
        model = load_fixture()
        modeling.build_system(model, 'VRF', sorted_zones(model))
        audit = AuditLog()

        hvac.apply_efficiencies(model, code='necb2020', audit=audit)

        self.assertTrue(any('VRF cooling capacity unavailable' in warning['action']
                            and warning.get('article') == 'Table 5.2.12.1.-I'
                    and warning.get('ruling') == 'D-85'
                            for warning in audit.warnings))
        self.assertTrue(any('VRF heating capacity unavailable' in warning['action']
                    and warning.get('article') == 'Table 5.2.12.1.-I'
                    and warning.get('ruling') == 'D-85'
                    for warning in audit.warnings))


@needs_sdk
class TestTheShippedChillerCurvesDisclosureIsReachable(unittest.TestCase):
    """AHJ-17: a chiller row that applies NO curve must SAY so.

    `find_row` treats a null field as a WILDCARD, and the single `AirCooled`
    row in both editions carries `compressor_type: null` over 0-9999 tons, so
    it MATCHES every air-cooled chiller and the "no chiller efficiency row
    found" warning never fires. Its `capft`, `eirft` and `eirfplr` are all
    null, so `curve()` returns None on each and the applier set nothing.

    The decision line already recorded `curves None/None/None`, so this was
    never total silence — what was missing was a WARNING level and a citation,
    which is what an AHJ reading the trail weighs (issue #181).

    No frozen scenario builds an air-cooled chiller — all three lanes stay
    green with the warning in — so this test is the only thing that exercises
    it.
    """

    @staticmethod
    def _audit_for(condenser):
        """A chiller of the given condenser type, through the real applier.

        `setCondenserType('WaterCooled')` only takes once the chiller is on a
        CONDENSER loop — it is refused on an unconnected machine — so the
        water-cooled fixture builds both loops. A capacity is required either
        way: the applier returns before the curve loop when it cannot
        establish one, which is why a probe without it reported zero warnings
        and made the citation look unreachable.
        """
        import openstudio

        from btap.codes.necb.hvac import efficiency

        model = openstudio.model.Model()
        chiller = openstudio.model.ChillerElectricEIR(model)
        chiller.setName(f'Scroll {condenser} probe')
        chiller.setReferenceCapacity(500000.0)
        chilled = openstudio.model.PlantLoop(model)
        chilled.setName('Chilled Water')
        chilled.sizingPlant().setLoopType('Cooling')
        assert chilled.addSupplyBranchForComponent(chiller)
        if condenser == 'WaterCooled':
            condenser_loop = openstudio.model.PlantLoop(model)
            condenser_loop.setName('Condenser Water')
            condenser_loop.sizingPlant().setLoopType('Condenser')
            assert condenser_loop.addDemandBranchForComponent(chiller)
            assert chiller.setCondenserType('WaterCooled')
        audit = AuditLog()
        efficiency.apply(model, code='necb2020', audit=audit)
        return chiller, audit

    def test_an_air_cooled_chiller_discloses_the_simulator_default(self):
        chiller, audit = self._audit_for('AirCooled')
        self.assertEqual('AirCooled', chiller.condenserType(),
                         'ChillerElectricEIR must default to AirCooled for '
                         'this fixture to exercise the wildcard row')

        cited = [e for e in audit.entries if e.get('ahj') == 'AHJ-17']
        self.assertEqual(
            1, len(cited),
            'an air-cooled chiller whose row ships no curves must warn once '
            f'and cite AHJ-17; got {[e.get("ahj") for e in audit.entries]}')
        entry = cited[0]
        self.assertEqual('warning', entry['level'],
                         'a disclosure an AHJ weighs is a WARNING, not an '
                         'info line — the decision already said '
                         '"curves None/None/None" and nothing flagged it')
        self.assertEqual(
            [], entry['inputs']['curves_in_row'],
            'the inputs must name WHICH curves the row carries, so the '
            'reader need not go to the data to see that it is none of them')
        self.assertEqual('AirCooled', entry['inputs']['cooling_type'])

    def test_a_WATER_cooled_chiller_does_not_warn(self):
        """The control, and my first version of it was VACUOUS.

        It reused the air-cooled fixture and filtered on
        `inputs['curves_in_row']` being non-empty — which for that fixture is
        always `[]`, so the filter could never match and the assertion could
        never fail. A control that cannot fail is the thing this suite keeps
        catching.

        A water-cooled Scroll chiller genuinely reaches a row that carries
        curves — the decision line reads `curves
        WaterCooled_Scroll_CAPFT/...` — so this rules out the warning
        degenerating into a notice on every chiller.

        What it does NOT prove, measured rather than assumed: that the
        condition is scoped to the ABSENCE of curves rather than to the
        AirCooled TYPE. Mutating `if not applied:` to
        `if cooling_type == 'AirCooled' or not applied:` leaves every test
        green, because the two coincide on every shipped row — the single
        AirCooled row carries no curves and all nineteen WaterCooled rows
        carry them, so no fixture can distinguish them. The scoping is a
        choice about how this code ages (an edition that ships the curves
        stops warning with no code change), not a property the data can
        witness, and saying so beats a docstring that claims a proof it
        does not have.
        """
        chiller, audit = self._audit_for('WaterCooled')
        self.assertEqual('WaterCooled', chiller.condenserType(),
                         'the fixture must really be water-cooled, or the '
                         'control degenerates into the air-cooled case again')
        self.assertEqual(
            [], [e.get('ahj') for e in audit.entries
                 if e.get('ahj') == 'AHJ-17'],
            'a row that DOES carry curves must not warn, or the disclosure '
            'becomes a notice on every chiller')
        self.assertTrue(
            any('WaterCooled_Scroll' in str(e.get('value') or '')
                for e in audit.entries),
            'the water-cooled row must actually have applied its curves — '
            'otherwise this control passes for the wrong reason')


if __name__ == '__main__':
    unittest.main()
