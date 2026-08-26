"""btap.simulation — run EnergyPlus on an OpenStudio model and get results
back, WITHOUT any compliance layer (port of the btap-simulation gem).

Depends on nothing else in the family but btap.audit's level of the stack
(in practice: only the SDK wheel and the provisioned engine). Two entry
points:

* ``run`` — the low-friction "just run a model" facade.
* ``btap.simulation.runner`` — the granular steps (attach_weather,
  run_energyplus, is_clean_run, energy_results, unmet_occupied_hours).

Execution is pluggable via a Backend: Local (in-process ForwardTranslator +
the provisioned ``energyplus`` binary — see engine.py) or Remote (an
AWS-Batch EnergyPlus service). The Ruby gem's Local drives the `openstudio`
CLI instead; the artifacts and parse surface are identical (D-79, M2).
"""

from __future__ import annotations

from dataclasses import dataclass

from btap.simulation import engine, runner
from btap.simulation.backends import Backend, Http, Local, Remote


@dataclass
class Result:
    """Result of a run. `clean` mirrors runner.is_clean_run; energy and
    unmet_hours are None for a sizing-only run (no annual results)."""

    run_dir: str
    clean: bool
    energy: dict | None
    unmet_hours: dict | None

    def is_clean(self) -> bool:
        return self.clean


def run(model, *, run_dir, weather=None, sizing_only=False, run_period=None, backend=None):
    """Run a model end to end and return a Result.

    weather: {'epw':, 'ddy':} — attached first if given.
    run_period: {'begin_month':, 'begin_day':, 'end_month':, 'end_day':}.
    backend: execution backend (the process default — Local — if None).
    """
    if weather:
        runner.attach_weather(model, epw=weather["epw"], ddy=weather["ddy"])
    out_dir = runner.run_energyplus(model, run_dir, sizing_only=sizing_only,
                                    run_period=run_period, backend=backend)
    return Result(
        run_dir=out_dir,
        clean=runner.is_clean_run(out_dir),
        energy=None if sizing_only else runner.energy_results(model),
        unmet_hours=None if sizing_only else runner.unmet_occupied_hours(model),
    )


__all__ = ["Backend", "Http", "Local", "Remote", "Result", "engine", "run", "runner"]
