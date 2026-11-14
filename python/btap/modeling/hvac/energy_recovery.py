"""Air-to-air energy recovery on an outdoor-air system, for ANY family.

#217. This was implemented inside `systems/vav_reheat.py`, which made it the
only one of the TEN families calling `BaseSystem.build_oa_system` that could
carry recovery — 55 of 77 OA-bearing catalogue rows across nine families had
no heat-recovery option at all, including `doas`, where a recovery device is
arguably the expected case, and `mau_ptac`, where an HRV on a make-up air
unit is standard practice in the climate NECB addresses.

Nothing here was ever VAV-specific: both public functions take
`(model, oa_system, config)` and touch no family. Moving them is therefore a
pure relocation, and `tests/modeling/test_energy_recovery_is_family_neutral.py`
pins the two catalogue rows that already use them against a
ForwardTranslator-level baseboard taken before the move.

**`needs_erv` alone is not a recovery request this module can satisfy.**
`validate_energy_recovery` requires all eleven `erv_*` parameters and raises
otherwise, because an exchanger needs effectiveness, frost control, bypass
behaviour and parasitic power — none of which a single boolean supplies. A
caller that sets the flag without them FAILS rather than receiving a device
built from invented defaults.
"""
from __future__ import annotations

import math

import openstudio

from btap._compat import opt

ERV_TYPES = ('Plate', 'Rotary')
ERV_FROST_CONTROLS = (
    'None', 'ExhaustAirRecirculation', 'ExhaustOnly',
    'MinimumExhaustTemperature',
)
ERV_BYPASS_CONTROLS = (
    'BypassWhenWithinEconomizerLimits',
    'BypassWhenOAFlowGreaterThanMinimum',
)
ENERGY_RECOVERY_SOURCE_FEATURE = 'btap_energy_recovery_source'
ENERGY_RECOVERY_SOURCE_CATALOG = 'catalog'


def _number(config, key, *, minimum=None, maximum=None):
    value = config.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{key} must be a finite number')
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f'{key} must be a finite number')
    if minimum is not None and value < minimum:
        raise ValueError(f'{key} must be at least {minimum}')
    if maximum is not None and value > maximum:
        raise ValueError(f'{key} must be at most {maximum}')
    return value


def validate_energy_recovery(config):
    if not config.get('needs_erv'):
        return

    if config.get('erv_heat_exchanger_type') not in ERV_TYPES:
        raise ValueError(
            f"erv_heat_exchanger_type must be one of {ERV_TYPES!r}")
    if config.get('erv_frost_control_type') not in ERV_FROST_CONTROLS:
        raise ValueError(
            f"erv_frost_control_type must be one of {ERV_FROST_CONTROLS!r}")
    if config.get('erv_bypass_control_type') not in ERV_BYPASS_CONTROLS:
        raise ValueError(
            f"erv_bypass_control_type must be one of {ERV_BYPASS_CONTROLS!r}")
    for key in (
            'erv_economizer_lockout',
            'erv_supply_air_outlet_temperature_control'):
        if not isinstance(config.get(key), bool):
            raise ValueError(f'{key} must be a boolean')

    _number(config, 'erv_sensible_effectiveness', minimum=0.0, maximum=1.0)
    _number(config, 'erv_latent_effectiveness', minimum=0.0, maximum=1.0)
    _number(config, 'erv_frost_threshold_temperature',
            minimum=-100.0, maximum=100.0)
    _number(config, 'erv_initial_defrost_time_fraction',
            minimum=0.0, maximum=1.0)
    _number(config, 'erv_defrost_time_fraction_increase_rate', minimum=0.0)
    _number(config, 'erv_nominal_electric_power', minimum=0.0)


def _effectiveness_curve(model, name, value):
    independent = openstudio.model.TableIndependentVariable(model)
    independent.setName(f'{name} Flow Fraction')
    independent.setInterpolationMethod('Linear')
    independent.setExtrapolationMethod('Constant')
    independent.setMinimumValue(0.0)
    independent.setMaximumValue(1.0)
    independent.setUnitType('Dimensionless')
    independent.addValue(0.75)
    independent.addValue(1.0)
    independent.additionalProperties().setFeature(
        ENERGY_RECOVERY_SOURCE_FEATURE, ENERGY_RECOVERY_SOURCE_CATALOG)

    table = openstudio.model.TableLookup(model)
    table.setName(name)
    table.addIndependentVariable(independent)
    table.setNormalizationMethod('DivisorOnly')
    table.setNormalizationDivisor(value if value > 0.0 else 1.0)
    table.setMinimumOutput(0.0)
    table.setMaximumOutput(1.0)
    table.setOutputUnitType('Dimensionless')
    table.addOutputValue(value)
    table.addOutputValue(value)
    return table


def add_energy_recovery(model, oa_system, config, *, name):
    """Attach one catalog-selected exchanger across the OA and relief streams."""
    existing = [
        opt(component.to_HeatExchangerAirToAirSensibleAndLatent())
        for component in oa_system.oaComponents()
        if component.to_HeatExchangerAirToAirSensibleAndLatent().is_initialized()
    ]
    if existing:
        return existing[0]

    sensible = float(config['erv_sensible_effectiveness'])
    latent = float(config['erv_latent_effectiveness'])
    exchanger = openstudio.model.HeatExchangerAirToAirSensibleAndLatent(model)
    exchanger.setName(
        f"{name} {config['erv_heat_exchanger_type']} "
        f"{'ERV' if latent > 0.0 else 'HRV'}")
    exchanger.setHeatExchangerType(config['erv_heat_exchanger_type'])
    exchanger.setEconomizerLockout(config['erv_economizer_lockout'])
    exchanger.setSupplyAirOutletTemperatureControl(
        config['erv_supply_air_outlet_temperature_control'])
    exchanger.setFrostControlType(config['erv_frost_control_type'])
    exchanger.setThresholdTemperature(
        float(config['erv_frost_threshold_temperature']))
    exchanger.setInitialDefrostTimeFraction(
        float(config['erv_initial_defrost_time_fraction']))
    exchanger.setRateofDefrostTimeFractionIncrease(
        float(config['erv_defrost_time_fraction_increase_rate']))
    exchanger.setNominalElectricPower(
        float(config['erv_nominal_electric_power']))
    for load in ('Heating', 'Cooling'):
        exchanger_method = (
            f'setSensibleEffectivenessat100{load}AirFlow')
        getattr(exchanger, exchanger_method)(sensible)
        getattr(
            exchanger,
            f'setSensibleEffectivenessof{load}AirFlowCurve')(
                _effectiveness_curve(
                    model, f'{name} Sensible {load} Effectiveness',
                    sensible))
        getattr(
            exchanger, f'setLatentEffectivenessat100{load}AirFlow')(latent)
        getattr(
            exchanger,
            f'setLatentEffectivenessof{load}AirFlowCurve')(
                _effectiveness_curve(
                    model, f'{name} Latent {load} Effectiveness',
                    latent))
    exchanger.additionalProperties().setFeature(
        ENERGY_RECOVERY_SOURCE_FEATURE, ENERGY_RECOVERY_SOURCE_CATALOG)
    # #217 made this reachable from ELEVEN families instead of one, so the
    # crash surface grew with it. A bare `.get()` on an empty SDK optional
    # SEGFAULTS for 615 of the 617 `Optional*` types — it does not raise — and
    # these four accessors all return `boost::optional` (checked in
    # `AirLoopHVACOutdoorAirSystem.hpp` and `AirToAirComponent.hpp`, not
    # assumed). An OA system that is not attached to a supply node has none of
    # these nodes, so the guard turns "interpreter dies somewhere inside a
    # builder" into a sentence naming the missing node.
    nodes = {
        'outboard OA': opt(oa_system.outboardOANode()),
        'mixed air': opt(oa_system.mixedAirModelObject()),
        'return air': opt(oa_system.returnAirModelObject()),
    }
    missing = sorted(k for k, v in nodes.items() if v is None)
    if missing:
        raise RuntimeError(
            f'cannot add energy recovery to {name!r}: the outdoor-air system '
            f"has no {', '.join(missing)} node. An OA system has these only "
            'once it is attached to an air loop supply node — attach it '
            'first, or go through BaseSystem.attach_oa_system.')

    outboard_oa_node = nodes['outboard OA']
    exchanger.addToNode(outboard_oa_node)

    mixed_air_node = opt(nodes['mixed air'].to_Node())
    pretreat = openstudio.model.SetpointManagerOutdoorAirPretreat(model)
    pretreat.setName(f'{name} ERV Pretreat Setpoint Manager')
    pretreat.setMinimumSetpointTemperature(-99.0)
    pretreat.setMaximumSetpointTemperature(99.0)
    pretreat.setMinimumSetpointHumidityRatio(0.00001)
    pretreat.setMaximumSetpointHumidityRatio(1.0)
    pretreat.setReferenceSetpointNode(mixed_air_node)
    pretreat.setMixedAirStreamNode(mixed_air_node)
    pretreat.setOutdoorAirStreamNode(outboard_oa_node)
    pretreat.setReturnAirStreamNode(opt(nodes['return air'].to_Node()))
    primary_outlet = opt(exchanger.primaryAirOutletModelObject())
    if primary_outlet is None:
        raise RuntimeError(
            f'cannot add energy recovery to {name!r}: the exchanger has no '
            'primary air outlet after being added to the outdoor-air node.')
    pretreat.addToNode(opt(primary_outlet.to_Node()))

    oa_system.getControllerOutdoorAir().setHeatRecoveryBypassControlType(
        config['erv_bypass_control_type'])
    return exchanger


# ---------------- zone-level recovery ----------------

def add_zone_energy_recovery(model, zone, *, name=None):
    """One `ZoneHVAC:EnergyRecoveryVentilator` on ``zone``.

    The OTHER recovery mechanism. `add_energy_recovery` above puts an
    exchanger on an air loop's outdoor-air stream, which needs a loop; TWELVE
    families build no outdoor air at all — `baseboards`, `unit_heaters`,
    `vrf`, `wshp`, `zone_terminal` among them — and for those the device is a
    zone ERV, which brings its own supply and exhaust fans and is that zone's
    ventilation source rather than an accessory to a loop.

    Lifted from `systems/zone_ervs.py` UNCHANGED, so the standalone
    "Zone ERVs" catalogue row and this option build the same device. That
    family now calls this.

    **It inherits the SDK's defaults, and they are worth knowing**: sensible
    0.76, latent 0.68, `nominalElectricPower` 0.0 — no fan parasitic — and
    `frostControlType` 'None', which in the climate NECB addresses is
    questionable where the central path explicitly sets 'ExhaustOnly' at
    -23.3 C. Those defaults are PRE-EXISTING behaviour of the shipped row, so
    they are preserved here rather than silently changed by the refactor that
    made the device reusable. Correcting them is an adjudicated change to that
    row's output, not a side effect of this one.
    """
    label = name or zone.nameString()

    supply_fan = openstudio.model.FanOnOff(model)
    supply_fan.setName(f'{label} ERV Supply Fan')
    exhaust_fan = openstudio.model.FanOnOff(model)
    exhaust_fan.setName(f'{label} ERV Exhaust Fan')

    controller = openstudio.model.ZoneHVACEnergyRecoveryVentilatorController(
        model)
    heat_exchanger = openstudio.model.HeatExchangerAirToAirSensibleAndLatent(
        model)
    heat_exchanger.setName(f'{label} ERV HX')
    heat_exchanger.setSupplyAirOutletTemperatureControl(False)
    # NOT tagged with ENERGY_RECOVERY_SOURCE_FEATURE, though the central path
    # tags its exchanger. The shipped 'Zone ERVs' row never did, and the point
    # of lifting this function out was to make the device REUSABLE, not to
    # change what that row emits — the central move was proven byte-identical
    # and this one is held to the same standard. Whether a zone ERV should
    # carry the tag is a separate question; `teardown` reads it on
    # `TableIndependentVariable`, which this device does not create.

    erv = openstudio.model.ZoneHVACEnergyRecoveryVentilator(
        model, heat_exchanger, supply_fan, exhaust_fan)
    erv.setName(f'{label} ERV')
    erv.setController(controller)
    erv.addToThermalZone(zone)
    return erv
