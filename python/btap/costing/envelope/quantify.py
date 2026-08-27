"""Surface census for envelope costing — port of
BTAP::Attributes#compile_model. Buckets every costed surface/subsurface into
the 16 legacy surface types and computes each one's RSI the way legacy does:

- exterior/ground opaque surfaces: construction resistance + air films
  (legacy TBD.rsi(construction, filmResistance))
- subsurfaces: construction resistance only (no films)
- surfaces carrying a TBD 'uprated_Uo' additional property: 1/uprated_Uo
  (the thermally-derated effective value, films included by TBD)

Space conditioning: the legacy 'space_conditioning_category' additional
property is honoured when present (standards-built models); otherwise the
package's proxy (partofTotalFloorArea + dual-setpoint thermostat) decides.
Unconditioned spaces contribute no exterior roofs/floors — instead their
floor/wall surfaces' ADJACENT (conditioned-side) mirrors are censused as
InterzonalRoof / InterzonalSkylightWalls (attic pattern).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from btap._compat import opt, ruby_round, sorted_by_name
from btap.modeling.envelope import geometry

SURFACE_TYPES = (
    "ExteriorWall", "ExteriorRoof", "ExteriorFloor",
    "InterzonalRoof", "InterzonalSkylightWalls",
    "ExteriorFixedWindow", "ExteriorOperableWindow", "ExteriorSkylight",
    "ExteriorTubularDaylightDiffuser", "ExteriorTubularDaylightDome",
    "ExteriorDoor", "ExteriorGlassDoor", "ExteriorOverheadDoor",
    "GroundContactWall", "GroundContactRoof", "GroundContactFloor",
)

SUBSURFACE_TYPES = {
    "FixedWindow": "ExteriorFixedWindow",
    "OperableWindow": "ExteriorOperableWindow",
    "Skylight": "ExteriorSkylight",
    "TubularDaylightDiffuser": "ExteriorTubularDaylightDiffuser",
    "TubularDaylightDome": "ExteriorTubularDaylightDome",
    "Door": "ExteriorDoor",
    "GlassDoor": "ExteriorGlassDoor",
    "OverheadDoor": "ExteriorOverheadDoor",
}

GROUND_BOUNDARIES = ("Ground", "Foundation", "GroundFCfactorMethod",
                     "GroundSlabPreprocessorAverage")


@dataclass
class Item:
    surface: object
    surface_type: str
    rsi: float
    area_m2: float
    multiplier: int
    space_name: str


def census(model, audit=None) -> dict:
    """Returns {surface type: [Item, ...]} (a defaultdict — reading a key
    creates it, exactly like the Ruby Hash.new block)."""
    items = defaultdict(list)
    for space in sorted_by_name(model.getSpaces()):
        zone = opt(space.thermalZone())
        multiplier = zone.multiplier() if zone is not None else 1
        unconditioned = is_unconditioned(space)

        for surface in sorted_by_name(space.surfaces()):
            if surface.outsideBoundaryCondition() == "Outdoors":
                census_exterior(items, space, surface, multiplier, unconditioned)
            elif surface.outsideBoundaryCondition() in GROUND_BOUNDARIES:
                surface_type = {"Wall": "GroundContactWall",
                                "RoofCeiling": "GroundContactRoof",
                                "Floor": "GroundContactFloor"}.get(surface.surfaceType())
                if surface_type is not None:
                    add(items, surface_type, space, surface, multiplier, film=True)
            elif unconditioned and surface.adjacentSurface().is_initialized():
                census_interzonal(items, surface, multiplier)

    if audit is not None:
        summary = {
            surface_type: {"count": len(item_list),
                           "area_m2": ruby_round(sum(i.area_m2 for i in item_list), 1)}
            for surface_type, item_list in items.items() if len(item_list) > 0
        }
        audit.info("costing_envelope", "envelope surface census", inputs=summary)
    return items


def census_exterior(items, space, surface, multiplier, unconditioned):
    surface_type = surface.surfaceType()
    if surface_type == "Wall":
        add(items, "ExteriorWall", space, surface, multiplier, film=True)
    elif surface_type == "RoofCeiling":
        if not unconditioned:
            add(items, "ExteriorRoof", space, surface, multiplier, film=True)
    elif surface_type == "Floor":
        if not unconditioned:
            add(items, "ExteriorFloor", space, surface, multiplier, film=True)
    if unconditioned:
        return

    for sub in sorted_by_name(surface.subSurfaces()):
        sub_type = SUBSURFACE_TYPES.get(sub.subSurfaceType())
        if sub_type is not None:
            add(items, sub_type, space, sub, multiplier, film=False)


def census_interzonal(items, surface, _multiplier):
    """Attic pattern: this surface belongs to an UNCONDITIONED space and
    touches a conditioned one — census the conditioned-side mirror (legacy
    walks attic floors -> InterzonalRoof, attic walls ->
    InterzonalSkylightWalls)."""
    mirror = surface.adjacentSurface().get()
    mirror_space = opt(mirror.space())
    if mirror_space is None or is_unconditioned(mirror_space):
        return

    zone = opt(mirror_space.thermalZone())
    mirror_multiplier = zone.multiplier() if zone is not None else 1
    if surface.surfaceType() == "Floor":
        add(items, "InterzonalRoof", mirror_space, mirror, mirror_multiplier,
            film=True)
    elif surface.surfaceType() == "Wall":
        add(items, "InterzonalSkylightWalls", mirror_space, mirror,
            mirror_multiplier, film=True)


def add(items, surface_type, space, surface, multiplier, *, film):
    rsi = rsi_of(surface, film=film)
    if rsi is None:
        return

    items[surface_type].append(Item(
        surface=surface, surface_type=surface_type, rsi=rsi,
        area_m2=surface.netArea(), multiplier=multiplier,
        space_name=space.nameString()))


def rsi_of(surface, *, film):
    """film: include air films (legacy: surfaces yes, subsurfaces no)."""
    uprated = opt(surface.additionalProperties().getFeatureAsDouble("uprated_Uo"))
    if uprated is not None and uprated > 0:
        return 1.0 / uprated

    base = opt(surface.construction())
    if base is None:
        return None

    construction = opt(base.to_LayeredConstruction())
    if construction is None:
        return None

    conductance = opt(construction.thermalConductance())
    # fenestration (SimpleGlazing) has no layer conductance — use the
    # U-factor (films included by definition; legacy TBD.rsi treats it as
    # 1/usi likewise)
    if conductance is None:
        conductance = opt(construction.uFactor())
    if conductance is None or conductance <= 0:
        return None

    rsi = 1.0 / conductance
    if film:
        rsi += surface.filmResistance()
    return rsi


def is_unconditioned(space) -> bool:
    category = opt(space.additionalProperties()
                   .getFeatureAsString("space_conditioning_category"))
    if category is not None:
        return category.lower() == "unconditioned"

    return not geometry.is_conditioned(space)
