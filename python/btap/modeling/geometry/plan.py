"""Per-storey floor plans: :mod:`plan_query` (SDK) + :mod:`plan_svg`
(SDK-free drawing) composed into the two consumable products —

 * :func:`diagrams`    — a plain-dict bundle of inline SVG strings a HOST
                         report embeds (shaped like the hvac catalog_report's
                         ``model_diagrams``, the bundle btap-necb's AHJ report
                         already knows how to consume). NEVER raises.
 * :func:`html_report` — one self-contained standalone page (inline CSS,
                         inline SVG, native <details>, NO scripts and NO
                         external references of any kind — unlike the 3D
                         ``render`` viewer, which needs the model-viewer CDN).

:func:`png` is an OPTIONAL convenience: it rasterizes a plan through
whichever system SVG converter is installed and warns loudly (returning
None) when none is — a PNG is never a required output.

Port of btap-modeling/lib/btap_modeling/geometry/plan.rb (D-79).
"""

from __future__ import annotations

import os
import random
import re
import subprocess
import tempfile

import openstudio

from btap import __version__ as VERSION
from btap.modeling.geometry import plan_query as PlanQuery
from btap.modeling.geometry import plan_svg as PlanSvg

# ------------------------------------------------------------- bundle

def diagrams(model, audit=None):
    """Returns ``{'storeys': [{'name':, 'svg':}], 'legend_svg':, 'empty':,
    'inferred_storeys':, 'error': (only on failure)}``."""
    try:
        return bundle_from(PlanQuery.extract(model, audit=audit))
    except Exception as e:  # Ruby: rescue StandardError
        if audit is not None:
            audit.warn("plan", f"floor-plan diagrams failed — none produced ({e})")
        return {"storeys": [], "legend_svg": None, "empty": True,
                "inferred_storeys": False, "error": str(e)}


def bundle_from(data):
    """The SDK-free half of :func:`diagrams`: a plan_query dict -> the SVG
    bundle. Split out so a caller that also wants the raw dict (for the space
    tables) extracts ONCE."""
    if data.get("error"):
        return {"storeys": [], "legend_svg": None, "empty": True,
                "inferred_storeys": data.get("inferred_storeys") or False,
                "error": data["error"]}

    storeys = [{"name": storey["name"],
                "svg": PlanSvg.storey_svg(storey, bounds=data["bounds"],
                                          north_axis=float(data["north_axis_deg"]))}
               for storey in data["storeys"]]
    zones = list(dict.fromkeys(space["zone"]
                               for storey in data["storeys"]
                               for space in storey["spaces"]))
    return {"storeys": storeys,
            "legend_svg": None if not storeys else PlanSvg.legend_svg(zones),
            "empty": not storeys,
            "inferred_storeys": data["inferred_storeys"]}


# ------------------------------------------------------------- page

CSS = """\
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       color: #111; background: #fff; line-height: 1.45; font-size: 14px;
       max-width: 62rem; margin: 0 auto; padding: 1.5rem; }
h1 { font-size: 1.5rem; margin-bottom: .25rem; }
h2 { font-size: 1.15rem; margin: 1.6rem 0 .6rem; border-bottom: 2px solid #111; padding-bottom: .2rem; }
p.meta { color: #444; font-size: .85rem; }
section { margin-bottom: 1rem; break-inside: avoid; }
svg { width: 100%; height: auto; }
table { border-collapse: collapse; width: 100%; margin: .5rem 0; font-size: .85rem; }
th, td { border: 1px solid #bbb; padding: .3rem .5rem; text-align: left; vertical-align: top; }
thead th { background: #eee; }
nav.toc { font-size: .85rem; margin: .6rem 0 1rem; }
nav.toc a { margin-right: .9rem; color: #1a5276; }
details { margin: .5rem 0; } summary { cursor: pointer; font-weight: 600; }
.warnstrip { background: #fff3cd; border: 2px solid #9a6700; padding: .6rem .8rem;
             font-weight: 600; margin: .6rem 0; }
footer { margin-top: 2rem; font-size: .75rem; color: #555; border-top: 1px solid #bbb; padding-top: .5rem; }
@media print {
  body { max-width: none; padding: 0; font-size: 12px; }
  nav.toc { display: none; }
  .page-break { break-before: page; }
  h2 { break-after: avoid; }
  thead { display: table-header-group; }
  * { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
}
"""


def esc(value):
    return PlanSvg.esc(value)


def anchor(name):
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower())
    return "storey-" + re.sub(r"^-|-$", "", slug)


def html_report(model_or_path, path=None, audit=None, title="Floor plans"):
    """Model or .osm path -> the complete standalone page (also written to
    ``path`` when given). Never raises: an unreadable/plan-less model renders
    as a one-line note. Returns the full HTML document."""
    detail = extract_for(model_or_path, audit=audit)
    html = page(bundle_from(detail), title=title,
                source=source_label(model_or_path), detail=detail)
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
    return html


def extract_for(model_or_path, audit=None):
    """Model or .osm path -> the raw plan_query dict (an 'error' dict when
    the path will not load). Never raises."""
    model = load_model(model_or_path, audit=audit)
    if model is not None:
        return PlanQuery.extract(model, audit=audit)

    return {"storeys": [], "bounds": None, "inferred_storeys": False,
            "error": f"could not load {model_or_path}"}


def page(bundle, title="Floor plans", source=None, detail=None):
    """Assemble the document from an already-built bundle (``detail`` is the
    raw plan_query dict, used for the per-storey space tables; optional)."""
    body = ""
    body += f"<h1>{esc(title)}</h1>"
    if source is not None:
        body += f'<p class="meta">{esc(source)}</p>'
    body += f'<p class="meta">{esc(summary_line(bundle))}</p>'
    if bundle.get("inferred_storeys"):
        body += ('<p class="warnstrip">Storeys were inferred from floor elevations — '
                 "the model carries no usable BuildingStory assignments.</p>")
    if bundle.get("error"):
        body += f'<p class="warnstrip">No floor plans: {esc(bundle["error"])}</p>'
    elif bundle["empty"]:
        body += '<p class="warnstrip">No floor plans: the model has no space with a Floor surface.</p>'
    else:
        body += toc(bundle)
        # No zone legend on the page (phylroy, 2026-08-10): too small to read
        # and redundant with the per-storey space inventory below; the bundle
        # still carries legend_svg for hosts that want it.
        for index, storey in enumerate(bundle["storeys"]):
            body += storey_section(storey, index, detail)
    body += (f"<footer>Generated by btap-modeling {esc(VERSION)} — "
             "plan view of each storey in world coordinates; fills are per thermal zone.</footer>")
    return document(title, body)


def document(title, body):
    return ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{esc(title)}</title><style>{CSS}</style></head><body>{body}</body></html>")


def summary_line(bundle):
    if not bundle["storeys"]:
        return "no storeys rendered"

    names = ", ".join(s["name"] for s in bundle["storeys"])
    return f"{len(bundle['storeys'])} storey(s): {names}"


def toc(bundle):
    links = "".join(f'<a href="#{anchor(s["name"])}">{esc(s["name"])}</a>'
                    for s in bundle["storeys"])
    return f'<nav class="toc">{links}</nav>'


def storey_section(storey, index, detail):
    """One section per storey — `page-break` so printing gives a plan per
    page, `break-inside: avoid` (in CSS, on every section) so a plan is never
    split."""
    klass = "storey" if index == 0 else "storey page-break"
    table = space_table(detail, storey["name"])
    return (f'<section class="{klass}" id="{anchor(storey["name"])}"><h2>{esc(storey["name"])}</h2>'
            + str(storey["svg"]) + table + "</section>")


def space_table(detail, storey_name):
    """The optional collapsible space inventory (native <details>, no
    scripts)."""
    storey = (next((s for s in detail["storeys"] if s["name"] == storey_name), None)
              if detail else None)
    if storey is None or not storey["spaces"]:
        return ""

    rows = "".join(
        f"<tr><td>{esc(space['name'])}</td>"
        f"<td>{esc(space['zone'] if space['zone'] is not None else '—')}</td>"
        f"<td>{esc(space['space_type'] if space['space_type'] is not None else '—')}</td>"
        f"<td>{float(space['area_m2']):.1f}</td></tr>"
        for space in storey["spaces"])
    return (f"<details><summary>{len(storey['spaces'])} space(s)</summary>"
            "<table><thead><tr><th>Space</th><th>Thermal zone</th><th>Space type</th>"
            f"<th>Floor area (m²)</th></tr></thead><tbody>{rows}</tbody></table></details>")


# ------------------------------------------------------------- helpers

def load_model(model_or_path, audit=None):
    """Model in -> model out; .osm path in -> loaded model (None + audited
    warn when it will not load)."""
    if not isinstance(model_or_path, str):
        return model_or_path

    try:
        loaded = openstudio.model.Model.load(openstudio.path(model_or_path))
        if loaded.is_initialized():
            return loaded.get()

        if audit is not None:
            audit.warn("plan", "model could not be loaded — no floor plans produced",
                       target=model_or_path)
        return None
    except Exception as e:  # Ruby: rescue StandardError
        if audit is not None:
            audit.warn("plan", f"model could not be loaded — no floor plans produced ({e})",
                       target=str(model_or_path))
        return None


def source_label(model_or_path):
    if isinstance(model_or_path, str):
        return os.path.basename(model_or_path)

    name = model_or_path.building() if hasattr(model_or_path, "building") else None
    return name.get().nameString() if name is not None and name.is_initialized() else None


# ------------------------------------------------------------- PNG

#: Rasterizer probes, in preference order: (executable, argv builder).
RASTERIZERS = (
    ("rsvg-convert", lambda svg, png: ["rsvg-convert", "-o", png, svg]),
    ("cairosvg", lambda svg, png: ["cairosvg", svg, "-o", png]),
    ("magick", lambda svg, png: ["magick", svg, png]),
)


def rasterizer():
    """First rasterizer on PATH, or None."""
    return next((entry for entry in RASTERIZERS if which(entry[0])), None)


def which(exe):
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(directory, exe)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def png(svg, path, audit=None):
    """OPTIONAL rasterization of one plan SVG. Returns the written path, or
    None (with a loud audit warning) when no system rasterizer is installed
    or the conversion fails. Never raises, never a hard dependency."""
    svg_path = None
    try:
        found = rasterizer()
        if found is None:
            if audit is not None:
                audit.warn("plan", "no SVG rasterizer found — PNG not produced",
                           target=os.path.basename(str(path)),
                           inputs={"probed": [exe for exe, _ in RASTERIZERS]})
            return None

        os.makedirs(os.path.dirname(str(path)) or ".", exist_ok=True)
        # rand is fine here — it names a temp file, not a result.
        svg_path = os.path.join(tempfile.gettempdir(),
                                f"plan_{os.getpid()}_{random.randrange(1 << 32)}.svg")
        with open(svg_path, "w", encoding="utf-8") as f:
            f.write(svg)
        try:
            ok = subprocess.run(found[1](svg_path, str(path)),
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL).returncode == 0
        except FileNotFoundError:  # Ruby `system` returns nil here
            ok = False
        if not (ok and os.path.exists(str(path))):
            if audit is not None:
                audit.warn("plan", f"{found[0]} failed to rasterize the plan — PNG not produced",
                           target=os.path.basename(str(path)))
            return None
        return str(path)
    except Exception as e:  # Ruby: rescue StandardError
        if audit is not None:
            audit.warn("plan", f"PNG rasterization failed ({e})",
                       target=os.path.basename(str(path)))
        return None
    finally:
        if svg_path and os.path.exists(svg_path):
            os.remove(svg_path)


def pngs(bundle, directory, audit=None):
    """Rasterize a whole bundle into ``directory``, one PNG per storey.
    Returns the written paths (empty when no rasterizer is available)."""
    os.makedirs(str(directory), exist_ok=True)
    written = []
    for storey in bundle["storeys"]:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(storey["name"]))
        result = png(storey["svg"], os.path.join(str(directory), f"{slug}.png"), audit=audit)
        if result is not None:
            written.append(result)
    return written
