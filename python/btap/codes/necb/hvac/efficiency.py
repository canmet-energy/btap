"""Vintage efficiency application (port of btap-necb's hvac/efficiency.rb) — a
faithful, SDK-only port of the NECB subset of openstudio-standards'
model_apply_hvac_efficiency_standard, driven entirely by the vendored
each edition's own efficiencies.json (NECB Table 5.2.12.1 values + performance curves).

Covered components: hot-water boilers (incl. NECB primary/secondary staging),
electric chillers (incl. 2100 kW split + cooling-tower sizing rules), single-speed
DX cooling and heating coils, VRF outdoor units, gas heating coils, VAV fan power curves (8.4.4.17)
and hydronic pump power (8.4.4.14: Table curves + proposed W/(L/s) transfer when
a proposed model is supplied). Reference-model fans get their explicit 8.4.4.18
static pressure/efficiency values in the reference transform; motor-table
application remains host-side.

Requires a SIZED model (capacities read from hard or autosized values).
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime

import openstudio

from btap._compat import NullAudit, ruby_round, sorted_by_name
from btap.codes import resolve
from btap.codes.necb import code_id, rulesdata
from btap.modeling.hvac.components import coils as _coils
from btap.modeling.hvac.systems.plant_loops import (
    BOILER_PART_LOAD_CLASS_FEATURE,
    BOILER_PLANT_ROLE_FEATURE,
)


def data(edition):
    """This edition's minimum-efficiency tables — a shim over the family's ONE
    loader (:func:`btap.codes.necb.rulesdata.load`), which owns the cache."""
    return rulesdata.load("hvac_efficiencies", code_id(edition))


def apply(model, code='necb2020', audit=None, proposed=None):
    """Apply NECB minimum-performance values + curves to every supported component.

    :param model: sized openstudio.model.Model
    :param code: the code id, e.g. 'necb2020'
    :param audit: AuditLog or None
    :param proposed: SIZED proposed model, enabling the 8.4.4.14.(1)-(3) pump power transfer
    :return: True
    """
    return _apply(model, resolve(code), audit=audit, proposed=proposed)


def _apply(model, ruleset, audit=None, proposed=None):
    """The minimum-performance pass against ONE resolved edition — the
    efficiency tables, the plant staging rules and every article number under
    them come from this same :class:`btap.codes.Ruleset` (Stage 6)."""
    audit = audit if audit is not None else NullAudit()
    tables = ruleset.rules("hvac_efficiencies")
    # Boiler/chiller staging thresholds (8.4.4.9.(6)/8.4.4.10.(6)) live in the
    # reference ruleset (heating_plant/cooling_plant), not the efficiencies
    # table — but in the SAME edition's snapshot, like everything else.
    plant_rules = ruleset.rules("hvac")
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
    totals = _apply_staging(model, plant_rules, ruleset, audit)
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
    for unit in sorted_by_name(model.getAirConditionerVariableRefrigerantFlows()):
        _apply_vrf(unit, tables, ruleset, audit)
    for f in sorted_by_name(model.getFanVariableVolumes()):
        _apply_fan_power_curve(f, ruleset, audit)
    _apply_pump_rules(model, ruleset, plant_rules.get('hydronic_pumps'), audit,
                      proposed=proposed)
    _align_heat_pump_heating_capacity(model, audit, ruleset)
    audit.info('efficiency', 'NECB efficiency pass complete',
               inputs={'code': ruleset.id, 'edition': ruleset.edition,
                       'boilers': len(model.getBoilerHotWaters()),
                       'chillers': len(model.getChillerElectricEIRs()),
                       'dx_cooling': len(model.getCoilCoolingDXSingleSpeeds()),
                       'dx_cooling_staged': len(model.getCoilCoolingDXMultiSpeeds()),
                       'dx_heating': len(model.getCoilHeatingDXSingleSpeeds()),
                       'dx_heating_staged': len(model.getCoilHeatingDXMultiSpeeds()),
                       'gas_coils': len(model.getCoilHeatingGass()),
                       'gas_coils_staged': len(model.getCoilHeatingGasMultiStages())})
    return True


def _vrf_row(rows, capacity_w):
    capacity_kw = capacity_w / 1000.0
    return next((row for row in rows
                 if capacity_kw >= row['minimum_capacity_kw']
                 and (row['maximum_capacity_kw'] is None
                      or capacity_kw < row['maximum_capacity_kw'])), None)


def _vrf_class(unit):
    """The Table-I equipment class, from MODEL EVIDENCE only.

    None means the model carries no evidence either way: the classic VRF
    outdoor unit has no heating/cooling-only field of its own, so a unit
    serving NO terminals says nothing about its class. That is not a
    hypothetical — the reference transform strips the terminals when it
    replaces a proposed VRF system, leaving the outdoor unit behind. Reading
    that silence as 'air conditioner' would apply the cooling-only rows to a
    heat pump AND drop its heating minimum without a word, so the caller
    warns instead (the same 'never guess' rule the condenser type follows).
    """
    terminals = unit.terminals()
    if not terminals:
        return None
    for terminal in terminals:
        heating = terminal.heatingCoil()
        if (heating.is_initialized()
                and heating.get().to_CoilHeatingDXVariableRefrigerantFlow().is_initialized()):
            return 'heat_pump'
    return 'air_conditioner'


def _apply_vrf(unit, tables, ruleset, audit):
    """Apply the air-cooled AC or air-source HP rows of Table 5.2.12.1.-I.

    OpenStudio's classic VRF object distinguishes only AirCooled, WaterCooled,
    and EvaporativelyCooled condensers. It cannot identify the table's water,
    groundwater, and ground-source classes, so those paths warn instead of
    guessing. An attached VRF DX heating coil selects the heat-pump class;
    cooling-only terminals select the air-conditioner class; an outdoor unit
    serving no terminals at all is INDETERMINATE and warns. Code minimums are
    assigned exactly, consistently with the other equipment appliers.
    """
    article = f'NECB {ruleset.edition} Table 5.2.12.1.-I'
    if unit.condenserType() != 'AirCooled':
        return audit.warn(
            'efficiency',
            'VRF source type cannot be distinguished as water, groundwater, or ground source '
            'from the OpenStudio condenser type — minimum efficiency not set',
            target=unit.nameString(), inputs={'condenser_type': unit.condenserType()},
            article=article)

    equipment_class = _vrf_class(unit)
    if equipment_class is None:
        return audit.warn(
            'efficiency',
            'VRF outdoor unit serves no terminals — Table-I equipment class indeterminate, '
            'minimums not set',
            target=unit.nameString(), inputs={'terminals': 0},
            article=article, ruling='D-85')

    cooling_w = (optional_f(unit.grossRatedTotalCoolingCapacity())
                 or optional_f(unit.autosizedGrossRatedTotalCoolingCapacity()))
    heating_w = (optional_f(unit.grossRatedHeatingCapacity())
                 or optional_f(unit.autosizedGrossRatedHeatingCapacity()))
    heat_pump = equipment_class == 'heat_pump'
    rows = tables['vrf_air_source_heat_pumps' if heat_pump else 'vrf_air_conditioners']
    applied = []

    cooling_row = _vrf_row(rows, cooling_w) if cooling_w is not None else None
    if cooling_row is None:
        audit.warn('efficiency', 'VRF cooling capacity unavailable (model not sized?) — '
                                 'Table-I cooling minimum not set',
                   target=unit.nameString(), inputs={'equipment_class': equipment_class},
                   article=article, ruling='D-85')
    else:
        if cooling_row.get('minimum_seer') is not None:
            cooling_cop = seer_to_cop_no_fan(cooling_row['minimum_seer'])
            cooling_label = f"SEER {cooling_row['minimum_seer']}"
        else:
            cooling_cop = eer_to_cop_no_fan(cooling_row['minimum_eer'], cooling_w)
            cooling_label = f"EER {cooling_row['minimum_eer']}"
        unit.setGrossRatedCoolingCOP(cooling_cop)
        applied.append(f'cooling {cooling_label} (COP {ruby_round(cooling_cop, 2)})')

    if heat_pump:
        heating_row = _vrf_row(rows, heating_w) if heating_w is not None else None
        if heating_row is None:
            audit.warn('efficiency', 'VRF heating capacity unavailable (model not sized?) — '
                                     'Table-I heating minimum not set',
                       target=unit.nameString(), inputs={'equipment_class': equipment_class},
                       article=article, ruling='D-85')
        else:
            if heating_row.get('minimum_hspf') is not None:
                heating_cop = hspf_to_cop_no_fan(heating_row['minimum_hspf'])
                heating_label = f"HSPF {heating_row['minimum_hspf']}"
            else:
                heating_cop = heating_row['minimum_heating_cop']
                heating_label = f'COP {heating_cop}'
            unit.setRatedHeatingCOP(heating_cop)
            applied.append(f'heating {heating_label}')

    if not applied:
        return None
    return audit.decision(
        'efficiency', 'VRF minimum efficiency applied', target=unit.nameString(),
        inputs={'equipment_class': equipment_class,
                'cooling_capacity_kw': (ruby_round(cooling_w / 1000.0, 1)
                                        if cooling_w is not None else None),
                'heating_capacity_kw': (ruby_round(heating_w / 1000.0, 1)
                                        if heating_w is not None else None)},
        value='; '.join(applied), article=article, ruling='D-85')


# ---------------- 8.4.4.9.(7) / 8.4.4.10.(8) staged heating and cooling ----------------

# The EnergyPlus structural ceiling: both Coil:Cooling:DX:MultiSpeed and
# Coil:Heating:Gas:MultiStage refuse a fifth stage (probe-verified on the
# SDK — addStage returns false), so a system needing more equal stages
# than this is clamped, loudly (D-47).
MAX_STAGES = 4


def apply_staging(model, rules, code, audit):
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
    :param code: the code id ('necb2020' or 'necb2025')
    :param audit: AuditLog or None
    :return: dict {coil handle -> the TOTAL capacity measured before re-staging}.
        Growing a coil appends a stage EnergyPlus has never sized, so the new top
        stage reads back None and shrinking one leaves a stale partial value behind
        — the appliers must bin on the measurement taken here, not on a re-read.
    """
    return _apply_staging(model, rules, resolve(code), audit)


def _apply_staging(model, rules, ruleset, audit):
    audit = audit if audit is not None else NullAudit()
    prefix = ruleset.article('reference_subsection')
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


def _apply_fan_power_curve(fan, ruleset, audit):
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
    prefix = ruleset.article('reference_subsection')
    audit.decision('efficiency', f'VAV fan power curve set ({row_name})',
                   target=fan.nameString(),
                   inputs={'rated_kw': ruby_round(power_kw, 2),
                           'coefficients': [row['a'], row['b'], row['c']],
                           'minimum_flow_fraction': row['d']},
                   value=f"below-D floor (E={row['e']}) approximated by the minimum-flow clamp",
                   article=f'{prefix}.17.(2)-(5); Table {prefix}.17.')


def _apply_pump_rules(model, ruleset, rule, audit, proposed=None):
    """8.4.4.14 (2025: 8.4.5.14) hydronic pump power. Sentence (5) directs
    variable-flow pumps to be modeled as a pump riding its curve, so
    reference PumpVariableSpeeds get the Table's riding-curve row (identical
    coefficients to the 8.4.4.17 airfoil fan row — same DOE-2 lineage; the
    VSD row is vendored for completeness). Coefficients come from the
    ruleset's hydronic_pumps.curves (Table 8.4.4.14., both editions
    identical). E+ mapping: A/B/C -> part-load performance coefficients 1-3
    (4th = 0); the below-D floor (P = E x Prated) is approximated by the
    minimum-flow clamp at D x rated flow — the polynomial at D equals E
    within the table's rounding (riding curve 0.691 vs 0.68, VSD 0.043 vs
    0.04)."""
    if rule is None:
        return

    prefix = ruleset.article('reference_subsection')
    if proposed is None:
        audit.info('efficiency', f'no proposed model supplied — {prefix}.14.(1)-(3) pump power transfer '
                                 f'skipped (Table {prefix}.14. curves still applied)', ruling='D-11 D-93')
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
        # _applicable_pumps, not a supply-side scan: a primary-secondary
        # arrangement puts the secondary pump on the DEMAND side, and it needs
        # the (4)-(5) curve exactly as much as the primary does (Sol, PR #53).
        for pump in _applicable_pumps(loop_):
            if pump.iddObjectType().valueName() == 'OS_Pump_VariableSpeed':
                row = rule['curves']['riding pump curve']
                pump.setCoefficient1ofthePartLoadPerformanceCurve(row['a'])
                pump.setCoefficient2ofthePartLoadPerformanceCurve(row['b'])
                pump.setCoefficient3ofthePartLoadPerformanceCurve(row['c'])
                pump.setCoefficient4ofthePartLoadPerformanceCurve(0.0)
                flow = _pump_flow(pump)
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
        if proposed is not None:
            _transfer_by_correspondence(loop_, proposed, prefix, audit)
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
    # 5.2.6.3.(1) caps the combined power of ALL the pumps in the hydronic
    # system, and a primary-secondary arrangement keeps its secondary pump on
    # the demand side. Scanning only the supply side reported a 10,100 W loop
    # as 100 W and certified it "within the maximum" against a 450 W cap, while
    # the demand pump kept every watt (Sol, PR #53). One collector, so a pump
    # cannot be visible to the transfer and invisible to the cap.
    pumps = _applicable_pumps(loop_)
    # D-92: derive each pump's power the way E+ will — from a hard-set value, a
    # PowerPerFlow intensity, or the flow/head/coefficient triple — rather than
    # reading a sizing SQL the pass has just invalidated.
    flows = [_pump_flow(p) for p in pumps]
    sources = [_pump_power_source(p, f) for p, f in zip(pumps, flows)]
    powers = [w for _, w in sources]
    # A pump whose flow is readable but whose power is not states something no
    # pump can draw (a negative or zero head, a negative rated power). That is a
    # broken input, not an unsized model, and it must SHOUT rather than be
    # filed as a quiet "not evaluable": the loop is left unclamped either way,
    # so a reader has to know the cap was never actually applied here.
    malformed = [p.nameString() for p, f, w in zip(pumps, flows, powers)
                 if w is None and f is not None and f > 0]
    if malformed:
        audit.warn('efficiency', '5.2.6.3 pump-power cap NOT APPLIED — '
                                 f'{", ".join(malformed)} state a power no pump can draw (non-positive '
                                 'or non-finite), so this loop\'s combined power cannot be measured and '
                                 'a real over-cap pump on it would go unclamped',
                   target=loop_.nameString(), article='5.2.6.3.(1)', ruling='D-38')
        return
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
    for pump, (source, _) in zip(pumps, sources):
        # D-92: clamp through whichever field E+ actually reads, scaling head
        # with it so the implied efficiency is unchanged — the gem's mechanism
        # and the one A-8.4.x.14.(2) uses, generalised to the pumps this pass
        # never transferred.
        _scale_pump_power(pump, source, factor)
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
    wta = _water_to_air_coils(loop_)
    if wta:
        kw = 0.0
        for coil in wta:
            # Cooling coils carry the loop's sizing basis; the heating halves of
            # the same units add nothing to it. Both speed controls spell the
            # capacity getter the same way.
            if not hasattr(coil, 'ratedTotalCoolingCapacity'):
                continue

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


# D-92 replaced the MECHANISM and D-93 the value source. What follows describes
# the mechanism; the value now comes from the correspondence and the sentence
# that governs it, never from a whole-building blend.
#
# (historical) D-92 replaced the MECHANISM, not yet the value source. It was
# still D-11's: the proposed loop-type's pumps' combined peak power intensity,
# W/(L/s). What changed is how it reaches the model — the reference pump's
# head, shaft coefficient and motor efficiency are stated and its power is left
# autosized, instead of its power being hard-set and the head bent afterwards
# when the two disagreed. On a single-pump correspondence that collapses
# algebraically to the proposed pump's own head and efficiency, which is what
# sentence (1) asks for; DF-11 carries the explicit (1)/(2)/(3) branch.
#
# E+ derives pump power from the flow/head/coefficient triple under
# PowerPerFlowPerPressure: P = V x H x k / motor_eff, where k is the design
# shaft power per unit flow per unit head (1 / pump efficiency). D-92 writes
# those three fields and leaves power autosized, so the pump efficiency E+
# computes IS the one we stated — it cannot exceed the motor efficiency, and
# the "Calculated Pump Efficiency > 100%" fatal is unreachable by construction.
POWER_PER_FLOW_PER_PRESSURE = 'PowerPerFlowPerPressure'
# The other E+ sizing method: P = V x DesignElectricPowerPerUnitFlowRate, with
# head absent from the equation entirely. A cap that moves head does nothing to
# a pump in this mode, which is why the clamp branches on the method.
POWER_PER_FLOW = 'PowerPerFlow'
# E+'s own defaults, and the physical fallback when the proposed pump's triple
# implies an efficiency no pump can have. The derived power does NOT depend on
# how the total splits between motor and impeller — P = V x H x k / motor_eff
# with H = I x 1000 x motor_eff x pump_eff cancels both — so a non-physical
# proposed split can be replaced by a physical one without moving a watt.
DEFAULT_MOTOR_EFFICIENCY = 0.9
DEFAULT_PUMP_EFFICIENCY = 0.78


def _state_pump_characteristics(pump, w_per_l_s, motor_eff, pump_eff):
    """D-92: state the reference pump as head + shaft coefficient + motor
    efficiency and leave its power AUTOSIZED, so EnergyPlus derives the power
    the Article asks for instead of being handed a number that may contradict
    the head it was given.

    The head that reproduces an intensity I (W/(L/s)) is I x 1000 x motor_eff x
    pump_eff, since P = V x H x k / motor_eff with k = 1 / pump_eff. Stating the
    efficiencies rather than solving for them is what makes the E+ pump
    efficiency equal the one we declared.

    :return: the head written, in Pa"""
    head_pa = w_per_l_s * 1000.0 * motor_eff * pump_eff
    pump.setDesignPowerSizingMethod(POWER_PER_FLOW_PER_PRESSURE)
    pump.setDesignShaftPowerPerUnitFlowRatePerUnitHead(1.0 / pump_eff)
    pump.setMotorEfficiency(motor_eff)
    pump.setRatedPumpHead(head_pa)
    pump.autosizeRatedPowerConsumption()
    return head_pa


def _pump_power_source(pump, flow):
    """How EnergyPlus will actually arrive at this pump's power, and what that
    power is — ``(source, watts)``, or ``(source, None)`` when it cannot be read.

    D-92 states the pumps it transfers as PowerPerFlowPerPressure with the power
    autosized, but the pass reaches pumps it never transfers: the 5.2.6.3 cap
    runs with or without a proposed model, and a caller's model may hard-set
    power or choose PowerPerFlow. For those, head does NOT enter E+'s sizing
    equation, so a cap that only scales head reports a clamp it did not apply
    (Sol, PR #50). Each source must be clamped on its own terms."""
    if not pump.isRatedPowerConsumptionAutosized():
        return 'hard', _usable_watts(optional_f(pump.ratedPowerConsumption()))

    if flow is None or flow <= 0:
        return 'autosized', None

    if pump.designPowerSizingMethod() == POWER_PER_FLOW:
        return 'per_flow', _usable_watts(flow * pump.designElectricPowerPerUnitFlowRate())

    motor_eff = pump.motorEfficiency()
    if not motor_eff:
        return 'per_flow_per_pressure', None

    return ('per_flow_per_pressure',
            _usable_watts(flow * pump.ratedPumpHead()
                          * pump.designShaftPowerPerUnitFlowRatePerUnitHead() / motor_eff))


def _usable_watts(watts):
    """A pump power that can be reasoned about, else ``None``.

    Input hardening (Sol, PR #50). The SDK refuses a motor efficiency outside
    (0, 1], a non-positive shaft coefficient, and a non-finite head — but it
    ACCEPTS a negative or zero rated head and a negative rated power. Those
    reach the 5.2.6.3 cap as a negative contribution to the loop's combined
    power, and because the clamp only fires when the combined power EXCEEDS the
    cap, one malformed pump can drag the sum under it: a genuine 5,110 W pump
    beside a -5,110 W one sums to zero, the loop is certified "within the Table
    5.2.6.3 maximum", and the real pump escapes the clamp. A compliance check
    that can be made to pass a violating loop is worse than one that refuses to
    answer, so an unusable power is reported as unreadable and the caller says
    so out loud."""
    if watts is None or not math.isfinite(watts) or watts <= 0.0:
        return None

    return watts


def _pump_power_from_triple(pump, flow):
    """The power E+ will derive for a PowerPerFlowPerPressure pump: V x H x k /
    motor_eff. Computed, never read back from a sizing SQL — after the pass
    writes a new head the stored autosized value is stale until the next sizing
    run, and the 5.2.6.3 cap has to compare against what the model now says."""
    return _pump_power_source(pump, flow)[1]


def _scale_pump_power(pump, source, factor):
    """Scale a pump's power by ``factor`` through whichever field E+ actually
    reads, and scale its head by the same factor so the IMPLIED EFFICIENCY is
    unchanged.

    Scaling head alongside is not decoration. Cutting a hard-set power while
    leaving the head raises V x H / P — the efficiency E+ checks — and a big
    enough cut pushes it past the motor efficiency into the "Calculated Pump
    Efficiency > 100%" fatal. That is why the pre-D-92 code had to reconcile the
    head after clamping. Moving both together preserves the ratio instead, so
    there is nothing to reconcile."""
    pump.setRatedPumpHead(pump.ratedPumpHead() * factor)
    if source == 'hard':
        power = optional_f(pump.ratedPowerConsumption())
        if power is not None:
            pump.setRatedPowerConsumption(power * factor)
    elif source == 'per_flow':
        pump.setDesignElectricPowerPerUnitFlowRate(pump.designElectricPowerPerUnitFlowRate() * factor)
    # 'per_flow_per_pressure': power is autosized FROM the head, so the head
    # scaling above already carried it.


#: OpenStudio's own defaults. A field still holding one of these was never
#: stated by a modeller, which is what 8.4.x.14.(3)'s "not known" means in a
#: model (Sol, DF-11 increment B). Blank-ness cannot be used instead: the
#: PumpConstantSpeed constructor WRITES head and motor efficiency as explicit
#: fields, so isRatedPumpHeadDefaulted() is False on a pump nobody touched,
#: and the shaft coefficient has no isDefaulted accessor at all.
SDK_DEFAULT_HEAD_PA = 179352.0
SDK_DEFAULT_SHAFT_COEFFICIENT = 1.282051282
#: The hydronic-pump article in the numbering the source literals use; the
#: active edition's own number comes from the ruleset, as everywhere else.
LITERAL_PUMP_ARTICLE = '8.4.4.14'


#: Water-to-air heat-pump coils, constant-speed and variable-speed alike. ONE
#: registry, because three places used to carry their own partial list: the
#: served-zone traversal knew the variable-speed ones, while _loop_role and
#: _pump_cap_basis knew only the equation-fit pair — so a variable-speed WSHP
#: loop classified as plain hot water and took the Heating cap row instead of
#: the water-source one (Sol, PR #53).
WATER_TO_AIR_HEAT_PUMP_COILS = (
    'to_CoilCoolingWaterToAirHeatPumpEquationFit',
    'to_CoilHeatingWaterToAirHeatPumpEquationFit',
    'to_CoilCoolingWaterToAirHeatPumpVariableSpeedEquationFit',
    'to_CoilHeatingWaterToAirHeatPumpVariableSpeedEquationFit',
)


#: Every water coil that delivers a hydronic loop's output to a thermal block.
#: COMPOSED from the registry above, not a second copy of it: the water-to-air
#: entries must be the same list the role and cap classifications use, or the
#: traversal silently stops seeing a coil type the others recognise.
ZONE_SERVING_WATER_COILS = (
    'to_CoilHeatingWater', 'to_CoilCoolingWater',
    # A hot-water baseboard carries CoilHeatingWaterBaseboard, NOT
    # CoilHeatingWater — omitting it made a baseboard-only loop resolve to no
    # served zones, on the commonest reference heating terminal there is.
    'to_CoilHeatingWaterBaseboard',
    'to_CoilHeatingWaterBaseboardRadiant',
    'to_CoilCoolingWaterPanelRadiant',
    'to_CoilHeatingLowTempRadiantVarFlow',
    'to_CoilCoolingLowTempRadiantVarFlow',
    'to_CoilHeatingLowTempRadiantConstFlow',
    'to_CoilCoolingLowTempRadiantConstFlow',
) + WATER_TO_AIR_HEAT_PUMP_COILS


def _water_to_air_coils(loop_):
    """The loop's water-to-air heat-pump coils, whatever their speed control."""
    found = []
    for comp in loop_.demandComponents():
        for caster in WATER_TO_AIR_HEAT_PUMP_COILS:
            candidate = getattr(comp, caster, None)
            if candidate is not None and candidate().is_initialized():
                found.append(candidate().get())
                break
    return found


def _loop_role(loop_):
    """What this hydronic loop is FOR — finer than Sizing:Plant's loop type.

    8.4.x.14 corresponds pumps between buildings, and a correspondence is only
    meaningful between loops doing the same job. Loop type alone is too coarse:
    a water-source heat-pump loop carries a boiler and reports 'Heating', so it
    would match a reference baseboard hot-water loop and transfer characteristics
    between two quite different systems. _pump_cap_basis already separates that
    case for the Part 5 cap; this uses the same test.
    """
    if _swh_loop(loop_):
        return 'service_water'

    if _water_to_air_coils(loop_):
        return 'heat_pump_source'

    return {'Heating': 'hot_water', 'Cooling': 'chilled_water',
            'Condenser': 'condenser'}.get(loop_.sizingPlant().loopType())


def _pump_flow(pump):
    """A pump's design flow — stated, else the value sizing produced.

    One definition, because this expression appeared inline at six call sites
    and every defect in this Article's implementation so far has come from two
    places computing the same thing independently.
    """
    return optional_f(pump.ratedFlowRate()) or optional_f(pump.autosizedRatedFlowRate())


def _coil_served_zones(coil):
    """The thermal blocks a water coil conditions, by name.

    THREE accessors, not two. A coil sitting directly in zone equipment answers
    `containingZoneHVACComponent`, and one on an air loop's main branch answers
    `airLoopHVAC` — but a coil held inside an `AirLoopHVACUnitarySystem` or an
    `AirTerminalSingleDuctVAVReheat` answers NEITHER: only
    `containingHVACComponent` is set. Checking the first two alone made a
    hot-water loop serving VAV reheat terminals resolve to no zones at all
    (Fable, PR #53).

    That is worse than a loud decline where the proposed has one loop: with two
    loops — reheat on one, baseboards on another — the reference matched the
    baseboard loop alone and reported a confident "one-to-one" for what is
    really an N:1 consolidation. A silently wrong sentence, on an ordinary
    rooftop-with-hydronic-reheat building.
    """
    zones = set()
    container = coil.containingZoneHVACComponent()
    if container.is_initialized() and container.get().thermalZone().is_initialized():
        zones.add(container.get().thermalZone().get().nameString())

    air_loop = coil.airLoopHVAC()
    if air_loop.is_initialized():
        zones |= {z.nameString() for z in air_loop.get().thermalZones()}

    held_by = coil.containingHVACComponent()
    if held_by.is_initialized():
        holder = held_by.get()
        holder_loop = holder.airLoopHVAC()
        if holder_loop.is_initialized():
            zones |= {z.nameString() for z in holder_loop.get().thermalZones()}
        terminal_zone = getattr(holder, 'thermalZone', None)
        if terminal_zone is not None and terminal_zone().is_initialized():
            zones.add(terminal_zone().get().nameString())
    return zones


def _served_zone_names(loop_, _seen=None):
    """The thermal zones this loop ultimately conditions, by NAME.

    Names, not handles: the reference is `model.clone()`d from the proposed and
    clone does not preserve handles, so a handle-keyed map cannot span the two
    buildings. Zone names survive the clone and the teardown.

    A condenser loop reaches zones only through the chillers it rejects heat
    for, and a loop behind a heat exchanger only through the loop it serves, so
    both recurse (guarded against a loop pair that references itself).
    """
    seen = _seen if _seen is not None else set()
    if loop_.handle() in seen:
        return set()

    seen.add(loop_.handle())
    zones: set[str] = set()
    for comp in loop_.demandComponents():
        coil = None
        # CoilHeatingWaterBaseboard is a DIFFERENT class from CoilHeatingWater,
        # and it is what a hot-water baseboard carries — the commonest reference
        # heating terminal there is. Omitting it made a baseboard-only loop
        # resolve to no served zones, so the correspondence declined on exactly
        # the systems this Article most often applies to.
        # Composed from WATER_TO_AIR_HEAT_PUMP_COILS rather than restating it:
        # three places carrying their own copy is exactly how a variable-speed
        # WSHP loop came to classify as plain hot water. A registry that one
        # caller still duplicates is not shared, it is only currently in
        # agreement.
        for caster in ZONE_SERVING_WATER_COILS:
            candidate = getattr(comp, caster, None)
            if candidate is not None and candidate().is_initialized():
                coil = candidate().get()
                break
        if coil is not None:
            zones |= _coil_served_zones(coil)
            continue

        # Equipment that passes the load on to another loop rather than a zone.
        for caster in ('to_ChillerElectricEIR', 'to_HeatExchangerFluidToFluid',
                       'to_HeatPumpPlantLoopEIRHeating', 'to_HeatPumpPlantLoopEIRCooling'):
            candidate = getattr(comp, caster, None)
            if candidate is None or not candidate().is_initialized():
                continue

            served = candidate().get().plantLoop()
            if served.is_initialized():
                zones |= _served_zone_names(served.get(), seen)
    return zones


def _distribution_flow(loop_):
    """The design flow delivered through this loop's load-serving circuit, in
    m3/s — counted ONCE per fluid stream, which is NOT the sum of its pumps'
    flows (Sol, DF-11 increment B).

    Two pumps in series, or a primary-secondary arrangement, circulate the same
    water; summing their rated flows counts it twice and halves the resulting
    W/(L/s). On the Code's own Appendix example that understates the reference
    pump by a third. The loop's own maximum flow rate is that stream, counted
    once, whichever sizing option produced it.

    :return: (flow m3/s, source) or (None, reason) — never a silent fallback
    """
    hard = optional_f(loop_.maximumLoopFlowRate())
    if hard is not None and hard > 0:
        return hard, 'input'

    sized = optional_f(loop_.autosizedMaximumLoopFlowRate())
    if sized is not None and sized > 0:
        return sized, 'autosized'

    return None, 'the loop has no design maximum flow rate (not sized)'


def _pump_characteristics_known(pump):
    """Does the proposed state this pump's head AND hydraulic efficiency?

    8.4.x.14.(3) applies where the head OR the efficiency is not known, so (1)
    requires BOTH — Sol corrected us on that: "any modeller-set field" was too
    weak a test. Neither can be read from blank-ness (see the constants above),
    so "stated" means "not holding the SDK's own default".

    Efficiency is known when the model pins the flow/head/power triple — a
    hard-set rated power against a stated head — or when the shaft coefficient
    itself was moved off its default.

    :return: (head_known, efficiency_known)
    """
    head = pump.ratedPumpHead()
    head_known = bool(head) and head > 0 and abs(head - SDK_DEFAULT_HEAD_PA) > 1e-6
    coefficient = pump.designShaftPowerPerUnitFlowRatePerUnitHead()
    stated = (
        abs(coefficient - SDK_DEFAULT_SHAFT_COEFFICIENT) > 1e-9
        or (head_known and not pump.isRatedPowerConsumptionAutosized()
            and optional_f(pump.ratedPowerConsumption()) is not None)
    )
    # "defaulted, missing OR INVALID" is the test, and validity is decided by
    # the same resolver that will later TRANSFER the value — otherwise a pump
    # can be classified known on one field and transferred from another. A
    # negative power and a shaft coefficient of 0.5 (200 %) both fail here.
    return head_known, bool(stated and _hydraulic_efficiency(pump) is not None)


def _corresponding_loop(reference_loop, proposed):
    """The proposed hydronic system this reference loop corresponds to, or a
    reason it has none (Sol, DF-11 increment B).

    Correspondence is by ROLE plus SERVED THERMAL BLOCKS, not by loop type —
    D-11 matched on 'Heating'/'Cooling'/'Condenser' across the whole building,
    which blends every heating pump in a mixed building into one intensity and
    is weakest exactly where a real pump-to-pump correspondence exists.

    Increment B is scoped to an UNAMBIGUOUS one-to-one match. Several proposed
    systems consolidated onto one reference loop is a real case (our own
    builders reuse a single hot-water loop) but the Code does not define
    correspondence across independently consolidated systems; that is a
    separate adjudication, so it declines here rather than guessing.

    :return: (proposed loop, 'one-to-one') or (None, reason)
    """
    role = _loop_role(reference_loop)
    if role in (None, 'service_water'):
        return None, f'{role or "unclassified"} loop is outside {LITERAL_PUMP_ARTICLE}'

    reference_zones = _served_zone_names(reference_loop)
    if not reference_zones:
        return None, 'the reference loop serves no thermal block, so no correspondence can be drawn'

    candidates = [loop_ for loop_ in sorted_by_name(proposed.getPlantLoops())
                  if _loop_role(loop_) == role]
    if not candidates:
        return None, f'the proposed building has no {role} loop'

    exact = [loop_ for loop_ in candidates if _served_zone_names(loop_) == reference_zones]
    if len(exact) == 1:
        return exact[0], 'one-to-one'
    if len(exact) > 1:
        return None, (f'{len(exact)} proposed {role} loops serve exactly the same thermal blocks — '
                      'the correspondence is ambiguous')

    overlapping = [loop_ for loop_ in candidates
                   if _served_zone_names(loop_) & reference_zones]
    if len(overlapping) > 1:
        return None, (f'{len(overlapping)} proposed {role} loops are consolidated onto this one — '
                      'cross-system correspondence is not defined by the Code and is adjudicated '
                      'separately')
    if len(overlapping) == 1:
        return None, (f'the proposed {role} loop also serves thermal blocks this reference loop does '
                      'not — a partial overlap is not a correspondence')
    return None, f'no proposed {role} loop serves these thermal blocks'


def _applicable_pumps(loop_):
    """The loop's own circulating pumps, BOTH sides, in name order.

    A primary-secondary arrangement puts the primary pump on the supply side
    and the secondary on the DEMAND side, so scanning only the supply side
    finds one pump where the system has two (Sol, PR #53). That mistakes (2)
    for (1), and drops the secondary's power out of (3) entirely — on exactly
    the topology the Appendix example describes.
    """
    pumps, seen = [], set()
    for comp in sorted_by_name(list(loop_.supplyComponents()) + list(loop_.demandComponents())):
        pump = None
        if comp.to_PumpVariableSpeed().is_initialized():
            pump = comp.to_PumpVariableSpeed().get()
        elif comp.to_PumpConstantSpeed().is_initialized():
            pump = comp.to_PumpConstantSpeed().get()
        if pump is not None and pump.handle() not in seen:
            seen.add(pump.handle())
            pumps.append(pump)
    return pumps


def _hydraulic_efficiency(pump):
    """The pump efficiency EnergyPlus will actually use, or None if it is not
    readable or not one a pump can have.

    One resolver for every caller, because the field that DEFINES the
    efficiency depends on how power is stated, and reading a different field
    than the one that defines it silently transfers the wrong number (Sol,
    PR #53: a proposed triple implying 50 % was transferred as the untouched
    coefficient's 78 %, turning 888.9 W of proposed power into 569.8 W).

    - a hard rated power pins the triple: eta_p = Q x H / (P x motor_eff)
    - PowerPerFlow states electrical per flow: eta_p = H / (intensity x motor_eff)
    - otherwise the shaft coefficient IS the statement: eta_p = 1 / k
    """
    motor_eff = pump.motorEfficiency()
    if not motor_eff or not 0.0 < motor_eff <= 1.0:
        return None

    head = pump.ratedPumpHead()
    flow = _pump_flow(pump)
    efficiency = None
    if not pump.isRatedPowerConsumptionAutosized():
        power = optional_f(pump.ratedPowerConsumption())
        if power is not None and power > 0 and head and flow:
            efficiency = (flow * head) / (power * motor_eff)
    elif pump.designPowerSizingMethod() == POWER_PER_FLOW:
        intensity = pump.designElectricPowerPerUnitFlowRate()
        if intensity and head:
            efficiency = head / (intensity * motor_eff)
    else:
        coefficient = pump.designShaftPowerPerUnitFlowRatePerUnitHead()
        efficiency = (1.0 / coefficient) if coefficient else None

    return efficiency if (efficiency and 0.0 < efficiency <= 1.0) else None


def _governing_sentence(pumps):
    """Which of 8.4.x.14 (1), (2) or (3) governs this correspondence group.

    Sol's precedence (DF-11 increment B), which the Code does not state and
    which is therefore itself an adjudication: if ANY applicable pump's head or
    hydraulic efficiency is unknown the whole group takes (3), because (2)
    cannot preserve a combined shaft power it is unable to compute and (3) is
    the Article's explicit missing-data rule. Otherwise more than one pump in
    the system takes (2), and a single known pump takes (1).

    This replaces D-92's partial treatment, where an unreadable pump still
    contributed to a (2)-style total while being dropped only from the
    efficiency average. The group is now all one sentence or the other.
    """
    if not pumps:
        return None

    if any(not all(_pump_characteristics_known(pump)) for pump in pumps):
        return '3'

    return '2' if len(pumps) > 1 else '1'


def _transfer_by_correspondence(reference_loop, proposed, prefix, audit):
    """Apply 8.4.x.14 (1), (2) or (3) to one reference loop's pumps (D-93).

    The value source follows the correspondence, not the loop type: find the
    proposed system this loop corresponds to, decide which sentence its pumps
    put us under, and apply that sentence's own formula. Where no unambiguous
    correspondence exists the transfer DECLINES and says so — the reference
    pump keeps the builder's default, which the Part 5 cap still binds. D-11
    inferred a whole-building intensity instead, which is a number no sentence
    of the Article asks for.
    """
    reference_pumps = _applicable_pumps(reference_loop)
    if not reference_pumps:
        return

    match, reason = _corresponding_loop(reference_loop, proposed)
    if match is None:
        if _loop_role(reference_loop) == 'service_water':
            return  # D-27 already said so, at the top of the pass

        return audit.warn('efficiency', f'{reference_loop.nameString()}: {prefix}.14.(1)-(3) NOT '
                                        f'applied — {reason}. The pump keeps the modelling default, '
                                        f'which is not a Code value; 5.2.6.3 still caps it',
                          target=reference_loop.nameString(), article=f'{prefix}.14.(1)-(3)',
                          ruling='D-93')

    proposed_pumps = _applicable_pumps(match)
    sentence = _governing_sentence(proposed_pumps)
    if sentence is None:
        return audit.warn('efficiency', f'{reference_loop.nameString()}: the corresponding proposed '
                                        f'loop {match.nameString()} has no pump — {prefix}.14.(1)-(3) '
                                        'NOT applied', target=reference_loop.nameString(),
                          article=f'{prefix}.14.(1)-(3)', ruling='D-93')

    if len(reference_pumps) > 1:
        return audit.warn('efficiency', f'{reference_loop.nameString()} has {len(reference_pumps)} '
                                        f'pumps; {prefix}.14 describes ONE reference pump per system '
                                        '— NOT applied', target=reference_loop.nameString(),
                          article=f'{prefix}.14.(1)-(3)', ruling='D-93')

    reference_pump = reference_pumps[0]
    reference_flow = (optional_f(reference_pump.ratedFlowRate())
                      or optional_f(reference_pump.autosizedRatedFlowRate()))
    if sentence == '1':
        return _apply_sentence_1(reference_pump, proposed_pumps[0], prefix, audit)
    if sentence == '2':
        return _apply_sentence_2(reference_pump, proposed_pumps, reference_flow, prefix, audit)

    distribution_flow, flow_source = _distribution_flow(match)
    if distribution_flow is None:
        return audit.warn('efficiency', f'{reference_loop.nameString()}: {prefix}.14.(3) needs the '
                                        f'proposed distribution flow and {flow_source} — NOT applied. '
                                        'The sum of the pumps\' own flows is not a substitute: in '
                                        'series or primary-secondary they circulate the same water',
                          target=reference_loop.nameString(), article=f'{prefix}.14.(3)',
                          ruling='D-93')
    return _apply_sentence_3(reference_pump, proposed_pumps, distribution_flow, reference_flow,
                             prefix, audit, flow_source)


def _pump_shaft_and_electrical(pump):
    """(shaft W, electrical W) for a PROPOSED pump, or (None, None).

    Electrical is what the model states or E+ will size; shaft is that times
    the motor efficiency. Sentence (2) is expressed in shaft power and (3) in
    power demand "required by the motors" (5.2.6.3's phrase for the same
    quantity), so both are needed and the distinction is explicit.
    """
    flow = _pump_flow(pump)
    _, electrical = _pump_power_source(pump, flow)
    if electrical is None:
        return None, None

    motor_eff = pump.motorEfficiency()
    if not motor_eff or not 0.0 < motor_eff <= 1.0:
        return None, None

    return electrical * motor_eff, electrical


def _apply_sentence_1(reference_pump, proposed_pump, prefix, audit):
    """(1): head and efficiency identical to the corresponding proposed pump.

    Power is not transferred at all — it follows from the inherited
    characteristics at the reference's own flow, which is the sentence's whole
    point. Flow-invariant: nothing here needs restating after a re-size.
    """
    head = proposed_pump.ratedPumpHead()
    motor_eff = proposed_pump.motorEfficiency()
    # The efficiency the proposed STATES, resolved from whichever field defines
    # it — not the shaft-coefficient field, which on a pump that pins its power
    # through a hard triple still holds the untouched default and would transfer
    # a number the proposed never claimed.
    pump_eff = _hydraulic_efficiency(proposed_pump)
    if pump_eff is None:
        return audit.warn('efficiency', f'{reference_pump.nameString()}: the corresponding proposed '
                                        f'pump states no usable efficiency — {prefix}.14.(1) NOT applied',
                          target=reference_pump.nameString(), article=f'{prefix}.14.(1)', ruling='D-93')

    reference_pump.setDesignPowerSizingMethod(POWER_PER_FLOW_PER_PRESSURE)
    reference_pump.setRatedPumpHead(head)
    reference_pump.setDesignShaftPowerPerUnitFlowRatePerUnitHead(1.0 / pump_eff)
    reference_pump.setMotorEfficiency(motor_eff)
    reference_pump.autosizeRatedPowerConsumption()

    audit.decision('efficiency', 'pump head and efficiency inherited from the corresponding '
                                 'proposed pump',
                   target=reference_pump.nameString(),
                   inputs={'corresponding_pump': proposed_pump.nameString(),
                           'head_pa': ruby_round(head),
                           'pump_efficiency': ruby_round(pump_eff, 4),
                           'motor_efficiency': ruby_round(motor_eff, 4)},
                   value=f'head {ruby_round(head)} Pa at {ruby_round(pump_eff * 100.0, 1)}% pump / '
                         f'{ruby_round(motor_eff * 100.0, 1)}% motor efficiency; power follows the '
                         f'reference flow',
                   article=f'{prefix}.14.(1)', ruling='D-93')


def _apply_sentence_2(reference_pump, proposed_pumps, reference_flow, prefix, audit):
    """(2): the reference pump's peak SHAFT power equals the proposed pumps'
    combined peak shaft power — absolutely, not scaled by flow.

    D-11 transferred an intensity times the reference flow instead. On the
    Code's own Appendix example that yields 578.6 W where the Article requires
    861 W, a third short, because the reference flow (179.4 L/min, fixed by
    8.4.x.9.(6)(f)) is smaller than the proposed's combined 267 L/min.

    The equivalent motor efficiency is NOT a flow-weighted mean — that
    preserves shaft power while leaking electrical power. Sum-of-shaft over
    sum-of-electrical conserves both at once (Sol, DF-11 increment B), and it
    is the electrical figure that D-38's Part 5 cap then binds.

    Head carries the target, so it depends on the reference flow and MUST be
    restated after every re-size; the pipeline already re-applies efficiencies
    after each sizing run.
    """
    pairs = [_pump_shaft_and_electrical(pump) for pump in proposed_pumps]
    if any(s is None or e is None for s, e in pairs):
        # D-92's hostile-input hardening, which this must not regress: a pump
        # stating a power no pump can draw used to reach sum() as a None and
        # terminate compliance processing with a TypeError (Sol, PR #53).
        # (2) cannot preserve a combined shaft power it cannot compute, so the
        # group declines — it does not silently drop the offending pump, which
        # would transfer less power than the proposed system draws.
        return audit.warn('efficiency', f'{reference_pump.nameString()}: a pump in the corresponding '
                                        f'proposed system states a power no pump can draw, so the '
                                        f'combined shaft power is not computable — {prefix}.14.(2) '
                                        'NOT applied',
                          target=reference_pump.nameString(), article=f'{prefix}.14.(2)',
                          ruling='D-92 D-93')

    shaft = sum(s for s, _ in pairs)
    electrical = sum(e for _, e in pairs)
    flows = [_pump_flow(p)
             for p in proposed_pumps]

    # The Note's flow-weighted hydraulic efficiency. Numerically inert in
    # EnergyPlus — it only moves the head we state, never the energy — which is
    # why the Note's own 54.2 % not reproducing as a flow-weighted mean changes
    # no result. Recorded in D-93 rather than silently reconciled.
    # Each pump's own stated efficiency, resolved from the field that defines
    # it — the same resolver the known-test used to admit the group.
    efficiencies = [_hydraulic_efficiency(p) for p in proposed_pumps]
    usable = [(f, e) for f, e in zip(flows, efficiencies) if f and e]
    weighted = sum(f for f, _ in usable)
    pump_eff = (sum(f * e for f, e in usable) / weighted) if weighted else None
    motor_eff = shaft / electrical if electrical else None
    if not pump_eff or not motor_eff or reference_flow is None or reference_flow <= 0:
        return audit.warn('efficiency', f'{reference_pump.nameString()}: the proposed system states '
                                        f'no usable combined shaft power — {prefix}.14.(2) NOT applied',
                          target=reference_pump.nameString(), article=f'{prefix}.14.(2)',
                          ruling='D-93')

    head_pa = shaft * pump_eff / reference_flow
    reference_pump.setDesignPowerSizingMethod(POWER_PER_FLOW_PER_PRESSURE)
    reference_pump.setRatedPumpHead(head_pa)
    reference_pump.setDesignShaftPowerPerUnitFlowRatePerUnitHead(1.0 / pump_eff)
    reference_pump.setMotorEfficiency(motor_eff)
    reference_pump.autosizeRatedPowerConsumption()

    audit.decision('efficiency', "combined peak shaft power transferred from the proposed system's pumps",
                   target=reference_pump.nameString(),
                   inputs={'proposed_pumps': len(proposed_pumps),
                           'combined_shaft_w': ruby_round(shaft, 1),
                           'combined_electrical_w': ruby_round(electrical, 1),
                           'reference_flow_l_s': ruby_round(reference_flow * 1000.0, 2),
                           'pump_efficiency': ruby_round(pump_eff, 4),
                           'motor_efficiency': ruby_round(motor_eff, 4)},
                   value=f'shaft {ruby_round(shaft, 1)} W preserved absolutely (NOT scaled by the '
                         f'reference flow); head {ruby_round(head_pa)} Pa derived, electrical '
                         f'{ruby_round(electrical, 1)} W',
                   article=f'{prefix}.14.(2)', ruling='D-93')


def _apply_sentence_3(reference_pump, proposed_pumps, distribution_flow, reference_flow,
                      prefix, audit, flow_source):
    """(3): where head or efficiency is not known, the reference pump is based
    on the proposed's peak power demand in W/(L/s) — electrical, per 5.2.6.3's
    "required by the motors".

    The denominator is the DISTRIBUTION flow, counted once per fluid stream,
    never the sum of the pumps' rated flows: pumps in series or in a
    primary-secondary arrangement circulate the same water, and summing them
    halves the intensity.

    Head and the efficiency split only have to reproduce that intensity — the
    split cancels out of the derived power — so a physical default split is
    used and declared as the modelling fallback it is.
    """
    readable, unreadable = [], []
    for pump in proposed_pumps:
        _, electrical = _pump_shaft_and_electrical(pump)
        (readable if electrical is not None else unreadable).append((pump, electrical))
    if unreadable:
        # D-92: a pump stating a power no pump can draw is excluded ENTIRELY
        # rather than netted off the total — a negative wattage would transfer
        # an intensity lower than any pump in the proposed draws. Sol's ruling
        # governs unknown head and efficiency; it does not speak to unreadable
        # power, so this stands.
        audit.warn('efficiency', f'{reference_pump.nameString()}: '
                                 f'{", ".join(p.nameString() for p, _ in unreadable)} state a power no '
                                 f'pump can draw and are excluded from the {prefix}.14.(3) combination',
                   target=reference_pump.nameString(), article=f'{prefix}.14.(3)', ruling='D-92 D-93')
    if not readable:
        return audit.warn('efficiency', f'{reference_pump.nameString()}: no proposed pump states a '
                                        f'readable power — {prefix}.14.(3) NOT applied',
                          target=reference_pump.nameString(), article=f'{prefix}.14.(3)',
                          ruling='D-93')

    electricals = [e for _, e in readable]
    w_per_l_s = sum(electricals) / (distribution_flow * 1000.0)
    head_pa = _state_pump_characteristics(reference_pump, w_per_l_s,
                                          DEFAULT_MOTOR_EFFICIENCY, DEFAULT_PUMP_EFFICIENCY)
    audit.decision('efficiency', 'pump power intensity transferred from the proposed system',
                   target=reference_pump.nameString(),
                   inputs={'proposed_pumps': len(readable),
                           'combined_electrical_w': ruby_round(sum(electricals), 1),
                           'distribution_flow_l_s': ruby_round(distribution_flow * 1000.0, 2),
                           'distribution_flow_source': flow_source,
                           'proposed_w_per_l_s': ruby_round(w_per_l_s, 2),
                           'reference_flow_l_s': (ruby_round(reference_flow * 1000.0, 2)
                                                  if reference_flow else None)},
                   value=f'{ruby_round(w_per_l_s, 2)} W/(L/s) over the distribution flow (counted once, '
                         f'not the sum of pump flows); head {ruby_round(head_pa)} Pa at a declared '
                         f'{ruby_round(DEFAULT_PUMP_EFFICIENCY * 100.0, 1)}% pump / '
                         f'{ruby_round(DEFAULT_MOTOR_EFFICIENCY * 100.0, 1)}% modelling split',
                   article=f'{prefix}.14.(3)', ruling='D-93')


def _align_heat_pump_heating_capacity(model, audit, ruleset):
    """T4 (audit 2026-07-25) 8.4.4.13.(2)(c): "the heat pump's heating capacity
    at an outdoor air temperature of 8.3 C shall be identical to its cooling
    capacity". The vendored CAP_FT cubic evaluates ~1.0 at 8.3 C, so pinning
    the RATED heating capacity to the rated cooling capacity realizes the
    sentence (the -8.3 C 50% point comes from the same curve). Post-sizing:
    both capacities must be readable; paired coils only (same air loop).

    :param ruleset: the resolved edition, which decides
        whether the heat-pump article is numbered 8.4.4.13 or 8.4.5.13"""
    hp_article = ruleset.article('heat_pump_aux_fuel')
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
#
# D-89 closes deferred finding DF-4. Until it landed, `curve()` adopted ANY
# model object whose NAME matched the wanted curve, with no check on its form,
# its coefficients or its bounds — so a proposed model carrying a differently
# shaped `BOILER-EFFFPLR` silently supplied the reference building's part-load
# curve, and a neutral curve identifier could not be trusted once two editions
# published different numbers under it. Reuse is now TYPED (the lookup for the
# row's own form) and VALIDATED; a mismatch is a WARNING naming the foreign
# object, never a silent adoption, and the ruleset then builds its OWN object
# under a disambiguated name. An unknown form is a WARNING too, not a silent
# `None` that leaves the component with whatever curve it already had.
#
# MEASURED CONSEQUENCE, beyond the part-load curves D-89 is about:
# `btap/modeling/hvac/data/curves.json` ships DIFFERENT coefficients and bounds
# under four of the names this catalogue also uses — DXCOOL-REF-CAPFT,
# DXCOOL-REF-CAPFFLOW, DXCOOL-REF-COOLEIRFT and DXCOOL-REF-COOLPLFFPLR (the
# last wholly different: cubic [0.0277, 4.9151, -8.184, 4.2702] over x 0.7-1.0
# against this catalogue's [0.5157488, 2.1061434, -3.4205764, 1.8073371] over
# 0.25-1.0). Before D-89 the reference building silently ADOPTED the proposed
# model's versions; it now gets the ruleset's own, with a warning naming the
# foreign object. That is the rest of DF-4, and it moves reference DX energy in
# every scenario with a DX coil — not only the boiler/furnace scenarios. The
# right durable fix is to make the two catalogues agree; narrowing the check to
# `form == 'TableLookup'` in `curve()` would defer it again.

#: The tolerance a reused object's numbers must agree within. Generous enough
#: for an .osm/.idf text round-trip of a double, far tighter than any real
#: divergence between two catalogues.
CURVE_MATCH_TOL = 1e-9

#: form (as the catalogue spells it) -> how to find, read and build it.
#: ``coefficients`` are the SDK accessor suffixes in the catalogue's
#: ``coeff_1..coeff_N`` order, so one table drives building AND validating.
_CURVE_FORMS = {
    'BiQuadratic': {
        'cls': 'CurveBiquadratic', 'find': 'getCurveBiquadraticByName',
        'two_vars': True,
        'coefficients': ('1Constant', '2x', '3xPOW2', '4y', '5yPOW2', '6xTIMESY'),
    },
    'BiCubic': {
        'cls': 'CurveBicubic', 'find': 'getCurveBicubicByName',
        'two_vars': True,
        'coefficients': ('1Constant', '2x', '3xPOW2', '4y', '5yPOW2', '6xTIMESY',
                         '7xPOW3', '8yPOW3', '9xPOW2TIMESY', '10xTIMESYPOW2'),
    },
    'Cubic': {
        'cls': 'CurveCubic', 'find': 'getCurveCubicByName', 'two_vars': False,
        'coefficients': ('1Constant', '2x', '3xPOW2', '4xPOW3'),
    },
    'Quadratic': {
        'cls': 'CurveQuadratic', 'find': 'getCurveQuadraticByName', 'two_vars': False,
        'coefficients': ('1Constant', '2x', '3xPOW2'),
    },
    'TableLookup': {
        'cls': 'TableLookup', 'find': 'getTableLookupByName', 'two_vars': False,
        'coefficients': (),
    },
}
#: Spellings the vendored catalogue has used for the same form.
_FORM_ALIASES = {'Biquadratic': 'BiQuadratic', 'Bicubic': 'BiCubic'}


def curve_form(row):
    """The catalogue row's form, in this module's one spelling, or None."""
    form = row.get('form')
    form = _FORM_ALIASES.get(form, form)
    return form if form in _CURVE_FORMS else None


def _close(a, b):
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= CURVE_MATCH_TOL + CURVE_MATCH_TOL * abs(float(b))


def _optional_value(getter):
    """An SDK optional's value (or a plain value), None when uninitialized;
    accepts the accessor itself or its result."""
    value = getter() if callable(getter) else getter
    if hasattr(value, 'is_initialized'):
        return value.get() if value.is_initialized() else None
    return value



def _limits_match(obj, row, two_vars):
    """Declared bounds agree. A bound the row leaves null is not compared — the
    catalogue is silent there and the SDK's own default stands."""
    pairs = [('minimum_independent_variable_1', obj.minimumValueofx),
             ('maximum_independent_variable_1', obj.maximumValueofx)]
    if two_vars:
        pairs += [('minimum_independent_variable_2', obj.minimumValueofy),
                  ('maximum_independent_variable_2', obj.maximumValueofy)]
    if hasattr(obj, 'minimumCurveOutput'):
        pairs += [('minimum_dependent_variable_output', obj.minimumCurveOutput),
                  ('maximum_dependent_variable_output', obj.maximumCurveOutput)]
    elif hasattr(obj, 'minimumOutput'):
        pairs += [('minimum_dependent_variable_output', obj.minimumOutput),
                  ('maximum_dependent_variable_output', obj.maximumOutput)]
    for key, getter in pairs:
        wanted = row.get(key)
        value = getter()
        if wanted is None:
            # A bound the row leaves null must be ABSENT on the object too: a
            # foreign clamp the catalogue never declared is a divergence
            # (Sol's R-O review). A required SDK field (plain float, never
            # optional) cannot be absent and is not compared.
            if hasattr(value, 'is_initialized') and value.is_initialized():
                return False
            continue
        if not _close(_optional_value(value), wanted):
            return False
    return True


def _polynomial_matches(obj, row, spec):
    for index, suffix in enumerate(spec['coefficients'], start=1):
        wanted = row.get(f'coeff_{index}')
        got = getattr(obj, f'coefficient{suffix}')()
        if not _close(got, wanted):
            return False
    return _limits_match(obj, row, spec['two_vars'])


def _lookup_matches(obj, row):
    """One independent variable, the same grid, the same outputs, the same
    interpolation/extrapolation and the same bounds."""
    variables = obj.independentVariables()
    if len(variables) != 1:
        return False
    points = row.get('points') or []
    independent = variables[0]
    values = [float(v) for v in independent.values()]
    outputs = [float(v) for v in obj.outputValues()]
    if len(values) != len(points) or len(outputs) != len(points):
        return False
    for (x, y), got_x, got_y in zip(points, values, outputs):
        if not _close(got_x, x) or not _close(got_y, y):
            return False
    if independent.interpolationMethod() != row.get('interpolation'):
        return False
    if independent.extrapolationMethod() != row.get('extrapolation'):
        return False
    if obj.normalizationMethod() != 'None':
        return False
    if independent.unitType() != 'Dimensionless' or obj.outputUnitType() != 'Dimensionless':
        return False  # what _build_lookup writes; a foreign unit type is a divergence
    for key, getter in (('minimum_independent_variable_1', independent.minimumValue),
                        ('maximum_independent_variable_1', independent.maximumValue),
                        ('minimum_dependent_variable_output', obj.minimumOutput),
                        ('maximum_dependent_variable_output', obj.maximumOutput)):
        wanted = row.get(key)
        value = getter()
        if wanted is None:
            if hasattr(value, 'is_initialized') and value.is_initialized():
                return False  # a clamp the catalogue never declared
            continue
        if not _close(_optional_value(value), wanted):
            return False
    return True


def curve_matches(obj, row):
    """Does this model object state exactly what the catalogue row states?

    The FORM is part of the answer: an object of another curve type sharing the
    name never matches, however close its numbers (the SHW loader's rule — a
    Quadratic spec must not be smuggled through as a cubic with a zero term)."""
    form = curve_form(row)
    if form is None:
        return False
    spec = _CURVE_FORMS[form]
    caster = getattr(obj, f"to_{spec['cls']}", None)
    if caster is None:
        return False
    cast = caster()
    if not cast.is_initialized():
        return False
    obj = cast.get()
    if form == 'TableLookup':
        return _lookup_matches(obj, row)
    return _polynomial_matches(obj, row, spec)


def _build_polynomial(model, row, spec, name):
    k = getattr(openstudio.model, spec['cls'])(model)
    for index, suffix in enumerate(spec['coefficients'], start=1):
        getattr(k, f'setCoefficient{suffix}')(row.get(f'coeff_{index}'))
    set_limits(k, row, two_vars=spec['two_vars'])
    k.setName(name)
    return k


def _build_lookup(model, row, name):
    """A `Table:Lookup` over one independent variable — the representation the
    part-load articles' printed points and rationals are carried in (D-89)."""
    points = row.get('points') or []
    independent = openstudio.model.TableIndependentVariable(model)
    independent.setName(f'{name} PLR')
    independent.setInterpolationMethod(row.get('interpolation') or 'Linear')
    independent.setExtrapolationMethod(row.get('extrapolation') or 'Constant')
    independent.setUnitType('Dimensionless')
    independent.setValues([float(x) for x, _y in points])
    if row.get('minimum_independent_variable_1') is not None:
        independent.setMinimumValue(row['minimum_independent_variable_1'])
    if row.get('maximum_independent_variable_1') is not None:
        independent.setMaximumValue(row['maximum_independent_variable_1'])

    table = openstudio.model.TableLookup(model)
    table.addIndependentVariable(independent)
    table.setNormalizationMethod('None')
    table.setOutputUnitType('Dimensionless')
    table.setOutputValues([float(y) for _x, y in points])
    if row.get('minimum_dependent_variable_output') is not None:
        table.setMinimumOutput(row['minimum_dependent_variable_output'])
    if row.get('maximum_dependent_variable_output') is not None:
        table.setMaximumOutput(row['maximum_dependent_variable_output'])
    table.setName(name)
    return table


def curve(model, tables, name, audit=None, target=None):
    """Build — or reuse, once validated — a performance curve from this
    edition's own catalogue row.

    Reuse is typed and checked (D-89/DF-4): the lookup is the one for the row's
    OWN form, and the object it finds is adopted only when its form,
    coefficients or points, and declared bounds all state what the row states.
    A model object that merely shares the name is reported as foreign and the
    ruleset builds its own object beside it.
    """
    if name is None or str(name) == '':
        return None
    audit = audit if audit is not None else NullAudit()

    row = next((c for c in tables['curves'] if c['name'] == name), None)
    if row is None:
        audit.warn('efficiency',
                   f"curve '{name}' is not in this edition's curve catalogue — not set",
                   target=target, inputs={'curve': name})
        return None

    form = curve_form(row)
    if form is None:
        audit.warn('efficiency',
                   f"curve '{name}' declares form {row.get('form')!r}, which this "
                   "loader cannot build — not set",
                   target=target, inputs={'curve': name, 'form': row.get('form')},
                   ruling='D-89')
        return None
    spec = _CURVE_FORMS[form]

    found = getattr(model, spec['find'])(name)
    existing = found.get() if found.is_initialized() else None
    if existing is None:
        # An object of a DIFFERENT curve type may hold the name; one built under
        # it would be silently renamed by the SDK ('NAME 1'), so it counts as
        # occupying the name even though the typed lookup does not see it.
        existing = next((c for c in model.getCurves() if c.nameString() == name), None)
    if existing is not None and curve_matches(existing, row):
        return existing

    if existing is None:
        return (_build_lookup(model, row, name) if form == 'TableLookup'
                else _build_polynomial(model, row, spec, name))

    own_name = f'{name} (D-89)'
    # The ruleset's own object is found by CONTENT among the objects carrying
    # the disambiguated name (the SDK suffixes ' 1', ' 2' when a foreign object
    # squats on '(D-89)' too), never by the single fixed name: the foreign
    # object was reported when the own curve was first built for this model,
    # and every later component that needs the row reuses that one silently.
    for candidate in model.getCurves():
        if candidate.nameString().startswith(own_name) and curve_matches(candidate, row):
            return candidate
    built = (_build_lookup(model, row, own_name) if form == 'TableLookup'
             else _build_polynomial(model, row, spec, own_name))
    audit.warn('efficiency',
               f"model object named '{name}' does not state this edition's "
               f"{form} catalogue row — it is NOT adopted; the ruleset's own "
               f"curve is applied as '{built.nameString()}'",
               target=target, inputs={'curve': name, 'form': form,
                                      'applied': built.nameString()},
               ruling='D-89')
    return built


def set_limits(curve_object, row, two_vars=False):
    """Write every bound the row DECLARES. A declared ``0.0`` is a legitimate
    bound, not an absent one — the pre-D-89 truthiness test dropped it."""
    def write(key, setter):
        value = row.get(key)
        if value is not None:
            setter(value)

    write('minimum_independent_variable_1', curve_object.setMinimumValueofx)
    write('maximum_independent_variable_1', curve_object.setMaximumValueofx)
    if two_vars:
        write('minimum_independent_variable_2', curve_object.setMinimumValueofy)
        write('maximum_independent_variable_2', curve_object.setMaximumValueofy)
    if hasattr(curve_object, 'setMinimumCurveOutput'):
        write('minimum_dependent_variable_output', curve_object.setMinimumCurveOutput)
        write('maximum_dependent_variable_output', curve_object.setMaximumCurveOutput)


# ---------------- capacities ----------------

def optional_f(value):
    """Unwrap an SDK optional numeric to a float, or None when uninitialized."""
    if value is None:
        return None
    if not hasattr(value, 'is_initialized'):
        return float(value)
    return float(value.get()) if value.is_initialized() else None


# ---------------- plant capacity ownership (D-90) ----------------

#: D-90: the efficiency pass hard-sets boiler and chiller capacities (8.4.4.9.(6)
#: / 8.4.4.10.(6) staging) and hardens cooling-tower hydraulics. These features
#: record what it set and from what, so a repeat pass stages from the same
#: design capacity instead of halving an already-halved value, and
#: prepare_for_resizing releases exactly what the pass owns — never a capacity
#: the model supplied as an input.
CAPACITY_BASIS_FEATURE = 'btap_capacity_basis_w'
CAPACITY_SOURCE_FEATURE = 'btap_capacity_source'
CAPACITY_APPLIED_FEATURE = 'btap_capacity_applied_w'
BASE_NAME_FEATURE = 'btap_base_name'
TOWER_HARDENED_FEATURE = 'btap_tower_hardened_fields'
#: Every ownership feature, for clone hygiene: a reference built from a model
#: that already carries them must re-derive ownership from its own sizing.
OWNERSHIP_FEATURES = (CAPACITY_BASIS_FEATURE, CAPACITY_SOURCE_FEATURE,
                      CAPACITY_APPLIED_FEATURE, BASE_NAME_FEATURE,
                      TOWER_HARDENED_FEATURE)


def _same_capacity(a, b):
    return abs(a - b) <= 1e-6 + 1e-9 * max(abs(a), abs(b))


def _plant_capacity(component, hard_w, autosized_w):
    """D-90: the design capacity to stage from, and where it came from.

    A hard value equal to what this pass last applied is the pass's own output,
    so the stored design basis is returned with its stored source — re-applying
    then stages from the same basis. Any other hard value is an ``input`` (set by
    a user or carried in with a copied proposed plant); an unset capacity is the
    ``autosized`` result of the model's own sizing run.

    :return: (design capacity W, 'autosized' | 'input'), or (None, None) unsized"""
    props = component.additionalProperties()
    basis = props.getFeatureAsDouble(CAPACITY_BASIS_FEATURE)
    applied = props.getFeatureAsDouble(CAPACITY_APPLIED_FEATURE)
    source = props.getFeatureAsString(CAPACITY_SOURCE_FEATURE)
    if (hard_w is not None and basis.is_initialized() and applied.is_initialized()
            and source.is_initialized() and _same_capacity(hard_w, applied.get())):
        return basis.get(), source.get()
    if hard_w is not None:
        return hard_w, 'input'
    if autosized_w is not None:
        return autosized_w, 'autosized'
    return None, None


def _plant_role(boiler, name):
    """Which boiler of a staged plant this is — ``'primary'``, ``'secondary'``
    or ``None`` for a plant that is not a staged pair.

    DF-13. The 8.4.x.9.(6) bands describe a PLANT, but the pass applies them per
    boiler, and it used to decide by matching 'Primary Boiler' / 'Secondary
    Boiler' in the name. That is fragile in both directions: a plant the
    reference copied from the proposed (D-58) was staged and re-controlled
    because it happened to carry those names, while a genuine two-boiler plant
    named anything else was never staged — a miss of (6)(c), which Sol confirmed
    (2026-09-16) applies to copied reference plants too.

    Three sources, most reliable first. The builder's own feature survives any
    renaming this pass does. The name is kept as the second source so every
    model that staged correctly before still does. Topology is the last resort
    and is what adds the missing coverage: exactly two boilers on one hot-water
    loop ARE the (6)(c) pair whatever they are called, ordered by the loop's own
    supply order so the choice is deterministic."""
    stored = boiler.additionalProperties().getFeatureAsString(BOILER_PLANT_ROLE_FEATURE)
    if stored.is_initialized() and stored.get() in ('primary', 'secondary'):
        return stored.get()

    if 'Primary Boiler' in name:
        return 'primary'
    if 'Secondary Boiler' in name:
        return 'secondary'

    loop_ = boiler.plantLoop()
    if not loop_.is_initialized():
        return None

    boilers = [c.to_BoilerHotWater().get() for c in loop_.get().supplyComponents()
               if c.to_BoilerHotWater().is_initialized()]
    if len(boilers) != 2:
        return None

    return 'primary' if boiler.handle() == boilers[0].handle() else 'secondary'


def _base_name(component):
    """The name before this pass appended its capacity and efficiency suffix."""
    stored = component.additionalProperties().getFeatureAsString(BASE_NAME_FEATURE)
    return stored.get() if stored.is_initialized() and stored.get() else component.nameString()


def _record_capacity(component, basis_w, source, applied_w, base_name):
    props = component.additionalProperties()
    props.setFeature(CAPACITY_BASIS_FEATURE, float(basis_w))
    props.setFeature(CAPACITY_SOURCE_FEATURE, source)
    props.setFeature(CAPACITY_APPLIED_FEATURE, float(applied_w))
    props.setFeature(BASE_NAME_FEATURE, base_name)


def _release_capacity(component, autosize_method):
    """Return a capacity this pass derived from sizing to autosize. Inputs stay."""
    props = component.additionalProperties()
    source = props.getFeatureAsString(CAPACITY_SOURCE_FEATURE)
    if not (source.is_initialized() and source.get() == 'autosized'):
        return False
    getattr(component, autosize_method)()
    for feature in (CAPACITY_BASIS_FEATURE, CAPACITY_SOURCE_FEATURE, CAPACITY_APPLIED_FEATURE):
        props.resetFeature(feature)
    return True


def _hardened_tower_fields(tower):
    stored = tower.additionalProperties().getFeatureAsString(TOWER_HARDENED_FEATURE)
    return set(filter(None, stored.get().split(';'))) if stored.is_initialized() else set()


# ---------------- component appliers ----------------

# ---------------- part-load classes (D-89) ----------------

#: The feature a reference-building selection stamps on an object it creates, so
#: the part-load class it elected survives the SECOND efficiency pass — the same
#: `additionalProperties` mechanism the purchased-cooling chiller COP uses.
PART_LOAD_CLASS_FEATURE = BOILER_PART_LOAD_CLASS_FEATURE
#: Every class the enum admits, across both editions. A row or a feature naming
#: anything else is a data error, reported rather than quietly defaulted.
PART_LOAD_CLASSES = ('non_condensing', 'atmospheric', 'condensing',
                     'modulating', 'not_applicable')


def _edition_label(tables):
    provenance = tables.get('provenance') or {}
    return f"{provenance.get('code') or 'NECB'} {provenance.get('edition') or ''}".strip()


def _part_load_class(component, row, audit, target):
    """``(class, source)``. A class PROPAGATED onto the object wins over the
    table row's default: the row bins by fluid, fuel and capacity and knows
    nothing about the reference selection that created this object.

    Two guards (independent review, 2026-09-13): a value outside
    PART_LOAD_CLASSES is a DATA error, reported as such and ignored rather
    than treated as a class the edition happens not to publish; and a row
    whose class is ``not_applicable`` (no combustion part-load factor —
    the electric boiler, contract item 4) keeps it whatever a tag says."""
    row_class = row.get('part_load_curve_class')
    if row_class not in PART_LOAD_CLASSES:
        audit.warn('efficiency',
                   f"row declares part_load_curve_class {row_class!r}, which is not "
                   f"one of {PART_LOAD_CLASSES} — data error; treated as no class",
                   target=target, inputs={'part_load_curve_class': row_class},
                   ruling='D-89')
        row_class = None
    feature = component.additionalProperties().getFeatureAsString(PART_LOAD_CLASS_FEATURE)
    tag = feature.get() if feature.is_initialized() and feature.get() else None
    if tag is None:
        return row_class, 'row'
    if tag not in PART_LOAD_CLASSES:
        audit.warn('efficiency',
                   f"propagated part-load class tag {tag!r} is not one of "
                   f"{PART_LOAD_CLASSES} — data error; the row's class "
                   f"{row_class!r} is used",
                   target=target, inputs={'tag': tag, 'part_load_curve_class': row_class},
                   ruling='D-89')
        return row_class, 'row'
    if row_class == 'not_applicable':
        audit.warn('efficiency',
                   f"propagated part-load class tag {tag!r} ignored: this row has no "
                   f"combustion part-load factor (not_applicable) and a tag cannot "
                   f"give it one",
                   target=target, inputs={'tag': tag, 'part_load_curve_class': row_class},
                   ruling='D-89')
        return row_class, 'row'
    return tag, 'reference selection'


def _fheatplc_entry(tables, equipment, klass):
    return next((e for e in (tables.get('part_load_fheatplc') or [])
                 if e.get('equipment') == equipment and e.get('class') == klass), None)


def _curve_evidence(tables, row):
    """What the part-load curve IS: the article, the table row it comes from,
    the transform, the representation and its published error."""
    implements = row.get('implements') or {}
    entry = _fheatplc_entry(tables, implements.get('equipment'), implements.get('class'))
    article = (entry or {}).get('article') or '(article not declared)'
    error = implements.get('max_error_vs_exact')
    error_text = ('exact at every value the Code publishes' if not error
                  else f'max relative error {error * 100:.4f} % against the exact '
                       'requirement (sampled at PLR step 0.00001)')
    first_node = row.get('minimum_independent_variable_1')
    if first_node == 0:
        low_end = "; a node at PLR 0 carries the Code equation down to zero load"
    elif (entry or {}).get('form') == 'points':
        # A printed-point table (NECB 2020 Table 8.4.5.2.-B) is no equation:
        # the Code states nothing below its lowest point, so there is no
        # standby term to bound the hold against.
        low_end = (f"; the Code publishes no value below PLR {first_node}, and "
                   f"the table's Constant extrapolation holds the lowest printed "
                   f"factor there — an implementation choice D-89 records")
    else:
        low_end = (f"; below the first node (PLR {first_node}) the table's "
                   f"Constant extrapolation holds the factor, an under-count "
                   f"bounded by the Code's standby term FHeatPLC(0) x rated fuel"
                   + ("; the first node's value lies above the engine's 0.7 floor "
                      "on the coil part-load fraction, so the engine never clamps"
                      if implements.get('engine_floor') else ""))
    return (f"Article {article} states FHeatPLC as a fuel-INPUT ratio "
            f"(Table {implements.get('table')}, row "
            f"{implements.get('row')!r}), so the EnergyPlus part-load field "
            f"carries the transform {implements.get('transform')}; represented as "
            f"a Table:Lookup on {implements.get('grid')} with "
            f"{row.get('interpolation')} interpolation and "
            f"{row.get('extrapolation')} extrapolation — {error_text}{low_end}")


def _part_load_curve(component, tables, equipment, klass, audit, target):
    """``(curve or None, label, form, evidence)`` for one equipment class.

    The edition's own class -> curve map decides. A class the map does not carry
    is UNREPRESENTABLE in this edition: a warning and a constant part-load
    factor, never a quiet fall back to the non-condensing curve."""
    spec = (tables.get('part_load_curves') or {}).get(equipment) or {}
    article = spec.get('article')
    classes = spec.get('classes') or {}
    if klass is None:
        # _part_load_class has already reported the row's class as a data
        # error; a second "no representation" warning would misname the cause.
        return None, 'none (no valid class)', None, (
            f"the {equipment} row declares no valid part-load curve class, so no "
            f"part-load curve applies and the part-load factor stays constant at 1.0")
    if klass not in classes:
        audit.warn('efficiency',
                   f"part-load class {klass!r} has no representation in "
                   f"{_edition_label(tables)} — part-load factor left constant",
                   target=target,
                   inputs={'part_load_curve_class': klass, 'equipment': equipment},
                   article=article, ruling='D-89')
        return None, 'none (class unrepresentable in this edition)', None, (
            f"{_edition_label(tables)} publishes no part-load curve this ruleset can "
            f"apply to the {klass!r} class, so the part-load factor stays constant "
            f"at 1.0 rather than borrowing another class's curve")
    name = classes[klass]
    if name is None:
        return None, 'none (constant part-load factor 1.0)', None, (
            f"{article} derives the part-load fuel consumption of a FUEL-fired "
            f"{equipment} from FHeatPLC; this {equipment} has no fuel input to "
            f"adjust, so no part-load curve applies and the part-load factor is "
            f"constant at 1.0")
    built = curve(component.model(), tables, name, audit=audit, target=target)
    row = next((c for c in tables['curves'] if c['name'] == name), None)
    if built is None or row is None:
        return None, f'none ({name} unavailable)', None, (
            f"{article} requires a part-load curve for the {klass!r} class, and "
            f"{name!r} could not be built from this edition's catalogue; the "
            f"part-load factor is left constant at 1.0")
    return built, built.nameString(), row.get('form'), _curve_evidence(tables, row)


def _apply_boiler(boiler, tables, plant, audit):
    """Legacy boiler_hot_water_apply_efficiency_and_curves (NECB2011 hvac_systems.rb:539):
    primary/secondary staging (176/352 kW), the part-load curve of the boiler's own
    FHeatPLC class (D-89), AFUE/thermal/combustion -> thermal efficiency, legacy
    rename."""
    fuel_type = boiler.fuelType()
    if fuel_type == 'Electricity':
        fuel = 'Electric'
    elif fuel_type in ('FuelOilNo1', 'FuelOilNo2'):
        fuel = 'Oil'
    else:
        fuel = 'Gas'
    capacity_w, capacity_source = _plant_capacity(
        boiler, optional_f(boiler.nominalCapacity()), optional_f(boiler.autosizedNominalCapacity()))
    if capacity_w is None:
        return audit.warn('efficiency', 'boiler capacity unavailable (model not sized?) — not set',
                          target=boiler.nameString())

    boiler_capacity = capacity_w
    # D-90: stage and rename from the base name, so a repeat pass neither
    # re-halves the plant nor appends a second capacity suffix
    name = _base_name(boiler)
    role = _plant_role(boiler, name)
    if role is not None:
        kw = capacity_w / 1000.0
        modulating = kw > plant['two_boiler_max_kw'] and role == 'primary'
        if kw > plant['two_boiler_max_kw']:  # 8.4.4.9.(6)(d): 'exceeds 352 kW' (strict)
            if role == 'secondary':
                boiler_capacity = 0.001
        elif kw > plant['single_boiler_max_kw']:  # (6)(c): 'greater than 176' (strict)
            boiler_capacity = capacity_w / 2
        elif role == 'secondary':
            boiler_capacity = 0.001
        elif capacity_w <= 1.0:
            boiler_capacity = 1.0
        # D-90: every pass sets the COMPLETE control state of the band it lands in.
        # The build-time pass reads the proposed's sizing and the next pass the
        # reference's, so a plant can cross 352 kW in either direction between
        # passes; a lower band must not keep the modulating controls of (d). The
        # non-modulating state is the one the plant builder leaves: an explicit
        # ConstantFlow flow mode and a defaulted minimum part-load ratio.
        if modulating:
            boiler.setBoilerFlowMode('LeavingSetpointModulated')
            boiler.setMinimumPartLoadRatio(plant['modulating_min_fraction'])
        else:
            boiler.setBoilerFlowMode('ConstantFlow')
            boiler.resetMinimumPartLoadRatio()
    boiler.setNominalCapacity(boiler_capacity)
    _record_capacity(boiler, capacity_w, capacity_source, boiler_capacity, name)

    cap_btuh = w_to_btu_per_hr(boiler_capacity)
    row = find_row(tables['boilers'], {'fluid_type': 'Hot Water', 'fuel_type': fuel}, cap_btuh)
    if row is None:
        return audit.warn('efficiency', 'no boiler efficiency row found — not set', target=name,
                          inputs={'fuel': fuel, 'capacity_btu_hr': ruby_round(cap_btuh)})

    # 8.4.5.2./8.4.6.2. state FHeatPLC on the part-load ratio alone, so the
    # evaluation variable is not load-bearing today; it is set explicitly
    # because the field has no IDD default and any future temperature-dependent
    # curve (2025's condensing row) needs an adjudicated basis.
    boiler.setEfficiencyCurveTemperatureEvaluationVariable('EnteringBoiler')
    klass, class_source = _part_load_class(boiler, row, audit, name)
    plf, curve_label, curve_shape, evidence = _part_load_curve(
        boiler, tables, 'boiler', klass, audit, name)
    if plf is None:
        # also clears a curve the proposed model contributed to this clone
        boiler.resetNormalizedBoilerEfficiencyCurve()
    else:
        boiler.setNormalizedBoilerEfficiencyCurve(plf)

    thermal_eff, label = boiler_thermal_efficiency(row)
    if thermal_eff is None:
        return audit.warn('efficiency', 'boiler row has no efficiency value — not set', target=name)

    boiler.setNominalThermalEfficiency(thermal_eff)
    boiler.setName(f'{name} {ruby_round(w_to_kbtu_per_hr(boiler_capacity))}kBtu/hr {label}')
    article = ((tables.get('part_load_curves') or {}).get('boiler') or {}).get('article')
    return audit.decision('efficiency', 'boiler efficiency applied', target=name,
                          inputs={'fuel': fuel,
                                  'capacity_kw': ruby_round(boiler_capacity / 1000.0, 1),
                                  'design_capacity_kw': ruby_round(capacity_w / 1000.0, 1),
                                  'capacity_source': capacity_source,
                                  'part_load_curve_class': klass,
                                  'class_source': class_source,
                                  'curve': curve_label, 'form': curve_shape},
                          value=f"thermal efficiency {ruby_round(thermal_eff, 3)} ({label}), "
                                f"part-load curve {curve_label}",
                          evidence=f"{evidence}; the efficiency curve is evaluated on "
                                   "the EnteringBoiler temperature",
                          article=article, ruling='D-89 D-90')


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
    name = _base_name(chiller)
    capacity_w, capacity_source = _plant_capacity(
        chiller, optional_f(chiller.referenceCapacity()),
        optional_f(chiller.autosizedReferenceCapacity()))
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
    _record_capacity(chiller, capacity_w, capacity_source, chiller_capacity, name)

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
        c = curve(chiller.model(), tables, row.get(key), audit=audit, target=name)
        if c:
            getattr(chiller, setter)(c)

    kw_per_ton = row.get('minimum_full_load_efficiency')
    if kw_per_ton is None:
        return audit.warn('efficiency', 'chiller row has no full-load efficiency — COP not set', target=name)

    purchased_cooling_cop = chiller.additionalProperties().getFeatureAsDouble(
        'btap_purchased_cooling_reference_cop')
    # The NAME suffix is compact by long-standing convention; the audit VALUE
    # must always state the COP actually applied, because that number IS the
    # determination an AHJ reads.
    if purchased_cooling_cop.is_initialized():
        cop = purchased_cooling_cop.get()
        article = 'Table 8.4.3.5'
        action = 'purchased-cooling reference chiller COP applied'
        name_suffix = f'COP {ruby_round(cop, 3)}'
        applied = f'COP {ruby_round(cop, 3)}'
    else:
        cop = kw_per_ton_to_cop(kw_per_ton)
        article = 'NECB 2020 Table 5.2.12.1 (chillers)'
        action = 'chiller efficiency applied'
        name_suffix = f'{ruby_round(kw_per_ton, 1)}kW/ton'
        applied = f'COP {ruby_round(cop, 2)} ({ruby_round(kw_per_ton, 2)} kW/ton)'
    chiller.setReferenceCOP(cop)
    chiller.setName(f'{name} {ruby_round(tons)}tons {name_suffix}')
    return audit.decision('efficiency', action, target=name,
                          inputs={'cooling_type': cooling_type, 'compressor': compressor,
                                  'tons': ruby_round(tons, 1),
                                  'design_capacity_kw': ruby_round(capacity_w / 1000.0, 1),
                                  'capacity_source': capacity_source},
                          value=f'{applied}, curves '
                                f"{row.get('capft')}/{row.get('eirft')}/{row.get('eirfplr')}",
                          article=article, ruling='D-90')


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
            # D-90: record every field hardened FROM an autosized value (and the
            # fan power, if it was autosized) so prepare_for_resizing can hand
            # them back to EnergyPlus before the next sizing run; input values
            # are never recorded and so never released.
            hardened = _hardened_tower_fields(towers[0])
            for getter, setter, is_autosized, release in (
                    ('autosizedDesignWaterFlowRate', 'setDesignWaterFlowRate',
                     'isDesignWaterFlowRateAutosized', 'autosizeDesignWaterFlowRate'),
                    ('autosizedDesignAirFlowRate', 'setDesignAirFlowRate',
                     'isDesignAirFlowRateAutosized', 'autosizeDesignAirFlowRate'),
                    ('autosizedUFactorTimesAreaValueatDesignAirFlowRate',
                     'setUFactorTimesAreaValueatDesignAirFlowRate',
                     'isUFactorTimesAreaValueatDesignAirFlowRateAutosized',
                     'autosizeUFactorTimesAreaValueatDesignAirFlowRate'),
                    ('autosizedAirFlowRateinFreeConvectionRegime',
                     'setAirFlowRateinFreeConvectionRegime',
                     'isAirFlowRateinFreeConvectionRegimeAutosized',
                     'autosizeAirFlowRateinFreeConvectionRegime'),
                    ('autosizedUFactorTimesAreaValueatFreeConvectionAirFlowRate',
                     'setUFactorTimesAreaValueatFreeConvectionAirFlowRate',
                     'isUFactorTimesAreaValueatFreeConvectionAirFlowRateAutosized',
                     'autosizeUFactorTimesAreaValueatFreeConvectionAirFlowRate')):
                v = getattr(towers[0], getter)()
                if hasattr(v, 'is_initialized') and v.is_initialized():
                    if getattr(towers[0], is_autosized)():
                        hardened.add(release)
                    getattr(towers[0], setter)(v.get())
            if towers[0].isFanPoweratDesignAirFlowRateAutosized():
                hardened.add('autosizeFanPoweratDesignAirFlowRate')
            towers[0].setFanPoweratDesignAirFlowRate(fan_w)
            if hardened:
                towers[0].additionalProperties().setFeature(
                    TOWER_HARDENED_FEATURE, ';'.join(sorted(hardened)))
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
        c = curve(coil.model(), tables, row.get(key), audit=audit, target=name)
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
            c = curve(coil.model(), tables, row.get(key), audit=audit, target=name)
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
            c = curve(coil.model(), tables, row.get(key), audit=audit, target=name)
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

    klass, class_source = _part_load_class(coil, row, audit, coil.nameString())
    plf, curve_label, curve_shape, evidence = _part_load_curve(
        coil, tables, 'furnace', klass, audit, name)
    if plf is None:
        coil.resetPartLoadFractionCorrelationCurve()
    else:
        coil.setPartLoadFractionCorrelationCurve(plf)

    # same AFUE/thermal/combustion triad
    thermal_eff, label = boiler_thermal_efficiency(row)
    if thermal_eff is None:
        return audit.warn('efficiency', 'furnace row has no efficiency value — not set', target=name)

    for stage in coil.stages():
        stage.setGasBurnerEfficiency(thermal_eff)
    coil.setName(f'{name} {ruby_round(w_to_kbtu_per_hr(capacity_w))}kBtu/hr {label}')
    article = ((tables.get('part_load_curves') or {}).get('furnace') or {}).get('article')
    return audit.decision('efficiency', 'staged gas heating efficiency applied to every stage', target=name,
                          inputs={'stages': len(coil.stages()),
                                  'top_stage_kw': ruby_round(capacity_w / 1000.0, 1),
                                  'part_load_curve_class': klass,
                                  'class_source': class_source,
                                  'curve': curve_label, 'form': curve_shape},
                          value=f'burner efficiency {ruby_round(thermal_eff, 3)} ({label}) on all '
                                f"{len(coil.stages())} stages, part-load curve {curve_label}",
                          evidence=f"{evidence}; the part-load curve sits on the PARENT "
                                   "staged coil, which carries EnergyPlus' single "
                                   "part-load-fraction field (D-46)",
                          article=article, ruling='D-46 D-89')


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
        c = curve(coil.model(), tables, row.get(key), audit=audit, target=name)
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

    klass, class_source = _part_load_class(coil, row, audit, coil.nameString())
    plf, curve_label, curve_shape, evidence = _part_load_curve(
        coil, tables, 'furnace', klass, audit, name)
    if plf is None:
        coil.resetPartLoadFractionCorrelationCurve()
    else:
        coil.setPartLoadFractionCorrelationCurve(plf)

    # same AFUE/thermal/combustion triad
    thermal_eff, label = boiler_thermal_efficiency(row)
    if thermal_eff is None:
        return audit.warn('efficiency', 'furnace row has no efficiency value — not set', target=name)

    coil.setGasBurnerEfficiency(thermal_eff)
    coil.setName(f'{name} {ruby_round(w_to_kbtu_per_hr(capacity_w))}kBtu/hr {label}')
    article = ((tables.get('part_load_curves') or {}).get('furnace') or {}).get('article')
    return audit.decision('efficiency', 'gas heating coil efficiency applied', target=name,
                          inputs={'capacity_kw': ruby_round(capacity_w / 1000.0, 1),
                                  'part_load_curve_class': klass,
                                  'class_source': class_source,
                                  'curve': curve_label, 'form': curve_shape},
                          value=f'burner efficiency {ruby_round(thermal_eff, 3)} ({label}), '
                                f'part-load curve {curve_label}',
                          evidence=evidence,
                          article=article, ruling='D-89')


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

def apply_efficiencies(model, code='necb2020', audit=None, proposed=None):
    """Facade: apply NECB minimum efficiencies to a sized model. Pass the sized
    PROPOSED model via proposed= to enable the 8.4.4.14.(1)-(3) pump power
    transfer (combined W/(L/s) by loop type); without it the Table 8.4.4.14
    curves still apply and the skip is noted in the audit."""
    return _apply(model, resolve(code), audit=audit,
                  proposed=proposed)


def prepare_for_resizing(model, audit=None, code='necb2020'):
    """Facade: make an ALREADY-EFFICIENCY-APPLIED model safe to re-size.

    Since D-92 the pass does NOT hard-set pump power: it states head, shaft
    coefficient and motor efficiency and leaves power autosized, so EnergyPlus
    derives it from whatever flow it last sized. A pump the pass has touched
    therefore needs no release at all — it is already consistent by
    construction, and there is no reconciliation step any more.

    What still needs releasing is a hard power the MODEL supplied: an input
    pump power sits frozen while pump FLOW stays autosized, and when a later
    sizing run grows the flow, the frozen power and head no longer fit it —
    EnergyPlus FATALS on "Calculated Pump Efficiency > 100%" during input
    checking, before the efficiency pass gets a chance to restate the pump.
    Releasing that power to autosize removes the inconsistency, and the
    caller's next apply_efficiencies restates the pump against the NEW flow.

    Call this before EVERY re-sizing run of a model that has already been
    through apply_efficiencies — the 8.4.1.2.(5) capacity iteration does.

    EVERY hard-set pump power is released, including one the model supplied as an
    input: a plant retained by the D-58 residential identity arrives with the
    legacy's hard power and head, and the reference re-sizes that loop's flow, so
    keeping the input value is what triggers the fatal above (found on the
    SmallHotel gas variant). Pump power is deliberately NOT ownership-tracked the
    way plant capacity is, and tracking it would change nothing: 8.4.4.14 (2025:
    8.4.5.14) makes the reference's rated power a DERIVED quantity, and the next
    pass re-derives it for every non-SWH pump whoever set the old value. WHICH
    sentence supplies that value — (1)'s inherited head and efficiency, (2)'s
    combined shaft power, or (3)'s W/(L/s) over the distribution flow — is
    decided per correspondence by D-93. The caller's
    next apply_efficiencies(proposed=) re-transfers it against the newly sized flow;
    WITHOUT proposed= nothing is transferred and the released pump is left for
    EnergyPlus to size.

    A service-water circulator is NOT released (DF-12, closed by D-92). D-27 puts
    it outside 8.4.4.14 and the pump pass leaves it 'as built', so releasing it
    would strand it autosized with nothing to re-establish it — the release is
    scoped to the pumps the Article governs.

    D-90: the same holds for plant capacity. The pass hard-sets boiler and
    chiller capacities (8.4.4.9.(6)(a): the sum of the served systems' capacities,
    then staged) and hardens tower hydraulics; left in place, the reference
    plant stays at whatever the FIRST pass read — on a reference clone, the
    proposed's sizing — while its systems grow through every capacity increase.
    Capacities the pass derived from sizing are released to autosize here;
    capacities the model supplied as inputs are kept.

    :return: int — pumps released"""
    audit = audit if audit is not None else NullAudit()
    # the edition's own article numbers: 2020 8.4.4.9/8.4.4.10/8.4.4.14,
    # 2025 8.4.5.9/8.4.5.10/8.4.5.14
    prefix = resolve(code).article('reference_subsection')
    # DF-12: the release is sizing safety for the pumps 8.4.x.14 governs. A
    # service-water circulator is outside that Article (D-27) and the pump pass
    # leaves it 'as built', so releasing it would strand it autosized with
    # nothing to re-establish it.
    def _hvac_pump(pump):
        loop_ = pump.plantLoop()
        return not (loop_.is_initialized() and _swh_loop(loop_.get()))

    pumps = ([p for p in model.getPumpVariableSpeeds()
              if not p.ratedPowerConsumption().empty() and _hvac_pump(p)]
             + [p for p in model.getPumpConstantSpeeds()
                if not p.ratedPowerConsumption().empty() and _hvac_pump(p)])
    for p in pumps:
        p.autosizeRatedPowerConsumption()
    if pumps:
        audit.info('efficiency', 'hard-set pump power released to autosize for the re-sizing run — the '
                                 'efficiency pass re-transfers it against the newly sized flow',
                   inputs={'pumps': len(pumps)}, article=f'{prefix}.14.(1)-(3)', ruling='D-11 D-27')

    released = {'boilers': 0, 'chillers': 0, 'towers': 0}
    for boiler in model.getBoilerHotWaters():
        released['boilers'] += _release_capacity(boiler, 'autosizeNominalCapacity')
    for chiller in model.getChillerElectricEIRs():
        released['chillers'] += _release_capacity(chiller, 'autosizeReferenceCapacity')
    for tower in model.getCoolingTowerSingleSpeeds():
        fields = _hardened_tower_fields(tower)
        if fields:
            for release in sorted(fields):
                getattr(tower, release)()
            tower.additionalProperties().resetFeature(TOWER_HARDENED_FEATURE)
            released['towers'] += 1
    if any(released.values()):
        audit.info('efficiency', 'plant capacities the efficiency pass derived from sizing released to '
                                 'autosize for the re-sizing run — the next pass re-stages them from the '
                                 'newly sized design capacities; input capacities are kept',
                   inputs=released, article=f'{prefix}.9.(6)(a); {prefix}.10.(6); 8.4.1.2.(5)',
                   ruling='D-90')
    return len(pumps)
