"""Proposed-vs-reference comparison charts built on svg.bar_row (port of
report/charts.rb)."""

from __future__ import annotations

from btap.necb.report import html as Html
from btap.necb.report import svg as SVG

LABEL_W = 150
PLOT_W = 560
WIDTH = LABEL_W + PLOT_W + 90
BAR_H = 14
PAIR_GAP = 4
GROUP_GAP = 14


def _blank(v):
    return v is None or v == 0


def paired_bars(rows, *, unit, label, prec=0):
    """rows: [[label, proposed_value, reference_value], ...] — reference may
    be None (EUI-only runs render proposed bars alone)."""
    rows = [r for r in rows if not (_blank(r[1]) and _blank(r[2]))]
    if not rows:
        return ""

    values = [v for _, p, r in rows for v in (p, r) if v is not None]
    max_value = float(max(values))
    if max_value == 0:
        return ""

    has_ref = any(r is not None for _, _, r in rows)
    group_h = (2 * BAR_H + PAIR_GAP) if has_ref else BAR_H
    height = len(rows) * (group_h + GROUP_GAP) + 10
    out = [SVG.open_svg(WIDTH, height, label)]
    y = 5
    for row_label, proposed, reference in rows:
        out.append(SVG.bar_row(
            y, row_label, proposed or 0, max_value, Html.PROPOSED_COLOR,
            label_w=LABEL_W, plot_w=PLOT_W, bar_h=BAR_H,
            value_text=f"{Html.fmt(proposed, prec=prec)} {unit}"))
        if has_ref:
            out.append(SVG.bar_row(
                y + BAR_H + PAIR_GAP, "", reference or 0, max_value,
                Html.REFERENCE_COLOR,
                label_w=LABEL_W, plot_w=PLOT_W, bar_h=BAR_H,
                value_text=f"{Html.fmt(reference, prec=prec)} {unit}"))
        y += group_h + GROUP_GAP
    out.append(SVG.close_svg())
    return "".join(out)


def total_bars(rows, *, targets=(), unit="kWh", label="Annual energy totals"):
    """Totals bar chart with dashed vertical target line(s):
    targets: [[label, value], ...] drawn as dashed lines across the plot."""
    rows = [r for r in rows if r[1] is not None]
    if not rows:
        return ""

    candidates = [v for _, v in rows] + [v for _, v in targets]
    max_value = float(max((v for v in candidates if v is not None), default=0))
    if max_value == 0:
        return ""

    height = len(rows) * (BAR_H + GROUP_GAP) + (10 if not targets else 30)
    out = [SVG.open_svg(WIDTH, height, label)]
    y = 5
    for i, (row_label, value) in enumerate(rows):
        color = Html.PROPOSED_COLOR if i == 0 else Html.REFERENCE_COLOR
        out.append(SVG.bar_row(
            y, row_label, value, max_value, color,
            label_w=LABEL_W, plot_w=PLOT_W, bar_h=BAR_H,
            value_text=f"{Html.fmt(value, prec=0)} {unit}"))
        y += BAR_H + GROUP_GAP
    for i, (t_label, t_value) in enumerate(targets):
        x = LABEL_W + (t_value / max_value) * PLOT_W
        out.append(SVG.line(x, 0, x, y, "#b02a37",
                            {"stroke_dasharray": "5,4", "stroke_width": 2}))
        out.append(SVG.text(x + 4, y + 12 + (i * 12),
                            f"{t_label}: {Html.fmt(t_value, prec=0)} {unit}",
                            {"fill": "#b02a37"}))
    out.append(SVG.close_svg())
    return "".join(out)
