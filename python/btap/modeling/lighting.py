"""Daylighting-control primitives — code-family-neutral.

The last piece of #192's controls cluster. `canmet-energy/campus` carries
`add_daylight_sensors` and `daylight_and_occupancy_controls`, and
`btap.modeling` had neither — measured, zero hits for `DaylightingControl`
anywhere in the package.

A daylighting control is a vintage marker: a pre-1980 building generally has
none, and the recipe needs to be able to say so by omission rather than by
silence.

Nothing here holds a value. WHICH spaces a code requires controls in, and at
what illuminance, stays in `btap.codes`.
"""

from __future__ import annotations

from btap._compat import opt, sorted_by_name


def lighting_control_types():
    """The control types THIS SDK accepts, from the SDK itself.

    Not a hardcoded list, because the first version of this module was one and
    it was wrong. The EnergyPlus 25.2 IDD that the SDK bundles lists
    `Continuous`, `Stepped` and `ContinuousOff` for `Daylighting:Controls`,
    and OpenStudio's own object does NOT accept the third:

        Energy+.idd     Continuous, Stepped, ContinuousOff
        OpenStudio      None, Continuous, Stepped, Continuous/Off

    Two differences, both silent: OpenStudio spells it with a SLASH, and adds
    a `None`. `setLightingControlType('ContinuousOff')` returns False, so a
    caller validated against the E+ keys would have been refused for a value
    the IDD calls legal.

    `DaylightingControl.validLightingControlTypeValues()` is the authority and
    cannot drift from the installed SDK, which is why this is a function
    rather than a constant. `ControllerOutdoorAir` has NO equivalent helper —
    measured — so `set_economizer`'s list is still taken from the E+ IDD, with
    every key there verified against the setter.
    """
    import openstudio

    return tuple(
        openstudio.model.DaylightingControl.validLightingControlTypeValues())


def add_daylighting_control(space, *, illuminance_setpoint_lux, position,
                            control_type='Continuous',
                            fraction_of_zone=1.0, steps=None,
                            minimum_input_power_fraction=None,
                            minimum_light_output_fraction=None,
                            name=None, audit=None, step='lighting'):
    """A `DaylightingControl` in ``space``, wired as its zone's PRIMARY control.

    `DaylightingControl` is a `SpaceItem` — measured:
    `DaylightingControl -> SpaceItem -> ModelObject` — so it attaches to a
    space, while the FRACTION of the zone it governs lives on the
    `ThermalZone`. Both halves are needed: a control with no zone pointer
    changes nothing in the simulation, which is the quiet failure this
    function exists to prevent.

    :param position: ``(x, y, z)`` in the space's coordinate system, REQUIRED
        and deliberately not defaulted. A daylight sensor's reading is a
        function of where it sits, so a guessed position produces a number
        that looks measured and is invented. The caller knows the work-plane
        height and the distance from the glazing; this function does not.
    :param illuminance_setpoint_lux: the target at the sensor.
    :param control_type: one of `lighting_control_types()`, validated here.
    :param fraction_of_zone: 0-1, the share of the zone's lights this control
        governs.
    :param steps: the number of stepped-control steps. Only meaningful for
        `'Stepped'`, and refused otherwise rather than silently ignored.
    :returns: the `DaylightingControl`.
    """
    import openstudio

    valid = lighting_control_types()
    if control_type not in valid:
        raise ValueError(
            f'{control_type!r} is not a lighting control type this SDK '
            f'accepts. It takes: {", ".join(valid)}. Note that OpenStudio '
            "spells the continuous-off mode 'Continuous/Off', with a slash, "
            "where the EnergyPlus IDD writes 'ContinuousOff'.")
    if steps is not None and control_type != 'Stepped':
        raise ValueError(
            f'steps={steps!r} is only meaningful for Stepped control; '
            f'got control_type={control_type!r}. EnergyPlus would ignore it, '
            'so passing it here is a mistake worth surfacing.')
    if not 0.0 <= float(fraction_of_zone) <= 1.0:
        raise ValueError(
            f'fraction_of_zone must be between 0 and 1; got '
            f'{fraction_of_zone!r}')

    zone = opt(space.thermalZone())
    if zone is None:
        raise ValueError(
            f'space {space.nameString()!r} is in no thermal zone, so a '
            'daylighting control in it would govern nothing — the fraction '
            'controlled lives on the ThermalZone.')

    control = openstudio.model.DaylightingControl(space.model())
    control.setName(name or f'{space.nameString()} Daylighting Control')
    if not control.setSpace(space):
        raise ValueError(
            f'the model refused the daylighting control in '
            f'{space.nameString()!r}')
    x, y, z = position
    control.setPositionXCoordinate(float(x))
    control.setPositionYCoordinate(float(y))
    control.setPositionZCoordinate(float(z))
    control.setIlluminanceSetpoint(float(illuminance_setpoint_lux))
    if not control.setLightingControlType(control_type):
        raise ValueError(
            f'the model refused lighting control type {control_type!r}')
    if steps is not None:
        control.setNumberofSteppedControlSteps(int(steps))
    if minimum_input_power_fraction is not None:
        control.setMinimumInputPowerFractionforContinuousDimmingControl(
            float(minimum_input_power_fraction))
    if minimum_light_output_fraction is not None:
        control.setMinimumLightOutputFractionforContinuousDimmingControl(
            float(minimum_light_output_fraction))

    if not zone.setPrimaryDaylightingControl(control):
        raise ValueError(
            f'the model refused the primary daylighting control on zone '
            f'{zone.nameString()!r}')
    zone.setFractionofZoneControlledbyPrimaryDaylightingControl(
        float(fraction_of_zone))

    if audit is not None:
        audit.info(step, 'daylighting control added',
                   target=space.nameString(),
                   inputs={'zone': zone.nameString(),
                           'illuminance_setpoint_lux':
                               float(illuminance_setpoint_lux),
                           'control_type': control_type,
                           'fraction_of_zone': float(fraction_of_zone),
                           'position': [float(x), float(y), float(z)]})
    return control


def daylighting_controls(model):
    """Every `DaylightingControl` in ``model``, name-ordered."""
    return sorted_by_name(model.getDaylightingControls())
