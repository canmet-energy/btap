"""Run a mutation matrix in PARALLEL, each mutant in its own shadow package.

WHY THIS EXISTS. A mutation matrix is the acceptance discipline for every gate
in this repository: change the rule, watch the test fail. But run serially it
is the most expensive thing in the development loop — N+2 full suite runs, one
after another. Measured on this host: `tests/simulation/` is 61 s, so a
five-mutation matrix costs about six minutes, and this session spent roughly
forty minutes that way.

HOW IT PARALLELISES WITHOUT COPYING A VENV. Each mutant needs its own source
tree, because each one edits the same file differently. It does NOT need its
own virtualenv: `PYTHONPATH` takes precedence over the venv's editable
install, so a 15 MB copy of `btap/` placed on `PYTHONPATH` shadows the
installed package completely. That is the same resolution order that made the
freeze-recipe trap possible — `$PY script.py` resolves `btap` through the
editable finder unless `PYTHONPATH` says otherwise — used deliberately here.

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

Exit status is 0 only if every mutation was CAUGHT (the suite failed for it)
and the unmutated baseline PASSED. A mutation that survives is the finding.
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
    path = root / target
    text = path.read_text(encoding="utf-8")
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
    summary = [ln for ln in proc.stdout.strip().split("\n")
               if "passed" in ln or "failed" in ln or "error" in ln.lower()]
    return proc.returncode, (summary[-1] if summary else "(no summary)")


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
    rc, summary = run_suite(None, tests, opts.timeout)
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
                    rc, summary = future.result()
                except Exception as error:  # noqa: BLE001
                    results.append((label, None, f"{type(error).__name__}: {error}"))
                    continue
                results.append((label, rc, summary))

    width = max((len(r[0]) for r in results), default=10)
    survived = []
    for label, rc, summary in sorted(results):
        if rc is None:
            verdict = "ERROR"
        elif rc == 0:
            verdict = "*** SURVIVED ***"
            survived.append(label)
        else:
            verdict = "caught"
        print(f"  {label:{width}}  {verdict:16} {summary}")
    for label, why in broken:
        print(f"  {label:{width}}  BROKEN ANCHOR    {why}")

    serial = (len(built) + 1) * 61
    print(f"\n  {time.time() - t0:.0f}s wall for {len(built)} mutation(s) "
          f"+ baseline (serial would be ~{serial}s)")
    if survived:
        print(f"  {len(survived)} SURVIVED — the tests do not pin: "
              f"{', '.join(survived)}")
    if broken:
        print(f"  {len(broken)} broken anchor(s) — neither caught nor survived")
    return 1 if (survived or broken) else 0


if __name__ == "__main__":
    sys.exit(main())
