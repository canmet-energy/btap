# legacy_pin — the parity oracle, pinned

The `openstudio-*` gem family's parity suites compare against the legacy
NECB/BTAP implementation in **this fork** of openstudio-standards. This
directory pins that oracle to ONE git revision, so the comparison target is
explicit and reproducible instead of "whatever the working tree holds".

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

That matters for one test: `test_legacy_archetype_e2e.rb` gates on
`bundle check`, so with a mismatched remote it SKIPS rather than running. It
skips loudly and never reports a false pass — but if you expected it to run,
this is why. Run `bundle install` once with your chosen `LEGACY_PIN_REMOTE` and
keep using that same value.

## Running a parity suite against the pin

```bash
BUNDLE_GEMFILE=../legacy_pin/Gemfile \
  bundle exec ruby test/test_shw_parity.rb
```

Set `LEGACY_PIN_REQUIRED=1` to turn "oracle not bundled" from a skip into a
FAILURE (CI and verification runs should always set it — a skipped parity
gate is a green-but-vacuous gate).

## Bumping the pin (absorbing upstream)

1. Edit `REF` to the new fork revision (full SHA).
2. `BUNDLE_GEMFILE=legacy_pin/Gemfile bundle install` (re-resolves the git
   source; refresh the lock).
3. Run ALL parity suites with `LEGACY_PIN_REQUIRED=1` plus the archetype
   regeneration gates. Flipped assertions = the upstream change reached a
   compared behavior — attribute every one (the D-68 discipline) before
   accepting.
4. Commit `REF` + `Gemfile.lock` together with the attribution notes and
   any gem-side flips.

## Remotes

The gems have now moved to their own repository, so the oracle is no longer a
parent directory. The default remote is therefore the fork's URL,
`https://github.com/NatLabRockies/openstudio-standards.git` — the first install
clones its full history, a one-time cost measured in gigabytes.

If you have the fork checked out locally, point at it instead. Bundler
git-clones from the local path, which is far faster and works offline:

```bash
LEGACY_PIN_REMOTE=/path/to/openstudio-standards \
BUNDLE_GEMFILE=../legacy_pin/Gemfile bundle install
```

**Never** point the pin at the published `openstudio-standards` RubyGems
release: that is NREL's release line and does not carry this fork's
NECB/BTAP state.
