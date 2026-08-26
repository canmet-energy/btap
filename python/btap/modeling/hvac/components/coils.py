"""SDK-only coil factories. DX coils carry the NECB reference curves from data/curves.json
(ported from openstudio-standards add_onespeed_DX_coil / add_onespeed_htg_DX_coil)."""

from __future__ import annotations

import openstudio

from btap.modeling.hvac.components import curves as curves_mod


def dx_cooling_single_speed(model, schedule, name='CoilCoolingDXSingleSpeed_dx'):
    """Single-speed DX cooling coil with NECB reference curves.

    :param model: openstudio.model.Model
    :param schedule: availability schedule
    :return: openstudio.model.CoilCoolingDXSingleSpeed
    """
    coil = openstudio.model.CoilCoolingDXSingleSpeed(
        model,
        schedule,
        curves_mod.build(model, 'DXCOOL-NECB2011-REF-CAPFT'),
        curves_mod.build(model, 'DXCOOL-NECB2011-REF-CAPFFLOW'),
        curves_mod.build(model, 'DXCOOL-NECB2011-REF-COOLEIRFT'),
        curves_mod.build(model, 'DXCOOL-NECB2011-REF-EIRFFLOW'),
        curves_mod.build(model, 'DXCOOL-NECB2011-REF-COOLPLFFPLR'),
    )
    coil.setName(name)
    return coil


def dx_heating_single_speed(model, schedule, name='CoilHeatingDXSingleSpeed_dx'):
    """Single-speed DX heating coil with NECB reference curves.

    :param model: openstudio.model.Model
    :param schedule: availability schedule
    :return: openstudio.model.CoilHeatingDXSingleSpeed
    """
    coil = openstudio.model.CoilHeatingDXSingleSpeed(
        model,
        schedule,
        curves_mod.build(model, 'DXHEAT-NECB2011-REF-CAPFT'),
        curves_mod.build(model, 'DXHEAT-NECB2011-REF-CAPFFLOW'),
        curves_mod.build(model, 'DXHEAT-NECB2011-REF-EIRFT'),
        curves_mod.build(model, 'DXHEAT-NECB2011-REF-EIRFFLOW'),
        curves_mod.build(model, 'DXHEAT-NECB2011-REF-PLFFPLR'),
    )
    coil.setMinimumOutdoorDryBulbTemperatureforCompressorOperation(-10.0)
    coil.setName(name)
    return coil


def dx_cooling_multi_speed(model, _schedule, stages=2, name='CoilCoolingDXMultiSpeed_dx'):
    """Multi-speed DX cooling coil with the NECB reference curves on EVERY stage
    (8.4.4.10.(8) / 2025 8.4.5.10.(8) staged DX). Stage capacities and flows are
    AUTOSIZED — E+ sizes stage k to k/N of the top stage through the containing
    unitary's UnitarySystemPerformanceMultispeed flow ratios, which is what
    realizes the code's equal capacity increments without hard-setting anything
    (hard-set capacities would break 8.4.1.2.(5) capacity auto-iteration).

    :param stages: initial stage count (the efficiency pass adjusts it post-sizing)
    :return: openstudio.model.CoilCoolingDXMultiSpeed
    """
    coil = openstudio.model.CoilCoolingDXMultiSpeed(model)
    coil.setName(name)
    coil.setFuelType('Electricity')
    # legacy hvac_system_3_and_8_multi_speed.rb:118 — the PLF cycling penalty
    # belongs to the lowest stage only
    coil.setApplyPartLoadFractiontoSpeedsGreaterthan1(False)
    for _ in range(stages):
        coil.addStage(dx_cooling_stage(model))
    return coil


def dx_cooling_stage(model):
    """One CoilCoolingDXMultiSpeedStageData carrying the NECB reference curves.
    :return: openstudio.model.CoilCoolingDXMultiSpeedStageData"""
    stage = openstudio.model.CoilCoolingDXMultiSpeedStageData(model)
    stage.setTotalCoolingCapacityFunctionofTemperatureCurve(curves_mod.build(model, 'DXCOOL-NECB2011-REF-CAPFT'))
    stage.setTotalCoolingCapacityFunctionofFlowFractionCurve(curves_mod.build(model, 'DXCOOL-NECB2011-REF-CAPFFLOW'))
    stage.setEnergyInputRatioFunctionofTemperatureCurve(curves_mod.build(model, 'DXCOOL-NECB2011-REF-COOLEIRFT'))
    stage.setEnergyInputRatioFunctionofFlowFractionCurve(curves_mod.build(model, 'DXCOOL-NECB2011-REF-EIRFFLOW'))
    stage.setPartLoadFractionCorrelationCurve(curves_mod.build(model, 'DXCOOL-NECB2011-REF-COOLPLFFPLR'))
    stage.autosizeGrossRatedTotalCoolingCapacity()
    stage.autosizeGrossRatedSensibleHeatRatio()
    stage.autosizeRatedAirFlowRate()
    return stage


def gas_heating_multi_stage(model, _schedule, stages=2, name='CoilHeatingGasMultiStage_gas'):
    """Multi-stage gas furnace coil (8.4.4.9.(7) / 2025 8.4.5.9.(7)). Stage
    capacities stay AUTOSIZED for the same reason as the DX stages above.
    :return: openstudio.model.CoilHeatingGasMultiStage"""
    coil = openstudio.model.CoilHeatingGasMultiStage(model)
    coil.setName(name)
    for _ in range(stages):
        coil.addStage(gas_heating_stage(model))
    return coil


def gas_heating_stage(model):
    """:return: openstudio.model.CoilHeatingGasMultiStageStageData"""
    stage = openstudio.model.CoilHeatingGasMultiStageStageData(model)
    stage.autosizeNominalCapacity()
    return stage


def dx_heating_multi_speed(model, _schedule, stages=2, name='CoilHeatingDXMultiSpeed_ashp'):
    """Multi-speed DX HEATING coil (reference ASHP staging). Same autosizing
    contract; the -10 degC compressor cutoff is applied by the reference
    transform, matching the single-speed coil.
    :return: openstudio.model.CoilHeatingDXMultiSpeed"""
    coil = openstudio.model.CoilHeatingDXMultiSpeed(model)
    coil.setName(name)
    if hasattr(coil, 'setFuelType'):
        coil.setFuelType('Electricity')
    coil.setApplyPartLoadFractiontoSpeedsGreaterthan1(False)
    coil.setMinimumOutdoorDryBulbTemperatureforCompressorOperation(-10.0)
    for _ in range(stages):
        coil.addStage(dx_heating_stage(model))
    return coil


def dx_heating_stage(model):
    """:return: openstudio.model.CoilHeatingDXMultiSpeedStageData"""
    stage = openstudio.model.CoilHeatingDXMultiSpeedStageData(model)
    stage.setHeatingCapacityFunctionofTemperatureCurve(curves_mod.build(model, 'DXHEAT-NECB2011-REF-CAPFT'))
    stage.setHeatingCapacityFunctionofFlowFractionCurve(curves_mod.build(model, 'DXHEAT-NECB2011-REF-CAPFFLOW'))
    stage.setEnergyInputRatioFunctionofTemperatureCurve(curves_mod.build(model, 'DXHEAT-NECB2011-REF-EIRFT'))
    stage.setEnergyInputRatioFunctionofFlowFractionCurve(curves_mod.build(model, 'DXHEAT-NECB2011-REF-EIRFFLOW'))
    stage.setPartLoadFractionCorrelationCurve(curves_mod.build(model, 'DXHEAT-NECB2011-REF-PLFFPLR'))
    stage.autosizeGrossRatedHeatingCapacity()
    stage.autosizeRatedAirFlowRate()
    return stage


def supply_components(air_loop):
    """Supply-path components of an air loop with every AirLoopHVACUnitarySystem
    container REPLACED by the fan and coils it holds.

    Staged reference systems (8.4.4.9.(7)/8.4.4.10.(8)) put the fan and coils
    INSIDE an AirLoopHVACUnitarySystem — a multispeed coil cannot sit bare on
    an air loop — so a plain ``supplyComponents`` scan silently stops finding
    them. Every consumer that looks for coils or fans on a supply path must go
    through here.

    :param air_loop: openstudio.model.AirLoopHVAC
    :return: list of openstudio.model.ModelObject
    """
    out = []
    for comp in air_loop.supplyComponents():
        unitary = comp.to_AirLoopHVACUnitarySystem()
        if unitary.is_initialized():
            out.extend(unitary_children(unitary.get()))
            continue

        # Legacy unitary HP wrappers (the NECB archetypes' PSZ ASHP recipe) hold
        # their coils the same way — without this unwrap the loop reads coil-less
        # and its heat pump is invisible to characterize (D-52).
        hp = comp.to_AirLoopHVACUnitaryHeatPumpAirToAir()
        if hp.is_initialized():
            hp = hp.get()
            out.extend([hp.heatingCoil(), hp.coolingCoil(),
                        hp.supplementalHeatingCoil(), hp.supplyAirFan()])
            continue

        if hasattr(comp, 'to_AirLoopHVACUnitaryHeatPumpAirToAirMultiSpeed'):
            hp_ms = comp.to_AirLoopHVACUnitaryHeatPumpAirToAirMultiSpeed()
            if hp_ms.is_initialized():
                hp_ms = hp_ms.get()
                out.extend([hp_ms.heatingCoil(), hp_ms.coolingCoil(),
                            hp_ms.supplementalHeatingCoil(), hp_ms.supplyAirFan()])
                continue

        out.append(comp)
    return out


def set_stage_flow_ratios(unitary, min_ratio=0.0):
    """Rewrite a unitary's UnitarySystemPerformanceMultispeed supply-airflow
    ratios from the CURRENT stage counts of its coils: stage k of N gets
    ratio k/N, per mode, so E+ autosizes stage k to k/N of the top stage
    (the equal capacity increments of 8.4.4.9.(7)/8.4.4.10.(8)).

    The airflow MUST track the staged capacity: the EnergyPlus IDD requires
    each speed's rated air flow to be 0.00004027-0.00006041 m3/s per watt OF
    THAT SPEED's capacity, so a stage carrying half the capacity at full flow
    sits at twice the legal ratio. Staged DX is inherently a multi-speed-fan
    machine; Table 8.4.4.7.-B's "Constant-volume" describes the DISTRIBUTION
    (no VAV terminals), not a fan locked to one speed.

    ``min_ratio`` floors every stage's ratio — pass the minimum-outdoor-air
    fraction of design supply flow so a low stage still delivers the required
    ventilation air (the same protection the legacy implementation applies by
    overriding low-speed flow to the minimum OA rate). Below that floor the
    unit would stage down past its own ventilation requirement.

    Heating and cooling stage counts are independent — the SDK writes each
    mode's speed count from its own coil, and the shorter mode's trailing
    ratios are pinned at 1.0. Single-stage (or absent) coils count as 1.

    :param unitary: openstudio.model.AirLoopHVACUnitarySystem
    :param min_ratio: lower bound on every stage ratio (0.0 = no floor)
    :return: number of ratio fields written, or None without a performance object
    """
    performance = unitary.designSpecificationMultispeedObject()
    if not performance.is_initialized():
        return None

    performance = performance.get()
    heating = stage_count(unitary.heatingCoil())
    cooling = stage_count(unitary.coolingCoil())
    floor = min(max(float(min_ratio), 0.0), 1.0)
    fields = [
        openstudio.model.SupplyAirflowRatioField(
            min(max(float(k) / heating, floor), 1.0),
            min(max(float(k) / cooling, floor), 1.0),
        )
        for k in range(1, max(heating, cooling) + 1)
    ]
    performance.setSupplyAirflowRatioFields(fields)
    return len(fields)


def outdoor_air_fraction(air_loop):
    """Minimum outdoor air flow as a fraction of design supply flow, from the
    SIZED air loop the unitary sits on — the floor a staged unit's low speed
    must not drop below without starving ventilation.
    :return: float; 0.0 when either flow is unavailable (no floor applied)"""
    if air_loop is None:
        return 0.0

    supply = optional_value(air_loop.designSupplyAirFlowRate())
    if supply is None:
        supply = optional_value(air_loop.autosizedDesignSupplyAirFlowRate())
    if supply is None or not supply > 0:
        return 0.0

    oa_system = air_loop.airLoopHVACOutdoorAirSystem()
    if not oa_system.is_initialized():
        return 0.0

    controller = oa_system.get().getControllerOutdoorAir()
    min_oa = optional_value(controller.minimumOutdoorAirFlowRate())
    if min_oa is None:
        min_oa = optional_value(controller.autosizedMinimumOutdoorAirFlowRate())
    if min_oa is None or not min_oa > 0:
        return 0.0

    return min(max(min_oa / supply, 0.0), 1.0)


def optional_value(value):
    if hasattr(value, 'is_initialized'):
        return value.get() if value.is_initialized() else None
    return value


def stage_count(optional_coil):
    """:return: stage count of a (possibly absent) multispeed coil; 1 otherwise"""
    coil = multispeed(optional_coil)
    return 1 if coil is None else max(len(coil.stages()), 1)


def multispeed(optional_coil):
    """The three staged coil types share no SDK base class, and a unitary's
    coil accessors hand back an abstract HVACComponent — cast down or the
    ``stages`` collection is invisible.

    :param optional_coil: Optional[HVACComponent], ModelObject, or None
    :return: the concrete multispeed coil, or None
    """
    if optional_coil is None:
        return None

    if hasattr(optional_coil, 'is_initialized'):
        coil = optional_coil.get() if optional_coil.is_initialized() else None
    else:
        coil = optional_coil
    if coil is None:
        return None
    if hasattr(coil, 'stages'):
        return coil

    for cast in ('to_CoilCoolingDXMultiSpeed', 'to_CoilHeatingDXMultiSpeed',
                 'to_CoilHeatingGasMultiStage'):
        if not hasattr(coil, cast):
            continue
        concrete = getattr(coil, cast)()
        if concrete.is_initialized():
            return concrete.get()
    return None


def unitary_children(unitary):
    """Fan + coils held by a unitary system, in supply-path order.
    :return: list of openstudio.model.ModelObject"""
    out = []
    for opt in (unitary.supplyFan(), unitary.coolingCoil(),
                unitary.heatingCoil(), unitary.supplementalHeatingCoil()):
        if opt.is_initialized():
            out.append(opt.get())
    return out


def heating_coil(model, heating_coil_type, schedule, hw_loop=None):
    """Air-loop heating coil by fuel keyword. Hot-water coils are attached to hw_loop.

    :param heating_coil_type: 'Electric', 'Gas'/'NaturalGas', 'Hot Water', 'DX'
    :return: openstudio.model.HVACComponent
    """
    if heating_coil_type in ('Electric', 'Electricity', 'FuelOilNo2'):
        return openstudio.model.CoilHeatingElectric(model, schedule)
    if heating_coil_type in ('Gas', 'NaturalGas'):
        return openstudio.model.CoilHeatingGas(model, schedule)
    if heating_coil_type in ('Hot Water', 'HotWater'):
        if hw_loop is None:
            raise ValueError('a hot water loop is required for a Hot Water heating coil')

        coil = openstudio.model.CoilHeatingWater(model, schedule)
        hw_loop.addDemandBranchForComponent(coil)
        return coil
    if heating_coil_type == 'DX':
        return dx_heating_single_speed(model, schedule)
    raise ValueError(f"'{heating_coil_type}' is not a valid heating coil type")
