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


def regenerate(allow_new=False):
    """Rewrite the grandfathered fixture — PRUNE-ONLY unless asked otherwise.

    The escape hatch this closes was real and I built it: guard one
    grandfathered site, add a new unguarded one, and both the rise check and
    the dead-entry check go red — whereupon the dead-entry message told the
    developer to run exactly this function, which absorbed the new site and
    turned both green (Fable, review of #171). My gate's own failure message
    was the bypass.

    So a count may only FALL here. Raising one, or adding a (file, accessor)
    the fixture does not list, requires `allow_new=True` — which is a
    deliberate act someone has to justify in a commit message, not a command
    an error message suggests.
    """
    found = unguarded_sites(crash_family_accessors())
    sites = {rel: dict(sorted(c.items())) for rel, c in sorted(found.items())}
    if not allow_new:
        committed, _ = grandfathered()
        risen = [f'{rel}: {acc} {committed.get(rel, {}).get(acc, 0)} -> {n}'
                 for rel, counts in sites.items()
                 for acc, n in counts.items()
                 if n > committed.get(rel, {}).get(acc, 0)]
        if risen:
            raise SystemExit(
                'refusing to raise the grandfathered counts — that is how a '
                'new unguarded unwrap gets laundered into the baseline. '
                'Guard the call, or call regenerate(allow_new=True) and say '
                'why in the commit message:\n  ' + '\n  '.join(risen))
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

    A guard is `is_initialized` in the THREE preceding lines or on the call's
    own line, or `opt(` on the call's line. `lines[lineno-4:lineno]` is three
    preceding plus the call — the first version of this docstring said four
    and was off by one (Fable, review of #171). Three is kept rather than
    widened: a narrower window counts a distant guard as absent, which
    over-reports, and over-reporting is the safe direction here.

    Crude in three further ways, all of which let a real hazard through, and
    all deliberate for a RATCHET whose only job is that the number not rise:

    - substring matching, so a COMMENT mentioning `is_initialized`, or a guard
      on a DIFFERENT object, reads as a guard;
    - only `X.accessor().get()`. A two-step `x = obj.accessor()` then
      `x.get()`, a walrus, an alias or a `getattr` is invisible — 240 of the
      444 zero-arg `.get()` calls in `btap` have a bare-Name receiver;
    - `btap/` only: `scripts/` and `tests/` are not walked, though test code
      is what produces the lost-xdist-worker symptom;
    - an ALIAS (`f = obj.accessor` then `f().get()`) or a
      `getattr(obj, 'accessor')().get()` still evades. Four `Call(Name)`
      receivers exist in `btap` today. Both shapes are contrived enough that
      catching them needs call-target resolution, and a gate that claims to
      stop a determined author is lying; this one stops an ordinary edit.

    Closing those needs same-function dataflow, which is a different tool. The
    gate's claim is narrow on purpose: no new unguarded ONE-LINER unwrap of a
    crash-family accessor or cast.
    """
    found = collections.defaultdict(collections.Counter)
    for path in sorted(PRODUCT.rglob('*.py')):
        source = path.read_text(encoding='utf-8')
        lines = source.splitlines()
        tree = ast.parse(source)
        rel = path.relative_to(PRODUCT).as_posix()
        for accessor, count in _two_step_sites(tree, accessors).items():
            found[rel][accessor] += count
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'get'
                    and not node.args and not node.keywords):
                continue
            inner = node.func.value
            # `(x := obj.accessor()).get()` — the receiver is a NamedExpr, so
            # neither this walk (which wants a Call) nor the two-step walk
            # (which wants a Name) saw it. Binding the walrus target in
            # `_two_step_sites` was not enough: the unwrap itself has to be
            # recognised here. Two fixes before this one missed that.
            if isinstance(inner, ast.NamedExpr):
                inner = inner.value
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


def _two_step_sites(tree, accessors):
    """`x = obj.accessor()` then `x.get()`, with no guard on `x` in the function.

    The one-liner walk below misses this shape entirely, and it is the common
    one: 240 of the 444 zero-arg `.get()` calls in `btap` have a bare-Name
    receiver (Fable, review of #171). Checked per FUNCTION, because that is the
    scope a guard plausibly lives in — `if x.is_initialized():` anywhere in the
    same function counts, wherever it sits relative to the unwrap.

    Deliberately not inter-procedural. Of the 108 existing two-step sites
    assigned from a crash-family accessor, exactly one has no guard anywhere in
    its function, which is the signal this is tight enough to be useful rather
    than noise.
    """
    counts = collections.Counter()
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        bound = {}
        for node in ast.walk(function):
            # `x = obj.accessor()`
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr in accessors):
                bound[node.targets[0].id] = node.value.func.attr
            # `(x := obj.accessor()).get()` — the walrus was the one evasion
            # of Fable's five that survived the first fix, because this walk
            # handled `Assign` only.
            elif (isinstance(node, ast.NamedExpr)
                    and isinstance(node.target, ast.Name)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr in accessors):
                bound[node.target.id] = node.value.func.attr
        if not bound:
            continue

        # Names guarded ANYWHERE in this function, matched as NODES. An
        # earlier version string-matched `ast.dump(function)` and reported 201
        # sites where the real figure is a handful — `ast.dump` carries
        # `ctx=Load()` and other fields, so the patterns never matched and
        # every guard read as absent.
        guarded = set()
        for node in ast.walk(function):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ('is_initialized', 'is_empty',
                                           'isNull', 'has_value')
                    and isinstance(node.func.value, ast.Name)):
                guarded.add(node.func.value.id)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id in ('opt', 'opt_or')
                  and node.args and isinstance(node.args[0], ast.Name)):
                guarded.add(node.args[0].id)

        for node in ast.walk(function):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == 'get'
                    and not node.args and not node.keywords
                    and isinstance(node.func.value, ast.Name)):
                continue
            name = node.func.value.id
            if name in bound and name not in guarded:
                counts[bound[name]] += 1
    return counts


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
            'these sites were fixed or moved — LOWER the counts in '
            'GRANDFATHERED_FILE so the ratchet keeps its teeth. '
            '`regenerate()` does that and is prune-only; it will refuse if a '
            'NEW unguarded site is also present, which is deliberate — this '
            'message used to suggest a command that absorbed one:\n  '
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
