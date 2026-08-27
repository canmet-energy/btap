"""The HVAC domain of btap.necb: reference-system selection (8.4.4.7-.19),
Part 5/8.4.4 efficiency application, energy recovery, and the economizer/
fan-curve checker. Drives btap.modeling's builders and btap.costing's
quantities.

Port note (D-79): Ruby's one `BtapNECB::HVAC` module is spread over four files
that reopen it; Python cannot have two files contribute to one module, so the
four become four submodules and THIS facade re-exports the public surface. The
Ruby `Efficiency` / `Checker` nested modules are the `efficiency` / `checker`
submodules — import them directly for the internals the suites exercise.
"""

from __future__ import annotations

from btap.necb.hvac import checker, efficiency, energy_recovery, reference
from btap.necb.hvac.checker import check_part5
from btap.necb.hvac.efficiency import apply_efficiencies, prepare_for_resizing
from btap.necb.hvac.energy_recovery import (
    annual_availability_hours,
    apply_energy_recovery,
    erv_threshold_verdict,
)
from btap.necb.hvac.reference import (
    Assignment,
    ReferenceResult,
    apply_economizer_thresholds,
    heat_pump_aux_energy_type,
    optional_flow,
    reference_hvac,
    rules,
    select_reference_systems,
)

__all__ = [
    "Assignment",
    "ReferenceResult",
    "annual_availability_hours",
    "apply_economizer_thresholds",
    "apply_efficiencies",
    "apply_energy_recovery",
    "check_part5",
    "checker",
    "efficiency",
    "energy_recovery",
    "erv_threshold_verdict",
    "heat_pump_aux_energy_type",
    "optional_flow",
    "prepare_for_resizing",
    "reference",
    "reference_hvac",
    "rules",
    "select_reference_systems",
]
