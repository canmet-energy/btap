"""Vintage efficiency application (port of btap-necb's hvac/efficiency.rb) — a
faithful, SDK-only port of the NECB subset of openstudio-standards'
model_apply_hvac_efficiency_standard, driven entirely by the vendored
data/efficiencies_<vintage>.json (NECB Table 5.2.12.1 values + performance curves).

Covered components: hot-water boilers (incl. NECB primary/secondary staging),
electric chillers (incl. 2100 kW split + cooling-tower sizing rules), single-speed
DX cooling and heating coils, gas heating coils, VAV fan power curves (8.4.4.17)
and hydronic pump power (8.4.4.14: Table curves + proposed W/(L/s) transfer when
a proposed model is supplied). Reference-model fans get their explicit 8.4.4.18
static pressure/efficiency values in the reference transform; motor-table
application remains host-side.

Requires a SIZED model (capacities read from hard or autosized values).
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime

import openstudio

from btap._compat import NullAudit, ruby_round, sorted_by_name
from btap.modeling.hvac.components import coils as _coils
from btap.necb.hvac.reference import RULES_DIR
from btap.necb.hvac.reference import rules as _rules

_DATA: dict[str, dict] = {}


def data(vintage):
    key = str(vintage)
    if key not in _DATA:
        path = RULES_DIR / f'efficiencies_{key}.json'
        if not path.exists():
            raise ValueError(
                f"no NECB efficiency data for vintage '{key}' (expected {path})")
        with open(path, encoding='utf-8') as f:
            _DATA[key] = json.load(f)
    return _DATA[key]


def effective_vintage(vintage):
    """The efficiency vintage to actually apply: the requested vintage when its tables
    are vendored, else the fallback its rules file declares (e.g. NECB 2025 falls
    back to 2020 until the restructured Table 5.2.12.1 series is transcribed).

    :param vintage: requested NECB vintage (e.g. '2020', '2025')
    :return: (effective vintage, fallback reason or None)
    """
    if (RULES_DIR / f'efficiencies_{vintage}.json').exists():
        return str(vintage), None

    provenance = _rules(vintage)['provenance']
    fallback = provenance.get('efficiency_vintage_fallback')
    if fallback is None:
        raise ValueError(
            f"no NECB efficiency data for vintage '{vintage}' and no declared fallback")

    return (str(fallback),
            provenance.get('efficiency_fallback_reason') or f'vintage {vintage} tables not vendored')


def apply(model, vintage='2020', audit=None, proposed=None):
    """Apply NECB minimum-performance values + curves to every supported component.

    :param model: sized openstudio.model.Model
    :param vintage: e.g. '2020'
    :param audit: AuditLog or None
    :param proposed: SIZED proposed model, enabling the 8.4.4.14.(1)-(3) pump power transfer
    :return: True
    """
    audit = audit if audit is not None else NullAudit()
    requested_vintage = str(vintage)
    vintage, fallback_reason = effective_vintage(vintage)
    if fallback_reason:
        audit.warn('efficiency', f'efficiency tables fall back to NECB {vintage} values: {fallback_reason}',
                   article='Table 5.2.12.1')
    tables = data(vintage)
    # Boiler/chiller staging thresholds (8.4.4.9.(6)/8.4.4.10.(6)) live in the
    # reference ruleset (heating_plant/cooling_plant), not the efficiencies table —
    # fetched by the originally requested vintage since reference_rules_<vintage>.json
    # is vendored for every supported vintage (no efficiency-style fallback needed).
    plant_rules = _rules(requested_vintage)
    heating_plant = plant_rules['heating_plant']
    cooling_plant = plant_rules['cooling_plant']
    for b in sorted_by_name(model.getBoilerHotWaters()):
        _apply_boiler(b, tables, heating_plant, audit)
    for c in sorted_by_name(model.getChillerElectricEIRs()):
        _apply_chiller(c, tables, cooling_plant, audit)
    # after ALL chiller capacities are final — the tower sees the loop SUM
    _apply_tower_rules(model, audit)
    # 8.4.4.9.(7)/8.4.4.10.(8) stage COUNTS first: the multispeed appliers bin
    # by TOP-stage capacity, and the top stage is unchanged by re-staging, but
    # the per-stage values must land on the stages the staging pass leaves behind.
    totals = apply_staging(model, plant_rules, requested_vintage, audit)
    for c in sorted_by_name(model.getCoilCoolingDXSingleSpeeds()):
        _apply_dx_cooling(c, tables, audit)
    for c in sorted_by_name(model.getCoilCoolingDXMultiSpeeds()):
        _apply_dx_cooling_multi(c, tables, audit, totals.get(str(c.handle())))
    for c in sorted_by_name(model.getCoilHeatingDXSingleSpeeds()):
        _apply_dx_heating(c, tables, audit)
    for c in sorted_by_name(model.getCoilHeatingDXMultiSpeeds()):
        _apply_dx_heating_multi(c, tables, audit, totals.get(str(c.handle())))
    for c in sorted_by_name(model.getCoilHeatingGass()):
        _apply_gas_coil(c, tables, audit)
    for c in sorted_by_name(model.getCoilHeatingGasMultiStages()):
        _apply_gas_multi(c, tables, audit, totals.get(str(c.handle())))
    for f in sorted_by_name(model.getFanVariableVolumes()):
        _apply_fan_power_curve(f, vintage, audit)
    _apply_pump_rules(model, requested_vintage, plant_rules.get('hydronic_pumps'), audit,
                      proposed=proposed)
    # requested_vintage, NOT vintage: the latter has been remapped to the
    # effective DATA vintage (2020 tables can back a 2025 run), and the
    # article number must follow the code edition being complied with. Using
    # the data vintage would cite 8.4.4.13 on a 2025 run whenever the tables
    # fall back — the very bug this argument exists to fix.
    _align_heat_pump_heating_capacity(model, audit, requested_vintage)
    audit.info('efficiency', 'NECB efficiency pass complete',
               inputs={'vintage': vintage,
                       'boilers': len(model.getBoilerHotWaters()),
                       'chillers': len(model.getChillerElectricEIRs()),
                       'dx_cooling': len(model.getCoilCoolingDXSingleSpeeds()),
                       'dx_cooling_staged': len(model.getCoilCoolingDXMultiSpeeds()),
                       'dx_heating': len(model.getCoilHeatingDXSingleSpeeds()),
                       'dx_heating_staged': len(model.getCoilHeatingDXMultiSpeeds()),
                       'gas_coils': len(model.getCoilHeatingGass()),
                       'gas_coils_staged': len(model.getCoilHeatingGasMultiStages())})
    return True


# ---------------- 8.4.4.9.(7) / 8.4.4.10.(8) staged heating and cooling ----------------

# The EnergyPlus structural ceiling: both Coil:Cooling:DX:MultiSpeed and
# Coil:Heating:Gas:MultiStage refuse a fifth stage (probe-verified on the
# SDK — addStage returns false), so a system needing more equal stages
# than this is clamped, loudly (D-47).
MAX_STAGES = 4


def apply_staging(model, rules, vintage, audit):
    """Post-sizing stage-COUNT pass. Sentence (7)/(8) read the same way: at or
    below the two-stage threshold the equipment is modelled as two equal
    stages; above it, as equal stages of the stage size (rounded up). Only
    the COUNT is set here — every stage capacity stays AUTOSIZED, and the
    equal increments realize themselves through the containing unitary's
    UnitarySystemPerformanceMultispeed flow ratios (stage k -> k/N). Never
    hard-set a stage capacity: hard-sized equipment stops responding to the
    8.4.1.2.(5) capacity iteration.

    :param model: sized openstudio.model.Model (modified in place)
    :param rules: the reference ruleset (dx_staging / furnace_staging /
        economizer_dx_staging blocks)
    :param vintage: NECB vintage ('2020' or '2025')
    :param audit: AuditLog or None
    :return: dict {coil handle -> the TOTAL capacity measured before re-staging}.
        Growing a coil appends a stage EnergyPlus has never sized, so the new top
        stage reads back None and shrinking one leaves a stale partial value behind
        — the appliers must bin on the measurement taken here, not on a re-read.
    """
    audit = audit if audit is not None else NullAudit()
    prefix = '8.4.5' if str(vintage) == '2025' else '8.4.4'
    totals: dict = {}
    for unitary in sorted_by_name(model.getAirLoopHVACUnitarySystems()):
        _stage_multispeed_coil(unitary.coolingCoil(), rules.get('dx_staging'),
                               f'{prefix}.10.(8)', 'DX cooling', audit, totals,
                               unitary=unitary, economizer_spec=rules.get('economizer_dx_staging'))
        _stage_multispeed_coil(unitary.heatingCoil(), rules.get('furnace_staging'),
                               f'{prefix}.9.(7)', 'furnace', audit, totals)
        _audit_electric_resistance_heating(unitary, prefix, audit)
        _apply_stage_flow_ratios(unitary, prefix, audit)
    _audit_staging_skips(model, prefix, audit)
    return totals


def _apply_stage_flow_ratios(unitary, prefix, audit):
    """Stage supply-airflow ratios, floored at the unit's minimum-outdoor-air
    fraction. A staged unit's low speed reduces supply flow with capacity
    (the E+ multispeed coil requires flow to track per-stage capacity), but
    it must not stage down below the ventilation air the system is there to
    deliver — the same protection the legacy multi-speed implementation
    applies by pinning low-speed flow to the minimum OA rate."""
    air_loop = unitary.airLoopHVAC()
    oaf = _coils.outdoor_air_fraction(air_loop.get() if air_loop.is_initialized() else None)
    stages = max(_coils.stage_count(unitary.heatingCoil()),
                 _coils.stage_count(unitary.coolingCoil()))
    _coils.set_stage_flow_ratios(unitary, min_ratio=oaf)
    if not (stages > 1 and oaf > 1.0 / stages):
        return

    audit.info('efficiency', 'staged supply airflow FLOORED at the minimum outdoor-air fraction — the lower '
                             'stage(s) would otherwise deliver less air than the ventilation requirement',
               target=unitary.nameString(),
               inputs={'outdoor_air_fraction': ruby_round(oaf, 3), 'stages': stages,
                       'unfloored_stage_1_ratio': ruby_round(1.0 / stages, 3)},
               article=f'{prefix}.10.(8); {prefix}.9.(7)', ruling='D-46')


def _stage_multispeed_coil(optional_coil, rule, article, label, audit, totals=None,
                           unitary=None, economizer_spec=None):
    """:return: the stage count applied, None when the coil is not staged"""
    if totals is None:
        totals = {}
    if rule is None:
        return None

    coil = _coils.multispeed(optional_coil)
    if coil is None:
        return None

    name = coil.nameString()
    capacity_w = _top_stage_capacity(coil)
    if capacity_w is None:
        audit.warn('efficiency', f'{name}: staged capacity unavailable (model not sized?) — {article} stage '
                                 'count NOT set; run sizing first', article=article, ruling='D-46')
        return None
    totals[str(coil.handle())] = capacity_w

    kw = capacity_w / 1000.0
    wanted = 2 if kw <= rule['two_stage_max_kw'] else math.ceil(kw / rule['stage_size_kw'])
    # 5.2.2.8.(4)-(5) (D-62): a system with an air economizer must stage its
    # cooling so the LOWEST stage is <= 25% of full capacity at >= 70 kW, or
    # <= 50% at > 25 kW — with equal increments that is a stage-count FLOOR
    # of ceil(1/fraction). Only cooling coils on economizer loops; any loop
    # the floor reaches (> 25 kW) is above the 5.2.2.7 retention trigger
    # (> 20 kW), so the build-time economizer state is the final state.
    floor = _economizer_stage_floor(unitary, kw, economizer_spec)
    if floor and floor > wanted:
        audit.decision('efficiency', 'stage count RAISED to the 5.2.2.8 economizer staging floor — the lowest '
                                     'stage of an economizer system must not exceed the sentence-(4)/(5) '
                                     'fraction of full capacity',
                       target=name,
                       inputs={'capacity_kw': ruby_round(kw, 1), 'incremental_stages': wanted,
                               'floor_stages': floor,
                               'lowest_stage_fraction': ruby_round(1.0 / floor, 3)},
                       value=f'{floor} stages (lowest {ruby_round(100.0 / floor, 0)}% <= '
                             f"{'25' if kw >= 70 else '50'}%)",
                       article=economizer_spec['article'], ruling='D-62')
        wanted = floor
    stages = min(wanted, MAX_STAGES)
    if wanted > MAX_STAGES:
        audit.warn('efficiency', f'{name}: {wanted} equal stages required at {ruby_round(kw, 1)} kW but EnergyPlus '
                                 f'EXCEEDS its multispeed ceiling beyond {MAX_STAGES} — stage count CLAMPED to '
                                 f'{MAX_STAGES} (stages are larger than the code increment)',
                   target=name, article=article, ruling='D-47')
    before = len(coil.stages())
    resize_stages(coil, stages)
    audit.decision('efficiency', f'{label} modelled as {stages} equal stages',
                   target=name,
                   inputs={'capacity_kw': ruby_round(kw, 1), 'two_stage_max_kw': rule['two_stage_max_kw'],
                           'stage_size_kw': rule['stage_size_kw'], 'stages_required': wanted,
                           'stages_before': before},
                   value=f'{stages} autosized stage(s), each sized to {ruby_round(100.0 / stages, 1)}% increments '
                         'of the total by the unitary flow ratios',
                   article=article, ruling='D-46')
    return stages


def _economizer_stage_floor(unitary, kw, spec):
    """The 5.2.2.8.(4)/(5) stage-count floor for a cooling coil on an
    air-economizer loop, None when no floor applies (no spec, no loop, no
    economizer, or capacity <= 25 kW)."""
    if spec is None or unitary is None:
        return None

    loop_ = unitary.airLoopHVAC()
    if loop_ is None or loop_.empty():
        return None

    oa = loop_.get().airLoopHVACOutdoorAirSystem()
    if oa.empty():
        return None
    if oa.get().getControllerOutdoorAir().getEconomizerControlType() == 'NoEconomizer':
        return None

    if kw >= 70:
        fraction = spec['ge_70_kw_lowest_fraction']
    elif kw > 25:
        fraction = spec['over_25_kw_lowest_fraction']
    else:
        fraction = None
    return math.ceil(1.0 / fraction) if fraction else None


def _top_stage_capacity(coil):
    """The TOTAL capacity of a staged coil is its TOP stage (the stages are
    cumulative in EnergyPlus, not additive)."""
    stages = coil.stages()
    stage = stages[-1] if len(stages) else None
    if stage is None:
        return None

    if hasattr(stage, 'grossRatedTotalCoolingCapacity'):
        return (optional_f(stage.grossRatedTotalCoolingCapacity())
                or optional_f(stage.autosizedGrossRatedTotalCoolingCapacity()))
    if hasattr(stage, 'grossRatedHeatingCapacity'):
        return (optional_f(stage.grossRatedHeatingCapacity())
                or optional_f(stage.autosizedGrossRatedHeatingCapacity()))
    return optional_f(stage.nominalCapacity()) or optional_f(stage.autosizedNominalCapacity())


def resize_stages(coil, stages):
    """Grow/shrink to `stages` and, when the count actually moved, re-autosize
    every stage capacity and flow so the next sizing run redistributes them
    at the new k/N increments. An unchanged count is left untouched — the
    stages are already autosized from the build, and re-autosizing would
    wipe the 8.4.4.13.(2)(c) heating=cooling pinning a previous pass applied.

    :param coil: CoilCoolingDXMultiSpeed / CoilHeatingDXMultiSpeed / CoilHeatingGasMultiStage
    :param stages: target stage count (1..MAX_STAGES)
    """
    model = coil.model()
    before = len(coil.stages())
    while len(coil.stages()) > stages:
        doomed = coil.stages()[-1]
        coil.removeStage(doomed)
        doomed.remove()
    while len(coil.stages()) < stages:
        if coil.to_CoilCoolingDXMultiSpeed().is_initialized():
            added = _coils.dx_cooling_stage(model)
        elif coil.to_CoilHeatingDXMultiSpeed().is_initialized():
            added = _coils.dx_heating_stage(model)
        else:
            added = _coils.gas_heating_stage(model)
        if not coil.addStage(added):  # SDK refuses beyond MAX_STAGES
            break

        added.setName(f'{coil.nameString()} Stage {len(coil.stages())}')
    if len(coil.stages()) == before:
        return len(coil.stages())

    for stage in coil.stages():
        if hasattr(stage, 'autosizeGrossRatedTotalCoolingCapacity'):
            stage.autosizeGrossRatedTotalCoolingCapacity()
        if hasattr(stage, 'autosizeGrossRatedHeatingCapacity'):
            stage.autosizeGrossRatedHeatingCapacity()
        if hasattr(stage, 'autosizeNominalCapacity'):
            stage.autosizeNominalCapacity()
        if hasattr(stage, 'autosizeRatedAirFlowRate'):
            stage.autosizeRatedAirFlowRate()
    return len(coil.stages())


def _audit_electric_resistance_heating(unitary, prefix, audit):
    """D-49: an electric-resistance coil is not a furnace — no burner, no
    combustion staging, linear part-load — so the furnace staging sentence
    does not reach it and the staged unitary keeps a single-stage electric
    coil next to its staged DX cooling. Recorded per unit so the reader sees
    the sentence was considered and declined, not overlooked."""
    coil = unitary.heatingCoil()
    if coil.empty() or not coil.get().to_CoilHeatingElectric().is_initialized():
        return

    audit.info('efficiency', 'electric resistance heating left single-stage — it is not a furnace, so the '
                             'furnace staging sentence does not apply (the staged DX cooling still does)',
               target=coil.get().nameString(),
               inputs={'unitary': unitary.nameString()},
               article=f'{prefix}.9.(7)', ruling='D-49')


def _audit_staging_skips(model, prefix, audit):
    """D-48: the staging scope is AIR-LOOP equipment. Zone terminals (PTAC /
    PTHP) cannot host a multispeed coil — the EnergyPlus IDD restricts their
    coil choices even though the SDK accepts the assignment — and make-up-air
    tempering DX is not the staged unitary equipment the sentences describe.
    Both stay single-speed; the skips are audited by REASON (one entry per
    reason with the count, rather than one per coil, so a fleet-scale model's
    hundreds of identical terminals cannot swamp the log)."""
    zonal = []
    air_loop = []
    for coil in sorted_by_name(list(model.getCoilCoolingDXSingleSpeeds())
                               + list(model.getCoilHeatingDXSingleSpeeds())):
        (air_loop if coil.airLoopHVAC().is_initialized() else zonal).append(coil.nameString())
    if zonal:
        audit.info('efficiency', f'{len(zonal)} zone-terminal DX coil(s) left single-speed — '
                                 f'{prefix}.9.(7)/{prefix}.10.(8) staging is modelled on air-loop unitary '
                                 'equipment; EnergyPlus packaged terminal objects cannot host a multispeed coil',
                   inputs={'coils': len(zonal)}, value=', '.join(zonal[:5]),
                   article=f'{prefix}.9.(7); {prefix}.10.(8)', ruling='D-48')
    if not air_loop:
        return

    audit.info('efficiency', f'{len(air_loop)} air-loop DX coil(s) left single-speed — make-up-air tempering '
                             'and non-reference systems are outside the staged-unitary scope',
               inputs={'coils': len(air_loop)}, value=', '.join(air_loop[:5]),
               article=f'{prefix}.9.(7); {prefix}.10.(8)', ruling='D-48')


# 8.4.4.17.(2)-(5) (2025: 8.4.5.17): VAV fan power-vs-flow curves from
# Table 8.4.4.17. Selection by rated fan power ((3)-(5)): default = airfoil/
# backward-inclined riding the fan curve; VAV fans > 7.5 kW and < 25 kW =
# airfoil/backward-inclined WITH inlet vanes; >= 25 kW = forward curved
# with inlet vanes. E+ mapping: coefficients A/B/C -> c1/c2/c3 (c4=c5=0)
# and the below-D floor (P = E x Prated) approximated by the Fan Power
# Minimum Flow Fraction = D clamp — the polynomial at D equals E within
# the table's rounding (verified for all three rows).
FAN_CURVES = {
    'airfoil riding fan curve': {'a': 0.227143, 'b': 1.178929, 'c': -0.41071, 'd': 0.47, 'e': 0.68},
    'airfoil with inlet vanes': {'a': 0.584345, 'b': -0.57917, 'c': 0.970238, 'd': 0.35, 'e': 0.50},
    'forward curved with inlet vanes': {'a': 0.339619, 'b': -0.84814, 'c': 1.495671, 'd': 0.25, 'e': 0.22},
}


def _apply_fan_power_curve(fan, vintage, audit):
    flow = fan.maximumFlowRate().get() if fan.maximumFlowRate().is_initialized() else None
    if flow is None:
        flow = (fan.autosizedMaximumFlowRate().get()
                if fan.autosizedMaximumFlowRate().is_initialized() else None)
    if flow is None:
        audit.warn('efficiency', f'{fan.nameString()}: flow not sized — 8.4.4.17 fan curve selection needs the '
                                 'rated power; run sizing first (curve not applied)')
        return

    power_kw = fan.pressureRise() * flow / (fan.fanTotalEfficiency() * 1000.0)
    if power_kw > 7.5 and power_kw < 25.0:
        row_name = 'airfoil with inlet vanes'
    elif power_kw >= 25.0:
        row_name = 'forward curved with inlet vanes'
    else:
        row_name = 'airfoil riding fan curve'
    row = FAN_CURVES[row_name]
    fan.setFanPowerCoefficient1(row['a'])
    fan.setFanPowerCoefficient2(row['b'])
    fan.setFanPowerCoefficient3(row['c'])
    fan.setFanPowerCoefficient4(0.0)
    fan.setFanPowerCoefficient5(0.0)
    fan.setFanPowerMinimumFlowRateInputMethod('Fraction')
    fan.setFanPowerMinimumFlowFraction(row['d'])
    prefix = '8.4.5' if str(vintage) == '2025' else '8.4.4'
    audit.decision('efficiency', f'VAV fan power curve set ({row_name})',
                   target=fan.nameString(),
                   inputs={'rated_kw': ruby_round(power_kw, 2),
                           'coefficients': [row['a'], row['b'], row['c']],
                           'minimum_flow_fraction': row['d']},
                   value=f"below-D floor (E={row['e']}) approximated by the minimum-flow clamp",
                   article=f'{prefix}.17.(2)-(5); Table {prefix}.17.')


def _apply_pump_rules(model, vintage, rule, audit, proposed=None):
    """8.4.4.14 (2025: 8.4.5.14) hydronic pump power. Sentence (5) directs
    variable-flow pumps to be modeled as a pump riding its curve, so
    reference PumpVariableSpeeds get the Table's riding-curve row (identical
    coefficients to the 8.4.4.17 airfoil fan row — same DOE-2 lineage; the
    VSD row is vendored for completeness). Coefficients come from the
    ruleset's hydronic_pumps.curves (Table 8.4.4.14., both vintages
    identical). E+ mapping: A/B/C -> part-load performance coefficients 1-3
    (4th = 0); the below-D floor (P = E x Prated) is approximated by the
    minimum-flow clamp at D x rated flow — the polynomial at D equals E
    within the table's rounding (riding curve 0.691 vs 0.68, VSD 0.043 vs
    0.04)."""
    if rule is None:
        return

    prefix = '8.4.5' if str(vintage) == '2025' else '8.4.4'
    stats = _proposed_pump_stats(proposed)
    if proposed is None:
        audit.info('efficiency', f'no proposed model supplied — {prefix}.14.(1)-(3) pump power transfer '
                                 f'skipped (Table {prefix}.14. curves still applied)', ruling='D-11')
    elif not stats:
        audit.warn('efficiency', 'proposed model has NO pumps with determinable power+flow — '
                                 f'{prefix}.14.(1)-(3) power NOT transferred to any reference pump',
                   ruling='D-11')
    for loop_ in sorted_by_name(model.getPlantLoops()):
        # 8.4.4.14 scopes HVAC hydronic pumping; a service-water loop's
        # circulator is Part 6 territory and stays as built. Transferring the
        # space-heating W/(L/s) intensity onto an SWH circulator (8 W against
        # the proposed's 1.9 MPa head) implies a 724% pump efficiency and is
        # an E+ FATAL — found by the gas-fuel variant sweep; the electric
        # fleet passed the same code path only by arithmetic luck.
        if _swh_loop(loop_):
            audit.info('efficiency',
                       'service water heating loop — outside 8.4.4.14 (HVAC hydronic pumps); pump left as built',
                       target=loop_.nameString(), ruling='D-27')
            continue

        loop_type = loop_.sizingPlant().loopType()
        for comp in sorted_by_name(loop_.supplyComponents()):
            if comp.to_PumpVariableSpeed().is_initialized():
                pump = comp.to_PumpVariableSpeed().get()
                row = rule['curves']['riding pump curve']
                pump.setCoefficient1ofthePartLoadPerformanceCurve(row['a'])
                pump.setCoefficient2ofthePartLoadPerformanceCurve(row['b'])
                pump.setCoefficient3ofthePartLoadPerformanceCurve(row['c'])
                pump.setCoefficient4ofthePartLoadPerformanceCurve(0.0)
                flow = optional_f(pump.ratedFlowRate()) or optional_f(pump.autosizedRatedFlowRate())
                if flow:
                    pump.setMinimumFlowRate(row['d'] * flow)
                audit.decision('efficiency', 'variable-flow pump modeled riding its curve',
                               target=pump.nameString(),
                               inputs={'coefficients': [row['a'], row['b'], row['c']],
                                       'minimum_flow_fraction': row['d'], 'loop': loop_.nameString()},
                               value=(f"below-D floor (E={row['e']}) via min flow "
                                      f"{ruby_round(row['d'] * flow, 5)} m3/s") if flow
                                     else 'coefficients set; min-flow clamp deferred (flow not sized)',
                               article=f'{prefix}.14.(4)-(5); Table {prefix}.14.', ruling='D-11')
                if proposed is not None and stats:
                    _transfer_pump_power(pump, flow, loop_type, stats, prefix, audit)
            elif comp.to_PumpConstantSpeed().is_initialized() and proposed is not None and stats:
                pump = comp.to_PumpConstantSpeed().get()
                flow = optional_f(pump.ratedFlowRate()) or optional_f(pump.autosizedRatedFlowRate())
                _transfer_pump_power(pump, flow, loop_type, stats, prefix, audit)
        _apply_pump_power_cap(loop_, loop_type, rule.get('power_caps_w_per_kw'), prefix, audit)


def _apply_pump_power_cap(loop_, loop_type, caps, prefix, audit):
    """D-38 (A3 ruled min-wins, phylroy 2026-07-28): 8.4.4.1.(2) makes the
    Part 5 prescriptive articles a CEILING for the reference, so after the
    8.4.4.14 intensity transfer the loop's COMBINED pump motor power is
    clamped at the Table 5.2.6.3 W/kW of the loop's peak thermal demand at
    design. min-wins: a proposed intensity below the cap transfers
    untouched; one above it is cut to the cap (audited). Applies with or
    without a proposed model (the cap binds the reference regardless)."""
    if caps is None:
        return

    row, thermal_kw = _pump_cap_basis(loop_, loop_type)
    rate = caps.get(row) if row else None
    if rate is None:
        return

    if thermal_kw is None or thermal_kw <= 0.0:
        audit.info('efficiency', "5.2.6.3 pump-power cap not evaluable — loop's peak thermal demand unsized",
                   target=loop_.nameString(), article='5.2.6.3.(1)', ruling='D-38')
        return
    pumps = []
    for c in loop_.supplyComponents():
        if c.to_PumpVariableSpeed().is_initialized():
            pumps.append(c.to_PumpVariableSpeed().get())
        elif c.to_PumpConstantSpeed().is_initialized():
            pumps.append(c.to_PumpConstantSpeed().get())
    powers = [optional_f(p.ratedPowerConsumption()) or optional_f(p.autosizedRatedPowerConsumption())
              for p in pumps]
    if not pumps or any(p is None for p in powers):
        audit.info('efficiency', '5.2.6.3 pump-power cap not evaluable — pump power unsized',
                   target=loop_.nameString(), article='5.2.6.3.(1)', ruling='D-38')
        return
    combined = sum(powers)
    cap_w = rate * thermal_kw
    if combined <= cap_w:
        audit.info('efficiency', 'combined pump power within the Table 5.2.6.3 maximum',
                   target=loop_.nameString(),
                   inputs={'combined_w': ruby_round(combined), 'cap_w': ruby_round(cap_w),
                           'w_per_kw': rate, 'thermal_kw': ruby_round(thermal_kw, 1), 'system_type': row},
                   article='5.2.6.3.(1)', ruling='D-38')
        return

    factor = cap_w / combined
    for pump, power in zip(pumps, powers):
        new_power = power * factor
        flow = optional_f(pump.ratedFlowRate()) or optional_f(pump.autosizedRatedFlowRate())
        # keep the flow/head/power triple physical (same guard as the transfer)
        _reconcile_pump_head(pump, new_power, flow)
        pump.setRatedPowerConsumption(new_power)
    audit.decision('efficiency', 'combined pump power exceeds Table 5.2.6.3 — clamped to the maximum '
                                 '(min-wins over the pump-power transfer)',
                   target=loop_.nameString(),
                   inputs={'before_w': ruby_round(combined), 'cap_w': ruby_round(cap_w), 'w_per_kw': rate,
                           'thermal_kw': ruby_round(thermal_kw, 1), 'system_type': row,
                           'scale': ruby_round(factor, 3)},
                   value=f'{ruby_round(combined)} W -> {ruby_round(cap_w)} W',
                   article=f'5.2.6.3.(1); {prefix}.1.(2)', ruling='D-38')


def _pump_cap_basis(loop_, loop_type):
    """Table 5.2.6.3 row + the loop's peak thermal demand (kW). A loop hosting
    water-to-air heat pump coils takes the WSHP row regardless of its
    sizing type; otherwise the row follows the Sizing:Plant loop type
    ('Condenser' = heat rejection, demand from the chillers it serves)."""
    wta = [c for c in loop_.demandComponents()
           if c.to_CoilCoolingWaterToAirHeatPumpEquationFit().is_initialized()
           or c.to_CoilHeatingWaterToAirHeatPumpEquationFit().is_initialized()]
    if wta:
        kw = 0.0
        for c in wta:
            coil = c.to_CoilCoolingWaterToAirHeatPumpEquationFit()
            if coil.empty():
                continue

            coil = coil.get()
            kw += (optional_f(coil.ratedTotalCoolingCapacity())
                   or optional_f(coil.autosizedRatedTotalCoolingCapacity()) or 0.0) / 1000.0
        return 'Water-source heat pump', (kw if kw > 0 else None)

    if loop_type == 'Heating':
        kw = 0.0
        for c in loop_.supplyComponents():
            if c.to_BoilerHotWater().is_initialized():
                b = c.to_BoilerHotWater().get()
                kw += (optional_f(b.nominalCapacity())
                       or optional_f(b.autosizedNominalCapacity()) or 0.0) / 1000.0
        return 'Heating', (kw if kw > 0 else None)
    if loop_type == 'Cooling':
        kw = 0.0
        for c in loop_.supplyComponents():
            if c.to_ChillerElectricEIR().is_initialized():
                ch = c.to_ChillerElectricEIR().get()
                kw += (optional_f(ch.referenceCapacity())
                       or optional_f(ch.autosizedReferenceCapacity()) or 0.0) / 1000.0
        return 'Cooling', (kw if kw > 0 else None)
    if loop_type == 'Condenser':
        kw = 0.0
        for c in loop_.demandComponents():
            if c.to_ChillerElectricEIR().is_initialized():
                ch = c.to_ChillerElectricEIR().get()
                cap = optional_f(ch.referenceCapacity()) or optional_f(ch.autosizedReferenceCapacity())
                kw += 0.0 if cap is None else cap * (1.0 + 1.0 / ch.referenceCOP()) / 1000.0
        return 'Heat rejection', (kw if kw > 0 else None)
    return None, None


def _swh_loop(loop_):
    """A service-water-heating loop: a water heater on supply or water-use
    connections on demand. Outside the 8.4.4.14 hydronic-pump scope."""
    return (any(c.to_WaterHeaterMixed().is_initialized() or c.to_WaterHeaterStratified().is_initialized()
                for c in loop_.supplyComponents())
            or any(c.to_WaterUseConnections().is_initialized() for c in loop_.demandComponents()))


# Sentences (1)-(3) through one mechanism: the proposed loop-type's pumps'
# combined peak power intensity, W/(L/s) — sentence (3)'s own metric, which
# equals head/efficiency (sentence (1): P = V x head / eff) and absorbs the
# multi-pump combination of sentence (2) by summing power AND flow. The
# reference pump's rated power is hard-set to that intensity times its own
# sized flow (reference flows legitimately differ from proposed flows, so
# the INTENSITY, not the absolute wattage, is what transfers).
# The total (wire-to-water) pump efficiency the reconciliation targets when
# a hard-set power and an inherited head disagree.
DESIGN_PUMP_EFFICIENCY = 0.65


def _reconcile_pump_head(pump, power_w, flow):
    """Keep a pump's flow/head/power triple physical whenever the power is
    hard-set (the 8.4.4.14 transfer and the 5.2.6.3 clamp both do that):
    EnergyPlus FATALS on a triple implying a pump efficiency above the motor
    efficiency. The transferred power is authoritative (it IS the article's
    number), so the inherited head is what gives.

    :return: bool — whether the head was changed"""
    if not (flow is not None and flow > 0 and float(power_w or 0.0) > 0):
        return False
    if (flow * pump.ratedPumpHead() / power_w) <= pump.motorEfficiency():
        return False

    pump.setRatedPumpHead(DESIGN_PUMP_EFFICIENCY * power_w / flow)
    return True


def _transfer_pump_power(pump, flow, loop_type, stats, prefix, audit):
    s = stats.get(loop_type)
    if s is None:
        audit.warn('efficiency', f'{pump.nameString()}: proposed has NO {loop_type}-type loop pumps with known '
                                 f'power+flow — {prefix}.14.(1)-(3) power NOT transferred (gem default retained)',
                   ruling='D-11')
        return
    if flow is None:
        audit.warn('efficiency', f'{pump.nameString()}: reference pump flow not sized — {prefix}.14.(1)-(3) '
                                 'transfer needs the sized flow; run sizing first', ruling='D-11')
        return
    w_per_l_s = s['power_w'] / s['flow_l_s']
    power_w = w_per_l_s * flow * 1000.0
    # E+ hard-rejects power/head/flow triples implying pump efficiency
    # above motor efficiency ("Calculated Pump Efficiency > 100%" fatal).
    # The transferred power is authoritative (it IS the article's number);
    # reconcile the inherited head to a physical 65% total efficiency.
    head = pump.ratedPumpHead()
    if _reconcile_pump_head(pump, power_w, flow):
        audit.warn('efficiency', f'{pump.nameString()}: inherited rated head {ruby_round(head)} Pa implies pump '
                                 f'efficiency above motor efficiency with the transferred {ruby_round(power_w)} W '
                                 f'— head reduced to {ruby_round(pump.ratedPumpHead())} Pa (65% total efficiency) '
                                 'to stay physical', ruling='D-27')
    pump.setRatedPowerConsumption(power_w)
    audit.decision('efficiency', 'pump power transferred from the proposed building',
                   target=pump.nameString(),
                   inputs={'proposed_pumps': s['count'], 'proposed_w_per_l_s': ruby_round(w_per_l_s, 2),
                           'reference_flow_l_s': ruby_round(flow * 1000.0, 2), 'loop_type': loop_type},
                   value=f'rated power {ruby_round(power_w, 0)} W (combined proposed intensity x reference flow)',
                   article=f'{prefix}.14.(1)-(3)', ruling='D-11')


def _proposed_pump_stats(proposed):
    """Combined peak power and flow of the PROPOSED building's pumps, grouped
    by plant-loop type ('Heating'/'Cooling'/'Condenser') — the loop-type
    correspondence sidesteps the pump-to-pump bijection that cannot exist
    between different topologies. Pumps whose power or flow cannot be read
    (unsized, no sql) are excluded; empty groups are dropped so callers can
    warn loudly instead of transferring zeros."""
    if proposed is None:
        return {}

    stats: dict = {}
    for loop_ in proposed.getPlantLoops():
        if _swh_loop(loop_):
            continue  # SWH circulators must not pollute the Heating-loop intensity

        type_ = loop_.sizingPlant().loopType()
        for comp in loop_.supplyComponents():
            pump = comp.to_PumpVariableSpeed().get() if comp.to_PumpVariableSpeed().is_initialized() else None
            if pump is None:
                pump = (comp.to_PumpConstantSpeed().get()
                        if comp.to_PumpConstantSpeed().is_initialized() else None)
            if pump is None:
                continue

            power = (optional_f(pump.ratedPowerConsumption())
                     or optional_f(pump.autosizedRatedPowerConsumption()))
            flow = optional_f(pump.ratedFlowRate()) or optional_f(pump.autosizedRatedFlowRate())
            if power is None or flow is None or flow == 0:
                continue

            entry = stats.setdefault(type_, {'power_w': 0.0, 'flow_l_s': 0.0, 'count': 0})
            entry['power_w'] += power
            entry['flow_l_s'] += flow * 1000.0
            entry['count'] += 1
    return {k: s for k, s in stats.items() if s['flow_l_s'] != 0}


def _align_heat_pump_heating_capacity(model, audit, requested_vintage='2020'):
    """T4 (audit 2026-07-25) 8.4.4.13.(2)(c): "the heat pump's heating capacity
    at an outdoor air temperature of 8.3 C shall be identical to its cooling
    capacity". The vendored CAP_FT cubic evaluates ~1.0 at 8.3 C, so pinning
    the RATED heating capacity to the rated cooling capacity realizes the
    sentence (the -8.3 C 50% point comes from the same curve). Post-sizing:
    both capacities must be readable; paired coils only (same air loop).

    :param requested_vintage: the CODE edition ('2020'/'2025'), which decides
        whether the heat-pump article is numbered 8.4.4.13 or 8.4.5.13"""
    hp_article = '8.4.5.13.(2)(c)' if str(requested_vintage) == '2025' else '8.4.4.13.(2)(c)'
    for loop_ in sorted_by_name(model.getAirLoopHVACs()):
        comps = _coils.supply_components(loop_)
        staged_heat = next((c for c in comps if c.to_CoilHeatingDXMultiSpeed().is_initialized()), None)
        staged_cool = next((c for c in comps if c.to_CoilCoolingDXMultiSpeed().is_initialized()), None)
        if staged_heat is not None and staged_cool is not None:
            _align_staged_heat_pump(staged_heat.to_CoilHeatingDXMultiSpeed().get(),
                                    staged_cool.to_CoilCoolingDXMultiSpeed().get(), audit, hp_article)
            continue

        heat = next((c for c in comps if c.to_CoilHeatingDXSingleSpeed().is_initialized()), None)
        cool = next((c for c in comps if c.to_CoilCoolingDXSingleSpeed().is_initialized()), None)
        if heat is None or cool is None:
            continue

        heat = heat.to_CoilHeatingDXSingleSpeed().get()
        cool = cool.to_CoilCoolingDXSingleSpeed().get()
        cool_w = (optional_f(cool.ratedTotalCoolingCapacity())
                  or optional_f(cool.autosizedRatedTotalCoolingCapacity()))
        if cool_w is None:
            audit.warn('efficiency', f'{heat.nameString()}: cooling capacity unavailable — 8.4.4.13.(2)(c) '
                                     'heating=cooling alignment skipped (run sizing first)')
            continue

        heat.setRatedTotalHeatingCapacity(cool_w)
        audit.decision('efficiency', 'heat pump heating capacity pinned to cooling capacity',
                       target=heat.nameString(), inputs={'cooling_kw': ruby_round(cool_w / 1000.0, 1)},
                       value=f'rated heating capacity = {ruby_round(cool_w / 1000.0, 1)} kW '
                             '(CAP_FT ~1.0 at 8.3 C)',
                       article=hp_article, ruling='D-22')


def _align_staged_heat_pump(heat, cool, audit, hp_article='8.4.4.13.(2)(c)'):
    """Same sentence on a STAGED heat pump: the unit's heating capacity is its
    top stage, so the top stages are what must match. The lower stages follow
    the cooling coil's own increments stage-for-stage, which keeps the two
    coils staged identically (both were sized to the same k/N ratios).
    This pins capacities that were autosized — the article demands a specific
    capacity, so the same D-22 exception that governs the single-speed coil
    governs here; the COOLING side stays autosized and drives the pair."""
    heat_stages = list(heat.stages())
    cool_stages = list(cool.stages())
    pairs = [(h, cool_stages[i] if i < len(cool_stages) else None)
             for i, h in enumerate(heat_stages)]
    if any(c is None for _, c in pairs):
        audit.warn('efficiency', f'{heat.nameString()}: staged heat pump has MORE heating stages than cooling '
                                 'stages — 8.4.4.13.(2)(c) alignment applied only to the matched stages',
                   target=heat.nameString(), article=hp_article, ruling='D-22')
    top = None
    for heat_stage, cool_stage in pairs:
        if cool_stage is None:
            continue

        cool_w = (optional_f(cool_stage.grossRatedTotalCoolingCapacity())
                  or optional_f(cool_stage.autosizedGrossRatedTotalCoolingCapacity()))
        if cool_w is None:
            continue

        heat_stage.setGrossRatedHeatingCapacity(cool_w)
        top = cool_w
    if top is None:
        audit.warn('efficiency', f'{heat.nameString()}: staged cooling capacity unavailable — 8.4.4.13.(2)(c) '
                                 'heating=cooling alignment skipped (run sizing first)',
                   target=heat.nameString(), article=hp_article, ruling='D-22')
        return
    audit.decision('efficiency', 'staged heat pump heating capacity pinned to cooling capacity, stage for stage',
                   target=heat.nameString(),
                   inputs={'stages': len(heat.stages()), 'cooling_kw': ruby_round(top / 1000.0, 1)},
                   value=f'top-stage heating capacity = {ruby_round(top / 1000.0, 1)} kW (CAP_FT ~1.0 at 8.3 C)',
                   article=hp_article, ruling='D-22 D-46')


# ---------------- table lookup (legacy model_find_object semantics) ----------------

def find_row(table, criteria, capacity=None):
    """Rows match when every criteria key PRESENT in the row equals the wanted value (a
    missing key or 'Any' is a wildcard); capacity matches min < cap <= max, retried at
    0.99x on boundary misses; date ranges are honored when present."""
    rows = [row for row in table
            if all(k not in row or row[k] is None or row[k] == 'Any' or row[k] == v
                   for k, v in criteria.items())
            and _date_ok(row)]
    if capacity is None:
        return rows[0] if rows else None

    rows = [r for r in rows
            if _numeric(r.get('minimum_capacity')) or isinstance(r.get('minimum_capacity'), str)]
    match = [r for r in rows if _in_capacity_range(r, capacity)]
    if not match:
        match = [r for r in rows if _in_capacity_range(r, capacity * 0.99)]
    return match[0] if match else None


def _in_capacity_range(row, capacity):
    minimum = _to_f(row.get('minimum_capacity'))
    maximum = _to_f(row.get('maximum_capacity'))
    return capacity > minimum and capacity <= maximum


def _numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


_LEADING_FLOAT_RE = re.compile(r'\A\s*[+-]?(\d+\.?\d*([eE][+-]?\d+)?|\.\d+([eE][+-]?\d+)?)')


def _to_f(value):
    """Ruby's #to_f: nil -> 0.0, String -> leading float or 0.0, Numeric -> itself."""
    if value is None:
        return 0.0
    if _numeric(value):
        return float(value)
    match = _LEADING_FLOAT_RE.match(str(value))
    return float(match.group(0)) if match else 0.0


def _date_ok(row):
    if not (row.get('start_date') and row.get('end_date')):
        return True

    try:
        today = date.today()
        starts = _parse_date(row['start_date'], date(1900, 1, 1))
        ends = _parse_date(row['end_date'], date(2999, 1, 1))
        return today >= starts and today <= ends
    except Exception:
        return True


def _parse_date(value, fallback):
    """Ruby's `Date.parse(value.to_s) rescue fallback`. The vendored tables carry
    both an ISO-8601 timestamp and a bare 'D/M/YYYY' (Ruby reads slashes
    day-first), so both spellings are honoured before falling back."""
    text = str(value)
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    try:
        return datetime.strptime(text, '%d/%m/%Y').date()
    except ValueError:
        return fallback


# ---------------- conversions (ports of OpenstudioStandards::HVAC) ----------------

W_PER_BTUH = 0.2930710701722222


def seer_to_cop_no_fan(seer):
    return (-0.0076 * seer * seer) + (0.3796 * seer)


def hspf_to_cop_no_fan(hspf):
    return (-0.0296 * hspf * hspf) + (0.7134 * hspf)


def kw_per_ton_to_cop(kw_per_ton):
    return 3.517 / kw_per_ton


def afue_to_thermal_eff(afue):
    return afue


def combustion_eff_to_thermal_eff(eff):
    return eff - 0.007


def cop_heating_to_cop_heating_no_fan(coph47, capacity_w):
    return (1.48E-7 * coph47 * (capacity_w / W_PER_BTUH)) + (1.062 * coph47)


def eer_to_cop_no_fan(eer, capacity_w=None):
    if capacity_w is None:
        r = 0.12  # supply-fan fraction of total power, Thornton et al. 2011
        return ((eer * W_PER_BTUH) + r) / (1 - r)
    return (7.84E-8 * eer * (capacity_w / W_PER_BTUH)) + (0.338 * eer)


def w_to_btu_per_hr(watts):
    return watts / W_PER_BTUH


def w_to_kbtu_per_hr(watts):
    return watts / W_PER_BTUH / 1000.0


def w_to_tons(watts):
    return watts / 3516.8525


# ---------------- curves ----------------

def curve(model, tables, name):
    """Build (or reuse by name) a performance curve from a vendored curve row."""
    if name is None or str(name) == '':
        return None

    existing = next((c for c in model.getCurves() if c.nameString() == name), None)
    if existing is not None:
        return existing

    row = next((c for c in tables['curves'] if c['name'] == name), None)
    if row is None:
        return None

    coeffs = [row.get(f'coeff_{i}') for i in range(1, 11)]
    form = row.get('form')
    if form in ('BiQuadratic', 'Biquadratic'):
        k = openstudio.model.CurveBiquadratic(model)
        k.setCoefficient1Constant(coeffs[0])
        k.setCoefficient2x(coeffs[1])
        k.setCoefficient3xPOW2(coeffs[2])
        k.setCoefficient4y(coeffs[3])
        k.setCoefficient5yPOW2(coeffs[4])
        k.setCoefficient6xTIMESY(coeffs[5])
        set_limits(k, row, two_vars=True)
        c = k
    elif form in ('BiCubic', 'Bicubic'):
        k = openstudio.model.CurveBicubic(model)
        k.setCoefficient1Constant(coeffs[0])
        k.setCoefficient2x(coeffs[1])
        k.setCoefficient3xPOW2(coeffs[2])
        k.setCoefficient4y(coeffs[3])
        k.setCoefficient5yPOW2(coeffs[4])
        k.setCoefficient6xTIMESY(coeffs[5])
        k.setCoefficient7xPOW3(coeffs[6])
        k.setCoefficient8yPOW3(coeffs[7])
        k.setCoefficient9xPOW2TIMESY(coeffs[8])
        k.setCoefficient10xTIMESYPOW2(coeffs[9])
        set_limits(k, row, two_vars=True)
        c = k
    elif form == 'Cubic':
        k = openstudio.model.CurveCubic(model)
        k.setCoefficient1Constant(coeffs[0])
        k.setCoefficient2x(coeffs[1])
        k.setCoefficient3xPOW2(coeffs[2])
        k.setCoefficient4xPOW3(coeffs[3])
        set_limits(k, row)
        c = k
    elif form == 'Quadratic':
        k = openstudio.model.CurveQuadratic(model)
        k.setCoefficient1Constant(coeffs[0])
        k.setCoefficient2x(coeffs[1])
        k.setCoefficient3xPOW2(coeffs[2])
        set_limits(k, row)
        c = k
    else:
        return None
    c.setName(name)
    return c


def set_limits(curve_object, row, two_vars=False):
    if row.get('minimum_independent_variable_1'):
        curve_object.setMinimumValueofx(row['minimum_independent_variable_1'])
    if row.get('maximum_independent_variable_1'):
        curve_object.setMaximumValueofx(row['maximum_independent_variable_1'])
    if two_vars:
        if row.get('minimum_independent_variable_2'):
            curve_object.setMinimumValueofy(row['minimum_independent_variable_2'])
        if row.get('maximum_independent_variable_2'):
            curve_object.setMaximumValueofy(row['maximum_independent_variable_2'])
    if hasattr(curve_object, 'setMinimumCurveOutput'):
        if row.get('minimum_dependent_variable_output'):
            curve_object.setMinimumCurveOutput(row['minimum_dependent_variable_output'])
        if row.get('maximum_dependent_variable_output'):
            curve_object.setMaximumCurveOutput(row['maximum_dependent_variable_output'])


# ---------------- capacities ----------------

def optional_f(value):
    """Unwrap an SDK optional numeric to a float, or None when uninitialized."""
    if value is None:
        return None
    if not hasattr(value, 'is_initialized'):
        return float(value)
    return float(value.get()) if value.is_initialized() else None


# ---------------- component appliers ----------------

def _apply_boiler(boiler, tables, plant, audit):
    """Legacy boiler_hot_water_apply_efficiency_and_curves (NECB2011 hvac_systems.rb:539):
    primary/secondary staging (176/352 kW), EFFFPLR curve, AFUE/thermal/combustion ->
    thermal efficiency, legacy rename."""
    fuel_type = boiler.fuelType()
    if fuel_type == 'Electricity':
        fuel = 'Electric'
    elif fuel_type in ('FuelOilNo1', 'FuelOilNo2'):
        fuel = 'Oil'
    else:
        fuel = 'Gas'
    capacity_w = optional_f(boiler.nominalCapacity()) or optional_f(boiler.autosizedNominalCapacity())
    if capacity_w is None:
        return audit.warn('efficiency', 'boiler capacity unavailable (model not sized?) — not set',
                          target=boiler.nameString())

    boiler_capacity = capacity_w
    name = boiler.nameString()
    if 'Primary Boiler' in name or 'Secondary Boiler' in name:
        kw = capacity_w / 1000.0
        if kw > plant['two_boiler_max_kw']:  # 8.4.4.9.(6)(d): 'exceeds 352 kW' (strict)
            if 'Primary Boiler' in name:
                boiler.setBoilerFlowMode('LeavingSetpointModulated')
                boiler.setMinimumPartLoadRatio(plant['modulating_min_fraction'])
            else:
                boiler_capacity = 0.001
        elif kw > plant['single_boiler_max_kw']:  # (6)(c): 'greater than 176' (strict)
            boiler_capacity = capacity_w / 2
        elif 'Secondary Boiler' in name:
            boiler_capacity = 0.001
        elif capacity_w <= 1.0:
            boiler_capacity = 1.0
    boiler.setNominalCapacity(boiler_capacity)

    cap_btuh = w_to_btu_per_hr(boiler_capacity)
    row = find_row(tables['boilers'], {'fluid_type': 'Hot Water', 'fuel_type': fuel}, cap_btuh)
    if row is None:
        return audit.warn('efficiency', 'no boiler efficiency row found — not set', target=name,
                          inputs={'fuel': fuel, 'capacity_btu_hr': ruby_round(cap_btuh)})

    eff_fplr = curve(boiler.model(), tables, row.get('efffplr'))
    if eff_fplr:
        boiler.setNormalizedBoilerEfficiencyCurve(eff_fplr)

    thermal_eff, label = boiler_thermal_efficiency(row)
    if thermal_eff is None:
        return audit.warn('efficiency', 'boiler row has no efficiency value — not set', target=name)

    boiler.setNominalThermalEfficiency(thermal_eff)
    boiler.setName(f'{name} {ruby_round(w_to_kbtu_per_hr(boiler_capacity))}kBtu/hr {label}')
    return audit.decision('efficiency', 'boiler efficiency applied', target=name,
                          inputs={'fuel': fuel, 'capacity_kw': ruby_round(boiler_capacity / 1000.0, 1)},
                          value=f"thermal efficiency {ruby_round(thermal_eff, 3)} ({label}), "
                                f"curve {row.get('efffplr')}",
                          article='NECB 2020 Table 5.2.12.1 (boilers)')


def boiler_thermal_efficiency(row):
    if row.get('minimum_annual_fuel_utilization_efficiency'):
        return (afue_to_thermal_eff(row['minimum_annual_fuel_utilization_efficiency']),
                f"{row['minimum_annual_fuel_utilization_efficiency']} AFUE")
    if row.get('minimum_thermal_efficiency'):
        return (row['minimum_thermal_efficiency'],
                f"{row['minimum_thermal_efficiency']} Thermal Eff")
    if row.get('minimum_combustion_efficiency'):
        return (combustion_eff_to_thermal_eff(row['minimum_combustion_efficiency']),
                f"{row['minimum_combustion_efficiency']} Combustion Eff")
    return None, None


def _apply_chiller(chiller, tables, plant, audit):
    """Legacy chiller_electric_eir_apply_efficiency_and_curves (NECB2011:648): modulating
    to 25%, primary/secondary 2100 kW split, curves, kW/ton -> COP, tower sizing."""
    name = chiller.nameString()
    capacity_w = (optional_f(chiller.referenceCapacity())
                  or optional_f(chiller.autosizedReferenceCapacity()))
    if capacity_w is None:
        return audit.warn('efficiency', 'chiller capacity unavailable (model not sized?) — not set', target=name)

    chiller.setChillerFlowMode('LeavingSetpointModulated')
    chiller.setMinimumPartLoadRatio(plant['modulating_min_fraction'])
    chiller.setMinimumUnloadingRatio(plant['modulating_min_fraction'])

    chiller_capacity = capacity_w
    if 'Primary' in name or 'Secondary' in name:
        # 8.4.4.10.(6)(b): 'not greater than 2100'
        if capacity_w / 1000.0 <= plant['single_chiller_max_kw']:
            if 'Secondary Chiller' in name:
                chiller_capacity = 0.001
        else:
            chiller_capacity = capacity_w / 2.0
    chiller.setReferenceCapacity(chiller_capacity)

    cooling_type = 'AirCooled' if chiller.condenserType() == 'AirCooled' else 'WaterCooled'
    compressor = next((t for t in ('Reciprocating', 'Scroll', 'Centrifugal')
                       if t.lower() in name.lower()), None)
    if compressor is None and 'screw' in name.lower():
        compressor = 'Rotary Screw'
    if compressor is None:
        audit.warn('efficiency', 'chiller compressor type not in name — Scroll assumed', target=name)
        compressor = 'Scroll'

    tons = w_to_tons(chiller_capacity)
    row = find_row(tables['chillers'],
                   {'cooling_type': cooling_type, 'compressor_type': compressor}, tons)
    if row is None:
        return audit.warn('efficiency', 'no chiller efficiency row found — not set', target=name,
                          inputs={'cooling_type': cooling_type, 'compressor': compressor,
                                  'tons': ruby_round(tons, 1)})

    for key, setter in zip(('capft', 'eirft', 'eirfplr'),
                           ('setCoolingCapacityFunctionOfTemperature',
                            'setElectricInputToCoolingOutputRatioFunctionOfTemperature',
                            'setElectricInputToCoolingOutputRatioFunctionOfPLR')):
        c = curve(chiller.model(), tables, row.get(key))
        if c:
            getattr(chiller, setter)(c)

    kw_per_ton = row.get('minimum_full_load_efficiency')
    if kw_per_ton is None:
        return audit.warn('efficiency', 'chiller row has no full-load efficiency — COP not set', target=name)

    cop = kw_per_ton_to_cop(kw_per_ton)
    chiller.setReferenceCOP(cop)
    chiller.setName(f'{name} {ruby_round(tons)}tons {ruby_round(kw_per_ton, 1)}kW/ton')
    return audit.decision('efficiency', 'chiller efficiency applied', target=name,
                          inputs={'cooling_type': cooling_type, 'compressor': compressor,
                                  'tons': ruby_round(tons, 1)},
                          value=f'COP {ruby_round(cop, 2)} ({ruby_round(kw_per_ton, 2)} kW/ton), '
                                f"curves {row.get('capft')}/{row.get('eirft')}/{row.get('eirfplr')}",
                          article='NECB 2020 Table 5.2.12.1 (chillers)')


def _apply_tower_rules(model, audit):
    """Legacy tower rules: cells per 1750 kW of heat rejection; fan at the
    Table 5.2.12.2 maximum. Runs as its OWN pass after every chiller
    capacity is final: the tower rejects heat for EVERY chiller on its
    condenser loop, and a two-chiller plant (8.4.4.10.(6) split) halves
    the per-chiller capacity — sizing the fan from the Primary alone
    starves E+'s fan-power-derived autosized air flow until the tower UA
    solve fails ("Bad starting values for UA"; found by the LargeOffice
    archetype, the first two-chiller+tower fleet member)."""
    for loop in sorted_by_name(model.getPlantLoops()):
        towers = [c.to_CoolingTowerSingleSpeed().get() for c in loop.supplyComponents()
                  if c.to_CoolingTowerSingleSpeed().is_initialized()]
        if not towers:
            continue

        chillers = [c.to_ChillerElectricEIR().get() for c in loop.demandComponents()
                    if c.to_ChillerElectricEIR().is_initialized()]
        tower_cap = 0.0
        for ch in chillers:
            cap = optional_f(ch.referenceCapacity()) or optional_f(ch.autosizedReferenceCapacity())
            tower_cap += 0.0 if cap is None else cap * (1.0 + 1.0 / ch.referenceCOP())
        if tower_cap <= 0.0:
            audit.warn('efficiency',
                       'condenser loop has a tower but no readable chiller capacity — tower rules not applied',
                       target=towers[0].nameString(), ruling='D-26')
            continue

        # 8.4.4.11.(2)-(3): one cell up to 1750 kW; above, capacity/1750 rounded UP
        cells = 1 if tower_cap / 1000.0 <= 1750 else math.ceil(tower_cap / (1000.0 * 1750))
        towers[0].setNumberofCells(cells)
        # Table 5.2.12.2 (NECB 2015+ incl. 2020/2025): axial direct-contact tower
        # fan <= 0.013 kW/kW rejection — NOT the 2011 value 0.015 (T2, audit
        # 2026-07-25; legacy NECB2015 override uses 0.013). Below the 13 kW
        # small-tower threshold the E+ default fan sizing stands.
        fan_w = 0.013 * tower_cap
        if fan_w > 13_000.0:
            # Harden the sizing run's tower hydraulics BEFORE overriding the fan:
            # E+ derives autosized tower air flow FROM fan power and then solves
            # UA by regula falsi — re-running sizing with a hard code fan lands
            # in an infeasible solver band ("Bad starting values for UA";
            # LargeOffice fails at 17-30 kW while its 15.9 kW autosize and
            # 39.3 kW both pass — legacy clears the band by luck). Pinning
            # water/air/UA at their solved values leaves nothing to re-solve;
            # Table 5.2.12.2 governs fan POWER only, so the code fan rides on
            # E+'s self-consistent heat-transfer sizing.
            for getter, setter in (
                    ('autosizedDesignWaterFlowRate', 'setDesignWaterFlowRate'),
                    ('autosizedDesignAirFlowRate', 'setDesignAirFlowRate'),
                    ('autosizedUFactorTimesAreaValueatDesignAirFlowRate',
                     'setUFactorTimesAreaValueatDesignAirFlowRate'),
                    ('autosizedAirFlowRateinFreeConvectionRegime',
                     'setAirFlowRateinFreeConvectionRegime'),
                    ('autosizedUFactorTimesAreaValueatFreeConvectionAirFlowRate',
                     'setUFactorTimesAreaValueatFreeConvectionAirFlowRate')):
                v = getattr(towers[0], getter)()
                if hasattr(v, 'is_initialized') and v.is_initialized():
                    getattr(towers[0], setter)(v.get())
            towers[0].setFanPoweratDesignAirFlowRate(fan_w)
        audit.decision('efficiency', 'cooling tower cells set from heat rejection',
                       target=towers[0].nameString(),
                       inputs={'tower_cap_kw': ruby_round(tower_cap / 1000.0, 1),
                               'chillers_on_loop': len(chillers)},
                       value=f'{cells} cell(s)', article='8.4.4.11.(2)-(3)', ruling='D-26')
        if fan_w > 13_000.0:
            audit.decision('efficiency', 'cooling tower fan power set at the Table 5.2.12.2 maximum',
                           target=towers[0].nameString(),
                           inputs={'kw_per_kw': 0.013, 'tower_cap_kw': ruby_round(tower_cap / 1000.0, 1)},
                           value=f'fan {ruby_round(fan_w / 1000.0, 1)} kW',
                           article='Table 5.2.12.2', ruling='D-22')


def _apply_dx_cooling(coil, tables, audit):
    """Legacy coil_cooling_dx_single_speed_apply_efficiency_and_curves via NECB
    unitary_acs/heat_pumps tables: SEER/EER -> COP (no fan) + performance curves."""
    name = coil.nameString()
    capacity_w = (optional_f(coil.ratedTotalCoolingCapacity())
                  or optional_f(coil.autosizedRatedTotalCoolingCapacity()))
    if capacity_w is None:
        return audit.warn('efficiency', 'DX cooling capacity unavailable (model not sized?) — not set',
                          target=name)

    heat_pump = paired_with_dx_heating(coil)
    table = tables['heat_pumps'] if heat_pump else tables['unitary_acs']
    heating_type = 'Electric Resistance or None' if electric_or_no_heating(coil) else 'All Other'
    cap_btuh = w_to_btu_per_hr(capacity_w)
    row = find_row(table, {'cooling_type': 'AirCooled', 'heating_type': heating_type,
                           'subcategory': 'Single Package'}, cap_btuh)
    if row is None:
        row = find_row(table, {'cooling_type': 'AirCooled', 'subcategory': 'Single Package'}, cap_btuh)
    if row is None:
        return audit.warn('efficiency', 'no DX cooling efficiency row found — not set', target=name,
                          inputs={'heat_pump': heat_pump, 'heating_type': heating_type,
                                  'capacity_btu_hr': ruby_round(cap_btuh)})

    # SEER2/EER2 converted like SEER/EER — the documented openstudio-standards
    # assumption (Standards.CoilCoolingDXSingleSpeed: 'assumed to be the same').
    cop_label = dx_cooling_cop(row)
    if cop_label is None:
        return audit.warn('efficiency', 'DX cooling row has no efficiency value — not set', target=name)
    cop, label = cop_label

    coil.setRatedCOP(cop)
    for key, setter in (('cool_cap_ft', 'setTotalCoolingCapacityFunctionOfTemperatureCurve'),
                        ('cool_cap_fflow', 'setTotalCoolingCapacityFunctionOfFlowFractionCurve'),
                        ('cool_eir_ft', 'setEnergyInputRatioFunctionOfTemperatureCurve'),
                        ('cool_eir_fflow', 'setEnergyInputRatioFunctionOfFlowFractionCurve'),
                        ('cool_plf_fplr', 'setPartLoadFractionCorrelationCurve')):
        c = curve(coil.model(), tables, row.get(key))
        if c:
            getattr(coil, setter)(c)
    coil.setName(f'{name} {ruby_round(w_to_kbtu_per_hr(capacity_w))}kBtu/hr {label}')
    return audit.decision('efficiency', 'DX cooling efficiency applied', target=name,
                          inputs={'table': 'heat_pumps' if heat_pump else 'unitary_acs',
                                  'heating_type': heating_type,
                                  'capacity_kw': ruby_round(capacity_w / 1000.0, 1)},
                          value=f'COP {ruby_round(cop, 2)} ({label})',
                          article='NECB 2020 Table 5.2.12.1 (unitary equipment)')


def _apply_dx_cooling_multi(coil, tables, audit, capacity_w=None):
    """Staged DX cooling (8.4.4.10.(8)). Binned by TOP-stage capacity — which IS
    the unit's total capacity — against the same unitary_acs/heat_pumps
    tables as the single-speed coil, with the row's COP and curves applied to
    EVERY stage. That is exactly what the legacy multispeed applier does
    (one row read from the last stage, same values per stage): the tables are
    unit-capacity tables, not per-stage tables."""
    name = coil.nameString()
    if capacity_w is None:
        capacity_w = _top_stage_capacity(coil)
    if capacity_w is None:
        return audit.warn('efficiency', 'staged DX cooling capacity unavailable (model not sized?) — not set',
                          target=name)

    heat_pump = paired_with_dx_heating(coil)
    table = tables['heat_pumps'] if heat_pump else tables['unitary_acs']
    heating_type = 'Electric Resistance or None' if electric_or_no_heating(coil) else 'All Other'
    cap_btuh = w_to_btu_per_hr(capacity_w)
    row = find_row(table, {'cooling_type': 'AirCooled', 'heating_type': heating_type,
                           'subcategory': 'Single Package'}, cap_btuh)
    if row is None:
        row = find_row(table, {'cooling_type': 'AirCooled', 'subcategory': 'Single Package'}, cap_btuh)
    if row is None:
        return audit.warn('efficiency', 'no DX cooling efficiency row found — not set', target=name,
                          inputs={'heat_pump': heat_pump, 'heating_type': heating_type,
                                  'capacity_btu_hr': ruby_round(cap_btuh)})

    cop_label = dx_cooling_cop(row)
    if cop_label is None:
        return audit.warn('efficiency', 'DX cooling row has no efficiency value — not set', target=name)
    cop, label = cop_label

    curves = (('cool_cap_ft', 'setTotalCoolingCapacityFunctionofTemperatureCurve'),
              ('cool_cap_fflow', 'setTotalCoolingCapacityFunctionofFlowFractionCurve'),
              ('cool_eir_ft', 'setEnergyInputRatioFunctionofTemperatureCurve'),
              ('cool_eir_fflow', 'setEnergyInputRatioFunctionofFlowFractionCurve'),
              ('cool_plf_fplr', 'setPartLoadFractionCorrelationCurve'))
    for stage in coil.stages():
        stage.setGrossRatedCoolingCOP(cop)
        for key, setter in curves:
            c = curve(coil.model(), tables, row.get(key))
            if c:
                getattr(stage, setter)(c)
    coil.setName(f'{name} {ruby_round(w_to_kbtu_per_hr(capacity_w))}kBtu/hr {label}')
    return audit.decision('efficiency', 'staged DX cooling efficiency applied to every stage', target=name,
                          inputs={'table': 'heat_pumps' if heat_pump else 'unitary_acs',
                                  'stages': len(coil.stages()), 'heating_type': heating_type,
                                  'top_stage_kw': ruby_round(capacity_w / 1000.0, 1)},
                          value=f'COP {ruby_round(cop, 2)} ({label}) on all {len(coil.stages())} stages, '
                                'binned by total capacity',
                          article='NECB 2020 Table 5.2.12.1 (unitary equipment)', ruling='D-46')


def dx_cooling_cop(row):
    """The SEER/EER/full-load ladder shared by the single- and multi-speed DX
    cooling appliers. :return: (float, str) or None"""
    if row.get('minimum_seasonal_energy_efficiency_ratio'):
        return (seer_to_cop_no_fan(row['minimum_seasonal_energy_efficiency_ratio']),
                f"{row['minimum_seasonal_energy_efficiency_ratio']}SEER")
    if row.get('minimum_seasonal_energy_efficiency_ratio_2'):
        return (seer_to_cop_no_fan(row['minimum_seasonal_energy_efficiency_ratio_2']),
                f"{row['minimum_seasonal_energy_efficiency_ratio_2']}SEER2")
    if row.get('minimum_seasonal_efficiency'):
        return (seer_to_cop_no_fan(row['minimum_seasonal_efficiency']),
                f"{row['minimum_seasonal_efficiency']}SEER")
    if row.get('minimum_energy_efficiency_ratio'):
        return (eer_to_cop_no_fan(row['minimum_energy_efficiency_ratio']),
                f"{row['minimum_energy_efficiency_ratio']}EER")
    if row.get('minimum_energy_efficiency_ratio_2'):
        return (eer_to_cop_no_fan(row['minimum_energy_efficiency_ratio_2']),
                f"{row['minimum_energy_efficiency_ratio_2']}EER2")
    if row.get('minimum_full_load_efficiency'):
        return (eer_to_cop_no_fan(row['minimum_full_load_efficiency']),
                f"{row['minimum_full_load_efficiency']}EER")
    return None


def _apply_dx_heating_multi(coil, tables, audit, capacity_w=None):
    """Staged DX heating (reference ASHP). Same top-stage binning contract as
    the staged cooling applier."""
    name = coil.nameString()
    if capacity_w is None:
        capacity_w = _top_stage_capacity(coil)
    if capacity_w is None:
        return audit.warn('efficiency', 'staged DX heating capacity unavailable (model not sized?) — not set',
                          target=name)

    cap_btuh = w_to_btu_per_hr(capacity_w)
    row = find_row(tables['heat_pumps_heating'],
                   {'cooling_type': 'AirCooled', 'subcategory': 'Single Package'}, cap_btuh)
    if row is None:
        return audit.warn('efficiency', 'no DX heating efficiency row found — not set', target=name,
                          inputs={'capacity_btu_hr': ruby_round(cap_btuh)})

    cop_label = dx_heating_cop(row, capacity_w)
    if cop_label is None:
        return audit.warn('efficiency', 'DX heating row has no efficiency value — not set', target=name)
    cop, label = cop_label

    curves = (('heat_cap_ft', 'setHeatingCapacityFunctionofTemperatureCurve'),
              ('heat_cap_fflow', 'setHeatingCapacityFunctionofFlowFractionCurve'),
              ('heat_eir_ft', 'setEnergyInputRatioFunctionofTemperatureCurve'),
              ('heat_eir_fflow', 'setEnergyInputRatioFunctionofFlowFractionCurve'),
              ('heat_plf_fplr', 'setPartLoadFractionCorrelationCurve'))
    for stage in coil.stages():
        stage.setGrossRatedHeatingCOP(cop)
        for key, setter in curves:
            c = curve(coil.model(), tables, row.get(key))
            if c and hasattr(stage, setter):
                getattr(stage, setter)(c)
    coil.setName(f'{name} {ruby_round(w_to_kbtu_per_hr(capacity_w))}kBtu/hr {label}')
    return audit.decision('efficiency', 'staged DX heating efficiency applied to every stage', target=name,
                          inputs={'stages': len(coil.stages()),
                                  'top_stage_kw': ruby_round(capacity_w / 1000.0, 1)},
                          value=f'heating COP {ruby_round(cop, 2)} ({label}) on all '
                                f'{len(coil.stages())} stages',
                          article='NECB 2020 Table 5.2.12.1 (heat pumps, heating)', ruling='D-46')


def dx_heating_cop(row, capacity_w):
    """:return: (float, str) or None"""
    if row.get('minimum_heating_seasonal_performance_factor'):
        return (hspf_to_cop_no_fan(row['minimum_heating_seasonal_performance_factor']),
                f"{row['minimum_heating_seasonal_performance_factor']}HSPF")
    if row.get('minimum_heating_seasonal_performance_factor_2'):
        # HSPF2 converted like HSPF (consistent with the SEER2/EER2 assumption)
        return (hspf_to_cop_no_fan(row['minimum_heating_seasonal_performance_factor_2']),
                f"{row['minimum_heating_seasonal_performance_factor_2']}HSPF2")
    if row.get('minimum_coefficient_of_performance_heating'):
        return (cop_heating_to_cop_heating_no_fan(row['minimum_coefficient_of_performance_heating'],
                                                  capacity_w),
                f"{row['minimum_coefficient_of_performance_heating']}COPH")
    return None


def _apply_gas_multi(coil, tables, audit, capacity_w=None):
    """Staged gas furnace (8.4.4.9.(7)). Binned by TOP-stage (= total) capacity
    against the same furnaces table; the burner efficiency goes on every
    stage and the part-load curve on the parent coil."""
    name = coil.nameString()
    if capacity_w is None:
        capacity_w = _top_stage_capacity(coil)
    if capacity_w is None:
        return audit.warn('efficiency', 'staged gas coil capacity unavailable (model not sized?) — not set',
                          target=name)

    cap_btuh = max(w_to_btu_per_hr(capacity_w), 0.001)
    row = find_row(tables['furnaces'], {'fluid_type': 'Air', 'fuel_type': 'Gas'}, cap_btuh)
    if row is None:
        return audit.warn('efficiency', 'no furnace efficiency row found — not set', target=name,
                          inputs={'capacity_btu_hr': ruby_round(cap_btuh)})

    plf = curve(coil.model(), tables, row.get('efffplr'))
    if plf:
        coil.setPartLoadFractionCorrelationCurve(plf)

    # same AFUE/thermal/combustion triad
    thermal_eff, label = boiler_thermal_efficiency(row)
    if thermal_eff is None:
        return audit.warn('efficiency', 'furnace row has no efficiency value — not set', target=name)

    for stage in coil.stages():
        stage.setGasBurnerEfficiency(thermal_eff)
    coil.setName(f'{name} {ruby_round(w_to_kbtu_per_hr(capacity_w))}kBtu/hr {label}')
    return audit.decision('efficiency', 'staged gas heating efficiency applied to every stage', target=name,
                          inputs={'stages': len(coil.stages()),
                                  'top_stage_kw': ruby_round(capacity_w / 1000.0, 1)},
                          value=f'burner efficiency {ruby_round(thermal_eff, 3)} ({label}) on all '
                                f"{len(coil.stages())} stages, curve {row.get('efffplr')}",
                          article='NECB 2020 Table 5.2.12.1 (furnaces)', ruling='D-46')


def _apply_dx_heating(coil, tables, audit):
    """Legacy DX heating via heat_pumps_heating: HSPF or COPH47 -> heating COP (no fan)."""
    name = coil.nameString()
    capacity_w = (optional_f(coil.ratedTotalHeatingCapacity())
                  or optional_f(coil.autosizedRatedTotalHeatingCapacity()))
    if capacity_w is None:
        return audit.warn('efficiency', 'DX heating capacity unavailable (model not sized?) — not set',
                          target=name)

    cap_btuh = w_to_btu_per_hr(capacity_w)
    row = find_row(tables['heat_pumps_heating'],
                   {'cooling_type': 'AirCooled', 'subcategory': 'Single Package'}, cap_btuh)
    if row is None:
        return audit.warn('efficiency', 'no DX heating efficiency row found — not set', target=name,
                          inputs={'capacity_btu_hr': ruby_round(cap_btuh)})

    cop_label = dx_heating_cop(row, capacity_w)
    if cop_label is None:
        return audit.warn('efficiency', 'DX heating row has no efficiency value — not set', target=name)
    cop, label = cop_label

    coil.setRatedCOP(cop)
    for key, setter in (('heat_cap_ft', 'setTotalHeatingCapacityFunctionofTemperatureCurve'),
                        ('heat_cap_fflow', 'setTotalHeatingCapacityFunctionofFlowFractionCurve'),
                        ('heat_eir_ft', 'setEnergyInputRatioFunctionofTemperatureCurve'),
                        ('heat_eir_fflow', 'setEnergyInputRatioFunctionofFlowFractionCurve'),
                        ('heat_plf_fplr', 'setPartLoadFractionCorrelationCurve')):
        c = curve(coil.model(), tables, row.get(key))
        if c and hasattr(coil, setter):
            getattr(coil, setter)(c)
    coil.setName(f'{name} {ruby_round(w_to_kbtu_per_hr(capacity_w))}kBtu/hr {label}')
    return audit.decision('efficiency', 'DX heating efficiency applied', target=name,
                          inputs={'capacity_kw': ruby_round(capacity_w / 1000.0, 1)},
                          value=f'heating COP {ruby_round(cop, 2)} ({label})',
                          article='NECB 2020 Table 5.2.12.1 (heat pumps, heating)')


def _apply_gas_coil(coil, tables, audit):
    """Legacy coil_heating_gas_apply_efficiency_and_curves (NECB2011:855)."""
    name = coil.nameString()
    capacity_w = optional_f(coil.nominalCapacity()) or optional_f(coil.autosizedNominalCapacity())
    if capacity_w is None:
        return audit.warn('efficiency', 'gas coil capacity unavailable (model not sized?) — not set',
                          target=name)

    cap_btuh = max(w_to_btu_per_hr(capacity_w), 0.001)
    row = find_row(tables['furnaces'], {'fluid_type': 'Air', 'fuel_type': 'Gas'}, cap_btuh)
    if row is None:
        return audit.warn('efficiency', 'no furnace efficiency row found — not set', target=name,
                          inputs={'capacity_btu_hr': ruby_round(cap_btuh)})

    plf = curve(coil.model(), tables, row.get('efffplr'))
    if plf:
        coil.setPartLoadFractionCorrelationCurve(plf)

    # same AFUE/thermal/combustion triad
    thermal_eff, label = boiler_thermal_efficiency(row)
    if thermal_eff is None:
        return audit.warn('efficiency', 'furnace row has no efficiency value — not set', target=name)

    coil.setGasBurnerEfficiency(thermal_eff)
    coil.setName(f'{name} {ruby_round(w_to_kbtu_per_hr(capacity_w))}kBtu/hr {label}')
    return audit.decision('efficiency', 'gas heating coil efficiency applied', target=name,
                          inputs={'capacity_kw': ruby_round(capacity_w / 1000.0, 1)},
                          value=f'burner efficiency {ruby_round(thermal_eff, 3)} ({label}), '
                                f"curve {row.get('efffplr')}",
                          article='NECB 2020 Table 5.2.12.1 (furnaces)')


# ---------------- context helpers ----------------

def paired_with_dx_heating(coil):
    """Is this cooling coil part of a heat-pump system (paired DX heating on the same
    air loop / containing HVAC component)?"""
    loop = coil.airLoopHVAC()
    if loop is None or loop.empty():
        unitary = containing_unitary(coil)
        loop = unitary.airLoopHVAC() if unitary is not None else None
    if loop is not None and loop.is_initialized():
        return any(c.to_CoilHeatingDXSingleSpeed().is_initialized()
                   or c.to_CoilHeatingDXVariableSpeed().is_initialized()
                   or c.to_CoilHeatingDXMultiSpeed().is_initialized()
                   for c in _coils.supply_components(loop.get()))

    containing = coil.containingHVACComponent()
    if not containing.is_initialized():
        return False

    comp = containing.get()
    if comp.to_ZoneHVACPackagedTerminalHeatPump().is_initialized():
        return True
    try:
        return comp.to_AirLoopHVACUnitaryHeatPumpAirToAir().is_initialized()
    except Exception:
        return False


def containing_unitary(coil):
    """The AirLoopHVACUnitarySystem holding this coil, if any — a staged coil is
    never a direct supply component of its air loop."""
    containing = coil.containingHVACComponent()
    if not containing.is_initialized():
        return None

    unitary = containing.get().to_AirLoopHVACUnitarySystem()
    return unitary.get() if unitary.is_initialized() else None


def electric_or_no_heating(coil):
    """Legacy coil_dx_heating_type: 'Electric Resistance or None' vs 'All Other'."""
    loop = coil.airLoopHVAC()
    if loop is None or loop.empty():
        unitary = containing_unitary(coil)
        loop = unitary.airLoopHVAC() if unitary is not None else None
    if loop is not None and loop.is_initialized():
        comps = _coils.supply_components(loop.get())
        gas_or_hydronic = any(c.to_CoilHeatingGas().is_initialized()
                              or c.to_CoilHeatingWater().is_initialized()
                              or c.to_CoilHeatingGasMultiStage().is_initialized()
                              or c.to_CoilHeatingDXSingleSpeed().is_initialized()
                              or c.to_CoilHeatingDXVariableSpeed().is_initialized()
                              or c.to_CoilHeatingDXMultiSpeed().is_initialized()
                              for c in comps)
        return not gas_or_hydronic

    containing = coil.containingHVACComponent()
    if (containing.is_initialized()
            and containing.get().to_ZoneHVACPackagedTerminalAirConditioner().is_initialized()):
        heat = containing.get().to_ZoneHVACPackagedTerminalAirConditioner().get().heatingCoil()
        return not (heat.to_CoilHeatingGas().is_initialized()
                    or heat.to_CoilHeatingWater().is_initialized())
    return True


# ---------------- the HVAC-module facades ----------------

def apply_efficiencies(model, vintage='2020', audit=None, proposed=None):
    """Facade: apply NECB minimum efficiencies to a sized model. Pass the sized
    PROPOSED model via proposed= to enable the 8.4.4.14.(1)-(3) pump power
    transfer (combined W/(L/s) by loop type); without it the Table 8.4.4.14
    curves still apply and the skip is noted in the audit."""
    return apply(model, vintage=vintage, audit=audit, proposed=proposed)


def prepare_for_resizing(model, audit=None):
    """Facade: make an ALREADY-EFFICIENCY-APPLIED model safe to re-size.

    The efficiency pass hard-sets pump rated power (the 8.4.4.14 transfer and
    the 5.2.6.3 clamp) while pump FLOW stays autosized, and reconciles the
    head so the triple is physical at the flow sized so far. A later sizing
    run re-derives the flow: if it grows, the frozen power/head no longer fit
    it and EnergyPlus FATALS on "Calculated Pump Efficiency > 100%" during
    input checking — before the efficiency pass gets its chance to
    re-reconcile. Releasing the hard power back to autosize removes the
    inconsistency by construction (EnergyPlus then derives power from the
    flow and head it just sized), and the caller's next apply_efficiencies
    re-transfers it against the NEW flow.

    Call this before EVERY re-sizing run of a model that has already been
    through apply_efficiencies — the 8.4.1.2.(5) capacity iteration does.

    :return: int — pumps released"""
    audit = audit if audit is not None else NullAudit()
    pumps = ([p for p in model.getPumpVariableSpeeds() if not p.ratedPowerConsumption().empty()]
             + [p for p in model.getPumpConstantSpeeds() if not p.ratedPowerConsumption().empty()])
    for p in pumps:
        p.autosizeRatedPowerConsumption()
    if pumps:
        audit.info('efficiency', 'hard-set pump power released to autosize for the re-sizing run — the '
                                 'efficiency pass re-transfers it against the newly sized flow',
                   inputs={'pumps': len(pumps)}, article='8.4.4.14.(1)-(3)', ruling='D-11 D-27')
    return len(pumps)
