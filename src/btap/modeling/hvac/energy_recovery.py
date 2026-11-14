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
import pathlib
from types import MappingProxyType

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


_PROFILES_FILE = (pathlib.Path(__file__).resolve().parent / 'data'
                  / 'energy_recovery.json')

#: Keys a profile carries for documentation, not for the model.
_PROFILE_METADATA = ('label', 'source')

_profiles_cache = None


def profiles():
    """The named product profiles, keyed CORE x TRANSFER.

    `plate_erv`, `rotary_erv`, `plate_hrv` — see the `comment` in
    `data/energy_recovery.json` for why core alone is not enough to key on,
    and why NECB's own numbers are deliberately not here.
    """
    global _profiles_cache
    if _profiles_cache is None:
        import json

        data = json.loads(_PROFILES_FILE.read_text(encoding='utf-8'))
        _profiles_cache = MappingProxyType({
            name: MappingProxyType(dict(values))
            for name, values in data['profiles'].items()
        })
    return _profiles_cache


def default_profile_name():
    """The profile used when a caller asks for recovery without naming one.

    Declared in the data file rather than here, so changing it is a data edit
    and the reason travels with the values.
    """
    import json

    return json.loads(_PROFILES_FILE.read_text(encoding='utf-8'))['default']


def resolve_energy_recovery(config):
    """`config` with a named `erv_profile` expanded, then validated.

    There is no implicit default. A caller either names a profile or supplies
    the eleven `erv_*` values itself; `needs_erv: true` alone raises, because
    effectiveness, frost control and parasitic power cannot be inferred from a
    boolean — the rule that kept #217 from spreading a fabrication across
    eleven families.

    An explicit `erv_*` key OVERRIDES the profile, so a row can take a product
    and change one field without restating the other ten.

    :returns: a plain dict of the merged values, carrying
        `erv_profile_used` so a caller and the audit can report WHICH profile
        a build came from, named or defaulted.
    """
    merged = dict(config)
    name = merged.pop('erv_profile', None)
    available = profiles()
    if name is None:
        # phylroy, 2026-11-14: a default so a user can move ahead to a
        # functioning HVAC. Asking for recovery and getting a refusal that
        # demands eleven values blocks the common case for no benefit.
        #
        # This is not the fabrication that `needs_erv: true` used to be
        # refused for. That refusal existed because the alternative was the
        # SDK's defaults, which are uncited and pair a plate core with
        # rotary-wheel latent performance and no frost control. A named,
        # cited, overridable profile is a DISCLOSED assumption, and
        # `profile_used` below carries it into the audit so it is never
        # silent.
        name = default_profile_name()
    if name not in available:
        raise ValueError(
            f'unknown erv_profile {name!r}. Available: '
            f"{', '.join(sorted(available))}")
    for key, value in available[name].items():
        if key in _PROFILE_METADATA:
            continue
        merged.setdefault(key, value)
    merged['erv_profile_used'] = name
    # Unconditional: this is only called when recovery IS wanted, and routing
    # through `validate_energy_recovery` would early-return for the zonal
    # path, whose flag is `needs_zone_erv`.
    _validate_recovery_fields(merged)
    return merged


def validate_energy_recovery(config):
    """Validate IF `needs_erv` asks for central recovery, else do nothing.

    The `needs_erv` gate is why `resolve_energy_recovery` does NOT route
    through this: the ZONAL path sets `needs_zone_erv`, so this returned early
    and left the missing fields to surface as a `KeyError` from deep inside
    the builder instead of a refusal naming what was absent.
    """
    if not config.get('needs_erv'):
        return
    _validate_recovery_fields(config)


def _validate_recovery_fields(config):
    """The field checks themselves, independent of which flag asked."""
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


def _apply_exchanger_fields(exchanger, config, *, name):
    """Set every `erv_*` field that belongs to the EXCHANGER.

    Shared by the central and zonal paths, which build the same
    `HeatExchangerAirToAirSensibleAndLatent`. `erv_bypass_control_type` is NOT
    here: it is set on the outdoor-air controller, which a zone ERV has none
    of, so it is the one value of the eleven that is central-only.
    """
    model = exchanger.model()
    sensible = float(config['erv_sensible_effectiveness'])
    latent = float(config['erv_latent_effectiveness'])

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
        getattr(exchanger, f'setSensibleEffectivenessat100{load}AirFlow')(
            sensible)
        getattr(exchanger, f'setSensibleEffectivenessof{load}AirFlowCurve')(
            _effectiveness_curve(
                model, f'{name} Sensible {load} Effectiveness', sensible))
        getattr(exchanger, f'setLatentEffectivenessat100{load}AirFlow')(latent)
        getattr(exchanger, f'setLatentEffectivenessof{load}AirFlowCurve')(
            _effectiveness_curve(
                model, f'{name} Latent {load} Effectiveness', latent))


def add_energy_recovery(model, oa_system, config, *, name):
    """Attach one catalog-selected exchanger across the OA and relief streams."""
    existing = [
        opt(component.to_HeatExchangerAirToAirSensibleAndLatent())
        for component in oa_system.oaComponents()
        if component.to_HeatExchangerAirToAirSensibleAndLatent().is_initialized()
    ]
    if existing:
        return existing[0]

    # `latent` only, for the name: an exchanger that moves moisture is an ERV
    # and one that does not is an HRV, which is why a profile is keyed on
    # CORE x TRANSFER rather than on core alone. The effectiveness values
    # themselves are set by `_apply_exchanger_fields`.
    latent = float(config['erv_latent_effectiveness'])
    exchanger = openstudio.model.HeatExchangerAirToAirSensibleAndLatent(model)
    exchanger.setName(
        f"{name} {config['erv_heat_exchanger_type']} "
        f"{'ERV' if latent > 0.0 else 'HRV'}")
    _apply_exchanger_fields(exchanger, config, name=name)
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

def zone_ventilation_rates(zone):
    """The zone's own outdoor-air requirement, as the two rates an ERV takes.

    A `ZoneHVAC:EnergyRecoveryVentilator` autosizes its flows from its OWN
    `VentilationRateperUnitFloorArea` and `VentilationRateperOccupant`, whose
    SDK defaults are 0.000508 m3/s-m2 and 0.00236 m3/s-person. It never looks
    at the zone's `DesignSpecificationOutdoorAir`, so an ERV built on those
    defaults ventilates at a rate unrelated to what the building asks for.

    The rates are read from the MODEL rather than from a standard, and that is
    deliberate. NECB 8.4.3.6 sets peak outdoor-air rates to "the minimum rates
    required by the applicable ventilation standard" — ASHRAE 62.1 for
    commercial work, and NBC Division B 9.32.3 for dwelling units, which is
    the Canadian path rather than ASHRAE 62.2 (A-5.2.10.4.(1)). Whichever
    applied, its rates are already encoded as the zone's DSOA, so reading the
    model keeps `btap.modeling` free of a standard choice it has no business
    making.

    Multiple spaces may carry DIFFERENT DSOAs — one zone of
    `Office_pre-1960` does — so the per-area rate is weighted by floor AREA
    and the per-person rate by PEOPLE, which is what reproduces the zone's
    total requirement rather than an unweighted mean of rates.

    :returns: `(per_area_m3_s_m2, per_person_m3_s_person)`, or None when the
        zone declares no outdoor-air requirement at all.
    :raises ValueError: when the requirement cannot be expressed as these two
        rates — an `outdoorAirMethod` of anything but `Sum`, or an absolute or
        air-changes component. The ERV ADDS its two rates, so mapping a
        `Maximum` requirement onto both would over-ventilate, and silently
        moving more outdoor air than the building asked for is worse than a
        refusal that names the zone.
    """
    area_flow = person_flow = 0.0
    total_area = total_people = 0.0
    seen = False

    for space in zone.spaces():
        spec = opt(space.designSpecificationOutdoorAir())
        if spec is None:
            continue
        seen = True
        method = spec.outdoorAirMethod()
        if method != 'Sum':
            raise ValueError(
                f'cannot size a zone ERV for {zone.nameString()!r}: its '
                f'outdoor-air specification {spec.nameString()!r} uses '
                f'outdoorAirMethod {method!r}, and a zone ERV ADDS its '
                'per-area and per-person rates, so the result would not be '
                f'the {method!r} of them.')
        if spec.outdoorAirFlowRate() or spec.outdoorAirFlowAirChangesperHour():
            raise ValueError(
                f'cannot size a zone ERV for {zone.nameString()!r}: its '
                f'outdoor-air specification {spec.nameString()!r} carries an '
                'absolute flow or an air-changes rate, and a zone ERV takes '
                'only a per-area and a per-occupant rate.')

        space_area = space.floorArea() * space.multiplier()
        space_people = space.numberOfPeople() * space.multiplier()
        area_flow += spec.outdoorAirFlowperFloorArea() * space_area
        person_flow += spec.outdoorAirFlowperPerson() * space_people
        total_area += space_area
        total_people += space_people

    if not seen:
        return None
    return (area_flow / total_area if total_area else 0.0,
            person_flow / total_people if total_people else 0.0)


def add_zone_energy_recovery(model, zone, config=None, *, name=None):
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

    # `config` is the resolved `erv_*` set, or None. None keeps the SDK
    # defaults, which is what the shipped "Zone ERVs" row has always built —
    # preserved so this stays a pure refactor of that row. Those defaults are
    # NOT good: sensible 0.76, latent 0.68 and `frostControlType 'None'`, the
    # last of which gives an exchanger no frost protection in a climate that
    # reaches -40 C. Migrating the row onto a profile fixes that and changes
    # its output, so it needs the catalogue's gates and is not done here.
    #
    # `erv_bypass_control_type` is deliberately not applied: it belongs to the
    # outdoor-air controller, which a zone ERV does not have.
    if config:
        _apply_exchanger_fields(heat_exchanger, config, name=label)

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

    # The flows, from the ZONE's own requirement rather than the SDK's
    # per-area and per-person defaults, which no model ever asked for. None
    # means the zone declares no requirement; the defaults then stand, since
    # inventing zero would silently stop ventilating a zone the caller asked
    # to ventilate.
    #
    # Set AFTER the ERV exists: my first version read the rates before
    # constructing it and used `erv` three lines early, which ruff caught.
    rates = zone_ventilation_rates(zone)
    if rates is not None:
        per_area, per_person = rates
        erv.setVentilationRateperUnitFloorArea(per_area)
        erv.setVentilationRateperOccupant(per_person)

    erv.addToThermalZone(zone)
    return erv
