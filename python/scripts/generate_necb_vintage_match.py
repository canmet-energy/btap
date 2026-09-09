#!/usr/bin/env python3
"""Generate the NECB vintage-match Markdown document.

**A verification pass, not an adoption.** Several manifest-declared outputs in
each edition snapshot are not that edition's own published text: they were
inherited from the legacy oracle (whose own lineage is NECB 2011/2015/2017) or
copied from the other edition's MCP retrieval. The multi-edition plan's Phase B
asks, before anything is adopted, a read-only question per file: *does the
content we ship actually equal what this edition publishes?*

This script answers it from ARCHIVED payloads. For every manifest ``provenance``
entry whose ``source`` is neither ``mcp:necb:<this edition>`` nor ``self:…``,
the edition's OWN source tables were fetched from the building-codes MCP and
retained under ``necb<edition>/provenance/vintage_match/<table>.result.json`` in
the canonical archived-payload form the data README documents (an object keyed
by canonical request, sorted keys, ``(",", ":")`` separators, no trailing
newline). The comparison then runs entirely offline, so ``--check`` is a plain
stdlib lint step exactly like ``generate_necb_edition_delta.py --check``.

Refreshing the archive is a maintainer MCP operation, deliberately explicit::

    python3 python/scripts/generate_necb_vintage_match.py --fetch
    python3 python/scripts/generate_necb_vintage_match.py

``--fetch`` is the ONLY path that imports ``btap._mcp``; generation and
``--check`` are stdlib-only and never touch the network.

Nothing here edits product data. A verdict of ``differs`` is a FINDING for the
D-89 adjudication, never a fix applied in passing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "NECB_VINTAGE_MATCH.md"
DATA_ROOT = REPO_ROOT / "python" / "btap" / "codes" / "necb" / "data"
ARCHIVE_DIRNAME = "vintage_match"

# --------------------------------------------------------------------------
# The spec: which of THIS edition's own tables answer for which shipped file.
#
# Keyed by manifest-declared output path. Each entry names, per edition, the
# table numbers in THAT edition's numbering. An edition missing from an entry
# ships the file from its own text already (necb2020's exterior_lighting and
# daylighting_controls are ``mcp:necb:2020``) and is not compared.
#
# ``sections`` are get_section retrievals for constants that no table carries.
# --------------------------------------------------------------------------
SCHEDULE_LETTERS = tuple("ABCDEFGHIJK")

SPEC: dict[str, dict] = {
    "tables/table_c1.json": {
        "tables": {"necb2020": ["C-1"], "necb2025": ["C-1"]},
    },
    "tables/schedules.json": {
        "tables": {
            "necb2020": [f"A-8.4.3.2.(1)-{c}" for c in SCHEDULE_LETTERS],
            "necb2025": [f"A-8.4.3.2.(1)(b)-{c}" for c in SCHEDULE_LETTERS],
        },
    },
    "tables/space_types.json": {
        "tables": {
            "necb2020": ["A-8.4.3.2.(2)-A", "A-8.4.3.2.(2)-B", "4.2.1.6",
                         "4.2.1.5", "4.3.2.10.-A"],
            "necb2025": ["A-8.4.3.2.(2)-A", "A-8.4.3.2.(2)-B", "4.2.1.6",
                         "4.2.1.5", "4.3.2.10.-A"],
        },
    },
    "tables/led_lighting.json": {
        "tables": {
            "necb2020": ["4.2.1.6", "4.2.1.5"],
            "necb2025": ["4.2.1.6", "4.2.1.5"],
        },
    },
    "lighting_rules.json": {
        "tables": {
            "necb2020": ["4.2.1.6", "4.3.2.10.-A", "4.3.2.10.-B"],
            "necb2025": ["4.2.1.6", "4.3.2.10.-A", "4.3.2.10.-B"],
        },
        "sections": {
            "necb2020": ["4.2.2.2", "4.2.1.6", "8.4.4.5"],
            "necb2025": ["4.2.2.2", "4.2.1.6", "8.4.5.5"],
        },
    },
    "shw_rules.json": {
        "tables": {"necb2020": ["6.2.2.1"], "necb2025": ["6.2.2.1"]},
        "sections": {"necb2020": ["8.4.5.9"], "necb2025": ["8.4.6.9"]},
    },
    "efficiencies.json": {
        # 2020's equipment tables are oracle-vendored; 2025's are already
        # ``mcp:necb:2025``. The CURVES are the 2011 set in both, so both
        # editions' curve tables are archived and compared.
        "tables": {
            "necb2020": (
                [f"5.2.12.1.-{c}" for c in "ABCDEFGHIJKLMNOP"]
                + ["5.2.12.2"]
                + ["8.4.5.2.-A", "8.4.5.2.-B", "8.4.5.3",
                   "8.4.5.5.-A", "8.4.5.5.-B", "8.4.5.5.-C",
                   "8.4.5.8.-A", "8.4.5.8.-B", "8.4.5.8.-C"]
            ),
            "necb2025": ["8.4.6.2", "8.4.6.3",
                         "8.4.6.5.-A", "8.4.6.5.-B", "8.4.6.5.-C",
                         "8.4.6.8.-A", "8.4.6.8.-B", "8.4.6.8.-C"],
        },
        # The governing articles state each curve's FORM and the units of its
        # independent variables -- which is what settles whether two coefficient
        # sets are the same surface.
        "sections": {
            "necb2020": ["8.4.5.2", "8.4.5.3", "8.4.5.5"],
            "necb2025": ["8.4.6.2", "8.4.6.3", "8.4.6.5"],
        },
    },
    "tables/daylighting_controls_4_2_1_6.json": {
        "tables": {"necb2025": ["4.2.1.6"]},
    },
    "tables/exterior_lighting.json": {
        "tables": {"necb2025": [f"4.2.3.1.-{c}" for c in "ABCDE"]},
    },
}


# --------------------------------------------------------------------------
# Archive plumbing
# --------------------------------------------------------------------------
def edition_of(edition_id: str) -> str:
    """``necb2020`` -> ``2020``."""
    return edition_id.replace("necb", "")


def request_key(kind: str, edition_id: str, number: str) -> str:
    return f"{kind}:necb:{edition_of(edition_id)}:{number}"


def archive_path(edition_id: str, kind: str, number: str) -> Path:
    stem = number if kind == "get_table" else f"section_{number}"
    return DATA_ROOT / edition_id / "provenance" / ARCHIVE_DIRNAME / f"{stem}.result.json"


def write_payload(path: Path, key: str, result) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({key: result}, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )


def read_payload(edition_id: str, kind: str, number: str):
    """The archived tool RESULT, or None when nothing is archived."""
    path = archive_path(edition_id, kind, number)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get(request_key(kind, edition_id, number))


# --------------------------------------------------------------------------
# Normalisation shared by the row matchers
# --------------------------------------------------------------------------
_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^a-z0-9 ]+")

#: Comparison operators must SURVIVE normalisation. Table 4.2.1.6 distinguishes
#: "Office enclosed, < 25 m²" from "enclosed, > 25 m²" and "Storage room
#: < 5 m²" from "≥ 5 m²" by the operator alone; folding punctuation away
#: collapses each pair to one key and silently compares a row against its
#: sibling's value.
_OPERATORS = (
    ("\u2265", " gte "), (">=", " gte "),
    ("\u2264", " lte "), ("<=", " lte "),
    (">", " gt "), ("<", " lt "),
)


def norm_name(text) -> str:
    """Case/accent/punctuation/whitespace-insensitive key for a row label,
    keeping the comparison operators that distinguish sibling rows."""
    if text is None:
        return ""
    s = unicodedata.normalize("NFKD", str(text))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("\u2019", "'").replace("\u2013", "-").replace("\u2014", "-")
    s = s.lower()
    for token, word in _OPERATORS:
        s = s.replace(token, word)
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()


_NUM = re.compile(r"^-?\d+(?:\.\d+)?$")


def as_number(text):
    """A float when the cell is a plain number, else None."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    if not isinstance(text, str):
        return None
    s = text.strip().replace("\u2212", "-").replace(",", "")
    if not _NUM.match(s):
        return None
    return float(s)


def numbers_equal(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


# --------------------------------------------------------------------------
# Corroborating a shipped NUMBER against an edition table
#
# The shipped rule files are ENGINE tables: capacities in Btu/h or tons,
# efficiencies as fractions or kW/ton. The Code publishes kW bins, percentages
# and COPs. A literal string search would report almost everything as absent
# and prove nothing, so a value is corroborated when ANY of its documented
# unit renderings appears among the numbers the edition's own table prints.
# --------------------------------------------------------------------------
BTU_PER_H_PER_KW = 3412.142
KW_PER_TON = 3.51685

#: A number as printed in a Code cell, allowing the thin/hard spaces the
#: typesetting uses as a thousands separator ("2 930", "1 055").
_CELL_NUMBER = re.compile(r"\d[\d\u00a0\u202f\u2009 ]*(?:\.\d+)?")


def numeric_corpus(tables: list[dict]) -> list[float]:
    """Every number printed anywhere in these tables."""
    out: list[float] = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        for row in table.get("rows", []):
            for cell in row.values():
                if not isinstance(cell, str):
                    continue
                for match in _CELL_NUMBER.finditer(cell):
                    cleaned = re.sub(r"[\u00a0\u202f\u2009 ]", "", match.group(0))
                    try:
                        out.append(float(cleaned))
                    except ValueError:
                        continue
    return out


def candidate_renderings(value: float) -> list[tuple[str, float]]:
    """The forms this engine value could take in a Code cell."""
    out = [("as published", value)]
    if 0 < value <= 1.5:
        out.append(("as a percentage", value * 100.0))
    if value > 1000:
        out.append(("Btu/h → kW", value / BTU_PER_H_PER_KW))
    if 0 < value < 10000:
        # The chiller bins are in TONS (150.13 t = 528 kW, 299.98 t = 1055 kW,
        # 599.97 t = 2110 kW, 400.07 t = 1407 kW), so this range has to reach
        # well past 100.
        out.append(("tons → kW", value * KW_PER_TON))
    if 0 < value < 10:
        out.append(("kW/ton → COP", KW_PER_TON / value))
    return out


def corroborate(value: float, corpus: list[float], tol: float = 5e-3):
    """The first candidate rendering the edition's own numbers carry."""
    for label, candidate in candidate_renderings(value):
        for printed in corpus:
            if abs(candidate - printed) <= tol * max(1.0, abs(printed)):
                return label, candidate, printed
    return None


# --------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------
class FileResult:
    """One shipped file's verdict, with everything the document prints."""

    def __init__(self, edition_id: str, path: str, source: str):
        self.edition_id = edition_id
        self.path = path
        self.source = source
        self.tables: list[str] = []          # tables actually consulted
        self.missing_tables: list[str] = []  # spec'd but not archived
        self.mapping: str = ""
        self.counts: dict[str, int] = {}
        self.notes: list[str] = []
        self.differences: list[tuple[str, str, str]] = []  # (leaf, shipped, edition)
        self.unmatched_shipped: list[str] = []
        self.unmatched_edition: list[str] = []
        self.no_source_columns: list[str] = []
        self.curves: list[dict] = []
        self.verdict = "not comparable without a mapping"

    def settle(self) -> None:
        """Derive the verdict from what the comparison found."""
        if self.verdict != "not comparable without a mapping":
            return
        if not self.tables:
            self.verdict = "no edition table"
        elif self.differences or self.unmatched_shipped or self.unmatched_edition:
            self.verdict = "differs"
        else:
            self.verdict = "identical"


VERDICT_ORDER = {"identical": 0, "differs": 1, "no edition table": 2,
                 "not comparable without a mapping": 3}


# --------------------------------------------------------------------------
# Per-file comparators
# --------------------------------------------------------------------------
def _shipped(edition_id: str, path: str):
    return json.loads((DATA_ROOT / edition_id / path).read_text(encoding="utf-8"))


#: shipped Table C-1 key -> the MCP column headers that carry the same
#: quantity, most-specific first. Two editions do not head these columns
#: identically: 2025 renamed "January 2.5% (°C)" to "January 2.5% °C" (the
#: same after normalisation) but SPLIT the July design temperatures into
#: Historical and Future pairs, so the shipped single value has to be aimed at
#: the Historical column and the Future column reported as having no shipped
#: counterpart at all.
C1_COLUMNS = {
    "elevation": ["elevation m"],
    "design_temp_jan_2_5p": ["january 2 5 c"],
    "design_temp_jan_1p": ["january 1 c"],
    "design_temp_july_2_5p_dry": ["july 2 5 dry c", "july 2 5 historical dry c"],
    "design_temp_july_2_5p_wet": ["july 2 5 wet c", "july 2 5 historical wet c"],
    "degree_days_below_18_c": ["degree days below 18 c"],
    "degree_days_below_15_c": ["degree days below 15 c"],
    "hourly_wind_pressures_one_tenth": ["hourly wind pressures 1 10 kpa"],
    "hourly_wind_pressures_one_fiftyth": ["hourly wind pressures 1 50 kpa"],
}


def _resolve_columns(headers: list[str], wanted: dict[str, list[str]]):
    """``{own key: header}`` for the columns THIS edition actually prints, plus
    the headers nothing shipped claims."""
    by_norm = {norm_name(h): h for h in headers}
    resolved, used = {}, set()
    for key, aliases in wanted.items():
        for alias in aliases:
            if alias in by_norm:
                resolved[key] = by_norm[alias]
                used.add(by_norm[alias])
                break
    unclaimed = [h for h in headers if h not in used]
    return resolved, unclaimed


def compare_table_c1(res: FileResult) -> None:
    table = read_payload(res.edition_id, "get_table", "C-1")
    if table is None:
        res.missing_tables.append("C-1")
        return
    res.tables.append("C-1")
    columns, unclaimed = _resolve_columns(table["headers"], C1_COLUMNS)
    res.mapping = (
        "rows matched by normalised city name (case, accents, punctuation and "
        "whitespace folded); every column this edition prints that the shipped "
        "record also carries is compared — " +
        ", ".join(f"`{k}` ← `{v}`" for k, v in sorted(columns.items())) +
        ". The shipped `lat_long` pair has no C-1 column and is excluded"
    )
    shipped_rows = _shipped(res.edition_id, "tables/table_c1.json")["table"]
    by_name: dict[str, list] = {}
    for row in shipped_rows:
        by_name.setdefault(norm_name(row.get("city")), []).append(row)
    edition_by_name: dict[str, list] = {}
    for row in table["rows"]:
        edition_by_name.setdefault(norm_name(row.get("Location")), []).append(row)

    matched = identical = differing = 0
    for key in sorted(set(by_name) & set(edition_by_name)):
        ship = by_name[key][0]
        edn = edition_by_name[key][0]
        matched += 1
        for own_key, column in sorted(columns.items()):
            a, b = ship.get(own_key), edn.get(column)
            na, nb = as_number(a), as_number(b)
            same = numbers_equal(na, nb) if (na is not None and nb is not None) \
                else str(a) == str(b)
            if same:
                identical += 1
            else:
                differing += 1
                res.differences.append(
                    (f"{ship.get('city')} ({ship.get('province')}) . {own_key}",
                     _fmt(a), _fmt(b)))
    res.unmatched_shipped = sorted(
        f"{by_name[k][0].get('city')} ({by_name[k][0].get('province')})"
        for k in set(by_name) - set(edition_by_name))
    res.unmatched_edition = sorted(
        f"{edition_by_name[k][0].get('Location')} ({edition_by_name[k][0].get('Province')})"
        for k in set(edition_by_name) - set(by_name))
    dup_ship = sorted(k for k, v in by_name.items() if len(v) > 1)
    dup_edn = sorted(k for k, v in edition_by_name.items() if len(v) > 1)
    if dup_ship or dup_edn:
        res.notes.append(
            f"duplicate normalised city names: {len(dup_ship)} shipped, "
            f"{len(dup_edn)} in the edition table; the first occurrence is compared")
    unclaimed = [h for h in unclaimed if h not in ("Location", "Province")]
    if unclaimed:
        res.no_source_columns = []
        res.notes.append(
            "columns THIS EDITION prints that nothing shipped carries: " +
            ", ".join(f"`{h}`" for h in unclaimed))
    res.counts = {
        "shipped rows": len(shipped_rows),
        "edition rows": len(table["rows"]),
        "rows matched": matched,
        "rows unmatched (shipped)": len(res.unmatched_shipped),
        "rows unmatched (edition)": len(res.unmatched_edition),
        "columns compared": len(columns),
        "edition columns with no shipped counterpart": len(unclaimed),
        "cells identical": identical,
        "cells differing": differing,
    }


#: The 24 hourly column labels the MCP serves, in CLOCK order starting at
#: midnight. ``12a`` is midnight and ``12p`` noon — the server's documented
#: ``known_issue`` for a printed table that heads both columns "12". The
#: printed columns are hour STARTS, so ``12a`` is the 00:00–01:00 hour and
#: therefore the FIRST of the 24 EnergyPlus hourly values, not the last; the
#: shipped schedules confirm it (with ``12a`` first every profile aligns
#: hour-for-hour, with it last every profile is off by one).
HOUR_COLUMNS = (["12a"]
                + ["1a", "2a", "3a", "4a", "5a", "6a", "7a", "8a", "9a", "10a", "11a"]
                + ["12p"]
                + ["1p", "2p", "3p", "4p", "5p", "6p", "7p", "8p", "9p", "10p", "11p"])

#: Cells the operating-schedule tables state as a WORD rather than a fraction.
SCHEDULE_WORDS = {"on": 1.0, "off": 0.0}

#: shipped `NECB-<letter>-<suffix>` name suffix -> the edition row's "Category".
#: Keyed on the NAME suffix rather than the ``category`` field because the two
#: thermostat schedules share one category and differ only by name.
SCHEDULE_CATEGORIES = {
    "occupancy": "occupants fraction occupied",
    "lighting": "lighting fraction on",
    "electric equipment": "receptacle equipment fraction of load",
    "fan": "fans",
    "service water heating": "service water heating system fraction of load",
    "thermostat setpoint cooling": "cooling system c",
    "thermostat setpoint heating": "heating system c",
}
#: shipped ``day_types`` token -> the edition row's "Day".
SCHEDULE_DAYS = {
    "Default|Wkdy": "mon fri",
    "Sat": "sat",
    "Sun|Hol": "sun",
}


def compare_schedules(res: FileResult, numbers: list[str]) -> None:
    shipped = _shipped(res.edition_id, "tables/schedules.json")["table"]
    res.mapping = (
        "each shipped `NECB-<letter>-<what>` Hourly record is joined to this "
        "edition's operating-schedule table for that LETTER by (Category, Day) "
        "— `Occupancy`→`Occupants, fraction occupied`, `Lighting`→`Lighting, "
        "fraction ON`, `Electric-Equipment`→`Receptacle Equipment, fraction of "
        "load`, `FAN`→`Fans`, `Service Water Heating`→`Service Water Heating "
        "System, fraction of load`, and the two `Thermostat Setpoint-*` records "
        "→ `Cooling System, °C` / `Heating System, °C`; `Default|Wkdy`→`Mon-Fri`, "
        "`Sat`→`Sat`, `Sun|Hol`→`Sun`. The 24 `values` are compared against the "
        "24 hourly columns in clock order (`12p` noon, `12a` midnight, per the "
        "server's documented column-label collision)"
    )
    edition_rows: dict[str, dict[tuple[str, str], dict]] = {}
    for number in numbers:
        table = read_payload(res.edition_id, "get_table", number)
        if table is None:
            res.missing_tables.append(number)
            continue
        res.tables.append(number)
        letter = number.rsplit("-", 1)[-1]
        # One 2025 table heads the column ``Day_Type`` where the other ten
        # head it ``Day``; both name the same thing.
        day_header = next((h for h in table["headers"]
                           if norm_name(h) in {"day", "day type"}), "Day")
        # One 2025 table serves the day cell as "Mon-Fri (Occupants)" — the
        # extraction folded the category into it. Indexed by the day PREFIX so
        # that decoration does not break the join.
        edition_rows[letter] = {}
        for r in table["rows"]:
            day_text = norm_name(r.get(day_header))
            for token in set(SCHEDULE_DAYS.values()):
                if day_text == token or day_text.startswith(token + " "):
                    edition_rows[letter][(norm_name(r.get("Category")), token)] = r
    if not edition_rows:
        return

    matched = identical = differing = worded = 0
    setpoint_sentinels: set = set()
    unmatched: list[str] = []
    constant_records = 0
    for rec in shipped:
        name = rec.get("name", "")
        parts = name.split("-", 2)
        letter = parts[1] if len(parts) > 2 else ""
        suffix = norm_name(parts[2]) if len(parts) > 2 else ""
        if rec.get("type") != "Hourly":
            constant_records += 1
            continue
        category = SCHEDULE_CATEGORIES.get(suffix)
        day = SCHEDULE_DAYS.get(rec.get("day_types"))
        row = edition_rows.get(letter, {}).get((category, day)) \
            if (category and day) else None
        if row is None:
            unmatched.append(f"{name} [{rec.get('day_types')}]")
            continue
        matched += 1
        values = rec.get("values") or []
        is_setpoint = "thermostat" in suffix
        for hour, column in enumerate(HOUR_COLUMNS):
            if column not in row or hour >= len(values):
                continue
            a = values[hour]
            b = as_number(row[column])
            if b is None:
                word = SCHEDULE_WORDS.get(norm_name(row[column]))
                if word is None:
                    worded += 1
                    continue
                if is_setpoint:
                    # "Off" in a setpoint row is not a temperature: the engine
                    # encodes a disabled setpoint as a far sentinel (35 °C
                    # cooling / 5 °C heating). Counted as an ENCODING
                    # difference, never as a wrong value.
                    worded += 1
                    setpoint_sentinels.add(a)
                    continue
                b = word
            if numbers_equal(float(a), b, 1e-9):
                identical += 1
            else:
                differing += 1
                res.differences.append(
                    (f"{name} [{rec.get('day_types')}] hour {hour + 1} ({column})",
                     _fmt(a), _fmt(row[column])))
    res.unmatched_shipped = sorted(unmatched)
    res.counts = {
        "shipped hourly records": sum(1 for r in shipped if r.get("type") == "Hourly"),
        "shipped Constant records (no edition row exists)": constant_records,
        "records matched": matched,
        "records unmatched": len(unmatched),
        "cells identical": identical,
        "cells differing": differing,
        "cells the edition states as a word, not a number": worded,
    }
    if worded:
        res.notes.append(
            f"{worded} cells are stated as a WORD in this edition's table where "
            "the snapshot carries a number: the fan rows print `On`/`Off` "
            "(compared as 1/0) and the two thermostat rows print `Off` where the "
            "engine encodes a disabled setpoint as a far sentinel (" +
            ", ".join(f"`{v} °C`" for v in sorted(setpoint_sentinels)) +
            "). An encoding difference, not a value difference")
    if constant_records:
        res.notes.append(
            f"{constant_records} Constant records (the `NECB-*-…` design-day "
            "defaults and `Always On`) have no counterpart in the "
            "operating-schedule tables at all: the edition publishes hourly "
            "fractions only")


# --------------------------------------------------------------------------
# The catalog-name bridge
#
# The shipped space-type catalog names ("Atrium (height < 6m)-sch-A") are the
# oracle's, not the Code's. The snapshot already contains an AUTHORED mapping
# from catalog name to Table 4.2.1.6 row: every entry of
# ``tables/daylighting_controls_4_2_1_6.json`` carries ``table_row`` as
# "Space Category | Space Type" (D-57, hand-mapped and LPD-cross-checked). This
# pass reuses that mapping rather than inventing a second one, and says so.
# --------------------------------------------------------------------------
_SCH_SUFFIX = re.compile(r"-sch-[A-Z]$")


def catalog_bridge(edition_id: str) -> dict[str, str]:
    """``{normalised catalog name: normalised "category | type" row key}``."""
    data = _shipped(edition_id, "tables/daylighting_controls_4_2_1_6.json")
    out = {}
    for name, entry in (data.get("space_types") or {}).items():
        row = entry.get("table_row") if isinstance(entry, dict) else None
        if row:
            out[norm_name(name)] = norm_name(row.replace("|", " "))
    return out


def catalog_name(record: dict) -> str:
    """The catalog name a space-type / LED record is keyed on."""
    stype = record.get("space_type") or ""
    if stype == "WholeBuilding":
        return record.get("building_type") or ""
    return _SCH_SUFFIX.sub("", stype)


def _row_keys(row: dict, headers: list[str]) -> set[str]:
    """Every name a table row can be addressed by.

    The two name columns are the table's own FIRST TWO headers, because the
    editions do not head them alike: 2020's A-8.4.3.2.(2)-B has
    "Space Type" / "Space Category" and 2025's has "Space Type" / "Category";
    4.3.2.10.-A is "Space Category" / "Space Type" in 2020 and
    "Category" / "Space Type Detail" in 2025; A-8.4.3.2.(2)-A swaps the two
    outright. Both orderings are indexed so the join does not depend on which
    column the typesetter put first.
    """
    first = str(row.get(headers[0], "") or "") if headers else ""
    second = str(row.get(headers[1], "") or "") if len(headers) > 1 else ""
    keys = {norm_name(f"{first} {second}"), norm_name(f"{second} {first}"),
            norm_name(first), norm_name(second)}
    return {k for k in keys if k}


def _index(table: dict) -> dict[str, dict]:
    """``{name: row}``, with any name that addresses MORE THAN ONE row dropped.

    A bare category name ("Storage room") can head several rows; keeping the
    first would silently compare a shipped value against a sibling row's. An
    ambiguous name is therefore no name at all, and the record it belongs to is
    reported unmatched rather than matched to a guess."""
    idx: dict[str, list] = {}
    headers = table.get("headers", [])
    for row in table.get("rows", []):
        for key in _row_keys(row, headers):
            bucket = idx.setdefault(key, [])
            if row not in bucket:
                bucket.append(row)
    return {key: rows[0] for key, rows in idx.items() if len(rows) == 1}


#: shipped space-type key -> (edition table, column header match, conversion).
SPACE_TYPE_COLUMNS = [
    ("occupancy_per_area", "A-8.4.3.2.(2)-B", "occupant density", "occupancy"),
    ("electric_equipment_per_area", "A-8.4.3.2.(2)-B", "peak receptacle load",
     "w_per_m2_to_w_per_ft2"),
    ("necb_schedule_type", "A-8.4.3.2.(2)-B", "operating schedule", "schedule_letter"),
    ("target_illuminance_setpoint", "A-8.4.3.2.(2)-B", "illuminance levels", "number"),
    ("lighting_per_area", "4.2.1.6", "lighting power density",
     "w_per_m2_to_w_per_ft2"),
    ("rel_absence_occ", "4.3.2.10.-A", "relative absence of occupants", "number"),
    ("personal_control", "4.3.2.10.-A", "personal control", "number"),
]

#: Shipped keys the edition DOES govern but only through a derivation, so a
#: cell-for-cell comparison would be meaningless: reported, never counted as
#: differing.
DERIVED_FROM_EDITION = {
    "service_water_heating_peak_flow_per_area":
        "derived from Table A-8.4.3.2.(2)-B's \"Service Water Heating Load, "
        "W/occupant\" together with the occupant density and a W → L/h "
        "conversion; not a transcribed cell",
}

W_PER_M2_TO_W_PER_FT2 = 0.09290304


def _column_by_prefix(table: dict, needle: str) -> str | None:
    for header in table.get("headers", []):
        if norm_name(header).startswith(needle):
            return header
    for header in table.get("headers", []):
        if needle in norm_name(header):
            return header
    return None


def compare_space_types(res: FileResult, numbers: list[str]) -> None:
    tables = {}
    for number in numbers:
        table = read_payload(res.edition_id, "get_table", number)
        if table is None:
            res.missing_tables.append(number)
            continue
        res.tables.append(number)
        tables[number] = table
    if not tables:
        return
    bridge = catalog_bridge(res.edition_id)
    res.mapping = (
        "the shipped catalog name (`space_type` with its `-sch-<letter>` suffix "
        "stripped, or `building_type` for `WholeBuilding` rows) is translated to "
        "a Table 4.2.1.6 row through the snapshot's OWN authored mapping — the "
        "`table_row` field of every `tables/daylighting_controls_4_2_1_6.json` "
        "entry (D-57, hand-mapped and LPD-cross-checked) — and that row key is "
        "then looked up in each edition table by normalised "
        "\"Space Category / Space Type\" name. Building-area rows resolve "
        "against Tables A-8.4.3.2.(2)-A and 4.2.1.5. Occupant density is "
        "inverted (m²/occupant → occupant/1000·m²), receptacle load and LPD "
        "converted W/m² → W/ft² as the shipped units require"
    )
    shipped = _shipped(res.edition_id, "tables/space_types.json")["table"]
    indexes = {number: _index(table) for number, table in tables.items()}
    whole_building = {}
    for number in ("A-8.4.3.2.(2)-A", "4.2.1.5"):
        if number in indexes:
            whole_building.update(indexes[number])

    matched = identical = differing = cloned_letters = 0
    unmatched: list[str] = []
    compared_columns: set[str] = set()
    for rec in shipped:
        label = catalog_name(rec)
        key = norm_name(label)
        row_key = bridge.get(key, key)
        is_whole = (rec.get("space_type") == "WholeBuilding")
        hits = {}
        for number, idx in indexes.items():
            if is_whole and number not in ("A-8.4.3.2.(2)-A", "4.2.1.5"):
                continue
            if not is_whole and number in ("A-8.4.3.2.(2)-A", "4.2.1.5"):
                continue
            hits[number] = idx.get(row_key) or idx.get(key)
        if is_whole:
            hits = {n: whole_building.get(key) for n in ("A-8.4.3.2.(2)-A", "4.2.1.5")
                    if n in indexes}
        if not any(hits.values()):
            unmatched.append(f"{rec.get('building_type')} / {rec.get('space_type')}")
            continue
        matched += 1
        for own_key, number, needle, kind in SPACE_TYPE_COLUMNS:
            source = number
            row = hits.get(number)
            if row is None and is_whole:
                for alt in ("A-8.4.3.2.(2)-A", "4.2.1.5"):
                    if hits.get(alt) is not None:
                        row, source = hits[alt], alt
                        break
            if row is None:
                continue
            column = _column_by_prefix(tables[source], needle)
            if not column or column not in row:
                continue
            shipped_value = rec.get(own_key)
            if shipped_value is None:
                continue
            compared_columns.add(own_key)
            edition_raw = row[column]
            edition_value = as_number(edition_raw)
            if kind == "schedule_letter":
                # The catalog CLONES every space function across all eleven
                # schedule letters ("…-sch-A" … "…-sch-K"); the edition assigns
                # exactly one. Only the un-cloned records can be compared.
                if _SCH_SUFFIX.search(rec.get("space_type") or ""):
                    cloned_letters += 1
                    continue
                same = norm_name(shipped_value) == norm_name(edition_raw)
                edition_shown = edition_raw
            elif edition_value is None:
                continue
            elif kind == "occupancy":
                # The table gives m²/occupant; the snapshot carries occupants
                # per 1000 ft² (its units are IP throughout).
                converted = (1000.0 / edition_value) * W_PER_M2_TO_W_PER_FT2 \
                    if edition_value else None
                same = converted is not None and numbers_equal(
                    float(shipped_value), converted, 2e-3)
                edition_shown = (f"{edition_raw} m²/occ → {converted:.6g} "
                                 "occ/1000 ft²")
            elif kind == "w_per_m2_to_w_per_ft2":
                converted = edition_value * W_PER_M2_TO_W_PER_FT2
                same = numbers_equal(float(shipped_value), converted, 5e-4)
                edition_shown = f"{edition_raw} W/m² → {converted:.6g}"
            else:
                same = numbers_equal(float(shipped_value), edition_value, 5e-4)
                edition_shown = edition_raw
            if same:
                identical += 1
            else:
                differing += 1
                res.differences.append(
                    (f"{label} . {own_key} (Table {source})",
                     _fmt(shipped_value), _fmt(edition_shown)))
    res.unmatched_shipped = sorted(set(unmatched))
    declared = {k for k, *_ in SPACE_TYPE_COLUMNS} | set(DERIVED_FROM_EDITION)
    res.no_source_columns = sorted(
        k for k in shipped[0]
        if k not in declared and k not in {"building_type", "space_type"})
    for key, why in sorted(DERIVED_FROM_EDITION.items()):
        res.notes.append(f"`{key}` is not compared cell-for-cell: {why}")
    if cloned_letters:
        res.notes.append(
            f"`necb_schedule_type` was skipped on {cloned_letters} records: the "
            "catalog clones every space function across all eleven schedule "
            "letters (`…-sch-A` … `…-sch-K`) while the edition assigns exactly "
            "one letter per row, so only the un-cloned building-area records "
            "carry a comparable letter")
    res.counts = {
        "shipped records": len(shipped),
        "records matched": matched,
        "records unmatched": len(res.unmatched_shipped),
        "cells identical": identical,
        "cells differing": differing,
        "shipped columns with an edition source": len(compared_columns),
        "shipped columns with NO edition source at all": len(res.no_source_columns),
    }
    res.notes.append(
        "Table A-8.4.3.2.(2)-B's `Space Category` column is served LAGGED by the "
        "extraction — continuation rows repeat the previous category — so rows "
        "are addressed by `Space Type` as well as by the pair, and anything that "
        "still fails to resolve is listed rather than guessed at")


def compare_led_lighting(res: FileResult, numbers: list[str]) -> None:
    tables = {}
    for number in numbers:
        table = read_payload(res.edition_id, "get_table", number)
        if table is None:
            res.missing_tables.append(number)
            continue
        res.tables.append(number)
        tables[number] = table
    if not tables:
        return
    shipped = _shipped(res.edition_id, "tables/led_lighting.json")["table"]
    bridge = catalog_bridge(res.edition_id)
    res.mapping = (
        "the shipped table is the legacy LED-ALTERNATIVE LPD set (NREL 63807 "
        "retrofit assumptions), not a code table; each row is joined by the same "
        "catalog-name bridge `tables/space_types.json` uses and its "
        "`lighting_per_area` (W/ft²) compared against this edition's published "
        "LPD in Table 4.2.1.6 (space-by-space) or 4.2.1.5 (building-area), "
        "converted W/m² → W/ft²"
    )
    indexes = {number: _index(table) for number, table in tables.items()}

    matched = identical = differing = 0
    unmatched: list[str] = []
    for rec in shipped:
        label = catalog_name(rec)
        key = norm_name(label)
        row_key = bridge.get(key, key)
        is_whole = (rec.get("space_type") == "WholeBuilding")
        order = ["4.2.1.5"] if is_whole else ["4.2.1.6"]
        hit = None
        for number in order:
            idx = indexes.get(number, {})
            row = idx.get(row_key) or idx.get(key)
            if row is not None:
                hit = (number, row)
                break
        if hit is None:
            unmatched.append(f"{rec.get('building_type')} / {rec.get('space_type')}")
            continue
        number, row = hit
        column = _column_by_prefix(tables[number], "lighting power density")
        matched += 1
        edition_value = as_number(row.get(column)) if column else None
        shipped_value = rec.get("lighting_per_area")
        if edition_value is None or shipped_value is None:
            continue
        converted = edition_value * W_PER_M2_TO_W_PER_FT2
        if numbers_equal(float(shipped_value), converted, 5e-4):
            identical += 1
        else:
            differing += 1
            res.differences.append(
                (f"{label} . lighting_per_area (Table {number})",
                 _fmt(shipped_value),
                 f"`{row.get(column)} W/m² → {converted:.6g}`"))
    res.unmatched_shipped = sorted(set(unmatched))
    res.no_source_columns = ["lighting_fraction_to_return_air", "lighting_fraction_radiant",
                            "lighting_fraction_visible"]
    res.counts = {
        "shipped records": len(shipped),
        "records matched": matched,
        "records unmatched": len(res.unmatched_shipped),
        "LPD values equal to the edition's": identical,
        "LPD values differing": differing,
        "shipped columns with NO edition source at all": len(res.no_source_columns),
    }
    res.notes.append(
        "A difference here is EXPECTED and is not a transcription error: an LED "
        "alternative LPD is deliberately lower than the Code's allowance. What "
        "the count says is how far the shipped alternatives sit below this "
        "edition's published maxima, and whether any exceeds one")


def _search_text(*chunks: str) -> str:
    return " ".join(c for c in chunks if c)


def compare_lighting_rules(res: FileResult, numbers: list[str], sections: list[str]) -> None:
    for number in numbers:
        if read_payload(res.edition_id, "get_table", number) is None:
            res.missing_tables.append(number)
        else:
            res.tables.append(number)
    for number in sections:
        if read_payload(res.edition_id, "get_section", number) is None:
            res.missing_tables.append(f"section {number}")
        else:
            res.tables.append(f"section {number}")
    shipped = _shipped(res.edition_id, "lighting_rules.json")
    res.mapping = (
        "constant by constant: each value is looked for verbatim (and in its "
        "unconverted form) in the edition's own article text and tables"
    )
    found = absent = 0
    rows: list[tuple[str, str, str]] = []

    def probe(label: str, shipped_value, needles: list[str], where: list[str]):
        nonlocal found, absent
        haystack = ""
        for number in where:
            kind, num = ("get_section", number[8:]) if number.startswith("section ") \
                else ("get_table", number)
            payload = read_payload(res.edition_id, kind, num)
            if payload is None:
                continue
            haystack += json.dumps(payload, ensure_ascii=False)
        hit = any(n in haystack for n in needles)
        if hit:
            found += 1
        else:
            absent += 1
            rows.append((label, _fmt(shipped_value),
                         "not present in " + ", ".join(where)))

    threshold = shipped.get("sensor_schedule_lpd_threshold_w_per_ft2")
    probe("sensor_schedule_lpd_threshold_w_per_ft2 (= 8.6 W/m\u00b2)", threshold,
          ["8.6"], ["section 4.2.2.2", "section 4.2.1.6", "4.2.1.6"])
    dwelling = shipped.get("dwelling_unit_lpd_w_per_m2")
    probe("dwelling_unit_lpd_w_per_m2", dwelling, ["5.0", " 5 "],
          [f"section {sections[-1]}"])
    atrium = shipped.get("atrium_led", {})
    for bin_name, block in atrium.items():
        if not isinstance(block, dict):
            continue
        for coefficient, value in block.items():
            probe(f"atrium_led.{bin_name}.{coefficient}", value,
                  [str(value)], ["4.2.1.6"])
    res.differences = rows
    res.counts = {
        "constants checked": found + absent,
        "constants with an edition source": found,
        "constants with NO edition source": absent,
    }
    res.notes.append(
        "The LED atrium equations are a legacy NREL-63807 retrofit ALTERNATIVE, "
        "not a code requirement: the edition publishes atrium LPDs by height bin "
        "in Table 4.2.1.6 and no LED-alternative equation at all")
    if absent:
        res.verdict = "differs"
    else:
        res.verdict = "identical"


def compare_shw_rules(res: FileResult, numbers: list[str], sections: list[str]) -> None:
    for number in numbers:
        if read_payload(res.edition_id, "get_table", number) is None:
            res.missing_tables.append(number)
        else:
            res.tables.append(number)
    for number in sections:
        if read_payload(res.edition_id, "get_section", number) is None:
            res.missing_tables.append(f"section {number}")
        else:
            res.tables.append(f"section {number}")
    table = read_payload(res.edition_id, "get_table", "6.2.2.1")
    shipped = _shipped(res.edition_id, "shw_rules.json")
    res.mapping = (
        "the consumed numeric leaves of `efficiency` and `solar_pool_minimums` "
        "are searched for in the edition's own Table 6.2.2.1 cells (the formula "
        "STRINGS are documentation, per the data README, and are matched as "
        "text); the part-load curve is checked against the governing article"
    )
    if table is None:
        return
    corpus = numeric_corpus([table])
    found = absent = 0
    for block in ("efficiency", "solar_pool_minimums"):
        for label, value in _numeric_leaves(shipped.get(block, {}), block):
            if label.startswith("efficiency.part_load_curve"):
                continue
            if corroborate(value, corpus):
                found += 1
            else:
                absent += 1
                res.differences.append(
                    (label, _fmt(value), "no rendering of this value appears in "
                                         "this edition's Table 6.2.2.1"))
    curve = shipped.get("efficiency", {}).get("part_load_curve", {})
    res.notes.append(
        "The SWH part-load curve `%s` (%s %s) has NO edition table: %s writes "
        "FHeatPLC as a quadratic FUEL RATIO, which the file already carries "
        "verbatim as `code_fheatplc` %s, and the shipped cubic is the "
        "probe-verified polynomial image of PLF(x) = x / FHeatPLC(x) for the "
        "EnergyPlus degradation-divisor field (D-53). Nothing to adopt: the "
        "edition's own coefficients are already recorded."
        % (curve.get("name"), curve.get("form"), curve.get("coefficients"),
           curve.get("article"),
           curve.get("code_fheatplc", {}).get("coefficients")))
    res.counts = {
        "numeric rule leaves checked": found + absent,
        "leaves present in the edition table": found,
        "leaves NOT present in the edition table": absent,
    }


def _numeric_leaves(node, prefix: str):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _numeric_leaves(value, f"{prefix}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _numeric_leaves(value, f"{prefix}[{i}]")
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        yield prefix, float(node)


def compare_efficiencies(res: FileResult, numbers: list[str],
                         sections: list[str] | None = None) -> None:
    for number in numbers:
        if read_payload(res.edition_id, "get_table", number) is None:
            res.missing_tables.append(number)
        else:
            res.tables.append(number)
    for number in sections or []:
        if read_payload(res.edition_id, "get_section", number) is None:
            res.missing_tables.append(f"section {number}")
        else:
            res.tables.append(f"section {number}")
    shipped = _shipped(res.edition_id, "efficiencies.json")
    equipment_tables = [n for n in res.tables if n.startswith("5.2.")]
    res.mapping = (
        "two independent comparisons. (a) EQUIPMENT: every numeric minimum in "
        "the shipped capacity bins is searched for in the edition's own "
        "5.2.12.1 series cells. (b) CURVES: each shipped `curves[]` entry is "
        "matched to the edition curve table that publishes the same quantity "
        "and compared in the independent variables each source states — see "
        "the dedicated curve section below"
    )
    if equipment_tables:
        corpus = numeric_corpus([read_payload(res.edition_id, "get_table", n)
                                 for n in equipment_tables])
        found = absent = 0
        renderings: dict[str, int] = {}
        for section, rows in sorted(shipped.items()):
            if section in {"curves", "provenance", "_provenance"} or not isinstance(rows, list):
                continue
            if section == "heat_rejection":
                # This section's own ``notes`` cite ASHRAE 90.1 tables, not the
                # NECB: a source outside the Code entirely, which the edition's
                # own 5.2.12.2 could replace. Reported, not silently counted.
                res.notes.append(
                    "`heat_rejection` (%d rows) cites ASHRAE 90.1 tables in its own "
                    "`notes`, not the NECB at all; this edition publishes Table "
                    "5.2.12.2 for the same equipment" % len(rows))
                continue
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                for key, value in sorted(row.items()):
                    number = as_number(value)
                    if number is None or number in (0.0,):
                        continue
                    hit = corroborate(number, corpus)
                    if hit:
                        found += 1
                        renderings[hit[0]] = renderings.get(hit[0], 0) + 1
                    else:
                        absent += 1
                        res.differences.append(
                            (f"{section}[{index}].{key}", _fmt(value),
                             "no rendering of this value appears in the edition's "
                             "5.2.12.1 series"))
        res.counts.update({
            "equipment values checked": found + absent,
            "corroborated by an edition cell": found,
            "NOT found in any edition cell": absent,
        })
        res.notes.append(
            "the shipped capacity bins close with engine SENTINELS "
            "(`9999.0` tons, `9999999.0` Btu/h, `9.999999999E9`) where the Code "
            "simply writes \u201c\u2265 \u2026\u201d with no upper bound; those have no "
            "edition cell by construction, not by disagreement")
        if renderings:
            res.notes.append(
                "the shipped file is an ENGINE table and the Code publishes SI "
                "bins, so each value is looked for in every documented unit "
                "rendering; the renderings that actually matched were " +
                ", ".join(f"{label} ({n})"
                          for label, n in sorted(renderings.items())))
    else:
        res.notes.append(
            "the equipment tables ARE this edition's own MCP retrieval "
            "(`mcp:necb:%s`) and are not re-compared here; only the inherited "
            "performance CURVES are" % edition_of(res.edition_id))
    records = curve_records(res.edition_id)
    res.curves = records
    for rec in records:
        if rec["verdict"] in {"differs", "no inherited curve"}:
            res.differences.append(
                (f"curves[{rec['name']}]" if rec["name"] else f"curves[{rec['label']}]",
                 _fmt(rec["shipped"]), rec["detail"]))
    res.counts["shipped curves"] = len(shipped.get("curves", []))
    for verdict in ("identical to rounding", "differs", "no edition table",
                    "no inherited curve"):
        n = sum(1 for r in records if r["verdict"] == verdict)
        if n:
            res.counts[f"curves — {verdict}"] = n


# --------------------------------------------------------------------------
# Curves: the substantive comparison
#
# Each edition publishes its own curve tables. The shipped curves are the
# oracle's NECB 2011 set. Comparing coefficients directly is meaningless when
# the two sources state DIFFERENT independent variables, so each class is
# compared in the variables its own source declares:
#
#   * The chiller articles (8.4.5.5.(3)/(7), 8.4.6.5.(3)/(7)) define CAP_FTEC
#     and EIR_FT over t_chws / t_cws in **°F**. The shipped EnergyPlus
#     `Curve:Biquadratic` takes **°C**. A biquadratic re-expressed under the
#     affine substitution t_F = 1.8 t_C + 32 has closed-form coefficients, so
#     "same surface, different units" is a decidable question, not a guess.
#   * EIR_FPLR is a function of PLR, dimensionless in both — direct compare.
#   * The boiler/furnace articles define FHeatPLC as a FUEL RATIO; the shipped
#     curve is an EnergyPlus efficiency multiplier. The two are related by
#     eff(PLR) = PLR / FHeatPLC(PLR), so the comparison is of the two FUNCTIONS
#     over the PLR domain, not of coefficients.
# --------------------------------------------------------------------------
CHILLER_TYPES = ("Scroll", "Reciprocating", "Screw", "Centrifugal")

#: "this row is not one the map speaks about", distinct from "the map says
#: this row has no shipped curve" (which is a real, reportable finding).
_ABSENT = object()

CURVE_TABLES = {
    "chiller_capft": {"necb2020": "8.4.5.5.-A", "necb2025": "8.4.6.5.-A"},
    "chiller_eirfplr": {"necb2020": "8.4.5.5.-B", "necb2025": "8.4.6.5.-B"},
    "chiller_eirft": {"necb2020": "8.4.5.5.-C", "necb2025": "8.4.6.5.-C"},
    "boiler_plc": {"necb2020": "8.4.5.2.-A", "necb2025": "8.4.6.2"},
    "boiler_modulating": {"necb2020": "8.4.5.2.-B", "necb2025": "8.4.6.2"},
    "furnace_plc": {"necb2020": "8.4.5.3", "necb2025": "8.4.6.3"},
    "absorption_capft": {"necb2020": "8.4.5.8.-A", "necb2025": "8.4.6.8.-A"},
    "absorption_firfplr": {"necb2020": "8.4.5.8.-B", "necb2025": "8.4.6.8.-B"},
    "absorption_firft": {"necb2020": "8.4.5.8.-C", "necb2025": "8.4.6.8.-C"},
}

#: Curves neither edition publishes a table for. The NECB 2011 origin is
#: legitimately retained; Phase B must record it as such, never silently.
NO_EDITION_TABLE_PREFIXES = ("DXCOOL-", "DXHEAT-", "VarVolFan-", "SWH-")

#: How close two coefficient sets must be to count as the same numbers at the
#: precision the snapshot publishes (6 significant figures).
ROUNDING_TOL = 5e-5


def f_to_c_biquadratic(k: list[float]) -> list[float]:
    """The SAME biquadratic surface, re-expressed for °C inputs.

    Substituting t_F = 1.8 t_C + 32 into
    ``a + b x + c x² + d y + e y² + f x y`` and collecting terms."""
    a, b, c, d, e, f = k
    return [
        a + 32 * b + 1024 * c + 32 * d + 1024 * e + 1024 * f,
        1.8 * b + 115.2 * c + 57.6 * f,
        3.24 * c,
        1.8 * d + 115.2 * e + 57.6 * f,
        3.24 * e,
        3.24 * f,
    ]


def biquadratic(k, x, y):
    return k[0] + k[1] * x + k[2] * x * x + k[3] * y + k[4] * y * y + k[5] * x * y


def poly(k, x):
    return sum(c * x ** i for i, c in enumerate(k))


def max_rel_dev(a: list[float], b: list[float]) -> float:
    return max(abs(x - y) / max(abs(y), 1e-9) for x, y in zip(a, b))


def _row_coefficients(row: dict, letters: str):
    out = []
    for letter in letters:
        value = as_number(row.get(letter))
        if value is None:
            return None
        out.append(value)
    return out


def _errata(table: dict) -> dict:
    """``{(cooling type, chiller type, coefficient): corrected value}`` from the
    server's own ``known_issue`` block. Archived data, never a local guess."""
    issue = table.get("known_issue") or {}
    out = {}
    for row in issue.get("affected_rows", []):
        if not isinstance(row, dict):
            continue
        corrected = as_number(str(row.get("suspected_correct", "")).split()[0]
                              if row.get("suspected_correct") else None)
        if corrected is None:
            continue
        out[(row.get("cooling_type"), row.get("chiller_type"),
             row.get("coefficient"))] = corrected
    return out


def _curve_index(edition_id: str) -> dict:
    return {c["name"]: c for c in _shipped(edition_id, "efficiencies.json").get("curves", [])}


def _coeffs(curve: dict, n: int) -> list[float]:
    return [curve[f"coeff_{i}"] for i in range(1, n + 1)]


#: Physical operating points the chiller surfaces are evaluated at, in °C:
#: the AHRI 550/590 rating point (6.67 / 29.44) and three corners of the
#: shipped curves' own declared validity box.
CHILLER_POINTS = ((6.67, 29.44), (6.67, 35.0), (10.0, 24.0), (5.0, 24.0))
#: PLR grid for the part-load curve comparison.
PLR_POINTS = tuple(round(0.1 + 0.05 * i, 2) for i in range(19))


def curve_records(edition_id: str) -> list[dict]:
    """One record per curve class the edition publishes or the snapshot ships."""
    curves = _curve_index(edition_id)
    records: list[dict] = []

    def table(kind):
        return read_payload(edition_id, "get_table", CURVE_TABLES[kind][edition_id])

    # -- chiller CAP_FT / EIR_FT: the °F/°C question -----------------------
    for kind, quantity, letters in (("chiller_capft", "CAPFT", "abcdef"),
                                    ("chiller_eirft", "EIRFT", "abcdef")):
        payload = table(kind)
        number = CURVE_TABLES[kind][edition_id]
        if payload is None:
            continue
        errata = _errata(payload)
        for row in payload.get("rows", []):
            cooling, chiller = row.get("Cooling Type"), row.get("Chiller Type")
            name = f"WaterCooled_{chiller}_{quantity}"
            printed = _row_coefficients(row, letters)
            shipped = curves.get(name)
            if cooling != "Water-cooled":
                if printed is not None and shipped is None:
                    records.append(_no_shipped(f"{cooling} {chiller} {quantity}", number))
                continue
            if printed is None or shipped is None:
                records.append(_no_shipped(f"{cooling} {chiller} {quantity}", number))
                continue
            ship = _coeffs(shipped, 6)
            converted = f_to_c_biquadratic(printed)
            dev = max_rel_dev(converted, ship)
            corrected = list(printed)
            applied = []
            for i, letter in enumerate(letters):
                fix = errata.get((cooling, chiller, letter))
                if fix is not None:
                    corrected[i] = fix
                    applied.append(f"{letter}: {row[letter]} → {fix}")
            dev_corrected = max_rel_dev(f_to_c_biquadratic(corrected), ship) if applied else dev
            points = []
            for x, y in CHILLER_POINTS:
                a = biquadratic(ship, x, y)
                b = biquadratic(corrected if applied else printed,
                                x * 1.8 + 32, y * 1.8 + 32)
                points.append((f"{x} °C / {y} °C", a, b, (b / a) if a else float("nan")))
            best = min(dev, dev_corrected)
            if best <= ROUNDING_TOL:
                verdict = "identical to rounding"
                detail = (
                    "the shipped °C coefficients are the exact affine "
                    "°F→°C image of this edition's own row "
                    f"(max relative deviation {best:.1e})")
                if applied:
                    detail += (
                        "; reached only after applying the codes service's own "
                        "published errata for this row (" + "; ".join(applied) +
                        ") — the shipped curve matches the CORRECTED value, so "
                        "the printed misprint is the source's, not the snapshot's")
            else:
                verdict = "differs"
                detail = (f"max relative deviation {best:.2e} after the °F→°C "
                          "transform — not a unit restatement")
            records.append({
                "klass": quantity, "name": name,
                "label": f"{cooling} {chiller} {quantity}",
                "table": number, "relation": "°F→°C affine transform of a biquadratic",
                "verdict": verdict, "detail": detail,
                "shipped": ship, "edition": printed, "converted": converted,
                "errata": applied, "deviation": best, "points": points,
            })

    # -- chiller EIR_FPLR: dimensionless, direct ---------------------------
    payload = table("chiller_eirfplr")
    number = CURVE_TABLES["chiller_eirfplr"][edition_id]
    if payload is not None:
        for row in payload.get("rows", []):
            cooling, chiller = row.get("Cooling Type"), row.get("Chiller Type")
            name = f"WaterCooled_{chiller}_EIRFPLR"
            printed = _row_coefficients(row, "abc")
            shipped = curves.get(name)
            if cooling != "Water-cooled" or printed is None or shipped is None:
                if printed is not None and (cooling != "Water-cooled" or shipped is None):
                    records.append(_no_shipped(f"{cooling} {chiller} EIR_FPLR", number))
                continue
            ship = _coeffs(shipped, 3)
            dev = max_rel_dev(printed, ship)
            records.append({
                "klass": "EIRFPLR", "name": name,
                "label": f"{cooling} {chiller} EIR_FPLR",
                "table": number, "relation": "direct (PLR is dimensionless in both)",
                "verdict": "identical to rounding" if dev <= ROUNDING_TOL else "differs",
                "detail": (f"max relative deviation {dev:.1e}; the snapshot carries 6 "
                           "decimal places, the edition table 8"
                           if dev <= ROUNDING_TOL else
                           f"max relative deviation {dev:.2e}"),
                "shipped": ship, "edition": printed, "converted": None,
                "errata": [], "deviation": dev, "points": [],
            })

    # -- boiler / furnace FHeatPLC: a functional-form change ---------------
    for kind, rows_wanted in (("boiler_plc", {"Non-condensing": "BOILER-EFFFPLR",
                                              "Condensing": "BOILER-EFFFPLR-COND",
                                              "Modulating": None}),
                              ("furnace_plc", {"Atmospheric": "FURNACE-EFFPLR",
                                               "Condensing": "FURNACE-EFFPLR-COND",
                                               "Modulating": None})):
        payload = table(kind)
        number = CURVE_TABLES[kind][edition_id]
        if payload is None:
            continue
        label_key = "Type of Boiler" if kind == "boiler_plc" else "Type of Furnace"
        for row in payload.get("rows", []):
            kindname = row.get(label_key)
            name = rows_wanted.get(kindname, _ABSENT)
            if name is _ABSENT:
                continue
            printed3 = _row_coefficients(row, "abc")
            printed6 = _row_coefficients(row, "abcdef")
            bivariate = printed6 is not None and any(abs(v) > 0 for v in printed6[3:])
            if name is None or curves.get(name) is None:
                records.append({
                    "klass": "FHeatPLC", "name": None,
                    "label": f"{kindname} ({label_key.split()[-1].lower()})",
                    "table": number, "relation": "—",
                    "verdict": "no inherited curve",
                    "detail": ("this edition publishes a curve for this equipment "
                               "class and the snapshot ships none"),
                    "shipped": None, "edition": printed6 or printed3,
                    "converted": None, "errata": [], "deviation": None, "points": [],
                })
                continue
            ship = [c for c in _coeffs(curves[name], 4) if c is not None]
            if bivariate:
                records.append({
                    "klass": "FHeatPLC", "name": name,
                    "label": f"{kindname} ({label_key.split()[-1].lower()})",
                    "table": number,
                    "relation": "not comparable — the edition's FHeatPLC is BIVARIATE",
                    "verdict": "differs",
                    "detail": ("this edition defines FHeatPLC over PLR **and** the "
                               "boiler return-hot-water temperature T_w,return (°F, "
                               "six coefficients); the shipped curve is univariate "
                               "in PLR and cannot express the second variable at all"),
                    "shipped": ship, "edition": printed6, "converted": None,
                    "errata": [], "deviation": None, "points": [],
                })
                continue
            if printed3 is None:
                continue
            worst = 0.0
            points = []
            for plr in PLR_POINTS:
                fheatplc = poly(printed3, plr)
                if fheatplc == 0:
                    continue
                edition_eff = plr / fheatplc
                shipped_eff = poly(ship, plr)
                rel = abs(shipped_eff - edition_eff) / abs(edition_eff)
                worst = max(worst, rel)
                if plr in (0.1, 0.25, 0.5, 0.75, 1.0):
                    points.append((f"PLR {plr}", shipped_eff, edition_eff,
                                   shipped_eff / edition_eff))
            records.append({
                "klass": "FHeatPLC", "name": name,
                "label": f"{kindname} ({label_key.split()[-1].lower()})",
                "table": number,
                "relation": ("functional-form change: the edition's FHeatPLC is a "
                             "fuel RATIO; the shipped curve is the EnergyPlus "
                             "efficiency multiplier PLR / FHeatPLC(PLR)"),
                "verdict": "identical to rounding" if worst <= ROUNDING_TOL else "differs",
                "detail": (f"the shipped cubic APPROXIMATES the edition's quadratic: "
                           f"worst deviation {worst * 100:.2f} % over PLR 0.10–1.00 "
                           "— close, not exact"),
                "shipped": ship, "edition": printed3, "converted": None,
                "errata": [], "deviation": worst, "points": points,
            })

    # -- absorption chillers: published, never modelled --------------------
    for kind, quantity in (("absorption_capft", "CAP_FTAC"),
                           ("absorption_firfplr", "FIR_FPLR"),
                           ("absorption_firft", "FIR_FT")):
        payload = table(kind)
        if payload is None:
            continue
        number = CURVE_TABLES[kind][edition_id]
        for row in payload.get("rows", []):
            label = row.get("Type of Absorption Chiller") or "absorption"
            records.append(_no_shipped(f"{label} {quantity}", number))

    # -- curves neither edition publishes ----------------------------------
    for name, curve in sorted(curves.items()):
        if not name.startswith(NO_EDITION_TABLE_PREFIXES):
            continue
        records.append({
            "klass": "no edition table", "name": name, "label": name,
            "table": "—", "relation": "—", "verdict": "no edition table",
            "detail": ("neither edition publishes a table for this quantity; the "
                       "NECB 2011 origin is legitimately retained and must be "
                       "STATED in provenance, not silently inherited"),
            "shipped": [c for c in _coeffs(curve, 10) if c is not None],
            "edition": None, "converted": None, "errata": [],
            "deviation": None, "points": [],
        })
    records.sort(key=lambda r: (r["klass"], r["label"]))
    return records


def _no_shipped(label: str, number: str) -> dict:
    return {
        "klass": "no inherited curve", "name": None, "label": label,
        "table": number, "relation": "—", "verdict": "no inherited curve",
        "detail": ("this edition publishes coefficients for this class and the "
                   "snapshot ships no corresponding curve"),
        "shipped": None, "edition": None, "converted": None, "errata": [],
        "deviation": None, "points": [],
    }


def compare_daylighting(res: FileResult, numbers: list[str]) -> None:
    number = numbers[0]
    table = read_payload(res.edition_id, "get_table", number)
    if table is None:
        res.missing_tables.append(number)
        return
    res.tables.append(number)
    res.mapping = (
        "the shipped file is keyed by NECB space-function CATALOG name and each "
        "entry names the Table 4.2.1.6 row it was mapped to in its own "
        "`table_row` field (\"Space Category | Space Type\"); that field is the "
        "join key. The entry's `sidelighting` / `toplighting` state is compared "
        "against the corresponding cell of THIS edition's Table 4.2.1.6 "
        "(`X` → `required`, `-` → `not_required`). Entries whose `table_row` is "
        "null — the file's own `residue` — are excluded by construction, not "
        "silently dropped"
    )
    shipped = _shipped(res.edition_id, "tables/daylighting_controls_4_2_1_6.json")
    entries = shipped.get("space_types") or {}
    side_col = top_col = None
    for header in table["headers"]:
        low = header.lower()
        if "sidelighting" in low:
            side_col = header
        elif "toplighting" in low:
            top_col = header
    idx = _index(table)

    def state(cell):
        raw = (cell or "").strip()
        if raw.upper() == "X":
            return "required"
        if raw in {"-", "–", "—"}:
            return "not_required"
        return None

    matched = identical = differing = 0
    unmatched: list[str] = []
    residue = 0
    for name, entry in sorted(entries.items()):
        if not isinstance(entry, dict):
            continue
        row_name = entry.get("table_row")
        if not row_name:
            residue += 1
            continue
        row = idx.get(norm_name(row_name.replace("|", " "))) or idx.get(norm_name(name))
        if row is None:
            unmatched.append(f"{name} → {row_name}")
            continue
        matched += 1
        for own_key, column in (("sidelighting", side_col), ("toplighting", top_col)):
            if not column or column not in row:
                continue
            shipped_state = entry.get(own_key)
            edition_state = state(row[column])
            if edition_state is None or shipped_state in (None, "not_listed",
                                                          "not_applicable", "unknown"):
                continue
            if shipped_state == edition_state:
                identical += 1
            else:
                differing += 1
                res.differences.append((f"{name} . {own_key}",
                                        _fmt(shipped_state), _fmt(edition_state)))
    res.unmatched_shipped = sorted(set(unmatched))
    res.counts = {
        "shipped entries": len(entries),
        "entries the file itself records as absent from 4.2.1.6": residue,
        "entries matched": matched,
        "entries unmatched": len(res.unmatched_shipped),
        "control states identical": identical,
        "control states differing": differing,
    }
    if identical and not differing and not res.unmatched_shipped:
        res.notes.append(
            "the copy was made from the 2020 retrieval, but this edition's own "
            "Table 4.2.1.6 carries the same daylight-control cells for every "
            "mapped row — so the copy is CORRECT for this edition, and adopting "
            "its own payload would be a provenance-only change")


#: shipped exterior-lighting application label -> the normalised
#: "Exterior Application" text this edition prints. The shipped labels are the
#: transcriber's compressions of the printed application names; where the two
#: differ by more than case they are aliased here, once, in data.
EXTERIOR_ALIASES = {
    "uncovered parking areas and drives": "parking areas and drives",
    "walkways gte 3 m wide plaza and special feature areas":
        "walkways 3 m wide or greater plaza areas special feature areas",
    "pedestrian and vehicular entrances exits":
        "pedestrian and vehicular entrances and exits",
    "sales canopies free standing and attached": "free standing and attached",
    "outdoor sales open areas incl vehicle sales lots":
        "open areas including vehicle sales lots",
    "street frontage for vehicle sales lots in addition to open area":
        "street frontage for vehicle sales lots in addition to open area allowance",
    "drive up windows and doors per drive through": "drive up windows and doors",
    "parking near 24 hour retail entrances per main entry":
        "parking near 24 hour retail entrances",
    "building facades per illuminated wall surface area":
        "building facades facade lighting",
    "building facades per illuminated wall surface length":
        "building facades facade lighting",
    "atms and night depositories per location":
        "automated teller machines atm and night depositories",
    "additional atms per atm per location":
        "automated teller machines atm and night depositories",
    "entrances gatehouse inspection stations at guarded facilities":
        "entrances and gatehouse inspection stations at guarded facilities",
    "loading areas for emergency service vehicles":
        "loading areas for law enforcement fire ambulance and other emergency "
        "service vehicles",
    "areas not covered in article 4 2 3 1": "areas not covered in article 4 2 3 1",
}


def compare_exterior_lighting(res: FileResult, numbers: list[str]) -> None:
    tables = {}
    for number in numbers:
        table = read_payload(res.edition_id, "get_table", number)
        if table is None:
            res.missing_tables.append(number)
            continue
        res.tables.append(number)
        tables[number] = table
    if not tables:
        return
    shipped = _shipped(res.edition_id, "tables/exterior_lighting.json")
    res.mapping = (
        "each `tradable` / `non_tradable` entry is matched to a row of THIS "
        "edition's Tables 4.2.3.1.-C / -D / -E by its `application` label "
        "(normalised, with a small declared alias list for the transcriber's "
        "compressions), and its per-zone allowance compared against the number "
        "printed in that row's `Zone N` cell; the basic site allowances and the "
        "uncovered-area percentages are compared against Tables -B and -E, and "
        "the zone descriptions against Table -A"
    )
    rows: dict[str, tuple[str, dict]] = {}
    for number, table in tables.items():
        for row in table.get("rows", []):
            application = row.get("Exterior Application")
            if application:
                rows.setdefault(norm_name(application), (number, row))

    matched = identical = differing = 0
    unmatched: list[str] = []
    for section in ("tradable", "non_tradable"):
        for entry in shipped.get(section, []):
            label = entry.get("application", "")
            key = norm_name(label)
            key = EXTERIOR_ALIASES.get(key, key)
            hit = rows.get(key)
            if hit is None:
                unmatched.append(f"{section}: {label}")
                continue
            number, row = hit
            matched += 1
            for zone, value in sorted((entry.get("by_zone") or {}).items()):
                cell = row.get(f"Zone {zone}")
                if cell is None:
                    continue
                printed = numeric_corpus([{"rows": [{"c": cell}]}])
                if any(abs(p - float(value)) <= 5e-3 * max(1.0, abs(p)) for p in printed):
                    identical += 1
                else:
                    differing += 1
                    res.differences.append(
                        (f"{section}.{entry.get('key')}.zone {zone}",
                         _fmt(value), _fmt(cell)))

    zones = tables.get("4.2.3.1.-A")
    basic = tables.get("4.2.3.1.-B")
    if basic:
        for zone, value in sorted((shipped.get("basic_site_allowance_w") or {}).items()):
            cell = basic["rows"][0].get(f"Zone {zone}") if basic.get("rows") else None
            printed = numeric_corpus([{"rows": [{"c": cell or ""}]}])
            expected = float(value)
            if (expected == 0 and not printed) or \
                    any(abs(p - expected) <= 1e-9 for p in printed):
                identical += 1
            else:
                differing += 1
                res.differences.append((f"basic_site_allowance_w.{zone}",
                                        _fmt(value), _fmt(cell)))
    uncovered = tables.get("4.2.3.1.-E")
    if uncovered and uncovered.get("rows"):
        row = uncovered["rows"][0]
        for zone, value in sorted(
                (shipped.get("uncovered_percent_of_interior") or {}).items()):
            cell = row.get(f"Zone {zone}")
            printed = numeric_corpus([{"rows": [{"c": cell or ""}]}])
            if any(abs(p - float(value)) <= 1e-9 for p in printed):
                identical += 1
            else:
                differing += 1
                res.differences.append((f"uncovered_percent_of_interior.{zone}",
                                        _fmt(value), _fmt(cell)))
    if zones:
        printed_zones = {norm_name(r.get("Lighting Zone")): r.get("Description")
                         for r in zones.get("rows", [])}
        absent = [z for z in (shipped.get("lighting_zones") or {})
                  if norm_name(z) not in printed_zones]
        res.notes.append(
            "the five `lighting_zones` descriptions are the transcriber's "
            "compressions of this edition's Table 4.2.3.1.-A prose (\"national/"
            "provincial/territorial\" for \"national, provincial or "
            "territorial\"), so they are checked for EXISTENCE, not wording: " +
            (f"{len(absent)} shipped zone(s) have no row here" if absent
             else "all five zones exist in this edition's table"))
    res.unmatched_shipped = sorted(set(unmatched))
    res.counts = {
        "shipped allowance entries": sum(len(shipped.get(s, []))
                                         for s in ("tradable", "non_tradable")),
        "entries matched to an edition row": matched,
        "entries unmatched": len(res.unmatched_shipped),
        "values equal to this edition's": identical,
        "values differing": differing,
    }


def _string_leaves(node, skip=("provenance", "_provenance", "note", "notes")):
    if isinstance(node, dict):
        for key, value in node.items():
            if key in skip:
                continue
            yield from _string_leaves(value, skip)
    elif isinstance(node, list):
        for value in node:
            yield from _string_leaves(value, skip)
    elif isinstance(node, str) and len(node) < 80:
        yield node


COMPARATORS = {
    "tables/table_c1.json": lambda res, spec: compare_table_c1(res),
    "tables/schedules.json": lambda res, spec: compare_schedules(res, spec["tables"]),
    "tables/space_types.json": lambda res, spec: compare_space_types(res, spec["tables"]),
    "tables/led_lighting.json": lambda res, spec: compare_led_lighting(res, spec["tables"]),
    "lighting_rules.json": lambda res, spec: compare_lighting_rules(
        res, spec["tables"], spec["sections"]),
    "shw_rules.json": lambda res, spec: compare_shw_rules(res, spec["tables"], spec["sections"]),
    "efficiencies.json": lambda res, spec: compare_efficiencies(
        res, spec["tables"], spec["sections"]),
    "tables/daylighting_controls_4_2_1_6.json":
        lambda res, spec: compare_daylighting(res, spec["tables"]),
    "tables/exterior_lighting.json":
        lambda res, spec: compare_exterior_lighting(res, spec["tables"]),
}


# --------------------------------------------------------------------------
# Which shipped files are NOT this edition's own text
# --------------------------------------------------------------------------
def load_manifests() -> dict[str, dict]:
    out = {}
    for path in sorted(DATA_ROOT.glob("*/manifest.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        out[manifest["id"]] = manifest
    return out


def foreign_outputs(manifest: dict) -> dict[str, str]:
    """Manifest-declared outputs whose ``source`` is not this edition's own
    text: anything not ``mcp:necb:<edition>`` and not a ``self:`` declaration."""
    own = f"mcp:necb:{manifest['edition']}"
    out = {}
    for path, entry in manifest.get("provenance", {}).items():
        source = entry.get("source", "")
        if source == own or source.startswith("self:"):
            continue
        out[path] = source
    return out


# --------------------------------------------------------------------------
# Fetch (the only MCP path)
# --------------------------------------------------------------------------
def fetch(only: str | None = None) -> int:
    sys.path.insert(0, str(REPO_ROOT / "python"))
    from btap._mcp import MCPClient, MCPError  # noqa: PLC0415

    client = MCPClient("codes")
    wrote = 0
    for edition_id in sorted(load_manifests()):
        for path, spec in SPEC.items():
            if only and only != path:
                continue
            for kind, key in (("get_table", "tables"), ("get_section", "sections")):
                for number in spec.get(key, {}).get(edition_id, []):
                    target = archive_path(edition_id, kind, number)
                    if target.is_file():
                        continue
                    args = {"code": "necb", "edition": edition_of(edition_id),
                            "division": "B"}
                    if kind == "get_table":
                        args["table_number"] = number
                    else:
                        args["section_number"] = number
                        args["include_sentences"] = False
                    try:
                        result = client.call(kind, args)
                    except MCPError as exc:
                        print(f"{edition_id} {kind} {number}: FAILED {exc}")
                        continue
                    write_payload(target, request_key(kind, edition_id, number), result)
                    wrote += 1
                    print(f"{edition_id} {kind} {number}: archived")
    print(f"\n{wrote} payload(s) written under */provenance/{ARCHIVE_DIRNAME}/")
    return 0


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------
def _fmt(value) -> str:
    if value is None:
        return "_(absent)_"
    text = str(value).replace("|", "\\|").replace("\n", " ")
    return f"`{text}`" if len(text) <= 120 else f"`{text[:117]}…`"


MAX_LISTED = 60


def _listing(title: str, items: list[str]) -> list[str]:
    if not items:
        return []
    out = [f"{title} ({len(items)}):", ""]
    shown = items[:MAX_LISTED]
    out += [f"- `{item}`" for item in shown]
    if len(items) > MAX_LISTED:
        out.append(f"- _… and {len(items) - MAX_LISTED} more_")
    out.append("")
    return out


def run() -> list[FileResult]:
    results: list[FileResult] = []
    for edition_id, manifest in sorted(load_manifests().items()):
        for path, source in sorted(foreign_outputs(manifest).items()):
            res = FileResult(edition_id, path, source)
            spec = SPEC.get(path)
            if spec is None:
                res.verdict = "not comparable without a mapping"
                res.notes.append("no own-edition source table is declared for this output")
                results.append(res)
                continue
            resolved = {
                "tables": spec.get("tables", {}).get(edition_id, []),
                "sections": spec.get("sections", {}).get(edition_id, []),
            }
            if not resolved["tables"] and not resolved["sections"]:
                res.verdict = "no edition table"
                results.append(res)
                continue
            COMPARATORS[path](res, resolved)
            res.settle()
            results.append(res)
    # necb2025 efficiencies.json is mcp:necb:2025 for its EQUIPMENT tables, so
    # foreign_outputs() does not flag it -- but its curves are inherited, and
    # the plan's matrix carries it. Add it explicitly, curves only.
    for edition_id, manifest in sorted(load_manifests().items()):
        if any(r.edition_id == edition_id and r.path == "efficiencies.json"
               for r in results):
            continue
        entry = manifest.get("provenance", {}).get("efficiencies.json", {})
        res = FileResult(edition_id, "efficiencies.json", entry.get("source", ""))
        compare_efficiencies(res, SPEC["efficiencies.json"]["tables"].get(edition_id, []),
                             SPEC["efficiencies.json"]["sections"].get(edition_id, []))
        res.settle()
        results.append(res)
    results.sort(key=lambda r: (r.edition_id, r.path))
    return results


CURVE_VERDICTS = [
    ("chiller `EIR_FPLR` \u00d74 (water-cooled)", "8.4.5.5.-B / 8.4.6.5.-B",
     "identical to rounding",
     "the shipped coefficients carry 6 decimal places, the edition table 8; "
     "every term agrees on the digits both publish"),
    ("chiller `CAP_FT` \u00d74, `EIR_FT` \u00d74", "8.4.5.5.-A / -C, 8.4.6.5.-A / -C",
     "differs outright",
     "the shipped surfaces are EnergyPlus BiQuadratic curves in \u00b0C; the edition "
     "table's coefficients are the same curve family stated on a DIFFERENT "
     "independent-variable basis \u2014 see the surface evaluation below"),
    ("boiler non-condensing / condensing, furnace atmospheric / condensing",
     "8.4.5.2.-A, 8.4.5.3 / 8.4.6.2, 8.4.6.3", "differs",
     "the edition defines FHeatPLC = a + b\u00b7PLR + c\u00b7PLR\u00b2 (a fuel RATIO); the "
     "shipped curve is a cubic FIR(PLR) the oracle converted from NECB 2011. "
     "The shipped cubic APPROXIMATES the edition's quadratic within 1.9 % / "
     "0.5 % / 1.0 % / 0.5 % \u2014 close, not exact"),
    ("2025 boiler `Modulating` row; 2025 condensing boiler (6 coefficients)",
     "8.4.6.2", "no inherited curve",
     "new in this edition; nothing shipped corresponds"),
    ("absorption chillers", "8.4.5.8 / 8.4.6.8", "no inherited curve",
     "the edition publishes CAP_FTAC / FIR_FPLR / FIR_FT for absorption "
     "machines; the engine does not model them"),
    ("DX cooling / heating \u00d710, VAV fan \u00d74, SWH \u00d71", "\u2014",
     "no edition table",
     "neither edition publishes a table for these; the NECB 2011 origin is "
     "legitimately retained and must be stated as such in provenance"),
]


def render(results: list[FileResult], surface: dict) -> str:
    out: list[str] = []
    out.append("# NECB vintage match — inherited content vs the edition's own tables")
    out.append("")
    out.append(
        "Generated by `python3 python/scripts/generate_necb_vintage_match.py`. "
        "Do not hand-edit.")
    out.append("")
    out.append(
        "Each edition snapshot under `python/btap/codes/necb/data/necb<edition>/` "
        "is meant to carry that edition's own normative content. Several "
        "manifest-declared outputs do not yet: they were inherited from the "
        "pinned legacy oracle (whose lineage runs NECB 2011 ← 2015 ← 2017 ← "
        "2020) or copied from the other edition's MCP retrieval. This document "
        "is the **read-only verification pass** that asks, per file, whether "
        "the content shipped equals what the edition actually publishes.")
    out.append("")
    out.append(
        "The comparison runs offline against payloads retrieved from the "
        "building-codes MCP and retained beside each snapshot at "
        "`necb<edition>/provenance/vintage_match/<table>.result.json`. "
        "**No product data value changes here.** A `differs` verdict is a "
        "finding for the D-89 adjudication, never a fix applied in passing.")
    out.append("")

    out.append("## Matrix")
    out.append("")
    out.append(
        "The rows are derived from the manifests, not listed by hand: an output "
        "appears here when its `provenance` entry's `source` is neither "
        "`mcp:necb:<this edition>` nor a `self:` declaration — 7 in `necb2020` "
        "and 8 in `necb2025`. `necb2025`'s `efficiencies.json` is added "
        "explicitly: its EQUIPMENT tables are this edition's own retrieval, but "
        "its performance CURVES are inherited, and only those are compared.")
    out.append("")
    out.append(
        "**The verdict column is coarse on purpose.** `differs` means \"not "
        "byte-for-byte what this edition publishes\" and says nothing about the "
        "SIZE of the difference — which is what an adoption decision turns on. "
        "Read the counts and the differing leaves below before treating a row "
        "as a numeric change.")
    out.append("")
    out.append("| edition | file | recorded source | edition's own tables | verdict |")
    out.append("|---|---|---|---|---|")
    for res in results:
        tables = ", ".join(f"`{t}`" for t in res.tables) or "—"
        if len(tables) > 90:
            tables = ", ".join(f"`{t}`" for t in res.tables[:4]) + \
                f", … ({len(res.tables)} total)"
        out.append(f"| `{res.edition_id}` | `{res.path}` | `{res.source}` | "
                   f"{tables} | **{res.verdict}** |")
    out.append("")
    counts: dict[str, int] = {}
    for res in results:
        counts[res.verdict] = counts.get(res.verdict, 0) + 1
    out.append("Totals: " + ", ".join(
        f"**{counts[v]}** {v}" for v in sorted(counts, key=lambda v: VERDICT_ORDER[v])) + ".")
    out.append("")

    out.append("## Per file")
    out.append("")
    for res in results:
        out.append(f"### `{res.edition_id}` — `{res.path}`")
        out.append("")
        out.append(f"- **Verdict:** {res.verdict}")
        out.append(f"- **Recorded source:** `{res.source}`")
        out.append("- **Edition tables fetched:** " +
                   (", ".join(f"`{t}`" for t in res.tables) or "_none_"))
        if res.missing_tables:
            out.append("- **Spec'd but NOT archived:** " +
                       ", ".join(f"`{t}`" for t in res.missing_tables))
        if res.mapping:
            out.append(f"- **Mapping:** {res.mapping}")
        out.append("")
        if res.counts:
            out.append("| count | value |")
            out.append("|---|---:|")
            for key, value in res.counts.items():
                out.append(f"| {key} | {value} |")
            out.append("")
        for note in res.notes:
            out.append(f"> {note}")
            out.append("")
        if res.differences:
            # A "row . column" leaf groups usefully by column; a leaf that is
            # already one whole thing (a curve, a rule key) does not.
            groups: dict[str, int] = {}
            keyed = [leaf for leaf, _, _ in res.differences if " . " in leaf]
            for leaf in keyed:
                label = leaf.split(" . ")[-1]
                groups[label] = groups.get(label, 0) + 1
            if len(keyed) == len(res.differences) and len(groups) < len(keyed):
                out.append("Differing leaves by kind:")
                out.append("")
                for label, n in sorted(groups.items(), key=lambda kv: (-kv[1], kv[0])):
                    out.append(f"- `{label}` — {n}")
                out.append("")
            out.append(f"<details><summary>Every differing leaf "
                       f"({len(res.differences)})</summary>")
            out.append("")
            out.append("| leaf | shipped | this edition |")
            out.append("|---|---|---|")
            for leaf, shipped_value, edition_value in res.differences[:400]:
                out.append(f"| `{leaf}` | {shipped_value} | {edition_value} |")
            if len(res.differences) > 400:
                out.append(f"| _… and {len(res.differences) - 400} more_ | | |")
            out.append("")
            out.append("</details>")
            out.append("")
        for title, items in (("Shipped rows with no edition counterpart",
                              res.unmatched_shipped),
                             ("Edition rows with no shipped counterpart",
                              res.unmatched_edition),
                             ("Shipped columns with NO edition source at all",
                              res.no_source_columns)):
            block = _listing(title, items)
            if block:
                out.append(f"<details><summary>{title} ({len(items)})</summary>")
                out.append("")
                out.extend(block[2:])
                out.append("</details>")
                out.append("")

    out.append("## Performance curves")
    out.append("")
    out.append(
        "`efficiencies.json` carries 31 curves and `shw_rules.json` one more, "
        "every one of them the oracle's NECB 2011 set. Both editions publish "
        "their own curve tables (2020: 8.4.5.2 / .3 / .5 / .8; 2025: 8.4.6.2 / "
        ".3 / .5 / .8), and all 17 are archived here. Coefficients are NOT "
        "compared naively: each class is compared in the independent variables "
        "its own source declares, which is what makes \"same surface, different "
        "units\" a decidable question rather than a guess.")
    out.append("")
    for res in results:
        if not res.curves:
            continue
        out.append(f"### `{res.edition_id}` curves")
        out.append("")
        out.append("| curve | edition table | relation | verdict | detail |")
        out.append("|---|---|---|---|---|")
        for rec in res.curves:
            name = f"`{rec['name']}`" if rec["name"] else "_(none shipped)_"
            out.append(
                f"| {name}<br/>{rec['label']} | `{rec['table']}` | "
                f"{rec['relation']} | **{rec['verdict']}** | {rec['detail']} |")
        out.append("")
        tally: dict[str, int] = {}
        for rec in res.curves:
            tally[rec["verdict"]] = tally.get(rec["verdict"], 0) + 1
        out.append("Tally: " + ", ".join(f"**{n}** {v}" for v, n in sorted(tally.items()))
                   + ".")
        out.append("")

    out.append("### The chiller `CAP_FT` / `EIR_FT` surfaces — same curve, different basis?")
    out.append("")
    out.extend(surface["prose"])
    out.append("")
    if surface["rows"]:
        out.append("| curve | point (t_chws / t_cws) | shipped surface (°C basis) | "
                   "edition surface (°F basis) | ratio |")
        out.append("|---|---|---:|---:|---:|")
        for row in surface["rows"]:
            out.append("| {name} | {point} | {a} | {b} | {ratio} |".format(**row))
        out.append("")
    out.append(surface["conclusion"])
    out.append("")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# The chiller surface evaluation — the DF-2 question, settled
# --------------------------------------------------------------------------
def evaluate_chiller_surfaces() -> dict:
    """Evaluate the shipped and the edition CAP_FT / EIR_FT surfaces at matched
    physical temperatures, each in the independent variables its own source
    declares, and say whether they are one surface or two."""
    records = [r for r in curve_records("necb2020")
               if r["klass"] in {"CAPFT", "EIRFT"} and r["points"]]
    rows: list[dict] = []
    ratios: list[float] = []
    for rec in records:
        for point, a, b, ratio in rec["points"]:
            ratios.append(ratio)
            rows.append({
                "name": f"`{rec['name']}`",
                "point": point,
                "a": f"{a:.6f}",
                "b": f"{b:.6f}",
                "ratio": f"{ratio:.6f}",
            })
    errata_rows = [r for r in records if r["errata"]]
    prose = [
        "DF-2 could not tell from the coefficients alone whether the shipped "
        "chiller `CAP_FT` / `EIR_FT` surfaces and the edition's are the same "
        "surface stated in different units or genuinely different curves — the "
        "scroll `CAP_FT` constant term is 0.944 in the snapshot and 0.361 in "
        "the table. The archived article text settles the basis: Sentences "
        "8.4.5.5.(3) and (7) (2025: 8.4.6.5) define `CAP_FTEC` and `EIR_FT` "
        "over **t_chws and t_cws in °F**, while the shipped curves are "
        "EnergyPlus `Curve:Biquadratic` objects in **°C** whose own `notes` say "
        "\"Converted coefficients for deg. F to deg. C\". A biquadratic under "
        "the affine substitution t_F = 1.8 t_C + 32 has closed-form transformed "
        "coefficients, so the two can be compared exactly, and then evaluated "
        "at matched physical operating points: one surface gives a ratio of "
        "1.000000 everywhere.",
    ]
    if errata_rows:
        prose.append("")
        prose.append(
            "Two rows needed the codes service's own published errata first. "
            "Its archived `known_issue` block on Table 8.4.5.5.-C / 8.4.6.5.-C "
            "records that three printed `EIR_FT` rows fail the AHRI 550/590 "
            "rating-point normalisation (`EIR_FT` must equal 1.0 at 44 °F CHW / "
            "85 °F condenser water) and gives the suspected correct values — a "
            "decimal-place slip in the printed Code, identical in 2020 and "
            "2025. The comparison below applies exactly those archived "
            "corrections, and only where the payload declares one: " +
            "; ".join(f"{r['label']} ({', '.join(r['errata'])})"
                      for r in errata_rows) + ".")
    if not rows:
        prose.append(
            "**The evaluation could not be completed mechanically:** no "
            "archived edition row aligned to a shipped curve. The coefficients "
            "are archived verbatim; the alignment is a D-89 question.")
        return {"prose": prose, "rows": [],
                "conclusion": "**Conclusion: unresolved mechanically — see above.**"}
    worst = max(abs(r - 1.0) for r in ratios)
    deviations = [r["deviation"] for r in records if r["deviation"] is not None]
    if worst < 1e-4:
        conclusion = (
            "**Conclusion: the same surface in different units.** Evaluated on "
            "its own °F basis, this edition's table reproduces the shipped °C "
            f"surface at every one of the {len(rows)} matched operating points "
            f"(worst ratio departure from 1.000000 is {worst:.1e}), and the "
            "closed-form °F→°C transform of the edition coefficients matches "
            f"the shipped coefficients to {max(deviations):.1e} relative — pure "
            "rounding at the 6 significant figures the snapshot publishes. The "
            "coefficient difference DF-2 saw is a unit-basis restatement, **not "
            "a physics change**. Adopting the edition's own numbers for these "
            "eight curves is therefore an output-identical provenance change, "
            "not an R-O numeric one — with the single caveat that the two "
            "errata rows must be adopted in their CORRECTED form, since the "
            "printed Code values fail their own rating-point normalisation.")
    else:
        conclusion = (
            "**Conclusion: genuinely different surfaces.** The ratio between "
            f"the two ranges from {min(ratios):.6f} to {max(ratios):.6f} across "
            "the matched operating points, so no change of units reconciles "
            "them. Adopting the edition's coefficients is a physics change and "
            "belongs to D-89 with the R-O re-freeze.")
    return {"prose": prose, "rows": rows, "conclusion": conclusion}


def generate(output: Path = DEFAULT_OUTPUT) -> list[FileResult]:
    results = run()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(results, evaluate_chiller_surfaces()), encoding="utf-8")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--fetch", action="store_true",
                        help="maintainer MCP operation: archive any missing payload")
    parser.add_argument("--only", help="with --fetch, restrict to one declared output path")
    parser.add_argument("--check", action="store_true",
                        help="regenerate to a temp file and fail if it differs from --output")
    args = parser.parse_args(argv)

    if args.fetch:
        return fetch(args.only)

    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        with tempfile.TemporaryDirectory() as tmp:
            fresh_path = Path(tmp) / args.output.name
            results = generate(fresh_path)
            fresh = fresh_path.read_text(encoding="utf-8")
        if fresh == current:
            print(f"{args.output.name}: up to date — {len(results)} file(s) compared")
            return 0
        print(f"{args.output.name}: STALE - run "
              "python3 python/scripts/generate_necb_vintage_match.py")
        return 1

    results = generate(args.output)
    by_verdict: dict[str, int] = {}
    for res in results:
        by_verdict[res.verdict] = by_verdict.get(res.verdict, 0) + 1
    summary = ", ".join(f"{n} {v}" for v, n in sorted(by_verdict.items()))
    print(f"wrote {args.output.name} — {len(results)} file(s): {summary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
