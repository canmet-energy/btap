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
})

#: Measured as crashing, so they are NOT merely the unmeasured default.
#: Recorded because `family()` would reach the same answer by falling through,
#: and a reader cannot otherwise tell a measurement from a fallback.
MEASURED_CRASH = frozenset({'UUID', 'EpwFile', 'ViewFactor', 'WorkspaceObject'})

_CLASS = re.compile(r'^class\s+(\w+)\(([\w.]+)\)', re.M)

#: Matched against COMMENT-STRIPPED, WHITESPACE-FLATTENED text.
#:
#: The first version missed 41 declarations (review of #170), every one a
#: genuine public declaration: 22 prefixed `OS_DEPRECATED(...)`, 12 `static`
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
    # `*_Impl.hpp` are the implementation classes: same methods, not the
    # public surface, and counting both double-reports everything.
    found = [p for p in sorted((SDK / 'include/openstudio/model').glob('*.hpp'))
             if not p.name.endswith('_Impl.hpp')]
    if not found:
        _die(f"no public model headers under "
             f"{SDK / 'include/openstudio/model'} — is this an SDK install "
             f"without headers?")
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
    tally = collections.Counter(worst for _, worst, _ in rows)
    print(f"{len(rows)} method NAMES returning boost::optional<T> "
          f"({declarations} declarations in all)"
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
