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
(``from btap.necb import loads``); the umbrella pipeline and CLI arrive
with M6.
"""

from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
