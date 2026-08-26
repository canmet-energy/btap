"""SDK-FREE inline-SVG primitives + the per-storey floor-plan drawing built
from them. Pure functions over the :mod:`plan_query` dicts, so every drawing
rule is unit-testable against a hand-written dict — no OpenStudio needed.

The primitives (open_svg/close_svg/rect/line/text) are a LOCAL COPY of
btap-necb's ``report/svg.rb``, plus the polygon/group/title helpers the
family lacked. They are copied rather than imported: btap-modeling sits
BELOW btap-necb in the dependency graph and must never depend upward (the
documented catalog_report.rb:29-32 precedent). The necb convention is kept:
a fit-to-width ``viewBox`` and NO width/height attributes, so a host
stylesheet's ``svg { width: 100% }`` scales the plan to the page.

Port of btap-modeling/lib/btap_modeling/geometry/plan_svg.rb (D-79).
"""

from __future__ import annotations

import math

from btap._compat import ruby_round

WIDTH = 920.0           # viewBox width; drawings fit to it
PAD = 26.0              # margin around the footprint, in viewBox units
MIN_HEIGHT = 120.0
LABEL_MIN_W = 54.0      # below this a two-line label is illegible: skipped
LABEL_MIN_H = 26.0
NAME_SIZE = 11.0
ZONE_SIZE = 9.0
CHAR_W = 0.55           # sans-serif average advance, in font-size units
NO_ZONE_FILL = "#ffffff"
NO_ZONE_LABEL = "unassigned"


# ------------------------------------------------------------ primitives

def esc(value):
    return (str(value if value is not None else "")
            .replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def attrs(opts):
    return "".join(f' {str(k).replace("_", "-")}="{esc(v)}"' for k, v in opts.items())


def open_svg(width, height, label):
    return (f'<svg viewBox="0 0 {ruby_round(width, 1)} {ruby_round(height, 1)}" '
            f'role="img" aria-label="{esc(label)}" '
            'xmlns="http://www.w3.org/2000/svg" font-family="sans-serif" font-size="11">')


def close_svg():
    return "</svg>"


def rect(x, y, w, h, fill, opts=None):
    return (f'<rect x="{ruby_round(x, 1)}" y="{ruby_round(y, 1)}" '
            f'width="{ruby_round(max(w, 0), 1)}" '
            f'height="{ruby_round(max(h, 0), 1)}" fill="{fill}"{attrs(opts or {})}/>')


def line(x1, y1, x2, y2, stroke, opts=None):
    return (f'<line x1="{ruby_round(x1, 1)}" y1="{ruby_round(y1, 1)}" '
            f'x2="{ruby_round(x2, 1)}" y2="{ruby_round(y2, 1)}" '
            f'stroke="{stroke}"{attrs(opts or {})}/>')


def text(x, y, string, opts=None):
    return (f'<text x="{ruby_round(x, 1)}" y="{ruby_round(y, 1)}"'
            f'{attrs(opts or {})}>{esc(string)}</text>')


def polygon(points, fill, opts=None, *, title=None):
    """New in this gem: a filled polygon, optionally carrying a native
    <title> tooltip child (self-closing when there is nothing to say)."""
    coords = " ".join(f"{ruby_round(x, 1)},{ruby_round(y, 1)}" for x, y in points)
    head = f'<polygon points="{coords}" fill="{fill}"{attrs(opts or {})}'
    return f"{head}>{_title(title)}</polygon>" if title is not None else f"{head}/>"


def title(string):
    """New: hover tooltip / accessible name for the element containing it."""
    return f"<title>{esc(string)}</title>"


_title = title  # `polygon`'s title= parameter shadows the function name


def group(content, opts=None):
    """New: a <g> wrapper around pre-built fragments."""
    return f"<g{attrs(opts or {})}>{content}</g>"


# ------------------------------------------------------------- palette

def zone_color(zone):
    """Deterministic zone -> HSL fill. The language string hash is SEEDED PER
    PROCESS (Ruby's String#hash; Python's hash() via PYTHONHASHSEED), so a
    stable djb2 is used instead: the same zone gets the same color in every
    run, every storey and every document — and identically in the Ruby gem.
    Lightness stays high (65%) so the black centroid labels stay readable on
    top."""
    if zone is None or str(zone) == "":
        return NO_ZONE_FILL

    return f"hsl({djb2(str(zone)) % 360}, 45%, 65%)"


def djb2(string):
    value = 5381
    for byte in string.encode("utf-8"):
        value = ((value * 33) + byte) & 0xFFFFFFFF
    return value


# ------------------------------------------------------- storey drawing

def storey_svg(storey, bounds=None, width=WIDTH, north_axis=0.0):
    """One storey -> one inline <svg>. ``bounds`` is the WHOLE BUILDING's
    extent (from plan_query) so every storey is drawn at the same scale and
    position and the storeys stack visually.

    ``storey`` is ``{'name':, 'z':, 'spaces': [...]}``; ``bounds`` is
    ``{'min_x':, 'min_y':, 'max_x':, 'max_y':}`` or None. Returns a complete
    <svg> element."""
    if bounds is None:
        bounds = derive_bounds(storey["spaces"])
    if bounds is None:
        return empty_svg(storey["name"], width)

    scale, height = fit(bounds, width)
    body = "".join(space_group(space, bounds, scale, height) for space in storey["spaces"])
    label_text = f"Floor plan — {storey['name']}"
    return "".join([open_svg(width, height, label_text),
                    rect(0, 0, width, height, "#ffffff"),
                    body,
                    scale_bar(scale, width, height),
                    north_arrow(width, north_axis),
                    close_svg()])


def north_arrow(width, north_axis):
    """True-north arrow, top-right. Building coordinates put "building north"
    up the page; the Building North Axis is the building y-axis's CLOCKWISE
    rotation from true north, so true north on screen is the up-arrow rotated
    by -north_axis (SVG rotate is clockwise-positive on the flipped y axis;
    sanity case: north_axis 90 = building y faces east = true north points
    LEFT on the plan)."""
    cx = width - PAD - 12
    cy = PAD + 12
    arrow = "".join([line(0, 10, 0, -8, "#111", {"stroke_width": 1.5}),
                     '<polygon points="0,-12 -4,-4 4,-4" fill="#111"/>',
                     text(0, -15, "N", {"text_anchor": "middle", "fill": "#111",
                                        "font_size": 10, "font_weight": "bold"})])
    return (f'<g class="north-arrow" transform="translate({ruby_round(cx, 1)},{ruby_round(cy, 1)}) '
            f'rotate({ruby_round(-float(north_axis), 1)})">{arrow}</g>')


def project(x, y, bounds, scale, height):
    """Building coords (metres, y up) -> viewBox coords (y DOWN, flipped)."""
    return [PAD + ((x - bounds["min_x"]) * scale),
            height - PAD - ((y - bounds["min_y"]) * scale)]


def fit(bounds, width):
    span_x = max(bounds["max_x"] - bounds["min_x"], 1e-6)
    span_y = max(bounds["max_y"] - bounds["min_y"], 1e-6)
    scale = (width - (2 * PAD)) / span_x
    height = max((span_y * scale) + (2 * PAD), MIN_HEIGHT)
    return scale, height


def derive_bounds(spaces):
    points = [point for space in spaces for ring in space["polygons"] for point in ring]
    if not points:
        return None

    return {"min_x": min(p[0] for p in points), "min_y": min(p[1] for p in points),
            "max_x": max(p[0] for p in points), "max_y": max(p[1] for p in points)}


def empty_svg(name, width):
    return "".join([open_svg(width, MIN_HEIGHT, f"Floor plan — {name} (no geometry)"),
                    text(width / 2, MIN_HEIGHT / 2, "no floor geometry on this storey",
                         {"text_anchor": "middle", "fill": "#777"}),
                    close_svg()])


def space_group(space, bounds, scale, height):
    """One space: its filled ring(s) — each carrying the tooltip — plus the
    two-line centroid label when the shape is big enough to hold it."""
    fill = zone_color(space["zone"])
    tip = tooltip(space)
    rings = "".join(
        polygon([project(x, y, bounds, scale, height) for x, y in ring], fill,
                {"stroke": "#333", "stroke_width": 0.8}, title=tip)
        for ring in space["polygons"])
    return group(rings + label(space, bounds, scale, height))


def tooltip(space):
    """ALWAYS present, on every polygon: the full identity of the space, so a
    shape too small to label still answers a hover."""
    return " | ".join([space["name"],
                       space["zone"] if space["zone"] is not None else NO_ZONE_LABEL,
                       space["space_type"] if space["space_type"] is not None else "no space type",
                       f"{float(space['area_m2']):.1f} m²"])


def label(space, bounds, scale, height):
    """Two lines at the centroid: space name, zone name smaller beneath.
    Skipped entirely when the space's largest ring cannot hold legible text
    (the tooltip still carries everything)."""
    ring = max(space["polygons"], default=None,
               key=lambda r: ring_span(r)[0] * ring_span(r)[1])
    if ring is None:
        return ""

    span_x, span_y = ring_span(ring)
    box_w = span_x * scale
    box_h = span_y * scale
    if box_w < LABEL_MIN_W or box_h < LABEL_MIN_H:
        return ""

    cx, cy = project(*space["centroid"], bounds, scale, height)
    name = clip(space["name"], box_w, NAME_SIZE)
    out = text(cx, cy, name, {"text_anchor": "middle", "fill": "#111", "font_size": NAME_SIZE})
    zone = space["zone"]
    if zone is not None and box_h >= LABEL_MIN_H + ZONE_SIZE:
        out += text(cx, cy + ZONE_SIZE + 2, clip(zone, box_w, ZONE_SIZE),
                    {"text_anchor": "middle", "fill": "#444", "font_size": ZONE_SIZE})
    return out


def ring_span(ring):
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return [max(xs) - min(xs), max(ys) - min(ys)]


def clip(string, box_w, font_size):
    """Truncate to what fits the shape at this font size (never mid-render
    overflow into the neighbouring space)."""
    max_chars = math.floor(box_w / (font_size * CHAR_W))
    if len(string) <= max_chars:
        return string
    if max_chars < 4:
        return string[:max_chars]

    return f"{string[:max_chars - 1]}…"


def scale_bar(scale, width, height):
    """A 1-2-5 rounded metric scale bar, so the plan reads as a drawing."""
    target = (width - (2 * PAD)) / 5.0
    metres = nice_length(target / scale)
    length = metres * scale
    x = width - PAD - length
    y = height - 8
    return "".join([line(x, y, x + length, y, "#111", {"stroke_width": 1.5}),
                    line(x, y - 4, x, y + 2, "#111", {"stroke_width": 1.5}),
                    line(x + length, y - 4, x + length, y + 2, "#111", {"stroke_width": 1.5}),
                    text(x + (length / 2), y - 6, f"{fmt_metres(metres)} m",
                         {"text_anchor": "middle", "fill": "#111", "font_size": 9})])


def nice_length(raw):
    if raw <= 0:
        return 1.0

    exponent = math.floor(math.log10(raw))
    base = 10.0 ** exponent
    return min((m * base for m in (1, 2, 5, 10)), key=lambda candidate: abs(candidate - raw))


def fmt_metres(metres):
    return str(int(metres)) if metres == int(metres) else f"{metres:.1f}"


# ---------------------------------------------------------------- legend

def legend_svg(zones, width=WIDTH, columns=3):
    """The shared zone legend: one swatch per zone across the whole model, in
    the same colors the plans use. ``zones`` may contain None (unassigned)."""
    entries = sorted(dict.fromkeys(zones),
                     key=lambda zone: (1 if _zone_str(zone) == "" else 0, _zone_str(zone)))
    if not entries:
        return empty_legend(width)

    rows = math.ceil(len(entries) / columns)
    col_w = (width - (2 * PAD)) / columns
    height = (rows * 18.0) + 30.0
    cells = "".join(
        rect(PAD + ((index // rows) * col_w), 26.0 + ((index % rows) * 18.0) - 9, 11, 11,
             zone_color(zone), {"stroke": "#333", "stroke_width": 0.6})
        + text(PAD + ((index // rows) * col_w) + 16, 26.0 + ((index % rows) * 18.0),
               zone if zone is not None else NO_ZONE_LABEL, {"fill": "#111", "font_size": 10})
        for index, zone in enumerate(entries))
    return "".join([open_svg(width, height, "Thermal zone legend"),
                    text(PAD, 14, "Thermal zones",
                         {"fill": "#111", "font_size": 11, "font_weight": "bold"}),
                    cells,
                    close_svg()])


def _zone_str(zone):
    return "" if zone is None else str(zone)


def empty_legend(width):
    return "".join([open_svg(width, 30, "Thermal zone legend (empty)"),
                    text(PAD, 18, "no thermal zones", {"fill": "#777", "font_size": 10}),
                    close_svg()])
