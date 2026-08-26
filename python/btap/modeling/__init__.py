"""btap.modeling — generic model authoring (port of the btap-modeling gem).

Parametric building geometry (footprint wizards, the bar engine, measured
footprints), the 97-system HVAC catalog + builders, classify/teardown, the
envelope constructions machinery, and the plan/render tooling. SDK-only,
code-agnostic: no NECB anywhere (rule application lives in btap.necb).

Every facade function imports its submodule lazily — deliberate (D-79): the
package imports without the SDK, and during the milestone port a half-landed
subpackage never blocks the rest.
"""

from __future__ import annotations

from btap.audit import AuditLog

SHAPES = ("rectangle", "aspect_ratio", "courtyard", "h", "l", "t", "u")

# Canonical facade vocabulary (storeys= / below_grade_storeys=) mapped to the
# spellings the verbatim-ported engines actually take (per entry point).
CREATE_ALIASES = {"rectangle": {"storeys": "above_ground_storys",
                                "below_grade_storeys": "under_ground_storys"}}
CREATE_ALIASES_DEFAULT = {"storeys": "num_floors"}


def create(*, shape, model=None, audit=None, **params):
    """Keyword-friendly facade over the wizards. Returns the model (a fresh
    one is created when none is given); every call is audited with the full
    parameter set so downstream QAQC can reproduce the massing.

        create(shape='rectangle', length=40, width=25, storeys=3,
               below_grade_storeys=1, audit=audit)

    storeys=/below_grade_storeys= are the canonical spellings; the engines'
    own names (above_ground_storys, under_ground_storys, num_floors) are
    still accepted. Only the rectangle shape has below-grade storeys."""
    import openstudio

    from btap.modeling.geometry import wizards

    audit = audit or AuditLog()
    model = model or openstudio.model.Model()
    shape = str(shape).lower()
    if shape not in SHAPES:
        raise ValueError(f"unknown shape '{shape}' ({', '.join(SHAPES)})")

    params = _normalize_storey_aliases(params, shape)

    if shape == "rectangle":
        result = wizards.create_shape_rectangle(model, *_ordered(
            params,
            ["length", "width", "above_ground_storys", "under_ground_storys",
             "floor_to_floor_height", "plenum_height", "perimeter_zone_depth",
             "initial_height"],
            [100.0, 100.0, 3, 1, 3.8, 1.0, 4.57, 0.0]))
    elif shape == "aspect_ratio":
        result = wizards.create_shape_aspect_ratio(model, *_ordered(
            params,
            ["aspect_ratio", "floor_area", "rotation", "num_floors",
             "floor_to_floor_height", "plenum_height", "perimeter_zone_depth"],
            [0.5, 1000.0, 0.0, 3, 3.8, 1.0, 4.57]))
    elif shape == "courtyard":
        result = wizards.create_shape_courtyard(model, *_ordered(
            params,
            ["length", "width", "courtyard_length", "courtyard_width",
             "num_floors", "floor_to_floor_height", "plenum_height",
             "perimeter_zone_depth"],
            [50.0, 30.0, 15.0, 5.0, 3, 3.8, 1.0, 4.57]))
    elif shape == "h":
        result = wizards.create_shape_h(model, *_ordered(
            params,
            ["length", "left_width", "center_width", "right_width",
             "left_end_length", "right_end_length", "left_upper_end_offset",
             "right_upper_end_offset", "num_floors", "floor_to_floor_height",
             "plenum_height", "perimeter_zone_depth"],
            [40.0, 40.0, 10.0, 40.0, 15.0, 15.0, 15.0, 15.0, 3, 3.8, 1.0, 4.57]))
    elif shape == "l":
        result = wizards.create_shape_l(model, *_ordered(
            params,
            ["length", "width", "lower_end_width", "upper_end_length",
             "num_floors", "floor_to_floor_height", "plenum_height",
             "perimeter_zone_depth"],
            [40.0, 40.0, 20.0, 20.0, 3, 3.8, 1.0, 4.57]))
    elif shape == "t":
        result = wizards.create_shape_t(model, *_ordered(
            params,
            ["length", "width", "upper_end_width", "lower_end_length",
             "left_end_offset", "num_floors", "floor_to_floor_height",
             "plenum_height", "perimeter_zone_depth"],
            [40.0, 40.0, 20.0, 20.0, 10.0, 3, 3.8, 1.0, 4.57]))
    else:  # 'u'
        result = wizards.create_shape_u(model, *_ordered(
            params,
            ["length", "left_width", "right_width", "left_end_length",
             "right_end_length", "left_end_offset", "num_floors",
             "floor_to_floor_height", "plenum_height", "perimeter_zone_depth"],
            [40.0, 40.0, 40.0, 15.0, 15.0, 25.0, 3, 3.8, 1.0, 4.57]))

    if result is None:
        raise ValueError(f"{shape} wizard rejected the parameters (see the OpenStudio log)")

    storeys_above = params.get("above_ground_storys", params.get("num_floors", 3))
    storeys_below = params.get("under_ground_storys", 1 if shape == "rectangle" else 0)
    audit.decision("geometry", f"{shape} massing created",
                   inputs={**params, "shape": shape,
                           "spaces": len(model.getSpaces()),
                           "storeys_above": storeys_above,
                           "storeys_below": storeys_below})
    return model


def create_from_footprint(*, geojson=None, points=None, height_m=None, storeys=None,
                          floor_to_floor_height=3.8, zoning="core_perimeter",
                          perimeter_zone_depth="auto", decimate_tolerance="auto",
                          multiplier="none", origin=None, source=None,
                          model=None, audit=None):
    """Measured-footprint entry: a real building outline plus a measured
    height in, zoned massing out. A peer of `create`, deliberately NOT a
    member of SHAPES. The audit entry carries full provenance (`source=`),
    and `core_perimeter` degrades to `single` with a warning when the outline
    cannot carry a core."""
    import openstudio

    from btap._compat import ruby_round
    from btap.modeling.geometry import footprint as fp

    audit = audit or AuditLog()
    model = model or openstudio.model.Model()
    source = source or {}
    if geojson is not None and points is not None:
        raise ValueError("pass either geojson= or points=, not both")
    if geojson is None and points is None:
        raise ValueError("a footprint needs geojson= or points=")
    if height_m is None and storeys is None:
        raise ValueError("pass height_m= or storeys=")
    if zoning not in ("core_perimeter", "single"):
        raise ValueError(f"unknown zoning '{zoning}' (core_perimeter, single)")
    if multiplier not in ("none", "mid"):
        raise ValueError(f"unknown multiplier '{multiplier}' (none, mid)")

    if geojson is not None:
        ring = fp.ring_from_geojson(geojson)
        centroid_lat = origin[0] if origin else sum(lat for _lon, lat in ring) / float(len(ring))
        centroid_lon = origin[1] if origin else sum(lon for lon, _lat in ring) / float(len(ring))
        points = fp.project(ring, lat0=centroid_lat, lon0=centroid_lon)
        model.getSite().setLatitude(centroid_lat)
        model.getSite().setLongitude(centroid_lon)

    raw_vertices = len(points)
    outline = fp.normalize(points)
    if decimate_tolerance == "auto":
        decimate_tolerance = ruby_round(fp.auto_tolerance(fp.area(outline)), 2)
    outline = fp.decimate(outline, decimate_tolerance)
    footprint_area = fp.area(outline)

    if storeys is None:
        storeys = fp.storeys_for(height_m, floor_to_floor_height)
    if storeys < 1:
        raise ValueError("storeys must be at least 1")

    if perimeter_zone_depth == "auto":
        perimeter_zone_depth = ruby_round(
            fp.auto_perimeter_depth(outline) or fp.MIN_USEFUL_DEPTH, 2)
        if zoning == "core_perimeter" and perimeter_zone_depth < fp.CONVENTIONAL_DEPTH:
            # Never silently: a reduced band is no longer the code's daylit zone.
            audit.warn("geometry",
                       "perimeter zone depth reduced below the 15 ft convention to fit the outline",
                       inputs={"perimeter_zone_depth": perimeter_zone_depth,
                               "conventional_depth": fp.CONVENTIONAL_DEPTH,
                               "outline_ceiling_m": ruby_round(fp.max_perimeter_depth(outline), 2),
                               **source})

    plan = fp.core_and_perimeter(outline, perimeter_zone_depth) if zoning == "core_perimeter" else None
    if plan and plan.get("rejected"):
        audit.warn("geometry",
                   "core-and-perimeter zoning not viable for this outline — single zone per storey",
                   inputs={"reason": plan["rejected"], "perimeter_zone_depth": perimeter_zone_depth,
                           "vertices": len(outline), "decimate_tolerance": decimate_tolerance,
                           "footprint_area_m2": ruby_round(footprint_area, 1), **source})
        plan = None
    achieved_zoning = "core_perimeter" if plan else "single"

    spaces = fp.build_massing(model, plan, outline, storeys, floor_to_floor_height,
                              multiplier=multiplier)

    audit.decision("geometry", "measured-footprint massing created",
                   inputs={"vertices_raw": raw_vertices, "vertices_used": len(outline),
                           "decimate_tolerance": decimate_tolerance,
                           "footprint_area_m2": ruby_round(footprint_area, 1),
                           "height_m": height_m, "floor_to_floor_height": floor_to_floor_height,
                           "storeys_above": storeys, "storeys_below": 0,
                           "modelled_height_m": ruby_round(storeys * floor_to_floor_height, 2),
                           "zoning": achieved_zoning, "requested_zoning": zoning,
                           # None when no perimeter zoning happened — reporting the depth
                           # that was tried and rejected reads as if it applied
                           "perimeter_zone_depth": (perimeter_zone_depth
                                                    if achieved_zoning == "core_perimeter" else None),
                           "multiplier": multiplier, "spaces": len(spaces), **source},
                   value=f"{ruby_round(footprint_area, 1)} m2 x {storeys} storeys")
    return model


def apply_wwr(model, wwr=None, audit=None, **bins):
    """Cut windows into every exterior wall to a caller-chosen window-to-wall
    ratio. NO default and no code knowledge — for the NECB maximum use
    btap.necb's envelope domain, which owns the rule. Accepts a float, a dict
    of compass bins, or bins as keywords."""
    from btap.modeling.geometry import footprint as fp

    ratio = bins if wwr is None and bins else wwr
    if ratio is None:
        raise ValueError("pass a window-to-wall ratio: a float, or per-orientation bins")
    return fp.apply_wwr(model, ratio, audit=audit or AuditLog())


def bar(*, space_type_ratios, model=None, length=50.0, width=20.0,
        storeys=None, below_grade_storeys=None,
        num_stories_above_grade=None, num_stories_below_grade=None,
        floor_height=3.8, wwr=0.4,
        division_method="Multiple Space Types - Simple Sliced",
        story_multiplier_method="None",
        make_mid_story_surfaces_adiabatic=False,
        party_wall_fraction=0.0,
        party_wall_stories_north=0, party_wall_stories_south=0,
        party_wall_stories_east=0, party_wall_stories_west=0,
        bottom_story_ground_exposed_floor=True,
        top_story_exterior_exposed_roof=True,
        audit=None):
    """The family-native bar entry: sliced bar massing with NECB space types
    assigned by ratio in ONE step — geometry AND standards tagging.

        bar(space_type_ratios={('Space Function', 'Office enclosed > 25 m2'): 0.7,
                               ('Space Function', 'Corridor/Transition area other-sch-A'): 0.3},
            length=50.0, width=20.0, storeys=3, wwr=0.4)
    """
    import openstudio

    from btap.modeling.geometry import bar as bar_engine

    audit = audit or AuditLog()
    model = model or openstudio.model.Model()
    if not space_type_ratios:
        raise ValueError("space_type_ratios must not be empty")

    num_stories_above_grade = _resolve_alias(
        "storeys", storeys, "num_stories_above_grade", num_stories_above_grade, 3)
    num_stories_below_grade = _resolve_alias(
        "below_grade_storeys", below_grade_storeys,
        "num_stories_below_grade", num_stories_below_grade, 0)

    num_stories = num_stories_below_grade + num_stories_above_grade
    total_area = length * width * num_stories
    ratio_sum = float(sum(space_type_ratios.values()))
    space_types_hash = {}
    for (building_type, space_type_name), ratio in space_type_ratios.items():
        space_type = openstudio.model.SpaceType(model)
        space_type.setName(f"{building_type} {space_type_name}")
        space_type.setStandardsBuildingType(building_type)
        space_type.setStandardsSpaceType(space_type_name)
        space_types_hash[space_type] = {"floor_area": total_area * ratio / ratio_sum}

    args = {"num_stories_below_grade": num_stories_below_grade,
            "num_stories_above_grade": num_stories_above_grade,
            "bar_division_method": division_method,
            "story_multiplier_method": story_multiplier_method,
            "make_mid_story_surfaces_adiabatic": make_mid_story_surfaces_adiabatic,
            "wwr": wwr,
            "party_wall_fraction": party_wall_fraction,
            "party_wall_stories_north": party_wall_stories_north,
            "party_wall_stories_south": party_wall_stories_south,
            "party_wall_stories_east": party_wall_stories_east,
            "party_wall_stories_west": party_wall_stories_west,
            "bottom_story_ground_exposed_floor": bottom_story_ground_exposed_floor,
            "top_story_exterior_exposed_roof": top_story_exterior_exposed_roof}

    result = bar_engine.bar_hash_setup_run(model, args, length, width, floor_height,
                                           openstudio.Point3d(0, 0, 0),
                                           space_types_hash, num_stories)
    if result is False:
        raise RuntimeError("bar creation failed (see the OpenStudio log)")

    audit.decision("geometry", "sliced bar massing created with NECB space types assigned by ratio",
                   inputs={"length": length, "width": width, "wwr": wwr,
                           "storeys_above": num_stories_above_grade,
                           "storeys_below": num_stories_below_grade,
                           "division_method": division_method,
                           "space_types": [f"{bt}|{st}" for bt, st in space_type_ratios],
                           "spaces": len(model.getSpaces())})
    return model


def render(model_or_path, path=None, height=480, work_dir=None, audit=None):
    """3D viewer facade: Model or .osm path in, self-contained HTML fragment
    out (glTF embedded as a base64 data URI, crash-isolated export). Writes a
    standalone page to path= when given; returns the fragment either way (''
    when unrenderable — audited, never raises)."""
    from btap.modeling.geometry import render as render_mod

    audit = audit or AuditLog()
    fragment = render_mod.geometry_viewer(model_or_path, height=height,
                                          work_dir=work_dir, audit=audit)
    if path and fragment:
        from pathlib import Path
        Path(path).write_text(
            '<!DOCTYPE html><html><head><meta charset="utf-8">'
            "<title>Building geometry</title></head><body "
            f'style="font-family:system-ui,sans-serif;margin:24px">{fragment}</body></html>',
            encoding="utf-8")
    return fragment


def floor_plans(model_or_path, path=None, png_dir=None, audit=None):
    """Per-storey floor plans (the 2D counterpart to `render`): a plain-dict
    bundle of inline SVG strings — one plan per storey plus a shared
    thermal-zone legend. Never raises: an unreadable or floor-less model
    comes back as an empty bundle carrying 'error'."""
    from pathlib import Path

    from btap.modeling.geometry import plan as plan_mod

    audit = audit or AuditLog()
    detail = plan_mod.extract_for(model_or_path, audit=audit)
    bundle = plan_mod.bundle_from(detail)
    if path:
        Path(path).write_text(plan_mod.page(bundle, source=plan_mod.source_label(model_or_path),
                                            detail=detail), encoding="utf-8")
    pngs = plan_mod.pngs(bundle, png_dir, audit=audit) if png_dir else []

    if bundle.get("error"):
        audit.warn("plan", "no floor plans produced", inputs={"error": bundle["error"]})
    else:
        audit.decision("plan", "per-storey floor plans rendered",
                       target=plan_mod.source_label(model_or_path),
                       inputs={"storeys": len(bundle["storeys"]),
                               "spaces": sum(len(s["spaces"]) for s in detail["storeys"]),
                               "inferred_storeys": bundle["inferred_storeys"],
                               "html": path, "pngs": len(pngs)},
                       value=", ".join(s["name"] for s in bundle["storeys"]))
    return bundle


# --- The HVAC authoring API ------------------------------------------------

def systems(filter=None, family=None):
    """List the system catalog (names are a closed, validated vocabulary)."""
    from btap.modeling.hvac import catalog
    return catalog.list_systems(filter=filter, family=family)


def build_system(model, system_name, zones, **kwargs):
    """Build a system by descriptive name. See hvac.builder.build_system."""
    from btap.modeling.hvac import builder
    return builder.build_system(model, system_name, zones, **kwargs)


def remove_hvac_from_zones(model, zones):
    """Zone-scoped teardown. See hvac.teardown.remove_hvac_from_zones."""
    from btap.modeling.hvac import teardown
    return teardown.remove_hvac_from_zones(model, zones)


def characterize(model, audit=None):
    """Characterize ANY model's HVAC into a neutral, serializable facts dict."""
    from btap.modeling.hvac import classify
    return classify.characterize(model, audit=audit)


def replace_system(model, system_name, zones, **kwargs):
    """Replace whatever HVAC currently serves these zones with a catalog system."""
    from btap.modeling.hvac import builder
    return builder.build_system(model, system_name, zones, **kwargs, remove_existing=True)


def catalog_html(path=None, **opts):
    """Self-contained HTML catalog of every buildable system."""
    from btap.modeling.hvac import catalog_report
    return catalog_report.to_html(path, **opts)


def model_hvac_diagrams(model):
    """OpenStudio-App-style HVAC loop diagrams for ANY model, as inline SVG."""
    from btap.modeling.hvac import catalog_report
    return catalog_report.model_diagrams(model)


def hvac_icon_defs():
    """The hidden master <svg><defs> embedding every component icon ONCE."""
    from btap.modeling.hvac import catalog_report
    return catalog_report.icon_defs()


# --- Facade plumbing (ports of the Ruby module helpers) --------------------

def _normalize_storey_aliases(params, shape):
    """Rewrites the canonical storey names to the spellings the shape's
    wizard takes, so `_ordered`'s unknown-parameter check still sees only
    real wizard keys (and still raises for genuine typos)."""
    params = dict(params)
    aliases = CREATE_ALIASES.get(shape, CREATE_ALIASES_DEFAULT)
    if "below_grade_storeys" in params and "below_grade_storeys" not in aliases:
        raise ValueError(
            "below_grade_storeys= is only supported by the 'rectangle' shape — "
            f"the {shape} wizard has no below-grade storeys "
            "(aspect_ratio delegates to rectangle but fixes them at 0)")

    for alias_key, target in aliases.items():
        if alias_key not in params:
            continue
        if target in params:
            raise ValueError(f"pass either {alias_key}= or {target}=, not both — "
                             "they set the same value")
        params[target] = params.pop(alias_key)
    return params


def _resolve_alias(alias_key, alias_value, target_key, target_value, default):
    if alias_value is not None and target_value is not None:
        raise ValueError(f"pass either {alias_key}= or {target_key}=, not both — "
                         "they set the same value")
    return alias_value if alias_value is not None else (
        target_value if target_value is not None else default)


def _ordered(params, keys, defaults):
    """Positional-argument adapter: the wizards keep their upstream positional
    signatures; unknown keys raise so typos never silently fall to defaults."""
    unknown = [k for k in params if k not in keys]
    if unknown:
        raise ValueError(f"unknown parameter(s) {', '.join(unknown)} — expected {', '.join(keys)}")
    return [params.get(key, defaults[index]) for index, key in enumerate(keys)]
