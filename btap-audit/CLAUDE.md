# CLAUDE.md — btap-audit

The family's shared audit machinery: **one** `AuditLog` class and **one**
article-coverage emitter. 180 lines across three files, and the lowest-level gem
— everything else depends on it, it depends on nothing.

[README.md](README.md) is the API guide and is thorough: entry schema, the
`article:`/`ruling:` axes, the `ruling:` shape rules (D-44), the coverage emit
contract and its status→level table. Read it first. This file is only what a
change *here* costs, which the README does not say.

## The Python twin (btap.audit)

This gem is fully mirrored by `python/btap/audit/` (the port is complete —
D-79; `PORT_STATUS.md` at the repo root is the record). **A behaviour change
here is now PYTHON-ONLY (D-82: the R4 handoff stopped Ruby backports)**:
this gem is FROZEN verification infrastructure — do not change its
behaviour. The Python twin changes with a re-frozen scenario baseline in
the same PR; the dormant cross-language gates sit behind `BTAP_LEGB=1`
until R6 deletes this tree.

## Blast radius — read before editing `log.rb`

This is the one gem where a small edit reaches everywhere. `AuditLog` is
aliased once per family gem:

```
btap-modeling/lib/btap_modeling/audit_log.rb      BtapModeling::AuditLog
btap-costing/lib/btap_costing/audit_log.rb        BtapCosting::AuditLog
btap-necb/lib/btap_necb.rb (module body)          BtapNECB::AuditLog
btap-necb/lib/btap_necb/loads.rb (guarded)        BtapNECB::AuditLog
``` **The aliases ARE the compatibility mechanism — there is no second
implementation.** Do not "tidy" them into a real class, and do not add a local
copy of the schema to a gem. `btap-necb`'s `test_decisions_registry.rb`
asserts that every family gem's `AuditLog` still resolves to
`BtapAudit::AuditLog`, and fails if one stops.

Changing the schema, the level names, or `to_s`'s format changes the AHJ report:

- **`to_s` is parsed, not just displayed.** The umbrella's checklist classifier
  reads the action text and is deliberately case-SENSITIVE (violations SHOUTED,
  passes lowercase). Reformatting the line shape breaks classification silently
   — the report still renders, just with verdicts in the wrong buckets.
- **`to_json` emits STRING keys** (`transform_keys(&:to_s)`) while `entries`
  holds SYMBOL keys. Consumers reading a written `audit.json` and consumers
  reading a live log see different key types. Both are load-bearing; do not
  "unify" one to the other.
- **`add` `.compact`s the entry**, so nil fields are absent rather than nil. A
  consumer must use `e[:article]` truthiness, never `key?`.

## Keep it SDK-free

`log.rb` requires only `json`. **This gem must never `require 'openstudio'`.**
That is not an aesthetic preference:

- CI's `lint` job runs `test/test_audit.rb` on a **bare runner** with no
  OpenStudio, precisely because this gem needs none. Adding an SDK dependency
  breaks that job.
- It is also why this is the only gem whose suite is instant.

The neighbouring trap, learned the hard way: `test_decisions_registry.rb` in the
umbrella *looks* equally SDK-free — it compares a markdown doc against a JSON
file — but it `require`s every gem's facade to check alias resolution, so it
needs the SDK container. Being pure Ruby is a property of THIS gem, not of
audit-adjacent tests generally.

## Traps

- **`with_building` is nestable and restores in `ensure`.** Pipelines rely on
  that to stamp phase boundaries (`'input model'` → `'proposed building'` →
  `'reference building'`, nil for cross-building verdicts). Do not replace it
  with a plain setter.
- **`warnings` selects on `level == :warning`**, not `:warn`. The writer methods
  are `decision` / `info` / `warn`, but the level recorded by `warn` is
  `:warning`. Filtering on `:warn` silently returns nothing.
- **`Coverage.emit(nil, audit)` is a deliberate no-op** — a gem whose ruleset
  carries no manifest emits nothing. Do not make it raise.
- **`step: :coverage` entries are never `ruling:`-tagged** — manifest
  boilerplate would swamp the report appendix's fire counts (this is why D-09 is
  `runtime_unwired`).

## Tests

```bash
cd btap-audit && ruby test/test_audit.rb   # SDK-free, sub-second
```

There is no Gemfile.lock to honour and no fixtures; the suite is self-contained.
