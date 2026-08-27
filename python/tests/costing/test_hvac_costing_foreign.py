"""Port of btap-costing/test/test_hvac_costing_foreign.rb.

Costing on a GENERAL OSM: systems= is optional. Loops are classified
automatically — exactly for recognizable names, structurally for foreign
models — so any OSM gets full ventilation/distribution costing, not just
plant/zonal."""

import json
import unittest

import btap.modeling as modeling
from btap._compat import ruby_round
from btap.costing.hvac import report as hvac_report
from tests.costing.support import load_fixture, needs_sdk


@needs_sdk
class TestCostingForeign(unittest.TestCase):
    def sized_vav_model(self):
        from btap._compat import sorted_by_name

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        result = modeling.build_system(
            model,
            'MZ BU RTU Hot Water Heating Coil Scroll Chiller and Hot Water Baseboard',
            zones)
        for al in result.air_loops:
            al.setDesignSupplyAirFlowRate(2.0)
        for b in model.getBoilerHotWaters():
            b.setNominalCapacity(60_000.0)
        for c in model.getChillerElectricEIRs():
            c.setReferenceCapacity(100_000.0)
        for p in list(model.getPumpConstantSpeeds()) + list(model.getPumpVariableSpeeds()):
            p.setRatedPowerConsumption(1000.0)
        for c in model.getCoilHeatingWaterBaseboards():
            c.setHeatingDesignCapacity(4_000.0)
        for t in model.getAirTerminalSingleDuctVAVReheats():
            t.setMaximumAirFlowRate(0.4)
        return model, result

    def item_signature(self, report):
        return sorted((i['id'], ruby_round(i['quantity'], 4)) for i in report.items)

    def test_cost_without_systems_matches_cost_with_systems(self):
        """systems= omitted on a gem-built model -> identical costing (names
        recognized exactly)"""
        model, result = self.sized_vav_model()
        with_ = hvac_report.cost(model, systems=[result], city='TORONTO',
                                 province_state='ONTARIO')
        without = hvac_report.cost(model, city='TORONTO', province_state='ONTARIO')

        self.assertEqual(self.item_signature(with_), self.item_signature(without))
        self.assertAlmostEqual(with_.total, without.total, delta=0.01)
        self.assertEqual([], [w for w in without.warnings if 'guessed structurally' in w],
                         'recognized names need no structural guess')

    def test_foreign_osm_costed_via_structural_classification(self):
        """fully foreign loop names -> structural classification, same AHU
        class, loud about it"""
        model, result = self.sized_vav_model()
        with_ = hvac_report.cost(model, systems=[result], city='TORONTO',
                                 province_state='ONTARIO')

        for i, al in enumerate(model.getAirLoopHVACs()):
            al.setName(f"Imported AHU {i + 1}")
        foreign = hvac_report.cost(model, city='TORONTO', province_state='ONTARIO')

        self.assertAlmostEqual(with_.total, foreign.total, delta=0.01,
                               msg='structural guess lands the same sys6 assembly class')
        self.assertTrue(any('guessed structurally' in w and 'vav_reheat' in w
                            for w in foreign.warnings))
        self.assertEqual([], [w for w in foreign.warnings
                              if 'was not built by this gem' in w],
                         'foreign loop is costed, not skipped')

    def test_legacy_pipe_named_osm_costed(self):
        """legacy NECB pipe-named loops (openstudio-standards output) -> exact
        family mapping"""
        model, result = self.sized_vav_model()
        with_ = hvac_report.cost(model, systems=[result], city='TORONTO',
                                 province_state='ONTARIO')

        for al in model.getAirLoopHVACs():
            al.setName('sys_6|mixed|shr>none|sh>c-hw|sc>c-chw|ssf>vv|zh>b-hw|zc>none|srf>vv|')
        legacy = hvac_report.cost(model, city='TORONTO', province_state='ONTARIO')

        self.assertAlmostEqual(with_.total, legacy.total, delta=0.01)
        self.assertEqual([], [w for w in legacy.warnings if 'guessed structurally' in w],
                         'pipe names map exactly, no guess needed')

    def test_costing_audit_log(self):
        """the costing audit log: classification, selection math, per-item
        decisions, geometry evidence and mirrored warnings — same contract as
        reference generation"""
        model, _ = self.sized_vav_model()
        for i, al in enumerate(model.getAirLoopHVACs()):
            al.setName(f"Imported AHU {i + 1}")
        report = hvac_report.cost(model, city='TORONTO', province_state='ONTARIO')

        audit = report.audit
        self.assertIsNotNone(audit)
        steps = list(dict.fromkeys(e['step'] for e in audit.entries))
        self.assertIn('costing_classification', steps, 'classification decisions logged')
        self.assertIn('costing_equipment', steps, 'plant/zonal item decisions logged')
        self.assertIn('costing_ventilation', steps, 'ventilation item decisions logged')
        self.assertIn('costing_geometry', steps, 'geometry evidence logged')

        guess = next(e for e in audit.entries
                     if 'guessed structurally' in e['action'])
        self.assertEqual('vav_reheat', guess['value'])

        ahu = next(e for e in audit.entries if 'AHU assembly selected' in e['action'])
        self.assertGreater(ahu['inputs']['bucket_lps'], 0)
        self.assertRegex(ahu['value'], r'scaled to')

        # every warning string is mirrored into the audit
        for w in report.warnings:
            self.assertTrue(any(e['action'] == w for e in audit.warnings),
                            f"warning not mirrored: {w}")
        self.assertGreater(len(json.loads(audit.to_json())), 0)

    def test_unified_audit_across_reference_and_costing(self):
        """ONE audit for compliance + costing: thread a single AuditLog through
        reference_hvac and cost and get one chronological narrative.
        Unblocked by M5's hvac rules domain."""
        import btap.modeling as modeling
        from btap._compat import sorted_by_name
        from btap.audit import AuditLog
        from btap.costing.hvac import report as hvac_report
        from btap.necb import hvac as necb_hvac

        model = load_fixture()
        zones = sorted_by_name(model.getThermalZones())
        modeling.build_system(model, 'Baseboard gas boiler', zones)
        types = {z.nameString(): 'Office - enclosed' for z in model.getThermalZones()}

        audit = AuditLog()
        result = necb_hvac.reference_hvac(
            model, building={'storeys': 1, 'zone_types': types,
                             'winter_design_temp_c': -20}, audit=audit)
        ref = result.model
        for boiler in ref.getBoilerHotWaters():
            boiler.setNominalCapacity(60_000.0)
        for coil in ref.getCoilCoolingDXSingleSpeeds():
            coil.setRatedTotalCoolingCapacity(15_000.0)
        report = hvac_report.cost(ref, city='TORONTO', province_state='ONTARIO', audit=audit)

        self.assertIs(report.audit, result.audit, 'one AuditLog object end to end')
        steps = list(dict.fromkeys(e['step'] for e in audit.entries))
        # compliance narrative first, costing narrative after — one chronological log
        for step in ('characterize', 'selection', 'build', 'rules', 'efficiency',
                     'coverage', 'costing_equipment', 'costing'):
            self.assertIn(step, steps)
        self.assertLess(steps.index('coverage'), steps.index('costing_equipment'),
                        'reference generation precedes costing in the same log')
        self.assertGreater(len(json.loads(audit.to_json())), 50)


if __name__ == '__main__':
    unittest.main()
