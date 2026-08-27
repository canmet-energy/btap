"""The performance-path reference ENVELOPE (2020: 8.4.4.1.(2)/8.4.4.3./8.4.4.4.;
2025: 8.4.5.x, verbatim text) — greenfield: no legacy implementation exists.
Operates IN PLACE on a model the caller clones, so a compliance umbrella can
chain the hvac domain's reference_hvac and this transform on ONE clone with
ONE audit (the AuditLog schemas are identical).

Port of btap-necb's envelope/reference.rb.

Order of operations:
 1. prescriptive U-values (8.4.4.1.(2): the reference envelope meets 3.2)
 2. FDWR/SRR overage -> PROPORTIONAL per-orientation scaling of existing
    fenestration (8.4.4.3.(3) — never a window rebuild)
 3. roof solar absorptance 0.7 iff the proposed model used actual values
    (8.4.4.3.(1)/(2))
 4. remove Space/Building shading + shading controls, keep Site shading
    (8.4.4.3.(4)/(5))
 5. fenestration optics preserved by construction (8.4.4.3.(8))
 6. lightweight construction rebuild at the prescriptive targets (8.4.4.4.(1))
 7. air leakage default: I_AGW = (5/75)^0.6 x 1.50 x S/A_AGW applied per space
    (8.4.4.3.(6) + 8.4.3.3.(3) + 8.4.2.9.(2))
 8. article-coverage emission (every article, statuses + citations, warnings
    for anything partial)
"""

from __future__ import annotations

import re

import openstudio

from btap._compat import opt, opt_or, ruby_round, ruby_str, sorted_by_name
from btap.audit import AuditLog, emit_coverage
from btap.modeling.envelope import geometry as Geometry
from btap.necb.envelope import climate, prescriptive as Prescriptive
from btap.necb.envelope.rules import max_fdwr, max_srr

AIR_LEAKAGE_I75 = 1.50   # L/(s.m2) @ 75 Pa, 8.4.3.3.(3)
AIR_LEAKAGE_N = 0.60     # flow exponent, 8.4.2.9.(2)

# Note A-8.4.4.4.(1) wood-frame example assembly (Figure/Table 1-1):
# 40.8 kg/m2 areal mass, 45.5 kJ/(m2.K) heat capacity. The rebuilt lightweight
# layer is calibrated to these at a fixed 0.15 m thickness (density and cp
# derived; conductivity from the target resistance).
LIGHTWEIGHT_MASS_KG_M2 = 40.8
LIGHTWEIGHT_HEAT_CAPACITY_J_M2K = 45_500.0
LIGHTWEIGHT_THICKNESS_M = 0.15

_GROUND_OR_FOUNDATION_RE = re.compile(r"Ground|Foundation", re.IGNORECASE)


def apply(model, *, vintage, hdd=None, actual_roof_absorptance_used=False,
          thermal_bridging=None, audit=None):
    from btap.necb import envelope

    audit = audit if audit is not None else AuditLog()
    prefix = "8.4.5" if str(vintage) == "2025" else "8.4.4"
    hdd = climate.hdd18(model, hdd=hdd, audit=audit)
    if hdd is None:
        raise ValueError("HDD unresolvable: pass hdd: explicitly or set a weather file")

    # 1. prescriptive Section 3.2 on the reference (no window rebuild here)
    Prescriptive.apply(model, vintage=vintage, hdd=hdd,
                       thermal_bridging=thermal_bridging, audit=audit)
    audit.decision("reference", "reference envelope meets prescriptive Section 3.2",
                   inputs={"hdd": hdd}, article=f"{prefix}.1.(2)")

    _scale_fenestration_to_limits(model, vintage, hdd, prefix, audit)
    roof_absorptance = (envelope.rules(vintage)["reference_envelope"]
                        ["roof_absorptance_if_actual_used"])
    _apply_roof_absorptance(model, actual_roof_absorptance_used, roof_absorptance,
                            prefix, audit)
    _strip_shading(model, prefix, audit)
    audit.info("reference",
               "fenestration optics (SHGC/VT) preserved — only U changed by construction "
               "of the prescriptive transform",
               article=f"{prefix}.3.(8)")
    _apply_lightweight_construction(model, vintage, hdd, prefix, audit)
    apply_air_leakage_default(model, prefix, audit)
    _emit_article_coverage(vintage, audit)
    return audit


def _scale_fenestration_to_limits(model, vintage, hdd, prefix, audit):
    """8.4.4.3.(3): where the proposed FDWR/SRR exceeds the 3.2.1.4 limits,
    scale the EXISTING fenestration proportionally (per orientation — a
    uniform ratio on every wall preserves each orientation's share)."""
    walls = Geometry.exposed_walls(model)
    limit = max_fdwr(vintage=vintage, hdd=hdd)
    if walls["fdwr"] is not None and walls["fdwr"] > limit:
        ratio = limit / walls["fdwr"]
        for w in walls["walls"]:
            Geometry.scale_subsurfaces(w, ratio)
        resulting = Geometry.exposed_walls(model)["fdwr"]
        shown = ruby_str(None if resulting is None else ruby_round(resulting, 4))
        audit.decision("reference",
                       "proposed FDWR exceeds the limit — fenestration scaled "
                       "proportionally per orientation",
                       inputs={"proposed_fdwr": ruby_round(walls["fdwr"], 4),
                               "limit": ruby_round(limit, 4)},
                       value=(f"area ratio {ruby_str(ruby_round(ratio, 4))} applied to every "
                              f"subsurface (resulting FDWR {shown})"),
                       article=f"{prefix}.3.(3)")
    else:
        audit.info("reference",
                   "proposed FDWR within the limit — fenestration areas identical to proposed",
                   inputs={"proposed_fdwr": (None if walls["fdwr"] is None
                                             else ruby_round(walls["fdwr"], 4)),
                           "limit": ruby_round(limit, 4)},
                   article=f"{prefix}.3.(3)")

    roofs = Geometry.exposed_roofs(model)
    srr_limit = max_srr(vintage=vintage)
    if not (roofs["srr"] is not None and roofs["srr"] > srr_limit):
        return

    ratio = srr_limit / roofs["srr"]
    for r in roofs["roofs"]:
        Geometry.scale_subsurfaces(r, ratio)
    audit.decision("reference",
                   "proposed skylight area exceeds the limit — skylights scaled proportionally",
                   inputs={"proposed_srr": ruby_round(roofs["srr"], 4), "limit": srr_limit},
                   value=f"area ratio {ruby_str(ruby_round(ratio, 4))}",
                   article=f"{prefix}.3.(3)")


def _apply_roof_absorptance(model, actual_used, roof_absorptance, prefix, audit):
    """8.4.4.3.(1)/(2): roof solar absorptance 0.7 ONLY when the proposed model
    used actual absorptance values; otherwise identical to proposed."""
    if not actual_used:
        audit.info("reference",
                   "proposed roof absorptance not flagged as actual — reference keeps the "
                   "proposed value",
                   article=f"{prefix}.3.(2)(a)")
        return

    changed = 0
    for surface in sorted_by_name(model.getSurfaces()):
        if not (surface.surfaceType() == "RoofCeiling"
                and surface.outsideBoundaryCondition() == "Outdoors"):
            continue
        construction = opt(surface.construction())
        layered = None if construction is None else opt(construction.to_Construction())
        if layered is None:
            continue

        outer = opt(layered.layers()[0].to_OpaqueMaterial())
        if outer is None:
            continue

        outer.setSolarAbsorptance(openstudio.OptionalDouble(roof_absorptance))
        changed += 1
    audit.decision("reference",
                   f"roof solar absorptance set to {ruby_str(roof_absorptance)} "
                   "(proposed used actual values)",
                   inputs={"roofs_changed": changed}, value=roof_absorptance,
                   article=f"{prefix}.3.(2)(b)")


def _strip_shading(model, prefix, audit):
    """8.4.4.3.(4): remove permanent fenestration shading projections
    (Space/Building shading groups + shading controls); (5): keep exterior
    shading from nearby structures (Site groups)."""
    removed = []
    kept = []
    for group in sorted_by_name(model.getShadingSurfaceGroups()):
        if group.shadingSurfaceType() == "Site":
            kept.append(group.nameString())
        else:
            removed.append(f"{group.nameString()} ({group.shadingSurfaceType()})")
            group.remove()
    controls = len(model.getShadingControls())
    for control in list(model.getShadingControls()):
        control.remove()
    audit.decision("reference",
                   "permanent shading projections removed; nearby-structure shading kept",
                   inputs={"removed_groups": len(removed),
                           "shading_controls_removed": controls,
                           "site_groups_kept": len(kept)},
                   value=("no Space/Building shading present" if not removed
                          else "; ".join(removed)),
                   article=f"{prefix}.3.(4)-(5)")


def _apply_lightweight_construction(model, vintage, hdd, prefix, audit):
    """8.4.4.4.(1): reference envelope thermal characteristics = lightweight
    construction. Implemented by rebuilding each exterior/ground opaque
    assembly as a single MASSLESS layer at the identical (already-prescriptive)
    resistance — zero thermal mass with unchanged Ut. NOTE: the canonical layer
    set of Note A-8.4.4.4.(1) is not machine-retrievable; the massless
    interpretation is documented in the coverage manifest.

    (PORT NOTE: this header is STALE in the Ruby too — D-35 replaced the
    massless reading with the light-frame StandardOpaqueMaterial rebuild
    below. Ported verbatim rather than silently corrected.)"""
    cache = {}
    rebuilt = 0
    for surface in sorted_by_name(model.getSurfaces()):
        boundary = Prescriptive.boundary_of(surface)
        surface_class = Prescriptive.SURFACE_CLASS.get(surface.surfaceType())
        if boundary is None or surface_class is None:
            continue
        construction = opt(surface.construction())
        original = None if construction is None else opt(construction.to_Construction())
        if original is None:
            continue
        # 8.4.4.4.(1) covers the building envelope; exterior surfaces of
        # unconditioned spaces (attic decks/gables) are not envelope and keep
        # the proposed's real construction.
        space = opt(surface.space())
        if space is not None and not Prescriptive.inside_envelope(space):
            continue

        conductance = opt_or(original.thermalConductance(), 0.0)
        if conductance <= 0:
            continue

        # The massless rebuild must CARRY OVER the outer layer's absorptances:
        # a fresh MasslessOpaqueMaterial defaults to solar 0.7 / thermal 0.9 /
        # visible 0.7, which silently overwrote the proposed values on EVERY
        # opaque surface — violating the 8.4.4.3.(2)(a) keep-the-proposed
        # promise, and making the (2)(b) set-to-0.7 branch "work" only by
        # coincidence (this transform runs AFTER apply_roof_absorptance, so
        # whatever that set is preserved here too). The absorptance triple is
        # part of the cache key: equal-conductance surfaces with different
        # finishes must not share a rebuilt construction.
        outer = opt(original.layers()[0].to_OpaqueMaterial())
        solar = 0.7 if outer is None else outer.solarAbsorptance()
        thermal = 0.9 if outer is None else outer.thermalAbsorptance()
        visible = 0.7 if outer is None else outer.visibleAbsorptance()

        # Note A-8.4.4.4.(1) [READ, MCP 2026-07-28]: "lightweight" is NOT
        # zero-mass — the note's example assemblies are light FRAME
        # constructions (wood-frame example: 40.8 kg/m2 areal mass, heat
        # capacity 45.5 kJ/(m2.K); steel-frame 33.9 / 35.3), with the layer
        # structure following the proposed and insulation varied to hit the
        # Part 3 U-value. Rebuild = one StandardOpaqueMaterial calibrated to
        # the wood-frame example's mass and heat capacity at the identical
        # (already-prescriptive) resistance. (The earlier zero-mass reading
        # predates the appendix being retrievable — corrected under D-35.)
        # A regular material is also what EnergyPlus's Kiva engine REQUIRES on
        # Foundation-boundary surfaces (massless there is a hard E+ fatal), so
        # ONE material now serves every boundary.
        kiva = surface.outsideBoundaryCondition() == "Foundation"
        key = (surface_class, boundary, ruby_round(conductance, 5),
               ruby_round(solar, 4), ruby_round(thermal, 4), ruby_round(visible, 4))
        if key not in cache:
            t = LIGHTWEIGHT_THICKNESS_M
            m = openstudio.model.StandardOpaqueMaterial(
                model, "MediumSmooth", t, t * conductance,
                LIGHTWEIGHT_MASS_KG_M2 / t,
                LIGHTWEIGHT_HEAT_CAPACITY_J_M2K / LIGHTWEIGHT_MASS_KG_M2,
            )
            m.setName(f"NECB Ref Lightweight {surface_class} "
                      f"R-{ruby_str(ruby_round(1.0 / conductance, 3))} "
                      f"a{ruby_str(ruby_round(solar, 2))}")
            # StandardOpaqueMaterial setters need OptionalDouble (CLAUDE.md trap)
            m.setSolarAbsorptance(openstudio.OptionalDouble(solar))
            m.setThermalAbsorptance(openstudio.OptionalDouble(thermal))
            m.setVisibleAbsorptance(openstudio.OptionalDouble(visible))
            c = openstudio.model.Construction(model)
            c.setName(f"NECB Ref Lightweight{'(Kiva)' if kiva else ''} {boundary} "
                      f"{surface_class}:U-{ruby_str(ruby_round(conductance, 4))} "
                      f"a{ruby_str(ruby_round(solar, 2))}")
            c.setLayers([m])
            c.setInsulation(m)
            cache[key] = c
        surface.setConstruction(cache[key])
        rebuilt += 1
    audit.decision("reference",
                   "opaque assemblies rebuilt as lightweight light-frame at unchanged Ut",
                   inputs={"surfaces": rebuilt, "unique_assemblies": len(cache),
                           "areal_mass_kg_m2": LIGHTWEIGHT_MASS_KG_M2,
                           "heat_capacity_kj_m2k": LIGHTWEIGHT_HEAT_CAPACITY_J_M2K / 1000.0},
                   article=f"{prefix}.4.(1) (Note A-8.4.4.4.(1): light-frame example "
                           "mass/heat capacity)",
                   ruling="D-35")


def apply_air_leakage_default(model, prefix, audit):
    """8.4.4.3.(6) via 8.4.3.3.(3) + 8.4.2.9.(2):
    I_AGW = (5/75)^0.6 x I75 x S / A_AGW, applied per space as flow per
    exterior above-ground wall area."""
    # S per 3.2.4.2.(1)(c) (D-21): the enclosure of the CONDITIONED volume —
    # Outdoors and ground-contact surfaces of conditioned spaces PLUS
    # interzone surfaces separating conditioned from unconditioned spaces
    # (attic ceilings, plenum boundaries). Surfaces of unconditioned spaces
    # themselves (attic roofs/gables) bound no conditioned space and are NOT
    # envelope. Ground contact stays IN S: it is enclosure area used to
    # NORMALIZE the tested/assumed rate, not a claim of slab leakage — the
    # S/A_AGW term moves the whole total onto above-ground walls.
    # Conditioned-or-indirectly-conditioned per Prescriptive.inside_envelope
    # (partofTotalFloorArea, with the legacy space_conditioning_category tag
    # honoured so tagged plenums count as inside). Space multipliers honoured.
    envelope_area = 0.0
    wall_area = 0.0
    for space in model.getSpaces():
        mult = float(space.multiplier())
        conditioned = Prescriptive.inside_envelope(space)
        for surface in space.surfaces():
            condition = surface.outsideBoundaryCondition()
            if condition == "Outdoors":
                if not conditioned:
                    continue

                envelope_area += surface.grossArea() * mult
                if surface.surfaceType() == "Wall":
                    wall_area += surface.grossArea() * mult
            elif _GROUND_OR_FOUNDATION_RE.search(condition):
                if conditioned:
                    envelope_area += surface.grossArea() * mult
            elif condition == "Surface":
                if not conditioned:
                    continue

                adj = opt(surface.adjacentSurface())
                if adj is None:
                    continue
                adj_space = opt(adj.space())
                if adj_space is None:
                    continue

                if not Prescriptive.inside_envelope(adj_space):
                    envelope_area += surface.grossArea() * mult
    if wall_area < 0.1:
        audit.warn("reference", "no above-ground walls — air-leakage default not applied",
                   article=f"{prefix}.3.(6)")
        return

    c = (5.0 / 75.0) ** AIR_LEAKAGE_N
    i_agw = c * AIR_LEAKAGE_I75 * envelope_area / wall_area  # L/(s.m2 of AG wall)

    # Clear EVERY infiltration representation before adding the default.
    # OpenStudio models infiltration with three unrelated object types, and
    # they are additive: clearing only DesignFlowRate leaves a proposed model
    # that used EffectiveLeakageArea or FlowCoefficient with its original
    # leakage PLUS the NECB default on top — roughly double infiltration on
    # the reference, which inflates reference energy and makes the proposed
    # easier to pass.
    cleared = {"design_flow_rate": len(model.getSpaceInfiltrationDesignFlowRates()),
               "effective_leakage_area": len(model.getSpaceInfiltrationEffectiveLeakageAreas()),
               "flow_coefficient": len(model.getSpaceInfiltrationFlowCoefficients())}
    # D-19: the reference must model the SAME default the proposed carries
    # (8.4.4.3.(6) -> 8.4.3.3.(3)) — including its TEMPORAL modulation. The
    # E+ modifier coefficients (constant/temperature/wind terms) change
    # delivered infiltration by ~2x between the constant convention (A=1) and
    # the DOE-2 wind-driven convention (A=0, C=0.224) even at identical design
    # totals, and an asymmetric pair breaks the comparison. Inherit the
    # proposed's dominant coefficient set + schedule; fall back to constant
    # (A=1) when the proposed has no DesignFlowRate infiltration.
    # Proposed installed total (DesignFlowRate representations only — the
    # other object types cannot be totalled without weather) for the
    # 8.4.3.3.(3) default-conformance check below.
    proposed_total_l_s = None
    if (not model.getSpaceInfiltrationEffectiveLeakageAreas()
            and not model.getSpaceInfiltrationFlowCoefficients()):
        proposed_total_l_s = 0.0
        for i in model.getSpaceInfiltrationDesignFlowRates():
            sp = opt(i.space())
            if sp is None:
                proposed_total_l_s += 0.0
                continue

            mult = sp.multiplier()
            if i.flowperExteriorSurfaceArea().is_initialized():
                proposed_total_l_s += (i.flowperExteriorSurfaceArea().get()
                                       * sp.exteriorArea() * mult * 1000.0)
            elif i.flowperExteriorWallArea().is_initialized():
                proposed_total_l_s += (i.flowperExteriorWallArea().get()
                                       * sp.exteriorWallArea() * mult * 1000.0)
            elif i.designFlowRate().is_initialized():
                proposed_total_l_s += i.designFlowRate().get() * mult * 1000.0
            elif i.flowperSpaceFloorArea().is_initialized():
                proposed_total_l_s += (i.flowperSpaceFloorArea().get()
                                       * sp.floorArea() * mult * 1000.0)
            else:
                proposed_total_l_s += 0.0
    design_flow_rates = list(model.getSpaceInfiltrationDesignFlowRates())
    donor = (min(design_flow_rates, key=lambda o: o.nameString())
             if design_flow_rates else None)
    if donor is not None:
        coeffs = {"a": donor.constantTermCoefficient(),
                  "b": donor.temperatureTermCoefficient(),
                  "c": donor.velocityTermCoefficient(),
                  "d": donor.velocitySquaredTermCoefficient(),
                  "schedule": opt(donor.schedule())}
    else:
        coeffs = {"a": 1.0, "b": 0.0, "c": 0.0, "d": 0.0, "schedule": None}
    for obj in list(model.getSpaceInfiltrationDesignFlowRates()):
        obj.remove()
    for obj in list(model.getSpaceInfiltrationEffectiveLeakageAreas()):
        obj.remove()
    for obj in list(model.getSpaceInfiltrationFlowCoefficients()):
        obj.remove()
    for space in sorted_by_name(model.getSpaces()):
        # unconditioned spaces (attics/plenums) receive NO infiltration
        # object: their exterior walls are outside A_AGW, and giving them
        # flow-per-wall-area would silently re-inflate the installed total
        # beyond the S-based default
        if not Prescriptive.inside_envelope(space):
            continue

        infiltration = openstudio.model.SpaceInfiltrationDesignFlowRate(model)
        infiltration.setName(f"{space.nameString()} NECB Ref Infiltration")
        infiltration.setFlowperExteriorWallArea(i_agw / 1000.0)  # m3/s per m2
        infiltration.setConstantTermCoefficient(coeffs["a"])
        infiltration.setTemperatureTermCoefficient(coeffs["b"])
        infiltration.setVelocityTermCoefficient(coeffs["c"])
        infiltration.setVelocitySquaredTermCoefficient(coeffs["d"])
        if coeffs["schedule"] is not None:
            infiltration.setSchedule(coeffs["schedule"])
        infiltration.setSpace(space)
    # 8.4.3.3.(3)/(4): an UNTESTED proposed carries this same default. Warn
    # when the proposed's installed total deviates — below-default proposed
    # infiltration is a free heating credit (permissive direction).
    code_total_l_s = c * AIR_LEAKAGE_I75 * envelope_area
    if (proposed_total_l_s is not None
            and abs(proposed_total_l_s - code_total_l_s) > 0.10 * code_total_l_s):
        audit.warn("reference",
                   "proposed infiltration total %.0f L/s DEVIATES from the untested "
                   "8.4.3.3.(3) default %.0f L/s by %+.0f%% — only a 3.2.4.2 airtightness "
                   "test justifies a different value"
                   % (proposed_total_l_s, code_total_l_s,
                      100 * (proposed_total_l_s / code_total_l_s - 1)),
                   article="8.4.3.3.(3)-(4)", ruling="D-19 D-21")
    # State the assumption to the AHJ rather than leaving it implicit. 3.2.4.2
    # is a TEST on the finished building, so this number is an assumption the
    # model makes on the reader's behalf until someone measures it — say so
    # where they will see it, not only in the coverage manifest (D-76).
    audit.info("reference",
               "airtightness ASSUMED at the untested 3.2.4.2. default of %.2f L/(s.m2) "
               "@ 75 Pa — PENDING FIELD VERIFICATION by a whole-building ASTM E3158 test; "
               "substitute the measured rate once tested" % (AIR_LEAKAGE_I75,),
               inputs={"assumed_i75_l_per_s_m2": AIR_LEAKAGE_I75,
                       "test_standard": "ASTM E3158", "pressure_pa": 75, "verified": False},
               article="3.2.4.2.", ruling="D-76")
    audit.decision("reference", "air-leakage default applied",
                   inputs={"i75_l_per_s_m2": AIR_LEAKAGE_I75,
                           "flow_exponent": AIR_LEAKAGE_N,
                           "envelope_area_m2": ruby_round(envelope_area, 1),
                           "ag_wall_area_m2": ruby_round(wall_area, 1),
                           "proposed_infiltration_objects_cleared": cleared,
                           "inherited_coefficients": {
                               "a": coeffs["a"], "b": coeffs["b"], "c": coeffs["c"],
                               "d": coeffs["d"],
                               "schedule": (None if coeffs["schedule"] is None
                                            else coeffs["schedule"].nameString())}},
                   value=(f"I_AGW = (5/75)^0.6 x {ruby_str(AIR_LEAKAGE_I75)} x "
                          f"{ruby_str(ruby_round(envelope_area, 1))}/"
                          f"{ruby_str(ruby_round(wall_area, 1))} = "
                          f"{ruby_str(ruby_round(i_agw, 4))} L/(s.m2 AG wall), per space as "
                          "flow-per-exterior-wall-area"),
                   article=f"{prefix}.3.(6); 8.4.3.3.(3); 8.4.2.9.(2)", ruling="D-19 D-21")


def _emit_article_coverage(vintage, audit):
    """Completeness accounting (same contract as the hvac domain)."""
    from btap.necb import envelope

    emit_coverage(envelope.rules(vintage).get("article_coverage"), audit)


def reference_envelope(model, *, vintage, hdd=None, actual_roof_absorptance_used=False,
                       thermal_bridging=None, audit=None):
    """Facade: reference envelope IN PLACE on the caller's clone."""
    return apply(model, vintage=vintage, hdd=hdd,
                 actual_roof_absorptance_used=actual_roof_absorptance_used,
                 thermal_bridging=thermal_bridging, audit=audit)
