# Developing canmet-btap

This guide is for contributors changing the product. To run a compliance check,
start with the [user README](../README.md).

R6 (D-84) retired the five product Ruby gems. The repository now ships one
Python distribution, `canmet-btap`, whose import package has five subpackages:
`btap.audit`, `btap.simulation`, `btap.modeling`, `btap.costing`, and
`btap.codes`. Ruby remains only for the pinned external oracle in `legacy_pin/`
and `verification/oracle/`.

## Contract

- Product code uses the OpenStudio SDK directly, not `openstudio-standards` or
  measures.
- Import direction is `necb` → `costing` → `modeling` → `audit`, with
  `simulation` beside and depending only on `audit`. Import-linter enforces it.
- `btap.audit` is SDK-free and owns the shared audit schema:
  `{step, target, action, inputs, value, article, ruling, evidence, building, level}`.
- `article` cites a code requirement; `ruling` cites a D-XX interpretation.
  Warnings are never silent. Violations are uppercase and passes lowercase
  because report classification is case-sensitive.
- Rules target NECB 2020 and 2025 only. Article-coverage manifests state every
  partial or missing sentence and emit the corresponding warning.
- An edition is selected by CODE ID: `code="necb2020"` on every public
  function, `--code necb2020` on the CLI (`btap.codes.code_ids()` is the
  list, `necb2020` the default). The per-edition data accessors take
  `edition="2020"`. `report.json` carries `edition`, `code` and
  `code_label`; audit entries that record the ruleset carry `code` and
  `edition` in `inputs` (D-87).
- Python is authoritative. Intentional output changes include a clean-tree
  frozen-scenario re-freeze and reviewed baseline diff in the same change.

## Requirements

- Python 3.11 or newer
- OpenStudio SDK 3.11.0
- EnergyPlus 25.2.0 for simulation tests
- A UTF-8 locale
- Ruby 3.2 and Bundler only when running the surviving legacy oracle

### Devcontainer

The devcontainer provides Ubuntu 24.04, OpenStudio 3.11.0, EnergyPlus 25.2.0,
Python, Ruby/Bundler for the oracle, and a UTF-8 locale. It installs staged host
certificates before network downloads, copies `.mcp.json.example` to the
gitignored `.mcp.json`, and leaves the multi-gigabyte oracle clone opt-in.

```bash
bash .devcontainer/setup.sh --no-claude
bash .devcontainer/setup.sh --serena
```

### Python environment

```bash
cd python
python3 -m venv .venv
.venv/bin/pip install -e '.[tbd]' pytest pytest-xdist pytest-cov import-linter ruff build
```

`[tbd]` installs the exact `canmet-tbd==3.5.2` thermal-bridging line. Do not
casually move it to upstream 3.6.x: the uprate physics differ materially and
require an adjudicated rebaseline.

### MCP servers

`.mcp.json.example` is tracked and `.mcp.json` is gitignored. The template holds
no secret; Claude Code expands `HBIX_API_KEY` from the environment. One key
covers codes, geocoding, weather, building-stock, modelling, and simulation.
`HBIX_MCP_BASE_URL` is the only URL override and repoints all six together.

```bash
cp .env.example .env
chmod 600 .env
$EDITOR .env
set -a && source .env && set +a
```

`set -a` is required in an existing shell because plain `source` does not
export values to child processes. The two Python maintainers' clients use the
same variables and also support a missing `.mcp.json`:

```bash
python3 python/scripts/fetch_necb_8_4_text.py
python3 python/scripts/building_stock.py --help
```

CI uses mocked protocol tests and never requires live HBIX.

## Testing

Fast local suite:

```bash
cd python
.venv/bin/pytest -n auto -q tests/
.venv/bin/lint-imports
.venv/bin/ruff check .
```

Serial zero-install fallback:

```bash
cd python && python3 -m unittest discover tests
```

Line coverage of `btap` (the frozen scenarios run in subprocesses, so they are
left out as they measure nothing):

```bash
cd python
.venv/bin/pytest -n auto -q --cov=btap --cov-report=term:skip-covered \
  --ignore=tests/necb/test_frozen_scenarios.py tests/
```

CI's `verify` job measures the same, publishes a per-module summary and an
HTML report, and fails below its floor (`--cov-fail-under` in
`.github/workflows/test.yml`). The baselines are recorded in
[necb_rule_verification.md](necb_rule_verification.md).

Repository checks from the root:

```bash
python3 python/scripts/necb_orphan_keys.py
python3 python/scripts/necb_8_4_6_curve_probe.py
python3 python/scripts/generate_necb_coverage.py
python3 python/scripts/generate_necb_8_4_coverage.py
python3 python/scripts/generate_decisions.py --check
cd python && python3 scripts/wheel_smoke.py
```

The `verify` CI job is the authoritative full-runtime lane: SDK, EnergyPlus,
rasterizer, sample corpus, thermal bridging, all 97 HVAC systems, and sizing
frozen scenarios are required rather than skipped.

**Running today's tests against an OLDER product tree** — to show a new test
fails without its fix — needs more than `PYTHONPATH`. The venv installs `btap`
as an editable install whose finder resolves the package to this checkout
whatever `sys.path` says, so the tests silently exercise the current code and
pass. Export the old tree (`git archive <ref> python/btap | tar -x -C <dir>`),
then, before importing `btap`, drop the editable finder and put the export
first:

```python
sys.meta_path[:] = [f for f in sys.meta_path
                    if 'editable' not in (type(f).__module__ + repr(f)).lower()]
sys.path.insert(0, EXPORT)
import btap
assert btap.__file__.startswith(EXPORT)   # never skip this check
```

## Decisions and generated docs

One decision is one file, `docs/decisions/D-NN.md`: TOML front matter
(`id`, `title`, `kind`, `articles`, `summary`) followed by the authored Markdown
body, whose first line is its own `## D-NN —` heading. Those files are
canonical. Both [necb_decisions.md](necb_decisions.md) and
`python/btap/codes/data/decisions.json` are generated from them, in numeric id
order, by `python3 python/scripts/generate_decisions.py`; use `--check` in
gates. To add or change a decision, edit the one source file and regenerate --
never the two outputs. The registry tests enforce the source schema, both
generated outputs, short-link resolution and runtime citations.

The two generated coverage documents are
[NECB_COVERAGE.md](NECB_COVERAGE.md) and
[NECB_8_4_COVERAGE.html](NECB_8_4_COVERAGE.html). Their retained filenames are
part of the evidence history; their inputs and code pointers are Python-owned
after R6. Do not edit either output by hand.

Section 8.4 source caches ship inside each edition's own snapshot at
`python/btap/codes/necb/data/necb<edition>/coverage/articles_8_4.json` for
offline, versioned use; the Crown-copyright notice and the cross-edition
disposition stay code-family-neutral in `python/btap/codes/data/coverage/`.
Refresh them only as a maintainer operation with
`python3 python/scripts/fetch_necb_8_4_text.py` and review the generated-doc
diff.

## Frozen scenarios

`verification/scenarios/` contains 45 scenarios in three lanes:

- `python`: engine-free, every Python-suite run
- `verify`: sizing, in the OpenStudio container
- `parity`: annual, in the dispatch-only parity job

When a deliberate behaviour change affects output, run
`verification/scenarios/freeze.py` from a clean tree and commit the resulting
baselines and provenance with the change.

**"Clean" includes untracked files, so freeze in a `git worktree`.** `freeze.py`
refuses on `git status --porcelain`, which lists untracked paths — and this
repository normally has other people's work-in-progress sitting in the tree, so
your own tracked changes being committed is not enough. A worktree at the
intended commit has no untracked files, so it is clean by construction rather
than by tidying:

```bash
set -euo pipefail                 # a failing step must STOP, not continue
REPO=$(pwd)                       # the main checkout
WT=/tmp/freeze-$(git rev-parse --short HEAD)
GUARD=$(mktemp -t freeze-guard-XXXXXX.py)   # OUTSIDE $WT — see below
trap 'rm -f "$GUARD"' EXIT                  # removed on failure too
PY=$REPO/python/.venv/bin/python  # one interpreter for every step

git worktree add --detach "$WT" HEAD

# PYTHONPATH IS MANDATORY, not belt-and-braces. One interpreter does not mean
# one source. Measured both ways from "$WT/python" on 2026-10-04:
#
#   $PY -c "import btap"   ->  $WT/python/btap     (cwd leads sys.path)
#   $PY some/script.py     ->  $REPO/python/btap   <- THE TRAP
#
# In script mode sys.path[0] is the SCRIPT's directory, not the cwd, so `btap`
# resolves through the venv's editable install — the main checkout. freeze.py
# is a script, and its check_required_python_engines() imports btap (line 117)
# BEFORE check_required_energyplus() reaches runner._sys_path_python() (line
# 151), so that module also lands in sys.modules first and persists.
export PYTHONPATH="$WT/python"

# THE GUARD FILE LIVES OUTSIDE $WT. Writing it inside makes `git status
# --porcelain` report `?? _assert_source.py`, and freeze.py checks exactly
# that — so the freeze refuses immediately after the guard passes, and no
# clean-tree freeze can follow. Sol hit this by running the recipe.
#
# `mktemp`, not `/tmp/freeze-guard-$$.py`: a predictable path on a shared
# host is a symlink-following write waiting to happen, since `cat >` follows
# an existing symlink. The `trap` removes it on failure as well as success,
# so a refused freeze leaves no stale guard behind (Sol, PR #76).
cat > "$GUARD" <<'GUARD_EOF'
import pathlib, sys
import btap
p = pathlib.Path(btap.__file__).resolve()
want = pathlib.Path(sys.argv[1]).resolve() / "python"
sys.exit(0 if p.is_relative_to(want) else f"WRONG SOURCE: {p} not under {want}")
GUARD_EOF
"$PY" "$GUARD" "$WT"               # script mode, like the freezer

# ...and the worktree must still be clean at the moment of freezing.
test -z "$(git -C "$WT" status --porcelain)" || {
  echo "worktree is dirty before freezing:"; git -C "$WT" status --porcelain; exit 1; }

cd "$WT/python"
"$PY" ../verification/scenarios/freeze.py

# TRANSFER the output before removing anything — freeze.py writes tracked
# baselines and the manifest, and they exist only here until copied.
#
# NOT `rsync --delete` into the shared tree: that would delete a colleague's
# UNTRACKED files sitting in baselines/, which this note promises not to
# touch. Copy the freeze's own output, then handle tracked DELETIONS
# deliberately via git, which only ever removes files git is tracking.
cp -r "$WT/verification/scenarios/baselines/." \
      "$REPO/verification/scenarios/baselines/"
cp "$WT/verification/scenarios/manifest.json" \
   "$REPO/verification/scenarios/manifest.json"

# A shrunken scenario set leaves obsolete TRACKED baselines behind, because
# the copy above is an overlay. `git ls-files --deleted` IN THE WORKTREE is
# the only query that sees them.
#
# An earlier version compared the two checkouts' plain `git ls-files` output.
# That reads the INDEX, not the working tree, and both checkouts start at the
# same commit — so a baseline `freeze.py` removed is STILL LISTED in $WT's
# index, and the comparison printed nothing precisely when a scenario had been
# removed. Reproduced in a scratch repo: after deleting a tracked baseline,
# `git status --short` shows ` D`, plain `ls-files` still lists it, and only
# `--deleted` reports it (Sol, PR #76).
#
# And this STOPS rather than warning. A removed baseline must be reviewed and
# `git rm`-ed deliberately, and the `|| true` on the old inventory meant a
# broken query looked identical to a clean one.
DELETED=$(git -C "$WT" ls-files --deleted -- verification/scenarios/baselines)
if [ -n "$DELETED" ]; then
  echo "the freeze REMOVED tracked baselines — review them, git rm them in"
  echo "$REPO deliberately, then re-run the drift check:"
  printf '%s\n' "$DELETED"
  exit 1
fi

# THE DRIFT CHECK, from the MAIN checkout, over THE LANES YOU ACTUALLY MOVED.
# `test_frozen_scenarios.py` defaults to BTAP_SCENARIO_LANES=python, the
# engine-free lane, which holds NONE of the sizing or annual baselines — so the
# default command can pass without comparing one changed file. Find the moved
# lanes with
#   git -C "$REPO" status --porcelain verification/scenarios/baselines
# and name them here.
cd "$REPO/python"
if PYTHONPATH="$REPO/python" BTAP_SCENARIO_LANES=python,verify \
   "$PY" -m pytest -q tests/necb/test_frozen_scenarios.py; then
  echo "zero drift on python,verify — PARTIAL: parity is dispatch-only"
else
  echo "DRIFT — the worktree is KEPT at $WT; inspect it"
  exit 1
fi

# THE WORKTREE IS DELIBERATELY NOT REMOVED HERE. The check above covers only
# the lanes that run locally; `parity` and `parity-scenarios` are
# dispatch-only, so the original freeze output is still the only copy of
# evidence for those lanes. Remove it once a green exact-head full dispatch
# has verified the affected lanes:
#
#   cd "$REPO" && git worktree remove --force "$WT"
#
# (`--force` because a completed freeze leaves the worktree dirty by
# construction; plain `remove` refuses it, and leaning on that refusal makes
# the recipe safe only in the case where nothing changed.)
echo "worktree kept at $WT until a full dispatch verifies the affected lanes"
```

Four things about that sequence, each of which was wrong in an earlier version
of this note:

* **The guard file is outside the worktree.** Inside, it registers as an
  untracked file and `freeze.py` — which checks `git status --porcelain`
  immediately — refuses. The guard passed and the freeze could never run.
* **It is an `if`/`else`, not `cmd || echo`.** `pytest … || echo "DRIFT"`
  turns a failed comparison into an exit-0 `echo` and then the cleanup
  underneath runs unconditionally, the opposite of what the message says.
* **No destructive mirror into the shared tree.** `rsync --delete` would
  remove a colleague's untracked files from `baselines/`. Tracked deletions
  are reported by `git ls-files --deleted` **in the worktree** — comparing the
  two checkouts' indices printed nothing exactly when a scenario had been
  removed — and the recipe **stops** so they are removed deliberately.
* **The worktree outlives a partial check.** Local lanes are not the whole
  corpus, so the freeze output is kept until a full dispatch has verified the
  lanes that only run there.

The drift step is what proves the freeze ran against the right source: if it
hadn't, the main checkout would disagree with the baselines it was just handed.
Verify the artifact, not the environment — but verify it over the lanes that
MOVED. The command above names `python,verify` rather than taking the default,
because the default `python` lane holds none of the simulating baselines and
would agree with anything.

Note the ordering, which matters more than it looks. `freeze.py`'s output lives
only in the worktree until you copy it, so removing the worktree first — or with
`--force` while still inside it — discards the only copy of a re-freeze you may
have waited an hour for. Leave it in place if the drift check fails: it is the
evidence you need to work out why. And the local comparison runs the default
`python` lane, which may not contain the baselines your change touched; check the
full dispatch for the `verify` and `parity` lanes.

Do **not** move or stash a colleague's untracked files, and do **not** use
`--allow-dirty` for a re-freeze you intend to commit — it records `dirty: true`
in the provenance, and nothing reads that field, so its only value is that a
human believes it. Sol ruled the strict predicate stays (2026-10-04): an
untracked `conftest.py`, `sitecustomize.py`, `.pth` or globbed data file can all
affect a run, so tracked-only cleanliness would weaken the provenance claim.

**Merge a freeze-carrying PR with GitHub's "Create a merge commit" (D-95).** A
PR that changes frozen baselines or the manifest provenance counts as
freeze-carrying — look for `manifest.json` or `baselines/` in the diff.
`freeze.py` records the commit it ran at — a branch commit — and
`test_manifest_integrity` requires that commit to be an ancestor of `HEAD`,
which is a separate claim from the content hashes the manifest already pins.

**Neither "Squash and merge" nor "Rebase and merge" will do.** Both give the
merged commit a new SHA, so the recorded branch commit is no longer an
ancestor and `main` goes red *after* the merge while every branch check was
green. Rebase merging is disabled on this repository, so that route is closed
mechanically — but it is the route that never bit: both measured breakages were
squashes, and the squash button is still there and still wrong for these PRs.
This is not theoretical: `main` failed that way for three days across two
merges, with a different stale pointer each time.

When it does happen the `main-red` job opens an issue naming the run and this
recovery path, assigned to `vars.MAIN_RED_ASSIGNEE` (or whoever pushed), and
closes it again when a push run on `main` is green. It tells someone; it does
not block anything.

If one is squash- or rebase-merged by mistake, re-freeze from the resulting `main` commit
and submit the minimal re-pin immediately; a pure repair moves only provenance
metadata and no baseline. And check the post-merge `main` run before calling
the work done — green PR-head CI is a different claim (D-94).

The 31 scenarios that once had live
Ruby seals are now `python-only:post-handoff` and retain their retired seal plus
the final attestation identity. The other fourteen are Python-only from their first
freeze: four that were already Python-only at the handoff, four NECB 2025
scenarios first frozen after R6, the two D-89 purchased-heating scenarios, and
the four DF-17 hydronic-VAV scenarios. A scenario authored after the handoff must
carry its own `python-only:` seal rather than inherit the default, or
`all_scenarios()` converts it to `post-handoff` and it claims a cross-language
attestation that was never run for it.

## Pinned oracle

`legacy_pin/REF` pins one full `openstudio-standards` SHA. Python-prepared models
and the Ruby probes in `verification/oracle/` produce live Leg-C evidence; the
committed goldens are in `verification/oracle/goldens/`. The whole-building
SmallOffice gate also generates its source model through this bundle.

```bash
BUNDLE_GEMFILE=legacy_pin/Gemfile bundle install

LEGACY_PIN_REQUIRED=1 \
BUNDLE_GEMFILE="$PWD/legacy_pin/Gemfile" \
PYTHONPATH="$PWD/python:/usr/local/openstudio-3.11.0/Python" \
BTAP_PYTHON="$PWD/python/.venv/bin/python" \
  bash verification/live_leg_c.sh /tmp/live-leg-c
```

For a local fork checkout, set `LEGACY_PIN_REMOTE=/path/to/openstudio-standards`
for both `bundle install` and every run. Bundler compares the remote with the
lock. `LEGACY_PIN_REQUIRED=1` turns an absent oracle into failure rather than a
vacuous skip.

On a pin bump, dispatch `.github/workflows/test.yml` with
`export_goldens=true`, download the `oracle-goldens` artifact into
`verification/oracle/goldens/`, and commit `REF`, `Gemfile.lock`, goldens, and
attribution together. Never hand-edit a golden. Full instructions are in
[legacy_pin/README.md](../legacy_pin/README.md).

## CI

`.github/workflows/test.yml` has six jobs:

| Job | Role |
|---|---|
| `lint` | orphan keys, coverage pointers and generated docs, decisions registry |
| `python` | import contracts, Ruff, full Python suite, installed-wheel smoke |
| `verify` | required SDK/EnergyPlus suite, NECB checks, sizing scenarios |
| `parity` | live pinned oracle, SmallOffice gate, optional golden export |
| `parity-scenarios` | annual frozen scenarios, in parallel with `parity` |
| `main-red` | on a failed push run on `main`, opens/updates an assigned issue (D-94) |

Beside it, `.github/workflows/decisions.yml` is a **separate path-unfiltered
gate**, not a seventh job. The property it enforces is exactly: path-unfiltered and reachable on pushes to main/develop, pull requests, merge groups and manual dispatch. It carries no `paths`/`paths-ignore` deliberately, and runs
`generate_decisions.py --check` plus
`tests.necb.test_decisions_registry{,_sync}` and
`tests.necb.test_decisions_generator` through stdlib `unittest` — no venv, no
dependency install, no SDK. It exists because `docs/decisions/D-NN.md` is the
canonical source of the runtime registry while `test.yml` path-ignores
`docs/**`: editing a source without regenerating touches only ignored paths, so
`test.yml` would not run, and `main` has no branch protection to require it.
`python/tests/test_decisions_gate_is_path_unfiltered.py` keeps the filter
absent and the check runnable as a failing command.

What the gate does NOT do: block a merge. `main` carries no branch protection
and no rulesets, and `main-red` is a job inside `test.yml` gated on that
workflow's own jobs — so a docs-only push to `main` with stale outputs turns
`decisions` red while `test.yml` never runs and no incident issue is opened. The
gate moves that failure from invisible to visible; someone still has to look.
`[skip ci]` in a head commit message skips it as it would any workflow.

`parity` and `parity-scenarios` are `workflow_dispatch` only; no schedule is
declared. Run them whenever the oracle pin changes.

`verify`, `parity` and `parity-scenarios` run in the CI image
`ghcr.io/canmet-energy/btap-ci`, built from `infra/ci-image/Dockerfile` by the
`ci-image` workflow under a content-addressed tag; `test_ci_image_pin.py` keeps
`test.yml` on the current one. With the repository variable
`CI_RUNNER=necb-ci`, every job but `lint` runs on a 36-vCPU AWS CodeBuild runner
([infra/aws-ci/README.md](../infra/aws-ci/README.md)).

## D-84 attestation

The final coexistence evidence is commit
`85ab14352677093e24038d933cf1071e5b03431a`, GitHub Actions run
`33544573991`: 45 Ruby parity runs / 629 assertions; Ruby SmallOffice 3 runs /
62 assertions; Python successor 4 tests; live Leg C 23/23; frozen parity
scenarios; lint, Python, verify, and every then-existing gem matrix job green;
zero parity skips. It is immutable historical evidence, not a claim that
product Ruby can still be run after R6.

The completed port chronology remains in [PORT_STATUS.md](../PORT_STATUS.md).
Do not rewrite that or the audit/decision records into present tense; update
only moved links when necessary.
