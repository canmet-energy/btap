"""Water-heater performance — verbatim port of the NECB2020
water_heater_mixed_apply_efficiency (Table 6.2.2.1 via the UEF procedure +
Maguire-Roberts (2020) UA derivation + PNNL assumptions). Electric: thermal
efficiency 1.0 + max standby-loss formulas -> UA. Gas/oil storage: UEF ladder
by tank volume and first-hour rating (FHR = 0.7 x V_litres + 151, the legacy
rule of thumb), burner efficiency 0.82, RE/UA from the UEF test draw; large
equipment: Et 0.9 + SL formula. The 8.4.5.9. (2025: 8.4.6.9.) part-load fuel
curve is applied to fuel-fired heaters, storage and instantaneous alike, as
the cubic SWH-EFFFPLR-NECB2011 — which is the PLF-domain image of the code's
FHeatPLC quadratic, not a rival curve (D-53).
"""

from __future__ import annotations

import math
import re

import openstudio

from btap._compat import NullAudit, ruby_round, ruby_str
from btap._sdk import ensure_sdk_hashable
from btap.audit import AuditLog
from btap.necb import shw as SHW

# `uniq` over SDK plant loops (apply_solar_pool_minimums) keys on the objects
# themselves, exactly as the Ruby Array#uniq did.
ensure_sdk_hashable()

# Table 6.2.2.1 storage-row boundaries (litres / watts). NOTE ON THE DATA
# SPLIT: the formula strings inside shw_rules_{2020,2025}.json are PROVENANCE
# DOCUMENTATION ONLY — the live coefficients are transcribed here (and in the
# formulas below), matching the legacy port this file declares. Editing the
# JSON strings changes nothing at runtime.
INSTANTANEOUS_MAX_L = 7.6         # gas instantaneous bound (Vr <= 7.6 L)
ELECTRIC_SL_BREAK_L = 270.0       # electric standby-loss formula switch
UEF_SMALL_MAX_W = 22_000          # <= 22 kW UEF rows
UEF_MEDIUM_MAX_W = 30_500         # the 22-30.5 kW UEF row
UEF_BIN1_MIN_L = 76.0             # 76-208 L UEF bin
UEF_BIN2_MIN_L = 208.0            # 208-380 L UEF bin
UEF_BIN2_MAX_L = 380.0
UEF_MEDIUM_MAX_L = 454.0          # volume cap on the 22-30.5 kW row
UA_DELTA_T_F = 70                 # tank-to-ambient design dT (deg F) in the
                                  # standby-loss -> efficiency identity

_NUMERIC_PREFIX = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def _to_f(value) -> float:
    """Ruby ``to_f``: nil -> 0.0, numerics pass, strings parse their leading
    float (unparseable -> 0.0)."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    m = _NUMERIC_PREFIX.match(str(value).strip())
    return float(m.group(0)) if m else 0.0


def apply_efficiency(water_heater, *, vintage="2020", audit=None):
    audit = audit if audit is not None else AuditLog()
    rules = SHW.rules(vintage)["efficiency"]

    capacity = _optional(water_heater.heaterMaximumCapacity())
    volume_m3 = _optional(water_heater.tankVolume())
    if capacity is None or volume_m3 is None:
        audit.warn("shw_efficiency",
                   f"{water_heater.nameString()}: capacity or volume not set — "
                   "standard not applied")
        return False

    fuel = water_heater.heaterFuelType()
    volume_l = volume_m3 * 1000.0
    capacity_btu_hr = openstudio.convert(capacity, "W", "Btu/hr").get()
    efficiency = None
    ua_btu_hr_f = None
    evidence = None

    # Instantaneous water heaters (Table 6.2.2.1 instantaneous rows): the code
    # bounds gas instantaneous at Vr <= 7.6 L — treat tanks at/below that (or
    # named instantaneous) as tankless: UEF/Et applied as thermal efficiency,
    # zero standby UA.
    if volume_l <= INSTANTANEOUS_MAX_L or re.search(r"instantaneous",
                                                    water_heater.nameString(), re.IGNORECASE):
        return _apply_instantaneous(water_heater, rules, fuel, capacity, audit)

    if fuel == "Electricity":
        electric = rules["electric"]
        efficiency = _to_f(electric["thermal_efficiency"])
        if capacity_btu_hr <= openstudio.convert(electric["small_max_kw"], "kW", "Btu/hr").get():
            sl_w = 40 + 0.2 * volume_l if volume_l < ELECTRIC_SL_BREAK_L \
                else 0.472 * volume_l - 33.5
        else:
            sl_w = 0.3 + 102.2 / volume_l
        ua_btu_hr_f = (openstudio.convert(sl_w, "W", "Btu/hr").get()
                       / _to_f(electric["ua_divisor_f"]))
        evidence = f"electric SL formula -> {ruby_str(ruby_round(sl_w, 2))} W standby"
    elif fuel in ("NaturalGas", "FuelOilNo2"):
        fuel_rules = rules["fuel_fired"]
        fhr = 0.7 * volume_l + 151.0
        if capacity <= UEF_SMALL_MAX_W and volume_l >= UEF_BIN1_MIN_L and volume_l < UEF_BIN2_MIN_L:
            efficiency, ua_btu_hr_f, evidence = _uef_path(
                fuel_rules, "uef_bins_76_to_208_l", fhr, volume_l, capacity_btu_hr)
        elif (capacity <= UEF_SMALL_MAX_W and volume_l >= UEF_BIN2_MIN_L
                and volume_l < UEF_BIN2_MAX_L):
            efficiency, ua_btu_hr_f, evidence = _uef_path(
                fuel_rules, "uef_bins_208_to_380_l", fhr, volume_l, capacity_btu_hr)
        elif (capacity > UEF_SMALL_MAX_W and capacity <= UEF_MEDIUM_MAX_W
                and volume_l <= UEF_MEDIUM_MAX_L):
            bin_ = fuel_rules["uef_22_to_30_5_kw_max_454_l"]
            uef = bin_["intercept"] + bin_["slope"] * volume_l
            draw = _draw_gal(fuel_rules["uef_bins_76_to_208_l"], fhr)
            efficiency, ua_btu_hr_f = _maguire_roberts(fuel_rules, uef, draw, capacity_btu_hr)
            evidence = (f"UEF {ruby_str(ruby_round(uef, 4))} (22-30.5 kW row), "
                        f"draw {ruby_str(draw)} gal")
        else:
            large = fuel_rules["large"]
            et = _to_f(large["thermal_efficiency"])
            sl_w = 0.84 * (1.25 * (capacity / 1000.0) + 16.57 * math.sqrt(volume_l))
            sl_btu_hr = openstudio.convert(sl_w, "W", "Btu/hr").get()
            ua_btu_hr_f = sl_btu_hr * et / _to_f(large["ua_divisor_f"])
            efficiency = (ua_btu_hr_f * UA_DELTA_T_F + capacity_btu_hr * et) / capacity_btu_hr
            evidence = f"large equipment: Et {ruby_str(et)}, SL {ruby_str(ruby_round(sl_w, 1))} W"
    else:
        audit.warn("shw_efficiency",
                   f"{water_heater.nameString()}: fuel '{fuel}' not supported — "
                   "standard not applied")
        return False

    ua_w_k = openstudio.convert(ua_btu_hr_f, "Btu/hr*R", "W/K").get()
    water_heater.setHeaterThermalEfficiency(efficiency)
    water_heater.setOffCycleLossCoefficienttoAmbientTemperature(ua_w_k)
    water_heater.setOnCycleLossCoefficienttoAmbientTemperature(ua_w_k)
    water_heater.setOnCycleParasiticFuelType(fuel)
    water_heater.setOnCycleParasiticHeatFractiontoTank(
        _to_f(rules["parasitic"]["on_cycle_heat_fraction"]))
    water_heater.setOffCycleParasiticFuelType(fuel)
    water_heater.setOffCycleParasiticHeatFractiontoTank(
        _to_f(rules["parasitic"]["off_cycle_heat_fraction"]))

    water_heater.setName(
        f"{water_heater.nameString()} {ruby_str(ruby_round(efficiency, 3))} Therm Eff")

    audit.decision("shw_efficiency",
                   "water heater performance applied (Table 6.2.2.1, NECB2020 UEF procedure)",
                   target=water_heater.nameString(),
                   inputs={"fuel": fuel, "capacity_kw": ruby_round(capacity / 1000, 2),
                           "volume_l": ruby_round(volume_l, 1),
                           "thermal_efficiency": ruby_round(efficiency, 4),
                           "ua_w_per_k": ruby_round(ua_w_k, 4)},
                   evidence=evidence, article="6.2.2.1.")
    _apply_part_load_curve(water_heater, rules, fuel, audit)
    return True


def _apply_instantaneous(water_heater, rules, fuel, capacity, audit):
    """Instantaneous rows of Table 6.2.2.1. Gas < 59 kW: UEF 0.86 (< 6.4 L/min)
    or 0.87 (>= 6.4 L/min) — rated flow is not model-resolvable, so the
    CONSERVATIVE 0.86 is used (audited); gas all others: Et >= 94%. Oil:
    Et >= 80% (< 37.8 L) / 78%. Electric instantaneous carries footnote (6)
    (no numeric requirement) — modeled at 1.0."""
    if fuel == "NaturalGas":
        efficiency, evidence = (
            (0.86, "gas instantaneous < 59 kW: UEF 0.86 (conservative low-flow row; "
                   "rated flow unknown)") if capacity < 59_000
            else (0.94, "gas instantaneous, all others: Et 0.94"))
    elif fuel == "FuelOilNo2":
        efficiency, evidence = 0.80, "oil instantaneous < 37.8 L: Et 0.80"
    elif fuel == "Electricity":
        efficiency, evidence = (
            1.0, "electric instantaneous: footnote (6), no numeric requirement — "
                 "modeled at 1.0")
    else:
        audit.warn("shw_efficiency",
                   f"{water_heater.nameString()}: instantaneous fuel '{fuel}' not supported")
        return False
    water_heater.setHeaterThermalEfficiency(efficiency)
    water_heater.setOffCycleLossCoefficienttoAmbientTemperature(0.0)
    water_heater.setOnCycleLossCoefficienttoAmbientTemperature(0.0)
    water_heater.setName(f"{water_heater.nameString()} "
                         f"{ruby_str(ruby_round(efficiency, 3))} Therm Eff Instantaneous")
    audit.decision("shw_efficiency",
                   "instantaneous water heater performance applied (tankless: zero standby UA)",
                   target=water_heater.nameString(),
                   inputs={"fuel": fuel, "capacity_kw": ruby_round(capacity / 1000, 2),
                           "thermal_efficiency": efficiency},
                   evidence=evidence, article="6.2.2.1. (instantaneous rows)")
    # 8.4.5.9 draws no storage/instantaneous distinction — a fuel-fired
    # instantaneous heater is a fuel-fired service water heater, so the
    # part-load fuel curve reaches it too.
    _apply_part_load_curve(water_heater, rules, fuel, audit)
    return True


def apply_heat_pump_efficiency(hpwh, *, vintage="2020", audit=None):
    """Heat-pump water heater performance: the code floor (2020: EF >= 2.1;
    2025: UEF >= 2.23) applied as the DX coil's rated COP — CONSERVATIVE
    (rated COP >= EF in practice since EF includes tank standby), audited."""
    audit = audit if audit is not None else AuditLog()
    floor = 2.23 if str(vintage) == "2025" else 2.1
    metric = "UEF" if str(vintage) == "2025" else "EF"
    coil = hpwh.dXCoil().to_CoilWaterHeatingAirToWaterHeatPump()
    if coil.empty():
        audit.warn("shw_efficiency",
                   f"{hpwh.nameString()}: no air-to-water HP coil found — "
                   "performance not applied")
        return False

    coil.get().setRatedCOP(floor)
    audit.decision("shw_efficiency",
                   f"heat-pump water heater performance applied: rated COP set to the code "
                   f"floor {metric} {ruby_str(floor)} "
                   "(conservative — rated COP exceeds EF in practice since EF includes "
                   "tank standby)",
                   target=hpwh.nameString(), inputs={f"{metric.lower()}_floor": floor},
                   article="6.2.2.1. (storage-type heat pump)")
    return True


def _uef_path(fuel_rules, bin_key, fhr, volume_l, capacity_btu_hr):
    bin_ = next(b for b in fuel_rules[bin_key]
                if b["fhr_max"] is None or fhr < b["fhr_max"])
    uef = bin_["intercept"] + bin_["slope"] * volume_l
    efficiency, ua = _maguire_roberts(fuel_rules, uef, bin_["draw_gal"], capacity_btu_hr)
    return [efficiency, ua,
            f"UEF {ruby_str(ruby_round(uef, 4))} (FHR {ruby_str(ruby_round(fhr, 1))} L/hr bin), "
            f"draw {ruby_str(bin_['draw_gal'])} gal"]


def _draw_gal(bins, fhr):
    return next(b for b in bins if b["fhr_max"] is None or fhr < b["fhr_max"])["draw_gal"]


def _maguire_roberts(fuel_rules, uef, draw_gal, capacity_btu_hr):
    """Maguire & Roberts (2020): recovery efficiency + UA from the UEF test draw."""
    efficiency = _to_f(fuel_rules["burner_efficiency"])
    q_load_btu = draw_gal * 8.30074 * 0.99826 * (125.0 - 58.0)
    re_ = efficiency + q_load_btu * (uef - efficiency) / (24 * capacity_btu_hr * uef)
    ua = (efficiency - re_) * capacity_btu_hr / (125 - 67.5)
    return [efficiency, ua]


def _apply_part_load_curve(water_heater, rules, fuel, audit):
    """NECB 8.4.5.9. (2025: 8.4.6.9.) "Fuel-Fired Service Water Heater" — the
    part-load fuel curve. SCOPE IS THE ARTICLE'S, not an implementation
    convenience: the article governs "the reference fuel-fired service water
    heater", so it reaches gas and oil (storage and instantaneous alike) and
    does NOT reach electric heaters — 8.4.5 carries no electric counterpart to
    apply. An out-of-scope fuel is audited as such rather than silently
    skipped. See D-53."""
    spec = rules["part_load_curve"]
    if fuel not in spec["applies_to"]:
        audit.info("shw_efficiency",
                   f"part-load fuel curve not applied — '{fuel}' is not a fuel-fired "
                   f"service water heater, so {spec['article']} does not reach it "
                   "(article scope, not an omission)",
                   target=water_heater.nameString(), article=spec["article"], ruling="D-53")
        return False

    water_heater.setPartLoadFactorCurve(part_load_curve(water_heater.model(), spec))
    audit.decision("shw_efficiency",
                   "part-load fuel curve applied to the fuel-fired water heater",
                   target=water_heater.nameString(),
                   inputs={"fuel": fuel, "curve": spec["name"], "form": spec["form"]},
                   value=spec["coefficients"],
                   evidence=f"code FHeatPLC {ruby_str(spec['code_fheatplc']['coefficients'])} "
                            "is a fuel-ratio curve; the EnergyPlus part-load-factor field is a "
                            "degradation divisor, so it carries the transform "
                            "PLF(x) = x / FHeatPLC(x) — probe-verified equivalent to 0.98% over "
                            "PLR 0.25-1.0 (necb_8_4_6_curve_probe.rb)",
                   article=spec["article"], ruling="D-53")
    return True


def part_load_curve(model, spec):
    """Builds the curve in the form the ruleset declares. `form` is honoured
    rather than assumed: the field accepts any UnivariateFunction, so a
    Quadratic ruleset must not be smuggled through as a cubic with a zero
    cubic term (that would silently accept a mis-shaped spec)."""
    coeffs = spec["coefficients"]
    if spec["form"] == "Quadratic":
        if len(coeffs) != 3:
            raise ValueError(f"part_load_curve '{spec['name']}': Quadratic needs 3 coefficients")

        existing = model.getCurveQuadraticByName(spec["name"])
        if existing.is_initialized():
            return existing.get()

        curve = openstudio.model.CurveQuadratic(model)
        curve.setCoefficient1Constant(coeffs[0])
        curve.setCoefficient2x(coeffs[1])
        curve.setCoefficient3xPOW2(coeffs[2])
    elif spec["form"] == "Cubic":
        if len(coeffs) != 4:
            raise ValueError(f"part_load_curve '{spec['name']}': Cubic needs 4 coefficients")

        existing = model.getCurveCubicByName(spec["name"])
        if existing.is_initialized():
            return existing.get()

        curve = openstudio.model.CurveCubic(model)
        curve.setCoefficient1Constant(coeffs[0])
        curve.setCoefficient2x(coeffs[1])
        curve.setCoefficient3xPOW2(coeffs[2])
        curve.setCoefficient4xPOW3(coeffs[3])
    else:
        raise ValueError(f"part_load_curve '{spec['name']}': unsupported form '{spec['form']}'")
    curve.setName(spec["name"])
    curve.setMinimumValueofx(0.0)
    curve.setMaximumValueofx(1.0)
    return curve


def _optional(value):
    return value.get() if value.is_initialized() else None


# ---------------- Table 6.2.2.1 solar + pool minimums (D-63) ----------------
#
# Apply-when-present: no archetype carries either class, but a foreign
# proposed can. The printed rows were recovered by hbix's table audit (the
# extraction LOST both sections in every edition), so the values come from the
# vendored solar_pool_minimums block, not the service.
#
# Pool heaters: a WaterHeaterMixed on a loop that serves a SwimmingPoolIndoor
# gets the printed minimum thermal efficiency (gas 82% / oil 78%); a heat-pump
# water heater on such a loop gets the printed COP 4.0 floor. Solar thermal:
# SEF is an equipment RATING with no EnergyPlus field — detected solar
# collectors get an audited determination citing the printed minimums, never a
# silent skip.
def apply_solar_pool_minimums(model, *, vintage="2020", audit=None):
    spec = SHW.rules(vintage).get("solar_pool_minimums")
    if spec is None:
        return None
    audit = audit if audit is not None else NullAudit()

    pool_loops = list(dict.fromkeys(
        p.plantLoop().get() for p in model.getSwimmingPoolIndoors()
        if p.plantLoop().is_initialized()))
    for loop in pool_loops:
        for comp in loop.supplyComponents():
            heater = comp.to_WaterHeaterMixed()
            if not heater.is_initialized():
                continue

            heater = heater.get()
            # A heat-pump water heater puts its TANK on the loop; the wrapper
            # is the tank's containing ZoneHVAC component.
            containing = heater.containingZoneHVACComponent()
            hp = containing.get().to_WaterHeaterHeatPump() if containing.is_initialized() else None
            if hp is not None and hp.is_initialized():
                coil = hp.get().dXCoil().to_CoilWaterHeatingAirToWaterHeatPump()
                if not coil.is_initialized():
                    continue

                floored = max(coil.get().ratedCOP(), spec["pool_heat_pump_cop"])
                coil.get().setRatedCOP(floored)
                audit.decision("shw_efficiency",
                               "heat-pump pool heater floored at the Table 6.2.2.1 minimum COP",
                               target=hp.get().nameString(),
                               inputs={"pool_loop": loop.nameString()},
                               value=f"COP {ruby_str(ruby_round(floored, 2))} "
                                     f"(minimum {ruby_str(spec['pool_heat_pump_cop'])})",
                               article=spec["article"], ruling="D-63")
                continue

            fuel = heater.heaterFuelType()
            if re.search(r"gas|propane", fuel, re.IGNORECASE):
                minimum = spec["pool_gas_thermal_efficiency"]
            elif re.search(r"oil", fuel, re.IGNORECASE):
                minimum = spec["pool_oil_thermal_efficiency"]
            else:
                minimum = None
            if minimum is not None:
                heater.setHeaterThermalEfficiency(minimum)
                audit.decision("shw_efficiency",
                               "pool heater set to the Table 6.2.2.1 minimum thermal efficiency",
                               target=heater.nameString(),
                               inputs={"fuel": fuel, "pool_loop": loop.nameString()},
                               value=f"Et = {ruby_str(ruby_round(minimum * 100))}%",
                               article=spec["article"], ruling="D-63")
            else:
                audit.info("shw_efficiency",
                           f"pool heater fuel '{fuel}' has no Table 6.2.2.1 pool row — "
                           "left as cloned",
                           target=heater.nameString(), article=spec["article"], ruling="D-63")

    collectors = list(model.getSolarCollectorFlatPlateWaters())
    collectors += list(model.getSolarCollectorFlatPlatePhotovoltaicThermals())
    collectors += list(model.getSolarCollectorIntegralCollectorStorages())
    if not collectors:
        return None

    audit.decision("shw_efficiency",
                   "solar-thermal service water heating detected — the Table 6.2.2.1 minimum "
                   "Solar Energy Factor (SEF >= "
                   f"{ruby_str(spec['solar_sef_aux_electric'])} electric-auxiliary / >= "
                   f"{ruby_str(spec['solar_sef_aux_gas'])} gas-auxiliary) is an equipment "
                   "RATING with no EnergyPlus field; the collectors are modeled physically as "
                   "cloned and the rating-level requirement is recorded here rather than "
                   "silently skipped",
                   inputs={"collectors": len(collectors)},
                   article=spec["article"], ruling="D-63")
    return None
