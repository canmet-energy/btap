"""HTML string helpers + the report stylesheet (port of report/html.rb).
Everything is escaped unless wrapped in Raw (pre-built fragments from these
helpers)."""

from __future__ import annotations

import re

from btap._compat import Raw, esc, ruby_round, ruby_str

__all__ = ["Raw", "esc", "raw", "cell", "tag", "section", "table", "kv_table",
           "badge", "glyph", "fmt", "building_chip", "details", "legend",
           "PROPOSED_COLOR", "REFERENCE_COLOR", "GLYPHS", "CSS"]

PROPOSED_COLOR = "#1a5276"
REFERENCE_COLOR = "#7f8c8d"


def raw(html):
    """Mark a pre-built HTML fragment as safe to embed unescaped."""
    return Raw(html)


def cell(value):
    """Render a table-cell value: Raw fragments pass through, all else
    escapes."""
    return value.html if isinstance(value, Raw) else esc(value)


def tag(name, content=None, **attrs):
    """One HTML element; underscores in attribute names become dashes."""
    attr_string = "".join(
        f' {str(k).replace("_", "-")}="{esc(v)}"' for k, v in attrs.items())
    if content is None:
        return f"<{name}{attr_string}>"
    return f"<{name}{attr_string}>{cell(content)}</{name}>"


def section(id, title, body, page_break=False):
    """A top-level report <section> with its <h2> (id anchors the TOC link)."""
    klass = ' class="page-break"' if page_break else ""
    return f'<section id="{id}"{klass}><h2>{esc(title)}</h2>{body}</section>'


def table(headers, rows, css=None):
    """A full <table> from a header row + list-of-lists body."""
    head = "".join(f"<th>{cell(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{cell(c)}</td>" for c in r) + "</tr>" for r in rows)
    klass = f' class="{css}"' if css else ""
    return (f"<table{klass}><thead><tr>{head}</tr></thead>"
            f"<tbody>{body}</tbody></table>")


def kv_table(pairs):
    """Two-column key/value table (project header, summary blocks)."""
    rows = "".join(f"<tr><th>{esc(k)}</th><td>{cell(v)}</td></tr>" for k, v in pairs)
    return f'<table class="kv">{rows}</table>'


def badge(text, kind):
    """Verdict pill; kind selects the CSS class (pass/fail/warn/tier/ghg)."""
    return f'<span class="badge badge-{kind}">{esc(text)}</span>'


GLYPHS = {"pass": ("✓", "pass"), "fail": ("✗", "fail"), "warning": ("▲", "warn"),
          "info": ("●", "info"), "na": ("○", "na")}


def glyph(kind):
    """Checklist status glyph (pass/fail/warning/info/na)."""
    symbol, klass = GLYPHS.get(kind, GLYPHS["na"])
    return f'<span class="glyph glyph-{klass}">{symbol}</span>'


def fmt(value, unit=None, prec=1):
    """Format a number for display: None -> em-dash, thousands separators,
    ``prec`` decimal places (default 1; integers drop the trailing .0),
    optional ``unit`` suffix. THE number formatter — used ~60x in sections."""
    if value is None:
        return "—"

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        rounded = ruby_round(value, prec)
        if prec == 0 or rounded == int(rounded):
            rounded = int(rounded)
        text = re.sub(r"(\d{3})(?=\d)", r"\1,", ruby_str(rounded)[::-1])[::-1]
    else:
        text = ruby_str(value)
    return f"{text} {unit}" if unit else text


def building_chip(name):
    """Which-model tag for audit-derived rows: proposed (blue), reference
    (gray), input model (amber); None = a cross-building comparison/verdict."""
    if name is None or str(name) == "":
        return '<span class="bldg bldg-na">comparison</span>'

    text = str(name)
    if re.search("reference", text, re.IGNORECASE):
        klass = "bldg-reference"
    elif re.search("input", text, re.IGNORECASE):
        klass = "bldg-input"
    else:
        klass = "bldg-proposed"
    label = re.sub(r" building\Z", "", text)
    return f'<span class="bldg {klass}">{esc(label)}</span>'


def details(summary, body, open=False):
    """Native collapsible block (the report's only interactivity beyond the
    loop chooser)."""
    return (f"<details{' open' if open else ''}><summary>{esc(summary)}"
            f"</summary>{body}</details>")


def legend():
    """Proposed/Reference color-chip legend for charts."""
    return (f'<span class="chip" style="background:{PROPOSED_COLOR}"></span> Proposed\n'
            f'          <span class="chip" style="background:{REFERENCE_COLOR}"></span> Reference')


CSS = """\
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       color: #111; background: #fff; line-height: 1.45; font-size: 14px;
       max-width: 62rem; margin: 0 auto; padding: 1.5rem; }
h1 { font-size: 1.5rem; margin-bottom: .25rem; }
h2 { font-size: 1.15rem; margin: 1.6rem 0 .6rem; border-bottom: 2px solid #111; padding-bottom: .2rem; }
h3 { font-size: 1rem; margin: .9rem 0 .4rem; }
p.meta { color: #444; font-size: .85rem; }
section { margin-bottom: 1rem; }
table { border-collapse: collapse; width: 100%; margin: .5rem 0; font-size: .85rem; }
th, td { border: 1px solid #bbb; padding: .3rem .5rem; text-align: left; vertical-align: top; }
thead th { background: #eee; }
table.kv { width: auto; min-width: 50%; }
table.kv th { background: #f4f4f4; width: 14rem; font-weight: 600; }
table.checklist { table-layout: fixed; }
table.checklist th:nth-child(1), table.checklist td:nth-child(1) { width: 2rem; text-align: center; }
table.checklist th:nth-child(2), table.checklist td:nth-child(2) { width: 8.5rem; }
table.checklist th:nth-child(3), table.checklist td:nth-child(3) { width: 7.5rem; }
table.checklist tbody tr:nth-child(even) { background: #f8f9fa; }
table.checklist td { padding-top: .55rem; padding-bottom: .55rem; }
.checklist-statement { font-size: .9rem; line-height: 1.45; }
.checklist-summary { font-weight: 700; margin-bottom: .35rem; }
.checklist-detail { margin-top: .3rem; }
.checklist-detail span { display: inline-block; min-width: 3.8rem; color: #1f5132;
                         font-size: .72rem; font-weight: 700; text-transform: uppercase; }
.checklist-gaps { margin-top: .45rem; padding-top: .4rem; border-top: 1px solid #ddd; }
.checklist-gaps span { color: #8a4b08; }
.checklist-evidence { color: #4b5563; font-size: .78rem; line-height: 1.4;
                      margin-top: .35rem; padding-top: .3rem; border-top: 1px solid #ddd;
                      overflow-wrap: anywhere; }
.checklist-evidence span { color: #30363d; font-weight: 700; }
.banner { border: 3px solid #111; padding: 1rem; margin: 1rem 0; display: flex;
          flex-wrap: wrap; gap: 1.2rem; align-items: center; }
.banner .big { font-size: 1.6rem; font-weight: 700; }
.badge { display: inline-block; padding: .18rem .6rem; border-radius: .3rem;
         font-weight: 700; font-size: .85rem; color: #fff; }
.badge-pass { background: #1e7e34; } .badge-fail { background: #b02a37; }
.badge-tier { background: #1a5276; } .badge-ghg { background: #5b2c6f; }
.badge-warn { background: #9a6700; }
.glyph { font-weight: 700; }
.glyph-pass { color: #1e7e34; } .glyph-fail { color: #b02a37; }
.glyph-warn { color: #9a6700; } .glyph-info { color: #1a5276; } .glyph-na { color: #777; }
.chip { display: inline-block; width: .8rem; height: .8rem; border-radius: .15rem;
        vertical-align: middle; margin: 0 .25rem 0 .8rem; }
.warnstrip { background: #fff3cd; border: 2px solid #9a6700; padding: .6rem .8rem;
             font-weight: 600; margin: .6rem 0; }
.bldg { display: inline-block; padding: .05rem .45rem; border-radius: .7rem;
        font-size: .75rem; font-weight: 700; color: #fff; white-space: nowrap; }
.bldg-proposed { background: #1a5276; } .bldg-reference { background: #7f8c8d; }
.bldg-input { background: #9a6700; } .bldg-na { background: #fff; color: #555; border: 1px solid #999; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
svg { width: 100%; height: auto; }
nav.toc { font-size: .85rem; margin: .6rem 0 1rem; }
nav.toc a { margin-right: .9rem; color: #1a5276; }
details { margin: .5rem 0; } summary { cursor: pointer; font-weight: 600; }
.sig { display: inline-block; width: 45%; margin: 1.6rem 2% 0 0; border-top: 1px solid #111;
       padding-top: .3rem; font-size: .85rem; }
footer { margin-top: 2rem; font-size: .75rem; color: #555; border-top: 1px solid #bbb; padding-top: .5rem; }
/* OpenStudio-App-style per-building loop dropdown chooser (inline JS) */
.hvac-select { margin: .5rem 0 1rem; }
.loop-select-label { font-weight: 600; font-size: .9rem; }
.loop-select { font-size: .9rem; padding: .2rem .4rem; margin-left: .3rem; }
.loop-panel[hidden] { display: none; }
.loop-panel-title { display: none; }
@media print {
  /* reveal every loop on paper (the chooser hides non-active panels on screen) */
  .loop-panel[hidden] { display: block !important; }
  .loop-panel-title { display: block; font-weight: 600; }
  .loop-select-label { display: none; }
  body { max-width: none; padding: 0; font-size: 12px; }
  nav.toc { display: none; }
  section { break-inside: avoid; }
  .page-break { break-before: page; }
  h2 { break-after: avoid; }
  thead { display: table-header-group; }
  * { print-color-adjust: exact; -webkit-print-color-adjust: exact; }
}
"""
