"""Article-coverage emission (port of btap-audit's coverage.rb): the ONE
implementation of the completeness accounting every family module performs at
the end of its happy path.

Each domain owns an `article_coverage` manifest (implemented / partial /
not_implemented / satisfied_by_clone / host_scope) and resolves it its own
way; what every domain then does with it is identical and lives here: every
declared article lands in the audit with its status and how many decisions
cited it this run, so a missed requirement is visible in every log rather
than discovered by review.

partial/not_implemented WARN — except entries flagged `gap_owner: "modeller"`,
whose remaining gaps are wholly the modeller's responsibility: those emit as
info scope notes instead (project decision D-09).
"""

from __future__ import annotations

import re
from collections import Counter

_ARTICLE_RE = re.compile(r"\d+\.\d+(?:\.\d+)*\.")
# Strip ' (slice label)' / '(N)' suffixes, but KEEP the trailing dot: the scan
# above only ever yields keys ending in '.', so the dot is what stops
# '8.4.4.1.' from prefix-matching '8.4.4.14.' and claiming its citations.
# (report/checklist.rb#covered? guards the same collision the same way.)
_SLICE_SUFFIX_RE = re.compile(r"\s*\(.*\Z")

_INFO_STATUSES = ("implemented", "satisfied_by_clone", "host_scope")


def emit_coverage(coverage, audit):
    """`coverage` is the resolved article_coverage block — a dict with an
    'articles' list of {article, title, status, how, gaps, gap_owner, code}
    records. None is a deliberate no-op (a ruleset with no manifest emits
    nothing). Entries append to `audit`; their `article:` tags are what the
    citation count reads."""
    if coverage is None:
        return

    cited = Counter()
    for e in audit.entries:
        cited.update(_ARTICLE_RE.findall(str(e.get("article") or "")))
    for art in coverage["articles"]:
        prefix = _SLICE_SUFFIX_RE.sub("", str(art["article"]))
        applied = sum(n for a, n in cited.items() if a.startswith(prefix))
        inputs = {"status": art["status"], "decisions_citing": applied}
        if art.get("gap_owner") is not None:
            inputs["gap_owner"] = art["gap_owner"]
        # "Where is this dealt with" — path#method refs, carried into the
        # audit so the AHJ trail answers the question without the repo.
        if art.get("code") is not None:
            inputs["code"] = art["code"]
        status_text = art["status"].replace("_", " ")
        how = art.get("how")
        gaps = art.get("gaps")
        if art["status"] in _INFO_STATUSES:
            audit.info("coverage",
                       f"{art['title']} — {status_text}{': ' + how if how else ''}",
                       inputs=inputs, article=art["article"])
        elif art.get("gap_owner") == "modeller":  # scope note, not a warning (D-09)
            action = f"{art['title']} — {status_text}, modeller scope"
            if how:
                action += f". Applied: {how}"
            if gaps:
                action += f". Modeller's responsibility: {gaps}"
            audit.info("coverage", action, inputs=inputs, article=art["article"])
        else:  # partial / not_implemented
            audit.warn("coverage",
                       f"{art['title']} — {status_text}"
                       f"{'. Applied: ' + how if how else ''}"
                       f"{'. Gaps: ' + gaps if gaps else ''}",
                       inputs=inputs, article=art["article"])
