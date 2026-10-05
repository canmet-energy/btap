"""Run a mutation matrix in PARALLEL, each mutant in its own shadow package.

WHY THIS EXISTS. A mutation matrix is the acceptance discipline for every gate
in this repository: change the rule, watch the test fail. But run serially it
is the most expensive thing in the development loop — N+2 full suite runs, one
after another. Measured on this host: `tests/simulation/` is 61 s, so a
five-mutation matrix costs about six minutes, and this session spent roughly
forty minutes that way.

HOW IT PARALLELISES WITHOUT COPYING A VENV. Each mutant needs its own source
tree, because each one edits the same file differently. It does NOT need its
own virtualenv: a 15 MB copy of `btap/` becomes the subprocess's CWD, and
`python -m pytest` puts the CWD at the FRONT of `sys.path` — ahead of the
venv's editable install and ahead of `PYTHONPATH`.

THE MECHANISM IS THE CWD, NOT `PYTHONPATH`, and this docstring previously
said the opposite. Measured:

    cwd=/tmp/ppA  PYTHONPATH=/tmp/ppB  ->  btap.WHO == 'A'

`PYTHONPATH` is set as well, but it is belt-and-braces; removing `cwd=root`
on the authority of the old wording would restore the silent inertness
described below, where no mutant was ever imported (Fable, PR #81 N4).

THE RAM CEILING, which is the reason this is capped rather than `-n auto`.
One run peaks at 438 MB RSS. The devcontainer sees every host core, and the
2026-09-08 incident was three `-n auto` runs (~150 SDK-loaded workers) plus
two EnergyPlus runs taking down a 32 GB VM. So concurrency here is a small
fixed number, checked against free memory at start, and each child is a
SINGLE process — never `-n auto`. At the default of 6 that is 2.6 GB, about
14% of what was free when this was written.

Usage:
    python3 python/scripts/mutate.py matrix.json [-j 6]

where matrix.json is:
    {"target": "btap/simulation/backends.py",
     "tests":  ["tests/simulation/"],
     "mutations": [{"label": "...", "old": "...", "new": "..."}]}

WHAT A MUTATION CAN AND CANNOT REACH. A mutant is visible only to tests that
IMPORT the target. A test that reads product source BY PATH reads the REAL
tree, because `tests/` is a symlink and `Path(__file__).resolve()` walks out
of the mutant directory — so such a test scans unmutated files and the row
reports SURVIVED. That is a harness limitation wearing the costume of a
coverage finding, which is the same conflation this tool is careful to avoid
for broken anchors. In this repository it affects at least
`test_no_legacy_namespace.py`, `test_decisions_gate_is_path_unfiltered.py`,
`test_coverage_code_refs.py`, `test_citation_no_loss.py` and the decisions
sync/generator modules. Copying `tests/` instead of symlinking does not help
— `parents[2]` then lands outside a git tree and the test fails for a third
reason — so the footer SAYS SO instead (Fable, PR #81 N1).

VERDICTS ARE THREE, NOT TWO, which is the heart of this tool's honesty.
"SURVIVED" only means nothing failed; it cannot see a row that fails for the
WRONG REASON. A real example: a #77 row labelled "counts computed before the
substitution" kept reporting a failure after a later fix made the bug it
named impossible — it had been validated against the pre-fix code and was
crediting a rule it no longer tested. So a mutation may DECLARE the test ids
that must fail, and a row whose declared test does not fail is reported as
CAUGHT BY SOMETHING ELSE rather than counted as a success. That also catches
an inert mutation, which cannot produce its declared failure.

Exit status is 0 only if every mutation was CAUGHT — by its declared test
where one is declared — and the unmutated baseline PASSED. A survivor, a
broken anchor, and a row caught by something else are all findings.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parents[1]
#: Measured peak RSS of one `tests/simulation/` run, used for the headroom
#: check. Deliberately generous.
PER_RUN_MB = 600


def available_mb() -> int | None:
    """Free memory, or None where it cannot be read (then skip the check)."""
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


def build_mutant(work: Path, index: int, target: str, old: str, new: str):
    """A shadow package dir with exactly one substitution applied.

    Returns the dir, or raises if the anchor is not unique — an anchor that
    matches zero or several places is a broken mutation, not a surviving one,
    and the two must never be confused.
    """
    root = work / f"mut{index}"
    root.mkdir(parents=True)
    shutil.copytree(PYTHON_ROOT / "btap", root / "btap",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # THE TARGET MUST STAY INSIDE THE COPIED PACKAGE. `target` was trusted,
    # and `tests/` in the shadow is a SYMLINK to the real checkout — so
    # `target="tests/.../x"` or an absolute path wrote to the REAL tree.
    # Reproduced: a file outside the shadow went from ORIGINAL to CHANGED. A
    # matrix typo must not overwrite a collaborator's source (Sol, PR #81).
    # Checked AFTER the copytree and BEFORE any read, with `resolve()` so a
    # symlink or `..` cannot smuggle a path past `is_relative_to`.
    if Path(target).is_absolute():
        raise ValueError(f"target must be relative to python/, got {target!r}")
    resolved = (root / target).resolve()
    package = (root / "btap").resolve()
    if not resolved.is_relative_to(package):
        raise ValueError(
            f"target {target!r} resolves to {resolved}, outside the mutant's "
            f"own btap/ — refusing to touch anything but the copied package")
    # The mutant runs with cwd=root, because `python -m pytest` puts CWD at the
    # FRONT of sys.path — ahead of PYTHONPATH. Setting PYTHONPATH alone left
    # the real `btap` winning from the repository's own python/ directory, and
    # every mutation reported SURVIVED while the mutated code was never
    # imported. (Same sys.path subtlety as the freeze-recipe trap, inverted.)
    # So the mutant dir needs everything pytest resolves relatively: the tests
    # themselves and the pytest configuration, symlinked rather than copied.
    for name in ("tests", "pyproject.toml", "pytest.ini", "setup.cfg",
                 "conftest.py"):
        source = PYTHON_ROOT / name
        if source.exists():
            (root / name).symlink_to(source)
    # `target` is relative to python/, e.g. btap/simulation/backends.py
    path = resolved
    text = path.read_text(encoding="utf-8")
    if new == old:
        # An inert mutation is a broken mutation, not evidence about the
        # tests. It changes nothing, so the suite passes, so it reports
        # SURVIVED and looks exactly like a coverage gap — the mistake that
        # cost a round on #77 (Fable, PR #81 N2). The SEMANTIC version of
        # this (`x if True else y`) is caught by `expect_failures` instead,
        # since an inert change cannot produce a declared failure.
        raise ValueError("`new` is identical to `old` — an inert mutation "
                         "proves nothing and would report SURVIVED")
    hits = text.count(old)
    if hits != 1:
        raise ValueError(f"anchor matches {hits} times, needs exactly 1")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return root


def run_suite(root: Path | None, tests: list[str], timeout: int):
    """One pytest run, in a single process. Never `-n auto` — see the docstring.

    `root` is the mutant directory, which becomes the CWD so its `btap` leads
    sys.path; None runs the unmutated baseline from the real tree.
    """
    cwd = root or PYTHON_ROOT
    env = dict(os.environ)
    env["PYTHONPATH"] = str(cwd)       # belt as well as braces
    env.pop("PYTEST_ADDOPTS", None)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly",
         "--color=no", "-p", "no:cacheprovider", *tests],
        capture_output=True, text=True, cwd=str(cwd),
        env=env, timeout=timeout)
    lines = proc.stdout.strip().split("\n")
    summary = [ln for ln in lines
               if "passed" in ln or "failed" in ln or "error" in ln.lower()]
    # pytest -q already prints the short summary, so the ids are a PARSE
    # rather than a second invocation.
    #
    # `SUBFAILED` MATTERS AS MUCH AS `FAILED`. With `pytest-subtests` a
    # failing subTest prints `SUBFAILED(state='x') path::test` — a different
    # prefix AND a parenthetical before the id. Matching only `FAILED ` made
    # every subtest-driven row report an empty failure set, so an honest row
    # was misreported as CAUGHT BY SOMETHING ELSE. This repository's predicate
    # tables are nearly all subTests, so that was most of them. The id is
    # taken as the first token containing `::` rather than by position, which
    # survives the parenthetical and any future prefix.
    failed, errored = set(), set()
    for line in lines:
        bucket = (failed if line.startswith(("FAILED", "SUBFAIL"))
                  else errored if line.startswith("ERROR") else None)
        if bucket is None:
            continue
        for token in line.split():
            if "::" in token:
                bucket.add(token)
                break
            # a collection error names a FILE, not a node id
            if token.endswith(".py"):
                bucket.add(token)
                break
    return (proc.returncode, (summary[-1] if summary else "(no summary)"),
            failed, errored)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("matrix", help="JSON file describing the mutations")
    ap.add_argument("-j", "--jobs", type=int, default=6,
                    help="concurrent mutants (default 6; RAM-checked)")
    ap.add_argument("--timeout", type=int, default=1800)
    opts = ap.parse_args(argv)

    spec = json.loads(Path(opts.matrix).read_text(encoding="utf-8"))
    target, tests = spec["target"], spec["tests"]
    mutations = spec["mutations"]

    free = available_mb()
    if free is not None:
        needed = opts.jobs * PER_RUN_MB
        print(f"  memory: {free} MB available, {needed} MB for -j{opts.jobs} "
              f"({needed / free * 100:.0f}%)")
        if needed > free * 0.6:
            safe = max(1, int(free * 0.6) // PER_RUN_MB)
            print(f"  REFUSING -j{opts.jobs}: that is over 60% of free memory. "
                  f"Use -j{safe} or fewer. The 32 GB VM died on 2026-09-08 "
                  "from exactly this.")
            return 2

    t0 = time.time()
    print(f"  baseline (unmutated, {len(tests)} path(s))...", flush=True)
    rc, summary, _, _ = run_suite(None, tests, opts.timeout)
    print(f"    {'PASS' if rc == 0 else 'FAIL'}  {summary}")
    if rc != 0:
        print("  baseline FAILED — fix that before mutating; every mutation "
              "would 'fail' for the wrong reason.")
        return 2

    results = []
    with tempfile.TemporaryDirectory(prefix="mutate-") as tmp:
        work = Path(tmp)
        built, broken = [], []
        for i, m in enumerate(mutations):
            try:
                built.append((m["label"],
                              build_mutant(work, i, target, m["old"], m["new"])))
            except (ValueError, KeyError, OSError) as error:
                broken.append((m.get("label", f"#{i}"), str(error)))

        print(f"  {len(built)} mutant(s) prepared, -j{opts.jobs}", flush=True)
        with concurrent.futures.ThreadPoolExecutor(opts.jobs) as pool:
            futures = {
                pool.submit(run_suite, root, tests, opts.timeout): label
                for label, root in built
            }
            for future in concurrent.futures.as_completed(futures):
                label = futures[future]
                try:
                    rc, summary, failed, errored = future.result()
                except Exception as error:  # noqa: BLE001
                    results.append((label, None,
                                    f"{type(error).__name__}: {error}",
                                    set(), set()))
                    continue
                results.append((label, rc, summary, failed, errored))

    width = max((len(r[0]) for r in results), default=10)
    expected = {m["label"]: m.get("expect_failures") or []
                for m in mutations if "label" in m}
    survived, mislabelled, errors, unviable = [], [], [], []
    by_failures = {}
    for label, rc, summary, failed, errored in sorted(results):
        want = expected.get(label) or []
        if rc is None:
            # A timeout or an exception running the mutant. This used to print
            # ERROR and then be omitted from the exit condition, so a hanging
            # mutant exited 0 (Sol, PR #81).
            verdict = "*** ERROR ***"
            errors.append(label)
        elif rc == 0:
            verdict = "*** SURVIVED ***"
            survived.append(label)
        elif not failed:
            # NONZERO EXIT IS NOT A CATCH. A mutant that fails to IMPORT gives
            # "1 error during collection" — nonzero, but no assertion ever saw
            # the mutant, so the gate discriminated nothing. This was reported
            # as `caught` and exited 0 (Sol, PR #81). A catch REQUIRES a failed
            # test; a usage error, a collection error and "no tests collected"
            # are broken runs.
            verdict = "*** UNVIABLE (no test failed) ***"
            unviable.append((label, sorted(errored)[:2] or f"exit {rc}"))
        elif want and not any(
                any(w in f for f in failed) for w in want):
            # The suite failed, but NOT where the row says it should. The row
            # is crediting a rule it did not test — the stale-row signal that
            # "SURVIVED vs caught" cannot see (Fable, PR #81 N3).
            verdict = "*** CAUGHT BY SOMETHING ELSE ***"
            mislabelled.append((label, want, sorted(failed)[:3]))
        else:
            verdict = "caught (as declared)" if want else "caught"
        print(f"  {label:{width}}  {verdict:34} {summary}")
        if rc not in (None, 0) and failed:
            by_failures.setdefault(frozenset(failed), []).append(label)
    for label, why in broken:
        print(f"  {label:{width}}  {'BROKEN':30} {why}")

    for labels in by_failures.values():
        if len(labels) > 1:
            print(f"  NOTE: identical failing-test sets — {', '.join(labels)}"
                  "\n        at least one is probably not discriminating what "
                  "its label claims")
    for label, want, got in mislabelled:
        print(f"  {label}: declared {want}, got {got}")

    serial = (len(built) + 1) * 61
    print(f"\n  {time.time() - t0:.0f}s wall for {len(built)} mutation(s) "
          f"+ baseline (serial would be ~{serial}s)")
    if survived:
        print(f"  {len(survived)} SURVIVED — the tests do not pin: "
              f"{', '.join(survived)}")
    if mislabelled:
        print(f"  {len(mislabelled)} CAUGHT BY SOMETHING ELSE — the row's "
              "declared test did not fail, so it credits a rule it did not "
              "test")
    if unviable:
        print(f"  {len(unviable)} UNVIABLE — the suite exited nonzero but no "
              "test failed, so nothing tested the mutant:")
        for label, why in unviable:
            print(f"      {label}: {why}")
    if errors:
        print(f"  {len(errors)} ERROR — the mutant could not be run: "
              f"{', '.join(errors)}")
    if broken:
        print(f"  {len(broken)} broken mutation(s) — neither caught nor "
              "survived")
    if not any(expected.values()):
        print("  NOTE: no row declared `expect_failures`, so a row that fails "
              "for the WRONG reason cannot be distinguished from one that "
              "works")
    print("  NOTE: a mutation reaches only tests that IMPORT the target; a "
          "test reading product source BY PATH reads the real tree")
    return 1 if (survived or broken or mislabelled
                 or errors or unviable) else 0


if __name__ == "__main__":
    sys.exit(main())
