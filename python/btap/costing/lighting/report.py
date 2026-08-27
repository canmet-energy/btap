"""Lighting costing facade (port of btap-costing lighting/report.rb)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from btap.audit import AuditLog
from btap.costing.lighting import fixtures
from btap.costing.lighting.database import Database


@dataclass
class Report:
    """Ruby ``Struct.new(:total, :lighting, :warnings, :city, :province_state,
    :audit, keyword_init: true)``."""

    total: Any = None
    lighting: Any = None
    warnings: Any = None
    city: Any = None
    province_state: Any = None
    audit: Any = None


# Cost a model's lighting fixtures. Same location/injection contract as the
# sibling domains' costing facades.
def cost(model, *, vintage="2020", city=None, province_state=None,
         costs_csv=None, local_factors_csv=None, audit=None, daylighting_areas=None):
    if audit is None:
        audit = AuditLog()
    database = Database(costs_csv=costs_csv, local_factors_csv=local_factors_csv)

    if city is None or province_state is None:
        site = model.getSite()
        location = database.closest_location(site.latitude(), site.longitude())
        if location is None:
            raise ValueError("pass city=/province_state= — locations.csv unavailable")

        if city is None:
            city = location["city"]
        if province_state is None:
            province_state = location["province_state"]
        audit.info("costing_lighting", "cost location resolved from the model site",
                   value=f"{city}, {province_state}")

    section = fixtures.cost(model, database=database, vintage=vintage,
                            province_state=province_state, city=city, audit=audit,
                            daylighting_areas=daylighting_areas)
    for w in database.warnings:
        audit.warn("costing_lighting", w)
    return Report(total=section["total_lighting_cost"], lighting=section,
                  warnings=[w["action"] for w in audit.warnings],
                  city=city, province_state=province_state, audit=audit)
