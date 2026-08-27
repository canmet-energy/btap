"""The SHW domain of btap.necb (port of btap-necb's shw.rb + shw/).

Per-space demand + the auto-sized plant, Part 6 performance
(Table 6.2.2.1, the NECB2020 UEF procedure), prescriptive checks (booster
heaters, field-verified declarations), and the 8.4.4.20 reference.

The vendored data lives in ``data/`` beside this module, byte-identical to
the gem's ``lib/btap_necb/shw/data/`` (Ruby's ``SHW::DATA_DIR``): the
per-vintage rules manifests carrying the Table 6.2.2.1 coefficients'
provenance, the autosize constants, the part-load-curve spec, the D-63 solar
and pool minimums, and the article-coverage manifest.
"""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

_RULES: dict[str, dict] = {}


def rules(vintage):
    """The parsed shw ruleset for a vintage, memoized (Ruby ``@rules``)."""
    key = str(vintage)
    if key not in _RULES:
        path = DATA_DIR / f"shw_rules_{key}.json"
        if not path.exists():
            raise ValueError(
                f"no NECB shw rules for vintage '{key}' (expected {path})")
        with open(path, encoding="utf-8") as f:
            _RULES[key] = json.load(f)
    return _RULES[key]


# Demand + plant: see demand.apply_shw.
def apply_shw(model, **kwargs):
    from btap.necb.shw import demand

    return demand.apply_shw(model, **kwargs)


def cost(model, **kwargs):
    """Ruby ``Costing = BtapCosting::SHW`` — the costing seam, forwarded."""
    from btap.costing import shw as costing

    return costing.cost(model, **kwargs)


def apply_water_heater_efficiency(water_heater, **kwargs):
    from btap.necb.shw import efficiency

    return efficiency.apply_efficiency(water_heater, **kwargs)


def reference_shw(model, **kwargs):
    from btap.necb.shw import reference

    return reference.reference_shw(model, **kwargs)
