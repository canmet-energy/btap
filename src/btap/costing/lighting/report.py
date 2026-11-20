"""Lighting costing facade (port of btap-costing lighting/report.rb)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from btap.audit import AuditLog
from btap.costing import _location
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
def cost(model, *, code="necb2020", city=None, province_state=None,
         costs_csv=None, local_factors_csv=None, audit=None, daylighting_areas=None):
    """Cost the model's lighting fixtures.

    ``code`` is the code id (``"necb2020"``), the one public selector (D-87);
    it picks the fixture table's ``NECB<year>`` rows. It was ``edition="2020"``
    until #237. btap.costing may not import btap.codes, so the id's SHAPE is
    checked here and an id with no rows simply prices nothing.
    """
    match = re.fullmatch(r"necb(\d{4})", str(code))
    if match is None:
        raise ValueError(f"code must be a code id such as 'necb2020', not {code!r}")
    edition = match.group(1)
    if audit is None:
        audit = AuditLog()
    database = Database(costs_csv=costs_csv, local_factors_csv=local_factors_csv)

    if city is None or province_state is None:
        site = model.getSite()
        location = _location.site_location(database.closest_location, site)
        if city is None:
            city = location["city"]
        if province_state is None:
            province_state = location["province_state"]
        audit.info("costing_lighting", "cost location resolved from the model site",
                   value=f"{city}, {province_state}")
    city, province_state = _location.canonical(database._locations, city, province_state)

    section = fixtures.cost(model, database=database, edition=edition,
                            province_state=province_state, city=city, audit=audit,
                            daylighting_areas=daylighting_areas)
    for w in database.warnings:
        audit.warn("costing_lighting", w)
    return Report(total=section["total_lighting_cost"], lighting=section,
                  warnings=[w["action"] for w in audit.warnings],
                  city=city, province_state=province_state, audit=audit)
