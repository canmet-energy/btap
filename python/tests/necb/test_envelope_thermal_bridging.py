"""P3b gate: NECB 3.1.1.7 effective transmittance via TBD — assemblies are
uprated so the derated Ut meets the table targets; unavailability/omission is
loud, never silent.

Port of btap-necb/test/test_envelope_thermal_bridging.rb, plus the M7
(D-79 Option A) gates: the engine is py-tbd's ``tbd-3.5.2-compat`` branch —
verified against the SAME Ruby TBD 3.5.2 / OSut 0.8.2 baseline the family's
oracle is frozen on — and its identity is asserted, so a silently different
engine cannot compare different physics against the frozen goldens.
BTAP_TBD_REQUIRED=1 turns the engine's absence from a skip into a failure
(CI's verify job sets it)."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from tests.necb.support import load_raw_fixture, needs_sdk
from tests.support import needs_tbd

HDD = 3890


@needs_sdk
class TestThermalBridging(unittest.TestCase):
    @property
    def n(self):
        from btap.necb import envelope
        return envelope

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

    def test_coverage_manifest_reflects_tbd_status(self):
        for v in ('2020', '2025'):
            art = next(a for a in self.n.rules(v)['article_coverage']['articles']
                       if a['article'] == '3.1.1.7.')
            self.assertEqual('implemented', art['status'])
            self.assertRegex(art['gaps'], r'tbd gem')


@needs_tbd
class TestThermalBridgingEngine(unittest.TestCase):
    """The gates that need the pinned engine (M7)."""

    @property
    def n(self):
        from btap.necb import envelope
        return envelope

    def test_engine_identity_matches_the_option_a_pin(self):
        # A silently different engine (e.g. py-tbd main, which ports upstream
        # 3.6.0 and PARTIALLY uprates where 3.5.2 refuses) would compare
        # different physics against the frozen oracle goldens. The pin is a
        # verification baseline, so its identity is asserted, not assumed.
        import tbd

        tb = self.n.thermal_bridging
        self.assertEqual(tb.PINNED_TBD_VERSION, tbd.VERSION)
        self.assertEqual(tb.PINNED_TBD_VERSION, tbd.UPSTREAM_VERSION)
        self.assertEqual(tb.PINNED_TBD_UPSTREAM_SHA, tbd.UPSTREAM_SHA)
        self.assertEqual("https://github.com/rd2/tbd", tbd.UPSTREAM_REPO)
        # the engine's own dependency versions are part of the baseline
        # identity (the compat branch pins them exactly; review, 2026-08-28)
        from importlib.metadata import version
        self.assertEqual("0.9.1", version("osut"))
        self.assertEqual("0.4.0", version("oslg"))

    def test_uprate_derate_meets_effective_targets(self):
        # The Ruby gate, verbatim: with tbd available,
        # apply_prescriptive(thermal_bridging='efficient (BETBG)') must log a
        # thermal_bridging decision citing Σψ, land the derated roof U
        # at/below 0.156, and surface TBD's 'Unable to uprate' refusal on
        # this fixture's tiny walls as an audit WARNING.
        from btap.audit import AuditLog

        model = load_raw_fixture()
        audit = self.n.apply_prescriptive(model, vintage='2020', hdd=HDD,
                                          thermal_bridging='efficient (BETBG)',
                                          audit=AuditLog())

        decision = next((e for e in audit.entries
                         if e['step'] == 'thermal_bridging'
                         and e['level'] == 'decision'), None)
        self.assertIsNotNone(decision, 'TBD uprate/derate decision logged')
        self.assertGreater(decision['inputs']['surfaces_derated'], 0)
        self.assertRegex(decision['article'], 'Σψ')

        # ROOFS: uprating succeeds — the derated effective U lands at/below
        # the target
        roof = next(s for s in model.getSurfaces()
                    if s.outsideBoundaryCondition() == 'Outdoors'
                    and s.surfaceType() == 'RoofCeiling')
        conductance = (roof.construction().get().to_Construction().get()
                       .thermalConductance())
        self.assertTrue(conductance.is_initialized())
        roof_u = conductance.get()
        self.assertLessEqual(roof_u, 0.156 + 1e-3,
                             f'derated roof U ({round(roof_u, 4)}) meets the '
                             'effective target 0.156')

        # WALLS: this fixture's tiny walls have edge losses alone above the
        # target — physically infeasible — and TBD's refusal must be LOUD
        infeasible = next((w for w in audit.warnings
                           if 'Unable to uprate' in w['action']), None)
        self.assertIsNotNone(infeasible,
                             'infeasible uprate must surface as a warning')

        per_surface = [e for e in audit.entries
                       if 'surface derated' in e['action']]
        self.assertTrue(per_surface,
                        'per-surface derating evidence in the audit')

    def test_reference_envelope_keeps_the_effective_target_after_rebuild(self):
        # The reference path REBUILDS opaque constructions as lightweight
        # assemblies after the prescriptive/TBD step — a later transform
        # erasing the uprate would leave the standalone TBD gate green while
        # the assembled reference silently reverts to clear-field. Assert the
        # FINAL post-rebuild reference still carries the effective roof
        # target.
        from btap.audit import AuditLog

        model = load_raw_fixture()
        audit = AuditLog()
        self.n.reference_envelope(model, vintage='2020', hdd=HDD,
                                  thermal_bridging='efficient (BETBG)',
                                  audit=audit)

        self.assertTrue(any(e['step'] == 'thermal_bridging'
                            and e['level'] == 'decision'
                            for e in audit.entries),
                        'the TBD pass ran inside the reference sequence')
        roof = next(s for s in model.getSurfaces()
                    if s.outsideBoundaryCondition() == 'Outdoors'
                    and s.surfaceType() == 'RoofCeiling')
        conductance = (roof.construction().get().to_Construction().get()
                       .thermalConductance())
        self.assertTrue(conductance.is_initialized())
        self.assertLessEqual(
            conductance.get(), 0.156 + 1e-3,
            'the FINAL reference roof (after the lightweight rebuild) must '
            'still meet the effective target — nothing downstream may erase '
            'the uprate')

    def test_invalid_psi_set_aborts_through_the_real_engine(self):
        # Review finding (2026-08-28), reproduced BEFORE the fix: TBD
        # reports an invalid PSI set by LOGGING fatal and returning a
        # PARTIAL result (status 5, all 30 surfaces present) — and the
        # adapter narrated it as 'assemblies uprated'. The mocked-exception
        # negative control below cannot see that path; this one drives the
        # REAL engine. Fixed Ruby-first (the Ruby module had the identical
        # flaw, pinned by its own test).
        from btap.audit import AuditLog

        audit = AuditLog()
        with self.assertRaises(RuntimeError) as ctx:
            self.n.thermal_bridging.apply(load_raw_fixture(), vintage='2020',
                                          hdd=HDD, psi_set='no such set',
                                          audit=audit)
        self.assertIn('TBD FAILED', str(ctx.exception))
        self.assertIn('NOT been applied', str(ctx.exception))
        self.assertFalse(any(e['step'] == 'thermal_bridging'
                             and e['level'] == 'decision'
                             for e in audit.entries),
                         'no uprated decision may be recorded for a failed run')
        self.assertFalse(any('NOT accounted' in w['action']
                             for w in audit.warnings),
                         'a processing failure must never be relabeled as '
                         'unavailability')

    def test_broken_engine_install_propagates_never_relabels(self):
        # Review finding (2026-08-28): a BROKEN py-tbd installation (a
        # missing/broken transitive dep) must propagate as an error, never
        # take the benign 'tbd is not available' fallback — only absence of
        # the top-level package does. Simulated by making the import of tbd
        # fail from INSIDE (ModuleNotFoundError naming a dependency).
        import builtins
        import sys

        tb = self.n.thermal_bridging
        real_import = builtins.__import__

        def broken(name, *args, **kwargs):
            if name == 'tbd':
                raise ModuleNotFoundError("No module named 'py_topolys'",
                                          name='py_topolys')
            return real_import(name, *args, **kwargs)

        saved_memo = tb._available
        saved_module = sys.modules.pop('tbd', None)
        try:
            tb._available = None
            with mock.patch('builtins.__import__', side_effect=broken):
                with self.assertRaises(ModuleNotFoundError):
                    tb.is_available()
            # absence of tbd ITSELF still takes the benign branch
            def absent(name, *args, **kwargs):
                if name == 'tbd':
                    raise ModuleNotFoundError("No module named 'tbd'",
                                              name='tbd')
                return real_import(name, *args, **kwargs)
            tb._available = None
            with mock.patch('builtins.__import__', side_effect=absent):
                self.assertFalse(tb.is_available())
        finally:
            tb._available = saved_memo
            if saved_module is not None:
                sys.modules['tbd'] = saved_module

    def test_available_engine_failure_aborts_never_degrades(self):
        # Negative control (review gate 9): an AVAILABLE engine that FAILS
        # must abort the run — relabeling a processing failure as mere
        # unavailability would silently produce clear-field values behind a
        # warning that claims the gem is missing.
        from btap.audit import AuditLog

        audit = AuditLog()
        with mock.patch('btap.necb.envelope.thermal_bridging._process',
                        side_effect=RuntimeError('forced engine failure')):
            with self.assertRaises(RuntimeError) as ctx:
                self.n.thermal_bridging.apply(load_raw_fixture(),
                                              vintage='2020', hdd=HDD,
                                              audit=audit)
        self.assertIn('forced engine failure', str(ctx.exception))
        self.assertFalse(any('NOT accounted' in w['action']
                             for w in audit.warnings),
                         'a processing failure must never be relabeled as '
                         'unavailability')

if __name__ == '__main__':
    unittest.main()
