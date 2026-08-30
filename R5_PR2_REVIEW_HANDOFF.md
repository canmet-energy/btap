# R5 PR-2 Review Handoff for Fable

Date: 2026-08-30

I reviewed and completed the final correction cycle for R5 PR #26.

## What I changed

The previous wheel smoke proved two separate facts:

- Source btap could run sizing through the installed companion.
- Installed btap could resolve the installed companion.

It did not prove that the **installed btap wheel could complete real sizing through the installed companion wheel**.

I updated `python/scripts/wheel_smoke.py` to add that end-to-end gate:

- Builds and installs the btap wheel in a scratch venv.
- Installs the companion wheel into the same venv.
- Requires both `btap.__file__` and `btap_energyplus.__file__` to reside under that venv.
- Executes `btap-compliance` from outside the repository.
- Removes `PYTHONPATH`, `BTAP_ENERGYPLUS`, `BTAP_ENERGYPLUS_ARCHIVE`, and `BTAP_COMPANION_WHEELHOUSE` from the CLI child environment.
- Uses an isolated `XDG_CACHE_HOME`.
- Runs both proposed and reference sizing.
- Requires a non-empty `eplusout.sql` for each run.
- Requires `EnergyPlus Completed Successfully` in each `eplusout.err`.
- Emits the installed package paths and a distinct installed-pair success marker.

I also changed `packaging/pypi/energyplus/build_wheel.py` to describe its own validation accurately: it tests source btap with the installed companion, while wheel smoke owns the installed-pair proof.

## CI failure and repair

The first corrected dispatch, `33314093120`, failed in both `python` and `verify`.

Both failures came from the same self-containment assertion:

```text
python/scripts/wheel_smoke.py references 'verification/'
```

The new smoke initially used the seed under `verification/oracle/fixtures`. I replaced that with `modeling.hvac.catalog_report.FIXTURE`, which resolves the seed shipped inside the installed btap wheel. This both fixed self-containment and strengthened the distribution test.

The exact previously failing test then passed:

```text
5 passed in 2.13s
```

## Local validation

The final installed-wheel smoke passed:

```text
H-6 ok: with every dep present EXCEPT the companion,
resolution fails NAMING btap-energyplus

btap imported from:
.../venv/lib/python3.12/site-packages/btap

btap-energyplus imported from:
.../venv/lib/python3.12/site-packages/btap_energyplus

installed-pair REAL sizing completed with isolated cache
and no engine-resolution overrides

WHEEL SMOKE OK
```

Compile, Ruff, editor diagnostics, and `git diff --check` also passed.

## Freeze discipline

I followed the unconditional D-82 rule after each intentional gate change:

- Implementation commit: `d3fc1bd`
- Re-freeze commit: `c0d4267`
- Self-containment repair: `cad7fc2`
- Final re-freeze commit: `18efb57`

The final freeze processed all 35 scenarios. Baseline bytes remained unchanged; only `manifest.provenance.commit` changed to `cad7fc2`. All four machinery hashes remained valid.

## Final CI evidence

Final full dispatch:

- Run: `33321928392`
- Head: `18efb578f5e60e620722eb2a8d3df2916de3b0f7`
- Result: success
- All eight jobs passed

Relevant log evidence:

```text
ELF closure ok: 7 shipped ELFs
auditwheel gate ok: grade manylinux_2_35_x86_64 == baked tag
installed-pair REAL sizing completed with isolated cache
ok installed btap + installed companion complete real sizing (R5)
WHEEL SMOKE OK
H-6 ok: ... fails NAMING btap-energyplus
```

Verification evidence:

```text
769 passed, 3 skipped, 80 warnings, 50 subtests passed
Frozen verify lane: 3 passed, 3 subtests passed
Frozen parity lane: 3 passed, 2 subtests passed
Live Leg C: 23/23 tests, 0 skips
```

## Merge record

PR #26 was merged:

- PR: <https://github.com/canmet-energy/btap-gems/pull/26>
- Validated head: `18efb578f5e60e620722eb2a8d3df2916de3b0f7`
- Merge commit: `6f7638edccafe1426897ba0e900d95a3a3a6d889`
- Merged: 2026-08-30 16:28 UTC

The merge commit tree was verified identical to the validated PR head.

Local `main` is at `6f7638e`. `R5_SESSION_HANDOFF.md` was deliberately preserved and never staged during this work.

## Current R5 boundary

PR #26 is complete. The next work is:

1. Finish Step 0 trusted-publisher setup and upstream `py-topolys` -> `py-tbd` publication.
2. Begin PR-3 for this repository's same-artifact TestPyPI/PyPI publication workflow and release checklist.
