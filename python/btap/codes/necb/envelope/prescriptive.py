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
inclination with the unconditioned enclosure credited at U 6.25. Both
sentence numbers are EDITION-OWNED and resolved through the ruleset:
NECB 2020 numbers them (6) and (4), NECB 2025 numbers them (4) and (3) — the
article was restructured from eight sentences to four without its own number
changing, so a literal was wrong on every 2025 run (Sol, applicability review).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import openstudio

from btap._compat import opt, opt_or, ruby_round, ruby_str, sorted_by_name
from btap.audit import AuditLog
from btap.codes import resolve
from btap.codes.necb.envelope import climate, fenestration
from btap.codes.necb.envelope import thermal_bridging as thermal_bridging_module
from btap.codes.necb.envelope.rules import (
    _ground_floor_extent,
    _max_fdwr,
    _max_srr,
    _max_u,
)
from btap.modeling.envelope import constructions as Constructions

SUBSURFACE_CLASS = {
    "FixedWindow": "window", "OperableWindow": "window", "GlassDoor": "window",
    "Skylight": "skylight", "TubularDaylightDome": "skylight",
    "TubularDaylightDiffuser": "skylight",
    "Door": "door", "OverheadDoor": "door",
}

SURFACE_CLASS = {"Wall": "wall", "RoofCeiling": "roofceiling", "Floor": "floor"}

_RADIANT_FLOOR_GETTERS = (
    "getZoneHVACLowTempRadiantVarFlows",
    "getZoneHVACLowTempRadiantConstFlows",
    "getZoneHVACLowTemperatureRadiantElectrics",
)
_FLOOR_RADIANT_TYPES = {"Floors", "CeilingsAndFloors", "AllSurfaces"}


@dataclass
class _EmbeddedFloorInventory:
    embedded: set[str] = field(default_factory=set)
    unresolved: set[str] = field(default_factory=set)
    evidence: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    def status(self, surface_name):
        if surface_name in self.embedded:
            return "embedded"
        if surface_name in self.unresolved:
            return "unresolved"
        return "ordinary"


def _is_ground_floor(surface):
    return surface.surfaceType() == "Floor" and boundary_of(surface) == "ground"


def _zone_ground_floors(zone):
    return [
        surface
        for space in zone.spaces()
        for surface in space.surfaces()
        if _is_ground_floor(surface)
    ]


def _embedded_floor_inventory(model):
    """Inventory embedded-floor applicability while proposed HVAC exists.

    Surface names are the handoff key because OpenStudio changes handles when
    cloning but preserves names. OpenStudio enforces unique object names
    case-insensitively, so the names remain unambiguous through the clone.
    """
    inventory = _EmbeddedFloorInventory()
    ground_floors = [surface for surface in model.getSurfaces()
                     if _is_ground_floor(surface)]

    for surface in ground_floors:
        name = surface.nameString()
        construction = opt(surface.construction())
        internal = (
            None if construction is None
            else opt(construction.to_ConstructionWithInternalSource())
        )
        if internal is not None:
            inventory.embedded.add(name)
            inventory.evidence[name].append(
                f"internal-source construction '{internal.nameString()}'")

    for getter_name in _RADIANT_FLOOR_GETTERS:
        for equipment in getattr(model, getter_name)():
            radiant_surface_type = opt(equipment.radiantSurfaceType())
            if radiant_surface_type not in _FLOOR_RADIANT_TYPES:
                continue

            selected = list(equipment.surfaces())
            selected_ground = [surface for surface in selected
                               if _is_ground_floor(surface)]
            for surface in selected_ground:
                name = surface.nameString()
                inventory.embedded.add(name)
                inventory.evidence[name].append(
                    f"{equipment.iddObjectType().valueName()} "
                    f"'{equipment.nameString()}' construction-derived "
                    "surface association")

            if selected:
                continue

            zone = opt(equipment.thermalZone())
            if zone is None:
                continue
            for surface in _zone_ground_floors(zone):
                name = surface.nameString()
                inventory.unresolved.add(name)
                inventory.evidence[name].append(
                    f"{equipment.iddObjectType().valueName()} "
                    f"'{equipment.nameString()}' declares floor radiant service "
                    "but resolves no surfaces")

    return inventory


def apply(model, *, code, hdd=None, apply_fdwr=False, apply_srr=False,
          include_films=True, thermal_bridging=None, audit=None):
    """PORT NOTE: the ``thermal_bridging`` KEYWORD keeps the Ruby spelling, so
    the sibling MODULE is imported as ``thermal_bridging_module`` above — the
    parameter would otherwise shadow it inside this function."""
    return _apply(model, resolve(code), hdd=hdd,
                  apply_fdwr=apply_fdwr, apply_srr=apply_srr,
                  include_films=include_films, thermal_bridging=thermal_bridging,
                  audit=audit)


def _apply(model, ruleset, *, hdd=None, apply_fdwr=False, apply_srr=False,
           include_films=True, thermal_bridging=None, audit=None,
           embedded_floor_inventory=None):
    """The prescriptive pass over ONE resolved edition: the surface loop and
    every table lookup under it read the same :class:`btap.codes.Ruleset`
    rather than re-resolving the edition per surface (Stage 6)."""
    audit = audit if audit is not None else AuditLog()
    hdd = climate.hdd18(model, edition=ruleset.edition, hdd=hdd, audit=audit)
    if hdd is None:
        raise ValueError("HDD unresolvable: pass hdd: explicitly or set a weather file")
    embedded_floor_inventory = (
        _embedded_floor_inventory(model)
        if embedded_floor_inventory is None
        else embedded_floor_inventory
    )

    audit.info("prescriptive", "film convention",
               value=("code-literal: table U treated as overall transmittance incl. air "
                      "films (1.4.1.2 definition; films subtracted from construction)"
                      if include_films else
                      "legacy-BTAP-compatible: table U applied as construction-only "
                      "conductance"),
               article="Division A 1.4.1.2.(1)", ruling="D-23")

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
            _assign_interzone_envelope(model, surface, surface_class, ruleset, hdd,
                                       include_films, cache, audit)
            continue

        if boundary == "ground" and surface_class == "floor":
            _assign_ground_floor(
                model, surface, ruleset, hdd, include_films, cache, audit,
                embedded_floor_inventory)
        else:
            _assign_surface(model, surface, surface_class, boundary, ruleset, hdd,
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

            construction = _assign_subsurface(model, sub, sub_class, ruleset, hdd,
                                              include_films, cache, audit)
            if sub_class == "window" and window_construction is None:
                window_construction = construction
            if sub_class == "skylight" and skylight_construction is None:
                skylight_construction = construction

    if outside_envelope > 0:
        audit.info("prescriptive",
                   "exterior/ground surfaces of unconditioned spaces left untouched — "
                   "not part of the building envelope",
                   inputs={"surfaces": outside_envelope},
                   article="Division A 1.4.1.2.(1)",
                   ruling="D-24")

    if apply_fdwr:
        limit = _max_fdwr(ruleset=ruleset, hdd=hdd, audit=audit)
        if window_construction is None:
            window_construction = _subsurface_target_construction(
                model, "window", ruleset, hdd, include_films, cache, audit)
        fenestration.apply_fdwr(model, limit, window_construction, audit=audit)
    if apply_srr:
        limit = _max_srr(ruleset=ruleset, audit=audit)
        if skylight_construction is None:
            skylight_construction = _subsurface_target_construction(
                model, "skylight", ruleset, hdd, include_films, cache, audit)
        fenestration.apply_srr(model, limit, skylight_construction, audit=audit)

    # 3.1.1.7: table values are EFFECTIVE transmittance — uprate for thermal
    # bridging when requested (psi set name/dict, or True for the default set).
    # Ruby truthiness: ONLY nil/false are falsy there, so an empty string or
    # an empty psi dict still takes the uprate branch — `if thermal_bridging`
    # must not become a bare Python truth test.
    if thermal_bridging is not None and thermal_bridging is not False:
        psi = "regular (BETBG)" if thermal_bridging is True else thermal_bridging
        thermal_bridging_module._apply(model, ruleset=ruleset, hdd=hdd, psi_set=psi,
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


def _assign_interzone_envelope(model, surface, surface_class, ruleset, hdd,
                               include_films, cache, audit):
    """Apply the envelope row to an interzone assembly where its scope is known."""
    if surface.outsideBoundaryCondition() != "Surface":
        return

    adj = opt(surface.adjacentSurface())
    if adj is None:
        return

    adj_space = opt(adj.space())
    if adj_space is None:
        return

    if inside_envelope(adj_space):
        pair = sorted((surface.nameString(), adj.nameString()))
        if surface.nameString() == pair[0]:
            audit.warn(
                "prescriptive",
                "conditioned-to-conditioned interzone assembly left unchanged "
                "because an intended temperature difference greater than 10 C "
                "is NOT established from the model",
                target=" / ".join(pair),
                article="Division A 1.4.1.2.(1)",
                ruling="D-24",
            )
        return

    construction = opt(surface.construction())
    layered = (
        None if construction is None
        else opt(construction.to_LayeredConstruction())
    )
    if layered is None:
        audit.warn("prescriptive",
                   "envelope surface to unconditioned space has no layered construction — skipped",
                   target=surface.nameString(),
                   article="Division A 1.4.1.2.(1)",
                   ruling="D-24")
        return

    u = _max_u(ruleset=ruleset, surface=surface_class, boundary="outdoors", hdd=hdd)
    target = _target_conductance(
        ruleset, surface_class, "outdoors", hdd, include_films, audit)
    key = (str(construction.handle()), surface_class, "interzone-conservative", target)
    if key not in cache:
        c = Constructions.opaque_at_conductance(model, layered, target)
        audit.decision("prescriptive",
                       f"envelope {surface_class} to unconditioned space set to "
                       "the exterior maximum U without the enclosed-space credit",
                       target=c.nameString(),
                       inputs={"hdd": hdd, "table_u": ruby_round(u, 4),
                               "target_u_construction": ruby_round(target, 4),
                               "adjacent_space": adj_space.nameString(),
                               "vented_status": "not represented by the model"},
                       value=("conductance "
                              f"{ruby_str(ruby_round(opt_or(c.thermalConductance(), 0.0), 4))}"
                              " W/m2K"),
                       article="Note A-{}".format(
                           ruleset.article("enclosed_unconditioned_credit")),
                       ruling="D-24")
        audit.info(
            "prescriptive",
            "interzone envelope table class selected by assembly inclination",
            target=surface.nameString(),
            value=surface_class,
            article=ruleset.article("assembly_inclination"),
            ruling="D-24")
        cache[key] = c
    surface.setConstruction(cache[key])
    adj.setConstruction(cache[key])


def _target_conductance(ruleset, surface_class, boundary, hdd, include_films, audit):
    u = _max_u(ruleset=ruleset, surface=surface_class, boundary=boundary, hdd=hdd)
    if not include_films:
        return u

    r_films = Constructions.film_r(surface_class, boundary)
    return 1.0 / ((1.0 / u) - r_films)


def _assign_surface(model, surface, surface_class, boundary, ruleset, hdd,
                    include_films, cache, audit):
    construction = opt(surface.construction())
    layered = (
        None if construction is None
        else opt(construction.to_LayeredConstruction())
    )
    if layered is None:
        audit.warn("prescriptive", "surface has no layered construction — skipped",
                   target=surface.nameString())
        return

    target = _target_conductance(ruleset, surface_class, boundary, hdd, include_films, audit)
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
    return cache[key]


def _assign_ground_floor(model, surface, ruleset, hdd, include_films, cache, audit,
                         embedded_floor_inventory):
    """Table 3.2.3.1 floors row is zone-conditional: zone 8 prescribes the
    table U over the FULL slab area; zones 4-7B prescribe it only within a
    1.2 m perimeter strip (3.2.3.3.(3)) and leave the slab field without a
    maximum. Full-area zones retarget the construction like any other surface;
    strip zones keep the modeled slab and represent the strip with the Kiva
    foundation's interior horizontal insulation. (Legacy OSut archetypes model
    the bare slab and OMIT the strip; the old BTAP path applied the strip U
    over the full area — both simplifications diverge from the printed table,
    see D-32.)"""
    name = surface.nameString()
    status = embedded_floor_inventory.status(name)
    evidence = embedded_floor_inventory.evidence.get(name, [])
    if status == "unresolved":
        audit.warn(
            "prescriptive",
            "embedded-system applicability UNRESOLVED — a floor-radiant object "
            "does not identify its served surfaces, so the ordinary perimeter-strip "
            "rule is not guessed and the slab is left as modeled",
            target=name,
            inputs={"evidence": evidence, "code": ruleset.id,
                    "edition": ruleset.edition},
            article="3.2.3.3.(4)(b)",
            ruling="D-105",
        )
        return

    embedded = status == "embedded"
    extent = _ground_floor_extent(
        ruleset=ruleset, hdd=hdd, embedded_system=embedded)
    if extent["extent"] == "full_area":
        construction = _assign_surface(
            model, surface, "floor", "ground", ruleset, hdd,
            include_films, cache, audit)
        if embedded and construction is not None:
            audit.decision(
                "prescriptive",
                "ground floor with an embedded heating/cooling system insulated "
                "over its FULL AREA",
                target=name,
                inputs={"hdd": hdd, "code": ruleset.id,
                        "edition": ruleset.edition, "detected_by": evidence},
                value=f"full-area construction '{construction.nameString()}'",
                article="3.2.3.3.(4)(b)",
                ruling="D-105",
            )
            _apply_embedded_floor_perimeter(
                surface, construction, audit)
        return

    _apply_ground_strip(model, surface, ruleset, hdd, include_films,
                        extent["width_m"], cache, audit)


def _construction_thickness(construction):
    thickness = 0.0
    for layer in construction.layers():
        material = opt(layer.to_StandardOpaqueMaterial())
        if material is not None:
            thickness += material.thickness()
    return thickness


def _foundation_wall_height(foundation):
    heights = []
    for surface in foundation.surfaces():
        if surface.surfaceType() != "Wall":
            continue
        space = opt(surface.space())
        if space is None:
            return None
        vertices = list(space.transformation() * surface.vertices())
        if not vertices:
            return None
        heights.append(
            max(vertex.z() for vertex in vertices)
            - min(vertex.z() for vertex in vertices)
        )
    return max(heights, default=0.0)


def _apply_embedded_floor_perimeter(surface, construction, audit):
    """Represent Sentence (5)'s vertical continuation for a detected floor."""
    name = surface.nameString()
    foundation = opt(surface.adjacentFoundation())
    if foundation is None:
        audit.warn(
            "prescriptive",
            "embedded ground floor has no Kiva foundation — the vertical "
            "perimeter continuation is not representable",
            target=name,
            article="3.2.3.3.(5)",
            ruling="D-105",
        )
        return

    insulation = opt(construction.insulation())
    floor_thickness = _construction_thickness(construction)
    foundation_wall_height = _foundation_wall_height(foundation)
    if (insulation is None or floor_thickness <= 0
            or foundation_wall_height is None):
        audit.warn(
            "prescriptive",
            "embedded ground floor's insulation layer, floor thickness, or "
            "adjoining foundation-wall height is "
            "UNRESOLVED — the vertical perimeter continuation is not representable",
            target=name,
            article="3.2.3.3.(5)",
            ruling="D-105",
        )
        return

    depth = foundation_wall_height + floor_thickness
    exterior = opt(foundation.exteriorVerticalInsulationMaterial())
    exterior_depth = opt(foundation.exteriorVerticalInsulationDepth())
    if exterior is not None and exterior_depth is not None and exterior_depth >= depth:
        audit.info(
            "prescriptive",
            "exterior foundation-wall insulation reaches the bottom of the "
            "embedded floor — the vertical perimeter exception applies",
            target=name,
            inputs={"floor_thickness_m": ruby_round(floor_thickness, 4),
                    "adjoining_foundation_wall_height_m":
                        ruby_round(foundation_wall_height, 4),
                    "required_vertical_depth_m": ruby_round(depth, 4),
                    "exterior_insulation_depth_m": ruby_round(exterior_depth, 4)},
            article="3.2.3.3.(5)",
            ruling="D-105",
        )
        return

    interior = opt(foundation.interiorVerticalInsulationMaterial())
    interior_depth = opt(foundation.interiorVerticalInsulationDepth())
    if interior is None or interior_depth is None or interior_depth < depth:
        if not foundation.setInteriorVerticalInsulationMaterial(insulation):
            raise RuntimeError(
                f"could not assign vertical perimeter insulation to "
                f"{foundation.nameString()}")
        if not foundation.setInteriorVerticalInsulationDepth(depth):
            raise RuntimeError(
                f"could not set vertical perimeter insulation depth on "
                f"{foundation.nameString()}")
    audit.decision(
        "prescriptive",
        "full-area floor insulation continued vertically around the perimeter",
        target=foundation.nameString(),
        inputs={
            "floor": name,
            "floor_thickness_m": ruby_round(floor_thickness, 4),
            "adjoining_foundation_wall_height_m":
                ruby_round(foundation_wall_height, 4),
            "required_vertical_depth_m": ruby_round(depth, 4),
        },
        value=f"interior vertical insulation depth {ruby_str(ruby_round(depth, 4))} m",
        article="3.2.3.3.(5)",
        ruling="D-105",
    )


def _apply_ground_strip(model, surface, ruleset, hdd, include_films, width_m,
                        cache, audit):
    kiva = opt(surface.adjacentFoundation())
    if kiva is None:
        audit.warn("prescriptive",
                   "ground floor without a Kiva foundation in a perimeter-strip zone — "
                   "the 1.2 m strip (3.2.3.3.(3)) is not representable; slab left as modeled",
                   target=surface.nameString(),
                   article="3.2.3.3.(3)", ruling="D-32")
        return

    u = _max_u(ruleset=ruleset, surface="floor", boundary="ground", hdd=hdd)
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
                           article="3.2.3.3.(3)", ruling="D-32")
        else:
            audit.info("prescriptive",
                       "slab construction already meets the perimeter-strip U — no strip "
                       "insulation added",
                       target=surface.nameString(),
                       inputs={"hdd": hdd,
                               "strip_target_u_construction": ruby_round(target, 4),
                               "slab_r": ruby_round(slab_r, 4)},
                       article="3.2.3.3.(3)", ruling="D-32")
        cache[key] = True


def _assign_subsurface(model, sub, sub_class, ruleset, hdd, include_films, cache, audit):
    construction = opt(sub.construction())
    base = None if construction is None else opt(construction.to_Construction())
    if base is None:
        audit.warn("prescriptive", "subsurface has no layered construction — skipped",
                   target=sub.nameString())
        return None

    # SimpleGlazing's uFactor IS the overall (with-films) value — films are
    # E+'s job there; only opaque doors get the construction-only solve.
    opaque_door = sub_class == "door" and base.isOpaque()
    target = _target_conductance(ruleset, sub_class, "outdoors", hdd,
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


def _subsurface_target_construction(model, sub_class, ruleset, hdd, _include_films,
                                    cache, audit):
    """A window/skylight construction at the prescriptive U when the model has
    no existing subsurface of that class to derive one from (needed by the
    FDWR/SRR rebuild on windowless models)."""
    # always SimpleGlazing here — its uFactor is the with-films value
    target = _target_conductance(ruleset, sub_class, "outdoors", hdd, False, audit)
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


def apply_prescriptive(model, *, code, hdd=None, apply_fdwr=False,
                       apply_srr=False, include_films=True,
                       thermal_bridging=None, audit=None):
    """Facade (Ruby ``Envelope.apply_prescriptive``)."""
    return _apply(model, resolve(code), hdd=hdd,
                  apply_fdwr=apply_fdwr, apply_srr=apply_srr,
                  include_films=include_films, thermal_bridging=thermal_bridging,
                  audit=audit)
