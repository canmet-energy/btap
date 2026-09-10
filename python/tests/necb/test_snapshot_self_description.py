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
    token in the same SENTENCE as a comparative word (``identical``,
    ``verified``, ``compared``, ``comparison``, ``renumber``, ``same as``,
    ``differs``, ``changed vs``, ``changes_vs``, ``mirrors``,
    ``cross-check``) is a problem, where a sentence ends at a ``.`` or
    ``;`` followed by whitespace or the end of the string (see
    ``_sentence_span``). A fixed character window can miss a comparative
    word in a long sentence or catch one from an unrelated neighbouring
    sentence; the sentence boundary is the actual unit of meaning. The
    plan's origin-phrase allowlist (``vendored from``, ``inherited from``,
    ``From NECB 2011 Table``, ``deep merge along``, ``retrieved via``,
    ``oracle``) is NOT applied as an override: a comparative word anywhere
    in the same sentence is still a problem — a sentence can carry both an
    origin clause and a comparison clause, and the comparison half is what
    this rule forbids. The allowlist is kept here only as a record of what
    a clean origin sentence looks like (one with no comparative word in it
    at all). The one exception is the origin-identity shape (see
    ``_ORIGIN_IDENTITY_RE``): "byte-identical to NECB20xx/data/..." is the
    only honest way to state an unmodified-copy fact. Two things follow from
    that, both scoped to the identity CLAUSE itself, never broadcast to the
    whole sentence: (i) the edition token that IS the object of that exact
    phrase (the `NECB20xx` inside the `.../data/...` path, see
    ``_identity_token_spans``) is never itself a (c) problem; (ii) the
    comparative word ``identical`` that the phrase is built from is masked
    out of the sentence (see ``_mask_identity_phrases``) before checking
    every OTHER token for a comparative word, so that one unavoidable word
    doesn't make an otherwise-clean origin narrative read as a comparison —
    a long origin sentence can legitimately name several other editions
    before ever reaching the clause that justifies them (e.g. "NECB2017 and
    NECB2020 ship no schedules table, so the merge resolves to NECB2015's:
    ... all 240 shipped records are byte-identical to
    NECB2015/data/schedules.json."). An unrelated comparative word elsewhere
    in the sentence still catches every non-identity-object token normally:
    `Rows are byte-identical to NECB2015/data/x.json but differs from
    NECB2011 values.` yields exactly one (c) problem, for the `NECB2011`
    token — `differs` is outside the identity clause and the masking does
    not touch it.

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

Passes on today's tree: the R-N re-freeze (deliverables 1-3 of the plan)
already stripped the ``-NECB2011`` curve-identifier suffix, the dead
vendored columns and the comparative provenance prose; the Sol review
follow-up (items 4-5 of "Sol's review of PRs #43/#44/#45") narrowed the
``notes`` exemption to ``curves[].notes``, rewrote the resulting exposure
(the necb2025 equipment rows' stale "From NECB 2020" citations), switched
rule (c) to a sentence-level check, and fixed the necb2020
``solar_pool_minimums`` forward reference to ``table-audit-necb-2020-
2025.md``. A further PR #43 review round narrowed the origin-identity
exemption from a whole-sentence bypass to the identity clause itself: the
phrase's own edition token is never a (c) problem, and only the
``identical`` it necessarily carries is masked out of the sentence before
checking every OTHER token for a comparative word -- so a mixed sentence
that also carries an unrelated other-edition comparison still gets its (c)
problem, while a genuinely long origin narrative naming several other
editions before its "byte-identical to NECB20xx/..." clause (the real
necb2020/necb2025 ``manifest.json`` ``tables/schedules.json`` note) still
passes. It also widened rule (a)'s ``NECB``-prefixed token to any
``20\\d\\d`` year rather than the five enumerated editions (so a snapshot
catches a forward reference to an edition that isn't enumerated yet, e.g.
``NECB 2030`` in a 2020 snapshot).
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

import btap.codes as codes
import btap.codes.necb as necb_pkg

#: `NECB20xx` for ANY two-digit year (not just the five enumerated editions),
#: or a bare `2020` restricted to those five and not glued to another digit or
#: a `.` (so table numbers like `8.4.5.2` and dates like `2026-07-22` never
#: match), plus the bare legacy word `vintage`.
#:
#: The `NECB`-prefixed form deliberately accepts any `20\d\d`, not the
#: enumerated list: a snapshot must catch a forward reference to an edition
#: that does not exist yet either (`NECB 2030` in a 2020 snapshot), and an
#: enumerated alternation can only ever be as current as the last edition
#: added to it. A bare, unprefixed year stays restricted to the enumerated
#: five -- `NECB` is what disambiguates a bare `20xx` reading as an edition
#: at all, so a bare `2030` is deliberately left too ambiguous with other
#: four-digit numbers to accept broadly.
#:
#: The trailing guard is `(?!\d|\.\d)`, not a plain `(?![\d.])`: a year is
#: excluded only when followed by another digit, OR by a `.` that itself is
#: followed by a digit (a table/article number like `8.4.4.2020.1`). A `.`
#: followed by anything else -- end of string, a letter, another `.` -- does
#: NOT exclude the year, so `2025.md` and a bare trailing `2025.` both match.
#: Without this split, the old `(?![\d.])` rejected a bare year merely for
#: having *any* `.` after it, which silently let a forward reference like
#: "...-2020-2025.md" through ungated for its 2025 half.
TOKEN_RE = re.compile(
    r"NECB ?20(?P<necb_yr>\d\d)"
    r"|(?<![\d.])20(?P<bare_yr>11|15|17|20|25)(?!\d|\.\d)"
    r"|\b(?P<vintage>vintage)\b",
    re.IGNORECASE,
)

#: Path segments that put a string inside the provenance key set.
#: ``notes`` is deliberately NOT listed here: D-88 names ``curves[].notes``
#: specifically, not every ``notes`` key. A bare ``curves`` segment followed
#: by an integer index is handled separately in ``_in_provenance_key_set``;
#: an equipment row's own ``notes`` (``unitary_acs[].notes``, and so on) is
#: NOT provenance and must speak in its own edition's terms like any other
#: field.
PROVENANCE_SEGMENTS = {"provenance", "_provenance", "derivation", "non_rule_keys_note"}

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

#: A sentence boundary: `.` or `;` immediately followed by whitespace or the
#: end of the string. Table/article numbers (`8.4.5.2`) and dotted paths
#: never trigger this -- their `.` is always followed by another digit or a
#: path segment character, never whitespace or end-of-string.
_SENTENCE_BOUNDARY_RE = re.compile(r"[.;](?=\s|$)")

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
    for i, seg in enumerate(path):
        if not isinstance(seg, str):
            continue
        if seg == "notes":
            # `curves[*].notes` only -- the segment directly before this
            # one is a list index, and the one before THAT is `curves`.
            if i >= 2 and path[i - 2] == "curves" and isinstance(path[i - 1], int):
                return True
            continue
        if seg in PROVENANCE_SEGMENTS:
            return True
        if seg.endswith("note") or seg.endswith("_provenance"):
            return True
    return False


#: "byte-identical to NECB2015/data/schedules.json" is an ORIGIN statement: it
#: says the shipped rows are an unmodified copy of that oracle file. The
#: comparative word is the only honest way to say so, so the edition token
#: that is the OBJECT of this exact phrase -- the `NECB20\d\d` captured as
#: ``oracle_path`` below, e.g. the `NECB2015` in "...identical to
#: NECB2015/data/..." -- is exempt from (c). This exemption is scoped to
#: that one token, not to the sentence around it: a sentence can legitimately
#: carry both a valid identity clause AND an unrelated comparative reference
#: to some other edition, e.g. "Rows are byte-identical to NECB2015/data/
#: x.json but differs from NECB2011 values." -- the `NECB2015` there is the
#: honest origin statement, but the `NECB2011` is a bare comparison the
#: allowlist was never meant to launder. See ``_identity_token_spans`` /
#: ``_is_origin_identity_token``, which test containment of the CANDIDATE
#: token's own span against the identity phrase's captured object span,
#: rather than asking only whether the phrase occurs anywhere in the
#: sentence.
_ORIGIN_IDENTITY_RE = re.compile(
    r"(byte-)?identical to (legacy )?(openstudio-standards )?(?P<oracle_path>NECB20\d\d)/(data|lighting)"
)


def _sentence_span(text: str, pos: int) -> tuple[int, int]:
    """The ``[start, end)`` span of the sentence containing character
    ``pos``, where a sentence ends at a ``.`` or ``;`` followed by
    whitespace or the end of the string (see ``_SENTENCE_BOUNDARY_RE``)."""
    start = 0
    end = len(text)
    for m in _SENTENCE_BOUNDARY_RE.finditer(text):
        boundary_end = m.end()
        if boundary_end <= pos:
            start = boundary_end
        elif boundary_end > pos:
            end = boundary_end
            break
    return start, end


def _identity_token_spans(sentence: str) -> list[tuple[int, int]]:
    """``[start, end)`` spans, within ``sentence``, of the `NECB20\\d\\d`
    token that is the OBJECT of a "(byte-)identical to NECB20xx/data/..."
    identity phrase -- the only part of the sentence exempt from rule (c),
    per ``_ORIGIN_IDENTITY_RE``'s ``oracle_path`` group."""
    return [m.span("oracle_path") for m in _ORIGIN_IDENTITY_RE.finditer(sentence)]


def _is_origin_identity_token(sentence: str, token_start: int, token_end: int) -> bool:
    """Whether the token spanning ``[token_start, token_end)`` within
    ``sentence`` IS the object of an identity phrase -- not whether the
    phrase merely occurs somewhere else in the same sentence."""
    return any(
        token_start >= span_start and token_end <= span_end
        for span_start, span_end in _identity_token_spans(sentence)
    )


def _mask_identity_phrases(sentence: str) -> str:
    """``sentence`` with every full origin-identity phrase match (e.g.
    "byte-identical to NECB2015/data", comparative word and all) blanked out.

    The comparative word ``identical`` inside ``(byte-)identical to
    NECB20xx/data/...`` is the honest way to state an unmodified-copy fact,
    so it must not itself make the REST of the sentence read as carrying a
    comparison -- a long origin sentence can legitimately name several other
    editions before ever reaching the clause that justifies them (e.g.
    "NECB2017 and NECB2020 ship no schedules table, so the merge resolves to
    NECB2015's: ... all 240 shipped records are byte-identical to
    NECB2015/data/schedules.json."). Masking, rather than a whole-sentence
    boolean, keeps this local to the identity clause itself: a genuinely
    unrelated comparative word elsewhere in the same sentence (e.g.
    "differs") still makes every non-identity-object token in it a (c)
    problem."""
    if not sentence:
        return sentence
    chars = list(sentence)
    for start, end in (m.span() for m in _ORIGIN_IDENTITY_RE.finditer(sentence)):
        for i in range(start, end):
            chars[i] = " "
    return "".join(chars)


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


def _has_comparative_word_in_sentence(sentence: str) -> bool:
    lowered = sentence.lower()
    return any(word in lowered for word in COMPARATIVE_WORDS)


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
        elif named_year is None or named_year != own_year:
            # (c) no comparison in provenance -- for OTHER editions only:
            # a snapshot verifying itself against its own edition's printed
            # table is provenance, not comparison. Sentence-level, not a
            # fixed character window: a comparative word ANYWHERE in the
            # same sentence as the token is a problem, so a long sentence
            # can't smuggle a comparison past a narrow radius.
            sentence_start, sentence_end = _sentence_span(text, match.start())
            sentence = text[sentence_start:sentence_end]
            token_start = match.start() - sentence_start
            token_end = match.end() - sentence_start
            # The identity-phrase's own object token is exempt outright --
            # it IS the "(byte-)identical to NECB20xx/data/..." clause's
            # subject, not a reference to "another" edition. For every OTHER
            # token, the comparative-word check runs against the sentence
            # with any identity phrase(s) masked out: `identical` inside the
            # identity clause itself must not count, but an unrelated
            # comparative word elsewhere in the same sentence still does.
            if _is_origin_identity_token(sentence, token_start, token_end):
                pass
            elif _has_comparative_word_in_sentence(_mask_identity_phrases(sentence)):
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


#: The two fixture snapshots for ``TestGateCatchesKnownShapes``, keyed by
#: code id exactly as ``find_problems`` expects (directory name == manifest
#: ``id`` == what ``own_year = int(code_id[-4:])`` reads). ``necb2020``
#: carries every scenario whose own edition is 2020; ``necb2025`` carries
#: the one scenario (stale equipment-row ``notes``) whose own edition needs
#: to be NEWER than the referenced 2020, so it cannot also be a forward
#: reference under rule (a).
_FIXTURE_MANIFEST = {
    "necb2020": {"id": "necb2020", "family": "necb", "edition": "2020", "label": "NECB 2020 (fixture)"},
    "necb2025": {"id": "necb2025", "family": "necb", "edition": "2025", "label": "NECB 2025 (fixture)"},
}

#: A sentence with the comparative word "verified" more than 80 characters
#: after the "NECB 2011" token, no `.`/`;` in between -- proves the (c)
#: check is sentence-level, not the old fixed 80-character radius (which
#: would have missed this one).
_LONG_SENTENCE = (
    "From NECB 2011 Table 8.4.4.21 the regenerated coefficients were "
    "transcribed from the original vendored source tables without any "
    "period in between and eventually this record was verified against "
    "the printed edition."
)

_FIXTURE_RULES_NECB2020 = {
    # (a) a forward reference: "2025.md" in a 2020 snapshot's `article`.
    "scenario_forward_ref": {"article": "See 2025.md for details"},
    # A table/article number shaped like a year -- must NOT match at all.
    "scenario_table_number": {"article": "Per 8.4.4.2020.1, this applies"},
    # (c) sentence-level: "verified" is >80 chars from the token, same
    # sentence, no origin-identity phrase -- must still be a problem.
    "scenario_long_sentence": {"provenance": {"note": _LONG_SENTENCE}},
    # The kept origin-identity exception: "byte-identical to NECB20xx/data/
    # ..." is the one honest way to state an unmodified-copy fact.
    "scenario_byte_identical": {
        "provenance": {"note": "All rows are byte-identical to NECB2015/data/x.json."}
    },
    # A token naming the snapshot's OWN edition next to "verified" is
    # self-identification, never a (b) or (c) problem.
    "scenario_own_edition_verified": {
        "provenance": {"note": "NECB 2020 Table 8.4.5.2 was verified against the printed edition."}
    },
    # (c) mixed sentence: a valid identity clause (NECB2015, exempt because
    # it IS the object of "byte-identical to NECB2015/data/...") sharing a
    # sentence with an unrelated comparative reference to a DIFFERENT other
    # edition (NECB2011, "differs from"). The old sentence-wide exemption
    # let the whole sentence through zero-problem; the fix scopes the
    # exemption to the identity phrase's own token, so NECB2011 still fails.
    "scenario_mixed_identity_and_reference": {
        "provenance": {
            "note": "Rows are byte-identical to NECB2015/data/x.json but differs from NECB2011 values."
        }
    },
    # The positive counterpart: the only other-edition token in the sentence
    # IS the identity phrase's object -- no problem in any bucket.
    "scenario_byte_identical_multi_record": {
        "provenance": {
            "note": "All 240 records are byte-identical to NECB2015/data/schedules.json."
        }
    },
    # (a) rule (a) must catch a forward reference to an edition that isn't
    # even enumerated yet -- TOKEN_RE's `NECB`-prefixed form has to accept
    # any `20\d\d`, not just the five enumerated editions, or a genuine
    # forward reference like this goes ungated. Spaced and glued forms.
    "scenario_unenumerated_edition_spaced": {"article": "See NECB 2030 for details"},
    "scenario_unenumerated_edition_glued": {"article": "See NECB2030 for details"},
}

_FIXTURE_RULES_NECB2025 = {
    # (b) `notes` OUTSIDE curves[] carrying another (older, non-forward)
    # edition -- the exact necb2025 efficiencies.json shape this review
    # found and fixed (equipment-row `notes` citing "NECB 2020" when the
    # row's own edition is 2025).
    "unitary_acs": [{"notes": "From NECB 2020, Table 5.2.12.1.-A"}],
}


class TestGateCatchesKnownShapes(unittest.TestCase):
    """Table-driven negative tests (Sol's review of PRs #43/#44/#45, item 4):
    small fixture snapshots in a temp data root, driving ``find_problems``
    directly against known-bad and known-good shapes so the gate's actual
    catch/pass behaviour is pinned, not just today's real snapshots."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.TemporaryDirectory(prefix="self-description-fixture-")
        tmp_path = Path(cls._tmpdir.name)
        for code_id, manifest in _FIXTURE_MANIFEST.items():
            snapshot_dir = tmp_path / code_id
            snapshot_dir.mkdir(parents=True)
            (snapshot_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (tmp_path / "necb2020" / "rules.json").write_text(
            json.dumps(_FIXTURE_RULES_NECB2020), encoding="utf-8"
        )
        (tmp_path / "necb2025" / "rules.json").write_text(
            json.dumps(_FIXTURE_RULES_NECB2025), encoding="utf-8"
        )
        cls._data_root = tmp_path
        necb_pkg._set_data_root(tmp_path, _testing=True)
        cls._problems = find_problems(tmp_path)

    @classmethod
    def tearDownClass(cls):
        necb_pkg._set_data_root(None, _testing=True)
        cls._tmpdir.cleanup()

    def _assert_bucket_has(self, bucket: str, needle: str):
        matches = [loc for loc in self._problems[bucket] if needle in loc]
        self.assertTrue(
            matches, f"expected {needle!r} in problems[{bucket!r}], got: {self._problems[bucket]}"
        )

    def _assert_no_problem_mentions(self, needle: str):
        for bucket in ("a", "b", "c"):
            matches = [loc for loc in self._problems[bucket] if needle in loc]
            self.assertFalse(
                matches, f"expected no problem for {needle!r}, got ({bucket}): {matches}"
            )

    def test_bare_year_forward_reference_fails_rule_a(self):
        """"2025.md" in a 2020 snapshot's `article` -- a forward reference,
        the exact shape the old `(?![\\d.])` trailing guard let through."""
        self._assert_bucket_has("a", "scenario_forward_ref.article")

    def test_table_article_number_is_not_a_token(self):
        """"8.4.4.2020.1"-style numbers must never match -- a `.` followed
        by a digit is a table/article number, not a bare year."""
        self._assert_no_problem_mentions("scenario_table_number")

    def test_notes_outside_curves_fails_rule_b(self):
        """`notes` on an equipment row (not `curves[].notes`) carrying
        another edition is a (b) problem -- D-88 names `curves[].notes`
        specifically, not every `notes` key."""
        self._assert_bucket_has("b", "unitary_acs[0].notes")

    def test_long_sentence_comparative_word_fails_rule_c(self):
        """A comparative word more than 80 characters from the token, same
        sentence, no origin-identity phrase -- the sentence-level rule
        catches what the old fixed-radius rule would have missed."""
        self._assert_bucket_has("c", "scenario_long_sentence.provenance.note")

    def test_byte_identical_to_oracle_path_passes(self):
        """"byte-identical to NECB2015/data/x.json" is the kept origin
        exception -- no problem in any bucket."""
        self._assert_no_problem_mentions("scenario_byte_identical")

    def test_own_edition_token_next_to_verified_passes(self):
        """A token naming the snapshot's OWN edition next to "verified" is
        self-identification, not a comparison -- no problem in any bucket."""
        self._assert_no_problem_mentions("scenario_own_edition_verified")

    def test_mixed_sentence_other_edition_token_outside_identity_phrase_fails_rule_c(self):
        """"Rows are byte-identical to NECB2015/data/x.json but differs from
        NECB2011 values." -- the NECB2015 token IS the identity phrase's
        object (exempt), but NECB2011 is a bare comparison the exemption
        must not launder. Exactly one (c) finding, for the NECB2011 token;
        the old sentence-wide exemption let this whole sentence through
        with zero problems."""
        matches = [
            loc for loc in self._problems["c"]
            if "scenario_mixed_identity_and_reference.provenance.note" in loc
        ]
        self.assertEqual(
            len(matches), 1,
            f"expected exactly one (c) finding, got: {matches}",
        )
        self.assertIn("NECB2011", matches[0])

    def test_byte_identical_multi_record_sentence_passes(self):
        """"All 240 records are byte-identical to NECB2015/data/
        schedules.json." -- the only other-edition token in the sentence is
        the identity phrase's own object, so no problem in any bucket."""
        self._assert_no_problem_mentions("scenario_byte_identical_multi_record")

    def test_unenumerated_necb_edition_spaced_fails_rule_a(self):
        """"NECB 2030" in a 2020 snapshot -- TOKEN_RE's `NECB`-prefixed form
        must accept any `20\\d\\d`, not just the five enumerated editions,
        or a forward reference to an edition that doesn't exist yet goes
        ungated."""
        self._assert_bucket_has("a", "scenario_unenumerated_edition_spaced.article")

    def test_unenumerated_necb_edition_glued_fails_rule_a(self):
        """Same as above with no space between `NECB` and the year:
        "NECB2030"."""
        self._assert_bucket_has("a", "scenario_unenumerated_edition_glued.article")


if __name__ == "__main__":
    unittest.main()
