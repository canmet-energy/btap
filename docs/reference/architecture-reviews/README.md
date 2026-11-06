# Architecture reviews — `btap.stock`'s recipe reader/writer

Independent agent reviews commissioned 2026-11-06, retained because they
contain measurements and file:line evidence that are expensive to reproduce.
They are **reference material, not decisions.** Where a review's premise was
wrong, this README says so rather than editing the review.

## The documents

| File | What it is |
|---|---|
| `2026-11-06-astra-recipe-defect-family.md` | Why four same-day defects were one family, plus findings A–H |
| `2026-11-06-astra-classify-identify-architecture.md` | Whether `classify` + `identify` is the right architecture |
| `2026-11-06-fable-classify-identify-architecture.md` | The same question, answered independently, with a measurement |

Fable was deliberately **not** shown Astra's conclusions, so where the two
agree it is corroboration rather than one agent deferring to another. They
agree on: the catalogue should stay as named presets; a recipe should carry
builder parameters rather than a row name; the flat fact dict loses scope and
bindings; nothing in `btap.codes` or the D-58 golden is threatened. They
independently found the same defect — a chilled-water air handler told its
loop has no cooling coil, since fixed under #221.

## TWO PREMISES I GAVE THEM WERE WRONG

Read the reviews with these in mind, because large parts of both rest on them:

1. **I told them a recipe must be portable across geometries.** phylroy,
   2026-11-06: the HVAC section is deliberately bound to ZONES. The reader
   matches target zones by exact source zone NAME and refuses the group
   otherwise, which is correct for the retrofit workflow — hold geometry and
   zoning fixed, change the systems. Astra's semantic-roles proposal and
   Fable's zone-selector ruling are both moot.
2. **I framed the round trip as reproduction fidelity.** phylroy: recipes are
   independent of NECB and exist for **model articulation**.
   `python/btap/stock/CLAUDE.md` already said a generated building is
   "representative for loads, envelope and equipment performance, and only
   approximately for HVAC", and said not to quote a headline gap against a
   hand-built archetype as a property of the package. Both reviews judge an
   opt-in SUGGESTER (`suggest_systems=` and `accept_candidates=` are off by
   default) against a reconstruction standard it does not claim.

So the "replace the architecture" verdicts should be read as conditional on a
requirement that does not exist. What survives is the concrete defects.

## What came out of them

Fixed and on main: #216 opaque doors, #214 the phantom HRV, #219 the
economizer limits, #221 three fact-plumbing gaps, plus two repairs to this
branch's own earlier commits.

Still open: #217 heat recovery implementable in one builder (55 of 77
OA-bearing rows cannot carry it), #220 a PTAC-only group gaining a central
MAU, #212 the unweighted aggregates.

Fable's measurement is the durable part and now lives as a test —
`python/tests/stock/test_suggester_self_consistency.py`. Build each catalogue
row, scrub the loop names so name-recognition cannot answer, and ask whether
the row that built the model comes back:

```
before #221's fixes   top-1 18 / 110   top-5 40 / 110
after                 top-1 21         top-5 55
```

Pinned as floors, not targets — approximate HVAC is the contract, so the
property is that the number never silently falls.
