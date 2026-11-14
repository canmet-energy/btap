"""Service-water-heating primitives — code-family-neutral.

#192's third cluster. `canmet-energy/campus` carries `upgrade_dhw_plant` and
`install_low_flow_fixtures`; the fixture half lives in
`btap.modeling.loads.scale_water_use` because `WaterUseEquipment` is one of
the eleven space-load pairs, and the plant half is here.

`btap.modeling` had nothing: `hvac/classify.py:299` reads
`to_WaterHeaterMixed()` for FUEL CLASSIFICATION only, which is why a grep for
the class looked like capability and was not. `btap.codes.necb` sets all three
quantities in `shw/efficiency.py`, so this is a lift.

Nothing here holds a value. WHICH efficiency a code requires, and the UA it
derives from a standby-loss standard, stay in `btap.codes`.
"""

from __future__ import annotations

# Measured on OpenStudio 3.11 — the two water-heater classes do not merely
# differ by a missing field, they PARAMETERISE TANK LOSS DIFFERENTLY:
#
#   WaterHeaterMixed        setOffCycleLossCoefficienttoAmbientTemperature
#                           setOnCycleLossCoefficienttoAmbientTemperature
#
#   WaterHeaterStratified   setOffCycleFlueLossCoefficienttoAmbientTemperature
#                           setUniformSkinLossCoefficientperUnitAreatoAmbient-
#                               Temperature
#                           setSkinLossFractiontoZone
#                           setOffCycleFlueLossFractiontoZone
#
# A stratified tank splits flue loss from skin loss and expresses the skin
# term PER UNIT AREA, so a mixed-tank UA in W/K is not the same quantity and
# cannot be written into it. The campus measure reaches for the mixed setters
# with `getattr(heater, name, None)` and skips a stratified heater silently;
# this module refuses it by name and says why, because "your upgrade did not
# reach half your tanks" should not be something a reader has to infer.
_MIXED_ONLY_LOSSES = 'WaterHeaterStratified'


def _class_name(obj):
    return type(obj).__name__


def set_water_heater_efficiency(heater, *, thermal_efficiency=None,
                                audit=None, step='shw'):
    """Burner thermal efficiency on a water heater, as a fraction.

    Declared by BOTH `WaterHeaterMixed` and `WaterHeaterStratified`, so this
    one takes either.

    :returns: 1 if written, 0 if nothing was given.
    """
    if thermal_efficiency is None:
        return 0
    value = float(thermal_efficiency)
    # Measured on 3.11: the setter's bound is > 0, NOT 0-1. It accepts 1.6 and
    # refuses 0.0 and negatives. So the realistic mistake — passing 82 for
    # 0.82 — is accepted silently, and is worth a warning rather than a
    # refusal: a bound the SDK does not enforce is not this primitive's to
    # invent, and a fuel-fired efficiency above 1 is wrong while a
    # heat-pump-style ratio above 1 is not this field's business either way.
    if value > 1.0 and audit is not None:
        audit.warn(step,
                   f'a thermal efficiency of {value} is greater than 1 — if '
                   'this is a percentage, EnergyPlus will read it as a '
                   'ratio and the heater will burn a fraction of the fuel it '
                   'should',
                   target=heater.nameString(),
                   inputs={'thermal_efficiency': value})
    if not heater.setHeaterThermalEfficiency(value):
        raise ValueError(
            f'the model refused a thermal efficiency of {thermal_efficiency} '
            f'on {heater.nameString()!r} — the SDK requires a value greater '
            'than zero')
    if audit is not None:
        audit.info(step, 'water heater thermal efficiency set',
                   target=heater.nameString(),
                   inputs={'class': _class_name(heater),
                           'thermal_efficiency': value})
    return 1


def set_water_heater_losses(heater, *, ua_w_per_k, audit=None, step='shw'):
    """Both ambient-loss coefficients of a MIXED tank, in W/K.

    One value for both the on- and off-cycle terms, which is what a
    standby-loss standard gives: the standard measures the tank at rest and
    does not distinguish the two.

    A `WaterHeaterStratified` is REFUSED rather than skipped — see the table
    at the top of this module. Its loss model is a different parameterisation,
    not a missing field, so there is no honest value to write.

    :returns: 2, the number of coefficients written.
    """
    kind = _class_name(heater)
    if kind == _MIXED_ONLY_LOSSES:
        raise ValueError(
            f'{kind} does not take a mixed-tank UA: it splits flue loss from '
            'skin loss and expresses the skin term per unit area '
            '(setOffCycleFlueLossCoefficienttoAmbientTemperature, '
            'setUniformSkinLossCoefficientperUnitAreatoAmbientTemperature). '
            f'A W/K UA is not that quantity. Set its own fields directly.')

    value = float(ua_w_per_k)
    if not heater.setOffCycleLossCoefficienttoAmbientTemperature(value):
        raise ValueError(
            f'the model refused an off-cycle loss coefficient of {value} on '
            f'{heater.nameString()!r}')
    if not heater.setOnCycleLossCoefficienttoAmbientTemperature(value):
        raise ValueError(
            f'the model refused an on-cycle loss coefficient of {value} on '
            f'{heater.nameString()!r}')
    if audit is not None:
        audit.info(step, 'water heater ambient loss coefficients set',
                   target=heater.nameString(),
                   inputs={'class': kind, 'ua_w_per_k': value})
    return 2


def scale_water_heater_losses(heater, *, factor, audit=None, step='shw'):
    """Scale a MIXED tank's two ambient-loss coefficients by ``factor``.

    The retrofit form — "a new jacket cuts standby loss by thirty percent" —
    where `set_water_heater_losses` is the absolute one. Same restriction and
    the same reason.

    An UNSPECIFIED coefficient is reported and left alone rather than treated
    as zero: scaling an absent value would write a 0.0 that reads as a
    perfectly insulated tank.

    :returns: the number of coefficients scaled.
    """
    kind = _class_name(heater)
    if kind == _MIXED_ONLY_LOSSES:
        raise ValueError(
            f'{kind} does not carry the mixed-tank loss coefficients — see '
            'set_water_heater_losses for what it carries instead.')

    scaled = 0
    for reader, setter in (
            ('offCycleLossCoefficienttoAmbientTemperature',
             'setOffCycleLossCoefficienttoAmbientTemperature'),
            ('onCycleLossCoefficienttoAmbientTemperature',
             'setOnCycleLossCoefficienttoAmbientTemperature')):
        current = getattr(heater, reader)()
        if not current.is_initialized():
            if audit is not None:
                audit.warn(step,
                           f'{reader} is unspecified on this water heater, so '
                           'it was NOT scaled — writing a scaled zero would '
                           'read as a perfectly insulated tank',
                           target=heater.nameString())
            continue
        getattr(heater, setter)(current.get() * factor)
        scaled += 1

    if scaled and audit is not None:
        audit.info(step, 'water heater ambient losses scaled',
                   target=heater.nameString(),
                   inputs={'class': kind, 'factor': factor,
                           'coefficients_scaled': scaled})
    return scaled
