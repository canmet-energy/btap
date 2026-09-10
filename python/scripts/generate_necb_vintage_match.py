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

``--fetch`` skips a payload that is already archived; add ``--refresh`` to
re-retrieve and overwrite one. ``--fetch`` is the ONLY path that imports
``btap._mcp``; generation and ``--check`` are stdlib-only and never touch the
network.

Generation and ``--check`` both begin with a COMPLETENESS gate: every payload
the matrix declares must exist. A missing payload is a failure, never a line of
prose — with the payload absent the comparison it drives silently does not
happen while its file still reports a verdict.

Nothing here edits product data. A verdict of ``differs`` is a FINDING for the
D-89 adjudication, never a fix applied in passing.
"""

from __future__ import annotations

import argparse
import difflib
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
# table numbers in THAT edition's numbering. An entry stays here after its
# file is adopted -- the mapping is what the adoption was checked against, and
# ``--fetch`` still keeps the payload current -- but an edition that now ships
# the file from its own text no longer appears in ``foreign_outputs`` and so is
# not re-compared. ``tables/daylighting_controls_4_2_1_6.json`` is in that
# state for both editions since the Phase B step 2 re-source.
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
# Loose numeric probing — SHW rule leaves ONLY
#
# ``shw_rules.json``'s consumed leaves are scalar constants scattered through a
# single small table with no row structure to join on, so "does this number
# appear in this edition's Table 6.2.2.1 at all" is the honest question there.
# It is NOT the question for equipment minima: a scan that accepts any nearby
# number under any unit conversion preserves no equipment class, no table, no
# row, no capacity band and no metric, and so cannot support a claim about the
# shipped efficiency tables. Those go through the explicit per-family
# row-and-column mapping below instead.
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
# Equipment minima: an EXPLICIT per-family row-and-column mapping
#
# Every shipped efficiency family names, per edition, the table it comes from,
# the row that governs each of its rows (equipment class + capacity band, with
# the band bounds converted out of the engine's units), and the column and
# METRIC the value is supposed to be. Nothing is inferred from proximity: a
# shipped number is compared against one identified cell or it is reported as
# having no mapping. A family with no faithful mapping is declared UNMAPPED and
# never counted as agreeing with anything.
# --------------------------------------------------------------------------

#: Subscripted metric letters as the codes service serves them.
_SUBSCRIPT_LETTERS = {"ₕ": "h", "ₜ": "t", "ᵥ": "v", "ₑ": "e",
                      "ₓ": "x", "ₐ": "a", "ₘ": "m", "ᶜ": "c"}

#: The metric tokens the 5.2.12.x series prints, LONGEST FIRST so that `IEER`
#: is never read as `EER` nor `HSPF V` as `HSPF`.
METRIC_TOKENS = ("ISMRE", "ISCOP", "HSPF V", "HSPF", "SCOP", "IEER", "CEER",
                 "SEER", "IPLV", "AFUE", "COPc", "COPh", "COP", "EER", "FER",
                 "NRE", "Et", "Ec", "FE")

_METRIC_RE = re.compile(
    r"(?P<token>" + "|".join(re.escape(t) for t in METRIC_TOKENS) + r")"
    r"\s*(?:=|≥|>=|≤|<=)\s*"
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<pct>%)?"
    r"(?P<tail>[^A-Z]*)")

#: `EER = 14.1 - (1.0435 × Capkw)` — the PTAC/PTHP sliding minimum. The slope is
#: per kW of capacity; the snapshot stores it per kBtu/h.
_SLOPE_RE = re.compile(r"-\s*\(?\s*(\d+(?:\.\d+)?)\s*[×x*]")


def _desubscript(text: str) -> str:
    return "".join(_SUBSCRIPT_LETTERS.get(c, c) for c in str(text or ""))


def norm_qualifier(text) -> str:
    """Lower-cased and whitespace-collapsed, but SIGNS AND DECIMAL POINTS KEPT.

    Table 5.2.12.1.-A's heating-mode rows are told apart only by `at 8.3°C`
    versus `at -8.3°C`; :func:`norm_name` folds both to the same key, so a
    qualifier must not go through it.
    """
    s = unicodedata.normalize("NFKD", _desubscript(text))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return _WS.sub(" ", s.replace("−", "-").lower()).strip()


def parse_metrics(cell) -> list[dict]:
    """Every `TOKEN = value` a performance cell prints, in printed order.

    ``qualifier`` is the text that follows the value up to the next token — the
    `(water)` / `(steam)` of a boiler row, the `evaluated at 8.3°C db` of a VRF
    heat-pump row — kept so a column mapping can name which of two same-token
    values it means.
    """
    text = _desubscript(cell).replace("\n", " ")
    out = []
    for match in _METRIC_RE.finditer(text):
        tail = match.group("tail") or ""
        slope = _SLOPE_RE.search(tail)
        out.append({
            "token": match.group("token"),
            "value": float(match.group("value")),
            "percent": bool(match.group("pct")),
            "qualifier": norm_qualifier(tail),
            "slope": float(slope.group(1)) if slope else None,
        })
    return out


_BAND_TOKEN = re.compile(r"(?P<op>≥|>=|≤|<=|<|>)\s*"
                         r"(?P<value>\d[\d    ]*(?:\.\d+)?)")


def parse_band(text) -> tuple[float | None, float | None] | None:
    """A printed capacity band as ``(lo, hi)`` in kW; ``None`` means open.

    ``All capacities`` is ``(None, None)``. The bound the operator excludes is
    still the bound: `< 19` and `≤ 19` both close at 19 for the purpose of
    lining a band up with a converted engine bin, whose bounds are rounded
    anyway (65 000 Btu/h is 19.05 kW, not 19).
    """
    raw = str(text or "")
    if not raw.strip():
        return None
    if "all capacit" in raw.lower():
        return (None, None)
    lo = hi = None
    found = False
    for match in _BAND_TOKEN.finditer(raw):
        found = True
        value = float(re.sub(r"[    ]", "", match.group("value")))
        if match.group("op") in ("≥", ">=", ">"):
            lo = value
        else:
            hi = value
    return (lo, hi) if found else None


#: Engine values that close a bin the Code writes with no upper bound at all.
CAPACITY_SENTINELS = (9999.0, 9999999.0, 9.999999999e9, 999999999.0)

CAPACITY_UNITS = {
    "btu_per_h": (lambda v: v / BTU_PER_H_PER_KW, "Btu/h → kW"),
    "ton": (lambda v: v * KW_PER_TON, "tons → kW"),
    "kw": (lambda v: v, "kW (as published)"),
}

#: How a shipped value relates to the metric the Code prints.
METRIC_TRANSFORMS = {
    "identity": (lambda printed, _: printed, "as published"),
    "percent_to_fraction": (lambda printed, _: printed / 100.0, "% → fraction"),
    "cop_to_kw_per_ton": (lambda printed, _: KW_PER_TON / printed
                          if printed else None, "COP → kW/ton"),
    "slope_per_kw_to_per_kbtu_per_h":
        (lambda printed, m: (m["slope"] / (BTU_PER_H_PER_KW / 1000.0))
         if m.get("slope") is not None else None, "per kW → per kBtu/h"),
}

#: Bands are compared after a unit conversion whose inputs are rounded engine
#: numbers (65 000 Btu/h for the Code's 19 kW is 0.26 % high), so a bound counts
#: as the same bound within 2 %.
BAND_TOL = 0.02

EQUIPMENT_BLOCKS: dict[str, list[dict]] = {
    "necb2020": [
        # ---- unitary air conditioners ------------------------------------
        {
            "family": "unitary_acs",
            "block": "air-cooled unitary air conditioners < 19 kW (seasonal)",
            "when": {"equipment_type": ("Air Conditioners",),
                     "cooling_type": ("AirCooled",)},
            "requires": ("minimum_seasonal_energy_efficiency_ratio",),
            "capacity_unit": "btu_per_h",
            "table": "5.2.12.1.-A",
            "row_column": "Equipment Category",
            "row_name": "Small air conditioners and heat pumps",
            "qualifier": {"column": "Equipment Subcategory", "from": "subcategory",
                          "map": {"Single Package": "single-package, others",
                                  "Split System": "split system, others"}},
            "columns": {
                "minimum_seasonal_energy_efficiency_ratio":
                    {"metric": "SEER", "column": "Minimum Performance",
                     "transform": "identity"},
            },
        },
        {
            "family": "unitary_acs",
            "block": "air-cooled unitary air conditioners ≥ 19 kW (full load)",
            "when": {"equipment_type": ("Air Conditioners",),
                     "cooling_type": ("AirCooled",)},
            "requires": ("minimum_energy_efficiency_ratio",),
            "capacity_unit": "btu_per_h",
            "table": "5.2.12.1.-A",
            "row_column": "Equipment Category",
            "row_name": ("Large air conditioners and heat pumps, split and "
                         "single-package, all electrical phases, in cooling mode"),
            "qualifier": {
                "column": "Rating Conditions", "from": "heating_type",
                "map": {"Electric Resistance or None":
                        "electric resistance heating section or no heating section",
                        "All Other": "other types of heating sections"}},
            "columns": {
                "minimum_energy_efficiency_ratio":
                    {"metric": "EER", "column": "Minimum Performance",
                     "transform": "identity"},
                "minimum_integrated_energy_efficiency_ratio":
                    {"metric": "IEER", "column": "Minimum Performance",
                     "transform": "identity"},
            },
        },
        {
            "family": "unitary_acs",
            "block": "packaged terminal air conditioners (PTAC), cooling mode",
            "when": {"equipment_type": ("PTAC",)},
            "capacity_unit": "btu_per_h",
            "table": "5.2.12.1.-G",
            "row_column": "Equipment Category",
            "row_name": ("PTAC and PTHP in cooling mode, standard and "
                         "non-standard sizes"),
            "columns": {
                "ptac_eer_coefficient_1":
                    {"metric": "EER", "column": "Minimum Performance",
                     "transform": "identity"},
                "ptac_eer_coefficient_2":
                    {"metric": "EER", "column": "Minimum Performance",
                     "transform": "slope_per_kw_to_per_kbtu_per_h",
                     "zero_when_no_slope": True},
            },
        },
        # ---- heat pumps, cooling mode -------------------------------------
        {
            "family": "heat_pumps",
            "block": "air-cooled heat pumps < 19 kW, cooling mode (seasonal)",
            "when": {"equipment_type": ("Heat Pumps",),
                     "cooling_type": ("AirCooled",)},
            "requires": ("minimum_seasonal_efficiency",),
            "capacity_unit": "btu_per_h",
            "table": "5.2.12.1.-A",
            "row_column": "Equipment Category",
            "row_name": "Small air conditioners and heat pumps",
            "qualifier": {"column": "Equipment Subcategory", "from": "subcategory",
                          "map": {"Single Package": "single-package, others",
                                  "Split System": "split system, others"}},
            "columns": {
                "minimum_seasonal_efficiency":
                    {"metric": "SEER", "column": "Minimum Performance",
                     "transform": "identity"},
            },
        },
        {
            "family": "heat_pumps",
            "block": "air-cooled heat pumps ≥ 19 kW, cooling mode (full load)",
            "when": {"equipment_type": ("Heat Pumps",),
                     "cooling_type": ("AirCooled",)},
            "requires": ("minimum_full_load_efficiency",),
            "capacity_unit": "btu_per_h",
            "table": "5.2.12.1.-A",
            "row_column": "Equipment Category",
            "row_name": ("Large air conditioners and heat pumps, split and "
                         "single-package, all electrical phases, in cooling mode"),
            "qualifier": {
                "column": "Rating Conditions", "from": "heating_type",
                "map": {"Electric Resistance or None":
                        "electric resistance heating section or no heating section",
                        "All Other": "other types of heating sections"}},
            "columns": {
                "minimum_full_load_efficiency":
                    {"metric": "EER", "column": "Minimum Performance",
                     "transform": "identity"},
                "minimum_integrated_energy_efficiency_ratio":
                    {"metric": "IEER", "column": "Minimum Performance",
                     "transform": "identity"},
            },
        },
        # ---- heat pumps, heating mode -------------------------------------
        {
            "family": "heat_pumps_heating",
            "block": "air-cooled heat pumps < 19 kW, heating mode (seasonal)",
            "when": {"equipment_type": ("Heat Pumps",),
                     "cooling_type": ("AirCooled",)},
            "requires": ("minimum_heating_seasonal_performance_factor",),
            "capacity_unit": "btu_per_h",
            "table": "5.2.12.1.-A",
            "row_column": "Equipment Category",
            "row_name": "Small air conditioners and heat pumps",
            "qualifier": {"column": "Equipment Subcategory", "from": "subcategory",
                          "map": {"Single Package": "single-package, others",
                                  "Split System": "split system, others"}},
            "columns": {
                "minimum_heating_seasonal_performance_factor":
                    {"metric": "HSPF V", "column": "Minimum Performance",
                     "transform": "identity"},
            },
            "note": ("the shipped rows' own `notes` cite Table 5.2.12.1.-B "
                     "(single-package VERTICAL units); the HSPF V = 7.4 they "
                     "carry is Table 5.2.12.1.-A's small air-cooled row, which "
                     "is the table mapped here — a provenance-note error, "
                     "reported, not fixed"),
        },
        {
            "family": "heat_pumps_heating",
            "block": "air-cooled heat pumps ≥ 19 kW, heating mode (COP at 8.3 °C)",
            "when": {"equipment_type": ("Heat Pumps",),
                     "cooling_type": ("AirCooled",)},
            "requires": ("minimum_coefficient_of_performance_heating",),
            "capacity_unit": "btu_per_h",
            "table": "5.2.12.1.-A",
            "row_column": "Equipment Category",
            "row_name": ("Large heat pumps, split and single-package, all "
                         "electrical phases, in heating mode"),
            "qualifier": {"column": "Rating Conditions", "fixed": ("at 8.3°c",)},
            "columns": {
                "minimum_coefficient_of_performance_heating":
                    {"metric": "COPh", "column": "Minimum Performance",
                     "transform": "identity"},
            },
        },
        # ---- chillers ------------------------------------------------------
        {
            "family": "chillers",
            "block": "water-cooled positive-displacement chillers, Path B",
            "when": {"cooling_type": ("WaterCooled",),
                     "compressor_type": ("Scroll", "Reciprocating", "Rotary Screw")},
            "capacity_unit": "ton",
            "table": "5.2.12.1.-K",
            "row_column": "Type of Equipment",
            "row_name": "Water-cooled, rotary screw, scroll, or reciprocating compressor",
            "columns": {
                "minimum_full_load_efficiency":
                    {"metric": "COPc", "column": "Minimum Performance Path B",
                     "transform": "cop_to_kw_per_ton"},
                "minimum_integrated_part_load_value":
                    {"metric": "IPLV", "column": "Minimum Performance Path B",
                     "transform": "cop_to_kw_per_ton"},
            },
        },
        {
            "family": "chillers",
            "block": "water-cooled centrifugal chillers, Path B",
            "when": {"cooling_type": ("WaterCooled",),
                     "compressor_type": ("Centrifugal",)},
            "capacity_unit": "ton",
            "table": "5.2.12.1.-K",
            "row_column": "Type of Equipment",
            "row_name": "Water-cooled, centrifugal compressor",
            "columns": {
                "minimum_full_load_efficiency":
                    {"metric": "COPc", "column": "Minimum Performance Path B",
                     "transform": "cop_to_kw_per_ton"},
                "minimum_integrated_part_load_value":
                    {"metric": "IPLV", "column": "Minimum Performance Path B",
                     "transform": "cop_to_kw_per_ton"},
            },
        },
        {
            "family": "chillers",
            "block": "air-cooled chillers, Path B",
            "when": {"cooling_type": ("AirCooled",)},
            "capacity_unit": "ton",
            "table": "5.2.12.1.-K",
            "row_column": "Type of Equipment",
            "row_name": ("Air-cooled, with or without remote condensers, all "
                         "types of compressors"),
            "columns": {
                "minimum_full_load_efficiency":
                    {"metric": "COPc", "column": "Minimum Performance Path B",
                     "transform": "cop_to_kw_per_ton"},
                "minimum_integrated_part_load_value":
                    {"metric": "IPLV", "column": "Minimum Performance Path B",
                     "transform": "cop_to_kw_per_ton"},
            },
        },
        # ---- boilers -------------------------------------------------------
        {
            "family": "boilers",
            "block": "gas-fired hot-water boilers",
            "when": {"fuel_type": ("Gas",), "fluid_type": ("Hot Water",)},
            "capacity_unit": "btu_per_h",
            "table": "5.2.12.1.-N",
            "row_column": "Equipment Category",
            "row_name": "Gas-fired",
            "columns": {
                "minimum_annual_fuel_utilization_efficiency":
                    {"metric": "AFUE", "column": "Minimum Performance",
                     "transform": "percent_to_fraction", "metric_qualifier": "(water)"},
                "minimum_thermal_efficiency":
                    {"metric": "Et", "column": "Minimum Performance",
                     "transform": "percent_to_fraction", "metric_qualifier": "(water)"},
                "minimum_combustion_efficiency":
                    {"metric": "Ec", "column": "Minimum Performance",
                     "transform": "percent_to_fraction", "metric_qualifier": "(water)"},
            },
        },
        {
            "family": "boilers",
            "block": "oil-fired hot-water boilers",
            "when": {"fuel_type": ("Oil",), "fluid_type": ("Hot Water",)},
            "capacity_unit": "btu_per_h",
            "table": "5.2.12.1.-N",
            "row_column": "Equipment Category",
            "row_name": "Oil-fired",
            "columns": {
                "minimum_annual_fuel_utilization_efficiency":
                    {"metric": "AFUE", "column": "Minimum Performance",
                     "transform": "percent_to_fraction", "metric_qualifier": "(water)"},
                "minimum_thermal_efficiency":
                    {"metric": "Et", "column": "Minimum Performance",
                     "transform": "percent_to_fraction", "metric_qualifier": "(water)"},
                "minimum_combustion_efficiency":
                    {"metric": "Ec", "column": "Minimum Performance",
                     "transform": "percent_to_fraction", "metric_qualifier": "(water)"},
            },
        },
        {
            "family": "boilers",
            "block": "electric hot-water boilers",
            "when": {"fuel_type": ("Electric",), "fluid_type": ("Hot Water",)},
            "capacity_unit": "btu_per_h",
            "table": "5.2.12.1.-N",
            "row_column": "Equipment Category",
            "row_name": "Electric",
            "columns": {
                "minimum_thermal_efficiency":
                    {"metric": "Et", "column": "Minimum Performance",
                     "transform": "percent_to_fraction"},
            },
        },
        # ---- furnaces ------------------------------------------------------
        {
            "family": "furnaces",
            "block": "gas-fired warm-air furnaces",
            "when": {"fuel_type": ("Gas",), "fluid_type": ("Air",)},
            "capacity_unit": "btu_per_h",
            "table": "5.2.12.1.-O",
            "row_column": "Type of Equipment",
            "row_name": "Gas-fired warm-air furnaces",
            "qualifier": {"column": "Rating Conditions",
                          "fixed": ("without integrated cooling", "see standard")},
            "columns": {
                "minimum_annual_fuel_utilization_efficiency":
                    {"metric": "AFUE", "column": "Minimum Performance",
                     "transform": "percent_to_fraction"},
                "minimum_thermal_efficiency":
                    {"metric": "Et", "column": "Minimum Performance",
                     "transform": "percent_to_fraction"},
            },
        },
        # ---- variable refrigerant flow -------------------------------------
        {
            "family": "vrf_air_conditioners",
            "block": "VRF air-cooled air conditioners < 19 kW (seasonal)",
            "when": {},
            "requires": ("minimum_seer",),
            "capacity_unit": "kw",
            "capacity_keys": ("minimum_capacity_kw", "maximum_capacity_kw"),
            "table": "5.2.12.1.-I",
            "row_column": "Equipment Type",
            "row_name": ("Air-cooled air conditioners and heat pumps, with or "
                         "without heat recovery"),
            "columns": {
                "minimum_seer": {"metric": "SEER", "column": "Minimum Performance",
                                 "transform": "identity"},
            },
        },
        {
            "family": "vrf_air_conditioners",
            "block": "VRF air-cooled air conditioners ≥ 19 kW (full load)",
            "when": {},
            "requires": ("minimum_eer",),
            "capacity_unit": "kw",
            "capacity_keys": ("minimum_capacity_kw", "maximum_capacity_kw"),
            "table": "5.2.12.1.-I",
            "row_column": "Equipment Type",
            "row_name": "Air-cooled air conditioners",
            "columns": {
                "minimum_eer": {"metric": "EER", "column": "Minimum Performance",
                                "transform": "identity"},
            },
        },
        {
            "family": "vrf_air_source_heat_pumps",
            "block": "VRF air-source heat pumps < 19 kW (seasonal)",
            "when": {},
            "requires": ("minimum_seer",),
            "capacity_unit": "kw",
            "capacity_keys": ("minimum_capacity_kw", "maximum_capacity_kw"),
            "table": "5.2.12.1.-I",
            "row_column": "Equipment Type",
            "row_name": ("Air-cooled air conditioners and heat pumps, with or "
                         "without heat recovery"),
            "columns": {
                "minimum_seer": {"metric": "SEER", "column": "Minimum Performance",
                                 "transform": "identity"},
                "minimum_hspf": {"metric": "HSPF V", "column": "Minimum Performance",
                                 "transform": "identity"},
            },
        },
        {
            "family": "vrf_air_source_heat_pumps",
            "block": "VRF air-source heat pumps ≥ 19 kW (EER, COP at 8.3 °C)",
            "when": {},
            "requires": ("minimum_eer",),
            "capacity_unit": "kw",
            "capacity_keys": ("minimum_capacity_kw", "maximum_capacity_kw"),
            "table": "5.2.12.1.-I",
            "row_column": "Equipment Type",
            "row_name": "Air-source heat pumps, with or without heat recovery",
            "columns": {
                "minimum_eer": {"metric": "EER", "column": "Minimum Performance",
                                "transform": "identity"},
                # Table 5.2.12.1.-I prints two COPh minima in one cell, at
                # 8.3 °C db and at -8.3 °C db. The snapshot carries the warmer
                # rating point, so the mapping names it; the sign is what tells
                # the two apart, which is why a qualifier keeps its sign.
                "minimum_heating_cop":
                    {"metric": "COPh", "column": "Minimum Performance",
                     "transform": "identity",
                     "metric_qualifier": "evaluated at 8.3"},
            },
        },
    ],
}

#: Families with no faithful mapping to this edition's own tables. Reported as
#: UNMAPPED — never as corroborated, and never counted among the agreeing cells.
UNMAPPED_FAMILIES = {
    "heat_rejection": (
        "the block's own `notes` cite ASHRAE 90.1-2004 Table 6.8.1G and its "
        "`template` column names DOE reference vintages; its "
        "`minimum_performance` is an ASHRAE gpm-per-hp figure, while this "
        "edition's Table 5.2.12.2 publishes a fan-power RATIO (electrical kW "
        "per thermal kW, e.g. ≤ 0.013 for a propeller-fan open tower). Two "
        "different quantities on two different bases: there is no row-and-column "
        "mapping to make, and the block is vestigial — the runtime applies the "
        "0.013 ratio separately"),
}

#: Metric-bearing keys a family carries that no block declares are listed rather
#: than silently ignored; these engine bookkeeping keys are not metrics at all.
NON_METRIC_KEYS = {
    "start_date", "end_date", "notes", "equipment_type", "cooling_type",
    "heating_type", "subcategory", "compressor_type", "condenser_type",
    "absorption_type", "variable_speed_drive", "fluid_type", "fuel_type",
    "condensing", "condensing_control", "template", "fan_type",
    "minimum_capacity", "maximum_capacity", "minimum_capacity_kw",
    "maximum_capacity_kw", "capft", "eirft", "eirfplr", "efffplr",
    "cool_cap_ft", "cool_cap_fflow", "cool_eir_ft", "cool_eir_fflow",
    "cool_plf_fplr", "heat_cap_ft", "heat_cap_fflow", "heat_eir_ft",
    "heat_eir_fflow", "heat_plf_fplr", "condition",
}


def _capacity_bounds(row: dict, block: dict) -> tuple[float | None, float | None, str]:
    """The shipped row's band, converted into kW, with sentinels opened out."""
    lo_key, hi_key = block.get("capacity_keys", ("minimum_capacity", "maximum_capacity"))
    convert, label = CAPACITY_UNITS[block["capacity_unit"]]

    def bound(value):
        number = as_number(value)
        if number is None:
            return None
        if number in CAPACITY_SENTINELS:
            return None
        return convert(number)

    return bound(row.get(lo_key)), bound(row.get(hi_key)), label


def _bands_align(shipped: tuple, printed: tuple) -> bool:
    """Do the two bands describe the same bin, within the conversion's rounding?"""
    for a, b in zip(shipped, printed):
        if (a is None) != (b is None):
            return False
        if a is not None and abs(a - b) > BAND_TOL * max(1.0, abs(b)):
            return False
    return True


def _bands_overlap(shipped: tuple, printed: tuple) -> bool:
    lo_a, hi_a = shipped
    lo_b, hi_b = printed
    if hi_a is not None and lo_b is not None and hi_a <= lo_b * (1 + BAND_TOL):
        return False
    if hi_b is not None and lo_a is not None and hi_b <= lo_a * (1 + BAND_TOL):
        return False
    return True


def _fmt_band(band) -> str:
    lo, hi = band
    if lo is None and hi is None:
        return "all capacities"
    if lo is None:
        return f"< {hi:.4g} kW"
    if hi is None:
        return f"≥ {lo:.4g} kW"
    return f"≥ {lo:.4g} and < {hi:.4g} kW"


def _block_applies(row: dict, block: dict) -> bool:
    for key, wanted in block["when"].items():
        if row.get(key) not in wanted:
            return False
    required = block.get("requires")
    if required and not any(row.get(k) is not None for k in required):
        return False
    return True


def _pick_metric(cell, spec: dict):
    """The one metric this column mapping names, or ``None``."""
    wanted = spec["metric"]
    qualifier = spec.get("metric_qualifier")
    candidates = [m for m in parse_metrics(cell) if m["token"] == wanted]
    if qualifier:
        exact = [m for m in candidates
                 if norm_qualifier(qualifier) in m["qualifier"]]
        if exact:
            return exact[0]
        return None
    return candidates[0] if candidates else None


def compare_equipment_families(res: FileResult, tables: dict) -> dict:
    """Cell-by-cell, family by family, against the identified row and column."""
    shipped = _shipped(res.edition_id, "efficiencies.json")
    blocks = EQUIPMENT_BLOCKS.get(res.edition_id, [])
    families: dict[str, dict] = {}

    def bucket(name: str) -> dict:
        return families.setdefault(name, {
            "rows": 0, "matched": 0, "unmatched": 0, "identical": 0,
            "differing": 0, "no_edition_value": 0, "no_shipped_value": 0,
            "mappings": [], "tables": set(), "undeclared": set(),
            "unmapped_reason": None,
        })

    for family, reason in sorted(UNMAPPED_FAMILIES.items()):
        rows = shipped.get(family)
        if isinstance(rows, list):
            entry = bucket(family)
            entry["rows"] = len(rows)
            entry["unmapped_reason"] = reason

    declared_families = {b["family"] for b in blocks}
    for family in sorted(declared_families):
        rows = shipped.get(family)
        if isinstance(rows, list):
            bucket(family)["rows"] = len(rows)

    for family in sorted(shipped):
        rows = shipped.get(family)
        if family in {"curves", "provenance", "_provenance"} or not isinstance(rows, list):
            continue
        if family in UNMAPPED_FAMILIES:
            continue
        entry = bucket(family)
        entry["rows"] = len(rows)
        if family not in declared_families:
            entry["unmapped_reason"] = (
                "no block of the mapping claims this family in this edition")
            continue
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            block = next((b for b in blocks
                          if b["family"] == family and _block_applies(row, b)), None)
            declared = set()
            if block is None:
                entry["unmatched"] += 1
                res.differences.append(
                    (f"{family}[{index}]", _fmt(row.get("equipment_type")
                                                or row.get("fuel_type") or ""),
                     "no block of the mapping claims this row"))
            else:
                declared = set(block["columns"])
                entry["tables"].add(block["table"])
                _compare_one_equipment_row(res, entry, family, index, row, block,
                                           tables)
            for key, value in sorted(row.items()):
                if key in NON_METRIC_KEYS or key in declared or value is None:
                    continue
                entry["undeclared"].add(key)

    for block in blocks:
        entry = families.get(block["family"])
        if entry is None:
            continue
        line = (f"{block['block']} → Table {block['table']}, row "
                f"`{block['row_name']}` ({block['row_column']}), band in "
                f"{CAPACITY_UNITS[block['capacity_unit']][1]}, column(s) " +
                "; ".join(f"`{k}` ← {v['metric']} in `{v['column']}`"
                          f"{' [' + v['metric_qualifier'] + ']' if v.get('metric_qualifier') else ''}"
                          f" ({METRIC_TRANSFORMS[v['transform']][1]})"
                          for k, v in sorted(block["columns"].items())))
        if block.get("qualifier"):
            qualifier = block["qualifier"]
            line += (f"; row qualifier `{qualifier['column']}` from "
                     + (f"`{qualifier['from']}`" if qualifier.get("from")
                        else "the declared preference order "
                        + ", ".join(f"`{q}`" for q in qualifier["fixed"])))
        entry["mappings"].append(line)
        if block.get("note"):
            entry["mappings"].append("note: " + block["note"])
    return families


def _compare_one_equipment_row(res, entry, family, index, row, block, tables):
    table = tables.get(block["table"])
    if table is None:
        entry["unmatched"] += 1
        return
    band = _capacity_bounds(row, block)
    shipped_band, unit_label = (band[0], band[1]), band[2]
    wanted_name = norm_name(block["row_name"])
    qualifier = block.get("qualifier")
    wanted_qualifiers: tuple = ()
    if qualifier:
        if qualifier.get("fixed"):
            wanted_qualifiers = tuple(norm_qualifier(q) for q in qualifier["fixed"])
        else:
            mapped = qualifier["map"].get(row.get(qualifier["from"]))
            wanted_qualifiers = (norm_qualifier(mapped),) if mapped else ()

    def rows_for(qualifier_key):
        out = []
        for printed in table.get("rows", []):
            name = norm_name(printed.get(block["row_column"]))
            if not name.startswith(wanted_name):
                continue
            if qualifier and qualifier_key is not None:
                if qualifier_key not in norm_qualifier(printed.get(qualifier["column"])):
                    continue
            printed_band = parse_band(printed.get("Cooling or Heating Capacity, kW"))
            if printed_band is None:
                continue
            out.append((printed, printed_band))
        return out

    # A declared qualifier list is a PREFERENCE order, not a filter: Table
    # 5.2.12.1.-O prints three rating conditions for gas warm-air furnaces
    # ≤ 66 kW and only "See standard" above it, so the first qualifier that
    # yields a row for THIS band wins, not merely the first that yields a row.
    exact: list = []
    spanning: list = []
    for qualifier_key in (wanted_qualifiers or (None,)):
        candidates = rows_for(qualifier_key)
        exact = [c for c in candidates if _bands_align(shipped_band, c[1])]
        spanning = [c for c in candidates if _bands_overlap(shipped_band, c[1])]
        if exact or spanning:
            break
    hits = exact or spanning
    if not hits:
        entry["unmatched"] += 1
        res.differences.append(
            (f"{family}[{index}] {_fmt_band(shipped_band)} ({unit_label})",
             _fmt(block["row_name"]),
             f"Table {block['table']} publishes no row of this class for this "
             "capacity band"))
        return
    entry["matched"] += 1
    band_note = "" if exact else " (shipped bin spans several printed bands)"
    for own_key, spec in sorted(block["columns"].items()):
        value = as_number(row.get(own_key))
        printed_values = []
        for printed, _band in hits:
            metric = _pick_metric(printed.get(spec["column"]), spec)
            if metric is None:
                continue
            transform = METRIC_TRANSFORMS[spec["transform"]][0](metric["value"], metric)
            if transform is None and spec.get("zero_when_no_slope"):
                transform = 0.0
            if transform is not None:
                printed_values.append((transform, metric))
        if value is None:
            if printed_values:
                entry["no_shipped_value"] += 1
                res.differences.append(
                    (f"{family}[{index}] . {own_key} (Table {block['table']})",
                     "_(no shipped value)_",
                     f"`{spec['metric']} = {printed_values[0][1]['value']:g}` — "
                     "this edition publishes a minimum the snapshot does not carry"))
            continue
        if not printed_values:
            entry["no_edition_value"] += 1
            res.differences.append(
                (f"{family}[{index}] . {own_key} (Table {block['table']})",
                 _fmt(row.get(own_key)),
                 f"this edition's row prints no `{spec['metric']}` value at all"))
            continue
        if all(numbers_equal(value, expected, 2e-3)
               for expected, _m in printed_values):
            entry["identical"] += 1
        else:
            entry["differing"] += 1
            expected, metric = printed_values[0]
            res.differences.append(
                (f"{family}[{index}] . {own_key} (Table {block['table']}, "
                 f"{_fmt_band(shipped_band)}){band_note}",
                 _fmt(row.get(own_key)),
                 f"`{spec['metric']} = {metric['value']:g}"
                 f"{'%' if metric['percent'] else ''}` → "
                 f"{expected:.6g} ({METRIC_TRANSFORMS[spec['transform']][1]})"))


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
        self.families: dict[str, dict] = {}   # equipment family -> mapped counts
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


#: The shipped two-letter province code -> the province NAME this edition's
#: Table C-1 prints in its ``Province`` column. Declared rather than inferred:
#: a city name alone is NOT a key. Alma appears in both QC and NB, Princeton in
#: BC and ON, Waterloo in ON and QC, Windsor in ON and QC, so keying on the city
#: silently drops one of each pair and compares the other against whichever row
#: the dict happened to keep. ``Quebec``/``Québec`` differ between the two
#: editions' extractions and both fold to the same key after accent folding.
PROVINCE_NAMES = {
    "AB": "Alberta",
    "BC": "British Columbia",
    "MB": "Manitoba",
    "NB": "New Brunswick",
    "NF": "Newfoundland and Labrador",
    "NS": "Nova Scotia",
    "NT": "Northwest Territories",
    "NU": "Nunavut",
    "ON": "Ontario",
    "PE": "Prince Edward Island",
    "QC": "Quebec",
    "SK": "Saskatchewan",
    "YT": "Yukon",
}


def _province_key(text) -> str:
    """The comparable province key for either side's spelling.

    The shipped side prints a two-letter code, the edition side a full name;
    both reduce to the normalised full name. An unrecognised token normalises to
    itself so it shows up in the ledger instead of vanishing.
    """
    raw = str(text or "").strip()
    return norm_name(PROVINCE_NAMES.get(raw.upper(), raw))


#: How close two city names must read before the ledger offers one as the
#: other's candidate. Deliberately loose: the ledger's job is to make every
#: unmatched row a question someone can answer, and a wrong suggestion is
#: visibly wrong while a blank line says nothing.
NAME_SIMILARITY = 0.6


def _nearest(key: tuple[str, str], pool: dict[tuple[str, str], list],
             label) -> str:
    """The most plausible counterpart for an unmatched (city, province) key.

    A same-city row in another province is named first — that is the shape a
    real alias takes here. Then a name one side spells with an extra part (the
    snapshot writes "Arviat / Eskimo Point" and "Coppermine (Kugluktuk)" where
    the Code prints one of the two names), then the closest spelling in the same
    province, then the closest anywhere.
    """
    city, province = key
    same_city = sorted(p for p in pool if p[0] == city)
    if same_city:
        return f"{label(pool[same_city[0]][0])} — same city, different province"
    for scope, note in ((lambda p: p[1] == province, "same province"),
                        (lambda p: True, "another province")):
        names = [p for p in pool if scope(p)]
        contained = sorted(
            (p for p in names
             if len(p[0]) > 3 and (p[0] in city or city in p[0])),
            key=lambda p: -len(p[0]))
        if contained:
            return (f"{label(pool[contained[0]][0])} — one name contains the "
                    f"other, {note}")
        match = difflib.get_close_matches(city, [p[0] for p in names], n=1,
                                          cutoff=NAME_SIMILARITY)
        if match:
            best = next(p for p in names if p[0] == match[0])
            return f"{label(pool[best][0])} — closest spelling, {note}"
    return f"no candidate within {NAME_SIMILARITY:g} name similarity"


def compare_table_c1(res: FileResult) -> None:
    table = read_payload(res.edition_id, "get_table", "C-1")
    if table is None:
        res.missing_tables.append("C-1")
        return
    res.tables.append("C-1")
    columns, unclaimed = _resolve_columns(table["headers"], C1_COLUMNS)
    res.mapping = (
        "rows matched by (normalised city name, PROVINCE) — the city alone is "
        "not a key, because Alma, Princeton, Waterloo and Windsor each name two "
        "different places in two different provinces; the shipped two-letter "
        "code is resolved to this edition's printed province name through a "
        "declared 13-entry map. Every column this edition prints that the "
        "shipped record also carries is compared — " +
        ", ".join(f"`{k}` ← `{v}`" for k, v in sorted(columns.items())) +
        ". The shipped `lat_long` pair has no C-1 column at all and is excluded"
    )
    shipped_rows = _shipped(res.edition_id, "tables/table_c1.json")["table"]
    by_key: dict[tuple[str, str], list] = {}
    for row in shipped_rows:
        by_key.setdefault(
            (norm_name(row.get("city")), _province_key(row.get("province"))),
            []).append(row)
    edition_by_key: dict[tuple[str, str], list] = {}
    for row in table["rows"]:
        edition_by_key.setdefault(
            (norm_name(row.get("Location")), _province_key(row.get("Province"))),
            []).append(row)

    matched = identical = differing = 0
    for key in sorted(set(by_key) & set(edition_by_key)):
        ship = by_key[key][0]
        edn = edition_by_key[key][0]
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

    def ship_label(row) -> str:
        return f"{row.get('city')} ({row.get('province')})"

    def edn_label(row) -> str:
        return f"{row.get('Location')} ({row.get('Province')})"

    res.unmatched_shipped = sorted(
        f"{ship_label(by_key[k][0])} → nearest in this edition: "
        f"{_nearest(k, edition_by_key, edn_label)}"
        for k in set(by_key) - set(edition_by_key))
    res.unmatched_edition = sorted(
        f"{edn_label(edition_by_key[k][0])} → nearest in the snapshot: "
        f"{_nearest(k, by_key, ship_label)}"
        for k in set(edition_by_key) - set(by_key))
    dup_ship = sorted(k for k, v in by_key.items() if len(v) > 1)
    dup_edn = sorted(k for k, v in edition_by_key.items() if len(v) > 1)
    if dup_ship or dup_edn:
        res.notes.append(
            f"(city, province) keys that still address more than one row: "
            f"{len(dup_ship)} shipped, {len(dup_edn)} in the edition table; the "
            "first occurrence is compared and the rest are counted below")
    unclaimed = [h for h in unclaimed if h not in ("Location", "Province")]
    if unclaimed:
        res.no_source_columns = []
        res.notes.append(
            "columns THIS EDITION prints that nothing shipped carries: " +
            ", ".join(f"`{h}`" for h in unclaimed))
    res.notes.append(
        "**What runtime actually reads from this file is `lat_long` and "
        "`degree_days_below_18_c`** — the nearest-city search is by coordinates "
        "and the climate zone comes from HDD18. The edition's own Table C-1 "
        "publishes NO coordinates at all, so adopting its row set cannot supply "
        "the column the lookup keys on; every other shipped column is either "
        "compared above or has no reader in this package")
    res.notes.append(
        "the unmatched ledger below lists EVERY unmatched row on both sides "
        f"({len(res.unmatched_shipped)} shipped, {len(res.unmatched_edition)} "
        "edition) with its nearest candidate, so the residue is nameable rather "
        "than a count")
    res.counts = {
        "shipped rows": len(shipped_rows),
        "edition rows": len(table["rows"]),
        "distinct (city, province) keys shipped": len(by_key),
        "distinct (city, province) keys in the edition": len(edition_by_key),
        "rows matched": matched,
        "rows unmatched (shipped)": len(res.unmatched_shipped),
        "rows unmatched (edition)": len(res.unmatched_edition),
        "duplicate keys (shipped)": len(dup_ship),
        "duplicate keys (edition)": len(dup_edn),
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
    # Counted from the archived payloads, never asserted in prose.
    fan_words: dict[str, int] = {}
    for letter, by_key in edition_rows.items():
        for (category, _day), row in by_key.items():
            if category != SCHEDULE_CATEGORIES["fan"]:
                continue
            for column in HOUR_COLUMNS:
                word = norm_name(row.get(column))
                if word in SCHEDULE_WORDS:
                    key = f"{letter}:{word}"
                    fan_words[key] = fan_words.get(key, 0) + 1
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
    on_cells = fan_words.get("I:on", 0)
    off_cells = fan_words.get("I:off", 0)
    if on_cells or off_cells:
        res.counts["Schedule I `Fans` cells this edition prints `On`"] = on_cells
        res.counts["Schedule I `Fans` cells this edition prints `Off`"] = off_cells
        res.notes.append(
            f"**Schedule I is DORMANT DATA, not a live difference.** This "
            f"edition's Schedule I `Fans` row prints **{on_cells} `On`** cells "
            f"and **{off_cells} `Off`** cells across Mon-Fri / Sat / Sun; the "
            f"shipped `NECB-I-Fan` carries 0.0 in all {on_cells + off_cells}, so "
            f"the {off_cells} `Off` cells agree and the {on_cells} `On` cells are "
            "the entire difference. Nothing in product Python consumes it: no "
            "module reads `exhaust_schedule`, the reference air loops inherit "
            "the PROPOSED system's operating schedule instead "
            "(`hvac/reference.py:~843-866`, D-14, Article 8.4.3.2.(1)), and the "
            "space-type references spell the name `NECB-I-FAN` while the "
            "schedule table defines `NECB-I-Fan` — a case mismatch that would "
            "have to be resolved before any reader could find it. **These cells "
            "are NOT changed here**: a data correction is a D-89 adoption step, "
            "not a matcher fix")


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
    """``{normalised catalog name: normalised "category | type" row key}``.

    This is the CONTROL bridge and nothing else. Some of its entries are
    Table 4.2.1.6's own control CROSS-REFERENCES: the medical-supply-room row
    prints an LPD and a Note reading "See Storage Room under Common Space Types
    for applicable control requirements", so the daylighting file maps it to the
    Storage Room row and marks the entry ``mapping:
    cross_reference_storage_room``. That pointer answers "which row states this
    space's controls" and NOT "which row states its loads or its LPD" — both
    editions publish a medical-supply-room row of their own for those. Loads and
    LPD therefore go through :func:`loads_bridge`.
    """
    data = _shipped(edition_id, "tables/daylighting_controls_4_2_1_6.json")
    out = {}
    for name, entry in (data.get("space_types") or {}).items():
        row = entry.get("table_row") if isinstance(entry, dict) else None
        if row:
            out[norm_name(name)] = norm_name(row.replace("|", " "))
    return out


def control_cross_references(edition_id: str) -> dict[str, str]:
    """``{normalised catalog name: the declared cross-reference}``.

    Read from the daylighting file's own ``mapping`` field, not guessed: an
    entry whose mapping begins ``cross_reference`` says, in the snapshot's own
    words, that its ``table_row`` was chosen for CONTROLS.
    """
    data = _shipped(edition_id, "tables/daylighting_controls_4_2_1_6.json")
    out = {}
    for name, entry in (data.get("space_types") or {}).items():
        mapping = entry.get("mapping") if isinstance(entry, dict) else None
        if isinstance(mapping, str) and mapping.startswith("cross_reference"):
            out[norm_name(name)] = mapping
    return out


#: Catalog names whose OWN row exists in the edition tables under a spelling the
#: normaliser cannot reach. Declared in data, one line per case, exactly like
#: ``EXTERIOR_ALIASES`` — never a fuzzy match. Today there is one: the catalog
#: writes "Health care facility", both editions print "Healthcare facility".
SPACE_TYPE_ALIASES = {
    "health care facility medical supply room":
        "healthcare facility medical supply room",
}


def loads_bridge(edition_id: str) -> dict[str, str]:
    """The catalog-name translation to use for LOADS and LPD.

    The control bridge minus every entry the snapshot itself declares to be a
    control cross-reference; those names are aimed instead at the edition row
    that carries the space's own published loads and LPD.
    """
    bridge = dict(catalog_bridge(edition_id))
    for name in control_cross_references(edition_id):
        bridge.pop(name, None)
        alias = SPACE_TYPE_ALIASES.get(name)
        if alias:
            bridge[name] = alias
    return bridge


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
    bridge = loads_bridge(res.edition_id)
    res.mapping = (
        "the shipped catalog name (`space_type` with its `-sch-<letter>` suffix "
        "stripped, or `building_type` for `WholeBuilding` rows) is translated to "
        "a Table 4.2.1.6 row through the snapshot's OWN authored mapping — the "
        "`table_row` field of every `tables/daylighting_controls_4_2_1_6.json` "
        "entry (D-57, hand-mapped and LPD-cross-checked) — **minus the entries "
        "that file marks as control CROSS-REFERENCES**, which point at the row "
        "governing another space's controls and say nothing about this space's "
        "loads or LPD. That row key is then looked up in each edition table by "
        "normalised \"Space Category / Space Type\" name. Building-area rows "
        "resolve against Tables A-8.4.3.2.(2)-A and 4.2.1.5. Occupant density is "
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
    for name, mapping in sorted(control_cross_references(res.edition_id).items()):
        res.notes.append(
            f"`{name}` carries the daylighting file's `{mapping}` marker: Table "
            "4.2.1.6 refers it to another row for CONTROLS only. That pointer is "
            "excluded from this comparison — this edition publishes the space's "
            "own row in A-8.4.3.2.(2)-B and 4.2.1.6, and the shipped loads and "
            "LPD are compared against it")
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
    bridge = loads_bridge(res.edition_id)
    res.mapping = (
        "the shipped table is the legacy LED-ALTERNATIVE LPD set (NREL 63807 "
        "retrofit assumptions), not a code table; each row is joined by the same "
        "loads bridge `tables/space_types.json` uses — the authored catalog-name "
        "mapping with the control cross-references removed — and its "
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
        "two independent comparisons. (a) EQUIPMENT: an explicit per-family "
        "row-and-column mapping — each shipped family names the edition table, "
        "the equipment-class row, the capacity band (with the band bounds "
        "converted out of the engine's Btu/h or tons) and the METRIC column its "
        "value is supposed to be, and each cell is compared against that one "
        "identified cell; a family with no faithful mapping is reported "
        "UNMAPPED, never as agreeing. (b) CURVES: each shipped `curves[]` entry "
        "matched to the edition curve table that publishes the same quantity "
        "and compared in the independent variables each source states — see "
        "the dedicated curve section below"
    )
    if equipment_tables:
        tables = {n: read_payload(res.edition_id, "get_table", n)
                  for n in equipment_tables}
        res.families = compare_equipment_families(res, tables)
        totals = {"rows": 0, "matched": 0, "unmatched": 0, "identical": 0,
                  "differing": 0, "no_edition_value": 0, "no_shipped_value": 0}
        unmapped_rows = 0
        for entry in res.families.values():
            for key in totals:
                totals[key] += entry[key]
            if entry["unmapped_reason"]:
                unmapped_rows += entry["rows"]
        res.counts.update({
            "equipment families": len(res.families),
            "equipment families UNMAPPED": sum(
                1 for e in res.families.values() if e["unmapped_reason"]),
            "equipment rows in an unmapped family": unmapped_rows,
            "equipment rows mapped to an edition row": totals["matched"],
            "equipment rows with no edition row under the mapping": totals["unmatched"],
            "equipment cells identical to the mapped cell": totals["identical"],
            "equipment cells differing from the mapped cell": totals["differing"],
            "mapped cells this edition prints no value for": totals["no_edition_value"],
            "edition minima the snapshot carries no value for": totals["no_shipped_value"],
        })
        res.notes.append(
            "equipment minima are NOT probed by value. The superseded pass "
            "accepted any nearby number under any unit conversion and so "
            "preserved no equipment class, table, row, capacity band, metric or "
            "column; its count supported nothing. Each family below states its "
            "mapping explicitly and is compared cell by cell against the one "
            "cell that mapping names")
        res.notes.append(
            "the shipped capacity bins close with engine SENTINELS "
            "(`9999.0` tons, `9999999.0` Btu/h, `9.999999999E9`) where the Code "
            "writes \u201c\u2265 \u2026\u201d with no upper bound. A sentinel is read as an "
            "OPEN bound and never compared as a number, so it is no longer "
            "counted as a miss")
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


# --------------------------------------------------------------------------
# Boiler and furnace FHeatPLC — per EQUIPMENT CLASS, not per curve name
#
# The snapshot ships four part-load curves and names two of them `-COND`, which
# invites the reading that a condensing boiler gets the condensing curve. It
# does not: every row of `boilers` carries ``efffplr: BOILER-EFFFPLR`` and every
# row of `furnaces` carries ``FURNACE-EFFPLR``, so the non-condensing /
# atmospheric curve is what EVERY boiler and furnace in a reference building
# actually receives — including the gas-fired MODULATING boiler the reference
# selects to represent purchased heating. The comparison therefore reports, per
# class, the requirement that class is subject to and the deviation of the curve
# its rows are actually given, alongside the deviation of the curve whose NAME
# suggests it was meant for that class.
# --------------------------------------------------------------------------

#: kind -> (shipped family, the row key naming the part-load curve it is GIVEN).
FHEATPLC_ASSIGNMENT = {"boiler_plc": ("boilers", "efffplr"),
                       "furnace_plc": ("furnaces", "efffplr")}

#: kind -> {edition class name: the curve whose NAME says it is for that class}.
FHEATPLC_NOMINAL = {
    "boiler_plc": {"Non-condensing": "BOILER-EFFFPLR",
                   "Condensing": "BOILER-EFFFPLR-COND",
                   "Modulating": None},
    "furnace_plc": {"Atmospheric": "FURNACE-EFFPLR",
                    "Condensing": "FURNACE-EFFPLR-COND",
                    "Modulating": None},
}

#: Boiler return-hot-water temperatures the 2025 bivariate condensing surface is
#: evaluated over. The Code prints NO bounds for T_w,return, so the box is
#: declared here and stated in the document: 80–180 °F spans a condensing return
#: (a boiler stops condensing well above it) to a conventional 180 °F return.
T_W_RETURN_F = tuple(range(80, 181, 10))


def _plf_from_ratio(coefficients, plr):
    """PLF = PLR / FHeatPLC(PLR) — the EnergyPlus efficiency multiplier."""
    fheatplc = poly(coefficients, plr)
    return plr / fheatplc if fheatplc else None


def _requirement_points(requirement):
    """[(label, plr, required PLF)] over this requirement's own domain."""
    out = []
    if requirement["form"] == "tabulated":
        for plr in sorted(requirement["points"]):
            fheatplc = requirement["points"][plr]
            if fheatplc:
                out.append((f"PLR {plr:g}", plr, plr / fheatplc))
        return out
    if requirement["form"] == "bivariate":
        a, b, c, d, e, f = requirement["coefficients"]
        for t_w in T_W_RETURN_F:
            for plr in PLR_POINTS:
                value = (a + b * plr + c * plr * plr + d * t_w
                         + e * t_w * t_w + f * plr * t_w)
                if value:
                    out.append((f"PLR {plr:g} / T_w {t_w} °F", plr, plr / value))
        return out
    for plr in PLR_POINTS:
        value = _plf_from_ratio(requirement["coefficients"], plr)
        if value is not None:
            out.append((f"PLR {plr:g}", plr, value))
    return out


def _worst_against(curve, requirement):
    """(worst relative deviation, sample points) of a shipped curve."""
    worst = 0.0
    samples = []
    wanted = {0.1, 0.25, 0.5, 0.75, 1.0}
    for label, plr, required in _requirement_points(requirement):
        got = poly(curve, plr)
        worst = max(worst, abs(got - required) / abs(required))
        if plr in wanted and len(samples) < 8:
            samples.append((label, got, required, got / required))
    return worst, samples


def fheatplc_records(edition_id: str, kind: str, curves: dict) -> list[dict]:
    payload = read_payload(edition_id, "get_table", CURVE_TABLES[kind][edition_id])
    number = CURVE_TABLES[kind][edition_id]
    if payload is None:
        return []
    label_key = "Type of Boiler" if kind == "boiler_plc" else "Type of Furnace"
    equipment = label_key.split()[-1].lower()

    requirements: list[tuple[str, str, dict]] = []
    for row in payload.get("rows", []):
        klass = row.get(label_key)
        if not klass:
            continue
        printed3 = _row_coefficients(row, "abc")
        printed6 = _row_coefficients(row, "abcdef")
        if printed6 is not None and any(abs(v) > 0 for v in printed6[3:]):
            requirements.append((klass, number,
                                 {"form": "bivariate", "coefficients": printed6,
                                  "points": {}}))
        elif printed3 is not None:
            requirements.append((klass, number,
                                 {"form": "quadratic", "coefficients": printed3,
                                  "points": {}}))

    # 2020 prints the modulating requirement in a SEPARATE table, as ten
    # (PLR, FHeatPLC) points covering modulating boilers AND furnaces; 2025
    # folds a Modulating row into the same coefficient table. Injected only
    # when the class table itself has no Modulating row, so 2025 is not
    # double-counted.
    if not any(klass == "Modulating" for klass, _n, _r in requirements):
        modulating_number = CURVE_TABLES["boiler_modulating"][edition_id]
        modulating = read_payload(edition_id, "get_table", modulating_number)
        points = {}
        for row in (modulating or {}).get("rows", []):
            plr = next((as_number(v) for k, v in row.items()
                        if "part-load ratio" in k.lower()), None)
            fheatplc = as_number(row.get("FHeatPLC"))
            if plr is not None and fheatplc is not None:
                points[plr] = fheatplc
        if points:
            requirements.append(("Modulating", modulating_number,
                                 {"form": "tabulated", "coefficients": None,
                                  "points": points}))

    family, curve_key = FHEATPLC_ASSIGNMENT[kind]
    rows = _shipped(edition_id, "efficiencies.json").get(family) or []
    assigned_names: dict[str, int] = {}
    for row in rows:
        if isinstance(row, dict) and row.get(curve_key):
            assigned_names[row[curve_key]] = assigned_names.get(row[curve_key], 0) + 1
    assigned_name = max(assigned_names, key=assigned_names.get) if assigned_names else None
    assigned_curve = (
        [c for c in _coeffs(curves[assigned_name], 4) if c is not None]
        if assigned_name and curves.get(assigned_name) else None)

    records = []
    for klass, source_number, requirement in requirements:
        nominal_name = FHEATPLC_NOMINAL[kind].get(klass)
        nominal_curve = (
            [c for c in _coeffs(curves[nominal_name], 4) if c is not None]
            if nominal_name and curves.get(nominal_name) else None)
        domain = ("the ten printed PLR points 0.1–1.0"
                  if requirement["form"] == "tabulated"
                  else "PLR 0.10–1.00" if requirement["form"] == "quadratic"
                  else (f"PLR 0.10–1.00 × T_w,return "
                        f"{T_W_RETURN_F[0]}–{T_W_RETURN_F[-1]} °F"))
        assigned_worst = samples = None
        if assigned_curve:
            assigned_worst, samples = _worst_against(assigned_curve, requirement)
        nominal_worst = None
        if nominal_curve and nominal_name != assigned_name:
            nominal_worst, _ = _worst_against(nominal_curve, requirement)

        if requirement["form"] == "bivariate":
            relation = ("BIVARIATE: FHeatPLC is stated over PLR **and** the "
                        "boiler return-hot-water temperature T_w,return (°F, six "
                        "coefficients)")
        elif requirement["form"] == "tabulated":
            relation = (f"TABULATED: Table {source_number} states the requirement "
                        "as ten (PLR, FHeatPLC) points, not as coefficients")
        else:
            relation = ("functional-form change: the requirement is a fuel RATIO "
                        "quadratic; the shipped curve is the EnergyPlus "
                        "efficiency multiplier PLR / FHeatPLC(PLR)")

        detail_parts = []
        if assigned_worst is None:
            detail_parts.append(
                f"no shipped curve is assigned to any {family} row at all")
            verdict = "no inherited curve"
        else:
            detail_parts.append(
                f"every `{family}` row is GIVEN `{assigned_name}` "
                f"({assigned_names[assigned_name]}/{len(rows)} rows); against "
                f"this class's requirement it deviates by up to "
                f"**{assigned_worst * 100:.2f} %** over {domain}")
            verdict = ("identical to rounding" if assigned_worst <= ROUNDING_TOL
                       else "differs")
        if nominal_worst is not None:
            detail_parts.append(
                f"the curve NAMED for this class, `{nominal_name}`, would deviate "
                f"by {nominal_worst * 100:.2f} % — but no row references it")
        elif nominal_name is None:
            detail_parts.append(
                "the snapshot ships no curve named for this class at all")
        if requirement["form"] == "bivariate":
            plfs = [p for _l, _p, p in _requirement_points(requirement)]
            detail_parts.append(
                f"the required PLF ranges {min(plfs):.4f}–{max(plfs):.4f} across "
                "that box, so a single normalised-efficiency curve in PLR alone "
                "cannot hold it exactly at any T_w")

        records.append({
            "klass": "FHeatPLC", "name": assigned_name,
            "label": f"{klass} ({equipment})",
            "table": source_number, "relation": relation,
            "verdict": verdict, "detail": "; ".join(detail_parts),
            "shipped": assigned_curve,
            "edition": requirement["coefficients"] or sorted(requirement["points"].items()),
            "converted": None, "errata": [], "deviation": assigned_worst,
            "points": samples or [],
            "equipment_class": klass, "equipment": equipment,
            "assigned_name": assigned_name, "assigned_deviation": assigned_worst,
            "nominal_name": nominal_name, "nominal_deviation": nominal_worst,
            "requirement_form": requirement["form"], "domain": domain,
        })
    return records


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

    # -- boiler / furnace FHeatPLC, per EQUIPMENT CLASS --------------------
    for kind in ("boiler_plc", "furnace_plc"):
        records.extend(fheatplc_records(edition_id, kind, curves))

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
def declared_payloads() -> list[tuple[str, str, str]]:
    """Every ``(edition, kind, number)`` the matrix declares, archived or not."""
    out = []
    for edition_id in sorted(load_manifests()):
        for spec in SPEC.values():
            for kind, key in (("get_table", "tables"), ("get_section", "sections")):
                for number in spec.get(key, {}).get(edition_id, []):
                    out.append((edition_id, kind, number))
    return sorted(set(out))


def missing_payloads() -> list[str]:
    """The declared payloads that are not on disk.

    A missing payload is a FAILURE, not a line of prose in the document: with
    the payload absent the comparison it was meant to drive silently does not
    happen, and the file it belongs to still reports a verdict. The gate makes
    that impossible to publish.
    """
    out = []
    for edition_id, kind, number in declared_payloads():
        if read_payload(edition_id, kind, number) is not None:
            continue
        path = archive_path(edition_id, kind, number)
        # A synthetic DATA_ROOT in a test lives outside the repository.
        shown = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path
        out.append(f"{edition_id} {kind} {number} ({shown})")
    return out


def fetch(only: str | None = None, refresh: bool = False) -> int:
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
                    if target.is_file() and not refresh:
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
                    print(f"{edition_id} {kind} {number}: "
                          + ("refreshed" if refresh else "archived"))
    print(f"\n{wrote} payload(s) written under */provenance/{ARCHIVE_DIRNAME}/")
    still_missing = missing_payloads()
    if still_missing:
        print(f"\n{len(still_missing)} declared payload(s) still missing:")
        for item in still_missing:
            print(f"  {item}")
        return 1
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


def _foreign_counts() -> str:
    """"7 in `necb2020` and 7 in `necb2025`" — counted, never hand-written, so
    an adoption that re-sources a file drops its row AND its count together."""
    parts = [f"{len(foreign_outputs(manifest))} in `{edition_id}`"
             for edition_id, manifest in sorted(load_manifests().items())]
    return " and ".join(parts)


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
    out.append(
        f"**Completeness is a gate, not a caveat.** All {len(declared_payloads())} "
        "payloads the matrix declares are archived; generation refuses to run "
        "with any of them missing, so no comparison can silently not happen and "
        "still leave its file carrying a verdict.")
    out.append("")

    out.append("## Matrix")
    out.append("")
    out.append(
        "The rows are derived from the manifests, not listed by hand: an output "
        "appears here when its `provenance` entry's `source` is neither "
        "`mcp:necb:<this edition>` nor a `self:` declaration — "
        + _foreign_counts() + ". `necb2025`'s `efficiencies.json` is added "
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
        if res.families:
            out.append("**Equipment families — the explicit mapping and what it "
                       "proves.** Every row is joined to ONE identified edition "
                       "row (equipment class + capacity band, the band bounds "
                       "converted out of the engine's units) and every declared "
                       "cell compared against ONE identified column and metric. "
                       "A family with no faithful mapping is **unmapped** and "
                       "contributes no agreeing cells.")
            out.append("")
            out.append("| family | rows | edition table(s) | rows mapped | rows "
                       "unmapped | cells identical | cells differing | edition "
                       "prints no value | snapshot carries no value |")
            out.append("|---|---:|---|---:|---:|---:|---:|---:|---:|")
            for name, entry in sorted(res.families.items()):
                if entry["unmapped_reason"]:
                    out.append(f"| `{name}` | {entry['rows']} | **unmapped** | — "
                               "| — | — | — | — | — |")
                    continue
                tables = ", ".join(f"`{t}`" for t in sorted(entry["tables"])) or "—"
                out.append(
                    f"| `{name}` | {entry['rows']} | {tables} | "
                    f"{entry['matched']} | {entry['unmatched']} | "
                    f"{entry['identical']} | {entry['differing']} | "
                    f"{entry['no_edition_value']} | {entry['no_shipped_value']} |")
            out.append("")
            for name, entry in sorted(res.families.items()):
                if entry["unmapped_reason"]:
                    reason = entry["unmapped_reason"]
                    out.append(f"- `{name}` — **UNMAPPED.** "
                               f"{reason[:1].upper()}{reason[1:]}")
                    continue
                out.append(f"- `{name}`:")
                for line in entry["mappings"]:
                    out.append(f"  - {line}")
                if entry["undeclared"]:
                    out.append("  - metric-bearing keys NO block declares: " +
                               ", ".join(f"`{k}`"
                                         for k in sorted(entry["undeclared"])))
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

    out.append("### Boiler and furnace `FHeatPLC` — by EQUIPMENT CLASS, "
               "including modulating")
    out.append("")
    out.append(
        "**Naming is not assignment.** The snapshot ships four part-load curves "
        "and names two of them `-COND`, but no row references them: every row of "
        "`boilers` carries `efffplr: BOILER-EFFFPLR` (the NON-condensing curve) "
        "and every row of `furnaces` carries `FURNACE-EFFPLR` (the ATMOSPHERIC "
        "curve), at `hvac/efficiency.py:~1137-1154`. So the deviation that "
        "matters for a class is the deviation of the curve its rows are actually "
        "GIVEN, not of the curve whose name suggests it was meant for them. This "
        "bites hardest on modulating equipment, which the reference building "
        "elects: `hvac/reference.py:~1733` represents purchased heating by a "
        "gas-fired **modulating** boiler, and that boiler receives "
        "`BOILER-EFFFPLR` like every other.")
    out.append("")
    out.append(
        "**2025 does not “add” modulating equipment.** NECB 2020 already "
        "requires it: Table 8.4.5.2.-B publishes `FHeatPLC` for modulating "
        "boilers **and furnaces** as ten printed (PLR, FHeatPLC) points. What "
        "2025 changes is the FORM — the ten-point table is retired and a "
        "`Modulating` row joins the coefficient tables 8.4.6.2 and 8.4.6.3 as a "
        "polynomial. Both editions state the same kind of requirement; only "
        "2025 states it as coefficients.")
    out.append("")
    out.append(
        "PLF is the EnergyPlus normalised-efficiency multiplier, PLF(PLR) = "
        "PLR / FHeatPLC(PLR), so the two sources are compared as FUNCTIONS over "
        "the PLR grid rather than as coefficients.")
    out.append("")
    for res in results:
        classes = [r for r in res.curves if r.get("equipment_class")]
        if not classes:
            continue
        out.append(f"#### `{res.edition_id}`")
        out.append("")
        out.append("| equipment class | requirement table | requirement form | "
                   "curve every row is GIVEN | its worst PLF deviation | curve "
                   "NAMED for the class | its worst PLF deviation | domain |")
        out.append("|---|---|---|---|---:|---|---:|---|")
        for rec in classes:
            assigned = f"`{rec['assigned_name']}`" if rec["assigned_name"] else "_(none)_"
            nominal = (f"`{rec['nominal_name']}`" if rec["nominal_name"]
                       else "_(none shipped)_")
            nominal_dev = ("same curve" if rec["nominal_name"] == rec["assigned_name"]
                           else f"{rec['nominal_deviation'] * 100:.2f} %"
                           if rec["nominal_deviation"] is not None else "—")
            assigned_dev = (f"**{rec['assigned_deviation'] * 100:.2f} %**"
                            if rec["assigned_deviation"] is not None else "—")
            out.append(
                f"| {rec['label']} | `{rec['table']}` | {rec['requirement_form']} "
                f"| {assigned} | {assigned_dev} | {nominal} | {nominal_dev} | "
                f"{rec['domain']} |")
        out.append("")
        bivariate = [r for r in classes if r["requirement_form"] == "bivariate"]
        for rec in bivariate:
            out.append(
                f"> `{rec['label']}` is **bivariate**: `{rec['table']}` states "
                "FHeatPLC over PLR *and* the boiler return-hot-water temperature "
                "T_w,return in °F, with six coefficients. The Code prints no "
                "bounds for T_w,return, so the box evaluated here is declared: "
                f"{rec['domain']} — a condensing return at the low end (below "
                "which a boiler is not condensing) to a conventional 180 °F "
                "return at the high end. T" + rec["detail"].split("; ")[-1][1:] +
                ". Representing this surface needs a per-edition curve FORM — a "
                "bounded fit or table over both variables, or EMS — with the "
                "domain and the fit error pinned; it is not a new coefficient "
                "for the existing univariate curve.")
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
    # One trailing newline, never a blank line at EOF: `git diff --check`
    # rejects the latter.
    while out and not out[-1].strip():
        out.pop()
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
    parser.add_argument("--refresh", action="store_true",
                        help="with --fetch, re-retrieve and OVERWRITE payloads "
                             "that are already archived (--fetch alone skips them)")
    parser.add_argument("--only", help="with --fetch, restrict to one declared output path")
    parser.add_argument("--check", action="store_true",
                        help="regenerate to a temp file and fail if it differs from --output")
    args = parser.parse_args(argv)

    if args.fetch:
        return fetch(args.only, refresh=args.refresh)
    if args.refresh:
        parser.error("--refresh is only meaningful with --fetch")

    missing = missing_payloads()
    if missing:
        print(f"{len(missing)} declared payload(s) are NOT archived — the "
              "comparisons they drive would silently not happen:")
        for item in missing:
            print(f"  {item}")
        print("run: python3 python/scripts/generate_necb_vintage_match.py --fetch")
        return 1

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
