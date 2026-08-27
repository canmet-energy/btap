"""btap.costing.envelope — envelope + thermal-bridging costing (port of the
btap-costing gem's Envelope domain).

Facade: ``cost(model, ...)`` -> ``Report`` (the Ruby
``BtapCosting::Envelope.cost``). The domain modules — database, interpolate,
assemblies, quantify, envelope_costs, thermal_bridging_costs — are importable
directly for finer-grained use (the parity/golden gates do).
"""

from btap.costing.envelope.report import Report, cost

__all__ = ["Report", "cost"]
