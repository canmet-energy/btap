#!/usr/bin/env python3
"""Generate the packaged AHJ registry projection from the AUTHORED register.

`docs/NECB_AHJ_QUESTIONS.md` stays CANONICAL. This writes
`python/btap/codes/data/ahj.json`, the runtime projection the determination
resolver reads, exactly as `generate_decisions.py` writes `decisions.json`
from `docs/decisions/D-NN.md`.

Why a projection at all (Sol's `127`): the collector cannot read the register
at runtime, because repository documentation is not a wheel dependency, and it
must not hard-code a second `{id: status}` map in `path.py` — that is the
second source of truth this design exists to remove.

**`sets_conditional` is NOT serialized.** It is derived from `status`, so a
boolean cannot contradict the status it came from. Only `referral` and
`alternative-solution` require approval; `ruled` and `tool-gap` are cited for
traceability and change no verdict.

STDLIB ONLY, like `generate_decisions.py`: the decisions gate installs no
dependencies, and this must be runnable in the same place.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
REGISTER = REPO_ROOT / "docs" / "NECB_AHJ_QUESTIONS.md"
OUTPUT = (REPO_ROOT / "python" / "btap" / "codes" / "data" / "ahj.json")

#: The four statuses, and the two that require approval. The register's own
#: status table is the contract; this mirrors it and nothing else may.
STATUSES = ("referral", "alternative-solution", "ruled", "tool-gap")
APPROVAL_REQUIRED = ("referral", "alternative-solution")

ID_RE = re.compile(r"^AHJ-\d+$")
ROW_RE = re.compile(
    r"^\|\s*(AHJ-\d+)\s*\|([^|]*)\|\s*([a-z-]+)\s*\|([^|]*)\|([^|]*)\|\s*$",
    re.M)
HEADING_RE = re.compile(r"^## (AHJ-\d+)\s+—\s+(.+?)\s*$", re.M)
BODY_STATUS_RE = re.compile(r"\*\*Status[:*\s]*`?([a-z-]+)`?")


def parse_register(text: str) -> list:
    """`[{id, title, status, editions}]`, in numeric id order.

    The title comes from the entry HEADING, not the table's article column:
    the heading is the authored prose a reader sees, and the report appendix
    shows it.
    """
    rows = {}
    for ident, _article, status, editions, _sets in ROW_RE.findall(text):
        rows[ident] = (status.strip(), editions.strip())
    headings = dict(HEADING_RE.findall(text))
    bodies = {}
    parts = re.split(r"^## (AHJ-\d+)", text, flags=re.M)
    for index in range(1, len(parts), 2):
        bodies[parts[index]] = parts[index + 1]

    if not rows:
        raise ValueError(
            "no status rows parsed from {} — the table's shape changed, and a "
            "silently empty registry would make every citation unresolvable"
            .format(REGISTER))
    missing_heading = sorted(set(rows) - set(headings))
    if missing_heading:
        raise ValueError(
            "{}: {} appear in the status table with no entry heading".format(
                REGISTER, missing_heading))
    extra_heading = sorted(set(headings) - set(rows))
    if extra_heading:
        raise ValueError(
            "{}: {} have an entry but no status row".format(
                REGISTER, extra_heading))

    out = []
    for ident in sorted(rows, key=lambda value: int(value.split("-")[1])):
        status, editions = rows[ident]
        if not ID_RE.match(ident):
            raise ValueError("{}: malformed id {!r}".format(REGISTER, ident))
        if status not in STATUSES:
            raise ValueError(
                "{}: {} has status {!r}, which is not one of {}".format(
                    REGISTER, ident, status, list(STATUSES)))
        body_status = BODY_STATUS_RE.search(bodies.get(ident) or "")
        if body_status is None or body_status.group(1) != status:
            raise ValueError(
                "{}: {}'s table row says {!r} and its own body says {!r} — a "
                "status carried in only one place let one entry hold a "
                "referral and a tool gap at once".format(
                    REGISTER, ident, status,
                    body_status.group(1) if body_status else None))
        codes = [part.strip() for part in editions.split(",") if part.strip()]
        if not codes:
            raise ValueError(
                "{}: {} lists no editions".format(REGISTER, ident))
        out.append({
            "id": ident,
            "title": headings[ident].strip(),
            "status": status,
            "editions": codes,
        })
    return out


def render(records: list) -> str:
    return json.dumps(
        {"generated_from": "docs/NECB_AHJ_QUESTIONS.md",
         "statuses": list(STATUSES),
         "approval_required": list(APPROVAL_REQUIRED),
         "entries": records},
        indent=2, ensure_ascii=False) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="fail if the generated output is stale")
    args = parser.parse_args(argv)

    records = parse_register(REGISTER.read_text(encoding="utf-8"))
    rendered = render(records)
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else ""
        if current != rendered:
            print("ahj: {} is stale — run "
                  "python3 python/scripts/generate_ahj_registry.py"
                  .format(OUTPUT.relative_to(REPO_ROOT)), file=sys.stderr)
            return 1
        print("ahj: the generated registry is up to date")
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    print("ahj: wrote {} ({} entries)".format(
        OUTPUT.relative_to(REPO_ROOT), len(records)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
