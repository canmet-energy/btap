"""Lighting fixture costing (port of btap-costing lighting/fixtures.rb).

Port of legacy cost_audit_lighting: per tagged space, the lighting_sets row
(template x building_type x space_type x CFL/LED) picks a fixture type by
average ceiling-height bin (<7.88 ft / 7.88-15.75 / >15.75); the fixture's
id_layers x quantity multipliers price through materials_lighting -> costs ->
regional factors, x floor area (ft2) x zone multiplier.

Fidelity notes (audited):
- legacy detect ignores the sets sheet's min/max_stories columns (first
  match wins) — preserved;
- legacy FORCES light type LED whenever the template is NECB2020 regardless
  of the modeled lights; this port detects the ACTUAL Lights definitions
  ('- LED lighting' suffix) and only falls back to the template assumption
  when a type cannot be detected — deviation audited;
- daylighting-sensor costing IS ported (see SENSOR_BOM + daylighting_note
  below — the legacy per-sensor BOM driven by the daylighted-area rule);
  an earlier version of this header said otherwise, from before the
  sensor port landed. Models without daylighting controls cost $0 there
  exactly like legacy;
- the legacy per-zone `total_with_region` initialization (which made
  'Nil'-fixture spaces report the previous space's cost) was fixed
  upstream by #2119 to a per-space reset — this gem always did the
  per-space equivalent (`zero_line`), so the two now agree; previously
  this was an undocumented divergence.
"""

from __future__ import annotations

import math
import re

import openstudio

from btap._compat import opt, ruby_round, sorted_by_name
from btap.costing.lighting.database import to_f, to_i, to_s

HEIGHT_COLUMNS = (
    (7.88, "Fixture_type_less_than_7.88ft_ht"),
    (15.75, "Fixture_type_7.88_to_15.75ft_ht"),
    (math.inf, "Fixture_type_greater_than_>15.75ft_ht"),
)


# daylighting_areas: a callable (space) -> {'sidelighted_m2':, 'skylight_m2':}
# supplied by the NECB layer. Costing owns no daylighted-area geometry —
# that is rule machinery — so when the model HAS daylighting controls and
# no provider is given, this raises rather than silently under-costing.
def cost(model, *, database, vintage, province_state, city, audit, daylighting_areas=None):
    template = f"NECB{vintage}"
    section = {"space_report": [], "fixture_report": [], "total_lighting_cost": 0.0}
    total = 0.0

    for zone in sorted_by_name(model.getThermalZones()):
        for space in sorted_by_name(zone.spaces()):
            line = cost_space(space, zone, database, template, province_state, city, audit)
            if line is None:
                continue
            total += line["cost"]
            section["space_report"].append(line)
            accumulate_fixture(section["fixture_report"], line)

    total += daylighting_note(model, database, template, province_state, city, section, audit,
                              daylighting_areas=daylighting_areas)
    section["total_lighting_cost"] = ruby_round(total, 2)
    audit.decision("costing_lighting", "lighting fixtures costed by space (ceiling-height fixture bins)",
                   inputs={"spaces": len(section["space_report"]), "template": template},
                   value=f"${ruby_round(total, 2)}")
    return section


def cost_space(space, zone, database, template, province_state, city, audit):
    space_type_obj = opt(space.spaceType())
    if (space_type_obj is None or opt(space_type_obj.standardsSpaceType()) is None
            or opt(space_type_obj.standardsBuildingType()) is None):
        audit.warn("costing_lighting",
                   f"space '{space.nameString()}' has no standards space type — not costed")
        return None

    space_type = opt(space_type_obj.standardsSpaceType())
    building_type = opt(space_type_obj.standardsBuildingType())
    light_type = detect_light_type(space, template, audit)

    def match(type_):
        for row in database.lighting_sets:
            if (re.sub(r"\s*", "", to_s(row["template"])) == template
                    and to_s(row["building_type"]).lower() == building_type.lower()
                    and to_s(row["space_type"]).lower() == space_type.lower()
                    and (type_ is None or to_s(row["Type"]).lower() == type_.lower())):
                return row
        return None

    set_row = match(light_type)
    if set_row is None and light_type is not None:
        # the NECB2020 sets are LED-only (which is why legacy hard-forces LED
        # for that template) — fall back to whatever type the sheet carries
        set_row = match(None)
        if set_row is not None:
            audit.info("costing_lighting",
                       f"no {light_type} lighting set for {template} — costed with the sheet's "
                       f"{set_row['Type']} set (the {template} catalog carries only {set_row['Type']})",
                       target=space.nameString())
            light_type = set_row["Type"]
    if set_row is None:
        audit.warn("costing_lighting",
                   f"no lighting_sets row for [{template}, {building_type}, {space_type}, "
                   f"{light_type}] — not costed",
                   target=space.nameString())
        return None

    floor_area_m2 = space.floorArea()
    if floor_area_m2 <= 0:
        return None

    ceiling_ft = opt(openstudio.convert(space.volume() / floor_area_m2, "m", "ft"))
    floor_ft2 = opt(openstudio.convert(floor_area_m2, "m^2", "ft^2"))
    column = next(col for limit, col in HEIGHT_COLUMNS if ceiling_ft < limit)
    fixture_type = set_row[column]
    if to_s(fixture_type) == "Nil" or to_s(fixture_type) == "":
        return zero_line(space, zone, fixture_type, ceiling_ft, floor_ft2)

    fixture = next((row for row in database.lighting
                    if to_s(row["lighting_type_id"]) == to_s(fixture_type)), None)
    if fixture is None:
        raise ValueError(f"no lighting row for fixture type id {fixture_type}")

    multiplier = zone.multiplier()
    material_total = 0.0
    labour_total = 0.0
    regional = [100.0, 100.0]
    ids = _split_csv_field(fixture["id_layers"])
    mults = _split_csv_field(fixture["Id_layers_quantity_multipliers"])
    for i, layer_id in enumerate(ids):
        layer_mult = mults[i] if i < len(mults) else None  # Ruby zip pads with nil
        material = next((row for row in database.materials_lighting
                         if to_s(row["lighting_type_id"]) == to_s(layer_id)), None)
        if material is None:
            raise ValueError(f"lighting material {layer_id} not in materials_lighting")

        costs = database.cost_record(material["id"])
        material_total += costs["materialOpCost"] * to_f(layer_mult) * floor_ft2 * multiplier
        labour_total += costs["laborOpCost"] * to_f(layer_mult) * floor_ft2 * multiplier
        regional = database.regional_factors(province_state, city, material["id"])
    cost_ = material_total * regional[0] / 100.0 + labour_total * regional[1] / 100.0

    audit.info("costing_lighting", "space lighting fixtures costed",
               target=space.nameString(),
               inputs={"fixture_type": fixture_type,
                       "light_type": light_type if light_type is not None else set_row["Type"],
                       "ceiling_ft": ruby_round(ceiling_ft, 1),
                       "floor_ft2": ruby_round(floor_ft2 * multiplier, 1)},
               value=f"${ruby_round(cost_, 2)}", evidence=to_s(fixture["description"])[0:80])
    return {"space": space.nameString(), "zone": zone.nameString(),
            "building_type": building_type, "space_type": space_type,
            "zone_multiplier": multiplier, "fixture_type": fixture_type,
            "fixture_description": fixture["description"],
            "height_avg_ft": ruby_round(ceiling_ft, 1),
            "floor_area_ft2": ruby_round(floor_ft2 * multiplier, 1),
            "cost": ruby_round(cost_, 2),
            "cost_per_ft2": ruby_round(cost_ / (floor_ft2 * multiplier), 2)}


# Actual-model detection first; template assumption only as fallback (legacy
# unconditionally forces LED for NECB2020 — deviation audited at cost()).
def detect_light_type(space, template, _audit):
    space_type = opt(space.spaceType())
    if space_type is None:
        return None

    lights = space_type.lights()
    if len(lights) == 0:
        return "LED" if template in ("NECB2020", "NECB2025") else "CFL"

    if any("LED lighting" in fixture.lightsDefinition().nameString() for fixture in lights):
        return "LED"
    return "CFL"


def zero_line(space, zone, fixture_type, ceiling_ft, floor_ft2):
    return {"space": space.nameString(), "zone": zone.nameString(),
            "building_type": opt(opt(space.spaceType()).standardsBuildingType()),
            "space_type": opt(opt(space.spaceType()).standardsSpaceType()),
            "zone_multiplier": zone.multiplier(), "fixture_type": to_s(fixture_type),
            "fixture_description": "", "height_avg_ft": ruby_round(ceiling_ft, 1),
            "floor_area_ft2": ruby_round(floor_ft2 * zone.multiplier(), 1),
            "cost": 0.0, "cost_per_ft2": 0.0}


def accumulate_fixture(report, line):
    row = next((r for r in report if r["fixture_type"] == line["fixture_type"]), None)
    if row is None:
        report.append({"fixture_type": line["fixture_type"],
                       "fixture_description": line["fixture_description"],
                       "floor_area_ft2": line["floor_area_ft2"], "cost": line["cost"],
                       "spaces": [line["space"]], "number_of_spaces": 1})
    else:
        row["floor_area_ft2"] = ruby_round(row["floor_area_ft2"] + line["floor_area_ft2"], 1)
        row["cost"] = ruby_round(row["cost"] + line["cost"], 2)
        row["spaces"].append(line["space"])
        row["number_of_spaces"] = len(row["spaces"])


# Daylighting-sensor costing (port of cost_audit_daylighting_sensor_control's
# per-sensor BOM: sensor row 407 + wiring row 10 x 0.3 CLF + PVC conduit row
# 17 x 30 LF + box row 14, per sensor x zone multiplier). Sensor counts:
# ceil(fixtures / 4) per zone — DEVIATION (audited): legacy derives the
# fixture count from the DAYLIGHTED-AREA portion (primary sidelighted /
# under-skylight geometry, not yet ported); this port uses the zone's whole
# floor area x the fixture density, an upper bound.
SENSOR_BOM = ((407, 1.0, "daylight sensor (remote, dimming)"),
              (10, 30.0 / 100.0, "sensor wiring (30 ft)"),
              (17, 30.0, "sensor PVC conduit (30 ft)"),
              (14, 1.0, "sensor box"))


# Daylighting-sensor costing — the legacy daylighted-area rule
# (cost_audit_daylighting_sensor_control): per controlled zone,
# fixtures = sum over spaces of ceil(ft2/1000 x Fix_1000ft.to_i);
# sidelighted sensors = ceil(ceil(fixtures x primary_sidelighted_area /
# zone_area) / 4); skylight sensors likewise from the under-skylight area.
# Each sensor is the legacy BOM x zone multiplier.
def daylighting_note(model, database, template, province_state, city, section, audit,
                     daylighting_areas=None):
    zones = [z for z in sorted_by_name(model.getThermalZones())
             if opt(z.primaryDaylightingControl()) is not None]
    if not zones:
        audit.info("costing_lighting",
                   "no daylighting controls in the model — daylighting-sensor costing $0 (matches legacy)")
        return 0.0

    if daylighting_areas is None:
        raise ValueError(
            "model has daylighting controls but no daylighting_areas: provider was given — "
            "pass one (the NECB layer supplies it) so sensors are not silently under-costed")

    total = 0.0
    sensors_total = 0
    for zone in zones:
        data = zone_daylighting_data(zone, database, template, daylighting_areas)
        if data["fixtures"] == 0 or data["area_m2"] == 0:
            continue

        side_sensors = math.ceil(
            math.ceil(data["fixtures"] * data["sidelighted_m2"] / data["area_m2"]) / 4.0
        ) * zone.multiplier()
        sky_sensors = math.ceil(
            math.ceil(data["fixtures"] * data["skylight_m2"] / data["area_m2"]) / 4.0
        ) * zone.multiplier()
        sensors = side_sensors + sky_sensors
        if sensors == 0:
            continue

        sensors_total += sensors
        for layer_id, quantity, label in SENSOR_BOM:
            material = next((row for row in database.materials_lighting
                             if to_s(row["lighting_type_id"]) == to_s(layer_id)), None)
            if material is None:
                continue

            costs = database.cost_record(material["id"])
            regional = database.regional_factors(province_state, city, material["id"])
            line = (costs["materialOpCost"] * regional[0] / 100.0 +
                    costs["laborOpCost"] * regional[1] / 100.0) * quantity * sensors
            total += line
            audit.info("costing_lighting", f"daylighting {label}", target=zone.nameString(),
                       inputs={"sidelighted_sensors": side_sensors, "skylight_sensors": sky_sensors,
                               "quantity_each": quantity}, value=f"${ruby_round(line, 2)}")
    audit.decision("costing_lighting",
                   "daylighting sensors costed from the DAYLIGHTED-AREA fixture ratio (legacy rule: "
                   "ceil(ceil(fixtures x area ratio)/4) per aperture type per controlled zone)",
                   inputs={"zones": len(zones), "sensors": sensors_total},
                   value=f"${ruby_round(total, 2)}",
                   article="NECB 2011 4.2.2.4./4.2.2.5./4.2.2.9. (legacy costing rule; 4.2.2.9. does not exist in NECB 2020/2025)")
    section["daylighting_sensor_cost"] = ruby_round(total, 2)
    return total


# Zone fixture count (per-space ceil, Fix_1000ft truncated to integer as
# legacy does) + accumulated daylighted areas + zone floor area.
def zone_daylighting_data(zone, database, template, daylighting_areas):
    fixtures = 0
    area_m2 = 0.0
    sidelighted = 0.0
    skylight = 0.0
    for space in sorted_by_name(zone.spaces()):
        space_type_obj = opt(space.spaceType())
        if space_type_obj is None or opt(space_type_obj.standardsSpaceType()) is None:
            continue
        if "undefined" in space_type_obj.nameString().lower():
            continue

        space_type = opt(space_type_obj.standardsSpaceType())
        # bare .get in the Ruby (unguarded) — a missing standardsBuildingType
        # raises here exactly as it does there
        building_type = space_type_obj.standardsBuildingType().get()
        set_row = next(
            (row for row in database.lighting_sets
             if re.sub(r"\s*", "", to_s(row["template"])) == template
             and to_s(row["building_type"]).lower() == building_type.lower()
             and to_s(row["space_type"]).lower() == space_type.lower()),
            None)
        if set_row is not None:
            floor_ft2 = opt(openstudio.convert(space.floorArea(), "m^2", "ft^2"))
            height_ft = max_space_height_ft(space)
            column = next(col for limit, col in HEIGHT_COLUMNS if height_ft < limit)
            fixture = next((row for row in database.lighting
                            if to_s(row["lighting_type_id"]) == to_s(set_row[column])), None)
            if fixture is not None:
                fixtures += math.ceil(floor_ft2 / 1000.0 * to_i(fixture["Fix_1000ft"]))
        area_m2 += space.floorArea()
        areas = daylighting_areas(space)
        sidelighted += to_f(areas.get("sidelighted_m2"))
        skylight += to_f(areas.get("skylight_m2"))
    return {"fixtures": fixtures, "area_m2": area_m2,
            "sidelighted_m2": sidelighted, "skylight_m2": skylight}


# Legacy DSC uses the max wall-vertex height (not volume/area) for the bin.
def max_space_height_ft(space):
    height = 0.0
    for wall in (s for s in space.surfaces() if s.surfaceType() == "Wall"):
        zs = [v.z() for v in wall.vertices()]
        top = max(zs) if zs else None
        if top is not None and top > height:
            height = top
    return opt(openstudio.convert(height, "m", "ft"))


def _split_csv_field(value):
    """Ruby ``value.to_s.split(/\\s*,\\s*/)`` — '' splits to [] and trailing
    empty strings are dropped."""
    s = to_s(value)
    if s == "":
        return []
    parts = re.split(r"\s*,\s*", s)
    while parts and parts[-1] == "":
        parts.pop()
    return parts
