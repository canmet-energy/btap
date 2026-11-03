"""Ventilation control primitives — code-family-neutral.

Phase 0 of the stock plan listed `ecm_dcv` among the four load primitives that
existed ONLY inside `btap.codes.necb`, so a model authored through
`btap.modeling` alone could not turn demand-controlled ventilation on at all.
This module is that lift. Nothing here knows what NECB is and nothing holds a
value: the decision of WHETHER the reference gets DCV, and which outdoor-air
method it inherits, stays in `codes` (D-54) and calls down.
"""

from __future__ import annotations

from btap._compat import opt


def set_demand_controlled_ventilation(air_loop, *, enabled=True,
                                      system_outdoor_air_method=None,
                                      audit=None, step='ventilation'):
    """Turn demand-controlled ventilation on (or off) for one air loop.

    The control lives three objects down from the loop — outdoor-air system,
    then its controller, then that controller's mechanical-ventilation
    controller — and the first hop is OPTIONAL: an air loop with no
    outdoor-air system has nowhere to carry the setting. That is not an error,
    so this returns None rather than raising. A loop with no OA system is a
    recirculating loop, and DCV is meaningless on one.

    `airLoopHVACOutdoorAirSystem()` returns
    `boost::optional<AirLoopHVACOutdoorAirSystem>`, which is a D-79
    crash-family optional, so it goes through `opt()` rather than a bare
    `.get()`.

    :param enabled: False clears the flag, which is NOT the same as leaving it
        alone — the caller is asserting that this loop must not have DCV.
    :param system_outdoor_air_method: set only when given. EnergyPlus carries
        several (`'ZoneSum'`, `'VentilationRateProcedure'`, …) and the choice
        is a code question, not a modelling one, so this module does not pick
        one.
    :returns: the ``ControllerMechanicalVentilation``, or None when the loop
        has no outdoor-air system.
    """
    oa_system = opt(air_loop.airLoopHVACOutdoorAirSystem())
    if oa_system is None:
        if audit is not None:
            audit.info(step,
                       'no outdoor-air system on this air loop — '
                       'demand-controlled ventilation not applicable',
                       target=air_loop.nameString())
        return None

    controller = oa_system.getControllerOutdoorAir()
    mech = controller.controllerMechanicalVentilation()

    # A FixedMinimum outdoor-air FLOOR can make this a silent no-op: DCV
    # cannot reduce ventilation below a hard minimum, so the flag goes on and
    # nothing changes in the simulation. `canmet-energy/campus`'s
    # demand_controlled_ventilation measure warns about exactly this, and a
    # measure that reports no saving for an unstated reason is worse than one
    # that refuses.
    if enabled:
        floor = opt(controller.minimumOutdoorAirFlowRate())
        if (controller.getMinimumLimitType() == 'FixedMinimum'
                and floor is not None and floor > 0):
            if audit is not None:
                audit.warn(step,
                           'demand-controlled ventilation turned on while the '
                           'outdoor-air controller holds a FixedMinimum floor '
                           '— DCV cannot reduce ventilation below it, so this '
                           'may change nothing',
                           target=air_loop.nameString(),
                           inputs={'minimum_outdoor_air_m3_per_s': floor,
                                   'minimum_limit_type': 'FixedMinimum'})

    # The setters return a bool and CAN fail; treating a false as success is
    # how a measure reports work it did not do.
    if not mech.setDemandControlledVentilation(bool(enabled)):
        raise ValueError(
            'the model refused setDemandControlledVentilation('
            f'{bool(enabled)}) on {air_loop.nameString()!r}')
    if system_outdoor_air_method is not None:
        if not mech.setSystemOutdoorAirMethod(system_outdoor_air_method):
            raise ValueError(
                'the model refused system outdoor-air method '
                f'{system_outdoor_air_method!r} on '
                f'{air_loop.nameString()!r} — EnergyPlus accepts only its own '
                'keys, such as ZoneSum or VentilationRateProcedure')
    if audit is not None:
        audit.info(step,
                   'demand-controlled ventilation '
                   f"{'on' if enabled else 'off'}",
                   target=air_loop.nameString(),
                   inputs={'system_outdoor_air_method':
                           mech.systemOutdoorAirMethod()})
    return mech


# From the EnergyPlus 25.2 IDD the SDK itself bundles at
# `$SDK/EnergyPlus/Energy+.idd` — Controller:OutdoorAir field A6. Validated
# here rather than left to the setter, because the SDK returns False for an
# unknown key and a caller who mistyped `DifferentialDrybulb` would otherwise
# get a silent NoEconomizer.
ECONOMIZER_CONTROL_TYPES = (
    'FixedDryBulb',
    'FixedEnthalpy',
    'DifferentialDryBulb',
    'DifferentialEnthalpy',
    'FixedDewPointAndDryBulb',
    'ElectronicEnthalpy',
    'DifferentialDryBulbAndEnthalpy',
    'NoEconomizer',
)

# Field A7, whose IDD default is ModulateFlow.
ECONOMIZER_ACTION_TYPES = ('ModulateFlow', 'MinimumFlowWithBypass')


def set_economizer(controller, *, control_type, action_type=None,
                   maximum_limit_drybulb_c=None,
                   minimum_limit_drybulb_c=None,
                   maximum_limit_enthalpy_j_per_kg=None,
                   maximum_limit_dewpoint_c=None, audit=None,
                   step='ventilation'):
    """The air-side economizer on one ``ControllerOutdoorAir``.

    #192's controls cluster. `canmet-energy/campus` carries an
    `economizer_control` measure and `btap.modeling` had no economizer
    primitive — only a hardcoded `setEconomizerControlType('NoEconomizer')`
    inside the DOAS builder, which is the opposite of the capability.

    For stock work the economizer is a VINTAGE MARKER as much as a control: a
    pre-1980 building generally has none, and NECB's own 5.2.2.7 trigger
    (D-22) is a threshold test that removes one from the reference when the
    proposed is below it. Both of those are "set the control type", which is
    what this is.

    **`NoEconomizer` is the IDD default, so omitting the economizer and
    disabling it are the same state but not the same act.** A caller passing
    `control_type='NoEconomizer'` is asserting the building has none, and that
    assertion reaches the audit trail; a model that merely never set it says
    nothing. That distinction is why this takes `control_type` as REQUIRED
    rather than defaulting it.

    :param control_type: one of `ECONOMIZER_CONTROL_TYPES`, validated here.
    :param action_type: one of `ECONOMIZER_ACTION_TYPES`; the IDD default is
        `'ModulateFlow'`, so this is only passed to change it.
    :param maximum_limit_drybulb_c: the high-limit shutoff. A dry-bulb
        economizer with no limit runs in weather it should not.
    :returns: the ``ControllerOutdoorAir``, for chaining.
    """
    if control_type not in ECONOMIZER_CONTROL_TYPES:
        raise ValueError(
            f'{control_type!r} is not an EnergyPlus economizer control type. '
            f'The IDD accepts: {", ".join(ECONOMIZER_CONTROL_TYPES)}.')
    if action_type is not None and action_type not in ECONOMIZER_ACTION_TYPES:
        raise ValueError(
            f'{action_type!r} is not an economizer control ACTION type. The '
            f'IDD accepts: {", ".join(ECONOMIZER_ACTION_TYPES)}.')

    if not controller.setEconomizerControlType(control_type):
        raise ValueError(
            f'the model refused economizer control type {control_type!r} on '
            f'{controller.nameString()!r}')
    if action_type is not None:
        controller.setEconomizerControlActionType(action_type)
    if maximum_limit_drybulb_c is not None:
        controller.setEconomizerMaximumLimitDryBulbTemperature(
            float(maximum_limit_drybulb_c))
    if minimum_limit_drybulb_c is not None:
        controller.setEconomizerMinimumLimitDryBulbTemperature(
            float(minimum_limit_drybulb_c))
    if maximum_limit_enthalpy_j_per_kg is not None:
        controller.setEconomizerMaximumLimitEnthalpy(
            float(maximum_limit_enthalpy_j_per_kg))
    if maximum_limit_dewpoint_c is not None:
        controller.setEconomizerMaximumLimitDewpointTemperature(
            float(maximum_limit_dewpoint_c))

    if audit is not None:
        audit.info(step,
                   'economizer control set'
                   if control_type != 'NoEconomizer'
                   else 'economizer DISABLED',
                   target=controller.nameString(),
                   inputs={'control_type': control_type,
                           'action_type': action_type,
                           'maximum_limit_drybulb_c': maximum_limit_drybulb_c,
                           'minimum_limit_drybulb_c': minimum_limit_drybulb_c})
    return controller


def economizer_controller(air_loop):
    """The ``ControllerOutdoorAir`` of ``air_loop``, or None.

    The same optional first hop as `set_demand_controlled_ventilation`: a
    recirculating loop has no outdoor-air system, so there is no controller
    and no economizer to set. Not an error.
    """
    oa_system = opt(air_loop.airLoopHVACOutdoorAirSystem())
    if oa_system is None:
        return None
    return oa_system.getControllerOutdoorAir()


def set_economizer_in_model(model, *, control_type, audit=None,
                            step='ventilation', **limits):
    """`set_economizer` on every air loop in ``model`` that has a controller.

    The retrofit and vintage shape both: "this building has no economizer", or
    "every system now has a differential dry-bulb one".

    :returns: the number of controllers set.
    """
    from btap._compat import sorted_by_name

    count = 0
    for air_loop in sorted_by_name(model.getAirLoopHVACs()):
        controller = economizer_controller(air_loop)
        if controller is None:
            continue
        set_economizer(controller, control_type=control_type, audit=audit,
                       step=step, **limits)
        count += 1
    return count

