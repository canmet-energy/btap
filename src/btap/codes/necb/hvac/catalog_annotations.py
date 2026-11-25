"""Which NECB reference System uses each HVAC catalogue row.

The catalogue and its taxonomy live in `btap.modeling`, which knows no code:
there a row carries only its NECB *lineage* (where it came from). Which rows
an NECB edition's REFERENCE building actually builds is this layer's to say,
read from that edition's own `reference_rules.json` — the same
`system_definitions` the reference selection uses (Astra, HVAC taxonomy
review: applicability must not live in the modeling layer).

The catalogue page takes these as labels through its `annotate` slot.
"""

from __future__ import annotations

from btap.codes import resolve
from btap.modeling.hvac import catalog


def catalog_reference_use(code="necb2020"):
    """``{catalogue id: [label, ...]}`` for every row the edition's reference
    building can build, e.g. ``"NECB 2020 System 6 reference (gas)"``.

    A definition that builds a row WITH a config override says so, because
    the override changes what is built: NECB System 2's electric variant is
    the four-pipe fan-coil row with ``boiler_fuel: Electricity``.
    """
    ruleset = resolve(code)
    label = ruleset.label
    definitions = ruleset.rules("hvac")["system_definitions"]
    uses = {}
    for system, variants in definitions.items():
        if not isinstance(variants, dict) or system == "table":
            continue
        for energy in ("gas", "electric"):
            variant = variants.get(energy)
            if not variant:
                continue
            row_id = catalog.resolve(variant["name"])["id"]
            which = ("heat-pump reference" if system == "hp"
                     else f"System {system} reference")
            text = f"{label} {which} ({energy})"
            overrides = variant.get("config") or {}
            if overrides:
                text += " with " + ", ".join(f"{k}={v}" for k, v in sorted(overrides.items()))
            uses.setdefault(row_id, []).append(text)
    return uses


def catalog_html(path=None, code="necb2020", **options):
    """The HVAC catalogue page, with each row's NECB reference use for `code`
    shown and searchable ("System 6", "heat-pump reference")."""
    from btap import modeling

    uses = catalog_reference_use(code)
    return modeling.catalog_html(path, annotate=lambda row: uses.get(row["id"], []),
                                 **options)
