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
