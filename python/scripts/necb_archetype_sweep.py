#!/usr/bin/env python3
"""Run legacy NECB2020 archetypes through Python performance compliance.

The proposed models are generated out of process by
``verification/oracle/gen_legacy_archetype.rb`` under ``legacy_pin/Gemfile``.
Only the consumer is Python: each worker loads the oracle-produced OSM and
calls :func:`btap.necb.compliance.performance_compliance` directly.

Usage::

    python3 scripts/necb_archetype_sweep.py [fleet | BUILDING_TYPE ...]
        [--mode sizing|annual|full] [--vintage 2020|2025]
        [--location toronto|edmonton|yellowknife] [--workers N] [--resume]

``annual`` is the January 1-7 quick tier; ``full`` is the 8760-hour tier.
Hospital and Outpatient remain available by explicit name but are excluded
from ``fleet`` because their capacity-iteration chains dominate routine runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
PYTHON_ROOT = HERE.parent
REPO_ROOT = PYTHON_ROOT.parent

GEN_SCRIPT = REPO_ROOT / "verification" / "oracle" / "gen_legacy_archetype.rb"
PIN_GEMFILE = REPO_ROOT / "legacy_pin" / "Gemfile"
PIN_REF = REPO_ROOT / "legacy_pin" / "REF"
CACHE_DIR = Path(tempfile.gettempdir()) / "btap_necb_legacy_archetype_e2e_py"
TEMPLATE = "NECB2020"
MEM_PER_WORKER_GB = 1.5

FLEET = (
    "SmallOffice", "MediumOffice", "LargeOffice", "PrimarySchool",
    "SecondarySchool", "RetailStandalone", "RetailStripmall", "Warehouse",
    "FullServiceRestaurant", "QuickServiceRestaurant", "HighriseApartment",
    "LowriseApartment", "MidriseApartment", "SmallHotel", "LargeHotel",
)
DEFAULT_TYPES = (
    "Warehouse", "FullServiceRestaurant", "HighriseApartment",
    "PrimarySchool", "RetailStandalone",
)
COST_HINT = {
    "Hospital": 100,
    "Outpatient": 90,
    "LargeHotel": 60,
    "LargeOffice": 55,
    "SecondarySchool": 50,
    "PrimarySchool": 40,
    "MediumOffice": 35,
    "HighriseApartment": 30,
    "MidriseApartment": 25,
    "SmallHotel": 25,
    "LowriseApartment": 20,
    "RetailStripmall": 15,
    "RetailStandalone": 12,
    "SmallOffice": 10,
    "FullServiceRestaurant": 8,
    "QuickServiceRestaurant": 6,
    "Warehouse": 5,
}

LOCATIONS = {
    "toronto": {
        "epw": PYTHON_ROOT / "tests" / "fixtures" / "weather"
        / "CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw",
        "hdd": 3890,
    },
    "edmonton": {
        "epw": REPO_ROOT / "data" / "weather"
        / "CAN_AB_Edmonton.Intl.AP.711230_CWEC2020.epw",
        "hdd": 5120,
    },
    "yellowknife": {
        "epw": REPO_ROOT / "data" / "weather"
        / "CAN_NT_Yellowknife.AP.719360_CWEC2020.epw",
        "hdd": 8170,
    },
}


@dataclass(frozen=True)
class SweepConfig:
    mode: str
    vintage: str
    location: str
    workers: int
    cache_dir: Path
    resume: bool = False
    fuel: str = "Electricity"
    ecm: str = "NECB_Default"


class GenerationError(RuntimeError):
    pass


def selected_types(arguments: list[str]) -> list[str]:
    if not arguments:
        return list(DEFAULT_TYPES)
    if arguments == ["fleet"]:
        return list(FLEET)
    return arguments


def ordered_types(building_types: list[str] | tuple[str, ...]) -> list[str]:
    return sorted(building_types, key=lambda name: (-COST_HINT.get(name, 0), name))


def detected_memory_gb() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1]) / 1_048_576.0
    except (OSError, ValueError, IndexError):
        pass
    return None


def default_workers() -> int:
    override = os.environ.get("SWEEP_WORKERS")
    if override is not None:
        try:
            return max(int(override), 1)
        except ValueError as error:
            raise ValueError("SWEEP_WORKERS must be an integer") from error
    processors = os.cpu_count() or 1
    memory = detected_memory_gb()
    by_memory = int(memory / MEM_PER_WORKER_GB) if memory is not None else processors
    return max(min(processors, by_memory), 1)


def _location(config: SweepConfig) -> tuple[Path, Path, int]:
    location = LOCATIONS[config.location]
    epw = location["epw"]
    return epw, epw.with_suffix(".ddy"), location["hdd"]


def _generation_arguments(building_type: str, output: str, sizing: str,
                          config: SweepConfig) -> list[str]:
    epw, _, _ = _location(config)
    return [output, sizing, TEMPLATE, building_type, epw.name,
            config.fuel, config.ecm]


def _oracle_attestation(building_type: str, config: SweepConfig) -> dict[str, str]:
    epw, _, _ = _location(config)
    return {
        "legacy_ref": PIN_REF.read_text(encoding="utf-8").strip(),
        "template": TEMPLATE,
        "building_type": building_type,
        "epw": epw.name,
        "primary_heating_fuel": config.fuel,
        "ecm_system_name": config.ecm,
    }


def _recipe(building_type: str, config: SweepConfig) -> dict[str, object]:
    epw, _, _ = _location(config)
    return {
        **_oracle_attestation(building_type, config),
        "generator_sha256": hashlib.sha256(GEN_SCRIPT.read_bytes()).hexdigest(),
        "epw_sha256": hashlib.sha256(epw.read_bytes()).hexdigest(),
        "arguments": _generation_arguments(
            building_type, "<OUTPUT_OSM>", "<SIZING_DIR>", config),
    }


def _recipe_key(building_type: str, config: SweepConfig) -> str:
    encoded = json.dumps(
        _recipe(building_type, config), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _generated_osm(building_type: str, config: SweepConfig) -> Path:
    key = _recipe_key(building_type, config)
    return config.cache_dir / f"legacy_necb2020_{building_type.lower()}_{key}.osm"


def _valid_generated_model(osm: Path, building_type: str, config: SweepConfig) -> bool:
    sidecar = osm.with_suffix(".json")
    try:
        return (
            osm.is_file()
            and osm.stat().st_size > 0
            and sidecar.is_file()
            and json.loads(sidecar.read_text(encoding="utf-8"))
            == _oracle_attestation(building_type, config)
        )
    except (OSError, json.JSONDecodeError):
        return False


def generate(building_type: str, config: SweepConfig) -> tuple[Path, bool]:
    """Generate one pinned-oracle model, returning ``(path, cache_hit)``."""
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    osm = _generated_osm(building_type, config)
    if _valid_generated_model(osm, building_type, config):
        return osm, True

    sidecar = osm.with_suffix(".json")
    osm.unlink(missing_ok=True)
    sidecar.unlink(missing_ok=True)
    sizing = config.cache_dir / f"gen_sizing_{building_type}_{_recipe_key(building_type, config)}"
    shutil.rmtree(sizing, ignore_errors=True)
    sizing.mkdir(parents=True)
    env = {**os.environ, "BUNDLE_GEMFILE": str(PIN_GEMFILE)}
    command = [
        "bundle", "exec", "ruby", str(GEN_SCRIPT),
        *_generation_arguments(building_type, str(osm), str(sizing), config),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=1800,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise GenerationError(f"oracle generation could not run: {error}") from error

    stem = config.cache_dir / f"gen_{building_type}_{_recipe_key(building_type, config)}"
    stem.with_suffix(".log").write_text(completed.stdout, encoding="utf-8")
    stem.with_suffix(".err").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0 or not _valid_generated_model(osm, building_type, config):
        detail = (completed.stdout + completed.stderr)[-2000:].strip()
        raise GenerationError(
            f"oracle generation failed (exit {completed.returncode}); "
            f"see {stem.with_suffix('.err')}: {detail}"
        )
    return osm, False


def _pipeline_dependencies():
    from btap._sdk import load_model
    from btap.costing.hvac.geometry import above_ground_storeys
    from btap.necb.compliance import PreflightError, performance_compliance

    return load_model, above_ground_storeys, performance_compliance, PreflightError


def _energy_summary(section: dict | None) -> dict[str, object]:
    if not section:
        return {}
    keys = (
        "total_site_kwh", "eui_kwh_per_m2", "floor_area_m2",
        "unmet_occupied_hours", "clean_run",
    )
    return {key: section[key] for key in keys if key in section}


def normalized_report_summary(result) -> dict[str, object]:
    report = result.report or {}
    return {
        "annual": report.get("annual"),
        "compliant": result.compliant,
        "tier": report.get("tier"),
        "percent_of_target": report.get("percent_of_target"),
        "proposed": _energy_summary(report.get("proposed")),
        "reference": _energy_summary(report.get("reference")),
    }


def _result_path(building_type: str, config: SweepConfig) -> Path:
    key = _recipe_key(building_type, config)
    return config.cache_dir / (
        f"result_{building_type}_{config.mode}_{config.vintage}_{config.location}_{key}.json"
    )


def _run_dir(building_type: str, config: SweepConfig) -> Path:
    key = _recipe_key(building_type, config)
    return config.cache_dir / (
        f"sweep_run_{config.mode}_{building_type.lower()}_"
        f"{config.vintage}_{config.location}_{key}"
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def run_one(building_type: str, config: SweepConfig) -> dict[str, object]:
    try:
        osm, cache_hit = generate(building_type, config)
    except GenerationError as error:
        return {
            "type": building_type,
            "verdict": "GEN-FAIL",
            "detail": str(error),
            "mode": config.mode,
            "vintage": config.vintage,
            "location": config.location,
            "fuel": config.fuel,
            "ecm": config.ecm,
            "report": {},
        }

    load_model, above_ground_storeys, performance_compliance, preflight_error = (
        _pipeline_dependencies()
    )
    run_dir = _run_dir(building_type, config)
    shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir(parents=True)
    epw, ddy, hdd = _location(config)
    annual = config.mode in ("annual", "full")
    run_period = None
    if config.mode == "annual":
        run_period = {
            "begin_month": 1,
            "begin_day": 1,
            "end_month": 1,
            "end_day": 7,
        }

    try:
        model = load_model(str(osm))
        result = performance_compliance(
            model,
            vintage=config.vintage,
            simulate="annual" if annual else "sizing",
            hdd=hdd,
            weather={"epw": str(epw), "ddy": str(ddy)},
            building={"storeys": above_ground_storeys(model)},
            run_dir=str(run_dir),
            run_period=run_period,
        )
        reference = result.reference_model
        detail = (
            f"zones={len(reference.getThermalZones())} "
            f"air_loops={len(reference.getAirLoopHVACs())} "
            f"plant_loops={len(reference.getPlantLoops())} "
            "ervs="
            f"{len(reference.getHeatExchangerAirToAirSensibleAndLatents())} "
            f"warnings={len(result.audit.warnings)}"
        )
        report_summary = normalized_report_summary(result)
        if annual:
            proposed = report_summary["proposed"].get("total_site_kwh") or 0
            reference_kwh = report_summary["reference"].get("total_site_kwh") or 0
            detail += (
                f" | proposed={float(proposed):.0f} ref={float(reference_kwh):.0f} kWh "
                f"compliant={report_summary['compliant']!r} "
                f"tier={report_summary['tier']!r} "
                f"({float(report_summary['percent_of_target'] or 0):.0f}% of target)"
            )
        return {
            "type": building_type,
            "verdict": "PASS",
            "detail": detail,
            "mode": config.mode,
            "vintage": config.vintage,
            "location": config.location,
            "fuel": config.fuel,
            "ecm": config.ecm,
            "oracle_cache_hit": cache_hit,
            "report": report_summary,
        }
    except preflight_error as error:
        detail = " ".join(str(error).splitlines()[:4]).strip()[:300]
        verdict = "PREFLIGHT-REFUSAL"
    except Exception as error:
        detail = f"{type(error).__name__}: {str(error)[:200]}"
        verdict = "ERROR"
    return {
        "type": building_type,
        "verdict": verdict,
        "detail": detail,
        "mode": config.mode,
        "vintage": config.vintage,
        "location": config.location,
        "fuel": config.fuel,
        "ecm": config.ecm,
        "oracle_cache_hit": cache_hit,
        "report": {},
    }


def _worker_command(building_type: str, config: SweepConfig) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).resolve()),
        "--one", building_type,
        "--mode", config.mode,
        "--vintage", config.vintage,
        "--location", config.location,
        "--workers", "1",
        "--cache-dir", str(config.cache_dir),
        "--fuel", config.fuel,
        "--ecm", config.ecm,
    ]


def _resumed_result(building_type: str, config: SweepConfig) -> dict | None:
    if not config.resume:
        return None
    path = _result_path(building_type, config)
    try:
        result = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    expected = {
        "type": building_type,
        "mode": config.mode,
        "vintage": config.vintage,
        "location": config.location,
        "fuel": config.fuel,
        "ecm": config.ecm,
    }
    return result if all(result.get(key) == value for key, value in expected.items()) else None


def run_workers(building_types: list[str], config: SweepConfig,
                popen=subprocess.Popen) -> list[dict]:
    pending = []
    results = {}
    for building_type in ordered_types(building_types):
        resumed = _resumed_result(building_type, config)
        if resumed is None:
            pending.append(building_type)
        else:
            results[building_type] = resumed
            print(f"  resumed {building_type}", file=sys.stderr)

    running = {}
    while pending or running:
        while pending and len(running) < config.workers:
            building_type = pending.pop(0)
            child = popen(
                _worker_command(building_type, config),
                cwd=str(PYTHON_ROOT),
                stdout=subprocess.PIPE,
                text=True,
            )
            running[child] = building_type
            print(
                f"  started {building_type} "
                f"({len(running)}/{config.workers} busy, {len(pending)} queued)",
                file=sys.stderr,
            )

        done = [child for child in running if child.poll() is not None]
        if not done:
            next(iter(running)).wait()
            done = [child for child in running if child.poll() is not None]
        for child in done:
            building_type = running.pop(child)
            raw = (child.stdout.read() if child.stdout else "").strip()
            try:
                outcome = json.loads(raw.splitlines()[-1])
            except (json.JSONDecodeError, IndexError):
                outcome = {
                    "type": building_type,
                    "verdict": "ERROR",
                    "detail": f"worker exited {child.returncode} with no JSON result",
                    "mode": config.mode,
                    "vintage": config.vintage,
                    "location": config.location,
                    "fuel": config.fuel,
                    "ecm": config.ecm,
                    "report": {},
                }
            results[building_type] = outcome
            _write_json(_result_path(building_type, config), outcome)
            print(f"  finished {building_type}: {outcome['verdict']}", file=sys.stderr)
    return [results[building_type] for building_type in building_types]


def structured_summary(building_types: list[str], results: list[dict],
                       config: SweepConfig) -> dict[str, object]:
    failed = [result["type"] for result in results if result.get("verdict") != "PASS"]
    return {
        "schema_version": 1,
        "mode": config.mode,
        "tier": "week" if config.mode == "annual" else config.mode,
        "vintage": config.vintage,
        "location": config.location,
        "fuel": config.fuel,
        "ecm": config.ecm,
        "workers": config.workers,
        "requested": building_types,
        "scheduled": ordered_types(building_types),
        "passed": len(results) - len(failed),
        "failed": failed,
        "results": results,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("types", nargs="*")
    parser.add_argument(
        "--mode", choices=("sizing", "annual", "full"),
        default=os.environ.get("SWEEP_MODE", "sizing"),
    )
    parser.add_argument(
        "--vintage", choices=("2020", "2025"),
        default=os.environ.get("VINTAGE", "2020"),
    )
    parser.add_argument(
        "--location", choices=tuple(LOCATIONS),
        default=os.environ.get("LOC", "toronto"),
    )
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    parser.add_argument("--fuel", default=os.environ.get("FUEL", "Electricity"))
    parser.add_argument("--ecm", default=os.environ.get("ECM", "NECB_Default"))
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--one", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        workers = args.workers if args.workers is not None else default_workers()
    except ValueError as error:
        parser.error(str(error))
    if workers < 1:
        parser.error("--workers must be at least 1")
    config = SweepConfig(
        mode=args.mode,
        vintage=args.vintage,
        location=args.location,
        workers=workers,
        cache_dir=args.cache_dir,
        resume=args.resume,
        fuel=args.fuel,
        ecm=args.ecm,
    )

    if args.one:
        outcome = run_one(args.one, config)
        _write_json(_result_path(args.one, config), outcome)
        print(json.dumps(outcome, sort_keys=True))
        return 0 if outcome["verdict"] == "PASS" else 1

    building_types = selected_types(args.types)
    memory = detected_memory_gb()
    memory_label = (
        f"{memory:.0f} GB RAM, {MEM_PER_WORKER_GB:.1f} GB budgeted per run"
        if memory is not None else "memory unknown"
    )
    print(
        f"running {len(building_types)} building(s) {workers} at a time "
        f"({os.cpu_count() or 1} cores, {memory_label}; --workers overrides)",
        file=sys.stderr,
    )
    results = run_workers(building_types, config)
    summary = structured_summary(building_types, results, config)
    summary_path = args.summary or config.cache_dir / (
        f"summary_{config.mode}_{config.vintage}_{config.location}.json"
    )
    _write_json(summary_path, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"summary -> {summary_path}", file=sys.stderr)
    return 0 if not summary["failed"] else 1


if __name__ == "__main__":
    sys.exit(main())