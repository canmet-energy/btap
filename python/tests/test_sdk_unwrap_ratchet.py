"""#169: no NEW unguarded unwrap of a crash-family SDK optional.

An empty `boost::optional<T>` behaves three ways when unwrapped without a
guard, measured in #164 and classified by `scripts/sdk_api.py`: a value type
raises `SystemError`, `OptionalModel` and `OptionalScheduleType` return a
default object, and everything else — 794 of the 2094 optional-returning
method names — SEGFAULTS. A segfault takes the process, and in a test run the
whole xdist worker, reported as a lost node rather than a failure.

phylroy's call (2026-11-01) is a RATCHET, not a migration: the 27 existing
sites stay, and a new one fails. The two I hand-checked are safe via guards a
4-line window cannot see — `costing/envelope/quantify.py`'s
`census_interzonal` is selected by a caller that tests `is_initialized()`, and
`modeling/geometry/bar.py` unwraps stories it just assigned — so a sweep would
have been 27 edits to working code for no measured defect.

WHY A COMMITTED BASELINE rather than deriving the method list at test time:
the crash-family names come from the SDK's C++ headers, which exist on the
`verify` image but NOT on the bare runner the `python` job uses. And `verify`
carries `if: github.event_name != 'pull_request'`, so it does not run on a PR
at all — a header-dependent gate would first fire on push to main, which is
after the thing it is meant to stop. So the names are generated offline into
`fixtures/sdk_crash_family_methods.json`, this gate reads that file anywhere,
and `TestTheBaselineMatchesTheHeaders` re-derives it where the headers exist.
"""

import ast
import collections
import json
import subprocess
import sys
import unittest
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parent.parent
PRODUCT = PYTHON_ROOT / 'btap'
BASELINE = Path(__file__).resolve().parent / 'fixtures' / 'sdk_crash_family_methods.json'
SDK_HEADERS = Path('/usr/local/openstudio-3.11.0/include/openstudio/model')

#: The grandfathered sites live in a GENERATED fixture, not in a literal
#: here. My first version typed the counts by hand from an earlier
#: measurement and three of eleven entries were wrong — which is the exact
#: defect issue #166 is about, committed inside the ratchet meant to guard
#: against it. Regenerate after a deliberate change:
#:
#:     python3 -c "import sys; sys.path.insert(0,'python'); \
#:       from tests.test_sdk_unwrap_ratchet import *; print(regenerate())"
#:
#: Per-(file, accessor) rather than per-file, so a SEVENTH unguarded unwrap in
#: `vav_reheat.py` still fails while the six already there do not.
GRANDFATHERED_FILE = (Path(__file__).resolve().parent / 'fixtures'
                      / 'sdk_unwrap_grandfathered.json')


def grandfathered():
    data = json.loads(GRANDFATHERED_FILE.read_text(encoding='utf-8'))
    return data['sites'], data['total']


def regenerate():
    """Rewrite the grandfathered fixture from the current tree."""
    found = unguarded_sites(crash_family_accessors())
    sites = {rel: dict(sorted(c.items())) for rel, c in sorted(found.items())}
    total = sum(sum(c.values()) for c in sites.values())
    GRANDFATHERED_FILE.write_text(
        json.dumps({'note': 'generated — see test_sdk_unwrap_ratchet.py',
                    'total': total, 'sites': sites}, indent=1, sort_keys=True)
        + '\n', encoding='utf-8')
    return f'{total} sites across {len(sites)} files'


def crash_family_accessors():
    data = json.loads(BASELINE.read_text(encoding='utf-8'))
    assert data['family'] == 'crash', data['family']
    return set(data['methods'])


def unguarded_sites(accessors):
    """`{relpath: {accessor: count}}` for `X.accessor().get()` with no guard.

    A guard is `is_initialized` within the preceding four lines, or `opt(` on
    the line itself. Deliberately crude: it over-reports, every sample checked
    so far was safe via a CALLER's guard, and the ratchet only cares that the
    number does not RISE. Tightening it would move every count and tell us
    nothing new.
    """
    found = collections.defaultdict(collections.Counter)
    for path in sorted(PRODUCT.rglob('*.py')):
        source = path.read_text(encoding='utf-8')
        lines = source.splitlines()
        for node in ast.walk(ast.parse(source)):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'get'
                    and not node.args and not node.keywords):
                continue
            inner = node.func.value
            if not (isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)):
                continue
            accessor = inner.func.attr
            if accessor not in accessors:
                continue
            context = '\n'.join(lines[max(0, node.lineno - 4):node.lineno])
            if 'is_initialized' in context or 'opt(' in lines[node.lineno - 1]:
                continue
            rel = path.relative_to(PRODUCT).as_posix()
            found[rel][accessor] += 1
    return found


class TestNoNewUnguardedCrashFamilyUnwrap(unittest.TestCase):

    def test_the_baseline_file_is_present_and_shaped(self):
        """It must fail loudly rather than vacuously pass if the file goes."""
        self.assertTrue(BASELINE.is_file(), f'missing baseline: {BASELINE}')
        accessors = crash_family_accessors()
        self.assertGreater(
            len(accessors), 500,
            'the crash-family list has collapsed; regenerate it with '
            '`sdk_api.py optionals --family crash --json`')

    def test_no_file_gains_an_unguarded_unwrap(self):
        found = unguarded_sites(crash_family_accessors())
        sites, _ = grandfathered()
        risen = []
        for rel, counts in sorted(found.items()):
            allowed = sites.get(rel, {})
            for accessor, count in sorted(counts.items()):
                if count > allowed.get(accessor, 0):
                    risen.append(
                        f'{rel}: {accessor}().get() x{count} '
                        f'(grandfathered {allowed.get(accessor, 0)})')
        self.assertEqual(
            [], risen,
            'NEW unguarded unwrap of a crash-family SDK optional. An empty one '
            'SEGFAULTS rather than raising, which reports as a lost xdist '
            'worker and not as a failure (#164, #169). Route it through '
            '`btap._compat.opt`. If the call genuinely cannot be empty, say '
            'why in a comment AND add it to GRANDFATHERED — the ratchet is '
            'there to make that a decision rather than an omission.\n  '
            + '\n  '.join(risen))

    def test_the_grandfathered_list_has_no_dead_entries(self):
        """A fixed site must leave the list, or the ratchet loosens silently.

        Reported as a failure, not a warning: a stale entry is permission for
        a future unguarded call at that exact spot.
        """
        found = unguarded_sites(crash_family_accessors())
        sites, _ = grandfathered()
        dead = []
        for rel, counts in sorted(sites.items()):
            for accessor, count in sorted(counts.items()):
                actual = found.get(rel, {}).get(accessor, 0)
                if actual < count:
                    dead.append(f'{rel}: {accessor} grandfathered {count}, '
                                f'now {actual}')
        self.assertEqual(
            [], dead,
            'these sites were fixed or moved — regenerate the fixture so the '
            'ratchet keeps its teeth (see GRANDFATHERED_FILE):\n  '
            + '\n  '.join(dead))

    def test_the_fixture_total_matches_its_own_sites(self):
        """The headline number must not drift from the detail it sums."""
        sites, total = grandfathered()
        self.assertEqual(
            total, sum(sum(c.values()) for c in sites.values()),
            'the fixture\'s `total` disagrees with its own `sites` — it was '
            'hand-edited rather than regenerated')


@unittest.skipUnless(SDK_HEADERS.is_dir(),
                     f'needs the SDK headers under {SDK_HEADERS}')
class TestTheBaselineMatchesTheHeaders(unittest.TestCase):
    """Drift check — only where the headers exist, which is `verify`.

    The gate above trusts a committed file. This is what stops that file
    going stale: on an SDK bump the regenerated names differ and this fails,
    where the gate itself would quietly keep enforcing yesterday's list.
    """

    def test_regenerating_reproduces_the_committed_baseline(self):
        script = PYTHON_ROOT / 'scripts' / 'sdk_api.py'
        out = subprocess.run(
            [sys.executable, '-I', str(script), 'optionals',
             '--family', 'crash', '--json'],
            capture_output=True, text=True, check=False, timeout=300)
        self.assertEqual(0, out.returncode, out.stderr[-400:])
        fresh = json.loads(out.stdout)
        committed = json.loads(BASELINE.read_text(encoding='utf-8'))
        self.assertEqual(
            committed['methods'], fresh['methods'],
            'the committed crash-family baseline no longer matches the '
            'headers. Regenerate: `python3 python/scripts/sdk_api.py '
            'optionals --family crash --json > '
            'python/tests/fixtures/sdk_crash_family_methods.json`')
        self.assertEqual(committed['declarations'], fresh['declarations'])


if __name__ == '__main__':
    unittest.main()
