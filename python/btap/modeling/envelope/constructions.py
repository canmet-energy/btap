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


def deep_copy(model, construction):
    """Clone the construction AND every layer material (a bare
    Construction#clone shares material objects, so solving one construction's
    insulation would mutate every other construction using the same material
    — port of the legacy construction_deep_copy)."""
    copy = construction.clone(model).to_Construction().get()
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


def opaque_at_conductance(model, construction, conductance):
    """Opaque construction at a target CONSTRUCTION conductance, W/(m2.K) —
    legacy-exact port of BTAP customize_opaque_construction: reuse by name,
    deep-copy, insulation-layer solve via SDK setConductance, layer-trimming
    fallback when the non-insulation layers alone exceed the target
    resistance."""
    base = re.sub(r":.*\Z", "", construction.nameString())
    # Names are keys for humans and legacy costing matchers; the
    # full-precision value lives in the material (setConductance below uses
    # the unrounded `conductance`). NECB table U-values are separated by far
    # more than 1e-4 W/(m2.K), so 4dp display names cannot collide.
    name = f"{base}:U-{ruby_str(ruby_round(conductance, 4))}"
    existing = opt(model.getConstructionByName(name))
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
