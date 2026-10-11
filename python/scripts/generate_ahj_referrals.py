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

#: Headings the register uses for each part of an entry. "now" and
#: "meanwhile" are both accepted for interim behaviour: once a question is
#: ruled, "meanwhile" is the wrong tense, and the register test accepts either.
FIELDS = {
    "article": ("Article.",),
    "question": ("The ambiguity.", "The question.", "The requirement."),
    "established": ("Established by.",),
    "meanwhile": ("What the tool does meanwhile.", "What the tool does now."),
}


def _statuses() -> dict:
    data = json.loads(PROJECTION.read_text(encoding="utf-8"))
    rows = data if isinstance(data, list) else (data.get("entries") or [])
    rows = list(rows.values()) if isinstance(rows, dict) else rows
    return {r["id"]: r for r in rows}


def _conditional_column() -> dict:
    """The register's own status table says whether an entry makes a run
    conditional. That column is the contract, so it is read rather than
    inferred from the status."""
    out = {}
    for line in REGISTER.read_text(encoding="utf-8").split("\n"):
        m = re.match(r"\|\s*(AHJ-\d+)\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|",
                     line)
        if m:
            out[m.group(1)] = m.group(5).strip()
    return out


def _sections() -> dict:
    text = REGISTER.read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"^## (AHJ-\d+) — (.*?)$(.*?)(?=^## AHJ-|\Z)",
                         text, re.S | re.M):
        out[m.group(1)] = {"title": m.group(2).strip(), "body": m.group(3)}
    return out


def _field(body: str, headings: tuple) -> str | None:
    for h in headings:
        m = re.search(rf"\*\*{re.escape(h)}\*\*\s*(.*?)(?=\n\n|\Z)", body, re.S)
        if m:
            return " ".join(m.group(1).split())
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

    by_status = {s: [i for i in wanted if statuses[i]["status"] == s]
                 for s in NEEDS_AUTHORITY}
    out = [
        "# NECB questions this tool does not decide — for an authority",
        "",
        "**GENERATED** by `python/scripts/generate_ahj_referrals.py` from",
        "`docs/NECB_AHJ_QUESTIONS.md`. Do not edit: edit the register and",
        "regenerate. It carries no figures or wording of its own, so it cannot",
        "drift from the register it summarises.",
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
            out += [f"- **Editions:** {eds}",
                    f"- **Article:** {_field(sec['body'], FIELDS['article']) or '(absent)'}",
                    f"- **Makes a run conditional:** {conditional.get(i, '(not in the status table)')}",
                    ""]
            for label, key in (("The question", "question"),
                               ("Established by", "established"),
                               ("What the tool does meanwhile", "meanwhile")):
                value = _field(sec["body"], FIELDS[key])
                if value:
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
