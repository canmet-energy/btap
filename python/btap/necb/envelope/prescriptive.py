"""Prescriptive Section 3.2 application (port of btap-necb's
envelope/prescriptive.rb): set every exterior/ground surface and subsurface to
its Table 3.2.2.x/3.2.3.1 maximum U at the building's HDD, and optionally
rebuild fenestration to the 3.2.1.4 FDWR/SRR limits.

Application is by HARD ASSIGNMENT of deep-copied constructions (one copy per
unique construction x target, legacy naming/reuse conventions preserved) —
default construction sets are left untouched; parity with the legacy
default-set path is by resulting per-surface conductance.

include_films: True (default) treats the table value as OVERALL thermal
transmittance and solves the construction to 1/(1/U - R_films) — the 1.4.1.2
definition says U "reflects ... air films on both faces of above-ground
components", and the legacy OSut construction path (TBD.genConstruction,
NECB2020 prototypes) does the same. False applies the table value as
construction-only conductance (the OLD legacy BTAP
apply_standard_construction_properties convention, ~4% more stringent on
walls — kept for mechanism-parity tests). The choice is always audited.

Scope follows the 1.4.1.2 "building envelope" definition: surfaces of
unconditioned spaces (attics, crawlspaces) are NOT envelope and keep their
constructions; assemblies separating conditioned space from enclosed
unconditioned space ARE envelope — they get the Table 3.2.2.2 row for their
inclination (3.1.1.7.(6)) with the unconditioned enclosure credited at
U 6.25 per 3.1.1.7.(4).
"""

from __future__ import annotations

import openstudio

from btap._compat import opt, opt_or, ruby_round, ruby_str, sorted_by_name
from btap.audit import AuditLog
from btap.modeling.envelope import constructions as Constructions
from btap.necb.envelope import climate, fenestration
from btap.necb.envelope import thermal_bridging as thermal_bridging_module
from btap.necb.envelope.rules import ground_floor_extent, max_fdwr, max_srr, max_u

SUBSURFACE_CLASS = {
    "FixedWindow": "window", "OperableWindow": "window", "GlassDoor": "window",
    "Skylight": "skylight", "TubularDaylightDome": "skylight",
    "TubularDaylightDiffuser": "skylight",
    "Door": "door", "OverheadDoor": "door",
}

SURFACE_CLASS = {"Wall": "wall", "RoofCeiling": "roofceiling", "Floor": "floor"}

# 3.1.1.7.(4): an enclosed unconditioned space protecting an envelope
# component may be considered to have an overall U of 6.25 W/(m2.K).
ENCLOSURE_R = 1.0 / 6.25


def apply(model, *, vintage, hdd=None, apply_fdwr=False, apply_srr=False,
          include_films=True, thermal_bridging=None, audit=None):
    """PORT NOTE: the ``thermal_bridging`` KEYWORD keeps the Ruby spelling, so
    the sibling MODULE is imported as ``thermal_bridging_module`` above — the
    parameter would otherwise shadow it inside this function."""
    audit = audit if audit is not None else AuditLog()
    hdd = climate.hdd18(model, hdd=hdd, audit=audit)
    if hdd is None:
        raise ValueError("HDD unresolvable: pass hdd: explicitly or set a weather file")

    audit.info("prescriptive", "film convention",
               value=("code-literal: table U treated as overall transmittance incl. air "
                      "films (1.4.1.2 definition; films subtracted from construction)"
                      if include_films else
                      "legacy-BTAP-compatible: table U applied as construction-only "
                      "conductance"),
               article="1.4.1.2.", ruling="D-23")

    cache = {}
    window_construction = None
    skylight_construction = None

    outside_envelope = 0
    for surface in sorted_by_name(model.getSurfaces()):
        surface_class = SURFACE_CLASS.get(surface.surfaceType())
        if surface_class is None:
            continue

        # 1.4.1.2: surfaces of unconditioned spaces are not building envelope.
        space = opt(surface.space())
        if space is not None and not inside_envelope(space):
            if boundary_of(surface) is not None:
                outside_envelope += 1
            continue

        boundary = boundary_of(surface)
        if boundary is None:
            _assign_interzone_envelope(model, surface, surface_class, vintage, hdd,
                                       include_films, cache, audit)
            continue

        if boundary == "ground" and surface_class == "floor":
            _assign_ground_floor(model, surface, vintage, hdd, include_films, cache, audit)
        else:
            _assign_surface(model, surface, surface_class, boundary, vintage, hdd,
                            include_films, cache, audit)
        for sub in sorted_by_name(surface.subSurfaces()):
            sub_class = SUBSURFACE_CLASS.get(sub.subSurfaceType())
            if sub_class is None:
                audit.warn("prescriptive",
                           f"subsurface type '{sub.subSurfaceType()}' not classified — "
                           "construction left as-is",
                           target=sub.nameString())
                continue
            if boundary == "ground":  # NECB: no ground windows/doors
                continue

            construction = _assign_subsurface(model, sub, sub_class, vintage, hdd,
                                              include_films, cache, audit)
            if sub_class == "window" and window_construction is None:
                window_construction = construction
            if sub_class == "skylight" and skylight_construction is None:
                skylight_construction = construction

    if outside_envelope > 0:
        audit.info("prescriptive",
                   "exterior/ground surfaces of unconditioned spaces left untouched — "
                   "not part of the building envelope",
                   inputs={"surfaces": outside_envelope}, article="1.4.1.2.", ruling="D-24")

    if apply_fdwr:
        limit = max_fdwr(vintage=vintage, hdd=hdd, audit=audit)
        if window_construction is None:
            window_construction = _subsurface_target_construction(
                model, "window", vintage, hdd, include_films, cache, audit)
        fenestration.apply_fdwr(model, limit, window_construction, audit=audit)
    if apply_srr:
        limit = max_srr(vintage=vintage, audit=audit)
        if skylight_construction is None:
            skylight_construction = _subsurface_target_construction(
                model, "skylight", vintage, hdd, include_films, cache, audit)
        fenestration.apply_srr(model, limit, skylight_construction, audit=audit)

    # 3.1.1.7: table values are EFFECTIVE transmittance — uprate for thermal
    # bridging when requested (psi set name/dict, or True for the default set).
    # Ruby truthiness: ONLY nil/false are falsy there, so an empty string or
    # an empty psi dict still takes the uprate branch — `if thermal_bridging`
    # must not become a bare Python truth test.
    if thermal_bridging is not None and thermal_bridging is not False:
        psi = "regular (BETBG)" if thermal_bridging is True else thermal_bridging
        thermal_bridging_module.apply(model, vintage=vintage, hdd=hdd, psi_set=psi,
                                      audit=audit)
    else:
        audit.warn("thermal_bridging",
                   "thermal bridging not requested — applied U-values are clear-field; "
                   "NECB 3.1.1.7 requires EFFECTIVE transmittance (pass thermal_bridging:)",
                   article="3.1.1.7.")

    return audit


def boundary_of(surface):
    condition = surface.outsideBoundaryCondition()
    if condition == "Outdoors":
        return "outdoors"
    if condition in ("Ground", "Foundation", "GroundFCfactorMethod",
                     "GroundSlabPreprocessorAverage"):
        return "ground"
    return None


def inside_envelope(space) -> bool:
    """Inside the building envelope = conditioned or indirectly conditioned.

    partofTotalFloorArea is the primary signal (same predicate as the 8.4.3.3
    air-leakage transform); spaces tagged with the legacy
    space_conditioning_category property count as inside unless tagged
    'unconditioned' (legacy tags plenums 'nonresconditioned' — indirectly
    conditioned, thermal block (c) of the 1.4.1.2 definition)."""
    if space.partofTotalFloorArea():
        return True

    tag = opt(space.additionalProperties().getFeatureAsString(
        "space_conditioning_category"))
    return tag is not None and tag.lower() != "unconditioned"


def _assign_interzone_envelope(model, surface, surface_class, vintage, hdd,
                               include_films, cache, audit):
    """Assemblies separating conditioned space from ENCLOSED UNCONDITIONED
    space (attic ceilings, walls to unheated storage, floors over crawlspaces)
    are building envelope per 1.4.1.2 and must meet the Table 3.2.2.2 row for
    their inclination (3.1.1.7.(6) — surfaceType already encodes it). The
    unconditioned enclosure is credited at U 6.25 per 3.1.1.7.(4); both faces
    see interior air films. The paired surface gets the same construction so
    the pair stays consistent. (Legacy OSut instead applies the exposed-FLOOR
    row to attic ceilings — floor 0.175 vs roof 0.156 at HDD 3890 — a more
    lenient reading with no inclination-rule basis; divergence logged.)"""
    if surface.outsideBoundaryCondition() != "Surface":
        return

    adj = opt(surface.adjacentSurface())
    if adj is None:
        return

    adj_space = opt(adj.space())
    if adj_space is None or inside_envelope(adj_space):
        return

    construction = opt(surface.construction())
    layered = None if construction is None else opt(construction.to_Construction())
    if layered is None:
        audit.warn("prescriptive",
                   "envelope surface to unconditioned space has no layered construction — skipped",
                   target=surface.nameString(), ruling="D-24")
        return

    u = max_u(vintage=vintage, surface=surface_class, boundary="outdoors", hdd=hdd)
    r = (1.0 / u) - ENCLOSURE_R
    if include_films:
        r -= Constructions.film_r_interzone(surface_class)
    target = 1.0 / r
    key = (str(construction.handle()), surface_class, "interzone", target)
    if key not in cache:
        c = Constructions.opaque_at_conductance(model, layered, target)
        audit.decision("prescriptive",
                       f"envelope {surface_class} to enclosed unconditioned space set to "
                       "maximum U (row by inclination; enclosure credited at U 6.25)",
                       target=c.nameString(),
                       inputs={"hdd": hdd, "table_u": ruby_round(u, 4),
                               "target_u_construction": ruby_round(target, 4)},
                       value=("conductance "
                              f"{ruby_str(ruby_round(opt_or(c.thermalConductance(), 0.0), 4))}"
                              " W/m2K"),
                       article="Table 3.2.2.2.; 3.1.1.7.(4)", ruling="D-24")
        cache[key] = c
    surface.setConstruction(cache[key])
    adj.setConstruction(cache[key])


def _target_conductance(vintage, surface_class, boundary, hdd, include_films, audit):
    u = max_u(vintage=vintage, surface=surface_class, boundary=boundary, hdd=hdd)
    if not include_films:
        return u

    r_films = Constructions.film_r(surface_class, boundary)
    return 1.0 / ((1.0 / u) - r_films)


def _assign_surface(model, surface, surface_class, boundary, vintage, hdd,
                    include_films, cache, audit):
    construction = opt(surface.construction())
    layered = None if construction is None else opt(construction.to_Construction())
    if layered is None:
        audit.warn("prescriptive", "surface has no layered construction — skipped",
                   target=surface.nameString())
        return

    target = _target_conductance(vintage, surface_class, boundary, hdd, include_films, audit)
    key = (str(construction.handle()), surface_class, boundary, target)
    if key not in cache:
        c = Constructions.opaque_at_conductance(model, layered, target)
        audit.decision("prescriptive",
                       f"{boundary} {surface_class} construction set to maximum U",
                       target=c.nameString(),
                       inputs={"hdd": hdd, "target_u_construction": ruby_round(target, 4)},
                       value=("conductance "
                              f"{ruby_str(ruby_round(opt_or(c.thermalConductance(), 0.0), 4))}"
                              " W/m2K"),
                       article=("Table 3.2.3.1." if boundary == "ground"
                                else "Table 3.2.2.2."))
        cache[key] = c
    surface.setConstruction(cache[key])


def _assign_ground_floor(model, surface, vintage, hdd, include_films, cache, audit):
    """Table 3.2.3.1 floors row is zone-conditional: zone 8 prescribes the
    table U over the FULL slab area; zones 4-7B prescribe it only within a
    1.2 m perimeter strip (3.2.3.3.(3)) and leave the slab field without a
    maximum. Full-area zones retarget the construction like any other surface;
    strip zones keep the modeled slab and represent the strip with the Kiva
    foundation's interior horizontal insulation. (Legacy OSut archetypes model
    the bare slab and OMIT the strip; the old BTAP path applied the strip U
    over the full area — both simplifications diverge from the printed table,
    see D-32.)"""
    extent = ground_floor_extent(vintage=vintage, hdd=hdd)
    if extent["extent"] == "full_area":
        _assign_surface(model, surface, "floor", "ground", vintage, hdd,
                        include_films, cache, audit)
        return

    _apply_ground_strip(model, surface, vintage, hdd, include_films,
                        extent["width_m"], cache, audit)


def _apply_ground_strip(model, surface, vintage, hdd, include_films, width_m,
                        cache, audit):
    kiva = opt(surface.adjacentFoundation())
    if kiva is None:
        audit.warn("prescriptive",
                   "ground floor without a Kiva foundation in a perimeter-strip zone — "
                   "the 1.2 m strip (3.2.3.3.(3)) is not representable; slab left as modeled",
                   target=surface.nameString(),
                   article="Table 3.2.3.1.; 3.2.3.3.(3)", ruling="D-32")
        return

    u = max_u(vintage=vintage, surface="floor", boundary="ground", hdd=hdd)
    target = (1.0 / ((1.0 / u) - Constructions.film_r("floor", "ground"))
              if include_films else u)
    slab_r = 0.0
    construction = opt(surface.construction())
    layered = None if construction is None else opt(construction.to_Construction())
    if layered is not None:
        conductance = opt(layered.thermalConductance())
        if conductance is not None and conductance > 0:
            slab_r = 1.0 / conductance
    r_add = (1.0 / target) - slab_r

    key = ("kiva-strip", str(kiva.handle()))
    if key not in cache:
        if r_add > 0:
            k = kiva
            # XPS-like board sized so the strip assembly meets the table U
            mat = openstudio.model.StandardOpaqueMaterial(
                model, "MediumSmooth", 0.029 * r_add, 0.029, 29.0, 1210.0)
            mat.setName(
                f"NECB 3.2.3.3 strip insulation R-{ruby_str(ruby_round(r_add, 3))}")
            k.setInteriorHorizontalInsulationMaterial(mat)
            k.setInteriorHorizontalInsulationDepth(0.0)
            k.setInteriorHorizontalInsulationWidth(width_m)
            audit.decision("prescriptive",
                           "ground floor: slab field left as modeled (no full-area maximum "
                           "below zone 8); perimeter strip insulated via Kiva interior "
                           "horizontal insulation",
                           target=k.nameString(),
                           inputs={"hdd": hdd, "table_u": ruby_round(u, 4),
                                   "strip_target_u_construction": ruby_round(target, 4),
                                   "slab_r": ruby_round(slab_r, 4),
                                   "strip_insulation_r": ruby_round(r_add, 4),
                                   "width_m": width_m},
                           value=(f"insulation R {ruby_str(ruby_round(r_add, 3))} m2K/W x "
                                  f"{ruby_str(width_m)} m from perimeter"),
                           article="Table 3.2.3.1.; 3.2.3.3.(3)", ruling="D-32")
        else:
            audit.info("prescriptive",
                       "slab construction already meets the perimeter-strip U — no strip "
                       "insulation added",
                       target=surface.nameString(),
                       inputs={"hdd": hdd,
                               "strip_target_u_construction": ruby_round(target, 4),
                               "slab_r": ruby_round(slab_r, 4)},
                       article="Table 3.2.3.1.; 3.2.3.3.(3)", ruling="D-32")
        cache[key] = True


def _assign_subsurface(model, sub, sub_class, vintage, hdd, include_films, cache, audit):
    construction = opt(sub.construction())
    base = None if construction is None else opt(construction.to_Construction())
    if base is None:
        audit.warn("prescriptive", "subsurface has no layered construction — skipped",
                   target=sub.nameString())
        return None

    # SimpleGlazing's uFactor IS the overall (with-films) value — films are
    # E+'s job there; only opaque doors get the construction-only solve.
    opaque_door = sub_class == "door" and base.isOpaque()
    target = _target_conductance(vintage, sub_class, "outdoors", hdd,
                                 include_films and opaque_door, audit)
    key = (str(base.handle()), sub_class, target)
    if key not in cache:
        if opaque_door:
            c = Constructions.opaque_at_conductance(model, base, target)
        else:
            c = Constructions.fenestration_at_conductance(model, base, target)
        audit.decision("prescriptive", f"{sub_class} construction set to maximum U",
                       target=c.nameString(),
                       inputs={"hdd": hdd, "target_u": ruby_round(target, 4)},
                       value=(f"conductance "
                              f"{ruby_str(ruby_round(opt_or(c.thermalConductance(), 0.0), 4))}"
                              if opaque_door else
                              f"SimpleGlazing U {ruby_str(ruby_round(target, 4))} "
                              "(SHGC/VT preserved)"),
                       article="Table 3.2.2.3.")
        cache[key] = c
    sub.setConstruction(cache[key])
    return cache[key]


def _subsurface_target_construction(model, sub_class, vintage, hdd, _include_films,
                                    cache, audit):
    """A window/skylight construction at the prescriptive U when the model has
    no existing subsurface of that class to derive one from (needed by the
    FDWR/SRR rebuild on windowless models)."""
    # always SimpleGlazing here — its uFactor is the with-films value
    target = _target_conductance(vintage, sub_class, "outdoors", hdd, False, audit)
    stub = openstudio.model.Construction(model)
    stub.setName(f"NECB {sub_class} base")
    glazing = openstudio.model.SimpleGlazing(model)
    glazing.setUFactor(target)
    glazing.setSolarHeatGainCoefficient(0.60)
    stub.setLayers([glazing])
    c = Constructions.fenestration_at_conductance(model, stub, target)
    stub.remove()
    audit.decision("prescriptive",
                   f"{sub_class} construction created at maximum U (no existing {sub_class})",
                   target=c.nameString(), inputs={"target_u": ruby_round(target, 4)},
                   article="Table 3.2.2.3.")
    return c


def apply_prescriptive(model, *, vintage, hdd=None, apply_fdwr=False,
                       apply_srr=False, include_films=True,
                       thermal_bridging=None, audit=None):
    """Facade (Ruby ``Envelope.apply_prescriptive``)."""
    return apply(model, vintage=vintage, hdd=hdd, apply_fdwr=apply_fdwr,
                 apply_srr=apply_srr, include_films=include_films,
                 thermal_bridging=thermal_bridging, audit=audit)
