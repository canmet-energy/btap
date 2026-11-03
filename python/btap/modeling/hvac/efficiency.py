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

from btap._compat import sorted_by_name

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
