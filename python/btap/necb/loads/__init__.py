"""The loads domain of btap.necb (port of btap-necb's loads.rb): NECB space-use
data application (people, plug/gas equipment, ventilation OA, infiltration,
NECB-<letter> schedule sets, thermostats) — and the family's vintage-data
authority (2025 aliases the 2020 tables where verified identical).

The vendored data lives in ``data/`` beside this module, byte-identical to the
gem's ``lib/btap_necb/loads/data/``: the per-vintage rules manifests plus the
merged space-type and schedule tables.
"""

from __future__ import annotations

import json
from pathlib import Path

from btap.audit import AuditLog  # the family's ONE AuditLog (Ruby's alias)

__all__ = ["DATA_DIR", "AuditLog", "rules", "data_vintage", "table",
           "assign_space_types", "apply_loads",
           "SpaceTypes", "Schedules", "Apply"]

DATA_DIR = Path(__file__).parent / "data"

_rules: dict[str, dict] = {}
_tables: dict[tuple[str, str], list] = {}


def rules(vintage):
    key = str(vintage)
    if key not in _rules:
        path = DATA_DIR / f"loads_rules_{key}.json"
        if not path.exists():
            raise ValueError(
                f"no NECB loads rules for vintage '{vintage}' (expected {path})")
        _rules[key] = json.loads(path.read_text(encoding="utf-8"))
    return _rules[key]


def data_vintage(vintage):
    """The vintage whose data tables back this vintage (2025 -> 2020)."""
    return rules(vintage).get("data_vintage_alias") or str(vintage)


def table(vintage, name):
    key = (data_vintage(vintage), name)
    if key not in _tables:
        path = DATA_DIR / f"{name}_{key[0]}.json"
        _tables[key] = json.loads(path.read_text(encoding="utf-8"))["table"]
    return _tables[key]


# The submodules read `table`/`rules` above — imported here, at the BOTTOM, the
# way loads.rb require_relatives them after defining the data accessors.
from btap.necb.loads import apply as _apply  # noqa: E402
from btap.necb.loads import schedules as _schedules  # noqa: E402
from btap.necb.loads import space_types as _space_types  # noqa: E402

#: Ruby's nested modules, reachable under their Ruby spelling
#: (``Loads::SpaceTypes.record`` -> ``loads.SpaceTypes.record``).
SpaceTypes = _space_types
Schedules = _schedules
Apply = _apply


def assign_space_types(model, map, vintage='2020', audit=None):
    """Assign NECB space types to a bare-geometry model. See Apply."""
    return _apply.assign_space_types(model, map, vintage=vintage, audit=audit)


def apply_loads(model, vintage='2020', audit=None):
    """Facade: apply NECB loads to every tagged space type."""
    return _apply.apply_loads(model, vintage=vintage, audit=audit)
