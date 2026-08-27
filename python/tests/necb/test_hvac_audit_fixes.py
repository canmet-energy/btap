"""Audit 2026-07-25 fixes (T-list): behavioural pins."""

from __future__ import annotations

import unittest

import btap.modeling as modeling
from btap._compat import sorted_by_name
from btap.audit import AuditLog
from btap.necb import hvac
from tests.necb.hvac_helpers import load_fixture, sorted_zones
from tests.support import needs_sdk


@needs_sdk
class TestAuditFixes(unittest.TestCase):

    def build_reference(self, system='Baseboard gas boiler'):
        model = load_fixture()
        modeling.build_system(model, system, sorted_zones(model))
        # proposed has NO oversizing
        model.getSizingParameters().setHeatingSizingFactor(1.0)
        model.getSizingParameters().setCoolingSizingFactor(1.0)
        audit = AuditLog()
        result = hvac.reference_hvac(
            model, vintage='2020',
            building={'storeys': 1,
                      'zone_types': {z.nameString(): 'Office - enclosed'
                                     for z in model.getThermalZones()}},
            audit=audit)
        return result, audit

    # T1: the 8.4.4.8 cap must actually govern — generic zone factors cleared.
    def test_oversizing_cap_binds_zone_factors_cleared(self):
        result, audit = self.build_reference()
        ref = result.model
        self.assertAlmostEqual(1.0, ref.getSizingParameters().heatingSizingFactor(),
                               delta=1e-9, msg='min(proposed 1.0, cap 1.3)')
        generic = 0
        for sz in ref.getSizingZones():
            h = sz.zoneHeatingSizingFactor()
            if h.is_initialized() and abs(h.get() - 1.3) < 1e-9:
                generic += 1
        self.assertEqual(0, generic,
                         'no zone carries the generic 1.3 heating factor that would override the cap')
        decision = next(e for e in audit.entries
                        if e['action'] == 'equipment oversizing capped')
        self.assertGreater(decision['inputs']['generic_zone_factors_cleared'], 0)

    # T3: below the 5.2.2.7 trigger the economizer is REMOVED post-sizing.
    def test_economizer_removed_below_trigger(self):
        result, _ = self.build_reference()  # sys3 PSZ with DX
        ref = result.model
        for loop in ref.getAirLoopHVACs():
            loop.setDesignSupplyAirFlowRate(0.5)  # 500 L/s <= 1500
            for c in loop.supplyComponents():
                coil = c.to_CoilCoolingDXSingleSpeed()
                if coil.is_initialized():
                    coil.get().setRatedTotalCoolingCapacity(10_000.0)  # 10 kW <= 20
        audit = hvac.apply_economizer_thresholds(ref)
        for loop in ref.getAirLoopHVACs():
            oa = loop.airLoopHVACOutdoorAirSystem()
            if oa.empty():
                continue
            self.assertEqual('NoEconomizer',
                             oa.get().getControllerOutdoorAir().getEconomizerControlType())
        self.assertTrue(any('economizer REMOVED' in e['action'] and '5.2.2.7' in e['article']
                            for e in audit.entries))

    # T3: above the trigger it stays.
    def test_economizer_retained_above_trigger(self):
        result, _ = self.build_reference()
        ref = result.model
        for loop in ref.getAirLoopHVACs():
            loop.setDesignSupplyAirFlowRate(2.0)  # 2000 L/s > 1500
        hvac.apply_economizer_thresholds(ref)
        kept = False
        for loop in ref.getAirLoopHVACs():
            oa = loop.airLoopHVACOutdoorAirSystem()
            if (oa.is_initialized()
                    and oa.get().getControllerOutdoorAir().getEconomizerControlType()
                    == 'DifferentialEnthalpy'):
                kept = True
        self.assertTrue(kept, 'economizer retained above 1500 L/s')

    # T2 follow-up (D-26): the tower fan is sized from the SUM of chiller
    # capacities on its condenser loop — a two-chiller plant sized from the
    # Primary alone gets half the fan and E+'s tower UA autosizing fails
    # ("Bad starting values for UA", LargeOffice archetype).
    def test_tower_fan_power_sums_chillers_on_loop(self):
        model = load_fixture()
        modeling.build_system(
            model, 'MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard',
            sorted_zones(model))
        for b in model.getBoilerHotWaters():
            b.setNominalCapacity(100_000.0)
        # above the 2100 kW single-chiller max -> two-chiller split (2 x 1.25 MW)
        for c in model.getChillerElectricEIRs():
            c.setReferenceCapacity(2_500_000.0)
        if not len(model.getCoolingTowerSingleSpeeds()):
            self.skipTest('fixture system has no condenser loop/tower')

        audit = AuditLog()
        hvac.apply_efficiencies(model, vintage='2020', audit=audit)

        tower = model.getCoolingTowerSingleSpeeds()[0]
        total_rejection = sum(c.referenceCapacity().get() * (1.0 + 1.0 / c.referenceCOP())
                              for c in model.getChillerElectricEIRs())
        self.assertGreater(total_rejection, 2_500_000.0, 'both chillers contribute')
        self.assertTrue(tower.fanPoweratDesignAirFlowRate().is_initialized())
        self.assertAlmostEqual(0.013 * total_rejection,
                               tower.fanPoweratDesignAirFlowRate().get(), delta=1.0,
                               msg='fan = 0.013 x SUM of loop chiller rejection, not the Primary alone')
        decision = next(e for e in audit.entries
                        if e['action'] == 'cooling tower cells set from heat rejection')
        self.assertEqual(2, decision['inputs']['chillers_on_loop'])

    # T4: paired DX HP heating capacity pinned to cooling capacity post-sizing.
    def test_hp_heating_capacity_pinned_to_cooling(self):
        model = load_fixture()
        modeling.build_system(
            model,
            'PSZ RTU ASHP with Electric and ASHP with Electric Supp. Heat Coils and '
            'Electric Baseboard', sorted_zones(model))
        for c in model.getCoilCoolingDXSingleSpeeds():
            c.setRatedTotalCoolingCapacity(14_000.0)
        for c in model.getCoilHeatingDXSingleSpeeds():
            c.setRatedTotalHeatingCapacity(9_000.0)  # wrong on purpose
        audit = AuditLog()
        hvac.apply_efficiencies(model, vintage='2020', audit=audit)
        hp = sorted_by_name(model.getCoilHeatingDXSingleSpeeds())[0]
        self.assertAlmostEqual(14_000.0, hp.ratedTotalHeatingCapacity().get(), delta=1.0,
                               msg='8.4.4.13.(2)(c): heating = cooling')
        self.assertTrue(any(e.get('article') == '8.4.4.13.(2)(c)' for e in audit.entries))


if __name__ == '__main__':
    unittest.main()
