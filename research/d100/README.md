# D-100 applicability research

Evidence for the D-100 classification (Sol's `050`, `055`, `058`, `059`, `060`,
`061`). **Not product code, and not the record.** The adjudicated result belongs
in the decision log as D-100; the payloads D-100 finally relies on move under
each edition's `provenance/` per the repository's retention convention.

Every number below is derived from the committed artifacts, and every artifact
is reproducible from this commit:

```bash
python3 research/d100/pipeline/rebuild.py            # verify (no network)
python3 research/d100/pipeline/rebuild.py --refetch  # also re-answer every request
```

`rebuild.py` rebuilds each derived artifact into a clean temporary directory and
compares it with the committed copy. It exits non-zero if any artifact is not
reproducible. Paths are derived from the script's own location; nothing is
hard-coded to one machine.

## Pipeline

```text
pipeline/common.py      roots, the state enum, the successor id grammar, IO
pipeline/citations.py   -> citations.json     every citation, TYPED
pipeline/fetch.py       -> hbix/, hbix_index.json  one archive per exact request
pipeline/trace.py       -> traces.json        ruling sites, chains, guards
pipeline/packets.py     -> packets.json       the mechanical half of each packet
pipeline/compare.py     -> comparisons.json   cross-edition, at the cited fragment
pipeline/rebuild.py     the reproducibility gate
```

## What the corpus contains

```text
citations                120   article 105 · table 12 · table-prefix-omitted 2 · note 1
exact requests           180   typed: an article/note is get_section, a table is get_table
  present                125
  mcp_empty               55
  hierarchy_absent         0
  error                    0
server_known_issue_count   2   get_table 8.4.5.5.-C@2020, get_table 8.4.6.5.-C@2025
packets                   97
  operative_clause null   56   requires_human_resolution
  superseding layers       9   D-19 D-20 D-21 D-27 D-28 D-46 D-57 D-61 D-80
ruling sites             174   across 48 decisions
  manifest-bound entry   151
  UNRESOLVED              23   marked, never inferred from a directory
comparisons              120
  substantively identical 23
  differs                 37   reported as spans, for reading
  not comparable          60   one side mcp_empty at that address
  at the cited fragment   28
  at the whole article    32
```

## Four states, never collapsed onto a boolean

```text
present           the tool returned content
mcp_empty         the tool returned nothing — NOT proven Code absence
hierarchy_absent  absence established from the edition hierarchy
error             transport/auth/protocol failure — FAILS THE RUN
```

A renumbered counterpart existing proves the positive mapping only. NECB 2025
did not vacate Subsection 8.4.4: it holds the archetype-EUI path there, so an
old `8.4.4.X` address can be absent OR resolve to an unrelated 2025 provision.
Nothing in this corpus carries `hierarchy_absent`; the 55 are `mcp_empty`.

## What the method does NOT establish

- **Reachability.** `path_based_candidates` records what a file's DIRECTORY
  would permit. It is evidence about the file, not a reachability claim: a
  shared module can branch on ruleset data. `per_code_chain` is null in every
  packet — the manifest-binding-to-site chain per code id, with edition guards,
  is human work.
- **Applicability.** Cross-edition text identity proves the text. It does not
  prove that a ruling, or its live realization, applies to both editions. Both
  axes must agree, and the ruling is Sol's. Every packet's `scope`, `code_ids`,
  `audiences` and `articles` are null.
- **An operative ruling.** Where no explicit marker is found the packet emits
  `operative_clause: null` plus `opening_context`, and never promotes an opening
  paragraph. D-19's opening states an OPEN problem and its ruling is three
  subsections later.

## Comparison method

Normalises exactly two things:

1. **Both subsection renumberings**, in ONE edition-keyed pass — reference
   `8.4.4 -> 8.4.5`, prescriptive `8.4.5 -> 8.4.6`. A sequential rewrite can
   move one reference twice. A token matching neither role for that edition is
   left alone.
2. **Observed subscript glyphs**, from an explicit allowlist. Not global NFKD,
   which folds superscripts and would erase the exponent in `(5/75)^n`.

Differences are reported as spans, never scored. A `similarity 1.000` hid four
real changes behind a rounded float.

## Locally observed extraction findings

`server_known_issue_count` is the SERVER's own flag and is **2**. That is not
the same claim as "no extraction issues observed". Observed separately, and not
folded into that count:

- `4.3.2.10` — the returned equation representations disagree internally about
  division versus multiplication (Sol).
- `8.4.4.14` / `8.4.5.14` — synthesized section text renders the VSD
  coefficients as `0.0015328` / `0.0052806`; `get_table` returns `0.00153028` /
  `0.00520806`, and the latter are what both edition snapshots carry (Sol).

An earlier corpus reported `known_issue: 0` because it fetched tables with
`get_section`, which does not carry a table's erratum. Both flags above are on
D-03's chiller EIR tables — the decision that is *about* a proposed erratum.

## Record inconsistencies surfaced

- **D-03** cites `8.4.5.5.-C` and `8.4.6.5.-C` without the `Table` prefix. The
  trailing designator makes the type unambiguous, so they are classified
  `table_prefix_omitted` rather than guessed past. Their pairing is positive
  evidence: `8.4.5.5.-C` is present in 2020 and empty in 2025, `8.4.6.5.-C` the
  reverse.
- **D-62** cites a sentence RANGE, `5.2.2.8.(4)-(5)`.

## Scope and lifetime

This snapshot is research. The 97 packets predate D-98, D-99 and D-100, so it
cannot be the final classification corpus — rebuild once those exist. The id
grammar is already the binding successor form, `D-(?:0[1-9]|[1-9][0-9]+)`, so
D-100 and beyond are matched rather than silently dropped.
