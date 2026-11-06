"""Fan and pump efficiency primitives — code-family-neutral.

#192's first cluster. `canmet-energy/campus` carries three measures here —
`improve_motor_efficiency`, `improve_fan_and_pump_total_efficiency` and
`fan_and_pump_motor_efficiency_upgrade` — and `btap.modeling` had no setter
for either quantity, while `btap.codes.necb` set both in six places.

A nameplate efficiency is not device physics. The stock plan's phase 3
deliberately leaves the defrost EIR curves and heat-recovery time constants
alone because those describe how a machine BEHAVES; a motor efficiency is a
rating that a retrofit changes and a vintage determines, and a 1955 fan motor
against a 2015 premium-efficiency one is the kind of difference the recipe
exists to express.

Nothing here holds a value. WHICH efficiency a code requires stays in
`btap.codes`.
"""

from __future__ import annotations

from btap._compat import opt, sorted_by_name

# Measured on OpenStudio 3.11, by reading the public headers and then probing
# the SWIG classes — not inferred:
#
#                          setFanTotalEfficiency  setFanEfficiency  setMotorEfficiency
#   FanConstantVolume      yes                    yes (deprecated)  yes
#   FanVariableVolume      yes                    yes (deprecated)  yes
#   FanOnOff               yes                    yes (deprecated)  yes
#   FanSystemModel         yes                    NO                yes
#   FanZoneExhaust         yes                    yes (deprecated)  NO
#   FanComponentModel      NO                     NO                NO
#
# `setFanEfficiency` is documented in FanConstantVolume.hpp as "Deprecated,
# forwards to setFanTotalEfficiency", so there is no class that needs the old
# name and every scalar class takes the new one. That matters because
# `codes/necb/hvac/reference.py` guarded with
# `hasattr(fan, 'setFanTotalEfficiency')` and fell back to `setFanEfficiency`:
# dead for all five scalar classes, and an AttributeError for the sixth, which
# has neither. The guard's premise was false.
_NO_MOTOR_EFFICIENCY = ('FanZoneExhaust',)

#: The accessor each fan class uses for design pressure rise. `FanSystemModel`
#: spells it DIFFERENTLY (`designPressureRise`), and a duck-typed
#: `getattr(fan, 'pressureRise')` would silently skip it — the same trap
#: `_fans` already documents for motor efficiency. All of these return a plain
#: `double`, NOT `boost::optional`, so `opt()` must not be applied: on a plain
#: double it raises. Verified in the C++ headers, class by class.
_PRESSURE_RISE_ACCESSOR = {
    'FanConstantVolume': ('pressureRise', 'setPressureRise'),
    'FanVariableVolume': ('pressureRise', 'setPressureRise'),
    'FanOnOff': ('pressureRise', 'setPressureRise'),
    'FanZoneExhaust': ('pressureRise', 'setPressureRise'),
    'FanSystemModel': ('designPressureRise', 'setDesignPressureRise'),
}
_CURVE_BASED = ('FanComponentModel',)


def _class_name(obj):
    return type(obj).__name__


def set_fan_efficiency(fan, *, total_efficiency=None, motor_efficiency=None,
                       audit=None, step='hvac'):
    """Fan total and/or motor efficiency, as fractions.

    :param total_efficiency: the combined fan-and-motor efficiency, 0-1.
        Always written through `setFanTotalEfficiency`; the deprecated
        `setFanEfficiency` alias is never used.
    :param motor_efficiency: the motor's own efficiency, 0-1. `FanZoneExhaust`
        has no such field and is refused rather than silently skipped.
    :returns: the number of fields written.
    """
    kind = _class_name(fan)
    if kind in _CURVE_BASED:
        raise ValueError(
            f"{kind} carries no scalar efficiency: it is a curve-based fan "
            'model whose surface is setMaximumFanStaticEfficiency, '
            'setMaximumMotorEfficiencyCurve and '
            'setEulerNumberatMaximumFanStaticEfficiency. Setting a scalar on '
            'it is not a rating change but a change of device model, which '
            'this primitive does not make.')

    written = 0
    if total_efficiency is not None:
        if not fan.setFanTotalEfficiency(float(total_efficiency)):
            raise ValueError(
                f'the model refused a fan total efficiency of '
                f'{total_efficiency} on {fan.nameString()!r} — EnergyPlus '
                'takes a fraction between 0 and 1')
        written += 1
    if motor_efficiency is not None:
        if kind in _NO_MOTOR_EFFICIENCY:
            raise ValueError(
                f'{kind} has no motor-efficiency field — its total efficiency '
                'already carries the motor. Pass total_efficiency instead.')
        if not fan.setMotorEfficiency(float(motor_efficiency)):
            raise ValueError(
                f'the model refused a motor efficiency of {motor_efficiency} '
                f'on {fan.nameString()!r} — EnergyPlus takes a fraction '
                'between 0 and 1')
        written += 1

    if written and audit is not None:
        audit.info(step, 'fan efficiency set', target=fan.nameString(),
                   inputs={'class': kind,
                           'total_efficiency': total_efficiency,
                           'motor_efficiency': motor_efficiency})
    return written


def set_pump_efficiency(pump, *, motor_efficiency=None, audit=None,
                        step='hvac'):
    """A pump's motor efficiency, as a fraction.

    All four pump classes — `PumpConstantSpeed`, `PumpVariableSpeed`,
    `HeaderedPumpsConstantSpeed` and `HeaderedPumpsVariableSpeed` — declare
    `setMotorEfficiency` and none declares a fan-style total efficiency, which
    is why this is a separate function rather than a mode of the fan one.

    :returns: the number of fields written.
    """
    if motor_efficiency is None:
        return 0
    if not pump.setMotorEfficiency(float(motor_efficiency)):
        raise ValueError(
            f'the model refused a motor efficiency of {motor_efficiency} on '
            f'{pump.nameString()!r} — EnergyPlus takes a fraction between 0 '
            'and 1')
    if audit is not None:
        audit.info(step, 'pump motor efficiency set', target=pump.nameString(),
                   inputs={'class': _class_name(pump),
                           'motor_efficiency': motor_efficiency})
    return 1


#: The accessor each fan class uses for design air flow. Differs by class
#: exactly as pressure does — `FanSystemModel` renames this one too.
#:
#: NOTE THE ASYMMETRY: pressure returns a plain `double`, flow returns
#: `boost::optional<double>` because it is AUTOSIZABLE. So `opt()` is required
#: here and would RAISE on pressure. Verified in the C++ headers class by
#: class; guessing either way is the D-79 trap.
_FLOW_ACCESSOR = {
    'FanConstantVolume': 'maximumFlowRate',
    'FanVariableVolume': 'maximumFlowRate',
    'FanOnOff': 'maximumFlowRate',
    'FanZoneExhaust': 'maximumFlowRate',
    'FanSystemModel': 'designMaximumAirFlowRate',
}


def fan_design_flow(fan):
    """A fan's design air flow in m3/s, or None when it is autosized.

    None is the honest answer for an autosized fan: there is no authored flow
    to weight by, and inventing one would be worse than declining to weight.
    """
    accessor = _FLOW_ACCESSOR.get(_class_name(fan))
    if accessor is None:
        return None
    value = getattr(fan, accessor)()
    return float(opt(value)) if value.is_initialized() else None


def fan_pressure_rise(fan):
    """A fan's design pressure rise in Pa, or None if the class has no scalar.

    `FanComponentModel` legitimately returns None: its pressure is in curves.
    """
    accessors = _PRESSURE_RISE_ACCESSOR.get(_class_name(fan))
    if accessors is None:
        return None
    return float(getattr(fan, accessors[0])())


def set_fan_pressure_rise(fan, pressure_rise_pa, *, audit=None, step='hvac'):
    """Set a fan's design pressure rise, in Pa.

    :returns: the number of fields written (0 for a curve-based fan).
    """
    kind = _class_name(fan)
    if kind in _CURVE_BASED:
        raise ValueError(
            f'{kind} carries no scalar pressure rise: its pressure is in '
            'curves, and writing a scalar would change the device model '
            'rather than its rating.')
    accessors = _PRESSURE_RISE_ACCESSOR.get(kind)
    if accessors is None:
        raise ValueError(f'no pressure-rise accessor known for {kind}')

    before = float(getattr(fan, accessors[0])())
    if not getattr(fan, accessors[1])(float(pressure_rise_pa)):
        raise ValueError(
            f'the model refused a pressure rise of {pressure_rise_pa} Pa on '
            f'{fan.nameString()!r}')
    if audit is not None:
        audit.info(step, 'fan design pressure rise set',
                   target=fan.nameString(), value=float(pressure_rise_pa),
                   inputs={'was_pa': before, 'class': kind})
    return 1


def set_fan_pressure_rise_in_model(model, pressure_rise_pa, *, audit=None,
                                   step='hvac'):
    """`set_fan_pressure_rise` across every scalar fan in ``model``.

    Curve-based fans are SKIPPED with a warning, matching
    `set_fan_efficiency_in_model`: one detailed fan does not stop the other
    forty being set.
    """
    getters = (model.getFanConstantVolumes, model.getFanVariableVolumes,
               model.getFanOnOffs, model.getFanSystemModels,
               model.getFanZoneExhausts)
    written = 0
    for getter in getters:
        for fan in sorted_by_name(getter()):
            written += set_fan_pressure_rise(
                fan, pressure_rise_pa, audit=audit, step=step)
    detailed = model.getFanComponentModels()
    if detailed and audit is not None:
        audit.warn(step,
                   f'{len(detailed)} FanComponentModel fan(s) SKIPPED — '
                   'pressure rise is in their curves, not a scalar field',
                   target='model')
    return written


def set_fan_pressure_rise_by_class_in_model(model, by_class, *, audit=None,
                                            step='hvac'):
    """Apply a pressure rise PER FAN CLASS, from `{class name: Pa}`.

    One value for every fan loses fan energy, because fan power is
    FLOW-WEIGHTED: a building's constant-volume supply fans move far more air
    than its unit-heater fans, so averaging a 100-658 Pa spread down to one
    number drops the supply fans and raises the small ones. Measured on
    `Office_pre-1960` (#202): the global average cost 138 GJ/yr, 62% of the
    whole remaining round-trip gap.

    A class absent from `by_class` is LEFT ALONE rather than defaulted — the
    recipe said nothing about it, and inventing a value would be the silent
    widening this split exists to avoid.
    """
    getters = {
        'FanConstantVolume': model.getFanConstantVolumes,
        'FanVariableVolume': model.getFanVariableVolumes,
        'FanOnOff': model.getFanOnOffs,
        'FanSystemModel': model.getFanSystemModels,
        'FanZoneExhaust': model.getFanZoneExhausts,
    }
    unknown = sorted(set(by_class) - set(getters))
    if unknown:
        raise ValueError(
            f"no fan class named {', '.join(unknown)} — expected one of "
            f"{', '.join(sorted(getters))}")

    written = 0
    for name, pressure_pa in sorted(by_class.items()):
        for fan in sorted_by_name(getters[name]()):
            written += set_fan_pressure_rise(
                fan, pressure_pa, audit=audit, step=step)
    detailed = model.getFanComponentModels()
    if detailed and audit is not None:
        audit.warn(step,
                   f'{len(detailed)} FanComponentModel fan(s) SKIPPED — '
                   'pressure rise is in their curves, not a scalar field',
                   target='model')
    return written


def set_fan_efficiency_in_model(model, *, total_efficiency=None,
                                motor_efficiency=None, audit=None,
                                step='hvac'):
    """`set_fan_efficiency` across every scalar fan in ``model``.

    The measures operate model-wide, which is the retrofit shape: "every fan
    in this building is now a premium-efficiency motor".

    A `FanComponentModel` is SKIPPED with a warning rather than refused, so one
    detailed fan does not stop an upgrade to the other forty. A caller naming
    one fan explicitly still gets the refusal, because then the curve-based
    model is what they asked for.
    """
    getters = (model.getFanConstantVolumes, model.getFanVariableVolumes,
               model.getFanOnOffs, model.getFanSystemModels,
               model.getFanZoneExhausts)
    written = 0
    for getter in getters:
        for fan in sorted_by_name(getter()):
            motor = (None if _class_name(fan) in _NO_MOTOR_EFFICIENCY
                     else motor_efficiency)
            written += set_fan_efficiency(
                fan, total_efficiency=total_efficiency,
                motor_efficiency=motor, audit=audit, step=step)
    detailed = model.getFanComponentModels()
    if detailed and audit is not None:
        audit.warn(step,
                   f'{len(detailed)} curve-based FanComponentModel fan(s) '
                   'SKIPPED — a scalar efficiency does not apply to them, so '
                   'their performance is unchanged by this upgrade',
                   inputs={'skipped': [f.nameString()
                                       for f in sorted_by_name(detailed)]})
    return written


def set_pump_efficiency_in_model(model, *, motor_efficiency=None, audit=None,
                                 step='hvac'):
    """`set_pump_efficiency` across every pump in ``model``."""
    if motor_efficiency is None:
        return 0
    written = 0
    for getter in (model.getPumpConstantSpeeds, model.getPumpVariableSpeeds,
                   model.getHeaderedPumpsConstantSpeeds,
                   model.getHeaderedPumpsVariableSpeeds):
        for pump in sorted_by_name(getter()):
            written += set_pump_efficiency(pump,
                                           motor_efficiency=motor_efficiency,
                                           audit=audit, step=step)
    return written
