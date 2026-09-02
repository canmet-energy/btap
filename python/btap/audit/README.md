# btap.audit

The shared audit machinery of the `canmet-btap` distribution (see
[the package README](../../README.md) for the family map): **one**
`AuditLog` class and **one** article-coverage emitter, used by
`btap.modeling` (authoring), `btap.necb` (hvac, envelope, loads, lighting,
shw, geometry and the umbrella), `btap.costing` and `btap.simulation`.

No domain knowledge, no OpenStudio dependency — this is the bottom of the
family, and import-linter enforces both facts.

```python
from btap.audit import AuditLog

audit = AuditLog()
with audit.with_building('reference building'):
    audit.decision('build',
                   'reference system operates on the proposed operating schedule',
                   target='SYS-3 air loop', inputs={'schedule': 'NECB-A'},
                   value='NECB-A', article='8.4.4.7.(1)', ruling='D-14')

audit.warnings      # a PROPERTY, not a method: never silent, anything skipped lands here
print(audit)        # narrative, one line per entry
audit.to_json()     # machines
```

## Entry schema

`{step, target, action, inputs, value, article, ruling, evidence, building, level}`
— all optional except `step` / `action` / `level`; `None` fields are dropped
at insert. `level` is `'decision' | 'info' | 'warning'`. **There is no
`'error'` level.**

- **`article`** cites the CODE that mandates a value (e.g. `'8.4.4.8.(1)'`).
  Several citations join into one string with `; `.
- **`ruling`** cites the adjudicated project DECISION that says how we read
  that code (`docs/necb_decisions.md`, mirrored machine-readably in
  `btap/necb/data/decisions.json`). Two axes: what was done, and why we did
  it that way.
- **`building`** is which model the entry is about (`'input model'`,
  `'proposed building'`, `'reference building'`; `None` = cross-building
  verdict), stamped automatically from the current context — set it at phase
  boundaries with the nestable `with_building(name)` context manager.
- **Contract: warnings are never silent** — anything skipped or unknown
  lands in the log.
- **Audit text convention:** violations are SHOUTED (`EXCEEDS`, `does NOT
  meet`, `BELOW the`), passes lowercase (`does not exceed`, `within`). The
  report's checklist classifier is deliberately case-SENSITIVE.

### The `ruling=` convention (D-44)

`tests/necb/test_decisions_registry.py` enforces this with an **AST walker**,
not a regex, so:

- TOP-LEVEL keyword argument, **never** inside `inputs=`;
- a string **literal** — a name, an f-string or a `**{'ruling': ...}`
  expansion on an audit-surface call is refused, not ignored;
- several ids = one space-separated string (`ruling='D-19 D-21'`), scanned
  as `\bD-\d{2}\b`;
- every id cited must exist in the registry, and every `kind: "runtime"`
  entry there must be cited by at least one tag — the test is hard in both
  directions;
- `ruling=None` parameter defaults and `ruling='D-14'` examples inside
  docstrings are excluded, so documenting the convention does not
  accidentally satisfy it;
- `step='coverage'` entries are NOT tagged (manifest boilerplate would swamp
  the report appendix's fire counts).

## The emit contract

Each domain owns an `article_coverage` manifest inside its vintage ruleset
JSON (`implemented` / `partial` / `not_implemented` / `satisfied_by_clone` /
`host_scope`) and resolves it its own way — from a pre-resolved ruleset
(hvac), from the domain's `rules(vintage)` (envelope, lighting, loads, shw),
or from a data-file path (the umbrella). What happens next is identical
everywhere and lives here:

```python
from btap.audit import emit_coverage
emit_coverage(coverage, audit)   # coverage = the resolved article_coverage dict
```

Every declared article lands in the audit as a `step='coverage'` entry
carrying `inputs={'status': …, 'decisions_citing': …}` (plus `gap_owner`
and `code` when present — `code` is the entry's "where is this dealt with"
list of `path#symbol` refs, resolved against real Python definitions by
`tests/test_coverage_code_refs.py` so a rename cannot leave a stale
pointer) and the manifest's `article`, so a missed requirement is visible
in every log rather than discovered by review. Levels:

| status | level |
| --- | --- |
| `implemented`, `satisfied_by_clone`, `host_scope` | `info` |
| `partial`, `not_implemented` | `warning` — on every run |
| any status with `gap_owner: "modeller"` | `info` scope note (D-09) |

`gap_owner: "modeller"` gaps are wholly the modeller's responsibility, so
the AHJ report is not permanently stamped with warnings no model change can
clear.

**Declaration depth.** An entry's `article` string carries its own depth:
`"8.4.5.9."` declares the whole article, `"8.4.5.9.(5)"` declares one
sentence, and the 8.4 coverage HTML groups sentence entries under their
article. Declare at the depth the evidence supports — the formerly-`partial`
articles are declared per sentence because their prose already adjudicated
each sentence, while a uniformly-`implemented` article stays one entry:
splitting it would restate the same claim N times without sentence-specific
evidence, which is the fabrication the coverage generator's depth note warns
about.

`decisions_citing` counts the run's `article` tags that PREFIX-match the
manifest id, after stripping a `' (slice label)'` / `'(N)'` suffix. The
trailing dot is kept deliberately: it is what stops `'8.4.4.1.'` from
matching `'8.4.4.14.'` and claiming its citations. Citations are harvested
with `\d+\.\d+(?:\.\d+)*\.`, so a Part 3 or Part 5 citation is scanned but
simply never prefix-matches a Part 8 manifest entry. `emit_coverage(None,
audit)` is a no-op — a domain whose ruleset carries no manifest emits
nothing.

## Tests

```bash
cd python && .venv/bin/python -m pytest -q tests/audit/    # SDK-free and fast
```
