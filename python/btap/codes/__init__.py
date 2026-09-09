"""btap.codes — the code-compliance layer (port of the btap-necb gem).

One subpackage per code family: ``btap.codes.necb`` holds every NECB 2020/2025
Part 8 rule as five domains (loads, lighting, shw, envelope, hvac), which
compose btap.modeling's authoring machinery and btap.costing into the full
Part 8 determination driven from ``compliance`` here. This is the ONLY package
allowed to run EnergyPlus (through btap.simulation) — the domains are SDK-only.

``data/`` here is deliberately code-family-NEUTRAL: the decisions registry and
the Section 8.4 article caches. The NECB rule tables live one level down, in
``btap/codes/necb/data/``.

Two citation axes run through every audit entry here (D-44): ``article``
cites the code that mandates a value; ``ruling`` cites the adjudicated
decision (D-XX) recording how we read it. Audit text convention: violations
SHOUTED, passes lowercase — the report's checklist classifier is
deliberately case-SENSITIVE.

Vintages are '2020' and '2025' only. Import domains directly
(``from btap.codes.necb import loads``). The umbrella pipeline is
``performance_compliance`` (M6); the CLI is ``btap.codes.cli`` (console
script ``btap-compliance``).
"""

from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def performance_compliance(model, **kwargs):
    """The NECB Part 8 performance-path pipeline — see
    :func:`btap.codes.compliance.performance_compliance`. Imported lazily so
    ``btap.codes`` stays importable without the SDK."""
    from btap.codes import compliance

    return compliance.performance_compliance(model, **kwargs)
