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
        # ONE entry counts ONCE per article, hence the set. `_ARTICLE_RE` strips
        # a leading `A-`, so an Appendix Note id collapses onto the article it
        # refers to: an entry citing `8.4.5.4.(1) (Note A-8.4.5.4.(1): ...)`
        # yielded that article TWICE and `decisions_citing` reported 2 for one
        # decision. The count reaches the AHJ report, so the inflation is a
        # disclosure defect (Fable + Sol, PR #65).
        #
        # Deduplicating PER ENTRY rather than tightening the pattern is
        # deliberate, for two reasons.
        #
        # A lookbehind that excluded `A-` would also stop a Note from crediting
        # its own article at all — an article whose only evidence is its Note
        # would drop to zero, under-stating coverage instead of over-stating it.
        #
        # And it would not have fixed the defect everywhere. The same
        # double-count has a second SPELLING: `eui_archetypes.py` cites
        # `"8.4.4.1.(2); Table 8.4.4.1."` — an article beside its own TABLE, not
        # its Note — which an `A-` lookbehind leaves counting twice while
        # appearing to succeed. Per-entry dedup is spelling-agnostic, and that
        # is what makes it the right shape rather than merely the safe one
        # (Fable, PR #74).
        #
        # WHY A NOTE COUNTS AT ALL, since this is the judgement the dedup
        # preserves: the metric counts MENTIONS, not applications — the report's
        # own caption says a citation "is not, by itself, evidence the rule is
        # applied". A line citing `Note A-8.4.5.4.(1)` does mention `8.4.5.4.`,
        # so crediting it is correct under that definition. It would NOT be
        # correct if the count claimed normative coverage, because Appendix A is
        # explanatory rather than normative; the weakness of the metric is
        # exactly what makes counting a Note defensible.
        cited.update(set(_ARTICLE_RE.findall(str(e.get("article") or ""))))
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
