"""Inline-SVG primitives (port of report/svg.rb). Every chart is built from
these so the report needs no external assets or scripts."""

from __future__ import annotations

from btap._compat import esc, ruby_round, ruby_str
from btap.necb.report import html as Html


def _extra(opts):
    return "".join(
        f' {str(k).replace("_", "-")}="{esc(v)}"' for k, v in (opts or {}).items())


def open_svg(width, height, label):
    return (f'<svg viewBox="0 0 {width} {height}" role="img" '
            f'aria-label="{Html.esc(label)}" '
            'xmlns="http://www.w3.org/2000/svg" font-family="sans-serif" '
            'font-size="11">')


def close_svg():
    return "</svg>"


def rect(x, y, w, h, fill, opts=None):
    return (f'<rect x="{ruby_round(x, 1)}" y="{ruby_round(y, 1)}" '
            f'width="{ruby_round(max(w, 0), 1)}" height="{ruby_round(h, 1)}" '
            f'fill="{fill}"{_extra(opts)}/>')


def line(x1, y1, x2, y2, stroke, opts=None):
    return (f'<line x1="{ruby_round(x1, 1)}" y1="{ruby_round(y1, 1)}" '
            f'x2="{ruby_round(x2, 1)}" y2="{ruby_round(y2, 1)}" '
            f'stroke="{stroke}"{_extra(opts)}/>')


def text(x, y, string, opts=None):
    return (f'<text x="{ruby_round(x, 1)}" y="{ruby_round(y, 1)}"{_extra(opts)}>'
            f"{Html.esc(string)}</text>")


def bar_row(y, label, value, max_value, color, *, label_w, plot_w, bar_h=14,
            value_text=None):
    """The shared horizontal-bar primitive: a labelled bar with its value
    printed at the end. Returns SVG fragments (no <svg> wrapper)."""
    frac = max(float(value) / max_value, 0.0) if float(max_value) > 0 else 0.0
    bar_w = frac * plot_w
    out = []
    out.append(text(label_w - 6, y + bar_h - 3, label,
                    {"text_anchor": "end", "fill": "#111"}))
    out.append(rect(label_w, y, bar_w, bar_h, color))
    vtext = value_text if value_text is not None else ruby_str(value)
    if bar_w > plot_w * 0.55:
        out.append(text(label_w + bar_w - 5, y + bar_h - 3, vtext,
                        {"text_anchor": "end", "fill": "#fff"}))
    else:
        out.append(text(label_w + bar_w + 5, y + bar_h - 3, vtext,
                        {"fill": "#111"}))
    return "".join(out)
