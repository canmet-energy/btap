"""The NECB report renderer (port of btap-necb's report.rb + report/).

The renderer is a layered stack — each module has one job:
  svg.py          geometric primitives (bars, axes, legends) -> inline SVG
  charts.py       proposed-vs-reference comparison charts, built on svg
  html.py         escaping, tags, tables, badges, the shared CSS
  checklist.py    audit entries -> article-sorted checklist rows
  model_query.py  SDK models -> plain dicts (with this assembler, the ONLY
                  SDK-touching part of the renderer; never raises)
  sections.py     composes the document sections from plain data
  (this file)     assembles the full HTML document

Renders a ComplianceResult into ONE self-contained HTML file suitable for
submission to an authority having jurisdiction: verdict-first summary, both
compliance paths, an AHJ-style checklist derived from the audit log, and
per-domain proposed-vs-reference sections with inline-SVG charts and system
schematics. No external resources; the only script is the inline loop-chooser.
"""

from __future__ import annotations

from btap.necb.report import (
    charts,
    checklist,
    html,
    model_query,
    sections,
    svg,
)
from btap.necb.report import html as Html

__all__ = ["charts", "checklist", "html", "Html", "model_query", "sections",
           "svg", "render", "write_html", "loop_select_script"]


def write_html(result, path, options=None):
    """:param result: ComplianceResult (or anything exposing .report/.audit)
    :param path: output .html path
    :param options: project metadata dict — 'project_name', 'address',
        'permit_number', 'prepared_by', 'professional_of_record', 'date'
    :return: the path written"""
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(render(result, options))
    return path


def render(result, options=None):
    """:return: the full HTML document (str)"""
    options = options or {}
    report = result.report
    audit_entries = result.audit.entries if result.audit is not None else []
    proposed_model = getattr(result, "proposed_model", None)
    reference_model = getattr(result, "reference_model", None)
    proposed_data = model_query.extract(proposed_model) if proposed_model else None
    reference_data = model_query.extract(reference_model) if reference_model else None

    # HVAC diagrams are drawn by btap.modeling's loop-diagram engine, driven
    # DIRECTLY off the SDK models here. This assembler and model_query are the
    # ONLY renderer files that touch the SDK — everything else under report/
    # consumes plain dicts. Each diagram is a plain dict of inline-SVG strings;
    # the engine never raises. The icon <defs> they reference are embedded
    # ONCE below. Import lazily so the SDK-free renderer stays importable.
    import btap.modeling as modeling
    from btap.modeling.geometry import plan
    from btap.modeling.hvac.catalog_report import DIAGRAM_CSS

    proposed_hvac = (modeling.model_hvac_diagrams(proposed_model)
                     if proposed_model else None)
    reference_hvac = (modeling.model_hvac_diagrams(reference_model)
                      if reference_model else None)

    # Floor plans come from btap.modeling's plan engine, PROPOSED model only —
    # the reference's spaces/zones are identical by construction (the
    # reference is a clone; no transform renames or rezones). Same contract as
    # the HVAC diagrams: a plain dict bundle, never raises.
    floor_plans = plan.diagrams(proposed_model) if proposed_model else None

    ctx = {
        "report": report,
        "audit_entries": audit_entries,
        "checklist_rows": checklist.rows(audit_entries),
        "proposed": proposed_data,
        "reference": reference_data,
        "proposed_hvac": proposed_hvac,
        "reference_hvac": reference_hvac,
        "floor_plans": floor_plans,
        "options": options,
    }
    body = sections.render_all(ctx)
    project_name = options.get("project_name")
    title_suffix = f" — {Html.esc(project_name)}" if project_name else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NECB {Html.esc(report.get('vintage'))} Compliance Report{title_suffix}</title>
<style>{Html.CSS}{DIAGRAM_CSS}</style>
</head>
<body>
{modeling.hvac_icon_defs()}
{body}
{loop_select_script()}
</body>
</html>
"""


def loop_select_script():
    """ONE inline, self-contained (no external refs) script that wires every
    per-building HVAC loop dropdown: on change it shows the chosen loop's
    panel and hides the rest within the same chooser. Native <select> + a few
    lines of vanilla JS — no libraries, no network requests."""
    return """<script>
document.querySelectorAll('.loop-select').forEach(function(sel){
  function show(){ var v=sel.value, view=sel.closest('.hvac-select').querySelector('.loop-view');
    view.querySelectorAll('.loop-panel').forEach(function(p){ p.hidden = (p.id !== v); }); }
  sel.addEventListener('change', show); show();
});
</script>
"""
