"""The descriptive-name system registry, loaded from data/systems.json.
The name is the API: it encodes topology family AND fuel/coil/baseboard choices.

Ruby ``Catalog.list`` is ``list_systems`` here — ``list`` would shadow the
Python builtin (the facade's public spelling is ``systems()`` either way).
"""

from __future__ import annotations

import heapq
import json
import re
from pathlib import Path

from btap.modeling.hvac import canonical

SYSTEMS_PATH = Path(__file__).parent / 'data' / 'systems.json'
SIZING_PATH = Path(__file__).parent / 'data' / 'sizing.json'

_rows = None
_sizing_blocks = None
_canonical_map = None


def rows():
    global _rows
    if _rows is None:
        _rows = json.loads(SYSTEMS_PATH.read_text(encoding='utf-8'))['systems']
    return _rows


def sizing_blocks():
    global _sizing_blocks
    if _sizing_blocks is None:
        _sizing_blocks = json.loads(SIZING_PATH.read_text(encoding='utf-8'))['sizing']
    return _sizing_blocks


def canonical_map():
    """Map of canonical (generated) name -> row. Canonical names are an equal-class
    resolver key alongside the legacy names; a collision with a legacy name would be
    a bug."""
    global _canonical_map
    if _canonical_map is None:
        mapping = {}
        for row in rows():
            canon = canonical.name(row)
            if canon in mapping or any(r['name'] == canon for r in rows()):
                raise RuntimeError(f"canonical name collision: '{canon}'")
            mapping[canon] = row
        _canonical_map = mapping
    return _canonical_map


def list_systems(filter=None, family=None):
    """List catalog entries, optionally filtered by a substring/regex on the name or a
    family. Each row includes its generated 'canonical_name' (the consolidated grammar).

    :param filter: name filter (str or compiled regex; matches legacy OR canonical name)
    :param family: family filter (e.g. 'psz')
    :return: list of matching row dicts (name, canonical_name, family, ...)
    """
    result = [{**r, 'canonical_name': canonical.name(r)} for r in rows()]
    if family:
        result = [r for r in result if r['family'] == family]
    if isinstance(filter, str):
        f = filter.lower()
        result = [r for r in result
                  if f in r['name'].lower() or f in r['canonical_name'].lower()]
    elif isinstance(filter, re.Pattern):
        result = [r for r in result
                  if filter.search(r['name']) or filter.search(r['canonical_name'])]
    return result


def resolve(name):
    """Resolve a descriptive name to its full config (row merged with its sizing block).
    Accepts the legacy catalog name, the generated canonical name, or a row alias.
    Raises with close-match suggestions on an unknown name.

    :param name: legacy name, canonical name, or alias
    :return: config dict with string keys; ['sizing'] is the resolved sizing block dict
    """
    row = next((r for r in rows()
                if r['name'] == name or name in (r.get('aliases') or [])), None)
    if row is None:
        row = canonical_map().get(name)
    if row is None:
        words = name.lower().split()
        suggestions = heapq.nlargest(
            3, (r['name'] for r in rows()),
            key=lambda n: sum(1 for w in words if w in n.lower()))
        raise ValueError(
            f"unknown system name '{name}'. Closest catalog entries:\n  - "
            + '\n  - '.join(suggestions))

    config = dict(row)
    if isinstance(row.get('sizing'), str):
        block = sizing_blocks().get(row['sizing'])
        if block is None:
            raise ValueError(
                f"systems.json row '{name}' references unknown sizing block '{row['sizing']}'")
        config['sizing'] = block
    return config
