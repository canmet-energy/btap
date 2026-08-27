"""Core prescriptive lookups over the vendored rules data (port of
btap-necb's envelope/rules.rb). Semantics are legacy-exact (parity-gated
against openstudio-standards NECB2020):

- max_u: scan HDD-bin ceilings ascending, return the first value where
  hdd < bin; fallback 0.110 (legacy max_u_necb, building_envelope.rb:307)
- max_fdwr: piecewise interpreter over structured data (never eval'd)
"""

from __future__ import annotations

from btap._compat import NullAudit, ruby_round

U_FALLBACK = 0.110
SURFACE_TYPES = ["wall", "roofceiling", "floor", "window", "skylight", "door"]
BOUNDARIES = ["outdoors", "ground"]


def max_u(*, vintage, surface, boundary, hdd, audit=None):
    """Maximum overall (effective) thermal transmittance, W/(m2.K).

    :param surface: wall|roofceiling|floor|window|skylight|door
    :param boundary: outdoors|ground
    """
    from btap.necb import envelope

    audit = audit if audit is not None else NullAudit()
    u_values = envelope.rules(vintage)["u_values"]
    if str(boundary) not in u_values:
        raise ValueError(f"unknown boundary '{boundary}' ({'/'.join(BOUNDARIES)})")
    table = u_values[str(boundary)]
    if str(surface) not in table:
        raise ValueError(f"unknown surface '{surface}' for boundary '{boundary}'")
    bins = table[str(surface)]

    value = None
    for key, bin_value in sorted(bins.items(), key=lambda kv: int(kv[0])):
        if hdd < int(key):
            value = bin_value
            break
    if value is None:
        value = U_FALLBACK
    audit.decision("rules", "maximum effective U-value looked up",
                   inputs={"vintage": vintage, "surface": surface,
                           "boundary": boundary, "hdd": hdd},
                   value=f"{value} W/m2K",
                   article=f"NECB {vintage} Tables 3.2.2.x/3.2.3.1 (3.1.1.7 effective)")
    return value


def ground_floor_extent(*, vintage, hdd):
    """Ground-floor insulation extent (Table 3.2.3.1 floors row): zone 8
    requires the table U over the full slab area; zones 4-7B require it only
    within a perimeter strip (3.2.3.3.(3)) — the slab field carries no
    prescriptive maximum there."""
    from btap.necb import envelope

    ext = envelope.rules(vintage).get("ground_floor_extent")
    if ext is None or hdd >= ext["full_area_min_hdd"]:
        return {"extent": "full_area"}

    return {"extent": "perimeter_strip", "width_m": ext["strip_width_m"]}


def max_fdwr(*, vintage, hdd, audit=None):
    """Maximum fenestration-and-door-to-gross-wall ratio (3.2.1.4.(1))."""
    from btap.necb import envelope

    audit = audit if audit is not None else NullAudit()
    fdwr = envelope.rules(vintage)["fdwr"]
    value = None
    for piece in fdwr["pieces"]:
        if piece.get("linear") is not None:
            if not (hdd >= piece["min_hdd"] and hdd < piece["max_hdd"]):
                continue

            linear = piece["linear"]
            value = (linear["intercept"] + linear["slope"] * hdd) / linear["divisor"]
            break
        elif piece.get("max_hdd") is not None:
            if hdd < piece["max_hdd"]:
                value = piece["value"]
                break
        elif piece.get("min_hdd") is not None:
            if hdd >= piece["min_hdd"]:
                value = piece["value"]
                break
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RuntimeError(f"fdwr pieces did not cover hdd={hdd}")

    audit.decision("rules", "maximum FDWR computed",
                   inputs={"vintage": vintage, "hdd": hdd},
                   value=ruby_round(value, 4),
                   article=fdwr.get("article"))
    return value


def max_srr(*, vintage, audit=None):
    """Maximum skylight-to-gross-roof-area ratio (3.2.1.4.(2))."""
    from btap.necb import envelope

    audit = audit if audit is not None else NullAudit()
    srr = envelope.rules(vintage)["srr_max"]
    audit.decision("rules", "maximum skylight-to-roof ratio looked up",
                   inputs={"vintage": vintage}, value=srr.get("value"),
                   article=srr.get("article"))
    return srr["value"]
