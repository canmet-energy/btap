# CLAUDE.md — the btap gem family (repository root)

Five standalone, SDK-only, **LGPL-3.0-or-later** Ruby gems, sliced by NATURE
(D-77): `btap-audit` (evidence), `btap-simulation` (execution),
`btap-modeling` (generic model authoring — no NECB anywhere), `btap-costing`
(the licensed-data seam), and `btap-necb` (every NECB 2020/2025 Part 8 rule,
the coverage manifests, the determination, the `btap-compliance` CLI). [README.md](README.md) is written for the
BUILDING ENGINEER — install, run, read the verdict, and what is not implemented;
the contributor material (family contract, devcontainer, MCP, test suites,
parity gates) lives in [docs/DEVELOPERS.md](docs/DEVELOPERS.md). Do not put
developer setup back in the README; **every gem carries its own `CLAUDE.md`** with
architecture, facade and traps — read that one before working inside a gem.
This file covers what is true across the family, plus how this repository came
to exist.

## Family contract (every gem obeys it)

- **Pure OpenStudio SDK.** No `openstudio-standards`, no measures, no BTAP.
- **Never simulates.** Only the umbrella (`btap-necb`) runs EnergyPlus.
- **One AuditLog schema** —
  `{step, target, action, inputs, value, article, ruling, evidence, building, level}`,
  levels `:decision | :info | :warning`. **Warnings are never silent.** The class
  lives in `btap-audit`; every other gem's `audit_log.rb` is a three-line
  alias. Change the schema THERE, never as a local copy.
- **Two citation axes.** `article:` cites the code that mandates a value;
  `ruling:` cites the adjudicated decision saying how we read it. `ruling:` is a
  TOP-LEVEL kwarg, single-quoted, on ONE line, never nested inside `inputs:`.
- **Audit text convention:** violations SHOUTED, passes lowercase — the report's
  checklist classifier is deliberately case-SENSITIVE.
- **Vintages 2020 + 2025 only.** 2011–2017 backfills are user-deferred.
- Dependency flow is ONE-WAY: `btap-necb` → `btap-costing` → `btap-modeling`
  → `btap-audit`, with `btap-simulation` beside; the umbrella runs E+ via it.
  Ruby modules are FLAT `Btap*` (`BtapNECB`, …). **`BTAP::*` is forbidden** —
  the oracle's `module BTAP` is live in-process in ten parity gates (D-77).

## Commands

```bash
cd btap-modeling && ruby test/test_catalog.rb     # a gem suite: plain ruby, no bundler
rake gems                                          # the five gems + versions
rake necb:verify                                   # orphan keys + 8.4.6 curves + hostile-outcome
rake necb:coverage_doc                             # regenerate coverage documents
rake legacy:pin                                    # the pinned oracle revision
rake legacy:whatsnew                               # what the fork has done since the pin
```

Tests run with **plain `ruby`**, not `bundle exec`. The per-gem Gemfiles exist so
`bundle exec` and `gem build` work; they are not how the suites run.

## How this repository came to be (2026-08-16)

Extracted from the `NatLabRockies/openstudio-standards` fork with
`git filter-repo`, keeping the nine gem dirs plus `legacy_pin/`. History
preserved: 9,403 → 199 commits, `.git` 4.61 GiB → 4.7 MB. The branch was renamed
`phylroy_dnd` → `main`. **The originals still exist in the fork** — removing them
is pending (see Open work).

The gems' relative-path requires (`../btap-<sibling>`), the shared test
fixtures in `btap-modeling/test/fixtures`, and all the doc cross-links depend
on this **flat sibling layout**. Do not nest the gems in a subdirectory or rename
their directories without fixing every one of them.

## Traps — all of these were paid for once

**The locale is load-bearing.** Without a UTF-8 locale Ruby's default external
encoding is US-ASCII, and `File.read` of anything the gems emit (`plan_svg.rb`
writes em dashes and `m²`; `necb_decisions.md` is full of them) raises
`invalid byte sequence in US-ASCII`. It took out three gems on CI's first run.
The devcontainer and the CI workflow both force `LANG`/`LC_ALL`; do not remove
them. Read a generated file with an explicit `encoding: 'UTF-8'`.

**`Gem::MissingSpecError` descends from `LoadError`, NOT `StandardError`.** A
bare `rescue StandardError` around `Gem::Specification.find_by_name` does not
catch it. Name it (`rescue Gem::LoadError, StandardError`) — see
`btap-costing/lib/btap_costing/envelope/database.rb`.

**The Leg-C oracle goldens follow legacy_pin/REF.** Bumping the pin without
re-exporting `verification/oracle/goldens/` fails the parity job's
currency meta-test loudly (D-78). Export happens IN CI (the pin bundle
lives there): dispatch `test.yml` with `export_goldens=true` and commit the
artifact. The exporter is GEM-FREE (D-80 python-prep / ruby-probe): prep
models come from `python/scripts/oracle_prep.py`, probe requests from the
committed `verification/oracle/request_manifest.json` — immutable except by
adjudicated update. Never hand-edit a golden — the manifest checksums are
asserted.

**The legacy oracle is ONE SHA, not a branch, and not a git remote.**
`legacy_pin/REF` is the whole tie to openstudio-standards. Nothing here points at
the fork's history, so `git log` cannot answer "has upstream moved?" — use
`rake legacy:whatsnew`.

**The lock records a REMOTE and bundler compares it.** `legacy_pin/Gemfile.lock`
commits the canonical fork URL. Setting `LEGACY_PIN_REMOTE` to a local checkout
(much faster, offline) makes them disagree until you `bundle install` once; until
then `bundle check` reports "not yet checked out". `test_legacy_archetype_e2e.rb`
gates on exactly that and therefore SKIPS. It skips loudly and never reports a
false pass. Use the same `LEGACY_PIN_REMOTE` for install and for every run.

**A skipped parity gate is a green-but-vacuous gate.** Always run them with
`LEGACY_PIN_REQUIRED=1`, which turns "oracle not bundled" from a skip into a
failure. There are **eleven** gates: envelope 4, loads 3, lighting 3, shw 1 —
and three of them are NOT named `*_parity.rb` (both `test_data_integrity.rb`,
lighting's `test_costing.rb`), so a glob misses them. CI lists them explicitly.

**`test_decisions_registry.rb` is not SDK-free** despite reading like a pure
doc/JSON drift check — it `require`s every gem's facade. It needs the container,
not a bare runner.

**Coverage is declared at the depth the evidence supports.** An entry's
`article` string carries its depth (`"8.4.5.9."` = whole article,
`"8.4.5.9.(5)"` = one sentence). The formerly-partial articles are per-sentence
(54 hvac entries per vintage, not 22; loads 9, not 7; umbrella 15/12) and tests
pin per-sentence ids — so **match coverage articles by PREFIX, never exact
string**. Do NOT split a uniformly-implemented article: that restates one claim
N times without sentence evidence, the exact fabrication the 8.4 HTML's depth
note warns about. `gap_owner: "modeller"` is only for requirements no model
change can ever satisfy (D-76); a rule the software could implement stays a
warning.

**Adding a `## D-XX` heading means adding a `decisions.json` entry** — the
CANONICAL one, `python/btap/necb/data/decisions.json` (R3, D-81). The Ruby
copy at `btap-necb/lib/btap_necb/data/decisions.json` is GENERATED from it;
never hand-edit that copy. The doc section is hand-authored, its id-ordered
TOC generated. The drift tests are hard in both directions:
```bash
python3 python/scripts/sync_decisions_registry.py   # canonical → generated Ruby copy
ruby btap-necb/scripts/generate_decisions_toc.rb    # after adding a decision
cd python && python3 -m unittest tests.necb.test_decisions_registry_sync tests.necb.test_decisions_registry
cd btap-necb && ruby test/test_decisions_registry.rb
```
A `kind: runtime` entry must be cited by ≥1 `ruling:` literal in BOTH
implementations (a gem's `lib/` AND `python/btap`) while both exist; entries
that are not cited must NOT be `runtime` (use `process`, `data`, or
`runtime_unwired`).

**`spec.files` excludes `test/` in every gemspec.** So
`btap-modeling/lib/btap_modeling/hvac/catalog_report.rb`'s `FIXTURE` constant is
already broken in a *packaged* gem. Pre-existing, not extraction fallout.

**All costing lives in btap-costing, and the priced pair is its shared
`data/` copy.** The old cross-gem CSV resolution is DEAD — priced values
resolve explicit-arg → `BTAP_COSTING_DIR` (`OPENSTUDIO_COSTING_DIR` still
honoured) → the gem's own placeholder tables. Real RS-Means values are
runtime-injected only and never committed or staged into the installer.

**The tbd triplet is pinned by `legacy_pin/Gemfile.lock`, not by any gemspec
constraint.** The suites run under plain `ruby`, so gemspec dependencies are
never resolved — tbd was absent from the devcontainer AND from CI, and the one
test proving the NECB 3.1.1.7 uprate/derate math skipped in both while the
summary line stayed green. The version is not a detail: tbd 3.5.2 / osut 0.8.2
and tbd 3.6.0 / osut 0.9.1 land 43% apart on the same wall, and BOTH pass the
unit test — only a parity comparison ever catches it. `ruby
legacy_pin/tbd_triplet.rb` prints the three in dependency order (topolys, osut,
tbd — resolving tbd first pulls the newest osut and defeats the pin) as valid
`gem install` arguments. `TBD_REQUIRED=1` turns the skip into a failure.

**One MCP key, and `set -a` is load-bearing.** `HBIX_API_KEY` covers all six
NRCan MCP servers and both Ruby scripts that call them directly;
`HBIX_MCP_BASE_URL` repoints all six at once. There is deliberately no
per-server alias for either. The key lives in a gitignored `.env` (template:
`.env.example`) that `~/.bashrc` auto-loads. A plain `source .env` sets the
variables without EXPORTING them, so Claude Code — a child process — expands
`${HBIX_API_KEY}` in `.mcp.json` to nothing and all six servers send an empty
`X-API-Key`. That surfaces as an opaque 403, never as a missing-key message.
The two scripts expand `${VAR}` placeholders themselves and treat an
unresolvable one as absent, so they fail into the message that names what to set.

**The devcontainer takes its CAs from the HOST, not off the network.**
`initializeCommand` runs on the host before the container exists and copies
`/usr/local/share/ca-certificates/*.crt` into `.devcontainer/certs/`
(gitignored, bind-mounted in). The routine it replaced cloned a certificate repo
*from GitHub* in order to make GitHub verifiable — circular, and on a
TLS-intercepting network the clone is precisely what fails, after which it
degraded silently into a container that could verify nothing. `gh` has no
`--insecure` escape hatch (unlike git's `http.sslVerify=false`), so certs are a
prerequisite for it, not an ordering preference.

## The command-line tool

`btap-necb/exe/btap-compliance.rb` (logic in `lib/btap_necb/cli.rb`)
turns the whole pipeline into one command: `.osm` in, EUIs + verdict + HTML
report out. `packaging/windows/` builds a Windows installer that bundles its own
OpenStudio, so the recipient installs one thing; `rake windows:stage` assembles
the payload from each gemspec's own `spec.files`.

The bundled-OpenStudio decision is why the launcher has no CLI detection, no
version gate and no PATH edit — and it removes version skew, which used to fail
opaquely ~20 minutes into a run.

## CI

`.github/workflows/test.yml`, four jobs — plus `release.yml`, which on a `v*`
tag push builds the Windows installer (stage in the SDK container, ISCC under
wine on the bare runner) and publishes it via `rake windows:release`;
dispatching it by hand rehearses the whole build but stops at `DRY_RUN`. Triggers are `push` to main/develop,
every `pull_request`, and `workflow_dispatch` — there is no `schedule:`:

- **`lint`** — bare runner, Ruby 3.2.2, no SDK. Orphan-key lint, the SDK-free
  `btap-audit` suite, and the coverage-doc gate: it regenerates both
  generated documents and demands a clean tree.
- **`test`** — matrix of the eight SDK gems in `nrel/openstudio:3.11.0`,
  `fail-fast: false`, `TBD_REQUIRED=1`. Each leg runs `rake test:gem[<gem>]`,
  which forks the gem's files rather than running them one at a time — the
  matrix parallelizes across gems, this parallelizes within one. The envelope
  leg installs the pinned tbd triplet first and asserts the ACTIVATED versions
  equal the lock.
- **`verify`** — decisions-registry drift + `rake necb:verify`, same container,
  and the registry generation direction (canonical Python → generated Ruby copy)
  is checked in `lint` on every PR.
- **`parity`** — the eleven gates with `LEGACY_PIN_REQUIRED=1`, cached on
  `legacy_pin/REF` because it clones the ~4.6 GB fork.

All four have run green. Parity was verified non-vacuous: 42 runs, 562
assertions, 0 skips — identical to local.

**`parity` is `workflow_dispatch` ONLY — nothing runs it on a timer.** Its `if:`
also names `schedule`, but `on:` declares no `schedule:` trigger, so that half
never fires. Dispatch it by hand whenever you bump `legacy_pin/REF`; that is the
only moment the oracle can move under you.

Costs are why parity is not on every push: a run was ~24 runner-minutes (~30
with parity) against the org's Team-plan allowance, and the biggest leg
was 9–11 of them — more than the other seven gem suites combined. The repo is
private, so those minutes are billed. `rake test:gem` cuts that leg; how much
depends on the runner's core count, which the job now prints so the next person
does not have to guess (locally, 45 files drop from ~10 min to ~150 s).

## The Python port (D-79)

A second implementation lives in `python/` — one pip distribution, `btap`,
with five subpackages mirroring the gems, ported milestone by milestone
against the D-78 verification. **`PORT_STATUS.md` at the repo root is the
handoff document**: what has landed, what each milestone was gated on, the
hazards the next one inherits, and the working agreements. Read it before
touching `python/`. Developer setup is in
[docs/DEVELOPERS.md](docs/DEVELOPERS.md#the-python-port-python-d-79).

**The port is COMPLETE and merged (M0–M8, PRs #5–#12, 2026-08-28).** The
whole surface is ported — audit, simulation + the EnergyPlus provisioner,
modeling, costing, the five necb rule domains, the umbrella (pipeline,
renderer, `btap-compliance` console script), and thermal bridging — and
verified: Leg B holds Ruby-CLI-vs-Python-CLI equivalence over the whole
corpus at the `none`, `sizing` and `annual --quick` tiers; Leg C closes
against the oracle both frozen (the goldens) and LIVE (the parity job's
lighting gate). The Python suite has ZERO unconditional skips — every skip
names a dependency and a REQUIRED flag, and CI supplies each somewhere with
its flag set.

Two rules OUTLIVE the port. (1) **Python is the primary implementation**
(R3, D-81): the Ruby gems have ZERO users and are kept green SOLELY as the
verification baseline, so a behaviour change lands Python-first WITH its
Ruby backport in the SAME PR — Leg B green at every commit — until R4's
verification handoff completes; a defect found on either side is fixed on
BOTH or flagged, never silently on one. (2) **Thermal bridging is pinned
to py-tbd's `tbd-3.5.2-compat` branch by commit SHA** — the revision
verified against the frozen Ruby TBD 3.5.2 / OSut 0.8.2 oracle triplet.
Never bump it to py-tbd main casually: main ports upstream 3.6.0, whose
uprate physics differ (~43% on a wall); the family-wide 3.6.x rebaseline
is a deliberate future event (see Open work).

## Open work

- **Retire the originals in the fork.** Remove the nine dirs + `legacy_pin/` from
  `NatLabRockies/openstudio-standards` and rewrite its `README.md:13-36` to point
  here. Keep the fork's `origin/nrcan` branch forever — it holds the pinned
  oracle `f01da13a6`.
- **The fork is 2 commits ahead of the pin** (`rake legacy:whatsnew`): #2134 adds
  a NECB footprint aspect-ratio option touching `btap/geometry.rb`, and #2136
  changes the costing sheets and `necb_2011.rb`. Absorbing means **bumping the
  pin and re-running the gates** — which since D-78/D-79 also means
  re-exporting the Leg-C goldens — never copying code across.
- **The TBD 3.6.x rebaseline** (pairs naturally with the pin bump): bump the
  Ruby triplet (tbd/osut/topolys) first, re-run Leg A, re-export the
  goldens, then retire py-tbd's `tbd-3.5.2-compat` branch and repoint the
  Python `[tbd]` pin at main. One adjudicated event, never a casual
  dependency upgrade — the two lines are ~43% apart on the same wall.
- **The LLM proposed-building workflow** (geometry → loads → constructions →
  HVAC). The one real physics gap: the envelope domain cannot build an opaque
  construction from nothing — zero `DefaultConstructionSet` usage family-wide, and
  `opaque_at_conductance` requires a base to deep-copy. Wizard geometry has no
  constructions, so `apply_prescriptive` silently skips everything. The test-only
  `seed_constructions` helper in `btap-modeling/test/test_bar.rb` is the
  placeholder to replace. Ordering constraint (D-75): thermostats come from
  the loads domain's `apply_loads` and gate the whole envelope pass via
  `Geometry.conditioned?`.
- **`NatLabRockies/openstudio-mcp`** (Python MCP server, ~150 tools) covers
  generic OpenStudio authoring but has **zero NECB content**, and its
  constructions skill is surface-at-a-time primitives that do not close the gap
  above. Licences do not mix — these gems are LGPL, that project is BSD-3-style —
  so the decision is to integrate at the **tool boundary, never the source
  boundary**: a thin `skills/necb/` package shelling out to these gems, not a
  fork. Do not copy gem source into it.
- Repository is **private**; the `LICENSE` preamble makes GitHub report
  `NOASSERTION` even though all nine gemspecs declare `LGPL-3.0-or-later`.
