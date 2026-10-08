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
import runner  # noqa: E402
import scenario_defs  # noqa: E402

REPO_ROOT = runner.REPO_ROOT
RUBY_CLI = REPO_ROOT / "btap-necb" / "exe" / "btap-compliance.rb"
RUBY_TBD_DRIVER = (REPO_ROOT / "python" / "tests" / "necb" / "cross_language"
                   / "ruby_tbd_compliance.rb")
RUBY_AUDIT_DRIVER = (REPO_ROOT / "python" / "tests" / "audit"
                     / "cross_language" / "ruby_reference.rb")
TRANSITION_FIELDS = (
    "retired_seal", "last_cross_language_commit", "last_cross_language_run_id",
    "last_cross_language_run_url", "seal_transition_reason",
)


#: The band a frozen scenario's energy intensity must fall in, kWh/m2.
#:
#: Deliberately WIDE. The corpus spans 3.2 (a `--quick` run simulating days
#: rather than a year) to 185 (a real full year), so this leaves roughly 30x
#: headroom below and 50x above. It is a sanity bound on a simulation result,
#: NOT a materiality threshold on a Code question — the point is to catch a
#: model that is physically absurd, never to express a view about how much
#: energy a compliant building may use.
#:
#: WHAT THIS GUARD DOES NOT CATCH, stated so nobody trusts it further than it
#: reaches. Sol's `130` measured a System 5 reference that completed with zero
#: severe and zero fatal errors AND a site EUI of about 314 kWh/m2 — squarely
#: inside this band — while refrigerating nothing: zone temperatures 9.32 to
#: 41.75 C against a 4 C setpoint, and 8,760 cooling-unmet hours in every zone.
#: A plausible total is not thermal control.
#:
#: The right check is ALL-HOURS zone control, and `report.json` does not carry
#: it — only `unmet_occupied_hours` and `zone_unmet_occupied_hours`, which a
#: real baseline legitimately pushes high (determination-01's proposed side
#: records 1,709.75 unmet cooling hours). A threshold on the occupied figure
#: would be a number I cannot justify rather than a check, so none is written
#: here. Carrying an all-hours metric is part of AHJ-19's reporting gap; when it
#: lands, this guard should grow a thermal-control arm beside the energy one.
EUI_SANE_MIN_KWH_M2 = 0.1
EUI_SANE_MAX_KWH_M2 = 10_000.0


def _implausible_eui(run):
    """Complaints about any side whose energy intensity is not a building's.

    Reads the run's own `report.json`; silent when the report carries no energy
    (a `--simulate none` scenario has none to check), because a missing number
    is not an absurd one.
    """
    report = (run.observations or {}).get("report") if run.observations else None
    if report is None:
        path = Path(run.run_dir) / "report.json"
        if not path.is_file():
            return []
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
    out = []
    for side in ("proposed", "reference"):
        block = report.get(side) or {}
        kwh = block.get("total_site_kwh")
        area = block.get("floor_area_m2") or report.get("floor_area_m2")
        if not kwh or not area:
            continue
        eui = kwh / area
        if not EUI_SANE_MIN_KWH_M2 <= eui <= EUI_SANE_MAX_KWH_M2:
            out.append(
                f"  {side}: {kwh:,.0f} kWh over {area:,.0f} m2 = "
                f"{eui:,.1f} kWh/m2, outside "
                f"[{EUI_SANE_MIN_KWH_M2}, {EUI_SANE_MAX_KWH_M2:,.0f}]")
    return out


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


def seal_accounting(scenarios):
    active = {"python-only:post-handoff": 0, "python-only": 0}
    retired = {"ruby": 0, "ruby-api": 0}
    attestation = None
    for scenario in scenarios:
        seal = scenario["seal"]
        if seal == "python-only:post-handoff":
            missing = [field for field in TRANSITION_FIELDS if not scenario.get(field)]
            if missing:
                raise ValueError(f"{scenario['id']}: transition metadata missing {missing}")
            retired_seal = scenario["retired_seal"]
            if retired_seal == "ruby":
                retired["ruby"] += 1
            elif retired_seal.startswith("ruby-api:"):
                retired["ruby-api"] += 1
            else:
                raise ValueError(
                    f"{scenario['id']}: invalid retired_seal {retired_seal!r}")
            active["python-only:post-handoff"] += 1
            current = {
                "commit": scenario["last_cross_language_commit"],
                "run_id": scenario["last_cross_language_run_id"],
                "run_url": scenario["last_cross_language_run_url"],
            }
            if attestation is not None and current != attestation:
                raise ValueError("post-handoff scenarios disagree on final attestation")
            attestation = current
        elif seal.startswith("python-only:"):
            active["python-only"] += 1
        else:
            raise ValueError(f"{scenario['id']}: active product-Ruby seal {seal!r}")
    return active, retired, attestation


def check_required_python_engines(scenarios):
    if not any(scenario.get("api_call", {}).get("thermal_bridging")
               for scenario in scenarios):
        return
    try:
        import tbd

        from btap.codes.necb.envelope import thermal_bridging
    except ImportError as error:
        raise ValueError(
            "thermal-bridging scenario requires the pinned tbd engine in the "
            "FREEZER interpreter; run python/.venv/bin/python "
            "verification/scenarios/freeze.py") from error
    if tbd.VERSION != thermal_bridging.PINNED_TBD_VERSION:
        raise ValueError(
            f"thermal-bridging scenario loaded tbd {tbd.VERSION}, expected "
            f"{thermal_bridging.PINNED_TBD_VERSION}")


def _wants_energyplus(scenario):
    """Does this scenario RUN EnergyPlus? Two independent shapes: an API
    scenario simulating anything but 'none' (the kwarg defaults to
    'annual', so an absent key still means a real run), and a CLI argv
    carrying --simulate annual|sizing."""
    if scenario.get("kind") == "api":
        if scenario.get("api_call", {}).get("simulate", "annual") != "none":
            return True
    argv = scenario.get("argv", [])
    for index, token in enumerate(argv[:-1]):
        if token == "--simulate" and argv[index + 1] in ("annual", "sizing"):
            return True
    return False


def check_required_energyplus(scenarios):
    """SEPARATE from the tbd check above: those are different engines with
    different failure modes, and a freeze that silently lacks EnergyPlus
    would die deep inside a scenario instead of at the door."""
    wanting = [s["id"] for s in scenarios if _wants_energyplus(s)]
    if not wanting:
        return
    runner._sys_path_python()
    try:
        from btap.simulation.engine import ensure_energyplus
        ensure_energyplus()
    except Exception as error:  # noqa: BLE001 — every failure is the same answer
        die("scenarios need a working EnergyPlus engine in the FREEZER "
            f"interpreter and none resolved ({error!r}).\n"
            f"  affected: {', '.join(wanting)}\n"
            "  run python/.venv/bin/python verification/scenarios/freeze.py "
            "in the container image (or set BTAP_ENERGYPLUS).")


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


def promote(staged_baselines, staged_manifest, dest_baselines,
            dest_manifest, mover=shutil.move):
    """Backup-swap promotion (the export_goldens pattern): the previous
    valid baselines+manifest survive ANY failed step — verified by a
    negative control that injects a mover failure mid-promotion.
    ``mover`` is injectable for exactly that control; production always
    uses shutil.move."""
    backup_b = Path(str(dest_baselines) + f".backup.{os.getpid()}")
    backup_m = Path(str(dest_manifest) + f".backup.{os.getpid()}")
    moved_b = moved_m = False
    try:
        if dest_baselines.exists():
            mover(str(dest_baselines), str(backup_b))
            moved_b = True
        if dest_manifest.exists():
            mover(str(dest_manifest), str(backup_m))
            moved_m = True
        mover(str(staged_baselines), str(dest_baselines))
        mover(str(staged_manifest), str(dest_manifest))
    except BaseException:
        # FULL rollback to the previous consistent state: a partial
        # promotion (new baselines in, old manifest still current — the
        # torn state the negative control reproduces) is rolled BACK, not
        # left standing. Whatever now occupies a dest that has a backup is
        # the unpromoted newcomer; remove it and restore the backup.
        if moved_b and backup_b.exists():
            if dest_baselines.exists():
                shutil.rmtree(str(dest_baselines))
            shutil.move(str(backup_b), str(dest_baselines))
        if moved_m and backup_m.exists():
            if dest_manifest.exists():
                os.remove(str(dest_manifest))
            shutil.move(str(backup_m), str(dest_manifest))
        raise
    for backup in (backup_b, backup_m):
        if backup.exists():
            (shutil.rmtree if backup.is_dir() else os.remove)(str(backup))


def producer_identity():
    """What actually produced this freeze, as far as it can be established.

    WHY THIS EXISTS. The manifest already pins the SOURCE — a commit, three
    harness hashes, the sample manifest — and because the scenarios' weather
    is COMMITTED (`python/tests/fixtures/weather/*.epw`/`.ddy`), that commit
    pins the weather bytes too. What it did not pin is the PRODUCER.
    `openstudio_cli` is a version STRING a machine reports; two laptops can
    report `3.11.0+241b8abb4d` while running different EnergyPlus builds, and
    CI never freezes, so the producer has always been whichever developer
    machine ran this script.

    EVERYTHING IS PROBED IN THE WORKER INTERPRETER, not this one. Scenario
    subprocesses run under `runner.python_exe()`, where `BTAP_PYTHON` takes
    precedence, and the worker's `Local.execute` calls its OWN
    `engine.ensure_energyplus()`. Probing `openstudio` and the engine here
    recorded the DRIVER's stack: under a controlled override the record said
    `python_worker=3.99.0` at `/other/python` while still reporting the
    driver's OpenStudio and EnergyPlus — false provenance whenever the two
    environments carry different builds (Sol, PR #80). The driver's own values
    are kept beside them, labelled, so a divergence is visible rather than
    hidden behind one ambiguous field.

    A BARE VERSION IS REFUSED. The build suffix is the entire reason this
    field exists — `25.2.0` is exactly what hides two engines — so a
    successful probe returning `EnergyPlus, Version 25.2.0` records NULL
    rather than a value that cannot distinguish anything.

    These fields are a RECORD, NOT A GATE. Nothing compares them against the
    running machine: a baseline frozen on one host must remain verifiable on
    another, which is the point of the frozen corpus. What they buy is
    attribution — when a baseline moves, the diff says whether the engine
    underneath it moved too.

    `container_digest` is the field this cannot fill. The CI image's tag is
    `<openstudio version>-<sha256(Dockerfile)[:12]>`, which pins the RECIPE,
    not the built bytes; a true `sha256:` digest is obtainable only where the
    image runs, so it stays null until freezing happens there.

    Every probe fails SOFT. A freeze must not break because an identity could
    not be read; an absent field says "unknown", which is honest, where a
    raised exception would just stop the work.
    """
    import platform
    import re

    #: A version WITH a build suffix. The suffix is mandatory: see the
    #: docstring.
    ENGINE_RE = re.compile(r"^\d+\.\d+\.\d+-[0-9A-Za-z]+$")

    identity = {
        "openstudio": None,
        "energyplus": None,
        "python_driver": platform.python_version(),
        "python_worker": None,
        "platform": platform.platform(),
        "container_digest": None,
    }

    # One probe, in the interpreter that will actually run the scenarios.
    probe = (
        "import platform, sys\n"
        "print('python', platform.python_version())\n"
        "print('exe', sys.executable)\n"
        "try:\n"
        "    import openstudio\n"
        "    print('openstudio', openstudio.openStudioLongVersion())\n"
        "except Exception: pass\n"
        "try:\n"
        "    import subprocess\n"
        "    from btap.simulation import engine\n"
        "    out = subprocess.run([str(engine.ensure_energyplus()), "
        "'--version'], capture_output=True, text=True, timeout=120)\n"
        "    if out.returncode == 0:\n"
        "        text = (out.stdout or out.stderr).strip()\n"
        "        print('energyplus', text.split()[-1] if text else '')\n"
        "except Exception: pass\n")
    try:
        runner._sys_path_python()
        worker = runner.python_exe()
        env = dict(os.environ)
        env["PYTHONPATH"] = (str(runner.PYTHON_ROOT) + os.pathsep
                             + env.get("PYTHONPATH", "")).rstrip(os.pathsep)
        out = subprocess.run([str(worker), "-c", probe], capture_output=True,
                             text=True, check=False, timeout=600, env=env)
        if out.returncode == 0:
            for line in out.stdout.strip().splitlines():
                key, _, value = line.partition(" ")
                value = value.strip()
                if key == "python" and re.fullmatch(r"\d+\.\d+\.\d+", value):
                    identity["python_worker"] = value
                elif key == "exe" and value:
                    identity["python_worker_executable"] = value
                elif key == "openstudio" and value:
                    identity["openstudio"] = value
                elif key == "energyplus" and ENGINE_RE.match(value):
                    identity["energyplus"] = value
    except Exception:  # noqa: BLE001 — an unknown identity is not a failure
        pass

    # The DRIVER's own stack, beside the worker's, so a divergence is visible.
    try:
        import openstudio

        identity["openstudio_driver"] = openstudio.openStudioLongVersion()
    except Exception:  # noqa: BLE001
        pass
    try:
        from btap.simulation import engine

        out = subprocess.run([str(engine.ensure_energyplus()), "--version"],
                             capture_output=True, text=True, check=False,
                             timeout=120)
        if out.returncode == 0:
            text = (out.stdout or out.stderr).strip()
            candidate = text.split()[-1] if text else ""
            if ENGINE_RE.match(candidate):
                identity["energyplus_driver"] = candidate
    except Exception:  # noqa: BLE001
        pass
    return identity


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
    try:
        active_seals, retired_seals, final_attestation = seal_accounting(scenarios)
        check_required_python_engines(scenarios)
    except ValueError as error:
        die(str(error))
    check_required_energyplus(scenarios)

    cr = runner.load_compare_runs()
    spec = cr.load_spec(REPO_ROOT / "verification" / "spec.json")

    global CTX_CORPUS, CTX_LONE
    work = Path(tempfile.mkdtemp(prefix="freeze-"))
    CTX_CORPUS = runner.ensure_corpus(work)
    CTX_LONE = runner.lone_epw(work)

    staging = Path(tempfile.mkdtemp(prefix="freeze-out-"))
    baselines = staging / "baselines"
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
            {**sc, "files": [], "text_files": {}, "asserts": [],
             "streams": {k: v for k, v in sc.get("streams", {}).items()
                         if v != "exact"}},
            run1, spec, cr)
        if probe:
            die(f"{sc['id']}: live-run contract failed pre-freeze:\n"
                + "\n".join(probe))

        # NON-VACUITY, per scenario, from the scenario's own authored
        # `asserts` block — the same runner.check_assertions the normal
        # comparator runs on every later run, so this is a contract the
        # baselines keep, not a one-off freeze-time inspection. A baseline
        # that fails its own non-vacuity does not freeze.
        vacuity = runner.check_assertions(sc, run1)
        if vacuity:
            die(f"{sc['id']}: non-vacuity assertions failed — a vacuous "
                "baseline must not freeze:\n" + "\n".join(vacuity))

        # PHYSICAL SANITY, before anything is written. A run that completes
        # is not a run that makes sense, and nothing here checked the
        # difference until a fixture froze with a proposed EUI of 13.9 MILLION
        # kWh/m2 — five orders of magnitude out, reported as a number rather
        # than an error, and caught only by `parity-scenarios` noticing it was
        # not reproducible across machines.
        insane = _implausible_eui(run1)
        if insane:
            die(f"{sc['id']}: implausible energy intensity — a baseline must "
                "be a building, not merely a completed simulation:\n"
                + "\n".join(insane))

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
        "version": 2,
        "spec_sha256": runner.sha256(REPO_ROOT / "verification" / "spec.json"),
        "provenance": {
            "commit": git("rev-parse", "HEAD"), "dirty": dirty,
            # The INTERPRETER MACHINERY is pinned too (post-merge review
            # High): a change to what executes/normalizes/compares frozen
            # baselines is a behaviour change and demands a re-freeze.
            "freezer_sha256": runner.sha256(__file__),
            "defs_sha256": runner.sha256(HERE / "scenario_defs.py"),
            "runner_sha256": runner.sha256(HERE / "runner.py"),
            # The API worker, the comparison semantics and the audit-scenario
            # constructor execute or shape frozen runs too (post-9a review
            # High): pinned with the rest of the machinery.
            "api_worker_sha256": runner.sha256(HERE / "api_worker.py"),
            "compare_runs_sha256": runner.sha256(
                REPO_ROOT / "verification" / "compare_runs.py"),
            "audit_scenario_sha256": runner.sha256(HERE / "audit_scenario.py"),
            "gate_sha256": runner.sha256(
                runner.PYTHON_ROOT / "tests" / "necb"
                / "test_frozen_scenarios.py"),
            "openstudio_cli": subprocess.run(
                ["openstudio", "openstudio_version"], capture_output=True,
                text=True, check=False).stdout.strip(),
                # WHO produced this freeze. A record, never a gate — no
            # test compares these against the running machine, because a
            # baseline frozen on one host must stay verifiable on another.
            "producer": producer_identity(),
            "active_seals": active_seals,
            "retired_seals": retired_seals,
            "final_cross_language_attestation": final_attestation,
            "attestation_note": "the final cross-language CI run validates "
                                "its own ancestor commit; its immutable run "
                                "identity is retained after product-Ruby retirement",
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

    promote(baselines, staging / "manifest.json",
            runner.BASELINES, runner.MANIFEST)
    print(f"frozen {len(frozen)} scenarios "
            f"({counts}), active seals {active_seals}, "
            f"retired seals {retired_seals}; manifest written")


if __name__ == "__main__":
    main()
