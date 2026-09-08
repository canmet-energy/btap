"""The loads domain of btap.codes (port of btap-necb's loads.rb): NECB space-use
data application (people, plug/gas equipment, ventilation OA, infiltration,
NECB-<letter> schedule sets, thermostats).

Every edition reads its OWN space-type and schedule tables out of its own
snapshot (``btap/codes/necb/data/<code id>/tables/``). Two editions verified
identical ship two identical copies; nothing aliases another edition (Stage 3
of the multi-edition plan removed ``data_vintage``).
"""

from __future__ import annotations

import json

from btap.audit import AuditLog  # the family's ONE AuditLog (Ruby's alias)
from btap.codes.necb import _data_root, edition_file

__all__ = ["AuditLog", "rules", "table",
           "assign_space_types", "apply_loads",
           "SpaceTypes", "Schedules", "Apply"]

#: Caches keyed by (data root, vintage[, table]) so a test that repoints the
#: family's data root is never served the previous root's tables.
_rules: dict[tuple, dict] = {}
_tables: dict[tuple, list] = {}


def rules(vintage):
    key = (_data_root(), str(vintage))
    if key not in _rules:
        path = edition_file(vintage, "loads_rules.json")
        _rules[key] = json.loads(path.read_text(encoding="utf-8"))
    return _rules[key]


def table(vintage, name):
    key = (_data_root(), str(vintage), name)
    if key not in _tables:
        path = edition_file(vintage, "tables", f"{name}.json")
        _tables[key] = json.loads(path.read_text(encoding="utf-8"))["table"]
    return _tables[key]


# The submodules read `table`/`rules` above — imported here, at the BOTTOM, the
# way loads.rb require_relatives them after defining the data accessors.
from btap.codes.necb.loads import apply as _apply  # noqa: E402
from btap.codes.necb.loads import schedules as _schedules  # noqa: E402
from btap.codes.necb.loads import space_types as _space_types  # noqa: E402

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
