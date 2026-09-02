# CLAUDE.md — btap.audit

The family's shared audit machinery: **one** `AuditLog` class and **one**
article-coverage emitter. 207 lines across three files, and the dependency
floor — everything depends on it, it depends on nothing.

[README.md](README.md) is the API guide and is thorough: entry schema, the
`article:`/`ruling:` axes, the `ruling=` shape rules (D-44), the coverage
emit contract and its status→level table. Read it first. This file is only
what a change *here* costs, which the README does not say.

## Blast radius — read before editing `log.py`

This is the one subpackage where a small edit reaches everywhere. There is
no adapter layer between it and its callers: `btap.modeling`,
`btap.costing`, `btap.necb` and `btap.simulation` all import the same
`AuditLog`. Changing the schema, the level names, or `__str__`'s format
changes the AHJ report.

- **`__str__` is PARSED, not just displayed.** The report's checklist
  classifier reads the action text and is deliberately case-SENSITIVE
  (violations SHOUTED, passes lowercase). Reformatting the line shape breaks
  classification silently — the report still renders, with verdicts in the
  wrong buckets. The `"[%-8s] %-13s %s"` widths are part of the contract;
  Ruff's `UP` rules are disabled repo-wide partly to stop an auto-fix
  rewriting that `%`-format into an f-string.
- **`_truthy` is RUBY truthiness, deliberately.** Only `None` and `False`
  are falsy, so `''` and `0` DO render as segments. A Python reader's
  instinct — `if e.get("value"):` — is the wrong test here and will drop
  a legitimate zero. This is a byte-parity contract with the frozen
  baselines, not an oversight.
- **`_add` drops `None`-valued fields** rather than storing them, so a
  consumer must use `e.get("article")` truthiness, never `"article" in e`
  with a `None` fallback.
- **Keys are `str` everywhere.** Ruby's symbol-in-memory /
  string-in-JSON dualism collapsed at the port (D-79) and the serialized
  `audit.json` was byte-identical across the change. Do not reintroduce a
  second key convention.

## Keep it SDK-free

`log.py` imports only `json`, `contextlib` and `btap._compat`. **This
subpackage must never import `openstudio`.** That is not an aesthetic
preference — it is a machine-checked contract:

```toml
[[tool.importlinter.contracts]]
name = "audit is SDK-free and bottom of the family"
type = "forbidden"
source_modules = ["btap.audit"]
forbidden_modules = ["openstudio", "btap.simulation", "btap.modeling",
                     "btap.costing", "btap.necb"]
```

`lint-imports` fails on violation, and CI's `lint` job runs on a bare
runner with no OpenStudio precisely because this layer needs none.

## Traps

- **`warnings` is a PROPERTY, not a method.** `audit.warnings` is the list;
  `audit.warnings()` raises `TypeError: 'list' object is not callable`.
  Easy to get wrong coming from the Ruby original, where it was a method.
- **The recorded level is `'warning'`, not `'warn'`.** The writer is
  `warn()`; filtering entries on `'warn'` silently returns nothing.
- **There is no `'error'` level.** Levels are `decision | info | warning`,
  full stop. A test asserting "no error-level entries" can never fail — that
  exact dead guard shipped once and was caught in review.
- **`with_building` is a context manager that restores in `finally`** and
  nests. Pipelines rely on it to stamp phase boundaries (`'input model'` →
  `'proposed building'` → `'reference building'`, `None` for cross-building
  verdicts). Do not replace it with a plain attribute set.
- **`emit_coverage(None, audit)` is a deliberate no-op** — a domain whose
  ruleset carries no manifest emits nothing. Do not make it raise.
- **The trailing dot in an article id is load-bearing.** `decisions_citing`
  prefix-matches, so `'8.4.4.1.'` must keep its dot or it will match
  `'8.4.4.14.'` and claim its citations.
- **`step='coverage'` entries are never `ruling=`-tagged** — manifest
  boilerplate would swamp the report appendix's fire counts (which is why
  D-09 is `runtime_unwired`).

## Tests

```bash
cd python && .venv/bin/python -m pytest -q tests/audit/    # SDK-free, fast
```

The suite needs no SDK, no engine and no fixtures. If a change here forces
you to import OpenStudio to test it, the change is in the wrong layer.
