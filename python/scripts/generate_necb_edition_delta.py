#!/usr/bin/env python3
"""Generate the NECB edition-to-edition delta Markdown document.

Stdlib-only (this runs under a bare ``python3`` in the ``lint`` job): reads
every edition manifest off disk by the path convention
``python/btap/codes/necb/data/<id>/manifest.json`` rather than importing
``btap.codes``, exactly the discipline ``generate_necb_coverage.py`` and
``necb_orphan_keys.py`` already use for the same reason.

For each pair of CONSECUTIVE editions (sorted by manifest ``edition``; today
just necb2020 -> necb2025) and for each domain in the manifest ``rules`` map
plus each ``tables`` entry present in BOTH editions, this produces a
leaf-level diff of the JSON with renumbering separated from value changes
(multi-edition plan, Stage 4): a leaf whose value differs from its
counterpart ONLY by substituting an article/table-number pattern (``8.4.4.``
-> ``8.4.5.``; a ``Table 5.2.12.1.-A`` suffix letter) is a RENUMBERING, not a
value change; everything else is added / removed / changed (old -> new).
``provenance``, ``_provenance``, ``article_coverage`` and ``non_rule_keys*``
are excluded at any level, and so is any leaf whose value is prose longer
than 200 characters (a "how"/"notes" description, not a rule value).

``coverage_text`` (the Section 8.4 article-text cache) is NOT diffed here:
its keys are themselves bare article numbers and its renumbering churn is
already what the provenance/coverage machinery accounts for; diffing it
would just restate the citation-renumbering table with worse signal.

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
    """One file's leaf-level delta between two editions."""

    def __init__(self, domain: str, rel_path: str):
        self.domain = domain
        self.rel_path = rel_path
        self.identical: list[tuple] = []
        #: (old_path, old_value, new_path, new_value) -- old_path == new_path
        #: for a same-path renumbering, or differ for a moved key.
        self.renumbered: list[tuple] = []
        #: (path, old_value, new_value)
        self.changed: list[tuple] = []
        #: (path, value)
        self.added: list[tuple] = []
        #: (path, value)
        self.removed: list[tuple] = []

    @property
    def total(self) -> int:
        return (len(self.identical) + len(self.renumbered) + len(self.changed)
                + len(self.added) + len(self.removed))


def diff_file(domain: str, rel_path: str, old_data, new_data) -> FileDelta:
    delta = FileDelta(domain, rel_path)
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
            delta.changed.append((path, old_value, new_value))

    # Cross-path renumbering: a leaf that moved to a differently-numbered key
    # (e.g. the article number is baked into the key itself). Pair only_old
    # and only_new entries whose CANONICAL path is unique on both sides.
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
            delta.renumbered.append((old_path, old_leaves[old_path], new_path, new_leaves[new_path]))
            paired_old.add(old_path)
            paired_new.add(new_path)

    for path in only_old - paired_old:
        delta.removed.append((path, old_leaves[path]))
    for path in only_new - paired_new:
        delta.added.append((path, new_leaves[path]))

    delta.identical.sort()
    delta.renumbered.sort(key=lambda row: (row[0], row[2]))
    delta.changed.sort(key=lambda row: row[0])
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


def pair_files(older: dict, newer: dict) -> list[tuple[str, str]]:
    """(domain label, relative path) for every rules-domain and tables entry
    present in BOTH editions' manifests."""
    files = []
    older_rules = older.get("rules") or {}
    newer_rules = newer.get("rules") or {}
    for key in sorted(set(older_rules) & set(newer_rules)):
        if older_rules[key] == newer_rules[key]:
            files.append((_domain_label(key), older_rules[key]))
    older_tables = set(older.get("tables") or [])
    newer_tables = set(newer.get("tables") or [])
    for rel_path in sorted(older_tables & newer_tables):
        files.append((f"tables/{Path(rel_path).stem}", rel_path))
    return files


def collect_pair_deltas(older: dict, newer: dict) -> list[FileDelta]:
    deltas = []
    for domain, rel_path in pair_files(older, newer):
        old_data = json.loads((older["_dir"] / rel_path).read_text(encoding="utf-8"))
        new_data = json.loads((newer["_dir"] / rel_path).read_text(encoding="utf-8"))
        deltas.append(diff_file(domain, rel_path, old_data, new_data))
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
    ]

    if not pairs:
        out.extend(["_No consecutive edition pair found._", ""])
        return "\n".join(out)

    all_pair_deltas = [(older, newer, collect_pair_deltas(older, newer)) for older, newer in pairs]

    out.extend(["## Summary", ""])
    for older, newer, deltas in all_pair_deltas:
        out.append(f"### {older['id']} \u2192 {newer['id']}")
        out.append("")
        out.append("| File | Identical | Renumbered | Changed | Added | Removed |")
        out.append("|---|---|---|---|---|---|")
        for delta in deltas:
            out.append(
                f"| {delta.domain} (`{delta.rel_path}`) | {len(delta.identical)} | "
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

    for older, newer, deltas in all_pair_deltas:
        out.extend([f"## {older['id']} \u2192 {newer['id']}", ""])
        for delta in deltas:
            out.extend([
                "<details>",
                f"<summary><b>{delta.domain}</b> (`{delta.rel_path}`) — "
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
                for path, old_value, new_value in delta.changed:
                    out.append(f"| `{_path_str(path)}` | changed | {_fmt(old_value)} \u2192 {_fmt(new_value)} |")
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
