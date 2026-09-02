"""P3 gate (standalone half): hvac.apply_efficiencies sets Table 5.2.12.1 values on a
hard-sized model. The other half is the scratchpad parity harness vs legacy
model_apply_hvac_efficiency_standard (0 mismatches on sys3/sys6/ref-HP)."""

from __future__ import annotations

import re
import unittest

import btap.modeling as modeling
from btap._compat import sorted_by_name
from btap.audit import AuditLog
from btap.necb import hvac
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
        hvac.apply_efficiencies(model, vintage='2020', audit=audit)

        # NECB 2020 gas boiler < 300 kBtu/hr: 0.90 AFUE -> thermal efficiency 0.90
        primary = next(b for b in model.getBoilerHotWaters() if 'Primary' in b.nameString())
        secondary = next(b for b in model.getBoilerHotWaters() if 'Secondary' in b.nameString())
        self.assertAlmostEqual(0.90, primary.nominalThermalEfficiency(), delta=1e-6)
        # < 176 kW: primary keeps capacity, secondary parked at 0.001 W (legacy staging rule)
        self.assertAlmostEqual(100_000.0, primary.nominalCapacity().get(), delta=1.0)
        self.assertAlmostEqual(0.001, secondary.nominalCapacity().get(), delta=1e-6)
        self.assertTrue(primary.normalizedBoilerEfficiencyCurve().is_initialized())
        self.assertRegex(primary.normalizedBoilerEfficiencyCurve().get().nameString(),
                         r'BOILER-EFFFPLR')

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
        hvac.apply_efficiencies(model, vintage='2020', audit=audit)

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

        hvac.apply_efficiencies(model, vintage='2020')

        # gas heat on the loop -> 'All Other' heating type; 15 kW (~51 kBtu/hr) bin
        coil = sorted_by_name(model.getCoilCoolingDXSingleSpeeds())[0]
        cop = coil.ratedCOP()
        cop = cop.get() if hasattr(cop, 'is_initialized') else cop
        self.assertGreater(cop, 2.5)
        self.assertRegex(coil.nameString(), r'SEER|EER')
        # Exact value, hand-derived the same way as the ASHP heating COP below:
        # efficiencies_2020.json's unitary_acs table, AirCooled/All Other/Single
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
        hvac.apply_efficiencies(model2, vintage='2020')
        hp = sorted_by_name(model2.getCoilHeatingDXSingleSpeeds())[0]
        # 7.4 HSPF -> -0.0296*7.4^2 + 0.7134*7.4 = 3.658
        self.assertAlmostEqual(3.658, hp.ratedCOP(), delta=0.01)

    def test_unsized_model_warns_never_silent(self):
        model = load_fixture()
        modeling.build_system(model, 'PSZ RTU Gas and DX Coils and Electric Baseboard',
                              sorted_zones(model))
        audit = AuditLog()
        hvac.apply_efficiencies(model, vintage='2020', audit=audit)
        self.assertTrue(any('not sized' in w['action'] for w in audit.warnings))

    def test_air_source_vrf_uses_table_i_minimums_and_audits(self):
        model = load_fixture()
        modeling.build_system(model, 'VRF', sorted_zones(model))
        unit = model.getAirConditionerVariableRefrigerantFlows()[0]
        unit.setGrossRatedTotalCoolingCapacity(20_000.0)
        unit.setGrossRatedHeatingCapacity(20_000.0)
        unit.setGrossRatedCoolingCOP(5.0)
        unit.setRatedHeatingCOP(5.0)

        audit = AuditLog()
        hvac.apply_efficiencies(model, vintage='2020', audit=audit)

        self.assertAlmostEqual(hvac.efficiency.eer_to_cop_no_fan(10.8, 20_000.0),
                               unit.grossRatedCoolingCOP(), delta=1e-6)
        self.assertAlmostEqual(3.30, unit.ratedHeatingCOP(), delta=1e-6)
        self.assertTrue(any(entry['action'] == 'VRF minimum efficiency applied'
                            and entry.get('article') == 'NECB 2020 Table 5.2.12.1.-I'
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
        hvac.apply_efficiencies(model, vintage='2020', audit=audit)

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
        hvac.apply_efficiencies(model, vintage='2020', audit=audit)

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
        hvac.apply_efficiencies(model, vintage='2020', audit=audit)

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

        hvac.apply_efficiencies(model, vintage='2020')

        self.assertAlmostEqual(hvac.efficiency.seer_to_cop_no_fan(15.0),
                               unit.grossRatedCoolingCOP(), delta=1e-6)
        self.assertAlmostEqual(hvac.efficiency.hspf_to_cop_no_fan(7.8),
                               unit.ratedHeatingCOP(), delta=1e-6)

    def test_unsized_vrf_warns_with_table_i_citation(self):
        model = load_fixture()
        modeling.build_system(model, 'VRF', sorted_zones(model))
        audit = AuditLog()

        hvac.apply_efficiencies(model, vintage='2020', audit=audit)

        self.assertTrue(any('VRF cooling capacity unavailable' in warning['action']
                            and warning.get('article') == 'NECB 2020 Table 5.2.12.1.-I'
                    and warning.get('ruling') == 'D-85'
                            for warning in audit.warnings))
        self.assertTrue(any('VRF heating capacity unavailable' in warning['action']
                    and warning.get('article') == 'NECB 2020 Table 5.2.12.1.-I'
                    and warning.get('ruling') == 'D-85'
                    for warning in audit.warnings))


if __name__ == '__main__':
    unittest.main()
