"""8.4.4.15.(2) / 8.4.5.15.(2) (D-54): "where demand control ventilation strategies
required by Article 5.2.3.4. are implemented in the proposed building, the
reference building shall be modeled with those same strategies".

The reference OA controller is REBUILT from scratch, so the strategy has to be
carried across the teardown. The DCV-ON path is the one that matters: a test that
only exercises the DCV-off path proves nothing, because the rebuilt controller is
DCV-off by construction."""

from __future__ import annotations

import pathlib
import unittest

import btap.modeling as modeling
from btap.audit import AuditLog
from btap.necb import hvac
from tests.necb.hvac_helpers import load_fixture, sorted_zones
from tests.support import needs_sdk

PROPOSED = 'PSZ RTU Gas and DX Coils and Hot Water Baseboard'


@needs_sdk
class TestNecbDcv(unittest.TestCase):

    def proposed(self, dcv=True, method=None):
        """A proposed model whose air loops actually carry DCV — the fixtures do not."""
        model = load_fixture()
        modeling.build_system(model, PROPOSED, sorted_zones(model))
        for air_loop in model.getAirLoopHVACs():
            oa = air_loop.airLoopHVACOutdoorAirSystem()
            if oa.empty():
                continue

            mech = oa.get().getControllerOutdoorAir().controllerMechanicalVentilation()
            mech.setDemandControlledVentilation(dcv)
            if method:
                mech.setSystemOutdoorAirMethod(method)
        return model

    def reference(self, model, vintage='2020'):
        audit = AuditLog()
        result = hvac.reference_hvac(
            model, vintage=vintage,
            building={'storeys': 1,
                      'zone_types': {z.nameString(): 'Office - enclosed'
                                     for z in model.getThermalZones()}},
            audit=audit)
        return result, audit

    @staticmethod
    def mech_controllers(model):
        out = []
        for air_loop in model.getAirLoopHVACs():
            oa = air_loop.airLoopHVACOutdoorAirSystem()
            if oa.empty():
                continue

            out.append(oa.get().getControllerOutdoorAir().controllerMechanicalVentilation())
        return out

    # ---- the capture side ----

    def test_characterize_records_proposed_dcv(self):
        facts = modeling.characterize(self.proposed(dcv=True))
        air_groups = [g for g in facts['zone_groups'] if g['air_loop'] is not None]
        self.assertTrue(air_groups)
        self.assertTrue(all(g['dcv'] for g in air_groups),
                        'per-air-loop DCV captured in the facts schema')
        self.assertEqual(['ZoneSum'],
                         sorted({g['system_outdoor_air_method'] for g in air_groups}))

    def test_characterize_records_dcv_off(self):
        facts = modeling.characterize(self.proposed(dcv=False))
        air_groups = [g for g in facts['zone_groups'] if g['air_loop'] is not None]
        self.assertTrue(air_groups)
        self.assertFalse(any(g['dcv'] for g in air_groups))

    # ---- the copy side (the one that matters) ----

    def test_dcv_on_in_the_proposed_is_rebuilt_on_the_reference(self):
        model = self.proposed(dcv=True)
        self.assertTrue(all(c.demandControlledVentilation()
                            for c in self.mech_controllers(model)),
                        'precondition: proposed HAS DCV')

        result, audit = self.reference(model)
        controllers = self.mech_controllers(result.model)
        self.assertTrue(controllers, 'reference builds air loops with OA systems')
        self.assertTrue(all(c.demandControlledVentilation() for c in controllers),
                        'the rebuilt reference OA controller carries the proposed DCV strategy')
        # sentence (1) convention is untouched: peak OA still determined by ZoneSum
        self.assertEqual(['ZoneSum'],
                         sorted({c.systemOutdoorAirMethod() for c in controllers}))

        entry = next((e for e in audit.entries
                      if 'demand-controlled ventilation strategy copied' in e['action']), None)
        self.assertIsNotNone(entry, 'the copy is audited')
        self.assertEqual('8.4.4.15.(2)', entry['article'])
        self.assertEqual('D-54', entry['ruling'])
        self.assertEqual('decision', entry['level'])

    def test_no_dcv_in_the_proposed_leaves_the_reference_without_it(self):
        result, audit = self.reference(self.proposed(dcv=False))
        self.assertFalse(any(c.demandControlledVentilation()
                             for c in self.mech_controllers(result.model)))
        entry = next((e for e in audit.entries
                      if 'no demand-controlled ventilation' in e['action']), None)
        self.assertIsNotNone(entry)
        self.assertEqual('8.4.4.15.(2)', entry['article'])
        self.assertEqual('D-54', entry['ruling'])

    # A CO2-based strategy is a DIFFERENT strategy from occupancy-based DCV: copying
    # the flag alone would silently substitute one for the other.
    def test_co2_based_strategy_copies_the_method_and_warns_about_the_missing_balance(self):
        result, audit = self.reference(
            self.proposed(dcv=True, method='IndoorAirQualityProcedure'))
        controllers = self.mech_controllers(result.model)
        self.assertTrue(all(c.demandControlledVentilation() for c in controllers))
        self.assertEqual(['IndoorAirQualityProcedure'],
                         sorted({c.systemOutdoorAirMethod() for c in controllers}))

        warning = next((e for e in audit.entries
                        if 'NO carbon dioxide concentration balance' in e['action']), None)
        self.assertIsNotNone(warning, 'an inert CO2 strategy is never silent')
        self.assertEqual('warning', warning['level'])
        self.assertEqual('D-54', warning['ruling'])

    # The peak-rate methods are sentence (1)'s subject, not a DCV strategy — copying
    # VRP would move the reference's peak outdoor air off the ZoneSum convention.
    def test_peak_rate_method_is_not_copied(self):
        result, _ = self.reference(
            self.proposed(dcv=True, method='Standard62.1VentilationRateProcedure'))
        controllers = self.mech_controllers(result.model)
        self.assertTrue(all(c.demandControlledVentilation() for c in controllers),
                        'the strategy IS copied')
        self.assertEqual(['ZoneSum'], sorted({c.systemOutdoorAirMethod() for c in controllers}),
                         'the peak-rate method is NOT copied')

    def test_2025_cites_the_renumbered_article(self):
        _, audit = self.reference(self.proposed(dcv=True), vintage='2025')
        entry = next((e for e in audit.entries
                      if 'demand-controlled ventilation strategy copied' in e['action']), None)
        self.assertIsNotNone(entry)
        self.assertEqual('8.4.5.15.(2)', entry['article'])

    # L-13: legacy guards DCV with a MISSPELLED sentinel ('NECB_Defualt' vs the
    # documented 'NECB_Default'), so the guard never fires. Filed as a legacy defect,
    # deliberately NOT ported.
    def test_legacy_misspelled_sentinel_is_not_ported(self):
        root = pathlib.Path(__file__).resolve().parents[2] / 'btap'
        hits = [str(p) for p in root.rglob('*.py')
                if 'NECB_Defualt' in p.read_text(encoding='utf-8')]
        self.assertEqual([], hits,
                         "L-13's misspelled 'NECB_Defualt' guard must not be ported here")


if __name__ == '__main__':
    unittest.main()
