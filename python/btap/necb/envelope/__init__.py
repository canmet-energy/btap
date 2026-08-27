"""The envelope domain of btap.necb (port of btap-necb's envelope.rb):
NECB Section 3.2 prescriptive application, the 8.4.4.3/.4 reference-envelope
transform, thermal bridging (TBD), the 3.2.1.4 fenestration rule appliers,
and Table C-1 climate resolution.

The generic machinery it drives lives in btap.modeling (``Geometry`` ->
``btap.modeling.envelope.geometry``, ``Constructions`` ->
``btap.modeling.envelope.constructions``); assembly costing in
``btap.costing.envelope``. Ruby aliased those under lexical names on the
module; Python imports them where they are used.

PORT NOTE (naming collision Ruby does not have): ``rules`` is BOTH the
vintage-data loader defined here (Ruby ``Envelope.rules``) and the file name
of the lookup module (``rules.rb`` -> ``rules.py``). Importing the submodule
rebinds the package attribute, so the loader is restored at the BOTTOM of
this file, after the submodule imports. Internal callers reach it lazily
(``from btap.necb import envelope`` inside the function) so the restore has
always happened by call time.
"""

from __future__ import annotations

import json
from pathlib import Path

RULES_DIR = Path(__file__).parent / "data"

_RULES_CACHE: dict[str, dict] = {}


def _load_rules(vintage):
    """Load the vendored envelope rules for a vintage ('2020', '2025')."""
    key = str(vintage)
    cached = _RULES_CACHE.get(key)
    if cached is not None:
        return cached

    path = RULES_DIR / f"envelope_rules_{key}.json"
    if not path.exists():
        raise ValueError(
            f"no NECB envelope rules for vintage '{key}' (expected {path})")
    with open(path, encoding="utf-8") as handle:
        _RULES_CACHE[key] = json.load(handle)
    return _RULES_CACHE[key]


#: Public name while the submodules below have not been imported yet — the
#: lookup module calls ``envelope.rules(vintage)`` exactly as the Ruby does.
rules = _load_rules

# The domain files, in the Ruby require order. Each defines its behaviour on
# its own module; the two conveniences the old facade added are below.
from btap.necb.envelope import (  # noqa: E402
    climate,  # noqa: E402
    fenestration,  # noqa: E402
    prescriptive,  # noqa: E402
    reference,  # noqa: E402
    thermal_bridging,  # noqa: E402
)
from btap.necb.envelope import rules as _rules_module  # noqa: E402,F401
from btap.necb.envelope.prescriptive import apply_prescriptive  # noqa: E402
from btap.necb.envelope.reference import reference_envelope  # noqa: E402
from btap.necb.envelope.rules import (  # noqa: E402
    BOUNDARIES,
    SURFACE_TYPES,
    U_FALLBACK,
    ground_floor_extent,
    max_fdwr,
    max_srr,
    max_u,
)


def hdd18(model, **kwargs):
    return climate.hdd18(model, **kwargs)


def cost(model, **kwargs):
    from btap.costing import envelope as costing

    return costing.cost(model, **kwargs)


# `from ... import rules as _rules_module` above set this package's `rules`
# attribute to the MODULE; restore the loader (see the port note in the
# docstring). The module itself stays reachable as `_rules_module`.
rules = _load_rules

__all__ = [
    "BOUNDARIES",
    "RULES_DIR",
    "SURFACE_TYPES",
    "U_FALLBACK",
    "apply_prescriptive",
    "climate",
    "cost",
    "fenestration",
    "ground_floor_extent",
    "hdd18",
    "max_fdwr",
    "max_srr",
    "max_u",
    "prescriptive",
    "reference",
    "reference_envelope",
    "rules",
    "thermal_bridging",
]
