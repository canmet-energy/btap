# legacy_pin — the parity oracle, pinned

Python verification compares against the legacy NECB/BTAP implementation in a
fork of `openstudio-standards`. This directory pins that external oracle to one
git revision, so the target is explicit and reproducible. It survived the D-84
retirement of the five product Ruby gems; it is not product code.

- `REF` — the full SHA of the pinned oracle revision. **The single source
  of truth**: the Gemfile reads it, and the archetype-generation cache keys
  derive from it.
- `Gemfile` / `Gemfile.lock` — bundler wiring. The lock is COMMITTED
  (tbd/osut/topolys resolved reproducibly). `.bundle/config` shares the
  repo's `vendor/bundle`.

**The lock records a REMOTE, and bundler compares it to the one the Gemfile
computes.** The committed value is the canonical fork URL, so a default
checkout and CI agree and the CI cache is usable. Point `LEGACY_PIN_REMOTE` at
a local checkout and the two disagree: bundler re-resolves on
`bundle install` (fine, and it rewrites your local lock — do not commit that),
but until you do, `bundle check` reports the source "not yet checked out".

The Python whole-building archetype test and live Leg-C harness both gate on
`bundle check`. With a mismatched remote they cannot run. Install once with
your chosen `LEGACY_PIN_REMOTE` and keep using that same value.

## Install the oracle

```bash
BUNDLE_GEMFILE=legacy_pin/Gemfile bundle install
```

With a local checkout:

```bash
LEGACY_PIN_REMOTE=/path/to/openstudio-standards \
BUNDLE_GEMFILE=legacy_pin/Gemfile bundle install
```

## Run Python against the pin

From the repository root, with a prepared Python environment:

```bash
LEGACY_PIN_REQUIRED=1 \
BUNDLE_GEMFILE="$PWD/legacy_pin/Gemfile" \
PYTHONPATH="$PWD/python:/usr/local/openstudio-3.11.0/Python" \
BTAP_PYTHON="$PWD/python/.venv/bin/python" \
   bash verification/live_leg_c.sh /tmp/live-leg-c

LEGACY_PIN_REQUIRED=1 \
BUNDLE_GEMFILE="$PWD/legacy_pin/Gemfile" \
PYTHONPATH="$PWD/python:/usr/local/openstudio-3.11.0/Python" \
BTAP_ENERGYPLUS=/usr/local/openstudio-3.11.0/EnergyPlus/energyplus \
   python/.venv/bin/pytest -q python/tests/necb/test_legacy_archetype_e2e.py
```

`LEGACY_PIN_REQUIRED=1` turns an unavailable oracle into failure instead of a
vacuous skip. CI sets it in the dispatch-only `parity` job.

## Bumping the pin (absorbing upstream)

1. Edit `REF` to the new fork revision (full SHA).
2. `BUNDLE_GEMFILE=legacy_pin/Gemfile bundle install` (re-resolves the git
   source; refresh the lock).
3. Run live Leg C and the whole-building archetype gate with
   `LEGACY_PIN_REQUIRED=1`. Attribute every changed comparison before accepting.
4. **Re-export the Leg-C oracle goldens** (D-78): dispatch `test.yml` with
   `export_goldens=true`, download the `oracle-goldens` artifact into
   `verification/oracle/goldens/`, and commit it with the bump. The currentness
   tests fail until the manifest's `legacy_ref` matches the new `REF`.
5. Commit `REF`, `Gemfile.lock`, goldens, and attribution notes together.

## Remotes

The default remote is the fork's URL,
`https://github.com/NatLabRockies/openstudio-standards.git` — the first install
clones its full history, a one-time cost measured in gigabytes.

If you have the fork checked out locally, point at it instead. Bundler
git-clones from the local path, which is far faster and works offline:

```bash
LEGACY_PIN_REMOTE=/path/to/openstudio-standards \
BUNDLE_GEMFILE=legacy_pin/Gemfile bundle install
```

**Never** point the pin at the published `openstudio-standards` RubyGems
release: that is NREL's release line and does not carry this fork's
NECB/BTAP state.
