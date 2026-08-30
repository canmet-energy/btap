# R5 session handoff — full working context (2026-08-30)

Untracked working document (like the plan review copies): everything a
reviewer or a fresh implementer needs to verify the current state and
continue. Durable records: decisions D-79…D-83 in the canonical registry
(`python/btap/necb/data/decisions.json` → generated Ruby copy → doc +
TOC), `PORT_STATUS.md`, and the plan file at
`~/.claude/plans/prancy-booping-nova.md`.

## Where the D-80 retirement stands

| Phase | State |
|---|---|
| R1+R2 verification decoupling | MERGED + review-closed (PRs #15–#17) |
| R3 primacy flip (D-81) | MERGED + review-closed (PRs #18–#19) |
| R4 Leg-B handoff (D-82), backports stopped | MERGED + review-closed (PRs #20–#23) |
| **R5 distribution (D-83)** | **IN FLIGHT — see below** |
| R6 deletion | Planned; own go-ahead + fresh plan |
| Parked | legacy_pin/REF bump + TBD 3.6.x rebaseline (one adjudicated event) |

## R5 state, precisely

**Decisions fixed by the user**: FULL PYPI (btap + btap-energyplus +
py-tbd + py-topolys published; `pip install btap[tbd]` = the zero-thought
goal on Windows x86-64 and glibc-2.35+ Linux x86-64); the Python Windows
installer REPLACES the Ruby one (Ruby packaging dormant at R5, deleted
R6). Plan: `~/.claude/plans/prancy-booping-nova.md` (4 Sol review rounds
folded in).

**MERGED**: PR #24 (the fail-closed companion rung in
`python/btap/simulation/engine.py` + 7 controls + D-83 + its re-freeze —
byte-identical) and PR #25 (the narrowed import semantics: only a
ModuleNotFoundError naming `btap_energyplus` itself is "absent"; a real
broken-package control; `engine_available()` delegates to the probe).

**OPEN — PR #26 (branch `python-d80-r5-pr2`, head `e25ce7c`), awaiting
Sol's approval pass** (Sol's round-4 verdict blocked merge until findings
1–5 were corrected + a fresh dispatch with step-level evidence; all now
present — see the PR body's evidence table). Fresh dispatch
**33311219141**, all jobs green, key step-log lines:
- `auditwheel gate ok: grade manylinux_2_35_x86_64 == baked tag`
- `build-side validation ok: companion-only REAL sizing run
  (proposed+reference) with isolated cache and no env vars`
- `H-6 ok: with every dep present EXCEPT the companion, resolution
  fails NAMING btap-energyplus`
- `WHEEL SMOKE OK`; verify lane 3+3; parity lane 3+2.

**The blocker's resolution (understand this before touching the
builder)**: PEP 600 forbids manylinux wheels linking libpythonX.Y.
EnergyPlus links its own BUNDLED libpython (for the PythonPlugin API
btap never uses). The builder renames the bundled file to
`libeplus-python3.12.so.1.0` and patchelfs the two NEEDED entries
(`energyplus-25.2.0`, `libenergyplusapi.so.25.2.0`); auditwheel then
grades the completed wheel EXACTLY `manylinux_2_35_x86_64` and the build
gate asserts grade == baked tag. The patched binary runs. Recorded in
PROVENANCE.json inside the wheel.

**PR #26 contents** (3 commits): the builder
(`packaging/pypi/energyplus/build_wheel.py` — sha-verify BEFORE
modification, prune-list `python_lib`+`pyenergyplus` only, libpython
rename+patchelf, recursive ELF closure with $ORIGIN/allowlist
verification, keep-list assertion, PROVENANCE.json, exec bits via
external_attr, DIGESTS.json, auditwheel gate, scratch-venv companion-only
sizing validation); the `btap_energyplus` package template (runtime
chmod backstop in `binary_path()`); pyproject 0.2.0 with the HARD
platform-marked EXACT pin `btap-energyplus==25.2.0.1` and
`[tbd] = ["py-tbd==3.5.2"]`; wheel_smoke wheelhouse support + honest
H-6 + companion-resolution check; test.yml companion build+cache with
digest-verified restores, tag-sourced tbd-chain installs (interim),
`packaging/**` carved out of paths-ignore; the committed re-freeze.

## Step 0 — upstream releases (staged; blocked on USER's PyPI clicks)

Both repos are PUBLIC; this account has admin. Already pushed:
- **py-topolys**: tag `v0.1.0` ALREADY sits at the D-79 pinned SHA
  36470305. `publish.yml` on main extended with the TestPyPI
  same-artifact stage (commit f191470).
- **py-tbd**: metadata-only commit `e484597` on `tbd-3.5.2-compat`
  (py-topolys git pin → `==0.1.0`; diff vs bfb23e6 touches ONLY
  pyproject.toml), tagged `v3.5.2`. `publish.yml` on main (1a92d2c) with
  the diff guard, version guard, TestPyPI stage, verify job
  (canmet-from-TestPyPI + third-party-from-PyPI — openstudio is not on
  TestPyPI; stated explicitly), PyPI promotion from the same artifact.

**USER CHECKLIST (the only human-gated piece)** — on BOTH pypi.org and
test.pypi.org: add pending trusted publishers for `py-topolys`
(canmet-energy/py-topolys, publish.yml, env pypi/testpypi), `py-tbd`
(canmet-energy/py-tbd, same), `btap` + `btap-energyplus`
(canmet-energy/btap, publish.yml — lands with PR-3). In each GitHub
repo: Settings → Environments → create `pypi` WITH required-reviewer
protection (the promotion approval gate). File the PyPI size-limit
request for `btap-energyplus` (156.4 MB Linux wheel) at
github.com/pypi/support once the project exists. Then dispatch
publish.yml: py-topolys (tag v0.1.0) first, py-tbd (tag v3.5.2) second.

## Remaining R5 work after PR #26 merges

- **PR-3**: this repo's `publish.yml` (single-run same-bytes promotion:
  build companion+btap once as immutable artifacts → digest manifest →
  validate-linux → validate-windows (windows-latest, exact digest, PE
  closure, real sizing) → TestPyPI → TestPyPI-alone install both
  platforms → protected-env approval → PyPI from the same artifacts;
  REFUSES btap while deps unresolvable; never re-invokes builders) +
  `docs/release_r5.md`. Post-publication: flip the interim tag-sourced
  installs in test.yml + wheel_smoke to plain PyPI pins.
- **PR-4**: installer succession — `packaging/windows/stage_python.py`
  (embedded CPython 3.12 embeddable zip sha-pinned; `python312._pth` +
  Lib\site-packages populated by cross-platform pip `--target
  --platform win_amd64 --implementation cp --python-version 3.12
  --only-binary=:all:`; openstudio Windows wheel is cp312 — record its
  exact filename+digest); launcher rewrite (`set BTAP_HOME=%~dp0..` +
  exec `python.exe -m btap.necb.cli %*`); iss AppVersion 0.2.0 +
  UninstallDelete gems→python; README-windows licence REWRITE (LGPL .py
  sources + written source offer + generated THIRD-PARTY license
  inventory gating release — human legal review flagged);
  `release_guards.py` (the Rakefile five + version-triple match);
  `installer_smoke.py` (STANDALONE, never a frozen lane; windows-latest
  runs the staged tree with the checkout ABSENT — H-9); release.yml
  rewrite (bare-linux stage — no nrel container needed since
  generate_samples.py; windows smoke job; innosetup docker; DRY_RUN);
  Rakefile `windows:*` dormancy (`BTAP_RUBY_INSTALLER=1`, R6 deletes).
- **PR-5**: README (pip install btap[tbd] as the product; the scoped
  Linux promise "glibc-2.35+"; musl/older-glibc fails resolution BY
  DESIGN with the tested metadata-generated escape procedure; mac =
  NREL-download rung) + DEVELOPERS + THE RELEASE (publish in order, tag
  v0.2.0, clean-machine acceptance on Windows + the floor container).

## Traps and lessons (hard-won; do not relearn)

- **Per-edit writes, always**: a batch python script that asserts before
  its final write DISCARDS every prior edit on a miss. Bit this session
  three times.
- **Step-level log evidence, never job-level green** (the R4 lesson,
  formalized in memory): a completion claim about a CI step requires
  that step's own log line.
- **Never `git checkout <file>` to revert controls over UNCOMMITTED
  work** — copy-based snapshots (destroyed D-81 authoring once).
- The D-82 re-freeze rule is UNCONDITIONAL for intentional changes —
  commit the manifest line even when identical; do not re-argue.
- Built wheels are never committed (GitHub 100 MB; dist/ gitignored).
- The freezer/scenario machinery hashes (freezer/defs/runner/gate) are
  pinned — ANY edit to those four files, even comments, forces a
  clean-tree re-freeze.
- The scenario manifest's ancestry gate fails on provenance commits
  erased by history rewrites — correct behaviour; restore main's
  manifest if no pinned file changed.
- Interim installs: py-topolys tag FIRST, then py-tbd tag (its metadata
  now pins `py-topolys==0.1.0`, not yet on PyPI).
- `ensure_energyplus` resolution: override(raises on bad) → companion
  (fail-closed once imported) → unverified cache → archive → download.
  The frozen exit-4 scenario depends on the override's raise semantics.
- Local machine: openstudio CLI + E+ at `/usr/local/openstudio-3.11.0`;
  freezes take ~12–15 min; `BTAP_ENERGYPLUS=/usr/local/openstudio-3.11.0/EnergyPlus/energyplus`
  for verify/parity-lane local runs; builds need
  `python/.venv/bin/python` (py-tbd + patchelf + auditwheel live there).
- The NREL asset cache for builds:
  `<scratchpad>/eplus-assets/` (session-local; CI downloads fresh).

## Verify-the-state commands

```bash
gh pr view 26                      # the awaiting-review PR
gh run view 33311219141            # the evidence dispatch
git log --oneline main -8          # merged history through PR #25
python3 python/scripts/sync_decisions_registry.py --check
(cd python && BTAP_SCENARIOS_REQUIRED=1 .venv/bin/python -m pytest \
  tests/necb/test_frozen_scenarios.py -p no:cacheprovider -q)
```
