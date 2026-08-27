"""Access to the vendored NECB space-type records (data/space_types_<v>.json).

Records are keyed the legacy way: (building_type, space_type) — the pair the
OpenStudio SpaceType carries as standardsBuildingType/standardsSpaceType.

Port note: Ruby's ``SpaceTypes.list`` is ``list_pairs`` here — ``list`` would
shadow the builtin (the same rename btap.modeling.hvac.catalog made).
``undefined?`` is ``is_undefined``.
"""

from __future__ import annotations

from btap.necb import loads as _loads


def record(building_type, space_type, vintage='2020'):
    """:return: the full 80-key record (raises on unknown pair)"""
    row = find(building_type=building_type, space_type=space_type, vintage=vintage)
    if row is None:
        raise ValueError(
            f"no NECB {vintage} space type ['{building_type}', '{space_type}'] — "
            f"see btap.necb.loads.SpaceTypes.list_pairs(vintage='{vintage}')")
    return row


def find(building_type, space_type, vintage='2020'):
    """:return: the record, or None"""
    for r in _loads.table(vintage, 'space_types'):
        if r['building_type'] == building_type and r['space_type'] == space_type:
            return r
    return None


def list_pairs(vintage='2020'):
    """:return: all (building_type, space_type) pairs"""
    return [[r['building_type'], r['space_type']]
            for r in _loads.table(vintage, 'space_types')]


def is_undefined(record):
    return record['necb_hvac_system_selection_type'] == '- undefined -'
