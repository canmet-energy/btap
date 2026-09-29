# D-100 applicability research artifacts

Working artifacts for the D-100 classification (Sol's `050`, `055`, `058`,
`060`). **Not product code, and not the record.** The adjudicated result
belongs in `docs/decisions/` as D-100; the payloads D-100 finally relies on
move under each edition's `provenance/` per the repository's retention
convention. This directory exists so the evidence behind the packets is
reviewable rather than asserted from a private scratch directory.

## Layout

```text
method/fetch_articles.py   every cited article fetched in BOTH editions
method/trace.py            ruling= sites traced to public entry points
method/packets.py          per-decision mechanical extraction
hbix/<article>__<edition>.json   payload + {request, retrieved_utc, sha256}
hbix_index.json            every request, stamp, exists flag, known_issue
articles.json              the 120 citations, normalised to 69 base numbers
packets.json               97 packets, mechanical half
traces.json                174 ruling sites, chains and guards
renumbering_corrected.json the 17 cross-edition comparisons
```

## What the method does and does not establish

**Does:** the exact request and retrieval stamp for every payload, a SHA-256
per payload, the call chain from each `ruling=` site to a public entry point
corroborated by the import graph, and a character-level comparison of a cited
provision between editions.

**Does not:** decide applicability. A shared call site proves the code path is
common, not that the Code requirement is unchanged. Cross-edition text
identity proves the text, not that a ruling or its realization applies to both.
Both axes must agree, and the ruling is Sol's.

## Three states, kept distinct

```text
present          the article was returned for that edition
mcp_empty        the server returned empty content -- NOT proven absence
hierarchy_absent established from the edition hierarchy, not from a counterpart
```

A renumbered counterpart existing proves the positive mapping only. NECB 2025
did not vacate Subsection 8.4.4: it holds the archetype-EUI path there, so an
old 8.4.4.X address can be absent OR collide with a different 2025 provision.

## Known extraction findings, separate from the server's own `known_issue`

`server_known_issue_count` is 0 across all 145 payloads. That is not the same
as "no extraction issues observed". Observed, by Sol:

- `4.3.2.10` — returned equation representations disagree internally about
  division versus multiplication.
- `8.4.4.14` / `8.4.5.14` — synthesized text renders the VSD coefficients as
  `0.0015328` / `0.0052806`; `get_table` returns `0.00153028` / `0.00520806`,
  and the latter are what both edition snapshots carry.
