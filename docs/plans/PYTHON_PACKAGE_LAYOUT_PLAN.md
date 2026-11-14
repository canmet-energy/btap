# Making `canmet-btap` installable straight from GitHub

Tracked in #229.

phylroy, 2026-11-14: *"I would like this project to be a true python package
that could be used straight from GitHub for development… Could you develop a
plan to make this a true python library in structure, while still supporting
APIs."*

## Status

- **Route A shipped** on PR #230: the build entry at the repository root,
  thermal bridging a default dependency (D-109), version `0.4.0.dev0`.
- **Route B started** 2026-11-14 on branch `src-layout` (stacked on #230),
  phylroy: *"Can we start the src reorg?"* The layout question below is
  settled as **`src/btap/`**, with `tests/` and `scripts/` at the root and
  `python/README.md` moving to `src/README.md`. Steps 1 (the checker,
  `scripts/check_path_rename.py`), 2, 3 and 5 are done; step 4, the
  re-freeze, follows on a clean tree. The rest of this document is the plan
  as written, in its period wording.

## What is already true

The distribution is a proper package in every respect **except where it sits**.
`python/pyproject.toml` already declares the metadata, the SPDX licence and
`license-files`, `requires-python`, platform-marked exact dependency pins, the
`tbd` extra, two console scripts, and an explicit `package-data` block that
exists because setuptools ships only `.py` by default and *"a wheel without
them fails on the first call"*. `btap/__init__.py` deliberately imports no
subpackage so `import btap` never pulls the SDK.

So this is not a packaging rewrite. It is a question of the build entry point.

## The one real blocker, measured

```
pip install .            ERROR: Neither 'setup.py' nor 'pyproject.toml' found
pip install ./python     succeeds
```

There is no `pyproject.toml` at the repository root, so

```
pip install git+https://github.com/canmet-energy/btap            FAILS
pip install "git+https://github.com/canmet-energy/btap#subdirectory=python"  works
```

Everything else about "use it from GitHub" already works once pip can find the
build entry.

## Two routes, with honest costs

### Route A — a root build entry (hours, near-zero risk)

A root `pyproject.toml` whose `[tool.setuptools] package-dir = {"" = "python"}`
and `packages.find.where = ["python"]` build the package where it already
lives. **Verified working**: a probe root `pyproject.toml` of exactly that
shape installed cleanly.

- `pip install git+<url>` works. `pip install -e .` from the root works.
- Nothing else in the repository moves.
- The cost is ONE source of truth. Keeping both `pyproject.toml` files invites
  drift — dependency pins and `package-data` would silently diverge, and
  `package-data` is the block whose own comment says the wheel breaks without
  it. So the root file must be the only one, which means
  `cd python && pip install -e .` stops working and the documented command in
  `CLAUDE.md` changes.
- It does NOT give a canonical layout: `pytest` still runs from `python/`, and
  the tree still looks unusual to anyone arriving from PyPI.

### Route B — move the package to the root (1–2 weeks, large but mechanical)

`src/btap` → `btap/` (or `src/btap/`), with `tests/`, `scripts/` and
`pyproject.toml` alongside.

The blast radius is **~16,700 `python/` references across 300+ files**, and
most of it is not source code:

```
verification/   14,281   56 frozen baselines whose audit output EMBEDS
                         the coverage code pointers
docs/            1,376   generated coverage documents with deep links
packaging/         253   the Windows installer tree
src/btap/       363   authored `article_coverage.articles[].code[]`
                         citations in the rules JSONs, BOTH editions
tests/      376
.github/            30   six workflow files
CLAUDE.md           27
```

Four interlocking consequences, each of which has bitten this project before:

1. the rules JSONs carry authored `code` pointers of the form
   `src/btap/codes/compliance.py#_evaluate`. Editing them changes the files,
   which carry a `result_sha256` in each edition's `manifest.json` — the
   provenance gate that must be recomputed (as it was on 2026-11-14 for an
   unrelated note);
2. the generated coverage documents carry line-number deep links, and
   `feedback-regenerate-coverage-in-the-same-commit` records five red runs in
   one session from getting that wrong;
3. the 56 frozen scenarios embed those pointers in their audit output, so the
   move forces a **mass re-freeze**, and a 16,000-line baseline diff is
   unreviewable — you could not tell a path rename from a behaviour change;
4. `test.yml`'s six jobs, the devcontainer, and the Windows packaging tree all
   hardcode `python/`.

**The pointers are repo-relative citations by design**, consumed by the
coverage generator — not filesystem paths resolved at runtime. So Route B is a
rename, NOT a correctness fix. It should be justified on layout grounds alone,
and not oversold.

## Recommended sequencing

**Route A first, as its own change.** It unblocks the stated goal —
installable from GitHub for development — in hours, with a blast radius of one
new file, one deleted file and a documentation line. Ship it, use it, and see
whether the canonical layout still matters afterwards.

**Then Route B, if the layout matters for its own sake**, in this order, each
step its own commit:

1. **make the rename machine-checkable first.** A script that asserts the
   whole diff is exactly `s|src/btap|btap|`-shaped, so the enormous diff can
   be reviewed as a property rather than read. Without this, step 4 is
   unreviewable and the project's re-freeze discipline cannot be honoured.
2. move source, tests and scripts; update `pyproject.toml`, `.github/`, the
   devcontainer and `packaging/`. Run the whole suite from the new root.
3. update the authored `code` pointers in both editions' rules JSONs and
   **recompute both `result_sha256` values**; regenerate the coverage
   documents in the SAME commit.
4. re-freeze all 56 scenarios on a clean tree, with the step-1 check proving
   the baseline diff is path-only.
5. update `CLAUDE.md`, `docs/DEVELOPERS.md` and the command block.

## APIs: what must keep working

Nothing here changes the API surface, and each of these is worth an explicit
test after either route:

- the two console scripts, `btap-compliance` and `btap-necb-coverage`;
- the public Python API — `btap.modeling` (19 public names),
  `btap.codes` (13), `btap.simulation` (2), and the subpackage-direct import
  style the root docstring prescribes;
- `import btap` must still NOT pull the OpenStudio SDK;
- `scripts/wheel_smoke.py`, which builds and installs the wheel and checks the
  installed distribution is self-sufficient — it already hardcodes the
  110-system catalogue count, so it is the natural place to assert the
  installed-from-GitHub path too;
- the import-linter contracts (D-77), which are declared by package name and
  so survive a directory move.

## What this plan does NOT propose

- **No `src/` layout debate resolved here.** `src/btap/` is the stricter
  convention and prevents accidental imports from the source directory; plain
  `btap/` is a smaller diff. Either satisfies "a true Python package"; pick one
  at the start of Route B, not during it.
- **No PyPI publication change.** The distribution already publishes; this is
  about installing from a git ref.
- **No move of `models/`, `legacy_pin/`, `verification/` or `infra/`.** They
  are repository infrastructure, not package contents, and they stay at the
  root under either route.
