"""8.4.4.19/8.4.5.19 energy recovery + the article-coverage completeness gate.

The 5.2.10.1 trigger is the NECB 2020/2025 Table 5.2.10.1.-A/-B airflow
thresholds: climate row by HDD, band by %OA, table by operating mode
(continuous = fan availability >= 8000 h/yr). It is evaluated POST-SIZING
(`hvac.apply_energy_recovery`) because it needs the sized supply and
minimum-OA flows — the umbrella calls it after the reference sizing run.
Tests hard-size the flows instead of running EnergyPlus.

This REPLACED the NECB 2011 150 kW exhaust-heat-content trigger, which was
the wrong vintage — and permissive exactly where it matters (see the first
test: a small high-%OA system is "R" under 2020, waved through by 2011)."""

from __future__ import annotations

import unittest

import openstudio

import btap.modeling as modeling
from btap.necb import hvac
from tests.necb.hvac_helpers import load_fixture, sorted_zones
from tests.support import needs_sdk

# Table -A row "3000 <= HDD < 5000"; Table -B row "all other zones >= 3000"
HDD_TORONTO = 3890


@needs_sdk
class TestNecbEnergyRecovery(unittest.TestCase):

    def proposed_office(self):
        model = load_fixture()
        modeling.build_system(
            model, 'MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard',
            sorted_zones(model))
        return model

    def reference(self, model, vintage='2020', extra=None):
        types = {z.nameString(): 'Office - enclosed' for z in model.getThermalZones()}
        building = {'storeys': 3, 'zone_types': types}
        building.update(extra or {})
        return hvac.reference_hvac(model, vintage=vintage, building=building)

    def size_loops(self, model, supply_m3s, oa_fraction, non_continuous=False):
        """Hard-size every reference air loop (the trigger needs sized flows), set the
        OA fraction, and optionally cap fan availability below the 8000 h/yr
        continuous threshold (06:00-18:00 daily = 4380 h -> non-continuous)."""
        for loop in model.getAirLoopHVACs():
            loop.setDesignSupplyAirFlowRate(supply_m3s)
            ctrl = loop.airLoopHVACOutdoorAirSystem().get().getControllerOutdoorAir()
            ctrl.setMinimumOutdoorAirFlowRate(supply_m3s * oa_fraction)
            if not non_continuous:
                continue

            schedule = openstudio.model.ScheduleRuleset(model)
            day = schedule.defaultDaySchedule()
            day.addValue(openstudio.Time(0, 6, 0, 0), 0.0)
            day.addValue(openstudio.Time(0, 18, 0, 0), 1.0)
            day.addValue(openstudio.Time(0, 24, 0, 0), 0.0)
            loop.setAvailabilitySchedule(schedule)

    # THE divergence that motivated replacing the 2011 trigger: a small DOAS-like
    # system at >= 80% OA. Table -A row 3000-5000 HDD, 80% band = "R (required at
    # all flow rates)" — while the 2011 formula (EHC = 0.00123 x 200 L/s x 41 K
    # ~= 10 kW << 150) would wave it through.
    def test_high_oa_small_system_required_at_all_flow_rates(self):
        result = self.reference(self.proposed_office())
        self.size_loops(result.model, supply_m3s=0.25, oa_fraction=0.85, non_continuous=True)
        audit = hvac.apply_energy_recovery(result.model, hdd=HDD_TORONTO)

        hxs = result.model.getHeatExchangerAirToAirSensibleAndLatents()
        self.assertTrue(len(hxs),
                        '85% OA non-continuous: Table 5.2.10.1.-A says R at any flow')
        hx = hxs[0]
        self.assertEqual('Rotary', hx.heatExchangerType())
        # 5.2.10.1.(4): >= 50% ENTHALPY effectiveness. Equal sensible AND latent
        # effectiveness of 0.50 at every rating point gives enthalpy effectiveness
        # exactly 0.50 by identity (both components of delta-h transfer at 50%) —
        # verified on ALL EIGHT fields, not just one.
        for field in ('sensibleEffectivenessat100HeatingAirFlow',
                      'latentEffectivenessat100HeatingAirFlow',
                      'sensibleEffectivenessat100CoolingAirFlow',
                      'latentEffectivenessat100CoolingAirFlow',
                      'sensibleEffectivenessat75HeatingAirFlow',
                      'latentEffectivenessat75HeatingAirFlow',
                      'sensibleEffectivenessat75CoolingAirFlow',
                      'latentEffectivenessat75CoolingAirFlow'):
            if not hasattr(hx, field):
                continue

            self.assertAlmostEqual(0.5, getattr(hx, field)(), delta=1e-6,
                                   msg=f'5.2.10.1.(4): {field} at the 50% minimum')
        # 5.2.10.1.(6): bypass/control against supply setpoint overshoot
        self.assertTrue(hx.supplyAirOutletTemperatureControl(),
                        '5.2.10.1.(6): outlet temperature control enabled')
        self.assertTrue(len(result.model.getSetpointManagerOutdoorAirPretreats()),
                        'OA pretreat SPM controls the ERV')
        # frost values are E+ MODELING ASSUMPTIONS, not code values (5.2.10.1 is
        # silent on frost) — pinned so a change is a conscious decision
        self.assertAlmostEqual(-23.3, hx.thresholdTemperature(), delta=1e-6)

        decision = next(e for e in audit.entries if 'energy recovery added' in e['action'])
        self.assertRegex(decision['article'], r'8\.4\.4\.19')
        self.assertRegex(decision['article'], r'5\.2\.10\.1\.\(4\)')
        self.assertRegex(decision['article'], r'5\.2\.10\.1\.\(6\)')
        self.assertRegex(str(decision['value']), r'ENTHALPY effectiveness by identity')
        self.assertEqual('non_continuous', decision['inputs']['operation'])
        self.assertEqual('R (required at all flow rates)', decision['inputs']['threshold'])
        self.assertEqual(4380, decision['inputs']['annual_hours'],
                         'ruleset availability hours counted over the year')

    def test_below_threshold_not_required_but_decision_logged(self):
        result = self.reference(self.proposed_office())
        # 500 L/s at 15% OA, non-continuous: Table -A row 3000-5000, 10% band -> 12 270 L/s
        self.size_loops(result.model, supply_m3s=0.5, oa_fraction=0.15, non_continuous=True)
        audit = hvac.apply_energy_recovery(result.model, hdd=HDD_TORONTO)

        self.assertEqual(0, len(result.model.getHeatExchangerAirToAirSensibleAndLatents()))
        decision = next((e for e in audit.entries
                         if 'energy recovery not required' in e['action']), None)
        self.assertIsNotNone(decision,
                             'below-threshold outcome must still be a logged decision')
        self.assertEqual('>= 12270 L/s', decision['inputs']['threshold'])
        self.assertEqual(500, decision['inputs']['supply_l_s'])

    # Builders leave availability at Always On -> 8760 h -> CONTINUOUS -> Table
    # -B "all other zones >= 3000 HDD" = R at every band. The same system that
    # test_below_threshold waves through as non-continuous is required here.
    def test_always_on_default_classifies_continuous_and_requires(self):
        result = self.reference(self.proposed_office())
        self.size_loops(result.model, supply_m3s=0.5, oa_fraction=0.15)
        audit = hvac.apply_energy_recovery(result.model, hdd=HDD_TORONTO)

        self.assertTrue(len(result.model.getHeatExchangerAirToAirSensibleAndLatents()))
        decision = next(e for e in audit.entries if 'energy recovery added' in e['action'])
        self.assertEqual('continuous', decision['inputs']['operation'])
        self.assertEqual(8760, decision['inputs']['annual_hours'])
        self.assertEqual('R (required at all flow rates)', decision['inputs']['threshold'])

    def test_below_10_pct_oa_is_outside_the_tables(self):
        result = self.reference(self.proposed_office())
        self.size_loops(result.model, supply_m3s=2.0, oa_fraction=0.05)  # even continuous
        audit = hvac.apply_energy_recovery(result.model, hdd=HDD_TORONTO)

        self.assertEqual(0, len(result.model.getHeatExchangerAirToAirSensibleAndLatents()))
        decision = next(e for e in audit.entries
                        if 'energy recovery not required' in e['action'])
        self.assertRegex(decision['inputs']['threshold'], r'below 10% OA')

    def test_unsized_flows_warn_never_silent(self):
        result = self.reference(self.proposed_office())  # no hard sizes, no sizing run
        audit = hvac.apply_energy_recovery(result.model, hdd=HDD_TORONTO)

        self.assertEqual(0, len(result.model.getHeatExchangerAirToAirSensibleAndLatents()))
        warning = next((w for w in audit.warnings
                        if 'needs SIZED supply/OA flows' in w['action']), None)
        self.assertIsNotNone(warning)
        self.assertRegex(warning['article'], r'5\.2\.10\.1')

    def test_idempotent_second_pass_adds_nothing(self):
        result = self.reference(self.proposed_office())
        self.size_loops(result.model, supply_m3s=0.25, oa_fraction=0.85)
        hvac.apply_energy_recovery(result.model, hdd=HDD_TORONTO)
        count = len(result.model.getHeatExchangerAirToAirSensibleAndLatents())
        hvac.apply_energy_recovery(result.model, hdd=HDD_TORONTO)
        self.assertEqual(count, len(result.model.getHeatExchangerAirToAirSensibleAndLatents()))

    def test_2025_erv_cites_renumbered_article(self):
        result = self.reference(self.proposed_office(), vintage='2025')
        self.size_loops(result.model, supply_m3s=0.25, oa_fraction=0.85)
        audit = hvac.apply_energy_recovery(result.model, vintage='2025', hdd=HDD_TORONTO)
        decision = next(e for e in audit.entries if 'energy recovery added' in e['action'])
        self.assertRegex(decision['article'], r'8\.4\.5\.19')

    # ---- the completeness gate the ERV gap motivated ----

    # Every article of the reference subsection appears in every audit, with a status;
    # partial/not_implemented articles surface as warnings.
    def test_article_coverage_emitted_for_all_20_articles(self):
        result = self.reference(self.proposed_office())
        coverage = [e for e in result.audit.entries if e['step'] == 'coverage']
        # 20 Subsection 8.4.4 articles + '8.4.1.1. (HVAC)' + '8.4.2.10.'. The
        # formerly-partial articles are declared PER SENTENCE now (the article-level
        # prose already enumerated its sentences; the split turned that into
        # structure), so the count is entries, not articles: 12 article-level rows
        # + 40 sentence rows across the 8 split articles + the 2 shared entries.
        self.assertEqual(54, len(coverage), 'all declared entries accounted for')
        for n in range(1, 21):
            self.assertTrue(any(str(e.get('article') or '').startswith(f'8.4.4.{n}.')
                                for e in coverage),
                            f'article 8.4.4.{n}. missing from coverage (at any declared depth)')
        # 8.4.4.12 graduated to implemented with D-62 (the 5.2.2.8.(4)-(5) staging
        # floor closed its last gap) — it must now be an INFO coverage line whose
        # how names the floor, never a warning.
        econ = next(e for e in coverage if e.get('article') == '8.4.4.12.')
        self.assertEqual('implemented', econ['inputs']['status'],
                         '8.4.4.12 implemented since D-62')
        self.assertNotEqual('warning', econ['level'], '8.4.4.12 no longer warns')
        self.assertIn('5.2.2.8.(4)-(5)', econ['action'])
        # 8.4.4.16 is declared per sentence, and the split preserves the D-11
        # adjudication exactly: (1) binds only when the modeller approximates
        # radiant convectively — modeller scope, an info note — while (2) is
        # identical by construction and simply implemented.
        stc1 = next(e for e in coverage if e.get('article') == '8.4.4.16.(1)')
        self.assertEqual('info', stc1['level'],
                         '8.4.4.16.(1) is a modeller scope note, not a warning')
        self.assertEqual('modeller', stc1['inputs']['gap_owner'])
        self.assertIn('modeller scope', stc1['action'])
        stc2 = next(e for e in coverage if e.get('article') == '8.4.4.16.(2)')
        self.assertEqual('implemented', stc2['inputs']['status'],
                         '(2) is identical by construction')
        # implemented articles report how many decisions cited them this run
        selection = next(e for e in coverage if e.get('article') == '8.4.4.7.')
        self.assertGreater(selection['inputs']['decisions_citing'], 0)
        # 8.4.4.19 is now a POST-SIZING determination: 0 citations during the
        # build is correct; the manifest line must still declare it implemented.
        erv = next(e for e in coverage if e.get('article') == '8.4.4.19.')
        self.assertEqual('implemented', erv['inputs']['status'])
        self.assertRegex(erv['action'], r'(?i)POST-SIZING')

    def test_coverage_manifest_lint_both_vintages(self):
        valid = ('implemented', 'partial', 'not_implemented', 'satisfied_by_clone', 'host_scope')
        for vintage in ('2020', '2025'):
            manifest = hvac.rules(vintage)['article_coverage']['articles']
            # 12 article-level + 40 per-sentence + the 2 shared entries
            self.assertEqual(54, len(manifest))
            for art in manifest:
                self.assertIn(art['status'], valid, f"{art['article']} has invalid status")
                self.assertTrue(art.get('title'), f"{art['article']} missing title")
                if art['status'] in ('partial', 'not_implemented'):
                    self.assertTrue(art.get('gaps'),
                                    f"{art['article']} is {art['status']} but declares no gaps")
            prefix = '8.4.4' if vintage == '2020' else '8.4.5'
            shared = ('8.4.1.1. (HVAC)', '8.4.2.10.')
            self.assertTrue(all(a['article'].startswith(prefix) or a['article'] in shared
                                for a in manifest))

    # 8.4.4.6.(2): purchased cooling -> air-cooled electric chiller in the reference
    def test_purchased_cooling_forces_air_cooled_chiller(self):
        model = load_fixture()
        modeling.build_system(model, 'DOAS with fan coil district chilled water with boiler',
                              sorted_zones(model))
        # -> System 2
        types = {z.nameString(): 'Museum archives' for z in model.getThermalZones()}
        result = hvac.reference_hvac(model, building={'storeys': 1, 'zone_types': types})

        sys2 = next((a for a in result.assignments if a.reference_system == 2), None)
        self.assertIsNotNone(sys2)
        self.assertEqual('air_cooled', sys2.config['chw_source'])
        chillers = result.model.getChillerElectricEIRs()
        self.assertTrue(len(chillers))
        self.assertTrue(all(c.condenserType() == 'AirCooled' for c in chillers))
        self.assertTrue(all(abs(c.referenceCOP() - 2.802) < 0.001 for c in chillers),
                'Table 8.4.3.5: purchased-cooling reference chiller COP is 2.802')
        self.assertTrue(any('air-cooled electric chiller' in e['action']
                            for e in result.audit.entries))
        self.assertTrue(any(e['action'] == 'purchased-cooling reference chiller COP applied'
                    and e.get('article') == 'Table 8.4.3.5'
                    for e in result.audit.entries))


if __name__ == '__main__':
    unittest.main()
