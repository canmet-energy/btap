"""Snapshot self-description gate (``/home/vscode/.claude/plans/
prancy-booping-nova.md``, "The policy" and "4. The gate"): a per-edition
NECB snapshot under ``btap.codes.necb.data/<code id>/`` may name another
edition only as its ORIGIN, never as a forward reference and never inside a
comparison. The plan's three rules, checked over every string KEY and every
string VALUE of every packaged ``.json`` file (JSON keys are always strings;
JSON numbers are excluded by construction — walking ``str`` nodes only):

(a) **no forward reference** — a token naming an edition NEWER than the
    snapshot's own edition is a problem ANYWHERE, provenance included (a
    2020 snapshot cannot know 2025 exists).
(b) **origin only** — a token naming any OTHER edition, or the bare word
    ``vintage``, is a problem everywhere EXCEPT inside the provenance key
    set (manifest ``provenance``, in-file ``provenance``/``_provenance``
    blocks, ``curves[].notes``, ``derivation``, any key ending in ``note``).
    A token naming the snapshot's OWN edition is never a (b) problem — that
    is self-identification, not a reference to "another" edition.
(c) **no comparison in provenance** — inside the provenance key set, a
    token within 80 characters of a comparative word (``identical``,
    ``verified``, ``compared``, ``comparison``, ``renumber``, ``same as``,
    ``differs``, ``changed vs``, ``changes_vs``, ``mirrors``,
    ``cross-check``) is a problem. The plan's origin-phrase allowlist
    (``vendored from``, ``inherited from``, ``From NECB 2011 Table``,
    ``deep merge along``, ``retrieved via``, ``oracle``) is NOT applied as
    an override: a comparative word right next to it is still a problem — a
    sentence can carry both an origin clause and a comparison clause, and
    the comparison half is what this rule forbids. The allowlist is kept
    here only as a record of what a clean origin sentence looks like (one
    with no comparative word in it at all).

Two keys are flagged by NAME, not by token content, because their existence
is the problem regardless of what they say: a key literally named
``verification`` or starting with ``changes_vs_`` sitting inside the
provenance key set (``efficiencies.json``'s ``provenance.verification``,
``lighting_rules.json``/``loads_rules.json``'s
``provenance.changes_vs_2020``) is a comparison block by construction, even
when its prose happens to carry no year token.

Archived MCP payloads under ``provenance/*.result.json`` are the server's
own text (hashed, never read — plan rule 4) and are excluded from the walk
entirely, key and value alike.

Exports :func:`check_self_description`, called from the Stage 3 removability
gate's SDK-free subprocess script
(``tests/necb/test_edition_independence.py``) exactly like that module's own
:func:`check_provenance`, so the self-description contract is proven to hold
with only one edition's snapshot present too.

Expected to FAIL on today's tree with a large inventory (curve identifiers
carrying the ``-NECB2011`` suffix, dead vendored columns naming another
edition, comparative provenance prose, and a handful of necb2020 forward
references to 2025) until the snapshot cleanup in the plan's deliverables
1-3 lands.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

import btap.codes as codes
import btap.codes.necb as necb_pkg

#: `NECB2020`, `NECB 2020`, or a bare `2020` not glued to another digit or a
#: `.` (so table numbers like `8.4.5.2` and dates like `2026-07-22` never
#: match), plus the bare legacy word `vintage`.
TOKEN_RE = re.compile(
    r"NECB ?20(?P<necb_yr>11|15|17|20|25)"
    r"|(?<![\d.])20(?P<bare_yr>11|15|17|20|25)(?![\d.])"
    r"|\b(?P<vintage>vintage)\b",
    re.IGNORECASE,
)

#: Path segments that put a string inside the provenance key set.
PROVENANCE_SEGMENTS = {"provenance", "_provenance", "notes", "derivation", "non_rule_keys_note"}

COMPARATIVE_WORDS = (
    "identical", "verified", "compared", "comparison", "renumber",
    "same as", "differs", "changed vs", "changes_vs", "mirrors", "cross-check",
)

#: What a clean origin sentence looks like (documentation only — see module
#: docstring: NOT used to suppress a comparative-word hit).
COMPARATIVE_ALLOWLIST = (
    "vendored from", "inherited from", "From NECB 2011 Table",
    "deep merge along", "retrieved via", "oracle",
)

#: Key names that are a comparison block BY NAME, wherever they sit inside
#: the provenance key set, independent of whether their text carries a token.
NAMED_COMPARISON_KEYS_UNDER_PROVENANCE = ("verification",)
NAMED_COMPARISON_KEY_PREFIXES_UNDER_PROVENANCE = ("changes_vs_",)

COMPARATIVE_RADIUS = 80
EXCERPT_RADIUS = 60


def _path_str(path: list) -> str:
    """Render a key-path as ``a.b[2].c`` — list indices fold onto the
    preceding segment rather than standing alone."""
    parts: list[str] = []
    for seg in path:
        if isinstance(seg, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{seg}]"
            else:
                parts.append(f"[{seg}]")
        else:
            parts.append(str(seg))
    return ".".join(parts)


def _in_provenance_key_set(path: list) -> bool:
    for seg in path:
        if not isinstance(seg, str):
            continue
        if seg in PROVENANCE_SEGMENTS:
            return True
        if seg.endswith("note"):
            return True
    return False


def _excerpt(text: str, start: int, end: int) -> str:
    lo = max(0, start - EXCERPT_RADIUS)
    hi = min(len(text), end + EXCERPT_RADIUS)
    snippet = text[lo:hi].replace("\n", " ")
    prefix = "…" if lo > 0 else ""
    suffix = "…" if hi < len(text) else ""
    return f"{prefix}{snippet}{suffix}"


def _named_year(match: re.Match) -> int | None:
    for group in ("necb_yr", "bare_yr"):
        value = match.group(group)
        if value:
            return 2000 + int(value)
    return None  # the bare word "vintage" -- names no specific edition


def _has_nearby_comparative_word(text: str, start: int, end: int) -> bool:
    lo = max(0, start - COMPARATIVE_RADIUS)
    hi = min(len(text), end + COMPARATIVE_RADIUS)
    window = text[lo:hi].lower()
    return any(word in window for word in COMPARATIVE_WORDS)


def _check_string(
    text: str, path: list, own_year: int, rel_file: str,
    problems_a: list[str], problems_b: list[str], problems_c: list[str],
) -> None:
    if not text:
        return
    in_provenance = _in_provenance_key_set(path)
    path_str = _path_str(path)
    for match in TOKEN_RE.finditer(text):
        named_year = _named_year(match)
        loc = f"{rel_file}: {path_str}: {_excerpt(text, match.start(), match.end())}"
        # (a) forward reference -- checked everywhere, provenance included.
        if named_year is not None and named_year > own_year:
            problems_a.append(loc)
        if not in_provenance:
            # (b) origin only -- "vintage" or any edition OTHER than this
            # snapshot's own is a problem outside the provenance key set. A
            # token naming this snapshot's OWN edition is self-identification,
            # not a reference to "another" edition, so it is not a problem.
            if named_year is None or named_year != own_year:
                problems_b.append(loc)
        elif _has_nearby_comparative_word(text, match.start(), match.end()):
            # (c) no comparison in provenance.
            problems_c.append(loc)


def _check_named_comparison_key(key: str, path: list, rel_file: str, problems_b: list[str]) -> None:
    """A key literally named ``verification`` or ``changes_vs_*`` sitting
    inside the provenance key set is a comparison block by construction --
    flagged even when its own text carries no token (efficiencies.json's
    ``provenance.verification`` prose describes a table cell-for-cell without
    ever spelling out a year)."""
    if not _in_provenance_key_set(path):
        return
    is_named_comparison = (
        key in NAMED_COMPARISON_KEYS_UNDER_PROVENANCE
        or key.startswith(NAMED_COMPARISON_KEY_PREFIXES_UNDER_PROVENANCE)
    )
    if is_named_comparison:
        problems_b.append(
            f"{rel_file}: {_path_str(path + [key])}: forbidden comparison key {key!r} under provenance"
        )


def _walk(
    node, path: list, own_year: int, rel_file: str,
    problems_a: list[str], problems_b: list[str], problems_c: list[str],
) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            key_path = path + [key]
            _check_string(key, key_path, own_year, rel_file, problems_a, problems_b, problems_c)
            _check_named_comparison_key(key, path, rel_file, problems_b)
            _walk(value, key_path, own_year, rel_file, problems_a, problems_b, problems_c)
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            _walk(item, path + [idx], own_year, rel_file, problems_a, problems_b, problems_c)
    elif isinstance(node, str):
        _check_string(node, path, own_year, rel_file, problems_a, problems_b, problems_c)
    # numbers, bools, None: not strings -- never scanned (spec: "treat
    # numbers, not strings").


def _is_archived_payload(json_path: Path) -> bool:
    """``provenance/*.result.json`` -- archived MCP payloads, exempt."""
    return json_path.parent.name == "provenance" and json_path.name.endswith(".result.json")


def find_problems(data_root) -> dict[str, list[str]]:
    """Every self-description problem across every registered code id's
    snapshot under ``data_root``, split by rule letter. Empty lists
    everywhere = ok.

    Iterates :func:`btap.codes.code_ids` rather than globbing ``data_root``
    itself: both ``_family_roots`` and the ``_registry_for`` cache key
    resolve AT CALL TIME off the currently active data root, so this sees
    exactly the one edition present after a subprocess's
    ``necb_pkg._set_data_root(data_root, _testing=True)`` -- the same
    removability property ``test_edition_independence.py`` exists to check.
    """
    data_root = Path(data_root)
    problems_a: list[str] = []
    problems_b: list[str] = []
    problems_c: list[str] = []
    for code_id in codes.code_ids():
        snapshot_dir = data_root / code_id
        own_year = int(code_id[-4:])
        for json_path in sorted(snapshot_dir.rglob("*.json")):
            if _is_archived_payload(json_path):
                continue
            rel_file = json_path.relative_to(data_root).as_posix()
            data = json.loads(json_path.read_text(encoding="utf-8"))
            _walk(data, [], own_year, rel_file, problems_a, problems_b, problems_c)
    return {"a": problems_a, "b": problems_b, "c": problems_c}


def check_self_description(data_root) -> list[str]:
    """Every self-description problem across every edition snapshot under
    ``data_root``, flat. Empty list = ok.

    Callable from the Stage 3 removability gate's subprocess (a fresh
    interpreter pointed at a temp tree holding one edition), exactly like
    ``tests.necb.test_edition_provenance.check_provenance`` -- so this
    contract is proven to hold with only one edition present too.
    """
    problems = find_problems(data_root)
    return problems["a"] + problems["b"] + problems["c"]


class TestSnapshotSelfDescription(unittest.TestCase):
    def test_no_cross_edition_reference_outside_provenance_and_no_comparison_inside_it(self):
        problems = find_problems(necb_pkg._data_root())
        total = problems["a"] + problems["b"] + problems["c"]
        if total:
            header = (
                f"(a) {len(problems['a'])} forward references, "
                f"(b) {len(problems['b'])} outside provenance, "
                f"(c) {len(problems['c'])} comparative\n"
            )
            body = "\n".join(total[:30])
            more = "" if len(total) <= 30 else f"\n... and {len(total) - 30} more"
            self.fail(header + body + more)

    def test_check_self_description_helper_matches_the_packaged_tree(self):
        """The exact function the Stage 3 removability gate calls."""
        problems = check_self_description(necb_pkg._data_root())
        expected = find_problems(necb_pkg._data_root())
        self.assertEqual(
            expected["a"] + expected["b"] + expected["c"], problems,
            "check_self_description must match find_problems' concatenation",
        )


if __name__ == "__main__":
    unittest.main()
