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
from btap.codes import Ruleset
from btap.codes.necb import _data_root, code_id, edition_file, rulesdata

__all__ = ["AuditLog", "rules", "table",
           "assign_space_types", "apply_loads",
           "SpaceTypes", "Schedules", "Apply"]

#: Table cache keyed by (data root, edition, table) so a test that repoints
#: the family's data root is never served the previous root's tables. The rule
#: files are cached once for the whole family in ``necb.rulesdata``.
_tables: dict[tuple, list] = {}


def rules(edition):
    """This edition's loads rules — a shim over the family's ONE loader.

    The name is an ADDRESS (Section 8.4 coverage ``code`` pointers and the
    removability gate call it), so Stage 6 kept it while the mechanism moved
    to :func:`btap.codes.necb.rulesdata.load`.
    """
    return rulesdata.load("loads", code_id(edition))


def table(edition, name):
    key = (_data_root(), str(edition), name)
    if key not in _tables:
        path = edition_file(edition, "tables", f"{name}.json")
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
    return _apply._assign_space_types(model, map, Ruleset.from_edition(vintage),
                                      audit=audit)


def apply_loads(model, vintage='2020', audit=None):
    """Facade: apply NECB loads to every tagged space type."""
    return _apply._apply_loads(model, Ruleset.from_edition(vintage), audit=audit)
