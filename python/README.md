# btap (Python)

The Python port of the btap gem family — one distribution, five subpackages
mirroring the gems (`btap.audit`, `btap.simulation`, `btap.modeling`,
`btap.costing`, `btap.necb`), same one-way dependency direction (D-77).
The port is COMPLETE (M0–M8, 2026-08-28; the record is `../PORT_STATUS.md`
and D-79), verified three ways: every Ruby suite ported, the Leg-C oracle
goldens consumed (frozen AND live), and the Leg-B corpus diff holding the
Ruby and Python `btap-compliance` CLIs equivalent at the `none`, `sizing`
and `annual --quick` tiers.

The Ruby gems remain the shipping product and the Leg-B baseline; behaviour
changes land Ruby-first or not at all.

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

## The CLI (M6)

The umbrella pipeline and its command line are ported:

```bash
pip install .                      # installs the btap-compliance console script
btap-compliance model.osm --epw weather.epw          # full 8.4.1.2 determination
python3 -m btap.necb.cli model.osm --simulate none   # no-install equivalent
```

Same seven exit codes as the Ruby CLI (0 compliant, 1 not compliant, 2
usage, 3 pre-flight, 4 simulation, 5 internal, 6 no determination), and the
same refusal to call a `--quick` week a determination. The Leg-B corpus gate
(`CLI_B=python bash verification/selftest.sh`) diffs this CLI's
`audit.json`/`report.json` against the Ruby CLI's over the whole corpus —
every pair equivalent at the `none`, `sizing`, and `annual` tiers.

## Thermal bridging (M7)

NECB 3.1.1.7 runs through **py-tbd** (native Python, no Ruby subprocess),
pinned by commit SHA to its `tbd-3.5.2-compat` branch — the revision
verified against the family's frozen Ruby TBD 3.5.2 / OSut 0.8.2 oracle
baseline:

```bash
pip install '.[tbd]'
```

Without it the pipeline still works: `thermal_bridging=` degrades to the
same loud audited 3.1.1.7-not-accounted warning the Ruby gem emits without
its tbd gem — never a silent clear-field result.
