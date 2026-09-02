# Leg-C oracle goldens (D-78)

Frozen oracle-side values — every quantity the eleven parity gates compare,
exported from the PINNED openstudio-standards revision (`legacy_pin/REF`,
recorded in `manifest.json`) by the GEM-FREE `../export_goldens.rb` (D-80:
python-prep / ruby-probe — prep models come from
`python/scripts/oracle_prep.py`, probe requests from
`../request_manifest.json`) via the same probe code the gates run
(`../oracle_probes.rb`).

**Contract for the Python port**: Python tests consume EXACTLY these files,
with the gates' tolerance table — giving Python ≡ oracle *directly*, so a
bug faithfully ported from Ruby fails here even when Ruby↔Python agree
(Leg B) and Ruby↔oracle agree (Leg A).

**Currency is enforced twice**: `python/tests/necb/test_oracle_goldens_current.py`
asserts `manifest.legacy_ref == legacy_pin/REF`, the checksums, the exact
file set, and the request-manifest recursive inventory; the parity job's
`verification/live_leg_c.sh` re-exports fresh from the live oracle and
`compare_goldens.py` proves these committed files match it. Bumping the pin
without re-exporting fails CI loudly.

**Regenerating** (the pin bundle lives on the parity runner):

```bash
gh workflow run test.yml --ref <branch> -f export_goldens=true
gh run download <run-id> -n oracle-goldens -D verification/oracle/goldens
git add verification/oracle/goldens && git commit
```

Never edit these files by hand — the manifest checksums are asserted.
The costing dollars were priced from the vendored PLACEHOLDER tables;
licensed RS-Means values are runtime-injected only and never frozen.
