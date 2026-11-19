"""The fan-coil mode-specific sizing marker (D-106, D-107, D-110).

A marked `ZoneHVAC:FourPipeFanCoil` is translated with a
`DesignSpecification:ZoneHVAC:Sizing` that rates each water coil at its OWN
operating mode's design airflow (``btap.simulation.translation`` applies it).
Unmarked, EnergyPlus fixes both coils to the larger unit maximum early in
autosizing; in a heating-dominated zone the cooling coil then rates at the
heating airflow and its UA inversion can fail — the #68 / #236 Severe.

It lives at the package root, not in ``btap.simulation``, because two
packages that may not import each other both need it: the translator that
honours the marker, and ``btap.modeling``'s builders, which mark the fan
coils they author (D-110). One definition, so the flag both read cannot
drift. It needs no SDK import: it only writes an additionalProperties flag.
"""

from __future__ import annotations

FAN_COIL_MODE_SPECIFIC_AIRFLOW_FEATURE = "btap_fan_coil_mode_specific_sizing_airflows"


def mark_fan_coil_for_mode_specific_sizing(fan_coil):
    """Require separate cooling/heating sizing airflow for this fan coil."""
    fan_coil.additionalProperties().setFeature(FAN_COIL_MODE_SPECIFIC_AIRFLOW_FEATURE, True)
