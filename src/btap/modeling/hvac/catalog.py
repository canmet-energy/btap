"""The HVAC system registry, loaded from data/systems.json.

Each row has a stable, model-safe `id` (what builders write into models and
what code keys on), a `legacy_name` (the name it had before the HVAC taxonomy,
kept as provenance and accepted as input) and `aliases` (the retired generated
canonical name, accepted as input). See docs/plans/HVAC_TAXONOMY_PLAN.md.

People see `display`, the plain-English name `taxonomy.display()` generates;
it is searchable but never the resolution key of record.

Ruby ``Catalog.list`` is ``list_systems`` here — ``list`` would shadow the
Python builtin (the facade's public spelling is ``systems()`` either way).
"""

from __future__ import annotations

import heapq
import json
import re
from pathlib import Path

SYSTEMS_PATH = Path(__file__).parent / 'data' / 'systems.json'
SIZING_PATH = Path(__file__).parent / 'data' / 'sizing.json'

_rows = None
_sizing_blocks = None
_index = None
_alias_config = None


def rows():
    global _rows
    if _rows is None:
        _rows = json.loads(SYSTEMS_PATH.read_text(encoding='utf-8'))['systems']
    return _rows


def alias_config():
    """``{casefolded retired name: config}`` — overrides a RETIRED name carries,
    so it builds what it built before (D-113)."""
    global _alias_config
    if _alias_config is None:
        data = json.loads(SYSTEMS_PATH.read_text(encoding='utf-8'))
        _alias_config = {_key(k): v for k, v in (data.get('alias_config') or {}).items()}
    return _alias_config


def sizing_blocks():
    global _sizing_blocks
    if _sizing_blocks is None:
        _sizing_blocks = json.loads(SIZING_PATH.read_text(encoding='utf-8'))['sizing']
    return _sizing_blocks


def _key(text):
    return ' '.join(str(text).split()).casefold()


def index():
    """Lower-cased key -> row, over every id, legacy name and alias.

    Built in a fixed order (Astra, taxonomy review finding 5): the keys first,
    then the composite references are checked, so nothing that DERIVES from
    a row (facets, display names) is needed to resolve one. Raises if any key
    maps to two different rows, if a composite part names no row, or if
    composites reference each other in a cycle.
    """
    global _index
    if _index is not None:
        return _index
    mapping = {}
    for row in rows():
        for key in (row['id'], row['legacy_name'], *(row.get('aliases') or [])):
            folded = _key(key)
            other = mapping.get(folded)
            if other is not None and other is not row:
                raise RuntimeError(
                    f"catalogue key {key!r} names two systems: "
                    f"{other['id']!r} and {row['id']!r}")
            mapping[folded] = row
    by_id = {row['id']: row for row in rows()}

    def check(row, trail):
        for part in row.get('parts') or ():
            if part.get('id') not in by_id:
                raise RuntimeError(
                    f"composite {row['id']!r} references unknown part {part.get('id')!r}")
            if part['id'] in trail:
                raise RuntimeError(f"composite cycle: {' -> '.join(trail + [part['id']])}")
            check(by_id[part['id']], trail + [part['id']])

    for row in rows():
        check(row, [row['id']])
    _index = mapping
    return _index


def row_for(name):
    """The catalogue row a key names, or None. Exact id first, then any key."""
    for row in rows():
        if row['id'] == name:
            return row
    return index().get(_key(name))


def is_legacy_key(name):
    """True when `name` resolves, but not by its id — the caller used an old
    name or alias, which a build may record."""
    row = row_for(name)
    return row is not None and row['id'].casefold() != str(name).casefold()


def list_systems(filter=None, family=None, **facet_filters):
    """List catalogue entries, each with its `display` name and `facets`.

    :param filter: text (case-insensitive, every word must match) or a
        compiled regex, over id, display, legacy name and aliases
    :param family: builder family filter (e.g. 'psz')
    :param facet_filters: any taxonomy facet, e.g. ``ahu_heating='gas'`` or
        ``system_type=['psz', 'pvav']``; a list means any of them. An unknown
        facet or value raises with the valid choices.
    :return: list of row dicts, each with 'display' and 'facets'
    """
    from btap.modeling.hvac import taxonomy

    for facet, wanted in facet_filters.items():
        if facet not in taxonomy.FACETS:
            raise ValueError(f"unknown facet {facet!r}; choose from {sorted(taxonomy.FACETS)}")
        for value in (wanted if isinstance(wanted, (list, tuple, set)) else [wanted]):
            if str(value) not in taxonomy.FACETS[facet]:
                raise ValueError(f"unknown {facet} value {value!r}; choose from "
                                 f"{list(taxonomy.FACETS[facet])}")
    result = []
    for row in rows():
        facets = taxonomy.facets(row)
        if family and row['family'] != family:
            continue
        keep = True
        for facet, wanted in facet_filters.items():
            values = facets[facet] if facet in taxonomy.MULTI else [facets[facet]]
            wanted = {str(w) for w in (wanted if isinstance(wanted, (list, tuple, set))
                                       else [wanted])}
            if not wanted & set(values):
                keep = False
                break
        if keep:
            result.append({**row, 'display': taxonomy.display(row), 'facets': facets})
    if isinstance(filter, str):
        words = filter.casefold().split()
        result = [r for r in result if all(
            w in ' '.join([r['id'], r['display'], r['legacy_name'],
                           *(r.get('aliases') or [])]).casefold() for w in words)]
    elif isinstance(filter, re.Pattern):
        result = [r for r in result if any(
            filter.search(text) for text in
            (r['id'], r['display'], r['legacy_name'], *(r.get('aliases') or [])))]
    return result


def resolve(name):
    """Resolve a system key to its full build config (the row merged with its
    sizing block), carrying `id`, `legacy_name` and `display`.

    Accepts the id, the legacy name or an alias, case-insensitively. Raises
    with the closest ids on an unknown key.
    """
    row = row_for(name)
    if row is None:
        words = _key(name).split()
        suggestions = heapq.nlargest(
            3, rows(),
            key=lambda r: sum(1 for w in words if w in _key(
                ' '.join([r['id'], r['legacy_name'], *(r.get('aliases') or [])]))))
        raise ValueError(
            f"unknown system name '{name}'. Closest catalogue entries:\n  - "
            + '\n  - '.join(f"{r['id']}  ({r['legacy_name']})" for r in suggestions))

    carried = alias_config().get(_key(name), {})
    config = {**row, **carried}
    if isinstance(row.get('sizing'), str):
        block = sizing_blocks().get(row['sizing'])
        if block is None:
            raise ValueError(
                f"systems.json row '{row['id']}' references unknown sizing block "
                f"'{row['sizing']}'")
        config['sizing'] = block
    from btap.modeling.hvac import taxonomy
    config['display'] = taxonomy.display({**row, **carried})
    return config
