# D-80 retirement plan review — Rev 4

**Date:** 2026-08-28  
**Reviewed repository revision:** `7c6f6ae` (`main`)  
**Reviewed plan:** D-80 Rev 4, Python-vs-oracle direct verification and the
btap-gem retirement path  
**Immediate scope:** R1 + R2 only

This is the durable review record for Claude and future implementers. It
supersedes the three conversational reviews that produced Rev 4. The detailed
migration history remains in `PORT_STATUS.md` and D-79.

## Verdict

**Rev 4 is architecturally ready. R1 and R2 can proceed.** The earlier structural
blockers are resolved: permanent verification assets move out of gem ownership;
the request inventory is independent and recursive; live oracle output is
checked against both Python and committed goldens; Leg A remains throughout the
Ruby support window; the current installer defect is fixed immediately; and a
pipeline-level successor to Leg B is frozen before Ruby deletion.

The items below are execution details that should be incorporated while
implementing R1/R2. Findings 1–5 affect acceptance claims and should be treated
as required, not optional cleanup. Findings 6–10 tighten maintainability and the
later R4–R6 handoff.

## Required findings

### 1. Require a real sizing generator matrix

R2.3 specifies all four generator/CLI cells at tier `none`, but only the two
same-generator diagonal cells at `sizing`. Diagonal runs cannot distinguish a
generator difference from a CLI difference.

For the three-model sizing subset, require all four combinations:

| Corpus | Ruby CLI | Python CLI |
|---|---:|---:|
| Ruby-generated | required | required |
| Python-generated | required | required |

Compare each CLI across generators and compare both CLIs on each corpus. If the
full four-cell sizing run is rejected for cost, define the reduced matrix
explicitly: one CLI must run both generated corpora, and both CLIs must still
run a common corpus. Do not leave acceptance as "where practical."

### 2. Record and enforce source provenance

`prep_manifest.json` records a Git SHA, but a SHA does not identify uncommitted
changes used to generate canonical goldens. Record:

- commit SHA;
- dirty/clean state;
- SHA-256 of `oracle_prep.py`;
- SHA-256 of `request_manifest.json`;
- seed-model SHA-256;
- OpenStudio SDK version and build SHA as separate fields.

Canonical committed-golden export must refuse a dirty source tree unless an
explicit development override is supplied. Temporary live verification may run
dirty, but its manifest must say so.

### 3. Specify portable atomic publication

A direct rename cannot portably replace an existing non-empty directory. For a
canonical re-export:

1. Write every result into a unique sibling temporary directory.
2. Validate the exact recursive inventory and exact expected file set.
3. Compute checksums and write `manifest.json` last.
4. Rename the current destination to a unique backup.
5. Rename the completed temporary directory into place.
6. Delete the backup only after successful promotion.
7. Restore the backup if promotion fails.

Ordinary live verification should always target a fresh temporary directory and
avoid replacement entirely.

### 4. Define golden override failure semantics

The shared golden-directory resolver runs during test import/collection, where
there may be no `unittest.TestCase` to "flunk." Use these rules:

- No override: read committed goldens.
- Valid explicit `BTAP_ORACLE_GOLDENS`: read exactly that directory.
- Invalid explicit override: always fail collection with a clear configuration
  error; never fall back to committed files.
- `BTAP_GOLDENS_REQUIRED=1`: missing files, malformed JSON, incomplete
  manifests, or unreadable paths are hard failures naming the path and remedy.

This prevents a misspelled live-export path from quietly testing the frozen
fast path.

### 5. Give generated sample consumers Python-owned paths

`test_reference_rules.py` currently reads generated samples under
`packaging/windows/samples`, another cross-tree dependency beyond the proposed
oracle/cross-language exceptions. Generate the Python sample corpus into a
Python-owned temporary or fixture directory and inject that location into the
test. If this is temporarily impossible, list the test as a named integration
exception with its retirement phase; do not make `packaging/windows` a permanent
allowlist entry.

## Additional findings

### 6. Declare registry authority

Rev 4 correctly records the existing registry defect: the Python copy has 78
entries and is missing D-79 while the Ruby copy has 79. Repair D-79 first, then
add D-80 and enforce byte identity.

Also state the repair direction:

- Ruby registry is authoritative through the Ruby support window.
- Python registry becomes authoritative at the primacy/retirement boundary
  selected by D-80.

The equivalence test detects drift; the authority rule tells maintainers which
side to repair.

### 7. Type every recursive list in the request manifest

For each list path, declare one comparison mode:

- `ordered`: compare recursively by index;
- `keyed`: compare by a specified stable field;
- `set`: canonicalize and compare membership.

Lengths alone catch shrinkage but can accidentally make incidental oracle
iteration order permanent, or hide an ordering contract that actually matters.

### 8. Reject extra export files

Completeness means exact equality in both directions. Before publication, assert
that the exporter produced exactly the expected JSON group set plus the
manifest. Unexpected files are failures, not harmless extras, because they may
be obsolete groups with valid checksums and no consumer.

### 9. Freeze CLI streams in R4 failure scenarios

Exit status and JSON artifacts do not fully capture usage, preflight, simulation
and internal-error behavior. R4's scenario manifest should retain normalized
stdout/stderr or required diagnostic fragments for exits 2–6, especially:

- actionable usage and missing-file messages;
- preflight repair guidance;
- simulation severe/fatal context;
- partial-audit location after failure;
- the `--quick` no-determination warning.

### 10. Preserve old command paths deliberately

Moving exporter/probe files will strand developer commands and historical
instructions. During the Ruby support window, leave small forwarding wrappers
at old script entry points, or fail there with a message naming the replacement
command. A generic missing-file failure is not an acceptable migration path.

## Rev 4 strengths

Rev 4 successfully incorporates the prior reviews:

- The historical TBD RSI probe keeps SDK-order `Surface 8`; sorted
  canonicalization is deferred to a separate adjudicated change.
- Existing D-79 registry drift is acknowledged rather than hidden.
- Probe requests come from an implementation-independent manifest.
- Recursive inventory protects nested values and list lengths.
- Fresh oracle output is compared to both Python and committed goldens.
- Export publication is completeness-gated and atomic.
- OpenStudio identity mismatch is a hard failure with an explicit rebaseline
  override.
- Leg A remains until the Ruby product is retired at R6.
- The supported Ruby installer staging defect is fixed during R1.
- Sample generation becomes fail-fast with an exact slug and run-count contract.
- Generator and CLI variables are separated with a matrix design.
- R4 freezes successful and failing pipeline behavior before Ruby disappears.
- R5 begins with an installer architecture decision rather than assuming the
  OpenStudio Python tree and embedded CPython are interchangeable.
- R6 retains only the pinned Ruby oracle infrastructure.

## Acceptance clarifications

The three independence negative controls should target the three inventory
assertions independently:

1. Remove one Python schedule: Python-versus-request fails.
2. Remove one fresh-oracle key: fresh-export-versus-request fails.
3. Remove one committed-golden key: committed-versus-request fails.

Other defenses may also fail in controls 2 and 3, particularly the
fresh-versus-committed comparator and checksum verification. That is expected
defense in depth; the assertion is that the inventory layer identifies the
correct side independently.

The live Leg-C orchestrator should list its five test files explicitly. At the
reviewed revision, `pytest --collect-only -q -k oracle_goldens` finds 22 tests,
but the expected file list and collection count should live in
`request_manifest.json`, not as an unrelated shell literal. A dedicated test
must prove every requested golden group has at least one consumer.

Fixture copy drift checks must cover all five files explicitly: EPW, DDY, STAT,
`system_simulation_status.json`, and `reference_selection_matrix.json`. Ruby is
authoritative until R6; at R6 the cross-tree comparison is removed and the
Python fixture hashes become authoritative.

## Final recommendation

Proceed with R1 and R2 after folding findings 1–5 into the implementation
checklist. Keep R3–R6 behind their separate go-aheads. The architecture no
longer needs another redesign; the remaining work is to ensure the new permanent
verification stack proves exactly what its documentation claims and fails
loudly when its inputs, inventory, or provenance are incomplete.
