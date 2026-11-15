"""SDK -> plain dicts (port of report/model_query.rb). With the report
assembler (which drives the btap.modeling diagram engine), this is one of the
only TWO renderer files that touch the OpenStudio SDK; every other module
(charts, sections, checklist) is SDK-free and unit-testable. Never raises on
odd models — missing data maps to None and any extraction error collapses to
an {'error':} dict."""

from __future__ import annotations

import re

from btap._compat import opt, ruby_round, sorted_by_name

_WINDOWISH = re.compile(r"Window|GlassDoor")


def extract(model):
    """:return: plain-data snapshot of one model, or None if model is None"""
    if model is None:
        return None

    try:
        return {"envelope": envelope(model), "space_types": space_types(model)}
    except Exception as e:
        return {"error": f"model extraction failed: {e}"}


def envelope(model):
    """Surfaces grouped by type with area-weighted average conductance, plus
    FDWR/SRR. SimpleGlazing constructions return an empty thermalConductance
    so subsurfaces fall back to uFactor."""
    groups: dict[str, dict] = {}

    def group(key):
        return groups.setdefault(key, {"area_m2": 0.0, "ua_w_per_k": 0.0})

    for surface in model.getSurfaces():
        if surface.outsideBoundaryCondition() != "Outdoors":
            continue

        key = surface.surfaceType()  # Wall / RoofCeiling / Floor
        area = surface.grossArea()
        u = construction_conductance(surface.construction())
        group(key)["area_m2"] += area
        group(key)["ua_w_per_k"] += (u or 0.0) * area
    for sub in model.getSubSurfaces():
        if sub.outsideBoundaryCondition() != "Outdoors":
            continue

        sub_type = sub.subSurfaceType()
        key = "Window" if _WINDOWISH.search(sub_type) else sub_type
        area = sub.grossArea()
        u = construction_conductance(sub.construction())
        group(key)["area_m2"] += area
        group(key)["ua_w_per_k"] += (u or 0.0) * area

    surfaces = []
    for surface_type, g in groups.items():
        avg_u = (g["ua_w_per_k"] / g["area_m2"]
                 if g["area_m2"] > 0 and g["ua_w_per_k"] > 0 else None)
        surfaces.append({
            "type": surface_type,
            "area_m2": ruby_round(g["area_m2"], 1),
            "avg_u_w_per_m2k": ruby_round(avg_u, 3) if avg_u is not None else None,
        })

    wall_area = group("Wall")["area_m2"]
    window_area = group("Window")["area_m2"]
    roof_area = group("RoofCeiling")["area_m2"]
    skylight_area = group("Skylight")["area_m2"]
    return {
        "surfaces": surfaces,
        "fdwr": (ruby_round(window_area / (wall_area + window_area), 3)
                 if wall_area > 0 else None),
        "srr": (ruby_round(skylight_area / (roof_area + skylight_area), 3)
                if roof_area > 0 else None),
    }


def construction_conductance(optional_construction):
    try:
        base = opt(optional_construction)
        if base is None:
            return None

        construction = opt(base.to_LayeredConstruction())
        if construction is None:
            return None

        tc = opt(construction.thermalConductance())
        if tc is not None:
            return tc

        return opt(construction.uFactor())  # SimpleGlazing path
    except Exception:
        return None


def space_types(model):
    out = []
    for st in sorted_by_name(model.getSpaceTypes()):
        area = sum(space.floorArea() for space in st.spaces())
        if area == 0:
            continue

        lpd = unwrap(st.lightingPowerPerFloorArea())
        people = unwrap(st.peoplePerFloorArea())
        equipment = unwrap(st.electricEquipmentPowerPerFloorArea())
        out.append({
            "name": st.nameString(),
            "area_m2": ruby_round(area, 1),
            "lpd_w_per_m2": ruby_round(lpd, 2) if lpd is not None else None,
            "people_per_m2": ruby_round(people, 4) if people is not None else None,
            "equipment_w_per_m2": (ruby_round(equipment, 2)
                                   if equipment is not None else None),
        })
    return out


def unwrap(value):
    """Density getters return a plain double or an OptionalDouble depending
    on SDK version — normalize to float or None."""
    if isinstance(value, (int, float)):
        return value
    if hasattr(value, "is_initialized"):
        return opt(value)

    return None
