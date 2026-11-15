"""The HVAC cost database (port of btap-costing's hvac/database.rb).

Vendored placeholder CSVs (RS-Means-derived schema; see data/hvac/README.md)
with runtime injection of licensed values via ``costs_csv=``. Ports the
openstudio-standards BTAPCosting data/localization semantics.

Priced tables resolve: explicit ``costs_csv=`` rows override the base;
the base itself comes from BTAP_COSTING_DIR (OPENSTUDIO_COSTING_DIR is the
honoured legacy name), then the package's own shared placeholder copies.
The dead cross-gem resolution must NOT reappear (M4 brief).

Port notes (D-79):
- Ruby ``CSV.read(headers: true)`` yields nil for EMPTY fields; csv.DictReader
  yields ''. The cost tables are FULL of empty columns and lookup code
  branches on nil-ness — so '' is normalized to None at load.
- ``to_f``/``to_s``/``to_i`` mirror Ruby's nil-tolerant conversions
  (``nil.to_f == 0.0``); the sibling costing modules import them from here.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / 'data' / 'hvac'
SHARED_DIR = Path(__file__).resolve().parent.parent / 'data'

_NUMERIC_PREFIX = re.compile(r'\s*[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?')
_INT_PREFIX = re.compile(r'\s*[-+]?\d+')


def to_f(value) -> float:
    """Ruby ``to_f``: nil -> 0.0, numerics pass, strings parse their leading
    float (unparseable -> 0.0)."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    m = _NUMERIC_PREFIX.match(str(value))
    return float(m.group(0)) if m else 0.0


def to_i(value) -> int:
    """Ruby ``to_i``: nil -> 0, floats truncate, strings parse their leading
    integer (unparseable -> 0)."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    m = _INT_PREFIX.match(str(value))
    return int(m.group(0)) if m else 0


def to_s(value) -> str:
    """Ruby ``to_s`` for the CSV cells this domain handles: nil -> ''."""
    return '' if value is None else str(value)


def load_csv(path) -> list[dict]:
    """CSV rows as dicts with '' normalized to None (Ruby CSV nil parity)."""
    with open(path, newline='', encoding='utf-8') as f:
        return [{k: (None if v == '' else v) for k, v in row.items()}
                for row in csv.DictReader(f)]


class Database:
    """The cost database: vendored placeholder CSVs with runtime injection of
    licensed values via ``costs_csv=``."""

    # Domain sheets live under data/hvac/; the tables shared by every
    # costing domain (the placeholder priced pair + locations) one level up.
    DATA_DIR = DATA_DIR
    SHARED_DIR = SHARED_DIR

    def __init__(self, costs_csv=None):
        """:param costs_csv: path to a custom costs CSV (same columns as the
        vendored costs.csv) whose rows override/extend the placeholder values
        """
        self.warnings: list[str] = []
        self._costs = _index_by_id(load_csv(self._resolve_priced('costs.csv', costs_csv)))
        if costs_csv and self._base_priced_path('costs.csv') is not None:
            # explicit costs_csv was loaded as base above only when no fallback
            # exists; when both exist the explicit file OVERRIDES row-by-row
            # (the hvac-gem contract)
            for id_, row in _index_by_id(load_csv(costs_csv)).items():
                self._costs[id_] = row
        self.materials_hvac = load_csv(DATA_DIR / 'materials_hvac.csv')
        self.ahu_assemblies = load_csv(DATA_DIR / 'hvac_vent_ahu.csv')
        self._local_factors = load_csv(self._resolve_priced('costs_local_factors.csv', None))
        self.locations = load_csv(SHARED_DIR / 'locations.csv')
        with open(DATA_DIR / 'mech_sizing.json', encoding='utf-8') as f:
            self.mech_sizing = json.load(f)

    def cost_record(self, id_) -> dict:
        """Unit-cost record for a line-item id (nil material AND labour raises,
        matching legacy).

        :return: {'materialOpCost':, 'laborOpCost':, 'equipmentOpCost': float}
        """
        row = self._costs.get(str(id_).upper())
        if row is None:
            raise ValueError(f"no costing information available for material id {id_}")

        mat = row.get('materialOpCost')
        lab = row.get('laborOpCost')
        if _blank(mat) and _blank(lab):
            raise ValueError(
                f"costing information for material id {id_} is nil — check costing data")

        return {'materialOpCost': to_f(mat), 'laborOpCost': to_f(lab),
                'equipmentOpCost': to_f(row.get('equipmentOpCost'))}

    def regional_factors(self, province_state, city, item_id):
        """Regional cost factors for a line item in a city (legacy
        get_regional_cost_factors): matched on province/city + the item id's
        2-char code prefix; 100/100/100 fallback with a recorded warning.

        :return: (material %, installation %, total %) floats
        """
        prefix = str(item_id)[0:2]
        for row in self._local_factors:
            if not (row.get('province_state') == province_state and row.get('city') == city):
                continue
            if row.get('code_prefix') == prefix:
                return (to_f(row.get('material')), to_f(row.get('installation')),
                        to_f(row.get('total')))
        warning = (f"no regional adjustment factor for item {item_id} (prefix {prefix}) "
                   f"in {city}, {province_state}; using 100/100/100")
        if warning not in self.warnings:
            self.warnings.append(warning)
        return (100.0, 100.0, 100.0)

    def closest_location(self, lat, long):
        """Nearest cost location to a lat/long (haversine; legacy
        get_closest_cost_location).

        :return: dict {'province_state':, 'city':, ...}
        """
        return min(self.locations,
                   key=lambda loc: _haversine_m((lat, long),
                                                (to_f(loc.get('latitude')),
                                                 to_f(loc.get('longitude')))))

    def materials(self, material, size=None, fuel=None):
        """HVAC material rows matching a Material name (and optional Size/Fuel
        selectors)."""
        rows = [r for r in self.materials_hvac if r.get('Material') == material]
        if size is not None:
            rows = [r for r in rows if to_s(r.get('Size')) == str(size)]
        if fuel is not None:
            rows = [r for r in rows if to_s(r.get('Fuel')) == str(fuel)]
        return rows

    # ---- priced-table resolution (M4 brief) ----

    @staticmethod
    def _priced_fallback_dirs():
        # BTAP_COSTING_DIR (OPENSTUDIO_COSTING_DIR is the honoured legacy
        # name), then this package's own shared placeholder copies. Read at
        # call time, not import time (divergence from Ruby envelope, which
        # freezes ENV at require).
        env = os.environ.get('BTAP_COSTING_DIR') or os.environ.get('OPENSTUDIO_COSTING_DIR')
        return [d for d in (env, str(SHARED_DIR)) if d]

    def _base_priced_path(self, filename):
        for d in self._priced_fallback_dirs():
            candidate = Path(d) / filename
            if candidate.exists():
                return candidate
        return None

    def _resolve_priced(self, filename, explicit):
        base = self._base_priced_path(filename)
        if base is not None:
            return base  # explicit costs_csv then overrides row-by-row in __init__
        if explicit and Path(explicit).exists():
            return explicit

        raise ValueError(
            f"{filename} not found. — pass costs_csv=, or set BTAP_COSTING_DIR "
            "(OPENSTUDIO_COSTING_DIR is still honoured).")


def _blank(value) -> bool:
    return value is None or str(value).strip() == ''


def _index_by_id(rows) -> dict:
    return {to_s(row.get('id')).upper(): row for row in rows}


def _haversine_m(loc1, loc2) -> float:
    rad = math.pi / 180
    dlat = (loc2[0] - loc1[0]) * rad
    dlon = (loc2[1] - loc1[1]) * rad
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(loc1[0] * rad) * math.cos(loc2[0] * rad) * math.sin(dlon / 2) ** 2)
    return 6_371_000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
