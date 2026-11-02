"""#169: no NEW unguarded unwrap of a crash-family SDK optional.

An empty `boost::optional<T>` behaves three ways when unwrapped without a
guard, measured in #164 and classified by `scripts/sdk_api.py`: a value type
raises `SystemError`, `OptionalModel` and `OptionalScheduleType` return a
default object, and everything else SEGFAULTS — 897 of the 2094 names
declared in the `model/` and `utilities/**` headers, plus every
proxy-generated accessor that returns one. A segfault takes the process, and in a test run the
whole xdist worker, reported as a lost node rather than a failure.

The baseline carries 2629 names: 897 declared in the headers plus 1732 found
only in the proxy files' module-level helpers, whose RETURN ANNOTATION says
they yield an `Optional*`. Those helpers are the `to_<Class>` casts, the
`get<Class>` and `get<Class>ByName` lookups, and six deprecated ALIASES whose
name does not match the class they return. A gate built from the headers alone
could see none of them — and two successive attempts to add them by NAME SHAPE
each missed a family, which is why the derivation is keyed on the annotation.

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
    - a two-step `x = obj.accessor()` then `x.get()` IS walked
      (`_two_step_sites`), through the five binding forms `_bindings` handles:
      `Assign` to a Name, every target of a chained assignment, a positional
      tuple unpack, `AnnAssign`, the walrus, a `for`/comprehension target over
      a literal sequence, and a conditional on either branch. The for-target
      idiom is PROVEN visible: removing the guard in `unitary_children`
      (`modeling/hvac/components/coils.py`) reddens the gate. Function names,
      not line numbers, because the sites move — `_apply_zone_fan_rules` in
      `codes/necb/hvac/reference.py`, `unitary_children` in
      `components/coils.py`, `_zonal_hp_coil` in `classify.py`;
    - still invisible, each with NO HAZARDOUS product instance: an attribute or
      subscript target (`reference.py` binds one in `_apply_zone_fan_rules`, to
      a NON-optional `availabilitySchedule()`, so the honest claim is "no
      hazardous instance" rather than "none"), a starred or nested unpack, a
      module- or class-level binding, and a tuple target over a literal
      iterable. A two-step site inside a NESTED function is counted under both
      the inner and the outer function, since `ast.walk` descends into nested
      defs: zero product instances, and over-reporting is the safe direction;
    - an alias or a `getattr` call is invisible, as is anything
      inter-procedural;
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
    guards_by_text: dict = {}
    stmt_end: dict = {}
    for path in sorted(PRODUCT.rglob('*.py')):
        source = path.read_text(encoding='utf-8')
        lines = source.splitlines()
        tree = ast.parse(source)
        rel = path.relative_to(PRODUCT).as_posix()
        # `{receiver source: [lines where it is GUARDED]}` — an
        # `is_initialized`/`empty` call whose own receiver unparses the same.
        guards_by_text.setdefault(path, {})
        for g in ast.walk(tree):
            if (isinstance(g, ast.Call) and isinstance(g.func, ast.Attribute)
                    and g.func.attr in ('is_initialized', 'empty', 'is_empty')):
                try:
                    text = ast.unparse(g.func.value)
                except Exception:               # pragma: no cover
                    continue
                guards_by_text[path].setdefault(text, []).append(g.lineno)
        # last line of the statement each line belongs to, so a guard trailing
        # the unwrap inside one expression still counts
        for stmt in ast.walk(tree):
            if isinstance(stmt, ast.stmt):
                for line in range(stmt.lineno,
                                  getattr(stmt, 'end_lineno', stmt.lineno) + 1):
                    stmt_end[line] = max(stmt_end.get(line, 0),
                                         getattr(stmt, 'end_lineno', stmt.lineno))
        for key, count in _two_step_sites(tree, accessors).items():
            found[rel][key] += count
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
            # Guards are matched in the AST, not in source text. A text
            # rule compared `ast.unparse(inner)` against the lines, which
            # disagrees on every formatting difference — single vs double
            # quotes (unparse always emits single), f-strings, `1.` vs `1.0`,
            # inner whitespace, a multi-line receiver — and, worse, could not
            # see a guard on the FOLLOWING line. It flagged two genuinely
            # guarded sites: a comprehension whose filter trails the unwrap
            # (`codes/necb/hvac/efficiency.py:2393`) and a ternary split
            # across lines (`reference.py:2608`). Both were grandfathered as
            # unguarded, which is a baseline growing for no reason.
            try:
                receiver = ast.unparse(inner)
            except Exception:                       # pragma: no cover
                receiver = None
            if receiver and receiver in guards_by_text.get(path, {}):
                span = guards_by_text[path][receiver]
                # within the enclosing statement, or the three lines above
                if any(node.lineno - 3 <= line <= stmt_end.get(node.lineno,
                                                               node.lineno)
                       for line in span):
                    continue
            if 'opt(' in lines[node.lineno - 1]:
                continue
            rel = path.relative_to(PRODUCT).as_posix()
            found[rel][f'{_enclosing(tree, node)}:{accessor}'] += 1
    return found


def _enclosing(tree, target):
    """Dotted name of the scope containing `target`, or `<module>`.

    The key includes it because `(file, accessor)` alone let a site be SWAPPED:
    guard one `outboardOANode` unwrap and add a new unguarded one elsewhere in
    the same file, and the count stays at 2 — nothing rises, nothing dies, all
    green, and prune-only `regenerate()` never runs because nothing failed
    (Fable, second review of #171). `vav_reheat.py` had `to_Node: 4` and three
    files share `airLoopHVACOutdoorAirSystem: 3`, so the hole was live.

    CLASS-QUALIFIED (#175). A bare function name let two classes in one file
    share a key, so the same swap worked between them. Measured across `btap`:
    `simulation/backends.py` defines `execute` in three classes and `__init__`
    in three, and `_mcp.py` defines `__init__` in two — no crash-family unwrap
    sits in either today, which is why Fable scored it zero instances over the
    21 files the baseline covers, but the shape exists in product code and the
    qualification costs one walk.
    """
    scopes = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            for child in ast.iter_child_nodes(node):
                scopes[id(child)] = node

    # innermost enclosing scope by line span, then walk out through its parents
    best = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end = getattr(node, 'end_lineno', node.lineno)
        if node.lineno <= target.lineno <= end:
            best = node
    if best is None:
        return '<module>'
    parts, cursor = [best.name], best
    while id(cursor) in scopes:
        cursor = scopes[id(cursor)]
        parts.append(cursor.name)
    return '.'.join(reversed(parts))


def _accessor(value, accessors):
    """The crash-family accessor this expression calls, or None.

    It DESCENDS through a conditional, because the common product idiom binds
    through one:

        loop = unitary.airLoopHVAC() if unitary is not None else None
        ...
        loop.get()

    Four sites in `btap` bind that way and later unwrap —
    `codes/necb/hvac/efficiency.py:3332` and `:3368`,
    `codes/necb/shw/efficiency.py:365`, `modeling/geometry/plan.py:239` — all
    guarded today, so a NEW unguarded one was the invisible case (Fable, review
    of #178; it was the shape none of my five snippets reached, which is the
    failure mode of every evasion table I write).

    The reasoning matches `_iter_bindings`: the name holds an optional on at
    least one path, so it must be guarded. Descending here covers a conditional
    inside a tuple element, a for-iterable, an `AnnAssign` and the walrus
    without `_bindings` knowing anything about it.

    `BoolOp` is included for the same reason and has zero product instances.
    """
    if (isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and value.func.attr in accessors):
        return value.func.attr
    if isinstance(value, ast.IfExp):
        return (_accessor(value.body, accessors)
                or _accessor(value.orelse, accessors))
    if isinstance(value, ast.BoolOp):
        for operand in value.values:
            found = _accessor(operand, accessors)
            if found:
                return found
    return None


def _zip_targets(target, value, accessors):
    """`a, b = obj.to_A(), obj.to_B()` — pairwise, positionally.

    Only when both sides are literal sequences of the same length. A starred
    target or a mismatched length is skipped rather than guessed at: binding
    the wrong name to an accessor would flag an unrelated unwrap.
    """
    if not (isinstance(target, (ast.Tuple, ast.List))
            and isinstance(value, (ast.Tuple, ast.List))
            and len(target.elts) == len(value.elts)):
        return {}
    out = {}
    for one, expr in zip(target.elts, value.elts):
        accessor = _accessor(expr, accessors)
        if isinstance(one, ast.Name) and accessor:
            out[one.id] = accessor
    return out


def _iter_bindings(target, iterable, accessors):
    """`for x in (obj.to_A(), obj.to_B()):` and the comprehension form.

    Every element binds the SAME name in turn, so one accessor among them is
    enough to make the name an optional for this walk's purposes. An arbitrary
    iterable expression says nothing about what it yields and binds nothing.
    """
    if not (isinstance(target, ast.Name)
            and isinstance(iterable, (ast.Tuple, ast.List, ast.Set))):
        return {}
    for expr in iterable.elts:
        accessor = _accessor(expr, accessors)
        if accessor:
            return {target.id: accessor}
    return {}


def _bindings(node, accessors):
    """Every name this node binds to a crash-family accessor's result.

    Five forms, all of which product code could use today and four of which
    the walk missed until Fable enumerated them (#175). The two it had were
    `Assign` to a single Name and the walrus; the walrus alone took three
    attempts, because the `.get()` RECEIVER is the `NamedExpr`, not its target.

    Deliberately NOT handled, with zero product instances each: an attribute
    or subscript target (`self.x = obj.to_X()`), which would need the walk to
    track object state rather than local names, and a starred unpack.
    """
    if isinstance(node, ast.Assign):
        # EVERY target: `x = y = obj.to_X()` bound neither when this required
        # exactly one, and iterating costs nothing (Fable, review of #178).
        out = {}
        accessor = _accessor(node.value, accessors)
        for target in node.targets:
            if isinstance(target, ast.Name) and accessor:
                out[target.id] = accessor
            else:
                out.update(_zip_targets(target, node.value, accessors))
        return out
    # `x: Construction = obj.to_Construction()` — an annotation changes the
    # node type, not the hazard.
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        accessor = _accessor(node.value, accessors)
        return {node.target.id: accessor} if accessor else {}
    if isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
        accessor = _accessor(node.value, accessors)
        return {node.target.id: accessor} if accessor else {}
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return _iter_bindings(node.target, node.iter, accessors)
    if isinstance(node, ast.comprehension):
        return _iter_bindings(node.target, node.iter, accessors)
    return {}


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
            bound.update(_bindings(node, accessors))
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
                                           'empty', 'isNull', 'has_value')
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
                counts[f'{_enclosing(tree, node)}:{bound[name]}'] += 1
    return counts


class TestNoNewUnguardedCrashFamilyUnwrap(unittest.TestCase):

    def test_the_baseline_file_is_present_and_shaped(self):
        """It must fail loudly rather than vacuously pass if the file goes."""
        self.assertTrue(BASELINE.is_file(), f'missing baseline: {BASELINE}')
        accessors = crash_family_accessors()
        # Above 2000 because the baseline is 2629: 897 header-declared plus
        # 1732 proxy-derived. A floor must sit below the true figure and above
        # a collapse — losing the proxy derivation leaves 897, losing
        # everything leaves 0, and both fail here. (897 and 1732, not the
        # earlier 794 and 1733: `utilities/**` joined the header scan in #175,
        # and `getMaterial` moved from proxy-only to declared because
        # utilities declares it too.) The previous floor was
        # 3000, set against a 7993 baseline that derived three speculative
        # names per class; annotation-derivation is smaller and more accurate,
        # so the floor moved down with it.
        self.assertGreater(
            len(accessors), 2000,
            'the crash-family list has collapsed; regenerate it with '
            '`sdk_api.py optionals --family crash --json`')
        # The floor used to be 500 — BELOW the 794 the baseline held before the
        # casts were added. So losing every cast and regenerating would have
        # left this green, and the gate would have gone back to missing the
        # hazard it is named for (Fable, second review of #171). These two pin
        # the family that `opt()`'s docstring warns about first.
        # ONE PIN PER SWIG-GENERATED FAMILY. `TestTheWalkItself` can prove the
        # walk works but can never notice a name missing from the baseline —
        # its `ACCESSORS` are hand-picked, so a probe for an absent name
        # returns 0 vacuously. These pins are the only defence, and they need
        # an entry per family because the gate has now shipped twice with a
        # whole family missing: the `to_<Class>` casts, then
        # `get<Class>ByName` (#171, two review rounds). Verified that
        # `getThermalZoneByName('nope').get()` dumps core.
        for name, family in (
                ('to_Node', 'to_<Class> cast'),
                ('to_Construction', 'to_<Class> cast'),
                ('getConstructionByName', 'get<Class>ByName'),
                ('getThermalZoneByName', 'get<Class>ByName'),
                ('getThermalZone', 'get<Class> by handle'),
                # The aliases: name does NOT match the class returned, so a
                # name-shape derivation cannot reach them. Product code
                # constructs `AirTerminalSingleDuctUncontrolled` at four
                # sites, so this unwrap is a line someone may write.
                ('to_AirTerminalSingleDuctUncontrolled', 'deprecated alias'),
                ('to_DistrictHeating', 'deprecated alias')):
            self.assertIn(
                name, accessors,
                f'{name} missing — the {family} family is derived from the '
                'proxy class tree, so `_CLASS`, `_proxy_files()` or '
                '`generated_accessors()` has regressed')
        self.assertNotIn(
            'getThermalZones', accessors,
            'the PLURAL family returns a vector, not an optional; including '
            'it would flag `.get()` calls that are not unwraps at all')

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


class TestTheWalkItself(unittest.TestCase):
    """One snippet per shape, through the REAL walk.

    Until this existed every shape was verified by hand-editing
    `vav_reheat.py` and running the suite, which is why the walrus took three
    attempts and why `.empty()` went unrecognised through a whole review
    round: a manual table only contains the cases its author thought of
    (Fable, second review of #171).

    `unguarded_sites` is pointed at a temp directory, so these run on a bare
    runner with no SDK and cost milliseconds.
    """

    ACCESSORS = {'outboardOANode', 'thermalZone', 'to_Node', 'to_ThermalZone',
                 'space', 'plantLoop'}

    def walk(self, source):
        import tempfile

        import tests.test_sdk_unwrap_ratchet as module
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'probe.py').write_text(source, encoding='utf-8')
            original = module.PRODUCT
            module.PRODUCT = root
            try:
                found = module.unguarded_sites(self.ACCESSORS)
            finally:
                module.PRODUCT = original
        return sum(sum(c.values()) for c in found.values())

    def test_shapes_that_must_be_FLAGGED(self):
        for label, body in (
                ('one-liner', 'def f(s):\n    return s.thermalZone().get()\n'),
                ('cast', 'def f(s):\n    return s.to_Node().get()\n'),
                ('chained', 'def f(s):\n'
                            '    return s.outboardOANode().to_Node().get()\n'),
                ('two-step', 'def f(s):\n    x = s.thermalZone()\n'
                             '    return x.get()\n'),
                ('walrus', 'def f(s):\n'
                           '    return (x := s.thermalZone()).get()\n'),
                ('subscript receiver',
                 'def f(ls):\n    return ls[0].thermalZone().get()\n'),
                ('guard on a DIFFERENT object',
                 'def f(s, t):\n    if t.thermalZone().is_initialized():\n'
                 '        pass\n    return s.thermalZone().get()\n'),
                # The four forms of #175. Each was reachable by product code
                # and bound nothing, so the unwrap read as being on a name the
                # walk had never seen and was silently ignored.
                ('annotated assignment',
                 'def f(s):\n    x: object = s.thermalZone()\n'
                 '    return x.get()\n'),
                ('tuple unpack, first element',
                 'def f(s):\n    x, y = s.thermalZone(), 1\n'
                 '    return x.get()\n'),
                ('tuple unpack, second element',
                 'def f(s):\n    y, x = 1, s.to_Node()\n'
                 '    return x.get()\n'),
                ('for-loop target over a tuple of accessor calls',
                 'def f(s):\n'
                 '    for x in (s.thermalZone(), s.space()):\n'
                 '        return x.get()\n'),
                ('comprehension target',
                 'def f(s):\n'
                 '    return [x.get() for x in (s.plantLoop(),)]\n'),
                # The accessor NOT first. Every snippet above put it in
                # position 0, so `_iter_bindings` scanning `elts[:1]` only
                # SURVIVED a mutation — the "one accessor among them is
                # enough" claim was untested (Fable, review of #178).
                ('for-loop target, accessor not first',
                 'def f(s):\n    for x in (1, s.thermalZone()):\n'
                 '        return x.get()\n'),
                # The shape none of my five reached. Four product sites bind
                # through a conditional and unwrap: efficiency.py:3332/:3368,
                # shw/efficiency.py:365, plan.py:239 — all guarded, so a new
                # unguarded one was the invisible case.
                ('conditional on the true branch',
                 'def f(s, c):\n'
                 '    x = s.thermalZone() if c else None\n'
                 '    return x.get()\n'),
                ('conditional on the false branch',
                 'def f(s, c):\n'
                 '    x = None if c else s.to_Node()\n'
                 '    return x.get()\n'),
                ('conditional inside a tuple element',
                 'def f(s, c):\n'
                 '    x, y = (s.space() if c else None), 1\n'
                 '    return x.get()\n'),
                # `BoolOp` had NO PIN until now: removing its branch from
                # `_accessor` left the whole harness green. Zero product
                # instances, so the choice was to pin it or drop it, and an
                # unfalsifiable rule is the thing this file keeps catching
                # itself on (Fable, follow-up on #178).
                ('a boolean fallback chain',
                 'def f(s, t):\n'
                 '    x = s.thermalZone() or t.thermalZone()\n'
                 '    return x.get()\n'),
                ('a chained assignment binds EVERY target',
                 'def f(s):\n    x = y = s.plantLoop()\n'
                 '    return y.get()\n'),
                ('list target',
                 'def f(s):\n    [x, y] = [s.thermalZone(), 1]\n'
                 '    return x.get()\n'),
        ):
            with self.subTest(shape=label):
                self.assertEqual(1, self.walk(body),
                                 f'{label} must be flagged:\n{body}')

    def test_shapes_that_must_NOT_be_flagged(self):
        for label, body in (
                # The same four forms, GUARDED — a form that flags everything
                # is as useless as one that flags nothing, and the guard scope
                # is per function, so each of these must come back clean.
                ('annotated assignment, guarded',
                 'def f(s):\n    x: object = s.thermalZone()\n'
                 '    if x.is_initialized():\n        return x.get()\n'
                 '    return None\n'),
                ('tuple unpack, guarded',
                 'def f(s):\n    x, y = s.thermalZone(), 1\n'
                 '    if not x.empty():\n        return x.get()\n'
                 '    return None\n'),
                ('for-loop target, guarded',
                 'def f(s):\n'
                 '    for x in (s.thermalZone(), s.space()):\n'
                 '        if x.is_initialized():\n            return x.get()\n'
                 '    return None\n'),
                ('comprehension target, guarded',
                 'def f(s):\n'
                 '    return [x.get() for x in (s.plantLoop(),)\n'
                 '            if x.is_initialized()]\n'),
                # An OPAQUE unpack binds nothing: the value is a single Name,
                # so there is no element to attribute an accessor to. This was
                # labelled "mismatched length" and never reached the length
                # rule at all — it is refused by the literal-sequence test
                # first, so the label described a check it did not exercise
                # (Fable, review of #178).
                ('opaque unpack',
                 'def f(s, pair):\n    x, y = pair\n    return x.get()\n'),
                ('conditional with no accessor on either branch',
                 'def f(s, c):\n    x = None if c else s.notAnAccessor()\n'
                 '    return x.get()\n'),
                # A LITERAL length mismatch. This raises `ValueError` if it
                # ever runs, which is why Fable suggested relabelling the
                # check as unpinnable — but the walk only PARSES, so the
                # snippet pins it fine, and without the length rule `zip`
                # would pair `x` with the accessor and flag it. Odd-looking on
                # purpose: it is the only input that reaches that branch.
                ('literal unpack whose sides disagree in length',
                 'def f(s):\n    x, y = s.thermalZone(), 1, 2\n'
                 '    return x.get()\n'),
                # An arbitrary iterable says nothing about what it yields.
                ('for-loop over an opaque iterable',
                 'def f(s, seq):\n    for x in seq:\n'
                 '        return x.get()\n'),
                ('is_initialized one-liner',
                 'def f(s):\n    x = s.thermalZone()\n'
                 '    if x.is_initialized():\n        return x.get()\n'
                 '    return None\n'),
                ('.empty() — the idiom at 19 of the grandfathered sites',
                 'def f(s):\n    x = s.thermalZone()\n'
                 '    if x.empty():\n        return None\n'
                 '    return x.get()\n'),
                ('opt() on the line',
                 'def f(s):\n    from btap._compat import opt\n'
                 '    return opt(s.thermalZone())\n'),
                ('opt() on the bound name',
                 'def f(s):\n    from btap._compat import opt\n'
                 '    x = s.thermalZone()\n    return opt(x)\n'),
                ('a .get() on something NOT an SDK accessor',
                 'def f(d):\n    return d.setdefault().get()\n'),
                ('dict.get with an argument',
                 'def f(d):\n    return d.get("k")\n'),
        ):
            with self.subTest(shape=label):
                self.assertEqual(0, self.walk(body),
                                 f'{label} must NOT be flagged:\n{body}')

    def test_regenerate_refuses_to_absorb_a_new_site(self):
        """`regenerate()`'s prune-only refusal, which was itself unpinned.

        The hole it closes: the dead-entry failure message used to name this
        command, which absorbed a new unguarded site and turned the suite
        green. Verified by raising a count against a stub fixture.
        """
        import json
        import tempfile

        import tests.test_sdk_unwrap_ratchet as module
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'probe.py').write_text(
                'def a(s):\n    return s.thermalZone().get()\n',
                encoding='utf-8')
            fixture = root / 'grandfathered.json'
            fixture.write_text(json.dumps(
                {'note': 'stub', 'total': 0, 'sites': {}}), encoding='utf-8')
            saved = (module.PRODUCT, module.GRANDFATHERED_FILE,
                     module.crash_family_accessors)
            module.PRODUCT = root
            module.GRANDFATHERED_FILE = fixture
            module.crash_family_accessors = lambda: {'thermalZone'}
            try:
                with self.assertRaises(SystemExit) as ctx:
                    module.regenerate()
                self.assertIn('refusing to raise', str(ctx.exception))
                self.assertEqual(
                    {'note': 'stub', 'total': 0, 'sites': {}},
                    json.loads(fixture.read_text(encoding='utf-8')),
                    'a refused regenerate must leave the fixture untouched')
                # and with the flag it writes
                module.regenerate(allow_new=True)
                self.assertEqual(
                    1, json.loads(fixture.read_text(encoding='utf-8'))['total'])
            finally:
                (module.PRODUCT, module.GRANDFATHERED_FILE,
                 module.crash_family_accessors) = saved

    def test_a_guarded_site_cannot_be_SWAPPED_for_an_unguarded_one(self):
        """The laundering hole `(file, accessor)` keying left open.

        Guard one site and add a new unguarded one in the same file with the
        same accessor, and a per-(file, accessor) count stays put: nothing
        rises, nothing dies, every test green, and prune-only `regenerate()`
        never runs because nothing failed. Keying by enclosing function makes
        the swap visible as one key dying and another appearing.
        """
        import tempfile

        import tests.test_sdk_unwrap_ratchet as module
        before = ('def a(s):\n    return s.thermalZone().get()\n\n'
                  'def b(s):\n    return 1\n')
        after = ('def a(s):\n    x = s.thermalZone()\n'
                 '    if x.is_initialized():\n        return x.get()\n'
                 '    return None\n\n'
                 'def b(s):\n    return s.thermalZone().get()\n')

        def keys(source):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / 'probe.py').write_text(source, encoding='utf-8')
                original = module.PRODUCT
                module.PRODUCT = root
                try:
                    found = module.unguarded_sites(self.ACCESSORS)
                finally:
                    module.PRODUCT = original
            return {k for counts in found.values() for k in counts}

        self.assertEqual({'a:thermalZone'}, keys(before))
        self.assertEqual(
            {'b:thermalZone'}, keys(after),
            'the swap must change the KEY, not just preserve a count — '
            'otherwise a new unguarded site rides in on a guarded one')


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
        self.assertEqual(committed['header_declarations'],
                         fresh['header_declarations'])
        self.assertEqual(committed['names_from_headers'],
                         fresh['names_from_headers'])
        self.assertEqual(committed['names_only_in_proxies'],
                         fresh['names_only_in_proxies'],
                         'the proxy-derived count moved: either the SDK '
                         'changed or `generated_accessors()` regressed')


if __name__ == '__main__':
    unittest.main()
