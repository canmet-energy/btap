"""Derives the AHJ-style checklist from the audit log (port of
report/checklist.rb). Rows come from 'compliance' decisions (the
article-cited verdicts), and every warning is elevated so the checklist can
never look cleaner than the run actually was. Coverage entries are
reconciled: a host_scope delegation with no implementing coverage entry in
the same audit surfaces as a warning row; everything else stays in the
coverage appendix.

Port note (D-79): the Python AuditLog records str-keyed entries with string
levels ('decision' | 'info' | 'warning'), so the membership tests here read
those spellings — Ruby's ``%i[warn warning]`` both landed as :warning in the
persisted audit anyway."""

from __future__ import annotations

import re
from dataclasses import dataclass

from btap._compat import ruby_round, ruby_str

#: The audit convention SHOUTS violations ('EXCEEDS', 'does NOT meet',
#: 'BELOW the') while pass texts stay lowercase ('does not exceed',
#: 'within 100 h') — so the fail check is deliberately case-SENSITIVE.
FAIL_WORDS = re.compile(r"\b(EXCEEDS?|NOT|BELOW|FAILS?)\b|non-compliant")
PASS_WORDS = re.compile(
    r"\b(meets|complies|compliant|does not exceed|within|satisfied)\b",
    re.IGNORECASE)

#: Coverage statuses that count as an article being actually handled in this
#: run (so a sibling host_scope delegation is reconciled, not warned).
COVERING_STATUSES = ("implemented", "partial", "satisfied_by_clone")


@dataclass
class Row:
    glyph: str
    article: str
    statement: str
    measured: str | None
    audit_index: int
    building: str | None = None


def rows(audit_entries):
    """:param audit_entries: AuditLog.entries (str-keyed dicts)
    :return: article-sorted checklist Rows"""
    covered = covered_articles(audit_entries)
    out = []
    for index, entry in enumerate(audit_entries):
        step = str(entry.get("step") or "")
        inputs = entry.get("inputs")
        status = str(inputs.get("status") or "") if isinstance(inputs, dict) else ""
        level = entry.get("level")
        if level == "warning":
            out.append(Row(glyph="warning", article=_article(entry),
                           building=entry.get("building"),
                           statement=statement_for(entry),
                           measured=measured_for(entry), audit_index=index))
        elif step == "compliance" and level == "decision":
            out.append(Row(glyph=verdict_glyph(str(entry.get("action") or "")),
                           article=_article(entry),
                           building=entry.get("building"),
                           statement=statement_for(entry),
                           measured=measured_for(entry), audit_index=index))
        elif (step == "coverage" and level == "info" and status == "host_scope"
              and not covered_by(_article(entry), covered)):
            out.append(Row(glyph="warning", article=_article(entry),
                           building=entry.get("building"),
                           statement="Delegated but NOT covered in this run: "
                                     f"{entry.get('action')}",
                           measured=None, audit_index=index))
    return sorted(out, key=lambda r: (article_sort_key(r.article), r.audit_index))


def covered_articles(audit_entries):
    """Articles an implementing coverage entry claims in THIS audit. Shared
    by the checklist reconciliation and the coverage appendix so both
    agree."""
    covered = set()
    for entry in audit_entries:
        if str(entry.get("step") or "") != "coverage":
            continue

        inputs = entry.get("inputs")
        if not (isinstance(inputs, dict)
                and str(inputs.get("status") or "") in COVERING_STATUSES):
            continue

        article = _article(entry)
        if article:
            covered.add(article)
    return covered


def covered_by(article, covered_set):
    """Bidirectional prefix match (subsumes exact equality): '8.4.4.20.'
    covers '8.4.4.20.(1)' and vice versa. NECB article strings end in '.',
    so the trailing dot guards against '8.4.4.2.' matching '8.4.4.20.'."""
    a = str(article or "")
    if not a:
        return False

    return any(a.startswith(b) or b.startswith(a) for b in covered_set)


def verdict_glyph(action):
    if FAIL_WORDS.search(action):
        return "fail"
    if PASS_WORDS.search(action):
        return "pass"

    return "na"


def statement_for(entry):
    text = str(entry.get("action") or "")
    target = entry.get("target")
    if target is not None and str(target) not in text:
        return f"{target}: {text}"
    return text


def measured_for(entry):
    """Compact "measured" cell from the decision's inputs dict."""
    inputs = entry.get("inputs")
    if not (isinstance(inputs, dict) and inputs):
        return None

    parts = []
    for k, v in list(inputs.items())[:4]:
        value = ruby_round(v, 2) if isinstance(v, float) else v
        parts.append(f"{k}: {ruby_str(value)}")
    return ", ".join(parts)


def article_sort_key(article):
    """Sort "8.4.1.2.(2)" numerically per level; unknown articles sink
    last."""
    numbers = [int(n) for n in re.findall(r"\d+", str(article or ""))]
    return numbers if numbers else [99]


def _article(entry):
    return str(entry.get("article") or "")
