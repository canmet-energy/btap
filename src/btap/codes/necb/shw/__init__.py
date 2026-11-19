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

from btap.codes.necb import code_id, rulesdata


def rules(edition):
    """This edition's shw rules — a shim over the family's ONE loader
    (:func:`btap.codes.necb.rulesdata.load`); the NAME is an address."""
    return rulesdata.load("shw", code_id(edition))


def apply_shw(model, *, code="necb2020", fuel="NaturalGas", shw_scale=1.0, audit=None):
    """Build the full NECB service-hot-water system: demand per space, the loop,
    the water heater and pump, Part 6 efficiency on the sized heater.

    ``fuel`` is the water heater's fuel; ``shw_scale`` scales every demand.
    Forwards to :func:`btap.codes.necb.shw.demand.apply_shw`, whose signature
    this one mirrors exactly (tests/necb/test_facade_signatures.py)."""
    from btap.codes.necb.shw import demand

    return demand.apply_shw(model, code=code, fuel=fuel, shw_scale=shw_scale, audit=audit)


def cost(model, *, city=None, province_state=None, costs_csv=None, audit=None):
    """Cost the model's service hot water. Forwards to
    :func:`btap.costing.shw.cost`, whose signature this one mirrors exactly."""
    from btap.costing import shw as costing

    return costing.cost(model, city=city, province_state=province_state,
                        costs_csv=costs_csv, audit=audit)


def apply_water_heater_efficiency(water_heater, *, code="necb2020", audit=None):
    """Apply the Part 6 minimum efficiency to one water heater. Forwards to
    :func:`btap.codes.necb.shw.efficiency.apply_efficiency`, whose signature
    this one mirrors exactly."""
    from btap.codes.necb.shw import efficiency

    return efficiency.apply_efficiency(water_heater, code=code, audit=audit)


def reference_shw(model, *, code="necb2020", audit=None):
    """Regenerate service hot water to code on a REFERENCE model. Forwards to
    :func:`btap.codes.necb.shw.reference.reference_shw`, whose signature this
    one mirrors exactly."""
    from btap.codes.necb.shw import reference

    return reference.reference_shw(model, code=code, audit=audit)
