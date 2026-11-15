"""The envelope-costing facade (port of btap-costing's envelope/report.rb):
one ``cost`` call — model in, priced envelope (and optionally thermal-bridge
edges) out — plus the ``Report`` result record.

``Report``'s field ORDER is load-bearing (Ruby Struct contract): total,
envelope, thermal_bridging, warnings, city, province_state, audit.
"""

from __future__ import annotations

from dataclasses import dataclass

from btap._compat import ruby_round, ruby_str
from btap.audit import AuditLog
from btap.costing.envelope import assemblies, envelope_costs, thermal_bridging_costs
from btap.costing.envelope.database import Database


@dataclass
class Report:
    total: float
    envelope: dict
    thermal_bridging: dict | None
    warnings: list
    city: str
    province_state: str
    audit: object


def cost(model, *, city=None, province_state=None, structure=None,
         performance="lp", tbd_result=None, tb_tallies=None, tb_quality="good",
         costs_csv=None, local_factors_csv=None, audit=None) -> Report:
    """Cost a model's envelope (and optionally its thermal-bridge edges).

    model: openstudio.model.Model
    city: cost location; None => nearest city to the model's site
    province_state: as city
    structure: dict {'framing': 'steel'|'wood'|'cmu', 'cladding':, 'finish':}
      — drives the costed wall assembly (default: steel-framed)
    performance: 'lp' or 'hp' assembly tier
    tbd_result: a TBD.process result dict — edges are tallied and costed, and
      the parapet allowance is applied (produce one with the pinned py-tbd
      engine — the [tbd] extra, M7)
    tb_tallies: pre-built {edge_type: {wall_ref: m}} tallies (legacy shape);
      takes precedence over tbd_result
    tb_quality: 'good' or 'bad' detail tier for the wall reference
    costs_csv: runtime-injected priced cost table
    local_factors_csv: runtime-injected localization table
    audit: shared AuditLog (compliance + costing in ONE log)
    """
    audit = audit if audit is not None else AuditLog()
    database = Database(costs_csv=costs_csv, local_factors_csv=local_factors_csv)

    if city is None or province_state is None:
        site = model.getSite()
        location = database.closest_location(site.latitude(), site.longitude())
        if city is None:
            city = location["city"]
        if province_state is None:
            province_state = location["province_state"]
        audit.info("costing_envelope", "cost location resolved from the model site",
                   value=f"{city}, {province_state}")

    tallies = tb_tallies
    if tallies is None and tbd_result is not None:
        wall_reference = (f"{assemblies.costed_assembly(structure, 'walls', performance)}"
                          f" {tb_quality}")
        tallies = thermal_bridging_costs.tallies_from_tbd(tbd_result, wall_reference)

    envelope = envelope_costs.cost(model, database=database,
                                   province_state=province_state, city=city,
                                   structure=structure, performance=performance,
                                   tb_tallies=tallies, audit=audit)
    tb_section = (thermal_bridging_costs.cost(tallies, database=database, audit=audit)
                  if tallies is not None else None)

    for warning in database.warnings:
        audit.warn("costing_envelope", warning)
    total = envelope["total_envelope_cost"] + (
        tb_section["total_thermal_bridging_cost"] if tb_section is not None else 0.0)
    audit.decision("costing_envelope", "envelope costing complete",
                   inputs={"envelope": envelope["total_envelope_cost"],
                           "thermal_bridging": (tb_section["total_thermal_bridging_cost"]
                                                if tb_section is not None
                                                else "not requested")},
                   value=f"${ruby_str(ruby_round(total, 2))}")

    return Report(total=ruby_round(total, 2), envelope=envelope,
                  thermal_bridging=tb_section,
                  warnings=[w["action"] for w in audit.warnings], city=city,
                  province_state=province_state, audit=audit)
