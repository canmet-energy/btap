"""HDD18 resolution for envelope rules (port of btap-necb's
envelope/climate.rb), mirroring legacy get_necb_hdd18 (necb_2011.rb:196): an
explicit value wins; else the nearest NECB Table C-1 city (haversine on the
weather file's coordinates, 500 km tolerance); else the .stat file's annual
(wthr file) heating degree-days at the 18 C baseline.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from btap._compat import NullAudit, opt, ruby_round

TABLE_C1_PATH = Path(__file__).parent / "data" / "table_c1.json"
TOLERANCE_KM = 500.0

_TABLE_C1 = None

# The .stat annual heating-degree-day line. Ruby's String#match is a SEARCH,
# and `.` does not cross newlines in either language — so re.search, never
# re.match.
_STAT_HDD_RE = re.compile(
    r"-\s*(\d+)\s*annual\s*\(wthr file\)\s*heating degree-days\s*\(18.*?C baseline\)")

_EPW_SUFFIX_RE = re.compile(r"\.epw\Z", re.IGNORECASE)


def table_c1():
    global _TABLE_C1
    if _TABLE_C1 is None:
        with open(TABLE_C1_PATH, encoding="utf-8") as handle:
            _TABLE_C1 = json.load(handle)["table"]
    return _TABLE_C1


def hdd18(model, *, hdd=None, audit=None):
    """:return: HDD18, or None (with an audit warning) when unresolvable."""
    audit = audit if audit is not None else NullAudit()
    if hdd is not None:
        audit.info("climate", "HDD supplied explicitly", value=hdd)
        return hdd

    weather = opt(model.weatherFile())
    if weather is None or not weather.path().is_initialized():
        audit.warn("climate",
                   "no weather file on model — HDD unresolvable (pass hdd: explicitly)")
        return None

    from_city = nearest_city_hdd(weather, audit)
    if from_city is not None:
        return from_city

    from_stat = stat_hdd18(str(weather.path().get()), audit)
    if from_stat is not None:
        return from_stat

    audit.warn("climate",
               "HDD unresolvable: no Table C-1 city within tolerance and no parsable .stat file")
    return None


def nearest_city_hdd(weather_file, audit):
    """Nearest NECB Table C-1 city by haversine distance (legacy convention)."""
    audit = audit if audit is not None else NullAudit()
    lat = weather_file.latitude()
    lon = weather_file.longitude()
    best = min(table_c1(), key=lambda row: haversine_km([lat, lon], row["lat_long"]))
    distance = haversine_km([lat, lon], best["lat_long"])
    if distance > TOLERANCE_KM:
        audit.info("climate",
                   "nearest Table C-1 city beyond tolerance — falling back to .stat HDD",
                   inputs={"nearest": f"{best['city']}, {best['province']}",
                           "distance_km": ruby_round(distance, 1)})
        return None

    audit.decision("climate", "HDD from nearest NECB Table C-1 city",
                   inputs={"city": f"{best['city']}, {best['province']}",
                           "distance_km": ruby_round(distance, 1)},
                   value=best["degree_days_below_18_c"],
                   article="NECB Table C-1 (legacy get_necb_hdd18 convention)")
    return best["degree_days_below_18_c"]


def stat_hdd18(epw_path, audit):
    """Annual (wthr file) HDD at the 18 C baseline from the .stat beside the EPW."""
    audit = audit if audit is not None else NullAudit()
    stat_path = Path(_EPW_SUFFIX_RE.sub(".stat", str(epw_path)))
    if not stat_path.exists():
        return None

    # EnergyPlus .stat files are ISO-8859-1 (degree signs in the design-day
    # tables); Ruby reads them in that encoding and re-encodes to UTF-8 with
    # invalid/undef replaced. latin-1 decodes every byte, so errors='replace'
    # is belt-and-braces — but reading them as UTF-8 raises.
    with open(stat_path, encoding="latin-1", errors="replace") as handle:
        text = handle.read()
    match = _STAT_HDD_RE.search(text)
    if match is None:
        return None

    value = int(match.group(1))
    audit.decision("climate", "HDD from .stat file (annual wthr-file, 18 C baseline)",
                   inputs={"stat": stat_path.name}, value=value)
    return value


def haversine_km(a, b):
    rad = math.pi / 180
    dlat = (b[0] - a[0]) * rad
    dlon = (b[1] - a[1]) * rad
    h = (math.sin(dlat / 2) ** 2
         + math.cos(a[0] * rad) * math.cos(b[0] * rad) * math.sin(dlon / 2) ** 2)
    return 6371.0 * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h))
