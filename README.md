# The NECB gem family

Standalone, SDK-only Ruby gems implementing the **National Energy Code of Canada
for Buildings (NECB) 2020/2025 Part 8 performance path** — from authoring a model
out of nothing, through space-use loads, lighting, service water heating, HVAC and
envelope, to the full proposed-vs-reference determination and an AHJ-ready report.

Licensed **LGPL-3.0-or-later** (see [LICENSE](LICENSE)).

## The family

Dependency flow: `audit` ← everything; `geometry` → `loads` → (`lighting`, `shw`);
`hvac` and `envelope` stand alone; the umbrella composes the domain gems and runs
EnergyPlus via `simulation`.

| Gem | One line |
|---|---|
| [openstudio-audit](openstudio-audit) | the shared AuditLog + article-coverage emitter every other gem writes to |
| [openstudio-geometry](openstudio-geometry) | model creation: seven shape wizards, the bar-by-shape engine, measured-footprint massing, a 3D viewer |
| [openstudio-loads](openstudio-loads) | NECB space types, space-use loads, schedules, thermostats (the bare-geometry on-ramp) |
| [openstudio-lighting](openstudio-lighting) | Part 4 LPD allowances, daylighting controls, exterior lighting, fixture costing |
| [openstudio-shw](openstudio-shw) | Part 6 service-water-heating demand, Table 6.2.2.1 efficiencies, costing |
| [openstudio-hvac](openstudio-hvac) | 97-system topology catalog, Table 8.4.4.7.-A reference systems, efficiencies, HVAC costing |
| [openstudio-envelope](openstudio-envelope) | prescriptive Section 3.2, thermal bridging (TBD), reference envelope, costing |
| [openstudio-simulation](openstudio-simulation) | the EnergyPlus runner (local CLI backend + remote seam) |
| [openstudio-necb](openstudio-necb) | **the umbrella**: the full 8.4.1.2 proposed-vs-reference determination, one audit, the AHJ HTML report |

Each gem's README is its API guide.
[openstudio-necb/docs/README.md](openstudio-necb/docs/README.md) carries the family
glossary and the decision-register guide.

## The family contract

Every gem in this repository obeys the same rules:

- **Pure OpenStudio SDK.** No `openstudio-standards`, no measures, no BTAP.
- **Never simulates.** Only the umbrella (`openstudio-necb`) runs EnergyPlus.
- **One AuditLog schema** —
  `{step, target, action, inputs, value, article, ruling, evidence, building, level}`,
  levels `:decision | :info | :warning`. **Warnings are never silent.** The class
  lives in `openstudio-audit`; every other gem's `audit_log.rb` is a three-line
  alias of it.
- **Two citation axes.** `article:` cites the code that mandates a value;
  `ruling:` cites the adjudicated decision that says how we read it. Every id
  must exist in
  [openstudio-necb/docs/necb_decisions.md](openstudio-necb/docs/necb_decisions.md)
  and its machine-readable mirror; a drift test enforces both directions.
- **Audit text convention:** violations are SHOUTED, passes are lowercase — the
  report's checklist classifier is deliberately case-sensitive about this.
- **Article-coverage manifests.** Each vintage ruleset JSON declares what it
  implements; partial and not-implemented entries warn on every run.
- **Vintages 2020 and 2025 only.** 2011–2017 backfills are deferred.

## Requirements

- Ruby 3.2.2
- OpenStudio SDK 3.11.0 (`require 'openstudio'` must succeed; the SDK is
  deliberately not declared as a gem dependency)
- The `openstudio` CLI, for the tests that run EnergyPlus
- **A UTF-8 locale.** Without one, Ruby's default external encoding is US-ASCII
  and `File.read` of anything the gems emit — `plan_svg.rb` writes em dashes and
  `m²`, the decisions doc is full of them — raises
  `invalid byte sequence in US-ASCII`.

### Devcontainer

`.devcontainer/` provides all of the above: Ubuntu 24.04, Ruby 3.2.2,
OpenStudio 3.11.0, EnergyPlus 25.2.0, and `LANG=en_US.UTF-8`, on the
`canmet/os_sdk_container:3.11.0` image. Open the repo in VS Code and reopen in
the container. `postCreate` installs NRCan certificates when it detects that
network, installs **Claude Code**, installs `.mcp.json` from the template,
verifies the toolchain, and prints the common commands.

```bash
bash .devcontainer/setup.sh --no-claude   # skip the Claude Code install
bash .devcontainer/setup.sh --serena      # also add uv + the Serena MCP server
```

It deliberately does **not** clone the legacy oracle — that is gigabytes, so it
stays opt-in.

### MCP servers

`.mcp.json.example` is tracked; `.mcp.json` is **not** (the family rule is never
to stage it). Setup copies the template, which carries **no key** — Claude Code
expands `${VAR}` in `url` and `headers`, so the secret stays in your
environment.

The key lives in a gitignored `.env`, using the same variable name and the same
loading mechanism as [canmet-energy/bluesky](https://github.com/canmet-energy/bluesky),
so one `.env` works in both repositories:

```bash
cp .env.example .env
chmod 600 .env
$EDITOR .env        # set HBIX_API_KEY
```

`.devcontainer/setup.sh` appends an auto-load block to `~/.bashrc`, so a **new
terminal** has the key exported. To load it into the shell you are already in:

```bash
set -a && source .env && set +a
```

The `set -a` is load-bearing. A plain `source .env` sets shell variables without
**exporting** them, so Claude Code — a child process — expands `${HBIX_API_KEY}`
to nothing and all six servers send an empty `X-API-Key`. That surfaces as an
opaque 403, not as a missing-key message.

**One key, one name.** `HBIX_API_KEY` covers all six MCP servers (codes,
geocoding, weather, building-stock, modelling, simulation) and both Ruby scripts
that call them directly — those scripts expand the `${VAR}` placeholders in
`.mcp.json` themselves and abort with a clear message when the key is
unresolvable. There is deliberately no per-server key alias, because the servers
do not take different keys.

`HBIX_MCP_BASE_URL` is the only other knob: it repoints all six servers at
once — for the Ruby scripts and for `.mcp.json` alike — at a staging or local
stack. There are no per-server overrides for the URL either; the scripts append
their own `/<server>/mcp` path. That also keeps a missing `.mcp.json` a
supported configuration without hardcoding a host in the scripts.

## Testing

Each gem is self-contained:

```bash
cd openstudio-hvac && ruby test/test_catalog.rb
```

Cross-gem rule verification runs from the repository root:

```bash
rake necb:verify        # orphan-key lint + 8.4.6 curve probe + hostile-outcome tests
rake necb:coverage_doc  # regenerate the coverage documents
```

### Legacy-parity gates

The parity suites compare against a **pinned revision** of the NECB/BTAP
implementation in the `NatLabRockies/openstudio-standards` fork. See
[legacy_pin/README.md](legacy_pin/README.md) for the pinning mechanism and the
bump workflow.

The tie to that fork is `legacy_pin/REF` — **one commit SHA, not a branch and
not a git remote**. Nothing in this repository points at the fork's history, so
"has upstream moved?" cannot be answered by `git log` here. Ask instead:

```bash
rake legacy:pin                                        # what we are pinned to
rake legacy:whatsnew                                   # what has landed since, on nrcan
LEGACY_FORK=/path/to/openstudio-standards rake legacy:whatsnew   # instant, offline
BRANCH=develop rake legacy:whatsnew                    # a different fork branch
```

`legacy:whatsnew` lists the commits between the pin and the fork branch and
groups every changed path by the gem that should care, so you can judge what is
worth absorbing. Absorbing means **bumping the pin and re-running the gates** —
never copying code across. With no local checkout it fetches a blobless mirror
under `tmp/` (first run only; GitHub honours the blob filter, a local `file://` path does not — prefer `LEGACY_FORK`).

Install the oracle once (it defaults to cloning the fork from GitHub — a
multi-gigabyte, one-time cost):

```bash
BUNDLE_GEMFILE=legacy_pin/Gemfile bundle install
```

If you already have the fork checked out locally, point at it instead — bundler
git-clones from the path, which is far faster and works offline. Use the **same**
`LEGACY_PIN_REMOTE` for install and for every run: it is part of the resolved
lockfile, so changing it re-resolves and re-clones.

```bash
cd openstudio-loads
LEGACY_PIN_REQUIRED=1 \
LEGACY_PIN_REMOTE=/path/to/openstudio-standards \
BUNDLE_GEMFILE=../legacy_pin/Gemfile \
  bundle exec ruby test/test_apply_parity.rb
```

`LEGACY_PIN_REQUIRED=1` turns "oracle not bundled" from a skip into a failure —
CI and verification runs should always set it, because a skipped parity gate is a
green-but-vacuous gate. The eleven gates live in openstudio-envelope (4),
openstudio-loads (3), openstudio-lighting (3) and openstudio-shw (1).

## History

These gems were developed inside a fork of
[openstudio-standards](https://github.com/NatLabRockies/openstudio-standards)
between July and August 2026 and extracted here with their full history intact.
The fork remains the source of the pinned parity oracle.
