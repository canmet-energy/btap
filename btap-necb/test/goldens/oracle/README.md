# Leg-C oracle goldens (D-78)

Frozen oracle-side values — every quantity the eleven parity gates compare,
exported from the PINNED openstudio-standards revision (`legacy_pin/REF`,
recorded in `manifest.json`) by `scripts/export_oracle_goldens.rb` via the
same probe code the gates run (`test/support/oracle_probes.rb`).

**Contract for the Python port**: Python tests consume EXACTLY these files,
with the gates' tolerance table — giving Python ≡ oracle *directly*, so a
bug faithfully ported from Ruby fails here even when Ruby↔Python agree
(Leg B) and Ruby↔oracle agree (Leg A).

**Currency is enforced**: `test/test_oracle_goldens_current.rb` (in the
parity job) re-runs a live subset of the probes against these files and
asserts `manifest.legacy_ref == legacy_pin/REF`. Bumping the pin without
re-exporting fails CI loudly.

**Regenerating** (the pin bundle lives on the parity runner):

```bash
gh workflow run test.yml --ref <branch> -f export_goldens=true
gh run download <run-id> -n oracle-goldens -D btap-necb/test/goldens/oracle
git add btap-necb/test/goldens/oracle && git commit
```

Never edit these files by hand — the manifest checksums are asserted.
The costing dollars were priced from the vendored PLACEHOLDER tables;
licensed RS-Means values are runtime-injected only and never frozen.
