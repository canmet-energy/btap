"""The envelope domain of btap.codes (port of btap-necb's envelope.rb):
NECB Section 3.2 prescriptive application, the 8.4.4.3/.4 reference-envelope
transform, thermal bridging (TBD), the 3.2.1.4 fenestration rule appliers,
and Table C-1 climate resolution.

The generic machinery it drives lives in btap.modeling (``Geometry`` ->
``btap.modeling.envelope.geometry``, ``Constructions`` ->
``btap.modeling.envelope.constructions``); assembly costing in
``btap.costing.envelope``. Ruby aliased those under lexical names on the
module; Python imports them where they are used.

PORT NOTE (naming collision Ruby does not have): ``rules`` is BOTH the
edition-data loader defined here (Ruby ``Envelope.rules``) and the file name
of the lookup module (``rules.rb`` -> ``rules.py``). Importing the submodule
rebinds the package attribute, so the loader is restored at the BOTTOM of
this file, after the submodule imports. Internal callers reach it lazily
(``from btap.codes.necb import envelope`` inside the function) so the restore has
always happened by call time.
"""

from __future__ import annotations

from btap.codes.necb import code_id, rulesdata


def _load_rules(edition):
    """This edition's envelope rules — a shim over the family's ONE loader
    (:func:`btap.codes.necb.rulesdata.load`), which owns the cache."""
    return rulesdata.load("envelope", code_id(edition))


#: Public name while the submodules below have not been imported yet — the
#: lookup module calls ``envelope.rules(edition)`` exactly as the Ruby does.
rules = _load_rules

# The domain files, in the Ruby require order. Each defines its behaviour on
# its own module; the two conveniences the old facade added are below.
from btap.codes.necb.envelope import (  # noqa: E402
    climate,  # noqa: E402
    fenestration,  # noqa: E402
    prescriptive,  # noqa: E402
    reference,  # noqa: E402
    thermal_bridging,  # noqa: E402
)
from btap.codes.necb.envelope import rules as _rules_module  # noqa: E402,F401
from btap.codes.necb.envelope.prescriptive import apply_prescriptive  # noqa: E402
from btap.codes.necb.envelope.reference import reference_envelope  # noqa: E402
from btap.codes.necb.envelope.rules import (  # noqa: E402
    BOUNDARIES,
    SURFACE_TYPES,
    U_FALLBACK,
    ground_floor_extent,
    max_fdwr,
    max_srr,
    max_u,
)


def hdd18(model, *, edition, hdd=None, audit=None):
    """Heating degree-days (18 °C) for the model's site: ``hdd`` when given,
    else the edition's Table C-1 for the nearest city, else the weather's
    ``.stat``. Takes ``edition=`` ('2020', '2025'), NOT ``code=`` — it is one of
    the per-edition DATA accessors. Forwards to
    :func:`btap.codes.necb.envelope.climate.hdd18`, whose signature this one
    mirrors exactly (tests/necb/test_facade_signatures.py)."""
    return climate.hdd18(model, edition=edition, hdd=hdd, audit=audit)


def cost(model, *, city=None, province_state=None, structure=None, performance="lp",
         tbd_result=None, tb_tallies=None, tb_quality="good", costs_csv=None,
         local_factors_csv=None, audit=None):
    """Cost the model's envelope. Forwards to :func:`btap.costing.envelope.cost`,
    whose signature this one mirrors exactly (tests/necb/test_facade_signatures.py)."""
    from btap.costing import envelope as costing

    return costing.cost(model, city=city, province_state=province_state,
                        structure=structure, performance=performance,
                        tbd_result=tbd_result, tb_tallies=tb_tallies,
                        tb_quality=tb_quality, costs_csv=costs_csv,
                        local_factors_csv=local_factors_csv, audit=audit)


# `from ... import rules as _rules_module` above set this package's `rules`
# attribute to the MODULE; restore the loader (see the port note in the
# docstring). The module itself stays reachable as `_rules_module`.
rules = _load_rules

__all__ = [
    "BOUNDARIES",
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
