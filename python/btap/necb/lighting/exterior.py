"""Exterior lighting power allowances — NECB 4.2.3.1 (Tables -A..-E), a
greenfield implementation (legacy only carries prototype-specific exterior
wattages; it never computes the code allowance).

The allowance = basic site allowance (Table -B) + tradable allowances
(Table -D, x quantities, tradable among themselves) + non-tradable
allowances (Table -C, per-application caps). Zone 0 has no allowances.
"""

from __future__ import annotations

import json

import openstudio

from btap._compat import ruby_round
from btap.audit import AuditLog
from btap.necb import lighting as _lighting

_data_cache = None


def _data():
    global _data_cache
    if _data_cache is None:
        path = _lighting.DATA_DIR / 'exterior_lighting_2020.json'
        _data_cache = json.loads(path.read_text(encoding='utf-8'))
    return _data_cache


def allowance(zone, quantities, vintage='2020', audit=None):
    """Compute the exterior lighting power allowance.

    :param zone: exterior lighting zone 0..4 (Table -A)
    :param quantities: {table key -> quantity} (m2, m, or count per the row's
        unit), e.g. {'parking_and_drives_m2': 500, 'entrances_exits_m': 12}
    :return: {'basic_site_w', 'tradable_w', 'non_tradable_w', 'total_w', 'lines'}
    """
    audit = audit if audit is not None else AuditLog()
    data = _data()
    zone_key = str(zone)
    if zone_key not in data['basic_site_allowance_w']:
        raise ValueError(f"unknown exterior lighting zone '{zone}' (0..4)")

    basic = float(data['basic_site_allowance_w'][zone_key])
    lines = []
    known = {r['key'] for r in (data['tradable'] + data['non_tradable'])}
    unknown = [str(key) for key in quantities if str(key) not in known]
    for key in unknown:
        audit.warn('lighting_exterior',
                   f"unknown exterior application '{key}' — not in Tables 4.2.3.1.-C/-D; skipped")

    tradable_w = _sum_rows(data['tradable'], quantities, zone_key, lines, audit)
    non_tradable_w = _sum_rows(data['non_tradable'], quantities, zone_key, lines, audit)
    total = basic + tradable_w + non_tradable_w

    audit.decision('lighting_exterior', 'exterior lighting power allowance computed',
                   inputs={'zone': zone_key, 'basic_site_w': basic,
                           'tradable_w': ruby_round(tradable_w, 1),
                           'non_tradable_w': ruby_round(non_tradable_w, 1)},
                   value=f"{ruby_round(total, 1)} W (tradable allowances may be traded among "
                         f"tradable applications; non-tradable are per-application caps)",
                   article='4.2.3.1.')
    return {'basic_site_w': basic, 'tradable_w': ruby_round(tradable_w, 1),
            'non_tradable_w': ruby_round(non_tradable_w, 1),
            'total_w': ruby_round(total, 1), 'lines': lines}


def _sum_rows(rows, quantities, zone_key, lines, audit):
    total = 0.0
    for row in rows:
        quantity = quantities.get(row['key'])
        if quantity is None or float(quantity) == 0.0:
            continue

        rate = row['by_zone'].get(zone_key)
        if rate is None:
            audit.warn('lighting_exterior',
                       f"no allowance for '{row['application']}' in lighting zone {zone_key} — 0 W",
                       article='4.2.3.1.')
            continue
        watts = float(rate) * float(quantity)
        lines.append({'application': row['application'], 'unit': row['unit'],
                      'rate': float(rate), 'quantity': float(quantity),
                      'watts': ruby_round(watts, 1)})
        total += watts
    return total


def apply_exterior_lights(model, watts, name='NECB Exterior Lighting', audit=None):
    """Create an ExteriorLights object at the given design wattage with
    astronomical-clock control (lights off in daylight)."""
    definition = openstudio.model.ExteriorLightsDefinition(model)
    definition.setName(f"{name} Definition")
    definition.setDesignLevel(float(watts))
    lights = openstudio.model.ExteriorLights(definition)
    lights.setName(name)
    lights.setControlOption('AstronomicalClock')
    if audit is not None:
        audit.decision('lighting_exterior',
                       'exterior lights created (astronomical clock control)',
                       inputs={'design_w': ruby_round(float(watts), 1)}, article='4.2.3.1.')
    return lights
