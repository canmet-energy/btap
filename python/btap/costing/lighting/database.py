"""Lighting cost database (port of btap-costing lighting/database.rb).

Vendored UNPRICED sheets (lighting_sets / lighting / materials_lighting —
none carry dollar values); the PRICED tables (costs.csv,
costs_local_factors.csv) resolve at runtime exactly like the
package's shared data/: explicit args, BTAP_COSTING_DIR, or the
package's shared data/ copies. Licensed values are
runtime-injected only and never committed.
"""

from __future__ import annotations

import csv
import math
import os
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "lighting"

# The priced tables live in this package's shared data/, the single public
# vendored copy. (The Ruby gem resolved the INSTALLED gem first for the
# split-install layout; the Python package carries its data inside itself,
# so the package copy IS that resolution.)

# Priced tables resolve: BTAP_COSTING_DIR (OPENSTUDIO_COSTING_DIR is the
# honoured legacy name), then this package's own shared placeholder copies.
# The cross-gem resolution died with the consolidation.
PRICED_FALLBACK_DIRS = tuple(
    d for d in (
        os.environ.get("BTAP_COSTING_DIR") or os.environ.get("OPENSTUDIO_COSTING_DIR"),
        str(Path(__file__).resolve().parent.parent / "data"),
    ) if d is not None
)


def to_s(value) -> str:
    """Ruby ``to_s``: nil -> ''."""
    return "" if value is None else str(value)


def to_f(value) -> float:
    """Ruby ``String#to_f`` / ``nil.to_f``: leading numeric prefix, else 0.0."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    m = re.match(r"\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?", str(value))
    return float(m.group()) if m else 0.0


def to_i(value) -> int:
    """Ruby ``String#to_i`` / ``nil.to_i``: leading integer prefix, else 0."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return math.trunc(value)
    m = re.match(r"\s*[-+]?\d+", str(value))
    return int(m.group()) if m else 0


def load_csv(path) -> list[dict]:
    """``CSV.read(path, headers: true).map(&:to_h)`` — Ruby yields nil for
    EMPTY fields where DictReader yields ''; normalize '' -> None at load
    (the lookup code branches on nil-ness)."""
    with open(path, newline="", encoding="utf-8") as f:
        return [
            {k: (None if v == "" else v) for k, v in row.items()}
            for row in csv.DictReader(f)
        ]


class Database:
    def __init__(self, costs_csv=None, local_factors_csv=None):
        self.warnings: list[str] = []
        self.lighting_sets = load_csv(DATA_DIR / "lighting_sets.csv")
        self.lighting = load_csv(DATA_DIR / "lighting.csv")
        self.materials_lighting = load_csv(DATA_DIR / "materials_lighting.csv")
        self._costs = _index_by_id(load_csv(self._resolve_priced("costs.csv", costs_csv)))
        if costs_csv is not None and os.path.exists(costs_csv):
            for id_, row in _index_by_id(load_csv(costs_csv)).items():
                self._costs[id_] = row
        self._local_factors = load_csv(
            self._resolve_priced("costs_local_factors.csv", local_factors_csv))
        self._locations = self._locations_table()

    def _locations_table(self):
        """locations.csv ships alongside the priced tables in data/.
        Scan every candidate directory rather than assuming the last one, and
        WARN when it cannot be found: the previous ``rescue []`` silently
        disabled regional cost factors, and in this family warnings are never
        silent."""
        for d in PRICED_FALLBACK_DIRS:
            path = os.path.join(d, "locations.csv")
            if os.path.exists(path):
                return load_csv(path)
        self.warnings.append(
            "locations.csv not found in any costing directory — regional cost factors unavailable")
        return []

    def cost_record(self, id_):
        row = self._costs.get(to_s(id_).upper())
        if row is None:
            raise ValueError(f"no costing information for material id {id_}")
        return {"materialOpCost": to_f(row["materialOpCost"]),
                "laborOpCost": to_f(row["laborOpCost"]),
                "equipmentOpCost": to_f(row["equipmentOpCost"])}

    def regional_factors(self, province_state, city, item_id):
        prefix = to_s(item_id)[0:2]
        for row in self._local_factors:
            if not (row["province_state"] == province_state and row["city"] == city):
                continue
            if row["code_prefix"] == prefix:
                return [to_f(row["material"]), to_f(row["installation"])]
        warning = (f"no regional adjustment factor for item {item_id} (prefix {prefix}) "
                   f"in {city}, {province_state}; using 100/100")
        if warning not in self.warnings:
            self.warnings.append(warning)
        return [100.0, 100.0]

    def closest_location(self, lat, long):
        if not self._locations:
            return None
        rad = math.pi / 180

        def key(loc):
            dlat = (to_f(loc["latitude"]) - lat) * rad
            dlon = (to_f(loc["longitude"]) - long) * rad
            return (math.sin(dlat / 2) ** 2 +
                    math.cos(lat * rad) * math.cos(to_f(loc["latitude"]) * rad) *
                    math.sin(dlon / 2) ** 2)

        return min(self._locations, key=key)

    def _resolve_priced(self, filename, explicit):
        for d in PRICED_FALLBACK_DIRS:
            path = os.path.join(d, filename)
            if os.path.exists(path):
                return path
        if explicit is not None and os.path.exists(explicit):
            return explicit
        raise ValueError(f"{filename} not found — pass costs_csv=/local_factors_csv=, set "
                         "BTAP_COSTING_DIR")


def _index_by_id(rows):
    return {to_s(row["id"]).upper(): row for row in rows}
