"""The lighting domain of btap.necb (port of btap-necb's lighting.rb): Part 4
LPD allowances, the LED alternative, daylighting (4.2.1.6 + storage garages
4.2.2.2), exterior lighting, and the 8.4.4.5 reference treatment.

The vendored data lives in ``data/`` beside this module, byte-identical to the
gem's ``lib/btap_necb/lighting/data/``: the per-vintage rules manifests, the
merged LED table, the 2025 LPD tables and the Table 4.2.1.6. control matrix.

Port layout (D-79). Ruby's ``Lighting::ApplyLights`` etc. are one module per
file here, imported at the BOTTOM the way lighting.rb ``require_relative``s
them after defining the data accessors, and re-exported under their Ruby
spelling (``lighting.ApplyLights``). TWO submodule names collide with facade
method names — ``apply_lights`` and ``reference_daylighting`` are both a Ruby
module (``ApplyLights`` / ``ReferenceDaylighting``) and a ``Lighting.``
method. Python has ONE namespace for both, so the facade functions are defined
AFTER the submodule imports and deliberately win the attribute: the modules
stay reachable as ``lighting.ApplyLights`` / ``lighting.ReferenceDaylighting``
(and by full dotted path), the functions as ``lighting.apply_lights(...)`` /
``lighting.reference_daylighting(...)``, exactly as Ruby spells both.
"""

from __future__ import annotations

import json
from pathlib import Path

from btap.audit import AuditLog  # the family's ONE AuditLog (Ruby's alias)
from btap.costing.lighting import report as Costing  # Ruby: Costing = BtapCosting::Lighting

__all__ = ["DATA_DIR", "AuditLog", "Costing", "rules", "data_vintage", "table",
           "led_record", "cost", "apply_lights", "add_daylighting_controls",
           "reference_lighting", "reference_daylighting",
           "ApplyLights", "Exterior", "Reference", "DaylightedAreas",
           "DaylightControlRequirement", "Daylighting", "StorageGarage",
           "ReferenceDaylighting"]

DATA_DIR = Path(__file__).parent / "data"

_rules: dict[str, dict] = {}
_tables: dict[str, list] = {}


def rules(vintage):
    key = str(vintage)
    if key not in _rules:
        path = DATA_DIR / f"lighting_rules_{key}.json"
        if not path.exists():
            raise ValueError(
                f"no NECB lighting rules for vintage '{vintage}' (expected {path})")
        _rules[key] = json.loads(path.read_text(encoding="utf-8"))
    return _rules[key]


def data_vintage(vintage):
    return rules(vintage).get("data_vintage_alias") or str(vintage)


def table(name):
    if name not in _tables:
        path = DATA_DIR / f"{name}.json"
        _tables[name] = json.loads(path.read_text(encoding="utf-8"))["table"]
    return _tables[name]


def led_record(building_type, space_type):
    """The merged LED alternative table (lighting_per_area W/ft2 + heat
    fractions)."""
    for r in table("led_lighting_2020"):
        if r["building_type"] == building_type and r["space_type"] == space_type:
            return r
    return None


# The submodules read `rules`/`table`/`led_record` above. Import order mirrors
# lighting.rb's require_relative sequence, with ONE inversion Python forces:
# daylighted_areas_legacy_2011.rb REOPENS Daylighting and therefore loads
# AFTER daylighting.rb; here the quarantined module is `_legacy_2011` and
# daylighting.py re-exports from it, so it loads WITH (just before)
# daylighting instead. See the header of _legacy_2011.py.
from btap.necb.lighting import apply_lights as _apply_lights  # noqa: E402
from btap.necb.lighting import exterior as _exterior  # noqa: E402
from btap.necb.lighting import reference as _reference  # noqa: E402
from btap.necb.lighting import daylighted_areas as _daylighted_areas  # noqa: E402
from btap.necb.lighting import daylight_control_requirement as _daylight_control_requirement  # noqa: E402
from btap.necb.lighting import daylighting as _daylighting  # noqa: E402
from btap.necb.lighting import storage_garage as _storage_garage  # noqa: E402
from btap.necb.lighting import reference_daylighting as _reference_daylighting  # noqa: E402

#: Ruby's nested modules, reachable under their Ruby spelling
#: (``Lighting::DaylightedAreas.areas`` -> ``lighting.DaylightedAreas.areas``).
ApplyLights = _apply_lights
Exterior = _exterior
Reference = _reference
DaylightedAreas = _daylighted_areas
DaylightControlRequirement = _daylight_control_requirement
Daylighting = _daylighting
StorageGarage = _storage_garage
ReferenceDaylighting = _reference_daylighting


def cost(model, **kwargs):
    """Cost the model's lighting fixtures. This is the NECB layer, so it
    supplies the daylighted-area provider btap.costing deliberately does not
    own (callers can still override it)."""
    if kwargs.get("daylighting_areas") is None:
        kwargs["daylighting_areas"] = _daylighting.costing_area_provider()
    return Costing.cost(model, **kwargs)


def apply_lights(model, **kwargs):
    return _apply_lights.apply_lights(model, **kwargs)


def add_daylighting_controls(model, **kwargs):
    """Facade: add NECB daylighting controls (placement: 'all' by default —
    every daylighted space; pass placement='necb2020' for the code rule)."""
    return _daylighting.add_controls(model, **kwargs)


def reference_lighting(model, **kwargs):
    return _reference.reference_lighting(model, **kwargs)


def reference_daylighting(reference, **kwargs):
    return _reference_daylighting.apply(reference, **kwargs)
