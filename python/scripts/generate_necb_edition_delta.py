#!/usr/bin/env python3
"""Generate the NECB edition-to-edition delta Markdown document.

Stdlib-only (this runs under a bare ``python3`` in the ``lint`` job): reads
every edition manifest off disk by the path convention
``python/btap/codes/necb/data/<id>/manifest.json`` rather than importing
``btap.codes``, exactly the discipline ``generate_necb_coverage.py`` and
``necb_orphan_keys.py`` already use for the same reason.

For each pair of CONSECUTIVE editions (sorted by manifest ``edition``; today
just necb2020 -> necb2025), this first reports WHOLE-FILE additions,
removals and renames over the UNION of manifest-declared outputs (the same
coverage set ``python/tests/necb/test_edition_provenance.py`` uses for its
provenance gate: every ``rules`` value, every ``tables`` entry, and the
singular file keys ``coverage_text``/``eui_targets``/``ghg_factors``) --
an output declared by only one edition's manifest, or declared by both under
different filenames, would otherwise vanish silently from a diff keyed on
"present in both, same path".

For every output that DOES survive matching (same path in both editions, or
matched-but-renamed), it then produces a leaf-level diff of the JSON with
renumbering separated from value changes (multi-edition plan, Stage 4): a
leaf whose value differs from its counterpart ONLY by substituting an
article/table-number pattern (``8.4.4.`` -> ``8.4.5.``; a
``Table 5.2.12.1.-A`` suffix letter) is a RENUMBERING, not a value change.
A leaf that MOVED to a different key is a renumbering only when its
canonical value also matches its old counterpart; a moved leaf whose value
changed for a reason other than renumbering is reported as a CHANGE (old
path -> new path, old value -> new value), never folded into renumbering.
Everything else at a matched path is added / removed / changed (old -> new).
``provenance``, ``_provenance``, ``article_coverage`` and ``non_rule_keys*``
are excluded at any level, and so is any leaf whose value is prose longer
than 200 characters (a "how"/"notes" description, not a rule value).

``coverage_text`` (the Section 8.4 article-text cache) is matched at the
whole-file level (so an edition-only or renamed coverage-text file is still
reported) but is NOT leaf-diffed here: its keys are themselves bare article
numbers and its renumbering churn is already what the provenance/coverage
machinery accounts for; diffing it would just restate the citation-
renumbering table with worse signal.

Regenerated in the ``lint`` job next to ``generate_necb_coverage.py`` and
``generate_necb_8_4_coverage.py``; ``--check`` fails on drift (the
``generate_decisions_toc.py --check`` contract).
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "NECB_EDITION_DELTAS.md"
#: The one code family this generator knows about today (Stage 4 scope is
#: NECB only; Stage 9 generalises across families).
MANIFEST_GLOB = "python/btap/codes/necb/data/*/manifest.json"

#: Top-level (or nested) keys excluded from the diff at ANY depth: metadata
#: about the rule, not the rule itself.
EXCLUDED_KEYS_EXACT = {"provenance", "_provenance", "article_coverage"}
EXCLUDED_KEYS_PREFIX = ("non_rule_keys",)
#: A value this long is prose (a "how"/"notes"/"source" description), not a
#: rule value; excluded from the diff entirely.
PROSE_LENGTH = 200

#: An NECB article/table citation: three-or-more dot-separated numeric
#: segments (``8.4.4``, ``3.2.2.2``, ``5.2.12.1``), optionally with a table
#: suffix letter (``-A``) and/or parenthesized sub-clauses (``(2)(c)``).
#: Deliberately requires >= 2 dots so ordinary decimal VALUES (U-values like
#: ``0.29``, one dot) are never mistaken for citations.
CITATION_PATTERN = re.compile(r"\d+(?:\.\d+){2,}\.?(?:-[A-Z])?(?:\([0-9a-zA-Z]+\))*")

#: manifest keys, besides ``rules`` and ``tables``, that each map to ONE
#: declared output file. This is the same coverage set
#: ``python/tests/necb/test_edition_provenance.py``'s ``declared_outputs``
#: uses (duplicated, not imported: this generator stays off ``btap.codes``
#: on purpose -- see the module docstring -- and that test module imports
#: it).
SINGULAR_FILE_KEYS = ("coverage_text", "eui_targets", "ghg_factors")
#: Of those, the ones also leaf-diffed when a matched pair survives.
#: ``coverage_text`` is matched (so an edition-only/renamed coverage-text
#: file is still reported as added/removed/renamed) but never leaf-diffed --
#: see the module docstring.
LEAF_DIFFABLE_SINGULAR_KEYS = ("eui_targets", "ghg_factors")

#: A trailing 4-digit edition year immediately before the extension --
#: e.g. the ``_2020`` in ``tables/foo_2020.json`` -- stripped when matching a
#: renamed ``tables`` entry (which, unlike a ``rules`` entry, has no manifest
#: key of its own) by canonical basename across editions.
EDITION_SUFFIX_PATTERN = re.compile(r"_(?:19|20)\d{2}(?=\.[^.]+$)")


def _excluded(key: str) -> bool:
    return key in EXCLUDED_KEYS_EXACT or any(key.startswith(p) for p in EXCLUDED_KEYS_PREFIX)


def _is_prose(value) -> bool:
    return isinstance(value, str) and len(value) > PROSE_LENGTH


def canonical(value):
    """Normalise embedded article/table citations to '#' so two values that
    differ ONLY by renumbering compare equal."""
    if not isinstance(value, str):
        return value
    return CITATION_PATTERN.sub("#", value)


def _path_str(path: tuple) -> str:
    return ".".join(path)


def flatten(node, path: tuple = ()) -> dict:
    """Every leaf (path tuple -> scalar value) under ``node``, dropping
    excluded keys (at any depth) and prose leaves."""
    out: dict = {}
    if isinstance(node, dict):
        for key, value in node.items():
            if _excluded(str(key)):
                continue
            out.update(flatten(value, path + (str(key),)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            out.update(flatten(value, path + (str(index),)))
    else:
        if not _is_prose(node):
            out[path] = node
    return out


class FileDelta:
    """One file's leaf-level delta between two editions. ``old_rel_path``
    and ``new_rel_path`` differ only when the whole file itself was matched
    as a RENAME (see ``diff_whole_files``); otherwise they are equal."""

    def __init__(self, domain: str, old_rel_path: str, new_rel_path: str):
        self.domain = domain
        self.old_rel_path = old_rel_path
        self.new_rel_path = new_rel_path
        self.identical: list[tuple] = []
        #: (old_path, old_value, new_path, new_value) -- old_path == new_path
        #: for a same-path renumbering, or differ for a moved key whose
        #: CANONICAL value also matches (a pure renumbering).
        self.renumbered: list[tuple] = []
        #: (old_path, old_value, new_path, new_value) -- old_path == new_path
        #: for an ordinary value change, or differ for a moved key whose
        #: value changed for a reason other than renumbering.
        self.changed: list[tuple] = []
        #: (path, value)
        self.added: list[tuple] = []
        #: (path, value)
        self.removed: list[tuple] = []

    @property
    def rel_path_label(self) -> str:
        if self.old_rel_path == self.new_rel_path:
            return self.old_rel_path
        return f"{self.old_rel_path} → {self.new_rel_path}"

    @property
    def total(self) -> int:
        return (len(self.identical) + len(self.renumbered) + len(self.changed)
                + len(self.added) + len(self.removed))


def diff_file(domain: str, old_rel_path: str, new_rel_path: str, old_data, new_data) -> FileDelta:
    delta = FileDelta(domain, old_rel_path, new_rel_path)
    old_leaves = flatten(old_data)
    new_leaves = flatten(new_data)

    common = set(old_leaves) & set(new_leaves)
    only_old = set(old_leaves) - set(new_leaves)
    only_new = set(new_leaves) - set(old_leaves)

    for path in common:
        old_value, new_value = old_leaves[path], new_leaves[path]
        if old_value == new_value:
            delta.identical.append(path)
        elif canonical(old_value) == canonical(new_value):
            delta.renumbered.append((path, old_value, path, new_value))
        else:
            delta.changed.append((path, old_value, path, new_value))

    # Cross-path move: a leaf that moved to a differently-numbered key (e.g.
    # the article number is baked into the key itself). Pair only_old and
    # only_new entries whose CANONICAL path is unique on both sides -- but a
    # moved leaf is a RENUMBERING only when its value is ALSO unchanged after
    # canonicalisation; otherwise the move carries a real value change and is
    # reported as CHANGED (old path -> new path), never folded into
    # renumbering just because the key happened to move too.
    def canon_path(path: tuple) -> tuple:
        return tuple(canonical(segment) for segment in path)

    old_by_canon: dict = {}
    for path in only_old:
        old_by_canon.setdefault(canon_path(path), []).append(path)
    new_by_canon: dict = {}
    for path in only_new:
        new_by_canon.setdefault(canon_path(path), []).append(path)

    paired_old, paired_new = set(), set()
    for canon, old_paths in old_by_canon.items():
        new_paths = new_by_canon.get(canon)
        if new_paths and len(old_paths) == 1 and len(new_paths) == 1:
            old_path, new_path = old_paths[0], new_paths[0]
            old_value, new_value = old_leaves[old_path], new_leaves[new_path]
            if canonical(old_value) == canonical(new_value):
                delta.renumbered.append((old_path, old_value, new_path, new_value))
            else:
                delta.changed.append((old_path, old_value, new_path, new_value))
            paired_old.add(old_path)
            paired_new.add(new_path)

    for path in only_old - paired_old:
        delta.removed.append((path, old_leaves[path]))
    for path in only_new - paired_new:
        delta.added.append((path, new_leaves[path]))

    delta.identical.sort()
    delta.renumbered.sort(key=lambda row: (row[0], row[2]))
    delta.changed.sort(key=lambda row: (row[0], row[2]))
    delta.added.sort(key=lambda row: row[0])
    delta.removed.sort(key=lambda row: row[0])
    return delta


#: manifest `rules` key -> the label the document prints (mirrors
#: generate_necb_coverage.py's MANIFEST_DOMAINS so the two documents read the
#: same way).
MANIFEST_DOMAINS = {"umbrella": "necb", "hvac_efficiencies": "hvac_efficiencies"}


def _domain_label(key: str) -> str:
    return MANIFEST_DOMAINS.get(key, key)


def load_manifests(repo_root: Path) -> list[dict]:
    """Every edition manifest, PARSED and sorted by (family, edition)."""
    manifests = []
    for manifest_path in sorted(repo_root.glob(MANIFEST_GLOB)):
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        data["_dir"] = manifest_path.parent
        manifests.append(data)
    manifests.sort(key=lambda m: (str(m["family"]), str(m["edition"])))
    return manifests


def consecutive_pairs(manifests: list[dict]) -> list[tuple[dict, dict]]:
    """Consecutive (older, newer) manifest pairs WITHIN one family, in
    sorted-edition order."""
    pairs = []
    by_family: dict = {}
    for manifest in manifests:
        by_family.setdefault(manifest["family"], []).append(manifest)
    for family in sorted(by_family):
        editions = by_family[family]
        for older, newer in zip(editions, editions[1:]):
            pairs.append((older, newer))
    return pairs


def _canonical_basename(rel_path: str) -> str:
    """The basename of ``rel_path`` with a trailing 4-digit edition year
    before the extension stripped, so e.g. ``tables/foo_2020.json`` and
    ``tables/foo.json`` (or ``tables/foo_2025.json``) are recognised as the
    same table renamed across editions."""
    return EDITION_SUFFIX_PATTERN.sub("", Path(rel_path).name)


def _keyed_outputs(manifest: dict) -> dict[str, str]:
    """domain-key -> relative path for every output that carries a stable
    identity key across editions: each ``rules`` entry (keyed
    ``rules:<domain>``) plus the singular file keys. ``tables`` entries have
    no such key -- they are matched separately, by path."""
    keyed: dict[str, str] = {}
    for key, value in (manifest.get("rules") or {}).items():
        keyed[f"rules:{key}"] = value
    for key in SINGULAR_FILE_KEYS:
        value = manifest.get(key)
        if value:
            keyed[key] = value
    return keyed


def _keyed_domain_label(key: str) -> str:
    if key.startswith("rules:"):
        return _domain_label(key.split(":", 1)[1])
    return key


class WholeFileDelta:
    """Whole-FILE additions/removals/renames between two editions'
    manifests, over the UNION of manifest-declared outputs -- distinct from
    (and reported before) the leaf-level diff of a matched file's
    contents."""

    def __init__(self):
        self.added: list[tuple[str, str]] = []        # (domain, new_path)
        self.removed: list[tuple[str, str]] = []       # (domain, old_path)
        self.renamed: list[tuple[str, str, str]] = []  # (domain, old_path, new_path)

    @property
    def total(self) -> int:
        return len(self.added) + len(self.removed) + len(self.renamed)


def diff_whole_files(older: dict, newer: dict) -> tuple[WholeFileDelta, list[tuple[str, str, str]]]:
    """Whole-file added/removed/renamed, plus the (domain, old_rel_path,
    new_rel_path) triples for every output MATCHED between the two editions
    (same key/path, or matched-but-renamed) -- the latter is what feeds the
    leaf-level diff. An output declared by only one manifest never appears
    in the matched list; a renamed one appears in both (as a rename here,
    and as a normal leaf-diffable pair there) so its content is still
    compared."""
    delta = WholeFileDelta()
    pairs: list[tuple[str, str, str]] = []

    older_keyed = _keyed_outputs(older)
    newer_keyed = _keyed_outputs(newer)
    for key in sorted(set(older_keyed) & set(newer_keyed)):
        old_path, new_path = older_keyed[key], newer_keyed[key]
        domain = _keyed_domain_label(key)
        if key.startswith("rules:") or key in LEAF_DIFFABLE_SINGULAR_KEYS:
            pairs.append((domain, old_path, new_path))
        if old_path != new_path:
            delta.renamed.append((domain, old_path, new_path))
    for key in sorted(set(older_keyed) - set(newer_keyed)):
        delta.removed.append((_keyed_domain_label(key), older_keyed[key]))
    for key in sorted(set(newer_keyed) - set(older_keyed)):
        delta.added.append((_keyed_domain_label(key), newer_keyed[key]))

    older_tables = set(older.get("tables") or [])
    newer_tables = set(newer.get("tables") or [])
    exact = older_tables & newer_tables
    for rel_path in sorted(exact):
        pairs.append((f"tables/{Path(rel_path).stem}", rel_path, rel_path))
    only_old = older_tables - exact
    only_new = newer_tables - exact

    old_by_canon: dict = {}
    for rel_path in only_old:
        old_by_canon.setdefault(_canonical_basename(rel_path), []).append(rel_path)
    new_by_canon: dict = {}
    for rel_path in only_new:
        new_by_canon.setdefault(_canonical_basename(rel_path), []).append(rel_path)

    paired_old, paired_new = set(), set()
    for canon in sorted(old_by_canon):
        old_paths = old_by_canon[canon]
        new_paths = new_by_canon.get(canon)
        if new_paths and len(old_paths) == 1 and len(new_paths) == 1:
            old_path, new_path = old_paths[0], new_paths[0]
            domain = f"tables/{Path(old_path).stem}"
            pairs.append((domain, old_path, new_path))
            delta.renamed.append((domain, old_path, new_path))
            paired_old.add(old_path)
            paired_new.add(new_path)

    for rel_path in sorted(only_old - paired_old):
        delta.removed.append((f"tables/{Path(rel_path).stem}", rel_path))
    for rel_path in sorted(only_new - paired_new):
        delta.added.append((f"tables/{Path(rel_path).stem}", rel_path))

    delta.added.sort()
    delta.removed.sort()
    delta.renamed.sort()
    # `pairs` is left in construction order (rule keys in manifest-key sort
    # order, then tables in path order) rather than re-sorted by domain
    # label -- that construction order is what already reproduces the
    # pre-fix document's file ordering (e.g. "shw" before "necb", the
    # `umbrella` rule key's label, because "shw" < "umbrella" but not
    # "shw" < "necb").
    return delta, pairs


def collect_pair_deltas(older: dict, newer: dict, pairs: list[tuple[str, str, str]]) -> list[FileDelta]:
    deltas = []
    for domain, old_rel_path, new_rel_path in pairs:
        old_data = json.loads((older["_dir"] / old_rel_path).read_text(encoding="utf-8"))
        new_data = json.loads((newer["_dir"] / new_rel_path).read_text(encoding="utf-8"))
        deltas.append(diff_file(domain, old_rel_path, new_rel_path, old_data, new_data))
    return deltas


def _fmt(value) -> str:
    text = json.dumps(value) if not isinstance(value, str) else value
    return text.replace("|", "\\|").replace("\n", " ")


def render(pairs: list[tuple[dict, dict]]) -> str:
    generator = "python/scripts/generate_necb_edition_delta.py"
    regenerate = "python3 python/scripts/generate_necb_edition_delta.py"
    out = [
        f"<!-- Generated by {generator} — do not edit by hand.",
        f"     Regenerate: {regenerate} -->",
        "",
        "# NECB edition-to-edition deltas",
        "",
        "Leaf-level diff of every domain rule file and shared table between each",
        "pair of consecutive NECB editions, with RENUMBERING (a value that changed",
        "only by an article/table-number substitution, e.g. `8.4.4.` -> `8.4.5.`)",
        "reported separately from a genuine VALUE change. `provenance`,",
        "`article_coverage` and prose longer than 200 characters are excluded — this",
        "is a review artifact over rule VALUES, not the citation renumbering the",
        "coverage documents already track.",
        "",
        "Before the leaf-level tables, whole-file ADDED / REMOVED / RENAMED is",
        "reported over the union of every manifest-declared output — an output",
        "declared by only one edition, or renamed between editions, is called out",
        "there rather than silently dropped from the comparison.",
        "",
    ]

    if not pairs:
        out.extend(["_No consecutive edition pair found._", ""])
        return "\n".join(out)

    all_pair_deltas = []
    for older, newer in pairs:
        whole_file_delta, matched_pairs = diff_whole_files(older, newer)
        deltas = collect_pair_deltas(older, newer, matched_pairs)
        all_pair_deltas.append((older, newer, whole_file_delta, deltas))

    out.extend(["## Summary", ""])
    for older, newer, whole_file_delta, deltas in all_pair_deltas:
        out.append(f"### {older['id']} \u2192 {newer['id']}")
        out.append("")
        if whole_file_delta.total:
            out.append("**Whole-file changes**")
            out.append("")
            for domain, new_path in whole_file_delta.added:
                out.append(f"- added: `{new_path}` ({domain})")
            for domain, old_path in whole_file_delta.removed:
                out.append(f"- removed: `{old_path}` ({domain})")
            for domain, old_path, new_path in whole_file_delta.renamed:
                out.append(f"- renamed: `{old_path}` \u2192 `{new_path}` ({domain})")
            out.append("")
        out.append("| File | Identical | Renumbered | Changed | Added | Removed |")
        out.append("|---|---|---|---|---|---|")
        for delta in deltas:
            out.append(
                f"| {delta.domain} (`{delta.rel_path_label}`) | {len(delta.identical)} | "
                f"{len(delta.renumbered)} | {len(delta.changed)} | {len(delta.added)} | "
                f"{len(delta.removed)} |"
            )
        totals = {
            "identical": sum(len(d.identical) for d in deltas),
            "renumbered": sum(len(d.renumbered) for d in deltas),
            "changed": sum(len(d.changed) for d in deltas),
            "added": sum(len(d.added) for d in deltas),
            "removed": sum(len(d.removed) for d in deltas),
        }
        out.append(
            f"| **Total** | **{totals['identical']}** | **{totals['renumbered']}** | "
            f"**{totals['changed']}** | **{totals['added']}** | **{totals['removed']}** |"
        )
        out.append("")

    for older, newer, _whole_file_delta, deltas in all_pair_deltas:
        out.extend([f"## {older['id']} \u2192 {newer['id']}", ""])
        for delta in deltas:
            out.extend([
                "<details>",
                f"<summary><b>{delta.domain}</b> (`{delta.rel_path_label}`) — "
                f"{delta.total} leaves: {len(delta.identical)} identical, "
                f"{len(delta.renumbered)} renumbered, {len(delta.changed)} changed, "
                f"{len(delta.added)} added, {len(delta.removed)} removed "
                "(click to expand)</summary>",
                "",
            ])
            if delta.renumbered:
                out.extend(["#### Renumbered", "", "| Old path | Old value | New path | New value |",
                           "|---|---|---|---|"])
                for old_path, old_value, new_path, new_value in delta.renumbered:
                    out.append(
                        f"| `{_path_str(old_path)}` | {_fmt(old_value)} | "
                        f"`{_path_str(new_path)}` | {_fmt(new_value)} |"
                    )
                out.append("")
            if delta.changed or delta.added or delta.removed:
                out.extend(["#### Changed / added / removed", "", "| Path | Kind | Old \u2192 New |",
                           "|---|---|---|"])
                for old_path, old_value, new_path, new_value in delta.changed:
                    if old_path == new_path:
                        path_label = f"`{_path_str(old_path)}`"
                    else:
                        path_label = f"`{_path_str(old_path)}` \u2192 `{_path_str(new_path)}`"
                    out.append(f"| {path_label} | changed | {_fmt(old_value)} \u2192 {_fmt(new_value)} |")
                for path, value in delta.added:
                    out.append(f"| `{_path_str(path)}` | added | \u2014 \u2192 {_fmt(value)} |")
                for path, value in delta.removed:
                    out.append(f"| `{_path_str(path)}` | removed | {_fmt(value)} \u2192 \u2014 |")
                out.append("")
            if not (delta.renumbered or delta.changed or delta.added or delta.removed):
                if delta.total == 0:
                    out.extend([
                        "_No comparable leaves — every key in this file is excluded "
                        "(provenance / article_coverage / prose)._",
                        "",
                    ])
                else:
                    out.extend(["_No renumbering or value changes — every leaf is identical._", ""])
            out.extend(["</details>", ""])

    return "\n".join(out)


def generate(repo_root: Path = REPO_ROOT, output: Path = DEFAULT_OUTPUT) -> list[tuple[dict, dict]]:
    manifests = load_manifests(repo_root)
    if not manifests:
        raise ValueError(f"no edition manifests found under {repo_root / MANIFEST_GLOB}")
    pairs = consecutive_pairs(manifests)
    output.write_text(render(pairs), encoding="utf-8")
    return pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true",
                        help="regenerate to a temp file and fail if it differs from --output")
    args = parser.parse_args(argv)

    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        with tempfile.TemporaryDirectory() as tmp:
            fresh_path = Path(tmp) / args.output.name
            pairs = generate(args.repo_root, fresh_path)
            fresh = fresh_path.read_text(encoding="utf-8")
        if fresh == current:
            print(f"{args.output.name}: up to date — {len(pairs)} edition pair(s)")
            return 0
        print(f"{args.output.name}: STALE - run "
              "python3 python/scripts/generate_necb_edition_delta.py")
        return 1

    pairs = generate(args.repo_root, args.output)
    print(f"wrote {args.output.name} — {len(pairs)} edition pair(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
