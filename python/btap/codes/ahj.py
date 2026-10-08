"""The AHJ register's RUNTIME projection, and the resolver over it.

`docs/NECB_AHJ_QUESTIONS.md` is canonical and authored;
`btap/codes/data/ahj.json` is GENERATED from it by
`python/scripts/generate_ahj_registry.py` and must not be edited. Documentation
is not a wheel dependency, so the determination reads this projection — and
only this one, because a second `{id: status}` map anywhere else is the drift
this design exists to remove (Sol's `127`).

Three axes cite three different things on an audit entry:

* ``article`` — what the governing Code requires;
* ``ruling`` — which D-XX project adjudication explains the implementation;
* ``ahj``  — which AHJ-NN register disposition applies to THIS runtime choice.

`ahj` means "this disposition applies here", NOT "approval is required". All
four statuses may be cited, for traceability; only `referral` and
`alternative-solution` make a run conditional. A `tool-gap` stays a defect and
a `ruled` question stays settled even though both are traceable on the same
axis.
"""

from __future__ import annotations

import json
import pathlib
import re

DATA_DIR = pathlib.Path(__file__).resolve().parent / "data"

#: Consumers scan for this, de-duplicate, and sort NUMERICALLY. One entry may
#: cite several ids as a space-separated string, mirroring D-44's established
#: multi-citation shape; a list is not the carrier.
ID_PATTERN = re.compile(r"\bAHJ-\d+\b")

_registry: dict | None = None


class UnknownAHJ(ValueError):
    """A cited id that the generated register does not carry.

    Raised rather than skipped: a citation that resolves to nothing is a
    product-data error, and silently dropping it would turn a missing
    disclosure into a clean non-conditional success — the exact failure mode
    AHJ-5's predicate defect was.
    """


def registry() -> dict:
    global _registry
    if _registry is None:
        with open(DATA_DIR / "ahj.json", encoding="utf-8") as handle:
            _registry = json.load(handle)
    return _registry


def by_id() -> dict:
    return {entry["id"]: entry for entry in registry()["entries"]}


def approval_required_statuses() -> tuple:
    """`('referral', 'alternative-solution')`, from the generated projection.

    Read rather than hardcoded, and no `sets_conditional` boolean is
    serialized, so nothing can contradict an entry's status.
    """
    return tuple(registry()["approval_required"])


def ids_in(value) -> list:
    """Every AHJ id in a citation string, de-duplicated, numeric order.

    A set comprehension over the raw field is too weak: one entry can cite
    more than one id, a malformed id must not vanish silently, and the order
    must be deterministic for stable report output (Sol, `127`).
    """
    if not value:
        return []
    found = ID_PATTERN.findall(str(value))
    return sorted(set(found), key=lambda item: int(item.split("-")[1]))


def resolve(citation, *, code: str) -> list:
    """Registry records for one entry's `ahj` citation, for a run of `code`.

    Rejects, rather than drops:

    * an id the register does not carry;
    * an id whose status is not one of the four;
    * an id whose `editions` does not include this run's code id — citing a
      question that does not govern the edition being checked is a product
      error, not a condition.
    """
    out = []
    table = by_id()
    statuses = set(registry()["statuses"])
    for ident in ids_in(citation):
        entry = table.get(ident)
        if entry is None:
            raise UnknownAHJ(
                "{} is cited at runtime but is not in the generated AHJ "
                "register; registered are {}".format(
                    ident, sorted(table)))
        if entry["status"] not in statuses:
            raise UnknownAHJ(
                "{} has status {!r}, which is not one of {}".format(
                    ident, entry["status"], sorted(statuses)))
        if code not in entry["editions"]:
            raise UnknownAHJ(
                "{} is cited on a {} run but the register says it governs "
                "{}".format(ident, code, entry["editions"]))
        out.append(entry)
    return out


def malformed_ids_in(value) -> list:
    """Id-like text that is NOT a well-formed citation, e.g. `AHJ-` or `ahj-3`.

    Exists so a typo surfaces as an error instead of matching nothing and
    disappearing.
    """
    if not value:
        return []
    suspicious = re.findall(r"\bAHJ[-_]?\w*", str(value), re.IGNORECASE)
    return sorted({item for item in suspicious
                   if not ID_PATTERN.fullmatch(item)})
