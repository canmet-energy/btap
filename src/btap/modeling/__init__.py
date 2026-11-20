"""btap.modeling — generic model authoring (port of the btap-modeling gem).

Parametric building geometry (footprint wizards, the bar engine, measured
footprints), the 110-system HVAC catalog + builders, classify/teardown, the
envelope constructions machinery, and the plan/render tooling. SDK-only,
code-agnostic: no NECB anywhere (rule application lives in btap.codes).

Every facade function imports its submodule lazily — deliberate (D-79): the
package imports without the SDK, and during the milestone port a half-landed
subpackage never blocks the rest.
"""

from __future__ import annotations

from btap.audit import AuditLog

#: The PUBLIC API of btap.modeling: the authoring facade. `AuditLog`
#: is imported here for the facade's own use and is NOT re-exported — its home
#: is `btap.audit`. `CREATE_ALIASES*` are internal parameter tables. The
#: domain submodules (`btap.modeling.loads`, `.lighting`, `.shw`, `.hvac`,
#: `.envelope`, `.geometry`) are imported directly, as the docstring says.
#: tests/test_public_api.py pins this list.
__all__ = [
    # geometry
    "SHAPES",
    "create",
    "create_from_footprint",
    "bar",
    "apply_wwr",
    "seed_constructions",
    # rendering
    "render",
    "floor_plans",
    # the HVAC catalogue
    "systems",
    "build_system",
    "elect_control_zones",
    "replace_system",
    "remove_hvac_from_zones",
    "plant_is_hvac_candidate",
    "characterize",
    "catalog_html",
    "model_hvac_diagrams",
    "hvac_icon_defs",
]

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
    still accepted. Only the rectangle shape has below-grade storeys.

    Every space the wizard creates gets its own thermal zone, named
    ``Zone <space>`` as ``bar()`` names them (#237); spaces already in a
    ``model=`` passed in are left as they are. Output carries NO space types
    or constructions: tag spaces with
    ``btap.codes.necb.loads.assign_space_types`` and give surfaces
    constructions with ``seed_constructions`` before the loads and envelope
    passes."""
    import openstudio

    from btap.modeling.geometry import wizards

    audit = audit or AuditLog()
    model = model or openstudio.model.Model()
    shape = str(shape).lower()
    if shape not in SHAPES:
        raise ValueError(f"unknown shape '{shape}' ({', '.join(SHAPES)})")
    existing = {str(space.handle()) for space in model.getSpaces()}

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
    model = result

    # #237: the ported wizards make SPACES but no thermal zones, unlike bar()
    # and create_from_footprint(). A zoneless model takes no thermostats from
    # the NECB loads pass, and EnergyPlus drops every surface of it while
    # reporting success — an empty building simulated cleanly. So each space
    # the wizard just made gets its own zone, named as bar() names them; a
    # caller's existing spaces (`model=`) are left alone.
    zoned = 0
    for space in model.getSpaces():
        if str(space.handle()) in existing or space.thermalZone().is_initialized():
            continue
        zone = openstudio.model.ThermalZone(model)
        zone.setName(f"Zone {space.nameString()}")
        space.setThermalZone(zone)
        zoned += 1

    storeys_above = params.get("above_ground_storys", params.get("num_floors", 3))
    storeys_below = params.get("under_ground_storys", 1 if shape == "rectangle" else 0)
    audit.decision("geometry", f"{shape} massing created",
                   inputs={**params, "shape": shape,
                           "spaces": len(model.getSpaces()),
                           "thermal_zones_created": zoned,
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


def seed_constructions(model, *, opaque_r_si=2.0, window_u_si=2.5,
                       window_shgc=0.4, window_vt=0.5, audit=None):
    """Give every surface a construction, so envelope work has one to retarget.

        model = modeling.bar(space_type_ratios=…, audit=audit)
        modeling.seed_constructions(model, audit=audit)

    Wizard and bar output carries no constructions, and every downstream
    envelope pass retargets an EXISTING one. `btap/modeling/README.md` has
    documented that precondition since the port while the only implementation
    was a method on a test class, so the documented authoring chain could not
    be started from the shipped wheel (issue #143).

    Defaults are deliberately poor — R-2 opaque, U-2.5 glazing — so a later
    envelope pass visibly improves on them. See
    `envelope.constructions.seed_set` for why one opaque construction is safe
    for every surface type and why assignment is direct rather than through a
    `DefaultConstructionSet`.

    THIS IS A SYNTHETIC SEED, not an archetype and not a code-backed
    assembly: one ordinary 16 mm gypsum board plus a low-density batt, on
    every wall, roof, floor and ground-contact surface alike. Its only job is
    to be present and improvable. A caller who needs a particular real
    assembly supplies one, and ENERGY RESULTS FROM AN UNREPLACED SEED ARE NOT
    REPRESENTATIVE of a real proposed building. Stated here rather than only
    in the primitive because this is the docstring a caller actually reads
    (Sol, `322`).
    """
    audit = audit or AuditLog()

    from btap.modeling.envelope import constructions

    opaque, window = constructions.seed_set(
        model, opaque_r_si=opaque_r_si, window_u_si=window_u_si,
        window_shgc=window_shgc, window_vt=window_vt)
    audit.decision("envelope", "seed construction set assigned",
                   inputs={"opaque_r_si": opaque_r_si,
                           "window_u_si": window_u_si,
                           "window_shgc": window_shgc,
                           "window_vt": window_vt,
                           "surfaces": len(model.getSurfaces()),
                           "sub_surfaces": len(model.getSubSurfaces())},
                   value=f"{opaque.nameString()} / {window.nameString()}")
    return model


def apply_wwr(model, wwr=None, audit=None, **bins):
    """Cut windows into every exterior wall to a caller-chosen window-to-wall
    ratio. NO default and no code knowledge — for the NECB maximum use
    btap.codes's envelope domain, which owns the rule. Accepts a float, a dict
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


def build_system(model, system_name, zones, *, performance_profile=None,
                 audit=None, **kwargs):
    """Build a catalogue system by descriptive name on ``zones``.

    See ``btap.modeling.hvac.builder.build_system`` for the keywords
    (``control_zone``, ``remove_existing``, ``config``, ...).

    **Single-zone systems and several zones.** Most "PSZ RTU ..." rows build
    ONE packaged unit over every zone they are given, following ONE control
    zone — as a house's furnace serves every floor from one thermostat. Which
    zone that is decides which zones go unmet, so:

    - pass ``control_zone=`` to choose it yourself; or
    - omit it, and the unit follows ``zones[0]`` PROVISIONALLY until
      :func:`elect_control_zones`, after a sizing run, moves control to the
      zone with the largest design heating load.

    For one unit per zone instead, pass ``config={'per_zone': True}`` or call
    once per zone. A shared build with no ``control_zone`` WARNS (#236); rows
    that state ``per_zone`` themselves, like the "Shared PSZ ..." rows, and an
    explicit ``control_zone`` do not.

    ``audit``, when given, records the build and that warning.
    """
    from btap.modeling.hvac import builder
    zones = list(zones)
    result = builder.build_system(
        model, system_name, zones,
        performance_profile=performance_profile, **kwargs)
    _record_hvac_build(system_name, zones, result, kwargs, audit,
                       replaced=bool(kwargs.get("remove_existing")))
    return result


def elect_control_zones(model, *, by=None, audit=None):
    """After a sizing run, carry out each shared single-zone unit's control
    rule: the zone with the largest design HEATING load (the default) or the
    largest COOLING load. ``build_system(..., control_zone="cooling")``
    chooses the rule; ``by=`` applies one to every marked unit. A control
    zone the user chose is never changed. Returns ``{air loop name: zone
    name}``. See ``btap.modeling.hvac.control_zones``.

    The sizing results must be attached to the model, which
    ``btap.simulation.run(model, ..., sizing_only=True)`` does::

        simulation.run(model, run_dir="runs/size", weather=weather,
                       sizing_only=True)
        modeling.elect_control_zones(model)
    """
    from btap.modeling.hvac import control_zones
    return control_zones.elect_control_zones(model, by=by, audit=audit)


def _shared_by_default(system_name, zones, config, control_zone=None):
    """The #236 trap: a PSZ row that does not state `per_zone`, built across
    several zones, becomes ONE unit for all of them. Returns the warning text,
    or None. The catalogue's explicit rows, shared or per-zone, are never
    flagged: their names and data already say what they build."""
    if len(zones) < 2:
        return None
    from btap.modeling.hvac import catalog
    row = catalog.resolve(system_name)
    if row.get("family") != "psz" or "per_zone" in row:
        return None
    if config and "per_zone" in config:
        return None
    if control_zone is not None:
        return None  # a shared unit on a chosen control zone is a design
    return (f"ONE shared '{system_name}' unit now serves {len(zones)} zones and "
            f"follows '{zones[0].nameString()}' PROVISIONALLY. After a sizing "
            f"run, btap.modeling.elect_control_zones(model) moves control to the "
            f"zone with the largest design heating load; or pass control_zone= "
            f"to choose it, or config={{'per_zone': True}} for one unit per "
            f"zone. (#236)")


def _control_zone_label(control_zone):
    if control_zone is None or isinstance(control_zone, str):
        return control_zone
    return control_zone.nameString()


def _record_hvac_build(system_name, zones, result, kwargs, audit, *, replaced):
    message = _shared_by_default(system_name, zones, kwargs.get("config"),
                                 kwargs.get("control_zone"))
    if message:
        import warnings
        warnings.warn(message, UserWarning, stacklevel=3)
    if audit is None:
        return
    if message:
        audit.warn("hvac", message, target=system_name,
                   inputs={"zones": len(zones)})
    air_loops = getattr(result, "air_loops", None)
    audit.decision("hvac", f"{'replaced with' if replaced else 'built'} {system_name}",
                   target=system_name,
                   inputs={"zones": len(zones),
                           "control_zone": _control_zone_label(kwargs.get("control_zone"))},
                   value={"air_loops": len(list(air_loops)) if air_loops is not None
                          else None})


def remove_hvac_from_zones(model, zones):
    """Zone-scoped teardown. See hvac.teardown.remove_hvac_from_zones."""
    from btap.modeling.hvac import teardown
    return teardown.remove_hvac_from_zones(model, zones)


def plant_is_hvac_candidate(loop):
    """Could a reference HVAC build adopt this plant loop? See
    hvac.systems.plant_loops.plant_is_hvac_candidate."""
    from btap.modeling.hvac.systems import plant_loops
    return plant_loops.plant_is_hvac_candidate(loop)


def characterize(model, audit=None):
    """Characterize ANY model's HVAC into a neutral, serializable facts dict."""
    from btap.modeling.hvac import classify
    return classify.characterize(model, audit=audit)


def replace_system(model, system_name, zones, *, performance_profile=None,
                   audit=None, **kwargs):
    """Replace whatever HVAC currently serves these zones with a catalog system.

    ``build_system(..., remove_existing=True)``; see its docstring for the
    single-zone warning and ``audit``."""
    from btap.modeling.hvac import builder
    zones = list(zones)
    result = builder.build_system(
        model, system_name, zones, **kwargs, remove_existing=True,
        performance_profile=performance_profile)
    _record_hvac_build(system_name, zones, result, kwargs, audit, replaced=True)
    return result


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
