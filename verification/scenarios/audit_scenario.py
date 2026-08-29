"""The canonical scripted audit scenario (D-80 R4, replaces B5/B6's live
Ruby comparison as the frozen audit-unit baseline).

MOVED here from python/tests/audit/test_cross_language.py, where the
docstring's contract was: MUST mirror cross_language/ruby_reference.rb line
for line. At freeze time the Ruby driver still runs (the seal); after the
handoff this file plus the frozen baselines ARE the contract — the dormant
test keeps its own copy to rot with it.
"""

import sys
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parents[2] / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from btap.audit import AuditLog, emit_coverage  # noqa: E402


def build_scenario():
    """MUST mirror cross_language/ruby_reference.rb line for line — drift
    between the two copies is exactly what the comparison then fails on."""
    audit = AuditLog()

    with audit.with_building("input model"):
        audit.info("load", "model loaded — 1,000 m² floor area, climate 4200 HDD·°C",
                   inputs={"path": "model.osm", "spaces": 5})

    with audit.with_building("proposed building"):
        audit.decision("characterize", "zones grouped into one thermal block",
                       target="Thermal Zone 1",
                       inputs={"zones": ["Zone A", "Zone B"], "floor_area_m2": 123.456,
                               "conditioned": True},
                       value="System 6", article="8.4.4.8.(1)", ruling="D-14")
        audit.warn("efficiency", "boiler efficiency UNKNOWN",
                   inputs={"kw": 25.0, "fuel": "gas"}, evidence="OS:Boiler 'B1'")
        with audit.with_building("reference building"):
            audit.decision("build", "reference system operates on the proposed operating schedule",
                           article="8.4.4.7.(1)", ruling="D-14 D-21")
        audit.info("rules", "infiltration sentinel", value=1.5e-05)

    audit.decision("verdict", "proposed does not exceed the reference", value=True)
    audit.info("verdict", "margin below threshold", value=0)
    audit.info("verdict", "eui supplement computed", value=False)

    coverage = {
        "articles": [
            {"article": "8.4.4.7.", "title": "System selection", "status": "implemented",
             "how": "Table 8.4.4.7.-A", "code": "hvac/reference.rb#assign"},
            {"article": "8.4.4.9.", "title": "Staged heating", "status": "partial",
             "how": "two stages", "gaps": "modulating burners"},
            {"article": "8.4.1.1. (HVAC)", "title": "Modeller inputs", "status": "partial",
             "gap_owner": "modeller", "how": "schedules read from the model",
             "gaps": "occupancy assumptions"},
        ]
    }
    emit_coverage(coverage, audit)
    return audit
