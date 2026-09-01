#!/usr/bin/env python3
"""Validate that the R6 re-freeze changed only approved evidence and seals."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINES = REPO_ROOT / "verification" / "scenarios" / "baselines"
MANIFEST = REPO_ROOT / "verification" / "scenarios" / "manifest.json"
MAPPING = REPO_ROOT / "python" / "tests" / "data" / "coverage_code_ref_mapping.json"
TRANSITION_FIELDS = {
    "retired_seal", "last_cross_language_commit", "last_cross_language_run_id",
    "last_cross_language_run_url", "seal_transition_reason",
}


def git_bytes(ref: str, relative: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{ref}:{relative}"],
        capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"cannot read {relative} at {ref}")
    return result.stdout


def baseline_files() -> list[Path]:
    return sorted(path for path in BASELINES.rglob("*") if path.is_file())


def normalize_new(data: bytes, inverse: dict[bytes, bytes]) -> bytes:
    for new, old in sorted(inverse.items(), key=lambda pair: len(pair[0]), reverse=True):
        data = data.replace(new, old)
    return data


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate(before_ref: str) -> dict:
    rows = json.loads(MAPPING.read_text(encoding="utf-8"))["mappings"]
    inverse = {row["new"].encode(): row["old"].encode() for row in rows}
    raw_changed = []
    normalized_changed = []
    files = baseline_files()
    current_names = {path.relative_to(REPO_ROOT).as_posix() for path in files}
    old_manifest = json.loads(git_bytes(
        before_ref, "verification/scenarios/manifest.json"))
    old_names = {
        f"verification/scenarios/baselines/{scenario['id']}/{name}"
        for scenario in old_manifest["scenarios"]
        for name in scenario["baseline_sha256"]
    }
    if current_names != old_names:
        raise AssertionError(
            f"baseline file set changed: added={sorted(current_names - old_names)}, "
            f"removed={sorted(old_names - current_names)}")

    normalized_hashes = {}
    for path in files:
        relative = path.relative_to(REPO_ROOT).as_posix()
        old = git_bytes(before_ref, relative)
        new = path.read_bytes()
        normalized = normalize_new(new, inverse)
        if old != new:
            raw_changed.append(relative)
        if old != normalized:
            normalized_changed.append(relative)
        normalized_hashes[relative] = sha256(normalized)
    if normalized_changed:
        raise AssertionError(
            "non-evidence baseline changes:\n" + "\n".join(normalized_changed))

    scenarios = sorted({path.split("/")[3] for path in raw_changed})
    if len(raw_changed) != 46 or len(scenarios) != 23:
        raise AssertionError(
            f"expected 46 evidence files across 23 scenarios, got "
            f"{len(raw_changed)} across {len(scenarios)}")

    current = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if current["version"] != 2:
        raise AssertionError(f"manifest version is {current['version']}, expected 2")
    active = current["provenance"].get("active_seals")
    retired = current["provenance"].get("retired_seals")
    if active != {"python-only:post-handoff": 31, "python-only": 4}:
        raise AssertionError(f"unexpected active seal tally: {active}")
    if retired != {"ruby": 29, "ruby-api": 2}:
        raise AssertionError(f"unexpected retired seal tally: {retired}")
    attestation = current["provenance"].get("final_cross_language_attestation")
    expected_attestation = {
        "commit": "85ab14352677093e24038d933cf1071e5b03431a",
        "run_id": 33544573991,
        "run_url": "https://github.com/canmet-energy/btap/actions/runs/33544573991",
    }
    if attestation != expected_attestation:
        raise AssertionError(f"unexpected final attestation: {attestation}")

    old_by_id = {scenario["id"]: scenario for scenario in old_manifest["scenarios"]}
    transitioned = 0
    for scenario in current["scenarios"]:
        old = old_by_id[scenario["id"]]
        if scenario["seal"] == "python-only:post-handoff":
            transitioned += 1
            if scenario.get("retired_seal") != old["seal"]:
                raise AssertionError(f"{scenario['id']}: retired seal changed")
            for field in TRANSITION_FIELDS:
                if not scenario.get(field):
                    raise AssertionError(f"{scenario['id']}: missing {field}")
        elif scenario["seal"] != old["seal"]:
            raise AssertionError(f"{scenario['id']}: historical Python-only seal changed")
        for name, old_hash in old["baseline_sha256"].items():
            relative = f"verification/scenarios/baselines/{scenario['id']}/{name}"
            if normalized_hashes[relative] != old_hash:
                raise AssertionError(f"{scenario['id']}/{name}: normalized hash changed")
    if transitioned != 31:
        raise AssertionError(f"transitioned {transitioned} scenarios, expected 31")

    return {
        "schema_version": 1,
        "before_ref": before_ref,
        "after_commit": current["provenance"]["commit"],
        "baseline_files_checked": len(files),
        "evidence_files_changed": len(raw_changed),
        "evidence_scenarios_changed": len(scenarios),
        "changed_scenarios": scenarios,
        "transitioned_seals": transitioned,
        "active_seals": active,
        "retired_seals": retired,
        "final_cross_language_attestation": attestation,
        "unexpected_changes": [],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-ref", default="cbce093")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    summary = validate(args.before_ref)
    text = json.dumps(summary, indent=1) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())