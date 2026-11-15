"""Thermal-bridging costing — port of BTAP::BridgingData
.get_material_quantities_for_edges + cost_audit_thermal_bridging, keyed on
the vendored thermal_bridging.csv ($/ft piecework recipes per TBD edge type x
wall reference "<assembly> <quality>", BETB detail provenance).

LEGACY DEFECT (fixed here, loudly): legacy cost_audit_thermal_bridging
iterates the id=>quantity map but its ``materials_opaque.find`` block never
tests the id — the block body (``total += ...``) is truthy, so ``find``
stops at the FIRST row and EVERY thermal-bridge material is priced as
materials_opaque row 1 ("gypsum wallboard 0.5 in thick"). This port matches
materials BY ID (the obvious intent) and audits the deviation.

Per legacy comment, NO regional factors apply: edge piecework is costed
nationwide.

The edge TALLIES consume a precomputed TBD.process result (or a pre-built
tallies dict) — a live TBD run needs the pinned py-tbd engine (M7, the
[tbd] extra); the quantity/table
math here is TBD-free.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

from btap._compat import ruby_round, ruby_str
from btap.costing.envelope.database import to_f, to_s

SKIPPED_EDGE_TYPES = ("transition", "ceiling")
FENESTRATION_EDGE = re.compile(r"(skylight)?(jamb|sill|head)")  # anchored via fullmatch


def tallies_from_tbd(tbd_result, wall_reference):
    """Normalize a tallies dict out of a TBD.process result: io edges grouped
    by (normalized edge type) with lengths in metres, all referenced to one
    wall assembly+quality (the census can't attribute edges per wall type —
    same as legacy, which tallies against the building's costed wall
    assembly)."""
    edges = None
    if isinstance(tbd_result, dict):
        io = tbd_result.get("io")
        if isinstance(io, dict):
            edges = io.get("edges")
    if edges is None:
        return None

    tallies = defaultdict(lambda: defaultdict(float))
    for edge in edges:
        edge_type = re.sub(r"convex$", "",
                           re.sub(r"concave$", "", to_s(edge["type"])))
        tallies[edge_type][wall_reference] += to_f(edge["length"])
    return tallies


def cost(tallies, *, database, audit=None) -> dict:
    """tallies: {edge_type: {"<assembly> <quality>": length_m}}.
    Returns the thermal_bridging section of the report."""
    import openstudio  # SDK needed only for unit conversion at costing time

    quantities, tally_rows = material_quantities(tallies, database, audit)

    total = 0.0
    by_material = []
    for material_id, quantity_m in sorted(quantities.items()):
        if to_s(material_id) == "0" or to_s(material_id).strip() == "":
            if audit is not None:
                audit.warn(
                    "costing_thermal_bridging",
                    f"thermal_bridging.csv references material id '{material_id}' "
                    "which has no materials_opaque row — skipped "
                    f"(quantity {ruby_str(ruby_round(quantity_m, 2))} m)")
            continue

        material = next((row for row in database.materials_opaque
                         if row.get("materials_opaque_id") == to_s(material_id)),
                        None)
        if material is None:
            if audit is not None:
                audit.warn("costing_thermal_bridging",
                           f"material id {material_id} not found in "
                           "materials_opaque — skipped")
            continue

        costs = database.cost_record(material["id"])
        material_cost = costs["materialOpCost"] * to_f(material.get("material_mult"))
        labour_cost = costs["laborOpCost"] * to_f(material.get("labour_mult"))
        quantity_ft = openstudio.convert(quantity_m, "m", "ft").get()
        # materials_opaque quantities are ft2; piecework recipes price per ft
        # of edge, hence the legacy sqrt (ft2 -> ft)
        per_ft_divisor = math.sqrt(to_f(material.get("quantity")))
        line = ruby_round((material_cost + labour_cost + costs["equipmentOpCost"])
                          * (quantity_ft / per_ft_divisor), 2)
        total += line
        by_material.append({"materials_opaque_id": material_id,
                            "description": material.get("description"),
                            "quantity_m": ruby_round(quantity_m, 2),
                            "cost": line})

    if audit is not None:
        audit.decision(
            "costing_thermal_bridging",
            "thermal-bridge edges costed via thermal_bridging.csv piecework recipes, materials matched BY ID",
            inputs={"edge_rows": tally_rows, "materials": len(by_material)},
            value=f"${ruby_str(ruby_round(total, 2))}",
            evidence="legacy defect corrected: cost_audit_thermal_bridging's "
                     "find block ignores the id and prices every edge as "
                     "materials_opaque row 1 (gypsum wallboard)")

    return {"total_thermal_bridging_cost": ruby_round(total, 2),
            "by_material": by_material}


def material_quantities(tallies, database, audit):
    """Port of get_material_quantities_for_edges: edge tallies ->
    materials_opaque id => accumulated quantity (m), via the CSV's
    id_layers x multipliers."""
    quantities = defaultdict(float)
    rows_used = 0

    for edge_type, references in tallies.items():
        if to_s(edge_type) in SKIPPED_EDGE_TYPES:
            continue

        normalized = to_s(edge_type)
        if FENESTRATION_EDGE.fullmatch(normalized):
            normalized = "fenestration"

        for wall_reference, quantity_m in references.items():
            row = next((r for r in database.thermal_bridging
                        if r.get("edge_type") == normalized
                        and r.get("wall_reference") == wall_reference), None)
            if row is None:
                if audit is not None:
                    audit.warn(
                        "costing_thermal_bridging",
                        f"no thermal_bridging.csv entry for edge '{normalized}' "
                        f"with wall reference '{wall_reference}' — skipped "
                        f"({ruby_str(ruby_round(quantity_m, 2))} m uncosted)")
                continue

            rows_used += 1
            ids = _ruby_split(row.get("material_opaque_id_layers"))
            multipliers = _ruby_split(row.get("id_layers_quantity_multipliers"))
            # Ruby ids.zip(multipliers): length of ids, missing multipliers nil
            for index, material_id in enumerate(ids):
                scale = multipliers[index] if index < len(multipliers) else None
                quantities[material_id.strip()] += to_f(scale) * quantity_m
    return quantities, rows_used


def _ruby_split(value, sep=","):
    """Ruby ``to_s.split(sep)``: nil → [], and trailing empty fields drop."""
    text = to_s(value)
    if text == "":
        return []
    parts = text.split(sep)
    while parts and parts[-1] == "":
        parts.pop()
    return parts
