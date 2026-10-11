#!/usr/bin/env python3
"""Generate docs/NECB_AHJ_REFERRALS.md — the questions needing an authority.

`docs/NECB_AHJ_QUESTIONS.md` is the AUTHORED register of every question this
tool does not decide, in all four statuses. Most of them need no authority:
`ruled` is settled and `tool-gap` is a defect to close. This document extracts
only the two statuses that DO need someone outside the project — `referral`,
where the Code's text does not decide the question, and
`alternative-solution`, where it does decide and we do not meet it — so the
set can be taken to an authority once rather than rediscovered one at a time.

It is GENERATED. Nothing here is authored, because a second hand-maintained
copy of the register is a copy that drifts: D-102's evidence was corrected
eight times in two days for exactly that reason, and the fix was to delete the
repetition rather than guard it.

    python3 python/scripts/generate_ahj_referrals.py
    python3 python/scripts/generate_ahj_referrals.py --check
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
REGISTER = ROOT / "docs" / "NECB_AHJ_QUESTIONS.md"
PROJECTION = ROOT / "python" / "btap" / "codes" / "data" / "ahj.json"
OUTPUT = ROOT / "docs" / "NECB_AHJ_REFERRALS.md"

#: Only these two statuses need an authority. `ruled` and `tool-gap` do not,
#: and including them would be the laundering the register's statuses exist to
#: prevent — a defect presented as a question for someone else.
NEEDS_AUTHORITY = ("referral", "alternative-solution")

#: Headings the register uses for each part of an entry, matched as PREFIXES.
#:
#: Exact matching silently lost both `alternative-solution` entries: AHJ-1 and
#: AHJ-7 head their requirement "The requirement, and why we do not meet it.",
#: which "The requirement." does not equal, so the package shipped the two
#: entries where the Code DOES decide and we do not meet it with no statement
#: of the requirement at all — to a reader whose whole job is to judge that
#: (Fable, `212`). "now" and "meanwhile" are both accepted for interim
#: behaviour because once a question is ruled, "meanwhile" is the wrong tense.
FIELDS = {
    "article": ("Article",),
    "question": ("The ambiguity", "The question", "The requirement"),
    "established": ("Established by",),
    "meanwhile": ("What the tool does meanwhile", "What the tool does now"),
}

#: Fields an entry MUST have for the package to be worth handing over. A
#: missing one is a register defect, and rendering the document without it
#: would hand an authority a question with no requirement, no interim
#: behaviour, or no article — so generation FAILS instead.
REQUIRED = ("article", "question", "established", "meanwhile")


def _statuses() -> dict:
    """Status, title and editions from the AUTHORED register, with the
    generated projection required to agree.

    This read `ahj.json` — itself generated from the register — and that made
    one generated projection the oracle for another. Sol (`213`) changed
    AHJ-21's status in both canonical authored locations, left the JSON and
    the package untouched, and `--check` reported success: the gate certified
    a current package while the canonical status had moved underneath it.

    So the register is parsed directly, with `generate_ahj_registry`'s own
    parser rather than a second copy of it — that parser already cross-checks
    each entry's table row against the status in its own body. The projection
    is then checked AGAINST that parse, so a stale `ahj.json` fails here too
    instead of silently steering the selection.
    """
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import generate_ahj_registry

    try:
        authored = {r["id"]: r for r in generate_ahj_registry.parse_register(
            REGISTER.read_text(encoding="utf-8"))}
    except ValueError as error:
        # A register edit is the EXPECTED trigger for this path, so it reports
        # rather than tracebacks. The parser's own message names the entry and
        # the contradiction.
        raise SystemExit(
            f"generate_ahj_referrals: the authored register does not parse, "
            f"so the questions needing an authority cannot be "
            f"identified:\n  {error}") from None

    data = json.loads(PROJECTION.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else (data.get("entries") or [])
    rows = list(rows.values()) if isinstance(rows, dict) else rows
    projected = {r["id"]: r for r in rows}

    drift = []
    for ident, record in sorted(authored.items(),
                                key=lambda kv: int(kv[0].split("-")[1])):
        mirror = projected.get(ident)
        if mirror is None:
            drift.append(f"{ident}: in the register, absent from ahj.json")
            continue
        for field in ("status", "title", "editions"):
            if mirror.get(field) != record[field]:
                drift.append(
                    f"{ident}.{field}: register {record[field]!r} vs "
                    f"ahj.json {mirror.get(field)!r}")
    for ident in sorted(set(projected) - set(authored)):
        drift.append(f"{ident}: in ahj.json, absent from the register")
    if drift:
        raise SystemExit(
            "generate_ahj_referrals: the generated registry has drifted from "
            "the authored register, so neither can be trusted to say which "
            "questions need an authority. Run generate_ahj_registry.py.\n  "
            + "\n  ".join(drift))
    return authored


def _conditional_column() -> dict:
    """The register's own status table says whether an entry makes a run
    conditional. That column is the contract, so it is read rather than
    inferred from the status.

    Read by POSITION, which means a mis-count renders a neighbouring column
    instead — reading the status column produced "Makes a run conditional:
    referral" on every entry with every test still green (Fable, `212`). So
    the value's SHAPE is checked: it must begin with a yes/no judgement,
    because that is what the column means. "not yet" is one of them, from
    AHJ-7, whose defect is in published data this tool corrects rather than in
    a run.
    """
    starts = ("yes", "no", "not yet")
    out = {}
    for line in REGISTER.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"\|\s*(AHJ-\d+)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|",
                     line)
        if m:
            value = m.group(5).strip()
            if not value.lower().startswith(starts):
                raise SystemExit(
                    f"generate_ahj_referrals: {m.group(1)}'s conditional "
                    f"column reads {value!r}, which does not begin with a "
                    f"yes/no judgement ({', '.join(starts)}). Either the "
                    "register's status table changed shape or this generator "
                    "is reading the wrong column — and a wrong column would "
                    "tell an authority the opposite of the truth.")
            out[m.group(1)] = value
    return out


def _sections() -> dict:
    text = REGISTER.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"^## (AHJ-\d+) — (.*?)$(.*?)(?=^## AHJ-|\Z)",
                         text, re.S | re.M):
        out[m.group(1)] = {"title": m.group(2).strip(), "body": m.group(3)}
    return out


#: The register's RECOGNISED field headings — a closed set, which is what
#: makes a field's end decidable.
#:
#: The previous rule was typographic: "a bold run that opens and closes on one
#: line". That is not the register's grammar, and it was wrong in BOTH
#: directions (Fable, `217`). It cut AHJ-7's requirement at its own
#: `**Why an authority must weigh in.**` sub-paragraph — the paragraph that
#: states the choice, and the one Sol named — because that line happens to
#: fit. And it ran AHJ-16's interim behaviour on through 50 lines of
#: review-loop history, because `**Guard 7 is MET since …**` happens to WRAP.
#: Whether a field ended depended on where the text wrapped.
#:
#: A bold run that is not in this set is EMPHASIS INSIDE a field, not a
#: boundary. Adding a new authored field heading means adding it here.
FIELD_HEADINGS = (
    "Article",
    "Status",
    "The ambiguity",
    "The question",
    "The requirement",
    "The gap",
    "What is missing",
    "Why it matters",
    "Established by",
    "What the tool does meanwhile",
    "What the tool does now",
    "Where a reader meets it",
)

#: A heading ends at a period or at its closing `**`. Without that,
#: `FIELD_HEADINGS`'s entries were bare PREFIXES: `**Articles of this
#: Section…**` would have ended a field as if it were `**Article.**`, and
#: `**Status quo…**` as if it were the status line (Fable, `219`).
_HEADING_TAIL = r"(?:\.|\*\*)"

_FIELD_END_RE = re.compile(
    r"(?m)^(?:" + "|".join(
        r"\*\*" + re.escape(name) + _HEADING_TAIL
        for name in FIELD_HEADINGS) + r"|#{2,6} )")


def _field(body: str, headings: tuple, *, collapse: bool = False) -> str | None:
    """One field's WHOLE text, from its heading to the next one.

    Matched as a PREFIX, because the register's headings carry trailing
    clauses — "The requirement, and why we do not meet it." — and an exact
    match drops the field, which a truthiness check downstream then drops
    silently.

    Read to the next HEADING rather than to the first blank line. Stopping at
    the blank line published 246 of AHJ-7's 1150 characters and ended on the
    colon introducing the coefficient table it dropped — so the authority was
    asked to accept a non-conforming substitution and shown neither the three
    wrong published rows nor the paragraph headed "Why an authority must weigh
    in" (Sol, `216`; Fable, `214` measured AHJ-1 losing 842 and AHJ-10 357).
    A length floor cannot see that, because what survived was a plausible
    sentence.

    `collapse` folds the result onto one line, for the fields rendered as
    bullets. The paragraph fields keep their blank lines, lists and tables.
    """
    for h in headings:
        m = re.search(rf"\*\*{re.escape(h)}[^*]*\*\*[ \t]*", body)
        if not m:
            continue
        rest = body[m.end():]
        stop = _FIELD_END_RE.search(rest)
        text = (rest[:stop.start()] if stop else rest).strip()
        return " ".join(text.split()) if collapse else text
    return None


def render() -> str:
    statuses, conditional, sections = (_statuses(), _conditional_column(),
                                       _sections())
    wanted = sorted(
        (i for i, r in statuses.items() if r.get("status") in NEEDS_AUTHORITY),
        key=lambda i: int(i.split("-")[1]))
    missing = [i for i in wanted if i not in sections]
    if missing:
        raise SystemExit(f"generate_ahj_referrals: {missing} have a status "
                         "needing an authority but no register section")
    holes = [f"{i}:{key}" for i in wanted for key in REQUIRED
             if not _field(sections[i]["body"], FIELDS[key])]
    # The conditional judgement is not a register heading, so it is checked
    # here against the same requirement: a blank cell renders a question with
    # nothing said about what hangs on it. Sol (`213`) blanked AHJ-2's cell,
    # regenerated, and all three tests passed on the empty value.
    holes += [f"{i}:conditional" for i in wanted
              if not (conditional.get(i) or "").strip()]
    if holes:
        raise SystemExit(
            "generate_ahj_referrals: these entries are missing a REQUIRED "
            f"field and the package will not be written: {', '.join(holes)}. "
            "A placeholder is not an authority package: an authority cannot "
            "act on a question with no requirement, no article, no "
            "attribution, no stated interim behaviour, or nothing said about "
            "whether a run is conditional on it.")

    by_status = {s: [i for i in wanted if statuses[i]["status"] == s]
                 for s in NEEDS_AUTHORITY}
    out = [
        "# NECB questions this tool does not decide — for an authority",
        "",
        "**GENERATED** by `python/scripts/generate_ahj_referrals.py` from",
        "`docs/NECB_AHJ_QUESTIONS.md`. Do not edit: edit the register and",
        "regenerate. Every question, article, attribution and interim",
        "behaviour below is the register's own text, so none of it can drift;",
        "the framing sentences are this generator's.",
        "",
        "The register holds every question in four statuses. Two of them need",
        "no authority — `ruled` is settled, and `tool-gap` is a defect for us",
        "to close, not a question for anyone else. This document is the other",
        f"two: **{len(by_status['referral'])} `referral`** entries, where the",
        "Code's text does not decide the question, and",
        f"**{len(by_status['alternative-solution'])} `alternative-solution`**",
        "entries, where it does decide and this tool does not meet it — which",
        "an authority can accept only as an explicitly identified",
        "non-conforming substitution.",
        "",
        "Every entry below states what the tool does in the meantime, so a",
        "reader can see what an answer would change rather than only what is",
        "being asked.",
        "",
        "---",
        "",
    ]
    for status in NEEDS_AUTHORITY:
        if not by_status[status]:
            continue
        out += [f"## `{status}`", ""]
        for i in by_status[status]:
            sec, row = sections[i], statuses[i]
            out += [f"### {i} — {sec['title']}", ""]
            eds = ", ".join(row.get("editions") or []) or "(none stated)"
            # No placeholder fallbacks. Every field below is validated
            # non-empty before anything is rendered, so `(absent)` here could
            # only ever hide a hole from the reader it matters to — and it
            # already did, for AHJ-1 and AHJ-7 (Sol, `213`).
            out += [f"- **Editions:** {eds}",
                    f"- **Article:** "
                    f"{_field(sec['body'], FIELDS['article'], collapse=True)}",
                    f"- **Makes a run conditional:** {conditional[i]}",
                    ""]
            for label, key in (("The question", "question"),
                               ("Established by", "established"),
                               ("What the tool does meanwhile", "meanwhile")):
                value = _field(sec["body"], FIELDS[key])
                out += [f"**{label}.** {value}", ""]
        out += ["---", ""]
    out += [
        "## How a run says this out loud",
        "",
        "Only `referral` and `alternative-solution` make a result",
        "conditional. Where one applies to a final choice, the report carries",
        "`compliance_determination: conditional` with a reason block naming",
        "the approval required, one record per unique final choice, and the",
        "exit code is deliberately unchanged. The CLI prints it inside the",
        "verdict string and the HTML report badges it beside the pass/fail",
        "badge, because the report is the artifact an authority reads.",
        "",
    ]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="fail if the committed document is not current")
    args = ap.parse_args(argv)
    text = render()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else ""
        if current != text:
            print(f"ahj-referrals: STALE {OUTPUT.name} — run "
                  "python3 python/scripts/generate_ahj_referrals.py",
                  file=sys.stderr)
            return 1
        print(f"ahj-referrals: {OUTPUT.name} is up to date")
        return 0
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"ahj-referrals: wrote {OUTPUT.name}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
