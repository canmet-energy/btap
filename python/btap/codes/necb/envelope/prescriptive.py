"""Prescriptive Section 3.2 application (port of btap-necb's
envelope/prescriptive.rb): apply the Table 3.2.2.x/3.2.3.1 target and extent
for exterior/ground surfaces and subsurfaces at the building's HDD, and
optionally rebuild fenestration to the 3.2.1.4 FDWR/SRR limits.

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

import math
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
from btap.modeling.envelope import foundations as Foundations

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
           embedded_floor_inventory=None, ground_floor_perimeters=None):
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
    if ground_floor_perimeters is None:
        strip_extent = _ground_floor_extent(
            ruleset=ruleset, hdd=hdd, embedded_system=False)
        if strip_extent["extent"] == "perimeter_strip":
            ground_floor_perimeters = Foundations.exposed_perimeters(
                model,
                [
                    surface for surface in model.getSurfaces()
                    if _is_ground_floor(surface)
                ],
            )["perimeters"]
        else:
            ground_floor_perimeters = {}

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
    # D-24 interzone pairs, collected rather than warned one at a time: the
    # condition is a property of the MODEL (no intended >10 C difference is
    # established anywhere), so 90 identical sentences on an office archetype
    # told an AHJ reader one fact ninety times and crowded out the rest of the
    # trail. One warning carries the count and every pair.
    interzone_unchanged = []
    simple_ground_applied = []
    unsupported_ground_methods = []
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
                                       include_films, cache, audit,
                                       interzone_unchanged)
            continue

        if boundary == "ground" and surface_class == "floor":
            _assign_ground_floor(
                model, surface, ruleset, hdd, include_films, cache, audit,
                embedded_floor_inventory,
                ground_floor_perimeters=ground_floor_perimeters,
                simple_ground_applied=simple_ground_applied,
                unsupported_ground_methods=unsupported_ground_methods)
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

    if simple_ground_applied:
        audit.decision(
            "prescriptive",
            f"{len(simple_ground_applied)} simple-Ground floor(s) represent "
            "the 1.2 m minimum perimeter extent through a uniform equivalent "
            "UA; strip area is approximated as exposed perimeter x 1.2 m, "
            "capped at floor area, and is NOT an exact geometric band",
            inputs={"floors": len(simple_ground_applied),
                    "surfaces": simple_ground_applied},
            article="3.2.3.3.(3)", ruling="D-32",
        )

    # SPLIT BY WHICH SENTENCE GOVERNS, because one hard-coded citation cannot
    # serve mixed statuses. 3.2.3.3.(3) applies only to floors with NO
    # embedded heating or cooling system — it EXPRESSLY EXCLUDES an embedded
    # floor — so citing it for a known embedded entry cited an article that
    # does not reach the floor it was attached to. An embedded floor's
    # obligation is 3.2.3.3.(4)'s full area in every climate zone, adjudicated
    # by D-105 (Sol, `307`).
    #
    # `unresolved` NEVER REACHES HERE, which is why only two groups exist and
    # why Sol recorded that this adjudication establishes no frozen delta: the
    # `status == "unresolved"` branch above returns at its own D-105 warning
    # before the factor branch can append anything. That matters because Sol
    # ruled `unresolved` is a TOOL EVIDENCE STATE and not a third Code
    # category — the Code offers only "no embedded system, (3) controls" or
    # "embedded, (4) controls" — so it must never be described as though (4)
    # were known to apply. `test_an_unresolved_floor_never_reaches_this_
    # warning` pins the early return: if it is ever removed, an unresolved
    # floor would silently inherit the Sentence (3) citation that Sol's
    # reasoning forbids, and that must surface as a failure.
    # Classified HERE from the inventory rather than carried on each entry,
    # so the audit payload is unchanged and no frozen baseline moves — Sol
    # recorded that this adjudication establishes no frozen delta.
    embedded_rows = [
        row for row in unsupported_ground_methods
        if embedded_floor_inventory.status(row["floor"]) == "embedded"]
    ordinary_rows = [
        row for row in unsupported_ground_methods
        if embedded_floor_inventory.status(row["floor"]) != "embedded"]

    # TWO EXPLICIT CALLS, because `article=` and `ruling=` must be LITERALS.
    # A loop over (key, article, ruling) tuples made both computed, and
    # `test_decisions_registry` scans this source with `ast` — it collects a
    # citation only from an `ast.Constant`, because that static inventory is
    # what proves every `kind: runtime` decision is cited by product code. A
    # computed `ruling=` is invisible to it, so D-105's citation here would
    # not count. Both that test and `test_a_dynamic_swap_is_caught` refused
    # the loop, correctly.
    #
    # NOT about the 8.4 coverage document: that is scoped to Section 8.4 and
    # carries no 3.2.3.3 rows at all, and `citation_counts_baseline.json`
    # does not track Section 3.2 either. The literal buys the static ruling
    # inventory, not a coverage row — checked rather than assumed, because
    # the first version of this comment claimed the coverage document.
    if ordinary_rows:
        audit.warn(
            "prescriptive",
            f"{len(ordinary_rows)} ground floor(s) retain a "
            "submitted foundation method for which BTAP has no validated "
            "NECB reference applier; the building energy target is NOT "
            "established by this transform",
            inputs={"floors": len(ordinary_rows), "surfaces": ordinary_rows},
            article="3.2.3.3.(3)", ruling="D-32",
        )

    if embedded_rows:
        audit.warn(
            "prescriptive",
            f"{len(embedded_rows)} ground floor(s) retain a "
            "submitted foundation method for which BTAP has no validated "
            "NECB reference applier; the building energy target is NOT "
            "established by this transform",
            inputs={"floors": len(embedded_rows), "surfaces": embedded_rows},
            # BOTH rulings, because this one entry makes both claims and a
            # ruling attaches to the runtime choice the entry states. D-105
            # governs WHY this floor has a full-area requirement; D-32 governs
            # the rest of the same action — the submitted whole-foundation
            # method is retained, BTAP has no validated applier for it, and
            # the target is not established by this transform. D-105 contains
            # no whole-foundation translation or no-determination ruling, and
            # the separate prepare/compliance entries that also fire D-32 do
            # NOT repair the local attribution (Sol, `309`).
            article="3.2.3.3.(4)", ruling="D-32 D-105",
        )

    if interzone_unchanged:
        audit.warn(
            "prescriptive",
            f"{len(interzone_unchanged)} conditioned-to-conditioned interzone "
            "assemblies left unchanged because an intended temperature "
            "difference greater than 10 C is NOT established from the model",
            inputs={"assemblies": len(interzone_unchanged),
                    "pairs": interzone_unchanged},
            article="Division A 1.4.1.2.(1)",
            ruling="D-24",
        )

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
                               include_films, cache, audit,
                               interzone_unchanged=None):
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
            # The caller emits ONE aggregated warning. `is None` keeps a direct
            # caller warning per pair rather than silently dropping the
            # disclosure — a warning is never silent.
            if interzone_unchanged is None:
                audit.warn(
                    "prescriptive",
                    "conditioned-to-conditioned interzone assembly left "
                    "unchanged because an intended temperature difference "
                    "greater than 10 C is NOT established from the model",
                    target=" / ".join(pair),
                    article="Division A 1.4.1.2.(1)",
                    ruling="D-24",
                )
            else:
                interzone_unchanged.append(" / ".join(pair))
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
                         embedded_floor_inventory, *,
                         ground_floor_perimeters,
                         simple_ground_applied,
                         unsupported_ground_methods):
    """Table 3.2.3.1 floors row is zone-conditional: zone 8 prescribes the
    table U over the FULL slab area; zones 4-7B prescribe it only within a
    1.2 m perimeter strip (3.2.3.3.(3)) and leave the slab field without a
    maximum. Full-area zones retarget layered constructions directly. In strip
    zones Kiva carries the physical band where available; simple Ground uses
    the declared equivalent-UA approximation in D-32."""
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
    condition = surface.outsideBoundaryCondition()
    if condition in ("GroundFCfactorMethod", "GroundSlabPreprocessorAverage"):
        # A MEASURED zero exposed edge means 3.2.3.3.(3) prescribes no strip
        # segment for this floor at all, so the missing translation costs the
        # target nothing and must not be reported as though it did. Without
        # this, `path.py#prepare_model` filtered the same floor out as
        # zero-edge and let the run determine, while this pass warned that
        # "the building energy target is NOT established by this transform" —
        # the audit and the report contradicted each other on one floor.
        # Fable's `299`, LOW. The test mirrors prepare_model's rule exactly:
        # `<= Foundations.TOLERANCE_M`, and an absent or non-finite
        # measurement is NOT a measured zero and still reports.
        # The extent gate is NOT redundant with the perimeter. The rationale
        # below — "3.2.3.3.(3) prescribes no perimeter-strip segment" — is
        # true only in the STRIP branch. An embedded floor takes `full_area`
        # under 3.2.3.3.(4)(b) whatever its edge measures, and there the
        # missing applier DOES cost the target. Without this check, reaching
        # `prescriptive.apply` directly (which measures embedded floors too)
        # exempted an embedded zero-edge factor floor with a strip rationale
        # that does not apply to it. Fable's `300`.
        perimeter = ground_floor_perimeters.get(name)
        if (extent["extent"] == "perimeter_strip"
                and perimeter is not None and math.isfinite(perimeter)
                and perimeter <= Foundations.TOLERANCE_M):
            audit.info(
                "prescriptive",
                f"ground floor on the {condition} method has a measured zero "
                "exposed edge, so 3.2.3.3.(3) prescribes no perimeter-strip "
                "segment for it and the unsupported-method limitation does "
                "not affect the building energy target",
                target=name,
                inputs={"boundary_condition": condition,
                        "exposed_perimeter_m": perimeter,
                        "zero_tolerance_m": Foundations.TOLERANCE_M,
                        "extent": extent["extent"]},
                article="3.2.3.3.(3)", ruling="D-32")
            return
        unsupported_ground_methods.append({
            "floor": name,
            "boundary_condition": condition,
            "extent": extent["extent"],
            "reason": (
                "BTAP has no validated translation from the NECB assembly U "
                "and placement extent to this whole-foundation method"
            ),
        })
        return

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

    if surface.adjacentFoundation().is_initialized():
        _apply_ground_strip(model, surface, ruleset, hdd, include_films,
                            extent["width_m"], cache, audit)
        return

    if condition == "Ground":
        _apply_simple_ground_equivalent(
            model, surface, ruleset, hdd, include_films, extent["width_m"],
            ground_floor_perimeters.get(name), cache, simple_ground_applied,
            unsupported_ground_methods)
        return

    unsupported_ground_methods.append({
        "floor": name,
        "boundary_condition": condition,
        "extent": extent["extent"],
        "reason": "the ground boundary has no attached Kiva foundation",
    })


def _apply_simple_ground_equivalent(
        model, surface, ruleset, hdd, include_films, width_m, perimeter_m,
        cache, applied, unsupported):
    """Apply D-32's uniform equivalent UA without replacing slab dynamics."""
    name = surface.nameString()
    construction = opt(surface.construction())
    layered = (
        None if construction is None
        else opt(construction.to_LayeredConstruction())
    )
    conductance = (
        None if layered is None
        else opt(layered.thermalConductance())
    )
    area_m2 = float(surface.grossArea())
    invalid = []
    if layered is None:
        invalid.append("surface has no layered construction")
    if conductance is None or not math.isfinite(conductance) or conductance <= 0:
        invalid.append(
            f"construction conductance is {conductance!r}, not a finite "
            "positive value")
    if not math.isfinite(area_m2) or area_m2 <= 0:
        invalid.append(
            f"floor area is {area_m2!r} m2, not a finite positive area")
    if (perimeter_m is None or not math.isfinite(perimeter_m)
            or perimeter_m < 0):
        invalid.append(
            f"exposed perimeter is {perimeter_m!r}, not a finite "
            "non-negative length")
    if invalid:
        unsupported.append({
            "floor": name,
            "boundary_condition": surface.outsideBoundaryCondition(),
            "extent": "perimeter_strip",
            "reason": "; ".join(invalid),
        })
        return

    effective_perimeter = (
        0.0 if perimeter_m <= Foundations.TOLERANCE_M else perimeter_m)
    strip_area_m2 = min(area_m2, effective_perimeter * width_m)
    fraction = strip_area_m2 / area_m2
    film_r = (
        Constructions.film_r("floor", "ground") if include_films else 0.0)
    u_field = 1.0 / ((1.0 / conductance) + film_r)
    u_table = _max_u(
        ruleset=ruleset, surface="floor", boundary="ground", hdd=hdd)
    u_strip = min(u_field, u_table)
    u_equivalent = fraction * u_strip + (1.0 - fraction) * u_field
    target_conductance = 1.0 / ((1.0 / u_equivalent) - film_r)

    changed = not math.isclose(
        target_conductance, conductance, rel_tol=1e-10, abs_tol=1e-10)
    if changed:
        key = (
            str(construction.handle()), "floor", "ground",
            "simple-equivalent-ua", target_conductance,
        )
        if key not in cache:
            cache[key] = Constructions.opaque_at_conductance(
                model, layered, target_conductance,
                name_discriminator=f"D32 {name}")
        surface.setConstruction(cache[key])

    applied.append({
        "floor": name,
        "exposed_perimeter_m": ruby_round(effective_perimeter, 4),
        "floor_area_m2": ruby_round(area_m2, 4),
        "strip_width_m": width_m,
        "strip_area_approx_m2": ruby_round(strip_area_m2, 4),
        "strip_area_fraction": ruby_round(fraction, 6),
        "field_u_overall_w_m2k": ruby_round(u_field, 6),
        "table_u_overall_w_m2k": ruby_round(u_table, 6),
        "strip_u_overall_w_m2k": ruby_round(u_strip, 6),
        "equivalent_u_overall_w_m2k": ruby_round(u_equivalent, 6),
        "target_u_construction_w_m2k": ruby_round(target_conductance, 6),
        "construction_changed": changed,
    })


def _construction_thickness(construction):
    thickness = 0.0
    for layer in construction.layers():
        material = opt(layer.to_StandardOpaqueMaterial())
        if material is not None:
            thickness += material.thickness()
    return thickness


def _polygon_perimeter(vertices):
    return sum(
        (vertices[(index + 1) % len(vertices)] - vertex).length()
        for index, vertex in enumerate(vertices)
    )


def _floor_exposed_perimeter(floor, vertices):
    geometric_perimeter = _polygon_perimeter(vertices)
    exposed = opt(floor.surfacePropertyExposedFoundationPerimeter())
    if exposed is None:
        # This is also the forward translator's default for a Kiva floor.
        return geometric_perimeter

    total = opt(exposed.totalExposedPerimeter())
    if total is not None:
        return total
    return exposed.exposedPerimeterFraction() * geometric_perimeter


def _wall_floor_contact_length(vertices, floor_elevation):
    coplanar = {
        index for index, vertex in enumerate(vertices)
        if abs(vertex.z() - floor_elevation) <= 1e-6
    }
    contact = sum(
        (vertices[(index + 1) % len(vertices)] - vertex).length()
        for index, vertex in enumerate(vertices)
        if index in coplanar
        and (index + 1) % len(vertices) in coplanar
    )
    if contact > 0:
        return contact
    if len(vertices) < 2:
        return None
    lowest = sorted(vertices, key=lambda vertex: vertex.z())[:2]
    return (lowest[1] - lowest[0]).length()


def _foundation_wall_profile(foundation, floor):
    floor_space = opt(floor.space())
    floor_zone = (
        None if floor_space is None
        else opt(floor_space.thermalZone())
    )
    if floor_zone is None:
        return None

    floor_vertices = list(floor_space.transformation() * floor.vertices())
    if not floor_vertices:
        return None
    floor_elevation = sum(vertex.z() for vertex in floor_vertices) / len(floor_vertices)
    exposed_floor_perimeter = _floor_exposed_perimeter(floor, floor_vertices)

    wall_instances = []
    other_floors = []
    same_zone_other_floors = []
    for candidate in sorted_by_name(foundation.surfaces()):
        if candidate.surfaceType() == "Floor":
            if candidate.handle() != floor.handle():
                other_floors.append(candidate.nameString())
                space = opt(candidate.space())
                zone = None if space is None else opt(space.thermalZone())
                if zone is not None and zone.handle() == floor_zone.handle():
                    same_zone_other_floors.append(candidate.nameString())
            continue
        if candidate.surfaceType() != "Wall":
            continue

        space = opt(candidate.space())
        zone = None if space is None else opt(space.thermalZone())
        if zone is None or zone.handle() != floor_zone.handle():
            continue

        vertices = list(space.transformation() * candidate.vertices())
        if not vertices:
            return None
        contact_length = _wall_floor_contact_length(vertices, floor_elevation)
        if contact_length is None:
            return None
        wall_instances.append((
            candidate.nameString(),
            max(vertex.z() for vertex in vertices)
            - min(vertex.z() for vertex in vertices),
            contact_length,
        ))

    return (
        wall_instances,
        other_floors,
        same_zone_other_floors,
        sum(contact for _wall, _height, contact in wall_instances),
        exposed_floor_perimeter,
    )


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

    internal_source = opt(construction.to_ConstructionWithInternalSource())
    if internal_source is not None:
        audit.warn(
            "prescriptive",
            "ENERGYPLUS REJECTS an internal-source construction on a "
            "Foundation surface — this input representation cannot simulate "
            "unless the construction or boundary is replaced",
            target=name,
            inputs={
                "construction": internal_source.nameString(),
                "foundation": foundation.nameString(),
            },
            article="3.2.3.3.(5)",
            ruling="D-105",
        )

    insulation = opt(construction.insulation())
    floor_thickness = _construction_thickness(construction)
    wall_profile = _foundation_wall_profile(foundation, surface)
    if (insulation is None or floor_thickness <= 0
            or wall_profile is None):
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

    (
        wall_instances,
        other_floors,
        same_zone_other_floors,
        selected_wall_perimeter,
        exposed_floor_perimeter,
    ) = wall_profile
    foundation_wall_height = max(
        (height for _wall, height, _contact in wall_instances), default=0.0)
    height_groups = defaultdict(list)
    for wall_name, height, _contact in wall_instances:
        height_groups[ruby_round(height, 3)].append(wall_name)
    grouped_instances = [
        {"height_m": height, "walls": sorted(walls)}
        for height, walls in sorted(height_groups.items())
    ]
    if len(grouped_instances) > 1:
        audit.warn(
            "prescriptive",
            "Kiva foundation has MIXED adjoining wall heights — its one "
            "vertical-insulation depth uses the tallest instance and "
            "over-insulates the shorter instances",
            target=foundation.nameString(),
            inputs={
                "floor": name,
                "wall_instances": grouped_instances,
                "over_reached_wall_instances": grouped_instances[:-1],
            },
            article="3.2.3.3.(5)",
            ruling="D-105",
        )
    zero_height_remainder = exposed_floor_perimeter - selected_wall_perimeter
    # EnergyPlus drops a remaining exposed perimeter below 0.001 m.
    if wall_instances and zero_height_remainder >= 0.001:
        audit.warn(
            "prescriptive",
            "Kiva foundation has a PARTIAL-PERIMETER wall condition — "
            "EnergyPlus creates a zero-wall-height slab-remainder instance, "
            "but the foundation's one vertical-insulation depth uses the "
            "tallest wall and over-insulates that remainder",
            target=foundation.nameString(),
            inputs={
                "floor": name,
                "selected_wall_perimeter_m":
                    ruby_round(selected_wall_perimeter, 4),
                "exposed_floor_perimeter_m":
                    ruby_round(exposed_floor_perimeter, 4),
                "zero_wall_height_remainder_m":
                    ruby_round(zero_height_remainder, 4),
            },
            article="3.2.3.3.(5)",
            ruling="D-105",
        )
    if other_floors:
        if same_zone_other_floors:
            action = (
                "Kiva foundation is SHARED by multiple floor surfaces — "
                "ENERGYPLUS REPORTS same-zone sharing as a Severe input error "
                "('only one floor per Foundation:Kiva Object allowed'), "
                "simulates every instance with the same walls, and BTAP "
                "CLASSIFIES the run as not clean; its "
                "Sentence (3) strip and Sentence (5) continuation fields also "
                "apply to every instance"
            )
        else:
            action = (
                "Kiva foundation is SHARED by multiple floor surfaces — its "
                "Sentence (3) strip and Sentence (5) continuation fields apply "
                "to every EnergyPlus instance and can affect the other floors"
            )
        audit.warn(
            "prescriptive",
            action,
            target=foundation.nameString(),
            inputs={
                "floor": name,
                "other_floor_instances": sorted(other_floors),
                "same_zone_floor_instances": sorted(same_zone_other_floors),
            },
            article="3.2.3.3.(5)",
            ruling="D-105",
        )

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
        raise RuntimeError(
            f"{surface.nameString()} has no adjacent Kiva foundation")

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
