"""SHW costing (port of btap-costing shw.rb).

Port of legacy shw_costing.rb on top of the btap.costing hvac costing engine
(Database/materials_hvac, Ledger with per-item regional factors,
geometry.building_data distances): tanks by fuel/efficiency class with the
largest-row multiplier rule, power vents for high-efficiency tanks, flues
(galvanized for regular fuel tanks incl. 20 ft headers; PVC for HE), electric
utility runs, gas/oil fuel lines, pumps (+VFD for variable), and the
10 ft-per-pump tank piping BOM. Distribution costing was never enabled in
legacy (shw_distribution_costing exists but is not called) — same here.

LEGACY DEFECT (fixed, audited; also fixed upstream by #2119): legacy gated the
gas fuel-line branch on ``num_reg_gas_tanks + num_reg_gas_tanks`` (the same
variable twice), so buildings whose ONLY gas tanks are high-efficiency got no
fuel line; both this port and the upstream legacy fix now use regular +
high-efficiency as intended, so behavior matches on both sides.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import openstudio

from btap._compat import opt, opt_or, ruby_round, sorted_by_name
from btap.audit import AuditLog
from btap.costing.hvac import geometry
from btap.costing.hvac.database import Database
from btap.costing.hvac.ledger import Ledger
from btap.costing.hvac.quantify_equipment import EquipmentQuantifier


@dataclass
class Report:
    """Ruby ``Struct.new(:total, :shw, :warnings, :city, :province_state,
    :audit, keyword_init: true)``."""

    total: Any = None
    shw: Any = None
    warnings: Any = None
    city: Any = None
    province_state: Any = None
    audit: Any = None


def cost(model, *, city=None, province_state=None, costs_csv=None, audit=None):
    if audit is None:
        audit = AuditLog()
    database = Database(costs_csv=costs_csv)
    if city is None or province_state is None:
        site = model.getSite()
        location = database.closest_location(site.latitude(), site.longitude())
        if city is None:
            city = location["city"]
        if province_state is None:
            province_state = location["province_state"]

    ledger = Ledger()
    quantifier = EquipmentQuantifier(database, ledger, audit=audit)
    geo = geometry.building_data(model)
    counts = {"tanks": 0, "hphw": 0, "reg_gas": 0, "he_gas": 0, "reg_oil": 0,
              "he_oil": 0, "elec": 0, "pumps": 0}

    for loop in sorted_by_name(model.getPlantLoops()):
        if not re.search(r"Main Service Water Loop", loop.nameString(), re.IGNORECASE):
            continue

        for component in loop.supplyComponents():
            tank = opt(component.to_WaterHeaterMixed())
            if tank is not None:
                cost_tank(tank, quantifier, counts, audit)
            elif (opt(component.to_PumpConstantSpeed()) is not None
                  or opt(component.to_PumpVariableSpeed()) is not None):
                cost_pump(component, quantifier, counts, audit)

    if counts["tanks"] > 0:
        cost_site_work(quantifier, counts, geo, audit)
        cost_pump_piping(quantifier, counts, audit)
    else:
        audit.info("costing_shw", "no Main Service Water Loop tanks found — nothing costed")

    priced = ledger.price(database, province_state=province_state, city=city)
    for w in database.warnings:
        audit.warn("costing_shw", w)
    for w in quantifier.warnings:
        audit.warn("costing_shw", w)
    total = priced["total"]
    audit.decision("costing_shw", "service water heating costed",
                   inputs={**counts, "city": city}, value=f"${ruby_round(total, 2)}")
    return Report(total=ruby_round(total, 2),
                  shw={**counts, "items": len(priced["items"])},
                  warnings=[w["action"] for w in audit.warnings],
                  city=city, province_state=province_state, audit=audit)


def cost_tank(tank, quantifier, counts, audit):
    capacity_kw = opt_or(tank.heaterMaximumCapacity(), 0.0) / 1000.0
    volume_gal = opt(openstudio.convert(opt_or(tank.tankVolume(), 0.0), "m^3", "gal"))
    efficiency = opt_or(tank.heaterThermalEfficiency(), 0.0)
    high_efficiency = efficiency >= 0.85

    hphw_tanks = ([hp.tank().nameString() for hp in tank.model().getWaterHeaterHeatPumps()] +
                  [hp.tank().nameString()
                   for hp in tank.model().getWaterHeaterHeatPumpWrappedCondensers()])
    fuel = tank.heaterFuelType()
    if re.search(r"Electric", fuel, re.IGNORECASE):
        if tank.nameString() in hphw_tanks:
            lookup, count_key = "HPHW_Heater", "hphw"
        else:
            lookup, count_key = "WaterElec", "elec"
    elif re.search(r"NaturalGas", fuel, re.IGNORECASE):
        lookup, count_key = ("WaterGas_HE", "he_gas") if high_efficiency else ("WaterGas", "reg_gas")
    elif re.search(r"Oil", fuel, re.IGNORECASE):
        lookup, count_key = ("WaterOil_HE", "he_oil") if high_efficiency else ("WaterOil", "reg_oil")
    else:
        audit.warn("costing_shw", f"tank fuel '{tank.heaterFuelType()}' not costable — skipped",
                   target=tank.nameString())
        return

    units = quantifier.add(lookup, capacity_kw, ["SHW"], f"SHW tank {tank.nameString()}")
    if units is None:
        units = 0
    counts[count_key] += units
    counts["tanks"] += units
    if not (high_efficiency and units > 0):
        return

    vent_size = 0.125 if capacity_kw < 200 else 0.5
    quantifier.add("Waterheater_power_vent", vent_size, ["SHW"],
                   f"power vent for HE tank {tank.nameString()}", count=units)
    _ = volume_gal  # volume participates in legacy elec/oil row selection via the Size column


def cost_pump(component, quantifier, counts, audit):
    pump = opt(component.to_PumpConstantSpeed())
    if pump is None:
        pump = component.to_PumpVariableSpeed().get()
    watts = opt(pump.ratedPowerConsumption())
    if watts is None and hasattr(pump, "autosizedRatedPowerConsumption"):
        watts = opt(pump.autosizedRatedPowerConsumption())
    if watts is None:
        audit.warn("costing_shw",
                   f"pump {pump.nameString()} has no rated power (unsized) — costed at the smallest row")
        watts = 0.0
    quantifier.add("Pumps", watts, ["SHW"], f"SHW pump {pump.nameString()}")
    if opt(component.to_PumpVariableSpeed()) is not None:
        quantifier.add("VFD", watts, ["SHW"], f"VFD for {pump.nameString()}")
    counts["pumps"] += 1


def cost_site_work(quantifier, counts, geo, audit):
    if geo is None:
        audit.warn("costing_shw", "building geometry unresolved — utility runs and flues NOT costed")
        return
    util = geo["util_dist_ft"]
    ht_roof = geo["ht_roof_ft"]

    non_hphw = counts["tanks"] - counts["hphw"]
    if non_hphw > 0:  # legacy: HPHW tanks are excluded from the electric utility run
        quantifier.add("Conduit", None, ["SHW"], "SHW electric utility conduit",
                       count=util * non_hphw)
        quantifier.add("Wiring", 14, ["SHW"], "SHW electric utility wire",
                       count=util / 100.0 * non_hphw)

    reg_fuel = counts["reg_gas"] + counts["reg_oil"]
    he_fuel = counts["he_gas"] + counts["he_oil"]
    if reg_fuel > 0:
        quantifier.add("Venting", 6, ["SHW"], "SHW flue", count=ht_roof)
        quantifier.add("VentingElbow", 6, ["SHW"], "SHW flue elbow")
        quantifier.add("VentingTop", 6, ["SHW"], "SHW flue top")
        if reg_fuel > 1:
            quantifier.add("Venting", 6, ["SHW"], "SHW flue header (20 ft per extra tank)",
                           count=20.0 * (reg_fuel - 1))
            quantifier.add("VentingElbow", 6, ["SHW"], "SHW flue header elbow",
                           count=float(reg_fuel - 1))
    if he_fuel > 0:
        quantifier.add("Vent_pvc", 6, ["SHW"], "SHW PVC flue (HE)", count=20.0 * he_fuel)
        quantifier.add("Vent_pvc_coupling", 6, ["SHW"], "SHW PVC flue coupling", count=float(he_fuel))
        quantifier.add("Vent_pvc_elbow", 6, ["SHW"], "SHW PVC flue elbow", count=float(he_fuel))

    gas = counts["reg_gas"] + counts["he_gas"]  # legacy defect fixed (both sides since #2119): HE-only gas got no fuel line
    oil = counts["reg_oil"] + counts["he_oil"]
    if gas > 0:
        quantifier.add("GasLine", None, ["SHW"], "SHW fuel line", count=util * gas)
        quantifier.add("GasLine", 4, ["SHW"], "SHW fuel line fitting", count=float(gas))
    elif oil > 0:
        quantifier.add("OilLine", None, ["SHW"], "SHW oil filtering system")
        quantifier.add("OilTanks", 2000, ["SHW"], "SHW oil storage tank (2000 USG)")
        quantifier.add("GasLine", None, ["SHW"], "SHW oil fuel line", count=util * oil)
        quantifier.add("GasLine", 4, ["SHW"], "SHW oil fuel line fitting", count=float(oil))


def cost_pump_piping(quantifier, counts, _audit):
    pumps = counts["pumps"]
    if not pumps > 0:
        return

    quantifier.add("SteelPipe", 1, ["SHW"], "SHW tank-to-pump piping (10 ft/pump)",
                   count=10.0 * pumps)
    quantifier.add("PipeInsulation", 1, ["SHW"], "SHW pipe insulation", count=10.0 * pumps)
    quantifier.add("SteelPipeElbow", 1, ["SHW"], "SHW pipe elbows", count=2.0 * pumps)
    quantifier.add("ValvesGate", 1, ["SHW"], "SHW gate valves", count=1.0 * pumps)


# NOTE: shw.rb used to define a module-level ``BtapCosting.cost`` delegating
# to ``Costing.cost`` — a constant left behind by the C7 rename, so the call
# always raised NameError while ``respond_to?(:cost)`` still answered true.
# Nothing called it (every caller uses the umbrella's ``SHW.cost``), and it
# has been DELETED from the gem rather than ported: the family exposes its
# domains as BtapCosting::SHW / ::HVAC / ::Envelope / ::Lighting, with no
# top-level facade, and a bare ``cost`` that priced only service water was
# misleading either way. Do not reintroduce it here.
