#!/usr/bin/env python3
"""Run ONE frozen API scenario in an isolated subprocess.

``timeout_s`` reaches only the ``subprocess.run`` inside ``_execute_cli``;
an in-process ``_execute_api`` could not be stopped, so a 40-90 minute
determination scenario had no way to fail rather than hang. This worker is
the other half of that fix: ``runner._execute_api`` spawns it with the
scenario's timeout and reads back what it wrote.

Usage: ``api_worker.py <resolved-api_call.json> <run_dir>``

The json is the scenario's ``api_call`` with every placeholder already
resolved by the parent. ``"model"`` is POPPED from it: present, it is a
path loaded through ``btap._sdk.load_model``; absent, the shared
``compliance_fixture()`` stands in — which is what the pre-existing
``api-thermal-bridging`` scenario relies on. Everything else is passed
through to ``performance_compliance`` verbatim.

On success ``<run_dir>/observations.json`` carries the structured
observations the ``asserts`` block addresses; the ``exit`` key comes from
the PRODUCT's own ``cli.verdict_exit`` (never a reimplementation here), so
``expect_exit`` is checked against the same classifier every CLI scenario
goes through. On failure the same file carries ``error``/``traceback`` and
the process exits non-zero.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
PYTHON_ROOT = REPO_ROOT / "python"

OBSERVATIONS = "observations.json"


def _write(run_dir, payload):
    (Path(run_dir) / OBSERVATIONS).write_text(
        json.dumps(payload, indent=1, default=str) + "\n", encoding="utf-8")


def run(call, run_dir):
    """:return: the observations dict for a resolved ``api_call``."""
    from btap.necb import cli, performance_compliance

    kwargs = dict(call)
    model_path = kwargs.pop("model", None)
    if model_path is not None:
        from btap._sdk import load_model
        model = load_model(str(model_path))
    else:
        # No model: the fixture the in-process executor always used.
        from tests.necb.support import compliance_fixture
        model = compliance_fixture()

    result = performance_compliance(model, run_dir=str(run_dir), **kwargs)
    return {
        "exit": cli.verdict_exit(result),
        "compliant": result.compliant,
        "reference_model_present": result.reference_model is not None,
        # The WHOLE report, so an assertion can address any key without
        # this worker having to know which keys a scenario cares about.
        "report": result.report,
    }


def main(argv):
    call_path, run_dir = Path(argv[1]), Path(argv[2])
    run_dir.mkdir(parents=True, exist_ok=True)
    if str(PYTHON_ROOT) not in sys.path:
        sys.path.insert(0, str(PYTHON_ROOT))
    try:
        call = json.loads(call_path.read_text(encoding="utf-8"))
        observations = run(call, run_dir)
    except BaseException as error:  # noqa: BLE001 — a crash must be readable
        _write(run_dir, {"error": repr(error),
                         "traceback": traceback.format_exc()})
        return 1
    _write(run_dir, observations)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
