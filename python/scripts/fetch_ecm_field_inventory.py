#!/usr/bin/env python3
"""Derive the ECM field inventory from the two external ECM implementations.

phylroy's scope for the recipe (#196): it must carry **all the values for all
the ECMs in the campus project and the items in the osruby project**. That is
a union of two field sets, and hand-transcribing ~200 names would rot on the
first upstream change — so this derives them.

    canmet-energy/osruby   lib/btap/measures.rb — 20 `ecm_*` methods, each
                           declaring a `measure_values` array of column names.
                           The measure that produced `models/` is
                           `measures/dnd_analysis`, whose class is literally
                           `ColdLakeVintageMaker`.
    canmet-energy/campus   src/resources/buildings/measures/*/measure.py —
                           OpenStudio measures whose `arguments()` declare
                           their parameters.

BOTH ARE PRIVATE repositories read through `gh`, so this is an AUTHENTICATED
MAINTAINER REFRESH like `fetch_necb_provisions.py`: ordinary runtime and CI
stay offline and read the committed output.

Campus measures build arguments two ways and both are parsed, because the
second is invisible to a literal-string scan: a direct
`makeDoubleArgument("name", …)`, and a loop over a `(name, label, default)`
tuple list. `add_doas_erv` and `improve_fan_and_pump_total_efficiency` use
only the second, so a first pass reported them as having ZERO arguments.

Out of scope and recorded as such rather than dropped silently: osruby's
`ecm_capital_costs` and `ecm_id`, and campus's costing arguments — those are
`btap.costing`'s and bookkeeping, not building performance.
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import re
import subprocess
import sys

OSRUBY = 'canmet-energy/osruby'
CAMPUS = 'canmet-energy/campus'
MEASURES_RB = 'lib/btap/measures.rb'
CAMPUS_DIR = 'src/resources/buildings/measures'

OUT = (pathlib.Path(__file__).resolve().parents[1]
       / 'btap' / 'modeling' / 'data' / 'ecm_field_inventory.json')

# osruby categories that are not building performance.
OSRUBY_OUT_OF_SCOPE = ('ecm_capital_costs', 'ecm_id')

# Campus argument names that are COSTING or bookkeeping, by substring.
# phylroy's scope call: cost and financial items are out.
#
# `template` is deliberately NOT here. It looked like bookkeeping and is not:
# in an OpenStudio measure it names the STANDARD or vintage ('90.1-2013',
# 'NECB2011'), which for a recipe is close to the vintage itself.
CAMPUS_OUT_OF_SCOPE_SUBSTRINGS = ('cost', 'years_until')
CAMPUS_OUT_OF_SCOPE_PREFIXES = ('om_', 'demo_')


def _is_costing(name):
    """Whether a campus argument is a cost or financial field.

    The O&M and demolition tests are PREFIXES, not substrings, because a
    substring `'om_'` matches `target_hoo_from_model` — fr-OM-_model — and
    silently dropped a real parameter of `shift_hours_of_operation` on the
    first run. A filter that quietly removes a field it was not meant to is
    worse than no filter, because the loss is invisible in the output.
    """
    return (any(token in name for token in CAMPUS_OUT_OF_SCOPE_SUBSTRINGS)
            or name.startswith(CAMPUS_OUT_OF_SCOPE_PREFIXES))


def _gh_json(path):
    out = subprocess.run(['gh', 'api', path], capture_output=True, text=True,
                         check=True).stdout
    return json.loads(out)


def _gh_file(repo, path):
    payload = _gh_json(f'repos/{repo}/contents/{path}')
    return base64.b64decode(payload['content']).decode('utf-8',
                                                       errors='replace')


def osruby_fields():
    """Each `ecm_*` method's `measure_values` column names, in source order."""
    src = _gh_file(OSRUBY, MEASURES_RB)
    parts = re.split(r'^\s*def (ecm_\w+)\(', src, flags=re.M)
    out = {}
    for index in range(1, len(parts), 2):
        name, body = parts[index], parts[index + 1]
        match = re.search(r'measure_values\s*=\s*\[(.*?)\]', body, re.S)
        columns = re.findall(r'"([^"]+)"', match.group(1)) if match else []
        out[name] = columns
    return out


def campus_fields():
    """Each measure's argument names, from both construction idioms."""
    entries = _gh_json(f'repos/{CAMPUS}/contents/{CAMPUS_DIR}')
    out = {}
    for entry in entries:
        if entry['type'] != 'dir' or entry['name'] == 'shared_resources':
            continue
        try:
            src = _gh_file(CAMPUS, f"{CAMPUS_DIR}/{entry['name']}/measure.py")
        except subprocess.CalledProcessError:
            out[entry['name']] = None      # no measure.py — recorded, not guessed
            continue
        direct = re.findall(
            r'make(?:Double|String|Choice|Bool|Integer)Argument\(\s*'
            r'["\']([^"\']+)["\']', src)
        # The loop idiom: a tuple list of (name, label[, default]).
        looped = []
        for block in re.findall(r'for\s+name,\s*label[^\n]*:\n(.*?)\n\s*\)',
                                src, re.S):
            looped += re.findall(r'\(\s*["\']([a-z_][a-z0-9_]*)["\']\s*,',
                                 block)
        out[entry['name']] = list(dict.fromkeys(direct + looped))
    return out


def build():
    osruby = osruby_fields()
    campus = campus_fields()

    in_scope_osruby = {k: v for k, v in osruby.items()
                       if k not in OSRUBY_OUT_OF_SCOPE}
    campus_scoped, campus_dropped = {}, {}
    for measure, args in campus.items():
        if args is None:
            campus_scoped[measure] = None
            continue
        keep = [a for a in args if not _is_costing(a)]
        campus_scoped[measure] = keep
        dropped = [a for a in args if a not in keep]
        if dropped:
            campus_dropped[measure] = dropped

    return {
        '_generated_by': 'python/scripts/fetch_ecm_field_inventory.py',
        '_note': ('DO NOT EDIT. Derived from two PRIVATE repositories through '
                  'an authenticated gh session; ordinary runtime and CI read '
                  'this file and stay offline.'),
        'osruby': {
            'repo': OSRUBY, 'source': MEASURES_RB,
            'categories': osruby,
            'out_of_scope': list(OSRUBY_OUT_OF_SCOPE),
            'counts': {
                'categories_total': len(osruby),
                'categories_in_scope': len(in_scope_osruby),
                'columns_total': sum(len(v) for v in osruby.values()),
                'columns_in_scope': sum(len(v) for v in
                                        in_scope_osruby.values()),
            },
        },
        'campus': {
            'repo': CAMPUS, 'source': CAMPUS_DIR,
            'measures': campus_scoped,
            'dropped_as_costing_or_bookkeeping': campus_dropped,
            'counts': {
                'measures': len(campus_scoped),
                'arguments_in_scope': sum(len(v or [])
                                          for v in campus_scoped.values()),
            },
        },
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true',
                        help='re-derive and diff without writing')
    args = parser.parse_args(argv)

    inventory = build()
    rendered = json.dumps(inventory, indent=2, sort_keys=True) + '\n'

    if args.check:
        if not OUT.exists():
            print(f'{OUT} does not exist', file=sys.stderr)
            return 1
        if OUT.read_text(encoding='utf-8') != rendered:
            print(f'{OUT} is STALE — re-run without --check', file=sys.stderr)
            return 1
        print(f'{OUT.name} matches the upstream sources')
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(rendered, encoding='utf-8')
    osr, cam = inventory['osruby']['counts'], inventory['campus']['counts']
    print(f'wrote {OUT}')
    print(f"  osruby: {osr['categories_in_scope']} categories in scope of "
          f"{osr['categories_total']}, {osr['columns_in_scope']} columns of "
          f"{osr['columns_total']}")
    print(f"  campus: {cam['measures']} measures, "
          f"{cam['arguments_in_scope']} arguments in scope")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
