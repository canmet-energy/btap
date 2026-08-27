"""P3b gate: NECB 3.1.1.7 effective transmittance via TBD — assemblies are
uprated so the derated Ut meets the table targets; unavailability/omission is
loud, never silent.

Port of btap-necb/test/test_envelope_thermal_bridging.rb.

M7 NOTE: rd2/tbd is a RUBY gem with no Python equivalent, so
``btap.necb.envelope.thermal_bridging.is_available()`` is permanently False
until the M7 TBD bridge exists. The two tests that assert the LOUD-when-absent
contract are the ones that matter here and they run; the uprate/derate math
test skips with 'needs TBD bridge (M7)'. That skip is deliberate and named —
the Ruby gate's own rule (a skipped TBD gate is a green-but-vacuous gate)
applies to the RUBY suite, where TBD_REQUIRED=1 turns it into a failure.
"""

from __future__ import annotations

import os
import unittest

from tests.necb.support import load_raw_fixture, needs_sdk

HDD = 3890


@needs_sdk
class TestThermalBridging(unittest.TestCase):
    @property
    def n(self):
        from btap.necb import envelope
        return envelope

    def tbd_available(self):
        return self.n.thermal_bridging.is_available()

    def test_not_requested_warns(self):
        model = load_raw_fixture()
        audit = self.n.apply_prescriptive(model, vintage='2020', hdd=HDD)
        warning = next((w for w in audit.warnings
                        if 'thermal bridging not requested' in w['action']), None)
        self.assertIsNotNone(warning)
        self.assertEqual('3.1.1.7.', warning['article'])

    def test_unavailable_is_loud(self):
        from btap.audit import AuditLog

        os.environ['OPENSTUDIO_ENVELOPE_DISABLE_TBD'] = '1'
        try:
            audit = AuditLog()
            result = self.n.thermal_bridging.apply(load_raw_fixture(), vintage='2020',
                                                   hdd=HDD, audit=audit)
            self.assertEqual(False, result)
            self.assertTrue(any('NOT accounted' in w['action']
                                and w['article'] == '3.1.1.7.'
                                for w in audit.warnings))
        finally:
            os.environ.pop('OPENSTUDIO_ENVELOPE_DISABLE_TBD', None)

    @unittest.skip('needs TBD bridge (M7)')
    def test_uprate_derate_meets_effective_targets(self):
        """The Ruby gate: with tbd installed, apply_prescriptive(
        thermal_bridging: 'efficient (BETBG)') must log a :thermal_bridging
        decision citing Σψ, land the derated roof U at/below 0.156, and surface
        TBD's 'Unable to uprate' refusal on this fixture's tiny walls as an
        audit WARNING. Reproducing it from Python needs the M7 TBD bridge."""

    def test_tbd_path_names_the_m7_bridge(self):
        """Python-side addition: with the disable flag clear, the uprate path
        must fail with a message that NAMES the missing bridge rather than
        silently producing clear-field values. ``apply`` itself still takes the
        Ruby's audited-warning branch (is_available() is False), so the raise
        is asserted on the bridge entry point directly."""
        self.assertFalse(self.tbd_available(),
                         'no Python TBD until the M7 bridge lands')
        with self.assertRaises(RuntimeError) as ctx:
            self.n.thermal_bridging._process(load_raw_fixture(), {})
        self.assertIn('M7 TBD bridge', str(ctx.exception))

    def test_coverage_manifest_reflects_tbd_status(self):
        for v in ('2020', '2025'):
            art = next(a for a in self.n.rules(v)['article_coverage']['articles']
                       if a['article'] == '3.1.1.7.')
            self.assertEqual('implemented', art['status'])
            self.assertRegex(art['gaps'], r'tbd gem')


if __name__ == '__main__':
    unittest.main()
