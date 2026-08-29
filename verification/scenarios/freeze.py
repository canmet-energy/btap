#!/usr/bin/env python3
"""Freeze the R4 scenario baselines (D-80 R4, PR-1 commit 2).

Runs every authored scenario (scenario_defs.py) and publishes
``manifest.json`` + ``baselines/`` — but only after every guarantee holds:

- CLEAN TREE: refuses to run with uncommitted changes (the baselines must
  be reproducible from a commit SHA);
- DETERMINISM: every scenario runs TWICE; 'exact' streams demand identical
  normalized output on both passes — variance forces a declared
  ``fragments`` policy or aborts the freeze;
- THE RUBY SEAL: every ``seal: ruby`` scenario also runs the Ruby CLI with
  mirrored argv and must agree — exit code equal, compare_runs-equivalent
  audit.json/report.json, audit.txt BYTE-identical. ``ruby-api:`` seals
  shell the named driver (ruby_tbd_compliance.rb / audit ruby_reference.rb)
  and compare the same way. ``python-only:<reason>`` is recorded verbatim,
  never silent;
- NON-VACUITY: annual baselines must carry energies + unmet hours; the
  thermal-bridging seal must show a thermal_bridging decision, a derated
  surface, the 3.1.1.7 article, and the infeasible-uprate warning on BOTH
  sides; exit-3's report.json must be the empty object;
- ENV HYGIENE: authored env only; any var named *KEY*/*TOKEN*/*SECRET*
  must carry a ``scenario-`` prefixed dummy;
- ATOMIC PUBLICATION: everything lands in a temp sibling, sha256'd, the
  manifest written last, then promoted — a partial freeze cannot land.

Provenance in the manifest is IMMUTABLE baseline provenance only (freeze
commit, engines, spec hash, seal tally). The validating CI run id is
EXTERNAL attestation (PR body + D-82) — never written here.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import runner
import scenario_defs

REPO_ROOT = runner.REPO_ROOT
RUBY_CLI = REPO_ROOT / "btap-necb" / "exe" / "btap-compliance.rb"
RUBY_TBD_DRIVER = (REPO_ROOT / "python" / "tests" / "necb" / "cross_language"
                   / "ruby_tbd_compliance.rb")
RUBY_AUDIT_DRIVER = (REPO_ROOT / "python" / "tests" / "audit"
                     / "cross_language" / "ruby_reference.rb")


def die(msg):
    sys.exit(f"FREEZE REFUSED: {msg}")


def git(*args):
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def check_env_hygiene(scenarios):
    for s in scenarios:
        for name, value in s.get("env", {}).items():
            secretish = any(t in name.upper() for t in ("KEY", "TOKEN", "SECRET"))
            if secretish and not str(value).startswith("scenario-"):
                die(f"{s['id']}: env var {name} must carry a "
                    "'scenario-' prefixed dummy, never a real value")


def normalized_streams(sc, run):
    return {stream: runner.normalize(getattr(run, stream),
                                     run.run_dir or "<none>", run.scratch)
            for stream in ("stdout", "stderr")}


def run_python_side(sc, ctx_root, tag):
    run_dir = ctx_root / "runs" / f"{sc['id']}-{tag}"
    run_dir.mkdir(parents=True)
    ctx = runner.make_ctx(run_dir, CTX_CORPUS, CTX_LONE)
    return runner.execute(sc, run_dir, ctx)


def ruby_cli_seal(sc, ctx_root, py_run, spec, cr):
    """Mirrored-argv Ruby run; exit + spec files must agree.

    The seal demands EXACTLY what Leg B proved — audit.json/report.json
    under the spec rules plus exit-code equality. audit.txt is deliberately
    NOT cross-language-sealed for pipeline runs: nested hashes in narrative
    inputs render language-idiomatically (Ruby {:a=>1} vs Python {'a': 1}),
    which is why Leg B itself never compared it; the narrative IS still
    frozen (Python-vs-frozen-Python) as a baseline. The audit-unit
    scenario's byte contract (B6's real guarantee) is sealed separately."""
    run_dir = ctx_root / "runs" / f"{sc['id']}-ruby"
    run_dir.mkdir(parents=True)
    ctx = runner.make_ctx(run_dir, CTX_CORPUS, CTX_LONE)
    rb = runner._execute_cli(sc, run_dir, ctx, argv0=["ruby", str(RUBY_CLI)])
    problems = []
    if rb.exit_code != py_run.exit_code:
        problems.append(f"exit {rb.exit_code} (ruby) != {py_run.exit_code} (python)")
    for name in sc.get("files", []):
        diffs = []
        cr.compare_file(str(run_dir), str(py_run.run_dir), name, spec, diffs)
        problems.extend(diffs)
    return problems


def ruby_api_seal(sc, ctx_root, py_run, spec, cr):
    driver = RUBY_TBD_DRIVER if "tbd" in sc["seal"] else RUBY_AUDIT_DRIVER
    run_dir = ctx_root / "runs" / f"{sc['id']}-ruby"
    run_dir.mkdir(parents=True, exist_ok=True)  # the audit driver writes into an existing dir
    proc = subprocess.run(["ruby", str(driver), str(run_dir)],
                          capture_output=True, text=True,
                          env={**runner._base_env(),
                               "BUNDLE_GEMFILE": ""},
                          cwd=str(REPO_ROOT), check=False)
    if proc.returncode != 0:
        return [f"ruby driver failed: {proc.stderr[-1500:]}"]
    problems = []
    for name in sc.get("files", []):
        diffs = []
        cr.compare_file(str(run_dir), str(py_run.run_dir), name, spec, diffs)
        problems.extend(diffs)
    # Only "exact"-mode text (the audit-unit byte contract, B6's real
    # guarantee) is cross-language-sealed; "normalized" pipeline narratives
    # carry language-idiomatic nested-hash renderings Leg B never compared.
    for name, mode in sc.get("text_files", {}).items():
        if mode != "exact":
            continue
        a, b = run_dir / name, Path(py_run.run_dir) / name
        if not (a.is_file() and b.is_file()):
            problems.append(f"{name} missing on one side of the API seal")
        elif a.read_text(encoding="utf-8") != b.read_text(encoding="utf-8"):
            problems.append(f"{name} not byte-identical across the API seal")
    if "tbd" in sc["seal"]:
        problems.extend(tb_non_vacuity(run_dir, "ruby"))
        problems.extend(tb_non_vacuity(Path(py_run.run_dir), "python"))
    return problems


def tb_non_vacuity(run_dir, side):
    """STRUCTURED assertions (post-merge review: substring checks could be
    satisfied by coverage text alone) — the decision-level entry with a
    positive derated count, the 3.1.1.7 article on it, and the specific
    infeasible-uprate warning, on BOTH sealed sides."""
    problems = []
    audit = json.loads((run_dir / "audit.json").read_text(encoding="utf-8"))
    entries = audit if isinstance(audit, list) else audit.get("entries", [])
    tb = [e for e in entries if e.get("step") == "thermal_bridging"]
    decisions = [e for e in tb if e.get("level") == "decision"]
    if not decisions:
        problems.append(f"TB seal ({side}): no DECISION-level "
                        "thermal_bridging entry")
    else:
        d = decisions[0]
        derated = (d.get("inputs") or {}).get("surfaces_derated")
        if not (isinstance(derated, (int, float)) and derated > 0):
            problems.append(f"TB seal ({side}): surfaces_derated is "
                            f"{derated!r}, expected > 0")
        if "3.1.1.7" not in str(d.get("article", "")):
            problems.append(f"TB seal ({side}): the decision's article "
                            "does not cite 3.1.1.7")
    if not any(e.get("level") == "warning"
               and "Unable to uprate" in str(e.get("action", ""))
               for e in tb):
        problems.append(f"TB seal ({side}): no 'Unable to uprate' warning")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--allow-dirty", action="store_true",
                    help="dev override, recorded in provenance")
    args = ap.parse_args()

    dirty = bool(git("status", "--porcelain"))
    if dirty and not args.allow_dirty:
        die("dirty source tree — baselines must be reproducible from a "
            "commit SHA. Commit first (PR-1 commit 1), then freeze.")

    slugs = json.loads((runner.PYTHON_ROOT / "scripts" / "sample_manifest.json")
                       .read_text(encoding="utf-8"))["samples"]
    scenarios = scenario_defs.all_scenarios(slugs)
    check_env_hygiene(scenarios)

    cr = runner.load_compare_runs()
    spec = cr.load_spec(REPO_ROOT / "verification" / "spec.json")

    global CTX_CORPUS, CTX_LONE
    work = Path(tempfile.mkdtemp(prefix="freeze-"))
    CTX_CORPUS = runner.ensure_corpus(work)
    CTX_LONE = runner.lone_epw(work)

    staging = Path(tempfile.mkdtemp(prefix="freeze-out-"))
    baselines = staging / "baselines"
    seal_tally = {"ruby": 0, "ruby-api": 0, "python-only": 0}
    frozen = []

    for sc in scenarios:
        print(f"== {sc['id']} ({sc['lane']}, seal={sc['seal'].split(':')[0]})",
              flush=True)
        run1 = run_python_side(sc, work, "a")
        run2 = run_python_side(sc, work, "b")
        if sc.get("expect_exit") is not None:
            for r in (run1, run2):
                if r.exit_code != sc["expect_exit"]:
                    die(f"{sc['id']}: exit {r.exit_code}, expected "
                        f"{sc['expect_exit']}\n{r.stderr[-1500:]}")
        s1, s2 = normalized_streams(sc, run1), normalized_streams(sc, run2)
        for stream, mode in sc.get("streams", {}).items():
            if mode == "exact" and s1[stream] != s2[stream]:
                die(f"{sc['id']}: {stream} is NOT deterministic across two "
                    "runs — declare a fragments policy or fix the source "
                    "of variance; 'exact' cannot be frozen from unstable "
                    "output")

        # live-run comparisons that need no baseline (fragments, bytes, set)
        probe = runner.compare(
            {**sc, "files": [], "text_files": {},
             "streams": {k: v for k, v in sc.get("streams", {}).items()
                         if v != "exact"}},
            run1, spec, cr)
        if probe:
            die(f"{sc['id']}: live-run contract failed pre-freeze:\n"
                + "\n".join(probe))

        seal = sc["seal"]
        if seal == "ruby":
            problems = ruby_cli_seal(sc, work, run1, spec, cr)
            seal_tally["ruby"] += 1
        elif seal.startswith("ruby-api:"):
            problems = ruby_api_seal(sc, work, run1, spec, cr)
            seal_tally["ruby-api"] += 1
        else:
            problems, _ = [], seal_tally.__setitem__(
                "python-only", seal_tally["python-only"] + 1)
        if problems:
            die(f"{sc['id']}: THE RUBY SEAL FAILED — the two implementations "
                "disagree at freeze time; this is a Leg-B finding, not a "
                "freeze problem:\n" + "\n".join(problems[:20]))

        # non-vacuity for annual energies
        if sc["id"].startswith("corpus-annual"):
            rep = json.loads((Path(run1.run_dir) / "report.json")
                             .read_text(encoding="utf-8"))
            if not (rep.get("proposed", {}).get("total_site_kwh")
                    and "unmet_occupied_hours" in rep.get("proposed", {})):
                die(f"{sc['id']}: annual baseline lacks energies/unmet "
                    "hours — a vacuous baseline must not freeze")

        # publish this scenario's baselines
        dest = baselines / sc["id"]
        dest.mkdir(parents=True)
        hashes = {}

        def strip_keys(node, keys):
            if isinstance(node, dict):
                return {k: strip_keys(v, keys) for k, v in node.items()
                        if k not in keys}
            if isinstance(node, list):
                return [strip_keys(v, keys) for v in node]
            return node

        for name in sc.get("files", []):
            # Store the CANONICAL form: spec strip_keys applied at freeze
            # time, so machine-local paths (run_dir) never enter the
            # committed baselines and re-freezes are byte-stable when
            # nothing real changed. compare_runs strips both sides at
            # compare time, so comparison semantics are unchanged.
            data = json.loads((Path(run1.run_dir) / name)
                              .read_text(encoding="utf-8"))
            (dest / name).write_text(
                json.dumps(strip_keys(data, set(spec.get("strip_keys", []))),
                           indent=1) + "\n", encoding="utf-8")
        for name in sc.get("text_files", {}):
            shutil.copyfile(Path(run1.run_dir) / name, dest / name)
        for stream, mode in sc.get("streams", {}).items():
            if mode == "exact":
                (dest / f"{stream}.txt").write_text(s1[stream],
                                                    encoding="utf-8")
        for f in sorted(dest.iterdir()):
            hashes[f.name] = runner.sha256(f)
        frozen.append({**sc, "baseline_sha256": hashes})

    counts = {}
    for sc in frozen:
        counts[sc["lane"]] = counts.get(sc["lane"], 0) + 1
    manifest = {
        "version": 1,
        "spec_sha256": runner.sha256(REPO_ROOT / "verification" / "spec.json"),
        "provenance": {
            "commit": git("rev-parse", "HEAD"), "dirty": dirty,
            # The INTERPRETER MACHINERY is pinned too (post-merge review
            # High): a change to what executes/normalizes/compares frozen
            # baselines is a behaviour change and demands a re-freeze.
            "freezer_sha256": runner.sha256(__file__),
            "defs_sha256": runner.sha256(HERE / "scenario_defs.py"),
            "runner_sha256": runner.sha256(HERE / "runner.py"),
            "gate_sha256": runner.sha256(
                runner.PYTHON_ROOT / "tests" / "necb"
                / "test_frozen_scenarios.py"),
            "openstudio_cli": subprocess.run(
                ["openstudio", "openstudio_version"], capture_output=True,
                text=True, check=False).stdout.strip(),
            "ruby": subprocess.run(["ruby", "-v"], capture_output=True,
                                   text=True, check=False).stdout.strip(),
            "seal": seal_tally,
            "attestation_note": "the validating CI run id is EXTERNAL "
                                "evidence (PR body + D-82), never recorded "
                                "here — writing it back would invalidate "
                                "the very run as head evidence",
        },
        "corpus": {"generator": "python",
                   "sample_manifest_sha256": runner.sha256(
                       runner.PYTHON_ROOT / "scripts" / "sample_manifest.json")},
        "counts": counts,
        "scenarios": frozen,
        "uncovered": scenario_defs.UNCOVERED,
    }
    (staging / "manifest.json").write_text(
        json.dumps(manifest, indent=1) + "\n", encoding="utf-8")

    # atomic promote via backup-swap (the export_goldens pattern): the
    # previous valid baselines must survive a failed promotion.
    backup_b = Path(str(runner.BASELINES) + f".backup.{os.getpid()}")
    backup_m = Path(str(runner.MANIFEST) + f".backup.{os.getpid()}")
    moved_b = moved_m = False
    try:
        if runner.BASELINES.exists():
            shutil.move(str(runner.BASELINES), str(backup_b))
            moved_b = True
        if runner.MANIFEST.exists():
            shutil.move(str(runner.MANIFEST), str(backup_m))
            moved_m = True
        shutil.move(str(baselines), str(runner.BASELINES))
        shutil.move(str(staging / "manifest.json"), str(runner.MANIFEST))
    except BaseException:
        if moved_b and not runner.BASELINES.exists():
            shutil.move(str(backup_b), str(runner.BASELINES))
        if moved_m and not runner.MANIFEST.exists():
            shutil.move(str(backup_m), str(runner.MANIFEST))
        raise
    for backup in (backup_b, backup_m):
        if backup.exists():
            (shutil.rmtree if backup.is_dir() else os.remove)(str(backup))
    print(f"frozen {len(frozen)} scenarios "
          f"({counts}), seal {seal_tally}; manifest written")


if __name__ == "__main__":
    main()
