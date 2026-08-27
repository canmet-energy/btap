"""btap.costing — pricing of model objects (port of the btap-costing gem).

HVAC equipment BOMs, envelope assemblies, lighting fixtures, and SHW — one
package owning the whole licensed-data seam. The vendored CSVs under
``data/`` are PLACEHOLDER schema copies; real RS-Means values are injected
at runtime (costs_csv=/local_factors_csv= kwargs, or BTAP_COSTING_DIR /
OPENSTUDIO_COSTING_DIR) and are never committed or redistributed.

Dependency direction is the design (D-77): costing imports btap.modeling
and btap.audit, NEVER btap.necb. Where a costing rule needs NECB-owned
geometry (the daylighted-area sensors), the NECB layer passes a provider in.
Sub-namespaced (hvac/envelope/lighting + shw) because Database/Report exist
per domain; import the domain modules directly.
"""
