# btap (Python)

The Python port of the btap gem family — one distribution, five subpackages
mirroring the gems (`btap.audit`, `btap.simulation`, `btap.modeling`,
`btap.costing`, `btap.necb`), same one-way dependency direction (D-77),
ported milestone by milestone under the three-way verification harness
(D-78/D-79): every module lands against the Ruby suites' ported tests, the
Leg-C oracle goldens, and — once the CLI exists — the Leg-B corpus diff
against the Ruby `btap-compliance`.

During the migration the Ruby gems remain the shipping product and the Leg-B
baseline; behaviour changes land Ruby-first or not at all.

```bash
cd python && python3 -m unittest discover tests   # stdlib-only, no install needed (serial)
cd python && .venv/bin/pytest -n auto tests/      # parallel (pytest-xdist worker
                                                  # processes; ~10x on the E+ suites)
```

`btap/_compat.py` holds the cross-cutting Ruby-parity contracts (round-half-
away rounding, SDK Optional unwrapping, the NullAudit, determinism-critical
sorting, HTML escaping). New code uses those helpers, never the raw Python
equivalents — the differences they paper over are exactly the silent
Ruby-vs-Python drifts the census identified.
