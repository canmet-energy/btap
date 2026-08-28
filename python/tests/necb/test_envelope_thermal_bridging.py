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

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.necb.support import load_raw_fixture, needs_sdk
from tests.support import needs_tbd

HDD = 3890
RUBY_PROBE = Path(__file__).parent / "cross_language" / "ruby_tbd_reference.rb"


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


@needs_tbd
@unittest.skipUnless(shutil.which('ruby'), 'the cross-language gate needs ruby')
class TestThermalBridgingCrossLanguage(unittest.TestCase):
    """Direct Ruby/Python TBD.process parity on the btap fixture (review
    gate 4): key sets in both directions; surface deratable/heatloss/ratio/u;
    edge type/length/PSI set; and both compliance paths' audits (gate 7 lives
    in its own module below). The Ruby side is the PINNED gem triplet
    (tbd 3.5.2 / osut 0.8.2 / topolys 0.6.2) — the baseline the compat
    branch exists to match."""

    def ruby_tbd_available(self):
        probe = subprocess.run(
            ['ruby', '-e', 'require "tbd"; print TBD::VERSION'],
            capture_output=True, text=True)
        return probe.returncode == 0, probe.stdout.strip()

    def test_process_parity_on_the_btap_fixture(self):
        # BTAP_TBD_REQUIRED governs the PY-TBD engine (needs_tbd above);
        # the RUBY gem is a separate dependency with the family's existing
        # flag: TBD_REQUIRED=1, set wherever the pinned triplet is installed
        # (the matrix envelope leg and verify) — the bare python job
        # deliberately has only the Python engine.
        ok, version = self.ruby_tbd_available()
        if not ok:
            if os.environ.get('TBD_REQUIRED') == '1':
                self.fail('TBD_REQUIRED=1 but the Ruby tbd gem is not '
                          'installed (ruby legacy_pin/tbd_triplet.rb prints '
                          'the pinned install args)')
            self.skipTest('needs the pinned Ruby tbd gem beside py-tbd '
                          '(TBD_REQUIRED=1 makes this a failure)')
        self.assertEqual('3.5.2', version,
                         'the Ruby side must be the PINNED 3.5.2 baseline')

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'ruby.json'
            proc = subprocess.run(['ruby', str(RUBY_PROBE), str(out)],
                                  capture_output=True, text=True)
            self.assertEqual(0, proc.returncode,
                             f'ruby probe failed: {proc.stderr[-2000:]}')
            ruby = json.loads(out.read_text(encoding='utf-8'))
            python = _python_process_snapshot()

        # key sets, BOTH directions
        self.assertEqual(sorted(ruby['surfaces']), sorted(python['surfaces']))
        self.assertEqual(sorted(map(str, ruby['edges'])),
                         sorted(map(str, python['edges'])))

        for name in ruby['surfaces']:
            rs, ps = ruby['surfaces'][name], python['surfaces'][name]
            self.assertEqual(rs['deratable'], ps['deratable'], name)
            for key in ('heatloss', 'ratio', 'u'):
                if rs[key] is None:
                    self.assertIsNone(ps[key], f'{name}.{key}')
                else:
                    self.assertAlmostEqual(rs[key], ps[key], delta=1e-9,
                                           msg=f'{name}.{key}')
        for key in ruby['edges']:
            re_, pe = ruby['edges'][key], python['edges'][key]
            self.assertEqual(re_['type'], pe['type'], key)
            self.assertEqual(re_['psi_set'], pe['psi_set'], key)
            self.assertAlmostEqual(re_['length'], pe['length'], delta=1e-9,
                                   msg=f'{key}.length')
            self.assertEqual(sorted(re_['surfaces']), sorted(pe['surfaces']),
                             key)
        self.assertEqual(ruby['warnings'], python['warnings'],
                         'the engines must refuse/warn identically')
        # non-vacuous: real derating happened on both sides
        self.assertGreater(
            sum(1 for s in ruby['surfaces'].values()
                if abs(s['heatloss'] or 0) > 1e-9), 0)


@needs_tbd
@unittest.skipUnless(shutil.which('ruby'), 'the cross-language gate needs ruby')
class TestThermalBridgingLegB(unittest.TestCase):
    """The assembled Leg-B thermal-bridging case (review gate 7): the
    existing corpus never requests thermal bridging, so re-running it proves
    nothing for M7. This runs the FULL compliance pipeline on both sides
    with thermal_bridging='efficient (BETBG)' (simulate none — the reference
    transforms, TBD pass included) and diffs audit.json/report.json under
    the Leg-B rules."""

    COMPLIANCE_PROBE = (Path(__file__).parent / 'cross_language'
                        / 'ruby_tbd_compliance.rb')

    def test_compliance_with_thermal_bridging_is_cross_language_equivalent(self):
        import importlib.util

        from btap.necb import performance_compliance
        from tests.necb.support import compliance_fixture
        from tests.support import REPO_ROOT

        probe = subprocess.run(
            ['ruby', '-e', 'require "tbd"; print TBD::VERSION'],
            capture_output=True, text=True)
        if probe.returncode != 0:
            if os.environ.get('TBD_REQUIRED') == '1':
                self.fail('TBD_REQUIRED=1 but the Ruby tbd gem is not '
                          'installed')
            self.skipTest('needs the pinned Ruby tbd gem beside py-tbd '
                          '(TBD_REQUIRED=1 makes this a failure)')

        with tempfile.TemporaryDirectory() as tmp:
            ruby_dir = Path(tmp) / 'ruby'
            proc = subprocess.run(
                ['ruby', str(self.COMPLIANCE_PROBE), str(ruby_dir)],
                capture_output=True, text=True)
            self.assertEqual(0, proc.returncode,
                             f'ruby compliance probe failed: '
                             f'{proc.stderr[-2000:]}')

            py_dir = Path(tmp) / 'py'
            performance_compliance(
                compliance_fixture(), vintage='2020', simulate='none',
                hdd=HDD, building={'storeys': 1},
                thermal_bridging='efficient (BETBG)', run_dir=str(py_dir))

            compare = REPO_ROOT / 'verification' / 'compare_runs.py'
            spec_module = importlib.util.module_from_spec(
                importlib.util.spec_from_file_location('compare_runs',
                                                       compare))
            spec_module.__spec__.loader.exec_module(spec_module)
            spec = spec_module.load_spec(REPO_ROOT / 'verification'
                                         / 'spec.json')
            diffs = []
            # compare_file, not a hand-rolled diff: production first strips
            # spec['strip_keys'] recursively, and bypassing that would make
            # this test fail on a deliberately ignored path later (review,
            # 2026-08-28).
            for name in spec['files']:
                spec_module.compare_file(str(ruby_dir), str(py_dir), name,
                                         spec, diffs)
            self.assertEqual(
                [], diffs,
                'thermal-bridging compliance runs diverge under Leg-B '
                'rules:\n' + '\n'.join(diffs))
            # non-vacuous: the TBD pass really fired in the Ruby run
            audit = json.loads((ruby_dir / 'audit.json')
                               .read_text(encoding='utf-8'))
            self.assertTrue(any(e.get('step') == 'thermal_bridging'
                                and e.get('level') == 'decision'
                                for e in audit),
                            'the 3.1.1.7 TBD decision must be in the '
                            'compared audit')


def _python_process_snapshot():
    """The Python half of the process-parity gate — the SAME extraction the
    Ruby probe performs, through btap's own adapter arguments."""
    import tbd

    from btap._sdk import load_model
    from btap.necb.envelope.rules import max_u
    from tests.support import FIXTURE_OSM

    model = load_model(FIXTURE_OSM)
    argh = {'uprate_walls': True, 'uprate_roofs': True, 'uprate_floors': True,
            'wall_option': 'all wall constructions',
            'roof_option': 'all roof constructions',
            'floor_option': 'all floor constructions',
            'option': 'efficient (BETBG)',
            'wall_ut': max_u(vintage='2020', surface='wall',
                             boundary='outdoors', hdd=HDD),
            'roof_ut': max_u(vintage='2020', surface='roofceiling',
                             boundary='outdoors', hdd=HDD),
            'floor_ut': max_u(vintage='2020', surface='floor',
                              boundary='outdoors', hdd=HDD)}
    tbd.oslg.clean()
    result = tbd.process(model, argh)

    surfaces = {}
    for name, s in (result.get('surfaces') or {}).items():
        surfaces[str(name)] = {
            'deratable': bool(s.get('deratable')),
            'heatloss': (None if s.get('heatloss') is None
                         else float(s['heatloss'])),
            'ratio': None if s.get('ratio') is None else float(s['ratio']),
            'u': None if s.get('u') is None else float(s['u'])}
    edges = {}
    io_edges = (result.get('io') or {}).get('edges') or []
    for e in io_edges:
        key = '%s|%s|%.6f' % (e['type'], '/'.join(sorted(map(str, e['surfaces']))),
                              float(e['length']))
        edges[key] = {'type': str(e['type']), 'psi_set': str(e['psi']),
                      'length': float(e['length']),
                      'surfaces': sorted(map(str, e['surfaces']))}
    warnings = [str(entry['message']) for entry in tbd.oslg.logs()
                if int(entry['level']) >= 3]
    return {'surfaces': surfaces, 'edges': edges, 'warnings': warnings}


if __name__ == '__main__':
    unittest.main()
