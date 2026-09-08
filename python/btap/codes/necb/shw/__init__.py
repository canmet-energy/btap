"""The SHW domain of btap.codes (port of btap-necb's shw.rb + shw/).

Per-space demand + the auto-sized plant, Part 6 performance
(Table 6.2.2.1, the NECB2020 UEF procedure), prescriptive checks (booster
heaters, field-verified declarations), and the 8.4.4.20 reference.

Each edition's rules manifest lives in that edition's own snapshot
(``btap/codes/necb/data/<code id>/shw_rules.json``): the Table 6.2.2.1
coefficients' provenance, the autosize constants, the part-load-curve spec, the
D-63 solar and pool minimums, and the article-coverage manifest.
"""

from __future__ import annotations

import json

from btap.codes.necb import _data_root, edition_file

_RULES: dict[tuple, dict] = {}


def rules(vintage):
    """The parsed shw ruleset for a vintage, memoized (Ruby ``@rules``)."""
    key = (_data_root(), str(vintage))
    if key not in _RULES:
        with open(edition_file(vintage, "shw_rules.json"), encoding="utf-8") as f:
            _RULES[key] = json.load(f)
    return _RULES[key]


# Demand + plant: see demand.apply_shw.
def apply_shw(model, **kwargs):
    from btap.codes.necb.shw import demand

    return demand.apply_shw(model, **kwargs)


def cost(model, **kwargs):
    """Ruby ``Costing = BtapCosting::SHW`` — the costing seam, forwarded."""
    from btap.costing import shw as costing

    return costing.cost(model, **kwargs)


def apply_water_heater_efficiency(water_heater, **kwargs):
    from btap.codes.necb.shw import efficiency

    return efficiency.apply_efficiency(water_heater, **kwargs)


def reference_shw(model, **kwargs):
    from btap.codes.necb.shw import reference

    return reference.reference_shw(model, **kwargs)
