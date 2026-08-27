"""Costed-assembly selection: which BTAP-* assembly catalog
(constructions.json) each surface type is priced against. Port of
BTAP::Constructions.costed_assembly + btap/attributes.rb default tables. The
wall assembly follows the building structure (framing/cladding/finish) and
the requested performance tier; everything else is a fixed default (the
catalogs carry the RSI range, so U-value variation is handled by
interpolation, not by assembly choice).

The 'BTAP-ExteriorWall-Mass-2'-style strings are CATALOG KEYS matched
against the legacy database — never rename them.
"""

from __future__ import annotations

MASS2 = "BTAP-ExteriorWall-Mass-2"
MASSB = "BTAP-ExteriorWall-Mass-2b"
MASS4 = "BTAP-ExteriorWall-Mass-4"
MASS8 = "BTAP-ExteriorWall-Mass-8c"
WOOD5 = "BTAP-ExteriorWall-WoodFramed-5"
WOOD7 = "BTAP-ExteriorWall-WoodFramed-7"
STEL1 = "BTAP-ExteriorWall-SteelFramed-1"
STEL2 = "BTAP-ExteriorWall-SteelFramed-2"
ROOF = "BTAP-ExteriorRoof-IEAD-4"
FLOOR = "BTAP-ExteriorFloor-SteelFramed-1"

# Legacy default assemblies for the non-structural surface types
# (btap/attributes.rb @default_surface_constructions_by_type).
DEFAULTS = {
    "ExteriorFixedWindow": "BTAP-ExteriorWindow-FixedWindow-1",
    "ExteriorOperableWindow": "BTAP-ExteriorWindow-OperableWindow-5b",
    "ExteriorSkylight": "BTAP-Skylight-2",
    "ExteriorTubularDaylightDiffuser": "BTAP-Skylight-2",
    "ExteriorTubularDaylightDome": "BTAP-Skylight-2",
    "ExteriorDoor": "BTAP-ExteriorDoor-Metal-1",
    "ExteriorGlassDoor": "BTAP-ExteriorWindow-GlazedDoor-4",
    "ExteriorOverheadDoor": "BTAP-ExteriorOverheadDoor-Metal-1",
    "GroundContactWall": "BTAP-GroundContactWall-Mass-2",
    "GroundContactRoof": "BTAP-GroundContactRoof-Mass-2",
    "GroundContactFloor": "BTAP-GroundContactFloor-Unheated-1",
}

# Surface type -> constructions.json sheet (btap/attributes.rb).
SHEETS = {
    "ExteriorWall": "wall",
    "ExteriorRoof": "roof",
    "ExteriorFloor": "floor",
    "InterzonalRoof": "roof",
    "InterzonalSkylightWalls": "wall",
    "ExteriorFixedWindow": "window",
    "ExteriorOperableWindow": "window",
    "ExteriorSkylight": "skylight",
    "ExteriorTubularDaylightDiffuser": "skylight",
    "ExteriorTubularDaylightDome": "skylight",
    "ExteriorDoor": "door",
    "ExteriorGlassDoor": "door_glass",
    "ExteriorOverheadDoor": "door",
    "GroundContactWall": "bg_wall",
    "GroundContactRoof": "bg_roof",
    "GroundContactFloor": "slab",
}

GLAZING_SHEETS = ("door_glass", "skylight", "window")


def costed_assembly(structure, surface_type, performance) -> str:
    """Structural wall/roof/floor assembly (port of costed_assembly).

    structure: dict {'framing': 'steel'|'wood'|'cmu', 'cladding':, 'finish':}
    surface_type: 'walls', 'roofs' or 'floors'
    performance: 'lp' or 'hp'
    """
    if surface_type not in ("roofs", "floors"):
        surface_type = "walls"
    if performance != "hp":
        performance = "lp"
    if surface_type == "roofs":
        return ROOF
    if surface_type == "floors":
        return FLOOR
    if structure is None or len(structure) == 0:
        return STEL1

    framing = structure.get("framing")
    if framing == "wood":
        low, high = WOOD5, WOOD7
    elif framing == "cmu":
        low, high = MASS2, MASSB
    elif structure.get("cladding") == "heavy" and structure.get("finish") == "heavy":
        low, high = MASS4, MASS8
    else:
        low, high = STEL1, STEL2
    return low if performance == "lp" else high


def for_surface_type(surface_type, structure, performance) -> str:
    """Assembly name for any of the 16 costed surface types."""
    if surface_type in ("ExteriorWall", "InterzonalSkylightWalls"):
        return costed_assembly(structure, "walls", performance)
    if surface_type in ("ExteriorRoof", "InterzonalRoof"):
        return costed_assembly(structure, "roofs", performance)
    if surface_type == "ExteriorFloor":
        return costed_assembly(structure, "floors", performance)
    return DEFAULTS[surface_type]
