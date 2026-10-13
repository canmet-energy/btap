"""The adjudicated-decision registry (port of btap-necb's decisions.rb): the
runtime projection of the per-decision sources in docs/decisions/.

Runtime code cites decisions through the AuditLog ``ruling`` kwarg
(``ruling='D-14'``, or ``'D-19 D-21'`` for several). This module resolves
those ids to a title and a SELF-CONTAINED summary, so the AHJ report can
explain WHY a ruled code path did what it did without sending the reader
anywhere — the report carries no external references by contract.

The file is ``{'_comment', 'schema': 2, 'decisions': [entry, ...]}``. This
module reads only each entry's ``id``, ``title``, ``kind`` and ``summary``,
and refuses any other schema number rather than guess at a layout. An entry
is either shape:

  legacy:     {'id', 'title', 'kind', 'articles', 'editions', 'summary'}
  structured: {'id', 'title', 'kind', 'editions', 'summary', 'requirements'}
              requirements: [{'id', 'label', 'decided',
                              'sources': [{'code', 'edition', 'role',
                                           'references'}]}]

  kind: 'runtime'         — has at least one ruling-tagged audit call
        'runtime_unwired' — runtime behaviour, no ruling-tagged call
        'data'            — manifest / vendored-data / verification only
        'process'         — how the project works, not what the code does

A structured entry's ``editions`` is derived from its ``governing`` sources
only. Requirements and sources are committee metadata: nothing here renders
them, so they cannot change a compliance report.

This package's data/decisions.json is GENERATED and must not be edited.
The canonical source is one file per decision, docs/decisions/D-NN.md, from
which python/scripts/generate_decisions.py emits both this registry and
docs/necb_decisions.md in numeric id order (D-81, amended 2026-09-29).
tests/necb/test_decisions_registry.py enforces the citation invariants,
test_decisions_registry_sync.py the drift gate on both outputs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

#: Every consumer of a ruling string parses it with this — mirrors the
#: joined-citation convention already used for ``article``.
#: Unbounded digits. `\bD-\d{2}\b` did NOT match `D-100`, so a decision the
#: generator accepted would have had INVISIBLE citations: no audit entry
#: would resolve its ruling and it would never reach the report appendix. I
#: described that trap in the commit that widened the generator and did not
#: actually edit this file (Sol, clearance review of be2118d).
ID_PATTERN = re.compile(r"\bD-\d+\b")

#: The registry layout this module reads. The generator imports it, so the
#: writer and the reader cannot disagree about the number.
SCHEMA = 2

_all: list[dict] | None = None
_by_id: dict[str, dict] | None = None


def all_decisions() -> list[dict]:
    """Every registered decision, numeric decision-id order.

    The order is the generator's (D-81, amended 2026-09-29). This previously
    documented itself as "document order", which was not true of either file:
    document order, registry order and numeric order were three different
    sequences before the migration.
    """
    global _all
    if _all is None:
        with open(DATA_DIR / "decisions.json", encoding="utf-8") as handle:
            _all = _validated(json.load(handle))
    return _all


def _validated(payload) -> list[dict]:
    """The ``decisions`` array of a schema-2 registry, or ValueError.

    Exact, not "at least": a registry written under another schema may move
    the fields this module reads, and resolving rulings from a layout it does
    not know would put wrong text in an AHJ-facing report.
    """
    if not isinstance(payload, dict):
        raise ValueError("decisions.json must be a JSON object")
    schema = payload.get("schema")
    if type(schema) is not int or schema != SCHEMA:
        raise ValueError(
            f"decisions.json has schema {schema!r}; this module reads schema "
            f"{SCHEMA} — regenerate it with python/scripts/generate_decisions.py")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("decisions.json has no 'decisions' array")
    return decisions


def by_id() -> dict[str, dict]:
    """id => entry."""
    global _by_id
    if _by_id is None:
        _by_id = {d["id"]: d for d in all_decisions()}
    return _by_id


def lookup(id):
    """The entry for e.g. 'D-14', or None when the id is not registered."""
    return by_id().get(str(id))


def ids() -> list[str]:
    """Every id registered."""
    return [d["id"] for d in all_decisions()]


def ids_in(string) -> list[str]:
    """Scan a ruling string (or anything str-able, including None) for
    decision ids. Order-preserving and de-duplicated."""
    text = "" if string is None else str(string)
    seen = []
    for match in ID_PATTERN.findall(text):
        if match not in seen:
            seen.append(match)
    return seen


def of_kind(kind) -> list[dict]:
    """'runtime' | 'runtime_unwired' | 'data' | 'process'."""
    return [d for d in all_decisions() if d["kind"] == str(kind)]
