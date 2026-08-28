# Python port review: M6 completion and M7 plan

**Date:** 2026-08-28  
**Reviewed branch:** `python-m6-umbrella`  
**Reviewed revision:** `d392cbb8b74cccf96e3133784a9f11646ba6ce6e`  
**M5 baseline:** `338559b157b08a18a90a6979249b02b39af4c6c4`  
**Scope:** M6 umbrella implementation and verification, plus the proposed M7
thermal-bridging integration.

This review supersedes an initial M7 assessment that assumed no native Python
TBD implementation existed. The public
[`canmet-energy/py-tbd`](https://github.com/canmet-energy/py-tbd) project is a
feature-complete Python port of the Ruby TBD engine. M7 should integrate it
directly; it should not build an OpenStudio/Ruby subprocess bridge.

## Executive verdict

**M6 is complete and ready to merge.** Its umbrella pipeline, report renderer,
CLI, installed-wheel gate and cross-language corpus gate form a coherent
delivery. The three concrete defects found during review were fixed in
`67d4e81`, with Ruby-first changes where the behavior was shared and regression
tests on both implementations.

M6's strongest evidence is the Leg-B corpus convergence reported in
[`PORT_STATUS.md`](../../PORT_STATUS.md): Ruby and Python are equivalent for
18/18 `none` runs, 3/3 `sizing` runs and 2/2 `annual --quick` runs. The harness
now checks exit status as well as artifacts, so a CLI that exits before doing
the requested work cannot produce a false pass.

**M7 is viable as a small native adapter, but its dependency baseline must be
decided before implementation.** The btap repository is pinned to Ruby TBD
3.5.2, OSut 0.8.2 and Topolys 0.6.2. Current `py-tbd` ports Ruby TBD 3.6.0 and
requires `osut>=0.9.0`. Those are not interchangeable baselines: this repository
already records a 43% result difference between the two dependency triplets on
the same wall. Installing current `py-tbd` without adjudicating that difference
would violate the D-78/D-79 verification contract.

## Review method

The review inspected the M6 range from `main`/M5 to the reviewed HEAD, including:

- the Python umbrella pipeline, EUI path, tiers, renderer and CLI;
- the eight ported M6 test suites;
- the wheel smoke test and CI wiring;
- the Leg-B corpus runner, differ and comparison specification;
- the Ruby thermal-bridging implementation and its required-dependency gate;
- the Python thermal-bridging placeholder and the two M7-deferred tests;
- `py-tbd` metadata, public API, dependency declarations, upstream pin and
  parity documentation.

Focused M6 lint and tests were run during review. The complete 703-test suite,
full cross-language corpus and dispatch-only annual gate were not independently
rerun; their results and continuous CI wiring were reviewed in the repository.

## M6 assessment

### Delivered surface

M6 adds the user-facing umbrella that was missing after the five NECB rule
domains landed in M5:

- `btap.necb.compliance`: the eleven-phase reference-building pipeline,
  proposed-first annual run, capacity iteration, EUI supplement and output
  finalization;
- `btap.necb.eui_archetypes`: NECB 2025 archetype-EUI applicability,
  normalization and target inputs;
- `btap.necb.tiers`: energy and GHG scoring;
- `btap.necb.report`: the self-contained AHJ report renderer;
- `btap.necb.cli`: command parsing, seven diagnostic exit codes, progress
  reporting and the `btap-compliance` console entry point;
- cross-language corpus execution through the same models and arguments;
- an installed-wheel smoke test that executes outside the checkout.

The implementation follows the repository's governing constraints: the Python
port preserves Ruby behavior, the Ruby product remains the Leg-B baseline, and
shared behavioral fixes land Ruby-first.

### Verification strengths

1. **The assembled product is tested, not only its modules.**
   `verification/run_corpus.rb` invokes both real CLIs and
   `verification/compare_runs.py` compares ordered `audit.json` plus
   `report.json` under the data-driven rules in `verification/spec.json`.

2. **The corpus runner checks that work actually happened.**
   The runner accepts only a successful status or the expected no-determination
   status 6 accompanied by an audit artifact. This closes the earlier sizing
   harness defect where missing weather caused an exit 2 before simulation.

3. **Distribution integrity is explicit.**
   `python/scripts/wheel_smoke.py` builds and installs a wheel into a clean
   virtual environment, runs outside the source tree, checks packaged data,
   performs a real domain operation and verifies that the console script is
   installed.

4. **Expensive claims are wired into CI.**
   The full 97-system M5 reference matrix runs in the container verification
   job. M6's `none` and `sizing` Leg-B tiers run there as well; the more
   expensive `annual --quick` tier runs in the dispatch-only parity job.

5. **Renderer parity has a direct cross-language artifact.**
   Python consumes the Ruby `paired_bars.svg` golden and reproduces it
   byte-for-byte.

### Review findings and disposition

| Severity | Finding | Disposition |
|---|---|---|
| Medium | Selecting the remote backend changed process-global state; a later in-process local run did not reset it. | **Fixed** in `67d4e81`. Local selection explicitly resets the default backend, with a regression test. |
| Medium | `--simulate none` returned from validation before checking supplied `--space-type-map` and `--costs-csv` paths, misclassifying bad input as an internal failure. | **Fixed Ruby-first** in `67d4e81`, with both CLIs tested. |
| Low | `--space-type` translated the OSM twice despite its load-once contract. | **Fixed Ruby-first** in `67d4e81` by memoizing the loaded model, with both implementations tested. |

No remaining merge-blocking M6 defect was identified.

### Residual M6 risks

These are coverage boundaries, not reasons to hold M6:

- The annual Leg-B tier uses a one-week `--quick` period. It exercises annual
  arithmetic, unmet-hours evaluation, reports and the required exit 6, but does
  not prove a full-year CLI returns compliant/non-compliant exit 0/1.
- Three known SDK iterations remain unsorted. They did not diverge on the
  corpus. Per the working agreement, any observed behavior change must be fixed
  Ruby-first and re-baselined rather than silently normalized only in Python.
- Leg C can cover NECB 2020 only because the pinned oracle predates NECB 2025.
  The 2025 implementation therefore rests on adjudicated decisions,
  data-integrity checks and cross-edition tests.

## Corrected M7 architecture

### Native integration

`py-tbd` exposes the Ruby-shaped operation M7 needs:

```python
import tbd

tbd.oslg.clean()
result = tbd.process(model, arguments)
logs = tbd.oslg.logs()
```

The operation mutates the supplied Python OpenStudio model and returns the
familiar `{"io": ..., "surfaces": ...}` structure. This fits the current
in-place contracts in `envelope.prescriptive`, `envelope.reference` and the
compliance pipeline.

M7 therefore does **not** need:

- `openstudio execute_ruby_script`;
- input/output OSM round-tripping;
- temporary files or a JSON subprocess protocol;
- embedded-Ruby discovery;
- subprocess timeouts and exit-code translation;
- Windows shell/path handling for a bridge process.

The existing Python placeholder should become a thin dependency adapter:

1. lazily import `tbd` in `_bridge_available()`;
2. honor `OPENSTUDIO_ENVELOPE_DISABLE_TBD=1` before importing;
3. clear `tbd.oslg` immediately before each operation;
4. call `tbd.process(model, arguments)` directly;
5. return the result without reshaping it;
6. pass the logs from that same call directly into `_record()`;
7. preserve the current loud warning and `False` result only when the optional
   dependency is genuinely unavailable;
8. allow processing failures from an available dependency to abort the run.

Logs should be passed as call-local data. Storing a "last logs" value in module
state would make concurrent calls interfere with each other.

### Blocking baseline decision

The native API resolves the engineering problem, but not the verification
problem.

| Component | Current btap oracle baseline | Current Python project |
|---|---|---|
| TBD | Ruby 3.5.2 | `py-tbd` 3.6.0, upstream `dd6f12f8` |
| OSut | Ruby 0.8.2 | Python `osut>=0.9.0` |
| Topolys | Ruby 0.6.2 | `py-topolys` 0.1.0 |
| OpenStudio | 3.11.0 | OpenStudio Python bindings |

There are two defensible choices.

#### Option A: compatibility release for the existing oracle baseline

Publish or pin a `py-tbd` revision whose behavior is verified against Ruby TBD
3.5.2 with the corresponding OSut/Topolys behavior. This is the preferred M7
scope because it preserves every existing Leg-A and Leg-C baseline.

This does not necessarily require maintaining an old port indefinitely. A
small compatibility release or branch can exist solely to complete D-79
against the frozen oracle, after which a separately adjudicated dependency
upgrade can move both implementations together.

#### Option B: rebaseline the family on TBD 3.6.0

Advance the Ruby dependency triplet first, rerun every affected Leg-A parity
gate, regenerate the oracle goldens, document the behavioral change and only
then integrate current `py-tbd`.

This is valid but substantially broader. It moves the shipping Ruby product and
the oracle relationship while the port is still in progress. It should be a
separate decision, not an incidental consequence of adding a Python dependency.

**Recommendation:** choose Option A for M7. Do not install current `py-tbd`
against the old Ruby baseline and rely on broad tolerances. The known numerical
difference is physical output, not serialization noise.

### Dependency reproducibility

At the time of review, `py-tbd` has no PyPI release or repository tag, and its
`py-topolys` dependency is a Git direct reference. Until both projects publish
immutable releases, btap should pin exact commit SHAs for both repositories.
Depending on `main` would allow the verification baseline to move without a
btap commit.

The final dependency should be declared in `python/pyproject.toml`, included in
the installed-wheel smoke environment, and accompanied by a test that asserts
the expected `tbd.VERSION`, `tbd.UPSTREAM_VERSION` and `tbd.UPSTREAM_SHA`.

## M7 behavior contract

M7 must preserve three distinct states:

1. **Not requested:** retain the existing warning that the model contains
   clear-field values and NECB 3.1.1.7 effective transmittance was not applied.
2. **Requested but dependency unavailable:** return `False` and emit the
   existing loud `NOT accounted` audit warning.
3. **Dependency available:** run `tbd.process`; success mutates the model and
   records the result, while any fatal/error condition that prevents a valid
   result aborts the compliance run. It must not be relabeled as mere
   unavailability.

Every TBD warning at or above the Ruby threshold must be forwarded to the
shared audit with the same action text and `article: '3.1.1.7.'`. In particular,
the fixture's physically infeasible walls must retain the `Unable to uprate`
warning.

## M7 acceptance gates

M7 should not be marked complete until all of the following are continuously
enforced:

1. **Enable the uprate/derate test.**
   Remove the M7 skip from
   `python/tests/necb/test_envelope_thermal_bridging.py`. Assert a decision was
   logged, at least one surface was derated, the roof effective U meets the
   target and the infeasible-wall warning is present.

2. **Add a required-dependency mode.**
   Add `BTAP_TBD_REQUIRED=1`, analogous to `BTAP_SDK_REQUIRED` and
   `BTAP_ENGINE_REQUIRED`. The container verification job must fail rather than
   skip when the selected `py-tbd` baseline is unavailable.

3. **Assert dependency identity.**
   Test the `py-tbd` package version, upstream Ruby SHA/version and dependency
   versions selected by the lock/install process.

4. **Prove direct Ruby/Python process parity for the btap fixture.**
   Compare key sets in both directions and compare at least surface
   `deratable`, `heatloss`, `ratio` and `u`, plus edge type, length, PSI set and
   connected surfaces. Use the D-78 tolerance discipline; do not shrink the
   comparison to values that happen to agree.

5. **Enable the frozen RSI Leg-C gate.**
   Reconstruct the existing oracle probe model, apply thermal bridging and
   compare Python `Quantify.rsi_of` results to every frozen `tbd_rsi` surface
   and subsurface within `1e-6`, with exact key-set equality.

6. **Test the complete reference-envelope sequence.**
   The reference path rebuilds opaque constructions as lightweight assemblies
   after the prescriptive/TBD step. Assert the final post-rebuild reference
   still carries the effective target so a later transform cannot erase the
   uprate while the standalone TBD test remains green.

7. **Add an assembled Leg-B thermal-bridging case.**
   The existing corpus never requests thermal bridging. Add a dedicated
   Ruby-versus-Python fixture or corpus mode that passes `efficient (BETBG)` and
   compares the resulting audit/report. Re-running the unchanged corpus is not
   evidence for M7.

8. **Exercise the installed distribution.**
   Extend the wheel smoke test to import the pinned native dependency and run a
   small real `tbd.process` operation outside the checkout. This catches Git
   dependency, package-data and import-resolution failures that source-tree
   tests cannot see.

9. **Retain negative controls.**
   Keep the disable-environment-variable test and add a malformed/forced-fatal
   process case proving an available but failed engine cannot degrade to the
   clear-field warning path.

10. **Run the existing M6 gates unchanged.**
    M7 must not regress the 18/18 `none`, 3/3 `sizing`, 2/2 `annual --quick`,
    renderer, import-contract or wheel gates.

## Suggested implementation sequence

1. Decide and document Option A versus Option B.
2. Produce immutable `py-tbd` and `py-topolys` dependency references matching
   that decision.
3. Add dependency identity tests and `BTAP_TBD_REQUIRED` before wiring runtime
   behavior; this makes the selected baseline falsifiable immediately.
4. Replace the M7 placeholder with the direct `tbd.process` adapter and
   call-local log forwarding.
5. Enable the standalone uprate/derate and Leg-C RSI tests.
6. Add the post-reference assertion and assembled Leg-B thermal-bridging case.
7. Extend wheel smoke and CI installation.
8. Run the full Python suite, import contracts, Ruff, wheel smoke, Leg-B corpus
   and the affected Ruby/Leg-A gates.
9. Update `PORT_STATUS.md`, D-79 and dependency documentation only after those
   gates pass with no M7 skips.

## Final recommendation

Merge M6 after its current CI gates pass at `d392cbb` or its descendant. Treat
M7 as a native Python dependency integration, not an inter-language bridge.
Before writing runtime code, freeze the exact thermal-bridging baseline; the
choice between compatibility with TBD 3.5.2 and a family-wide move to 3.6.0 is
the one decision that changes the validity and scope of the milestone.
