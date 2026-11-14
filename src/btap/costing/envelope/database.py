"""The envelope cost database (port of btap-costing's envelope/database.rb).

Vendored UNPRICED sheets (constructions.json, materials_opaque/glazing,
thermal_bridging — see data/envelope/README.md); the placeholder PRICED pair
is the package's shared data/ copy. Real licensed RS-Means values must only
ever be injected via costs_csv= (or a BTAP_COSTING_DIR directory) and never
committed.

Port notes (D-79): Ruby's ``CSV.read(headers: true)`` yields nil for empty
fields; ``csv.DictReader`` yields ``''`` — loading normalizes ``''`` → None
so the nil-branching lookup code keeps its meaning. The Ruby
``Gem::LoadError`` rescue was Ruby-only plumbing and drops here.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "envelope"
SHARED_DIR = Path(__file__).resolve().parent.parent / "data"

# Priced tables resolve: BTAP_COSTING_DIR (OPENSTUDIO_COSTING_DIR is the
# honoured legacy name), then this package's own shared placeholder copies.
# The cross-gem resolution died with the consolidation.
_env_dir = os.environ.get("BTAP_COSTING_DIR")
if _env_dir is None:
    _env_dir = os.environ.get("OPENSTUDIO_COSTING_DIR")
PRICED_FALLBACK_DIRS = tuple(
    d for d in (_env_dir, str(SHARED_DIR)) if d is not None
)


def to_s(value) -> str:
    """Ruby ``to_s`` for cell values: nil → ''."""
    return "" if value is None else str(value)


_FLOAT_RE = re.compile(r"\s*[-+]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?")


def to_f(value) -> float:
    """Ruby ``to_f``: nil → 0.0, leading-number parse, garbage → 0.0."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    match = _FLOAT_RE.match(str(value))
    if match is None or match.group(0).strip() in ("", "+", "-"):
        return 0.0
    try:
        return float(match.group(0))
    except ValueError:
        return 0.0


class Database:
    """Envelope cost database with the family's priced-table resolution."""

    # Class-level views of the module constants (Ruby's Database::DATA_DIR).
    DATA_DIR = DATA_DIR
    SHARED_DIR = SHARED_DIR
    PRICED_FALLBACK_DIRS = PRICED_FALLBACK_DIRS

    def __init__(self, costs_csv: str | None = None,
                 local_factors_csv: str | None = None):
        """costs_csv: priced unit-cost table (same columns as the vendored
        costs.csv); overrides/extends the resolved base.
        local_factors_csv: city cost-index factors table."""
        self.warnings: list[str] = []
        with open(DATA_DIR / "constructions.json", encoding="utf-8") as f:
            self.constructions = json.load(f)
        self.materials_opaque = self._load_csv(DATA_DIR / "materials_opaque.csv")
        self.materials_glazing = self._load_csv(DATA_DIR / "materials_glazing.csv")
        self.thermal_bridging = self._load_csv(DATA_DIR / "thermal_bridging.csv")
        self.locations = self._load_csv(SHARED_DIR / "locations.csv")

        self._costs = self._index_by_id(
            self._load_csv(self._resolve_priced("costs.csv", costs_csv)))
        base = self._base_priced_path("costs.csv")
        if costs_csv is not None and base is not None and os.path.exists(str(base)):
            # explicit costs_csv was loaded as base above only when no fallback
            # exists; when both exist the explicit file OVERRIDES row-by-row
            # (hvac-gem contract)
            for row_id, row in self._index_by_id(self._load_csv(costs_csv)).items():
                self._costs[row_id] = row
        self._local_factors = self._load_csv(
            self._resolve_priced("costs_local_factors.csv", local_factors_csv))

    def cost_record(self, item_id) -> dict:
        """Unit-cost record for a line-item id (nil material AND labour
        raises, matching legacy)."""
        row = self._costs.get(to_s(item_id).upper())
        if row is None:
            raise ValueError(
                f"no costing information available for material id {item_id}")

        mat = row.get("materialOpCost")
        lab = row.get("laborOpCost")
        if self._blank(mat) and self._blank(lab):
            raise ValueError(
                f"costing information for material id {item_id} is nil — "
                "check costing data")

        return {"materialOpCost": to_f(mat), "laborOpCost": to_f(lab),
                "equipmentOpCost": to_f(row.get("equipmentOpCost"))}

    def regional_factors(self, province_state, city, item_id):
        """Regional cost factors (legacy get_regional_cost_factors): matched
        on province/city + the item id's 2-char code prefix; 100/100/100
        fallback with a recorded warning.

        Returns (material %, installation %, total %)."""
        prefix = to_s(item_id)[:2]
        for row in self._local_factors:
            if not (row.get("province_state") == province_state
                    and row.get("city") == city):
                continue
            if row.get("code_prefix") == prefix:
                return (to_f(row.get("material")), to_f(row.get("installation")),
                        to_f(row.get("total")))
        warning = (f"no regional adjustment factor for item {item_id} "
                   f"(prefix {prefix}) in {city}, {province_state}; "
                   "using 100/100/100")
        if warning not in self.warnings:
            self.warnings.append(warning)
        return (100.0, 100.0, 100.0)

    def closest_location(self, lat, long):
        """Nearest cost location to a lat/long (haversine)."""
        return min(self.locations,
                   key=lambda loc: self._haversine_m(
                       (lat, long),
                       (to_f(loc.get("latitude")), to_f(loc.get("longitude")))))

    def construction_candidates(self, sheet, assembly_name) -> dict:
        """Candidate constructions for a sheet + assembly: {rsi: construction
        dict (with 'usi', 'name', 'type', 'id_layers')}, RSI ascending."""
        by_usi = self.constructions.get(sheet, {}).get(assembly_name, {}).get("usi")
        if by_usi is None:
            raise ValueError(
                f"no costed assembly '{assembly_name}' in constructions "
                f"sheet '{sheet}'")

        pairs = [(1.0 / to_f(usi),
                  {**construction, "name": assembly_name, "usi": to_f(usi)})
                 for usi, construction in by_usi.items()]
        return dict(sorted(pairs, key=lambda pair: pair[0]))

    def materials_sheet(self, sheet_type):
        return (self.materials_glazing if to_s(sheet_type) == "glazing"
                else self.materials_opaque)

    # ------------------------------------------------------------- private

    @staticmethod
    def _blank(value) -> bool:
        return value is None or to_s(value).strip() == ""

    def _base_priced_path(self, filename):
        for directory in PRICED_FALLBACK_DIRS:
            candidate = os.path.join(str(directory), filename)
            if os.path.exists(candidate):
                return candidate
        return None

    def _resolve_priced(self, filename, explicit):
        base = self._base_priced_path(filename)
        if base is not None:  # explicit costs_csv then overrides row-by-row in __init__
            return base
        if explicit is not None and os.path.exists(str(explicit)):
            return explicit

        raise ValueError(
            f"{filename} not found. — pass costs_csv=/local_factors_csv=, "
            "or set BTAP_COSTING_DIR.")

    @staticmethod
    def _load_csv(path) -> list[dict]:
        # '' → None: Ruby's CSV yields nil for empty fields and the lookup
        # code branches on nil-ness (see the module docstring).
        with open(path, newline="", encoding="utf-8") as f:
            return [{key: (None if value == "" else value)
                     for key, value in row.items()}
                    for row in csv.DictReader(f)]

    @staticmethod
    def _index_by_id(rows) -> dict:
        return {to_s(row.get("id")).upper(): row for row in rows}

    @staticmethod
    def _haversine_m(loc1, loc2) -> float:
        rad = math.pi / 180
        dlat = (loc2[0] - loc1[0]) * rad
        dlon = (loc2[1] - loc1[1]) * rad
        a = (math.sin(dlat / 2) ** 2
             + math.cos(loc1[0] * rad) * math.cos(loc2[0] * rad)
             * math.sin(dlon / 2) ** 2)
        return 6_371_000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
