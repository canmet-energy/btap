"""btap.necb — every NECB 2020/2025 Part 8 rule (port of the btap-necb gem).

The code-compliance layer: the five rule domains (loads, lighting, shw,
envelope, hvac) compose btap.modeling's authoring machinery and btap.costing
into the full Part 8 determination. This is the ONLY package allowed to run
EnergyPlus (through btap.simulation) — the domains below are SDK-only.

Two citation axes run through every audit entry here (D-44): ``article``
cites the code that mandates a value; ``ruling`` cites the adjudicated
decision (D-XX) recording how we read it. Audit text convention: violations
SHOUTED, passes lowercase — the report's checklist classifier is
deliberately case-SENSITIVE.

Vintages are '2020' and '2025' only. Import domains directly
(``from btap.necb import loads``). The umbrella pipeline is
``performance_compliance`` (M6); the CLI is ``btap.necb.cli`` (console
script ``btap-compliance``).
"""

from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def performance_compliance(model, **kwargs):
    """The NECB Part 8 performance-path pipeline — see
    :func:`btap.necb.compliance.performance_compliance`. Imported lazily so
    ``btap.necb`` stays importable without the SDK."""
    from btap.necb import compliance

    return compliance.performance_compliance(model, **kwargs)
