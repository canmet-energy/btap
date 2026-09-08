"""btap.codes.necb — the NECB code family (National Energy Code of Canada for
Buildings, 2020 and 2025).

The five rule domains (loads, lighting, shw, envelope, hvac) live here and
compose btap.modeling's authoring machinery and btap.costing into the Part 8
determination driven from ``btap.codes.compliance``. Import domains directly
(``from btap.codes.necb import loads``).

``editions/`` holds the modules that belong to one edition only —
``editions/necb2025/`` today.
"""

from pathlib import Path

#: The NECB rule tables and article-coverage manifests. The code-family-neutral
#: data (the decisions registry, the Section 8.4 caches) lives in
#: ``btap.codes.DATA_DIR`` instead.
DATA_DIR = Path(__file__).parent / "data"
