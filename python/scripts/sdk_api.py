#!/usr/bin/env python3
"""Answer OpenStudio SDK API questions from the artifacts the image ships.

Three sources, and they answer different questions. None of them needs the
SDK imported, a network, or a running MCP server:

- the SWIG **Python proxy files** (``$SDK/Python/openstudio*.py``) carry the
  full class tree and parameter names. SWIG emits them beside the compiled
  bindings; they are read AS TEXT, never executed.
- the **C++ headers** (``$SDK/include/openstudio/model/*.hpp``) state return
  types exactly, including which methods return ``boost::optional<T>``.
- ``dir()``/``getattr()`` on the live module recovers method NAMES only — not
  parameters, not return types. That is why probing an SDK question feels
  adequate and is not.

Why this exists: `_as_layered` in `btap/modeling/envelope/constructions.py`
was first written with two downcasts tried in a documented order, and the
documented reason was invented — `Construction` and
`ConstructionWithInternalSource` are SIBLINGS under `LayeredConstruction`, so
the order preserved nothing. One ``tree`` query below says so outright. The
same class of mistake produced a hand-written four-case guard covering one
case (#165), and issues #166 and #169 were both opened from the two queries
here.

Usage:

    # the class tree: parents, and every subclass of a name
    python3 python/scripts/sdk_api.py tree LayeredConstruction
    python3 python/scripts/sdk_api.py tree ConstructionBase --subclasses

    # methods returning boost::optional<T>, classified by what an EMPTY one
    # DOES when unwrapped without a guard (measured in #164)
    python3 python/scripts/sdk_api.py optionals --family crash
    python3 python/scripts/sdk_api.py optionals --on ThermalZone

    # where a method is declared, with its signature
    python3 python/scripts/sdk_api.py method layers
"""
from __future__ import annotations

import argparse
import collections
import difflib
import json
import pathlib
import re
import sys

#: Overridable for a different install; the devcontainer and the CI image
#: (`canmet/os_sdk_container:3.11.0`, `nrel/openstudio:3.11.0`) both place the
#: SDK here, and `.github/workflows/test.yml` hardcodes the same path.
SDK = pathlib.Path('/usr/local/openstudio-3.11.0')

#: What an unguarded `.get()` on an EMPTY `boost::optional<T>` does, by T.
#: Measured in #164 over all 617 `openstudio.model.Optional*` types, one fresh
#: subprocess each: 615 exited with SIGSEGV. The exceptions are the
#: default-constructible ones.
RAISES = frozenset({'double', 'string', 'int', 'unsigned', 'float', 'bool',
                    'size_t', 'char'})
#: Measured one fresh subprocess each, not inferred. `Time`/`Date`/`DateTime`
#: were inferred in the first version of this file and later confirmed; the
#: utilities types below were flagged by review as wrongly classified crash and
#: then measured — they all return a default.
RETURNS_DEFAULT = frozenset({
    'Model', 'ScheduleType', 'Time', 'Date', 'DateTime',
    'path', 'DayOfWeek', 'NthDayOfWeekInMonth', 'FuelType', 'EndUseType',
    'InstallLocationType', 'EndUseCategoryType', 'Unit', 'TimeSeries',
    'SqlFile', 'CSVFile', 'IddObject',
    # Measured for #175, when `utilities/**` joined the header scan. Both
    # return a DEFAULT-CONSTRUCTED object from an EMPTY optional — neither
    # raises and neither crashes:
    #     OptionalQuantity().get()  -> Quantity
    #     OptionalIddField().get()  -> IddField
    # `Quantity` is the one that mattered: `convert` is overloaded
    # `optional<double>` / `optional<Quantity>`, and with `Quantity`
    # unmeasured the worst-of rule made `convert` crash-family, which would
    # have added 28 product sites to the grandfathered list for a call that in
    # practice returns a double and RAISES. Measuring beat exempting.
    'Quantity', 'IddField',
})

#: Measured as crashing, so they are NOT merely the unmeasured default.
#: Recorded because `family()` would reach the same answer by falling through,
#: and a reader cannot otherwise tell a measurement from a fallback.
MEASURED_CRASH = frozenset({'UUID', 'EpwFile', 'ViewFactor', 'WorkspaceObject'})

_CLASS = re.compile(r'^class\s+(\w+)\(([\w.]+)\)', re.M)

#: Matched against COMMENT-STRIPPED, WHITESPACE-FLATTENED text.
#:
#: The first version missed 41 declarations (review of #170), every one a
#: genuine public declaration: 21 prefixed `OS_DEPRECATED(...)`, 12 `static`
#: (`Model::load`, `Component::load`, `Space::fromFloorPrint`, …), 6 with an
#: aggregate T (`std::pair<ConstructionBase, int>`), and 2 whose T is two
#: words (`unsigned int`), which the old `[\w:]*` could not cross. None of
#: the 41 has a call site in `btap`, so nothing was being mis-guarded — the
#: fix matters because under-reporting is the dangerous direction for a tool
#: whose job is to find calls that can segfault.
#:
#: A multi-line declaration was NOT among the misses: `>\s+(\w+)` already
#: spans a newline under `re.M`. An earlier version of this comment claimed
#: otherwise and named a method the old regex in fact found.
#:
#: If you re-derive that 41, classify each match by its OWN matched text. Two
#: attempts here paired new matches against old ones by `(T, name)` instead,
#: which miscounts any name declared twice: `ScheduleTypeLimits::units` is
#: `static` at line 50 and plain at line 65, the old regex finds only the
#: plain one, and the pairing consumes the static match against it — leaving
#: the plain declaration looking "recovered" with no prefix. That artefact
#: produced a phantom "1 other" and, briefly, a comment claiming the split
#: was genuinely uncertain. It is 12 static, determinately.
_OPTIONAL = re.compile(
    r'(?:OS_DEPRECATED\s*\([^)]*\)\s+|static\s+|virtual\s+)*'
    r'boost::optional\s*<\s*'
    r'([^<>]*(?:<[^<>]*>[^<>]*)*?)'      # one level of nesting in T
    r'\s*>\s+(\w+)\s*\(')
_BLOCK_COMMENT = re.compile(r'/\*.*?\*/', re.S)
_LINE_COMMENT = re.compile(r'//[^\n]*')
_DECL = re.compile(r'^\s*(?:virtual\s+)?([\w:<>,\s*&]+?)\s+(\w+)\s*\(([^)]*)\)',
                   re.M)


def _die(message: str) -> None:
    sys.exit(f"sdk_api: {message}")


def _proxy_files() -> list[pathlib.Path]:
    found = sorted((SDK / 'Python').glob('openstudio*.py'))
    if not found:
        _die(f"no SWIG proxy files under {SDK / 'Python'} — is the SDK "
             f"installed, or has the image layout changed?")
    return found


def _headers() -> list[pathlib.Path]:
    """The public headers: `model/*.hpp` plus all of `utilities/**`.

    `utilities` was missing until #175. It declares 333 optional-returning
    method names that `model` does not, two of which are TRUE FALSE NEGATIVES
    the proxy annotations cannot reach because they are header-declared rather
    than SWIG-generated: `WorkflowJSON.getBCLMeasure` ->
    `optional<BCLMeasure>` and `LocalBCL`/`RemoteBCL.getComponent` ->
    `optional<BCLComponent>` (Fable, review of #171). Neither is called in
    `btap`.

    Adding them costs nothing in the fixture, which was the open question.
    Product code unwraps exactly five utilities-only names — `convert` (28
    sites) and `BoundingBox`'s `minX`/`minY`/`maxX`/`maxY` (4 each) — and every
    one returns `optional<double>` in practice, which is the RAISE family. The
    only reason `convert` looked like a crash-family hazard is its second
    overload returning `optional<Quantity>`, and the worst-of rule. Measuring
    `Quantity` rather than exempting `convert` settled it: see
    `RETURNS_DEFAULT`.

    `*_Impl.hpp` are the implementation classes: same methods, not the public
    surface, and counting both double-reports everything.
    """
    model = (SDK / 'include/openstudio/model').glob('*.hpp')
    utilities = (SDK / 'include/openstudio/utilities').rglob('*.hpp')
    found = [p for p in sorted([*model, *utilities])
             if not p.name.endswith('_Impl.hpp')]
    if not found:
        _die(f"no public headers under {SDK / 'include/openstudio'} — is this "
             f"an SDK install without headers?")
    return found


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding='utf-8', errors='replace')


def _declarations(source: str) -> str:
    """Comments gone, newlines flattened — see `_OPTIONAL` for why.

    Stripping comments FIRST is load-bearing for the widened match: on the
    current headers it removes 50 commented-out declarations (3172 raw ->
    3122). It was NOT load-bearing for the narrower first version, which
    counted 3081 either way — so a docstring saying the strip changes nothing
    was true once and is now false. `test_sdk_api_script` pins the headline
    count under a ceiling so that cannot drift again unnoticed.
    """
    source = _BLOCK_COMMENT.sub(' ', source)
    source = _LINE_COMMENT.sub(' ', source)
    return re.sub(r'\s+', ' ', source)


def class_tree() -> dict[str, str]:
    """``{class: immediate base}`` across every proxy module."""
    tree: dict[str, str] = {}
    for path in _proxy_files():
        for name, base in _CLASS.findall(_read(path)):
            tree[name] = base.split('.')[-1]
    return tree


def family(wrapped: str) -> str:
    """What an unguarded unwrap of an empty ``optional<wrapped>`` does.

    A T carrying a comma (``std::pair<ConstructionBase, int>``) is reported
    crash: the aggregate's behaviour was not measured, and for this tool
    over-reporting danger is the safe direction.
    """
    if ',' in wrapped or '<' in wrapped:
        return 'crash'
    if wrapped in RAISES:
        return 'raise'
    if wrapped in RETURNS_DEFAULT:
        return 'default'
    return 'crash'


#: A module-level proxy helper annotated with its optional return type. This
#: is the GENERIC hook. Two earlier versions derived the generated accessors
#: from NAME SHAPES — first `to_<Class>`, then `get<Class>ByName` and
#: `get<Class>` — and each missed a family until a review named it. Shapes
#: cannot see a name that disagrees with the class it returns, and six such
#: aliases exist (`to_DistrictHeating -> OptionalDistrictHeatingWater`,
#: `to_AirTerminalSingleDuctUncontrolled -> Optional...ConstantVolumeNoReheat`,
#: and their two `get*` forms each). Product code constructs
#: `AirTerminalSingleDuctUncontrolled` at four sites, so that unwrap is a line
#: someone may write. Classifying by the ANNOTATED TYPE gets them for free.
# The quote class and the module prefix cost two characters each and match
# nothing new today: every annotation in the 39 proxies is a bare
# `Optional<X>` or `<X>Vector`, only the two `_workspace_to_*` helpers are
# quoted, none is module-qualified, and no signature spans lines — Fable
# measured that with a deliberately looser regex that matched the same 1738
# names. They are here so a change in what SWIG emits shows up as a DRIFT
# failure rather than a silent shrink.
_PROXY_OPTIONAL = re.compile(
    r'^def (\w+)\(.*\) -> ["\']?(?:[\w.]*\.)?(Optional\w+)["\']?:',
    re.M)


def generated_accessors() -> dict[str, set[str]]:
    """Every proxy helper whose ANNOTATION says it returns ``optional<T>``.

    1738 of them across the 39 proxy files, in three shapes — `_get<X>`
    (1139), `_to_<X>` (597) and `_workspace_to_<X>` (2) — all assigned onto a
    class after definition, which is why a class-body search finds nothing and
    an earlier docstring here wrongly said the casts appear in no proxy file.

    The leading underscore is stripped: the public name is what product code
    calls. `T` comes from the annotation, so the family and the wrapped type
    are read from the same place and an alias cannot slip through.

    Deliberately NOT included: the plural `get<X>s`, which returns a vector —
    `.get()` on one is not an unwrap.
    """
    out: dict[str, set[str]] = {}
    for path in _proxy_files():
        for name, returned in _PROXY_OPTIONAL.findall(_read(path)):
            out.setdefault(name.lstrip('_'), set()).add(
                returned[len('Optional'):])
    return out


def optional_methods() -> tuple[dict[str, set[str]], int]:
    """``({method name: {wrapped types}}, declaration count)``.

    The two numbers differ a lot and conflating them was a documentation bug
    (#170 review): the dict is keyed by NAME, so ``schedule()`` declared on
    290 classes counts once. Quote the declaration count when describing the
    size of the surface, and the name count when describing the API.
    """
    out: dict[str, set[str]] = collections.defaultdict(set)
    declarations = 0
    for path in _headers():
        for wrapped, method in _OPTIONAL.findall(_declarations(_read(path))):
            wrapped = wrapped.strip()
            # Keep the namespace off a simple T, but leave an aggregate whole
            # so `family()` can see the comma.
            simple = wrapped.split('::')[-1] if ',' not in wrapped else wrapped
            out[method].add(simple)
            declarations += 1
    return dict(out), declarations


def cmd_tree(args) -> int:
    tree = class_tree()
    if args.name not in tree:
        # Substring alone misses a typo ('Constructionn' is a substring of
        # nothing), which is the case a suggestion is most wanted for.
        near = [n for n in tree if args.name.lower() in n.lower()]
        near += difflib.get_close_matches(args.name, tree, n=6, cutoff=0.6)
        unique = list(dict.fromkeys(near))[:8]
        _die(f"{args.name!r} is not a class in the proxy files"
             + (f". Did you mean: {', '.join(unique)}" if unique else ""))
    if args.subclasses:
        direct = sorted(k for k, v in tree.items() if v == args.name)
        print(f"{args.name} direct subclasses ({len(direct)}):")
        for name in direct:
            grand = sorted(k for k, v in tree.items() if v == name)
            print(f"  {name}" + (f"  (+{len(grand)} below)" if grand else ""))
        return 0
    chain, cursor = [args.name], args.name
    while cursor in tree and tree[cursor] != cursor:
        cursor = tree[cursor]
        chain.append(cursor)
        if len(chain) > 40:  # a cycle would otherwise spin forever
            break
    print(" -> ".join(chain))
    return 0


def cmd_optionals(args) -> int:
    methods, declarations = optional_methods()
    # The cast family, which no header declares. Merged here rather than in
    # `optional_methods()` so the DECLARATION count stays a count of real
    # header declarations.
    from_headers = set(methods)
    generated = generated_accessors()
    for name, wrapped in generated.items():
        methods.setdefault(name, set()).update(wrapped)
    rows = []
    for method, wrapped in sorted(methods.items()):
        fams = {family(w) for w in wrapped}
        # A method overloaded across families is reported at its WORST, since
        # that is the consequence a caller must guard against.
        worst = ('crash' if 'crash' in fams
                 else 'default' if 'default' in fams else 'raise')
        if args.family and worst != args.family:
            continue
        if args.on and args.on not in wrapped:
            continue
        rows.append((method, worst, sorted(wrapped)))
    shown = {m for m, _, _ in rows}
    if args.json:
        # Names only, sorted, so a committed baseline has a stable diff. The
        # unwrap ratchet in `tests/test_sdk_unwrap_ratchet.py` reads this on a
        # runner with no SDK tree, which is why it must be committed rather
        # than derived at test time.
        print(json.dumps({'family': args.family or 'all',
                          'header_declarations': declarations,
                          'names_from_headers': len(shown & from_headers),
                          'names_only_in_proxies': len(shown - from_headers),
                          'methods': sorted(shown)},
                         indent=1, sort_keys=True))
        return 0

    tally = collections.Counter(worst for _, worst, _ in rows)
    # DECLARED and GENERATED reported separately. Merging them printed
    # "9293 method NAMES ... (3122 declarations)", which conflates a count of
    # header declarations with a count of names from two different sources —
    # the exact confusion CLAUDE.md warns about, reintroduced by me one
    # section below where I wrote the warning.
    # Counted over the FILTERED rows, not the whole set. Reporting the
    # unfiltered totals beside a `--family` figure was itself a conflation —
    # the third one I have introduced in this file while fixing one.
    print(f"{len(rows)} method NAMES returning boost::optional<T>: "
          f"{len(shown & from_headers)} declared in headers "
          f"({declarations} declarations in all), "
          f"{len(shown - from_headers)} only in the proxy annotations"
          + (f" (family={args.family})" if args.family else "")
          + (f" (wrapping {args.on})" if args.on else ""))
    for fam in ('crash', 'default', 'raise'):
        if tally[fam]:
            print(f"  {fam:8} {tally[fam]}")
    if args.list:
        for method, worst, wrapped in rows:
            shown = ','.join(wrapped[:3]) + ('…' if len(wrapped) > 3 else '')
            print(f"  {worst:8} {method}() -> optional<{shown}>")
    else:
        print("  (--list to print them)")
    print("\ncrash = an unguarded .get() on an empty one SEGFAULTS the "
          "process.\nUse btap._compat.opt() for every one of them.")
    return 0


def cmd_method(args) -> int:
    hits = []
    for path in _headers():
        for ret, name, params in _DECL.findall(_read(path)):
            if name != args.name:
                continue
            ret = ' '.join(ret.split())
            if ret in ('return', 'else', 'public:', 'private:'):
                continue
            hits.append((path.name, ret, params.strip()))
    if not hits:
        _die(f"no declaration of {args.name!r} in the public model headers. "
             f"It may live outside openstudio/model, or be SWIG-synthesized "
             f"(those appear only in the proxy .py files).")
    print(f"{args.name}: {len(hits)} declaration(s)")
    for header, ret, params in hits:
        print(f"  {header:46} {ret} {args.name}({params[:52]})")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.split('\n\n')[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Reads the SDK's own artifacts; needs no import, network or "
               "MCP server. Override the install with --sdk.")
    parser.add_argument('--sdk', type=pathlib.Path, default=None,
                        help='SDK install root (default %(default)s)')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('tree', help='class ancestry, or direct subclasses')
    p.add_argument('name')
    p.add_argument('--subclasses', action='store_true',
                   help='list direct subclasses instead of the ancestry')
    p.set_defaults(func=cmd_tree)

    p = sub.add_parser('optionals',
                       help='methods returning boost::optional<T>, by family')
    p.add_argument('--family', choices=('crash', 'default', 'raise'))
    p.add_argument('--on', metavar='T', help='only optionals wrapping T')
    p.add_argument('--list', action='store_true')
    p.add_argument('--json', action='store_true',
                   help='machine-readable names only, for a committed baseline')
    p.set_defaults(func=cmd_optionals)

    p = sub.add_parser('method', help='where a method is declared, and its signature')
    p.add_argument('name')
    p.set_defaults(func=cmd_method)

    args = parser.parse_args(argv)
    if args.sdk is not None:
        global SDK
        SDK = args.sdk
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
