"""Envelope costing — port of legacy cost_audit_envelope + cost_construction.

For each censused surface: the costed-assembly catalog supplies (RSI, cost)
pairs (each candidate construction's id_layers priced through the materials
sheet -> costs table -> regional factors), the surface's cost per ft2 is the
linear interpolation of that curve at the surface's own RSI, glazing adds the
nearest-SHGC solar-film premium, and the line total is cost/ft2 x net area x
zone multiplier.
"""

from __future__ import annotations

import re

from btap._compat import ruby_round, ruby_str
from btap.costing.envelope import assemblies, quantify
from btap.costing.envelope import interpolate as interpolate_mod
from btap.costing.envelope.database import to_f, to_s


def cost(model, *, database, province_state, city, structure=None,
         performance="lp", tb_tallies=None, audit=None) -> dict:
    """Returns the envelope section of the report."""
    import openstudio  # SDK needed only for unit conversion at costing time

    census = quantify.census(model, audit=audit)
    curve_cache = {}
    section = {"construction_costs": [], "surface_types": {},
               "total_envelope_cost": 0.0}
    upper_exceeded = []

    for surface_type in quantify.SURFACE_TYPES:
        items = census[surface_type]
        type_cost = 0.0
        type_area = 0.0

        for item in items:
            assembly = assemblies.for_surface_type(surface_type, structure,
                                                   performance)
            sheet = assemblies.SHEETS[surface_type]
            cache_key = (sheet, assembly)
            if cache_key not in curve_cache:
                curve_cache[cache_key] = cost_curve(database, sheet, assembly,
                                                    province_state, city)
            curve = curve_cache[cache_key]

            result = interpolate_mod.interpolate(x_y_array=curve["points"],
                                                 x2=item.rsi)
            if result.upper_bound_exceeded:
                upper_exceeded.append(
                    f"{item.surface.nameString()} ({surface_type}, "
                    f"RSI {ruby_str(ruby_round(item.rsi, 3))})")

            film_cost = 0.0
            if sheet in assemblies.GLAZING_SHEETS:
                film_cost = solar_film_cost(database, item.surface,
                                            province_state, city)

            area_m2 = item.area_m2 * item.multiplier
            area_ft2 = openstudio.convert(area_m2, "m^2", "ft^2").get()
            line_cost = (result.value + film_cost) * area_ft2
            type_cost += line_cost
            type_area += area_m2

            accumulate_row(section["construction_costs"], assembly,
                           surface_type, item, line_cost, area_m2, result.note)

        snake = re.sub(r"([a-z\d])([A-Z])", r"\1_\2", surface_type).lower()
        section["surface_types"][snake] = {
            "cost": ruby_round(type_cost, 2), "area_m2": ruby_round(type_area, 2),
            "cost_per_m2": (ruby_round(type_cost / type_area, 2)
                            if type_area > 0 else 0.0),
        }
        section["total_envelope_cost"] += type_cost

    if tb_tallies is not None:
        add_parapet(section, tb_tallies, audit)

    if upper_exceeded:
        message = (
            "assembly cost curve upper bound exceeded — no costed assembly "
            "reaches the required thermal resistance for: "
            f"{'; '.join(upper_exceeded)}. The clamped "
            "upper-bound cost was used; the real assembly may be unbuildable "
            "at catalog pricing (legacy adds a $10^12 sentinel here — this "
            "port flags instead).")
        if audit is not None:
            audit.warn("costing_envelope", message)
        section["unrealistic_assembly"] = True
        section["unrealistic_assembly_note"] = message

    section["total_envelope_cost"] = ruby_round(section["total_envelope_cost"], 2)
    if audit is not None:
        audit.decision(
            "costing_envelope",
            "envelope costed by assembly cost-curve interpolation at each surface RSI",
            inputs={"surfaces": sum(len(v) for v in census.values()),
                    "city": city, "province_state": province_state,
                    "performance": performance,
                    "structure": (structure if structure is not None
                                  else "default (steel-framed)")},
            value=f"${ruby_str(ruby_round(section['total_envelope_cost'], 2))}")
    return section


def cost_curve(database, sheet, assembly, province_state, city) -> dict:
    """(RSI, $/ft2) points for an assembly catalog — each candidate
    construction's id_layers priced once (legacy cost_construction)."""
    candidates = database.construction_candidates(sheet, assembly)
    points = [[rsi, construction_cost(database, construction, province_state, city)]
              for rsi, construction in candidates.items()]
    return {"points": points, "candidates": candidates}


def construction_cost(database, construction, province_state, city) -> float:
    """Legacy cost_construction: sum over id_layers of
    ((material x reg_mat/100) + (labour x reg_inst/100) + equipment) x
    quantity, each layer rounded to cents."""
    id_key = f"materials_{construction['type']}_id"
    sheet_rows = database.materials_sheet(construction["type"])

    total = 0
    for layer_id in construction["id_layers"]:
        material = next((row for row in sheet_rows
                         if row.get(id_key) == to_s(layer_id)), None)
        if material is None:
            raise ValueError(f"material id {layer_id} not found in "
                             f"materials_{construction['type']}")

        costs = database.cost_record(material["id"])
        reg_mat, reg_inst, _ = database.regional_factors(province_state, city,
                                                         material["id"])
        material_cost = costs["materialOpCost"] * to_f(material.get("material_mult"))
        labour_cost = costs["laborOpCost"] * to_f(material.get("labour_mult"))
        total += ruby_round(
            ((material_cost * reg_mat / 100.0) + (labour_cost * reg_inst / 100.0)
             + costs["equipmentOpCost"]) * to_f(material.get("quantity")), 2)
    return total


def solar_film_cost(database, subsurface, province_state, city) -> float:
    """Legacy SHGC film premium: nearest materials_glazing 'Solarfilms' row
    by |SHGC delta|, material+labour x regional factors."""
    shgc = shgc_of(subsurface)
    if shgc is None:
        return 0.0

    films = [row for row in database.materials_glazing
             if row.get("material_type") == "Solarfilms"]
    if not films:
        return 0.0
    row = min(films,
              key=lambda r: abs(shgc - to_f(r.get("solar_heat_gain_coefficient"))))

    costs = database.cost_record(row["id"])
    material_cost = costs["materialOpCost"] * mult(row.get("material_mult"))
    labour_cost = costs["laborOpCost"] * mult(row.get("labour_mult"))
    reg_mat, reg_inst, _ = database.regional_factors(province_state, city,
                                                     row["id"])
    return (material_cost * reg_mat / 100.0) + (labour_cost * reg_inst / 100.0)


def shgc_of(subsurface):
    from btap._compat import opt

    base = opt(subsurface.construction())
    if base is None:
        return None

    construction = opt(base.to_LayeredConstruction())
    if construction is None:
        return None

    layers = construction.layers()
    if not layers:
        return None
    layer = layers[0]
    simple = opt(layer.to_SimpleGlazing())
    if simple is not None:
        return simple.solarHeatGainCoefficient()

    glazing = opt(layer.to_StandardGlazing())
    if glazing is not None:
        transmittance = glazing.solarTransmittanceatNormalIncidence()
        # some SDK versions hand back an Optional here — unwrap either way
        if hasattr(transmittance, "is_initialized"):
            transmittance = opt(transmittance)
        if transmittance is not None:
            return float(transmittance)

    return None


def add_parapet(section, tb_tallies, audit):
    """Parapets are not modelled surfaces: legacy adds parapet length x 1 m
    of the averaged exterior-wall $/m2 when TBD edge tallies are available."""
    parapet = tb_tallies.get("parapet")
    if parapet is None or len(parapet) == 0:
        return

    length_m = sum(parapet.values())
    wall_rate = to_f(section["surface_types"]
                     .get("exterior_wall", {}).get("cost_per_m2"))
    parapet_cost = ruby_round(length_m * wall_rate, 2)
    section["parapet_cost"] = parapet_cost
    section["total_envelope_cost"] += parapet_cost
    if audit is not None:
        audit.info("costing_envelope",
                   "parapet allowance added (parapet length x 1 m at the exterior-wall rate)",
                   inputs={"parapet_length_m": ruby_round(length_m, 2),
                           "wall_cost_per_m2": wall_rate},
                   value=f"${ruby_str(parapet_cost)}")


def accumulate_row(rows, assembly, surface_type, item, line_cost, area_m2, note):
    conductance = ruby_round(1.0 / item.rsi, 3)
    row = next((r for r in rows
                if r["assembly_name"] == assembly
                and r["conductance"] == conductance
                and r["surface_type"] == surface_type), None)
    if row is None:
        rows.append({"assembly_name": assembly, "surface_type": surface_type,
                     "conductance": conductance,
                     "area": ruby_round(area_m2, 2),
                     "cost": ruby_round(line_cost, 2),
                     "cost_per_area": (ruby_round(line_cost / area_m2, 2)
                                       if area_m2 > 0 else 0.0),
                     "note": note})
    else:
        row["area"] = ruby_round(row["area"] + area_m2, 2)
        row["cost"] = ruby_round(row["cost"] + line_cost, 2)
        row["cost_per_area"] = (ruby_round(row["cost"] / row["area"], 2)
                                if row["area"] > 0 else 0.0)


def mult(value) -> float:
    return 1.0 if value is None or to_s(value).strip() == "" else to_f(value)
