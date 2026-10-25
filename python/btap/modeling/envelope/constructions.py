"""SDK-only construction machinery (port of btap-modeling's
envelope/constructions.rb) — SI-native ports of the clean pieces of
OpenstudioStandards::Constructions plus the legacy BTAP conventions the
parity gate (and costing) depend on:

- Opaque targets are applied as CONSTRUCTION-ONLY conductance (films
  excluded), exactly like legacy BTAP customize_opaque_construction. Pass
  include_films=True to the NECB appliers for the code-literal
  interpretation: the construction target becomes 1/(1/U - R_films).
- Naming/reuse conventions preserved: opaque "Base:U-<cond>", fenestration
  "Base:U=<cond*0.1> SHGC=<shgc>" with a shared SimpleGlazing — BTAP
  envelope costing keys on these names.
"""

from __future__ import annotations

import math
import re

import openstudio

from btap._compat import opt, ruby_round, ruby_str

IP_TO_SI_R = 0.17611018368230098  # ft2·h·R/Btu -> m2·K/W

FILM_R_SI = {
    "ext": 0.17 * IP_TO_SI_R,
    "semi_ext": 0.46 * IP_TO_SI_R,
    "int_up": 0.61 * IP_TO_SI_R,
    "int_down": 0.92 * IP_TO_SI_R,
    "int_vertical": 0.68 * IP_TO_SI_R,
}


def film_r(surface, boundary) -> float:
    """Interior+exterior film resistance for the envelope surface classes
    this package touches (subset of OpenstudioStandards
    film_coefficients_r_value)."""
    key = (str(boundary), str(surface))
    if key in (("outdoors", "wall"), ("outdoors", "window"), ("outdoors", "door")):
        return FILM_R_SI["ext"] + FILM_R_SI["int_vertical"]
    if key in (("outdoors", "roofceiling"), ("outdoors", "skylight")):
        return FILM_R_SI["ext"] + FILM_R_SI["int_up"]
    if key == ("outdoors", "floor"):
        return FILM_R_SI["ext"] + FILM_R_SI["int_down"]
    if key == ("ground", "wall"):
        return FILM_R_SI["int_vertical"]
    if key == ("ground", "floor"):
        return FILM_R_SI["int_down"]
    if key == ("ground", "roofceiling"):
        return FILM_R_SI["int_up"]
    return 0.0


def film_r_interzone(surface) -> float:
    """Both faces of an assembly separating conditioned from enclosed
    unconditioned space see INTERIOR films (attic ceilings, walls to unheated
    storage, floors over crawlspaces)."""
    key = str(surface)
    if key == "wall":
        return 2 * FILM_R_SI["int_vertical"]
    if key == "roofceiling":
        return 2 * FILM_R_SI["int_up"]
    if key == "floor":
        return 2 * FILM_R_SI["int_down"]
    return 0.0


#: The fixed layer's name. EXPORTED because the tests need to find that layer
#: and both alternatives are worse: matching by position breaks silently when
#: the layer order changes (which `318` A2 did), and matching by density or
#: thickness matches whatever else happens to share them (Fable, `318`).
BOARD_LAYER_NAME = "Seed Interior Board"

#: ORDINARY 16 mm gypsum board, as an interior finish layer, with textbook
#: material properties and nothing else behind them. Every quantity stands on
#: its own as a real material a supplier would sell.
#:
#: An earlier version used NECB Note A-8.4.4.4.(1)'s wood-frame worked
#: example instead. Sol refused it (`320`) on two grounds, and both are worth
#: keeping written down. The Note's numbers were SELECTED for a reference
#: approximation, so putting them on a synthetic authoring placeholder — one
#: applied indiscriminately to walls, roofs, floors and ground contact —
#: implied an NECB identity this object does not have. And the layer was not
#: even the Note's assembly: it combined the example's WHOLE-ASSEMBLY areal
#: mass and heat capacity with the FRAMING PATH's resistance and called the
#: three one homogeneous material.
#:
#: The broader rule, which is the reason this comment is long: copying rule
#: values rather than importing their owner is still a semantic dependency
#: when those values decide simulation physics. The D-77 boundary is about
#: NECB knowledge, not only about Python imports, so restating the constants
#: did not make the dependency allowed — it only made it invisible to
#: `lint-imports`.
#: These are EnergyPlus's own shipped `G01 16mm gypsum board`
#: (`DataSets/ASHRAE_2005_HOF_Materials.idf`) to the digit, except that the
#: thickness is 16 mm rather than the dataset's 15.9 mm, which makes
#: `BOARD_R_SI` exactly 0.1. The roughness matches the record too, because
#: "to the digit except thickness" has to be true of everything else or it is
#: not worth writing (Sol, `322`). Cited at all because the lesson of this
#: file is that a number with no derivation behind it is a liability.
BOARD_THICKNESS_M = 0.016
BOARD_CONDUCTIVITY_W_MK = 0.16
BOARD_DENSITY_KG_M3 = 800.0
BOARD_SPECIFIC_HEAT_J_KGK = 1090.0
#: Derived, not declared: 0.1 m2K/W. The guard below is twice this.
BOARD_R_SI = BOARD_THICKNESS_M / BOARD_CONDUCTIVITY_W_MK
#: Sub-surface types that are OPAQUE and must not receive glazing. Everything
#: else an OpenStudio model can carry here is fenestration.
OPAQUE_SUB_SURFACE_TYPES = frozenset({"Door", "OverheadDoor"})

#: Glass-fibre batt, for the layer whose THICKNESS the retargeter varies.
BATT_CONDUCTIVITY_W_MK = 0.04
BATT_DENSITY_KG_M3 = 12.0
BATT_SPECIFIC_HEAT_J_KGK = 840.0


def seed_set(model, *, opaque_r_si=2.0, window_u_si=2.5,
             window_shgc=0.4, window_vt=0.5):
    """Give every surface a construction, so envelope work has one to RETARGET.

    Wizard and bar output carries NO constructions, and every downstream
    envelope pass — `opaque_at_conductance`, `fenestration_at_conductance`,
    the NECB prescriptive and reference transforms — retargets an EXISTING
    construction rather than creating one. So an authored model needs a seed
    set before any of them will run, which `btap/modeling/README.md` has
    documented as a precondition while the only implementation lived on a test
    class (`tests/modeling/test_bar.py`). The documented chain therefore could
    not be started from the shipped wheel at all (issue #143).

    Deliberately POOR insulation. The seed exists to be improved on, so a
    default R-2 opaque and a U-2.5 window make a later envelope pass visibly
    change something; seeding at a plausible target would hide whether the
    transform ran at all. Pass your own values for a different starting
    point.

    THE OPAQUE CONSTRUCTION HAS TWO LAYERS, and that is the whole design.

    A single calibrated layer looks simpler and is wrong, because
    `opaque_at_conductance` solves a target with
    `LayeredConstruction.setConductance`, which on a lone
    `StandardOpaqueMaterial` grows its THICKNESS. Retargeting a one-layer seed
    therefore scales its mass linearly with the target R: measured, a seeded
    roof improved to U-0.156 became a 0.48 m slab at 130 kg/m2 and
    149 kJ/(m2.K), four times the mass it started with (Fable, `318` F1).
    Asking for more RESISTANCE and silently getting four times the MASS is
    incoherent on its own terms: the caller named one property and a
    different one moved.

    So the seed separates the two jobs. A fixed board layer carries the heat
    capacity, and a batt layer carries the resistance;
    `find_and_set_insulation_layer` picks the batt because its resistance is
    the larger, the solver grows only that, and the construction's mass stays
    put while its resistance goes wherever the caller asks.

    THE LAYERS CARRY REAL THERMAL MASS, and must. A
    `MasslessOpaqueMaterial` was the obvious choice for a placeholder and is
    wrong twice over:

    - EnergyPlus REFUSES a massless layer on a `Foundation` surface, so a
      massless seed makes the default `ground_model="kiva"` path unreachable.
      `foundations.create_kiva_foundation` returns `created: False` with
      "is not a standard opaque material", and the ground floor silently never
      becomes a Kiva foundation. Measured, not predicted — the first version of
      this function had exactly that defect;
    - zero mass is not a neutral placeholder. It removes the envelope's heat
      capacity from the simulation entirely, so a seeded model's results are
      not merely approximate but wrong in a known direction — no stored heat
      means no damping and no lag.

    One edge is NOT guarded, and the numbers are given because an earlier
    version of this paragraph asserted the callers never reach it and was
    WRONG. A target at or above `1 / BOARD_R_SI` — 10 W/(m2.K) — is worse
    than the board alone: just under it the batt goes to zero thickness, at
    exactly 10 the solver raises, and above it the board itself is trimmed
    away and the heat capacity goes with it.

    The largest target any caller in this repository passes is the NECB
    zone-4 door, 3.11 W/(m2.K) construction-only, so 10 is clear by a factor
    of about three. That margin is the reason this is a documented edge and
    not a guard. It is also a REGRESSION FIXED BY ACCIDENT: with the earlier,
    thicker fixed layer the same edge sat at 1.637, BELOW almost every door
    target, so retargeting a seeded door through the prescriptive path
    silently returned a construction with no mass layer at all (Fable, `318`
    addendum 3, measured against the previous head). The witness below pins
    the margin so that a future change to the board cannot quietly close it
    again.

    THIS IS A SYNTHETIC SEED, not an archetype and not a code-backed
    assembly. Its only job is to be present and improvable, so that a later
    envelope pass has something to retarget. A caller who needs a particular
    real assembly supplies one.

    ONE opaque construction serves walls, roofs, floors and ground contact,
    which is safe because every retargeting entry point deep-copies and reuses
    by name — `opaque_at_conductance` creates `<name>:U-x.xxxx` from the seed
    and assigns the copy, so retargeting a wall cannot alter a roof that
    shares the seed. A richer per-surface-type set is a separate feature, not a
    precondition for the chain.

    Constructions are assigned DIRECTLY rather than through a
    `DefaultConstructionSet`. Direct assignment leaves
    `surface.isConstructionDefaulted()` false, which keeps the seed out of the
    defaulted-construction interaction that `envelope/foundations.py` has to
    pin around when a surface's construction resolves through a set. An
    archetype-realistic default set is a reasonable future addition and would
    exercise that path on purpose.

    Returns the two constructions it created, opaque first.
    """
    # THE FLOOR IS TWICE THE BOARD'S RESISTANCE, not once. The batt must
    # out-resist the board for `find_and_set_insulation_layer` to pick it, and
    # the batt only carries `opaque_r_si - BOARD_R_SI`. An earlier version
    # guarded at ONE times the fixed layer's resistance, which left a whole
    # band where the picker chose the FIXED layer and retargeting grew that
    # to 1.4 m — worse than the one-layer defect the two layers replaced
    # (Fable, `318` A1). The comparison is strict, so the tie is refused
    # rather than left to scan order. At this floor both conductances are
    # exactly 10.0 and SCAN ORDER would decide; at the previous, larger floor
    # they differed by float noise and the noise decided. Either way the
    # outcome is not a property anyone should have to reason about, which is
    # why `<=` refuses it outright.
    if opaque_r_si <= 2 * BOARD_R_SI:
        raise ValueError(
            f"opaque_r_si must exceed {2 * BOARD_R_SI} m2K/W — twice the "
            f"board layer's own {BOARD_R_SI} — so the batt layer out-resists "
            f"it and the retargeter grows the batt rather than the board; "
            f"got {opaque_r_si}")

    # The board layer is FIXED: it carries the heat capacity and the
    # retargeter must not grow it. Declared directly, because each property
    # is a property of gypsum board and not derived from anything else.
    board = openstudio.model.StandardOpaqueMaterial(
        model, "MediumSmooth", BOARD_THICKNESS_M, BOARD_CONDUCTIVITY_W_MK,
        BOARD_DENSITY_KG_M3, BOARD_SPECIFIC_HEAT_J_KGK)
    board.setName(BOARD_LAYER_NAME)

    # The batt layer carries the resistance and is the one the solver grows,
    # because its resistance is the larger of the two.
    batt_thickness = (opaque_r_si - BOARD_R_SI) * BATT_CONDUCTIVITY_W_MK
    batt = openstudio.model.StandardOpaqueMaterial(
        model, "Rough", batt_thickness, BATT_CONDUCTIVITY_W_MK,
        BATT_DENSITY_KG_M3, BATT_SPECIFIC_HEAT_J_KGK)
    batt.setName(
        f"Seed Batt R-{ruby_str(ruby_round(opaque_r_si - BOARD_R_SI, 2))}")

    opaque = openstudio.model.Construction(model)
    opaque.setName("Seed Opaque")
    # BATT OUTSIDE, FRAME INSIDE. EnergyPlus reads the first layer as the
    # OUTSIDE one, so board-then-batt put the mass on the weather and soil
    # side of the insulation, decoupled from the zone it is there to damp —
    # the opposite of the point (Fable, `318` A2). The solver and Kiva are
    # indifferent to the order; the physics is not.
    opaque.setLayers([batt, board])

    glazing = openstudio.model.SimpleGlazing(model)
    glazing.setUFactor(window_u_si)
    glazing.setSolarHeatGainCoefficient(window_shgc)
    glazing.setVisibleTransmittance(window_vt)
    glazing.setName(f"Seed Glazing U-{ruby_str(ruby_round(window_u_si, 2))}")
    window = openstudio.model.Construction(model)
    window.setName("Seed Window")
    window.setLayers([glazing])

    for surface in model.getSurfaces():
        surface.setConstruction(opaque)
    for sub_surface in model.getSubSurfaces():
        # A DOOR IS NOT GLAZING, and getting this wrong is silent. The
        # OpenStudio forward translator rewrites a sub-surface that carries a
        # fenestration construction — "SubSurface 'X' uses fenestration
        # construction, changing SubSurfaceType to GlassDoor" — so seeding
        # every sub-surface with glazing turned a submitter's opaque door into
        # a glass one, with nothing in the audit to show it (Fable, `318` F2).
        if sub_surface.subSurfaceType() in OPAQUE_SUB_SURFACE_TYPES:
            sub_surface.setConstruction(opaque)
        else:
            sub_surface.setConstruction(window)
    return opaque, window


def deep_copy(model, construction):
    """Clone the construction AND every layer material (a bare
    LayeredConstruction#clone shares material objects, so solving one
    construction's insulation would mutate every other construction using the
    same material — port of the legacy construction_deep_copy). Internal-source
    constructions retain their source location and tube spacing."""
    internal_source = opt(construction.to_ConstructionWithInternalSource())
    if internal_source is None:
        copy = construction.clone(model).to_Construction().get()
    else:
        copy = construction.clone(model).to_ConstructionWithInternalSource().get()
    copy.setName(construction.nameString())
    copy.setLayers([layer.clone(model).to_Material().get()
                    for layer in construction.layers()])
    if copy.insulation().is_initialized():
        copy.resetInsulation()
    return copy


def find_and_set_insulation_layer(construction):
    """Lowest-conductance opaque layer, memoized on the construction (port of
    construction_find_and_set_insulation_layer)."""
    existing = opt(construction.insulation())
    if existing is not None:
        return existing

    best = None
    best_conductance = math.inf
    for layer in construction.layers():
        material = opt(layer.to_OpaqueMaterial())
        if material is None:
            continue
        c = material_conductance(material)
        if c < best_conductance:
            best_conductance = c
            best = material
    if best is not None:
        construction.setInsulation(best)
    return opt(construction.insulation())


def material_conductance(material) -> float:
    std = opt(material.to_StandardOpaqueMaterial())
    if std is not None:
        return std.conductivity() / std.thickness()
    massless = opt(material.to_MasslessOpaqueMaterial())
    if massless is not None:
        return 1.0 / massless.thermalResistance()
    air_gap = opt(material.to_AirGap())
    if air_gap is not None:
        return 1.0 / air_gap.thermalResistance()
    return math.inf


def opaque_at_conductance(
        model, construction, conductance, *, name_discriminator=None):
    """Opaque construction at a target CONSTRUCTION conductance, W/(m2.K) —
    legacy-exact port of BTAP customize_opaque_construction: reuse by name,
    deep-copy, insulation-layer solve via SDK setConductance, layer-trimming
    fallback when the non-insulation layers alone exceed the target
    resistance."""
    base = re.sub(r":.*\Z", "", construction.nameString())
    if name_discriminator is not None:
        base = f"{base} {name_discriminator}"
    # Names are keys for humans and legacy costing matchers; the
    # full-precision value lives in the material (setConductance below uses
    # the unrounded `conductance`). The optional discriminator is required for
    # continuously varying targets such as D-32's floor-specific equivalent U;
    # discrete NECB table values are separated far enough for the legacy 4dp
    # display name.
    name = f"{base}:U-{ruby_str(ruby_round(conductance, 4))}"
    internal_source = opt(construction.to_ConstructionWithInternalSource())
    existing = opt(
        model.getConstructionByName(name)
        if internal_source is None
        else model.getConstructionWithInternalSourceByName(name)
    )
    if existing is not None:
        return existing

    copy = deep_copy(model, construction)
    copy.setName(name)
    insulation = find_and_set_insulation_layer(copy)
    if insulation is None:
        raise RuntimeError(f"no insulation layer identifiable in {construction.nameString()}")

    # Ruby's `.to_f` on an empty Optional yields 0.0, making 1/0.0 = inf and
    # steering into the trim fallback — reproduce that, never a ZeroDivision.
    total = opt(copy.thermalConductance()) or 0.0
    total_resistance = math.inf if total == 0.0 else 1.0 / total
    minimum_resistance = total_resistance - (
        1.0 / material_conductance(insulation.to_OpaqueMaterial().get()))
    if minimum_resistance > 1.0 / conductance:
        trim_layers_to_conductance(copy, conductance)
    else:
        if not copy.setConductance(conductance):
            raise RuntimeError(f"could not set conductance of {name}")
    return copy


def trim_layers_to_conductance(construction, conductance):
    """Fallback when the insulation layer alone cannot reach the target:
    remove the least-conductive non-insulation layers until the SDK solve
    succeeds, ending with a single massless layer at the exact resistance if
    all else fails."""
    insulation = construction.insulation()
    while True:
        removable = [
            (layer, index) for index, layer in enumerate(construction.layers())
            if not (insulation.is_initialized()
                    and layer.handle() == insulation.get().handle())
        ]
        if not removable:
            break

        # remove the most resistive removable layer first
        def resistivity(pair):
            layer = pair[0]
            try:
                material = opt(layer.to_OpaqueMaterial())
                return material_conductance(material if material is not None else layer)
            except Exception:
                return math.inf

        layer, index = min(removable, key=resistivity)
        construction.eraseLayer(index)
        if construction.setConductance(conductance):
            return construction
        if len(construction.layers()) <= 1:
            break
    material = openstudio.model.MasslessOpaqueMaterial(
        construction.model(), "MediumSmooth", 1.0 / conductance)
    material.setName(f"{construction.nameString()} R-{ruby_str(ruby_round(1.0 / conductance, 3))}")
    construction.setLayers([material])
    construction.setInsulation(material)
    return construction


def fenestration_at_conductance(model, construction, conductance):
    """Fenestration construction at a target U — legacy-exact port of BTAP
    customize_fenestration_construction: replace with a shared SimpleGlazing
    that preserves SHGC and visible transmittance; reuse by name."""
    shgc = fenestration_solar_transmittance(construction)
    vt = fenestration_visible_transmittance(construction)
    base = re.sub(r":.*\Z", "", construction.nameString())
    suffix = f"U={conductance * 0.10:.3f} SHGC={shgc:.3f}"
    name = f"{base}:{suffix}"
    existing = opt(model.getConstructionByName(name))
    if existing is not None:
        return existing

    glazing_name = f"SimpleGlazing:{suffix}"
    glazing = opt(model.getSimpleGlazingByName(glazing_name))
    if glazing is None:
        glazing = openstudio.model.SimpleGlazing(model)
        glazing.setSolarHeatGainCoefficient(shgc)
        glazing.setUFactor(conductance)
        glazing.setThickness(0.21)
        glazing.setVisibleTransmittance(vt)
        glazing.setName(glazing_name)

    new_construction = openstudio.model.Construction(model)
    new_construction.setName(name)
    new_construction.setLayers([glazing])
    return new_construction


def fenestration_solar_transmittance(construction) -> float:
    for layer in construction.layers():
        simple = opt(layer.to_SimpleGlazing())
        if simple is not None:
            return simple.solarHeatGainCoefficient()
        standard = opt(layer.to_StandardGlazing())
        if standard is not None:
            return _to_float(standard.solarTransmittanceatNormalIncidence())
    return 0.60


def _to_float(value) -> float:
    """Ruby's `.to_f` on a maybe-Optional SDK return: 0.0 when empty
    (accessors changed Optional-ness across SDK versions)."""
    if hasattr(value, "is_initialized"):
        unwrapped = opt(value)
        return 0.0 if unwrapped is None else float(unwrapped)
    return float(value)


def fenestration_visible_transmittance(construction) -> float:
    for layer in construction.layers():
        simple = opt(layer.to_SimpleGlazing())
        if simple is not None:
            vt = simple.visibleTransmittance()
            # Optional in some SDK versions, plain double in others.
            if hasattr(vt, "is_initialized"):
                value = opt(vt)
                return value if value is not None else 0.60
            return vt
        standard = opt(layer.to_StandardGlazing())
        if standard is not None:
            return _to_float(standard.visibleTransmittanceatNormalIncidence())
    return 0.60


# The pinned oracle models a thin carpet finish with these properties in
# Prototype.hvac_systems.rb. They are evidence for CP02 CARPET PAD specifically,
# not a licence to invent physical properties for arbitrary no-mass layers.
KIVA_CARPET_CONDUCTIVITY_W_MK = 0.06
KIVA_CARPET_DENSITY_KG_M3 = 288.0
KIVA_CARPET_SPECIFIC_HEAT_J_KGK = 1380.0
_CP02_CARPET_PAD = re.compile(r"^CP02 CARPET PAD(?: \d+)?$", re.IGNORECASE)


def _kiva_carpet(layer):
    material = opt(layer.to_MasslessOpaqueMaterial())
    if material is None or not _CP02_CARPET_PAD.fullmatch(material.nameString()):
        return None
    return material


def kiva_legalization_blockers(surface):
    """Reasons ``surface`` cannot be made Kiva-legal without guessed physics.

    This is the read-only counterpart to :func:`kiva_legal`. An empty list
    means the assigned construction already uses standard opaque materials or
    every nonstandard layer is the specifically sourced CP02 carpet pad.
    """
    construction = opt(surface.construction())
    if construction is None:
        return ["no construction assigned"]
    layered = opt(construction.to_LayeredConstruction())
    if layered is None:
        return ["construction is not a layered construction"]
    layers = layered.layers()
    if not layers:
        return ["construction has no layers"]

    blockers = []
    for layer in layers:
        if (opt(layer.to_StandardOpaqueMaterial()) is None
                and _kiva_carpet(layer) is None):
            blockers.append(
                f"construction layer '{layer.nameString()}' is not a standard "
                "opaque material and has no sourced Kiva-compatible "
                "replacement")
    return blockers


def kiva_legal(model, surface):
    """Make `surface`'s construction legal for an EnergyPlus Foundation
    boundary, PRESERVING its resistance exactly. Returns a dict describing what
    changed, or None when nothing had to.

    EnergyPlus refuses a Foundation surface whose construction carries any
    no-mass layer, and 582 of the 588 shipped-archetype ground floors carry the
    known `CP02 CARPET PAD`, massless at R-0.2165. That specific material is
    replaced by a StandardOpaqueMaterial at the SAME thermal resistance using
    the pinned oracle's sourced thin-carpet conductivity, density and specific
    heat. Roughness and absorptances are copied from the submitted layer.
    Unknown no-mass materials and air gaps are left untouched so Kiva
    eligibility refuses them rather than assigning guessed physical properties.

    The construction is ALWAYS CLONED, so a shared construction cannot be
    changed out from under a refused floor or another surface.

    R is preserved, but replacing a no-mass layer necessarily introduces the
    sourced carpet's heat capacity. This is part of the symmetric ground-method
    normalization, not a claim that the two material objects are dynamically
    identical.
    """
    construction = opt(surface.construction())
    if construction is None:
        return None
    layered = opt(construction.to_LayeredConstruction())
    if layered is None:
        return None

    nonstandard_layers = [
        (index, layer) for index, layer in enumerate(layered.layers())
        if opt(layer.to_StandardOpaqueMaterial()) is None
    ]
    if not nonstandard_layers:
        return None
    convertible = [
        (index, _kiva_carpet(layer)) for index, layer in nonstandard_layers
    ]
    if any(material is None for _index, material in convertible):
        return None

    before_r = None
    conductance = opt(layered.thermalConductance())
    if conductance is not None and conductance > 0:
        before_r = 1.0 / conductance

    # Always clone. Besides protecting other surfaces, this makes the conversion
    # replaceable as one object if the later foundation write is refused.
    target = layered.clone(model).to_LayeredConstruction().get()
    target.setName(f"{layered.nameString()} (Kiva)")
    if not surface.setConstruction(target):
        target.remove()
        raise RuntimeError(
            f"could not assign Kiva-compatible construction to "
            f"{surface.nameString()!r}")
    convertible = [
        (index, _kiva_carpet(layer))
        for index, layer in enumerate(target.layers())
        if opt(layer.to_StandardOpaqueMaterial()) is None
    ]

    replaced = []
    for index, material in convertible:
        resistance = material.thermalResistance()
        thickness = KIVA_CARPET_CONDUCTIVITY_W_MK * resistance
        replacement = openstudio.model.StandardOpaqueMaterial(
            model, material.roughness(), thickness,
            KIVA_CARPET_CONDUCTIVITY_W_MK,
            KIVA_CARPET_DENSITY_KG_M3,
            KIVA_CARPET_SPECIFIC_HEAT_J_KGK)
        replacement.setThermalAbsorptance(material.thermalAbsorptance())
        replacement.setSolarAbsorptance(material.solarAbsorptance())
        replacement.setVisibleAbsorptance(material.visibleAbsorptance())
        replacement.setName(
            f"{material.nameString()} (Kiva-compatible, "
            f"R-{ruby_str(ruby_round(resistance, 4))})")
        if not target.setLayer(index, replacement):
            replacement.remove()
            raise RuntimeError(
                f"could not replace massless layer {index} of "
                f"{target.nameString()!r}")
        replaced.append({
            "layer": material.nameString(),
            "resistance_m2k_w": resistance,
            "thickness_m": thickness,
            "added_mass_kg_m2": thickness * KIVA_CARPET_DENSITY_KG_M3,
            "added_heat_capacity_j_m2k":
                thickness * KIVA_CARPET_DENSITY_KG_M3
                * KIVA_CARPET_SPECIFIC_HEAT_J_KGK,
        })

    after_r = None
    conductance = opt(target.thermalConductance())
    if conductance is not None and conductance > 0:
        after_r = 1.0 / conductance

    return {
        "construction": target.nameString(),
        "cloned": True,
        "replaced": replaced,
        "resistance_before_m2k_w": before_r,
        "resistance_after_m2k_w": after_r,
    }
