"""Which zone controls a shared single-zone unit.

A packaged single-zone unit can legitimately serve several zones: a house's
furnace serves the basement, main and second floor from ONE thermostat. The
unit then delivers the supply air its CONTROL zone asks for and every other
zone takes what it gets, so the choice of control zone decides which zones go
unmet.

Ways to choose (phylroy, 2026-11-20):

- **set by the user**: ``build_system(..., control_zone=zone)``. That choice is
  final; nothing here changes it;
- **elected from a sizing run**: ``build_system`` with no zone, or with one of
  the RULES below, controls from the first zone PROVISIONALLY and marks the
  loop with the rule. After a sizing run, :func:`elect_control_zones` carries
  the rule out:

  - ``"heating"`` (the default): the zone with the largest design heating
    load. The others are over-heated rather than starved, which suits a
    code like NECB whose heating limit is absolute (8.4.1.2.(3));
  - ``"cooling"``: the zone with the largest design cooling load.

**What no rule can do.** One thermostat serves ONE zone well. On a five-zone
office (core plus four orientations) the zone holding the thermostat met its
loads and the others did not, whichever zone it was: the zones peak at
different times. A seasonal outdoor-temperature changeover between the two
rules was built and measured (it reproduced the plain manager to 0.05 %), and
it still left 822 h of cooling unmet — so it was not kept. Where the zones
really differ, the answer is one unit per zone, or, where NECB's thermal-block
definition allows it (Division A 1.4.1.2 (b)(iii)), merging them.
"""

from __future__ import annotations

from btap._compat import opt, sorted_by_name

#: The mark ``build_system`` leaves on a shared loop whose control zone is
#: to be elected, and the rule it asks for.
FEATURE = "btap_control_zone"
LARGEST_HEATING_LOAD = "largest_heating_load"
LARGEST_COOLING_LOAD = "largest_cooling_load"

#: The public rule names and the mark each records.
RULES = {"heating": LARGEST_HEATING_LOAD, "cooling": LARGEST_COOLING_LOAD}



#: Setpoint managers that follow ONE zone (each carries `setControlZone`).
_ZONE_MANAGERS = (
    "SetpointManagerSingleZoneReheat",
    "SetpointManagerSingleZoneHeating",
    "SetpointManagerSingleZoneCooling",
    "SetpointManagerSingleZoneOneStageHeating",
    "SetpointManagerSingleZoneOneStageCooling",
    "SetpointManagerSingleZoneHumidityMinimum",
    "SetpointManagerSingleZoneHumidityMaximum",
)


def rule_of(name):
    """The mark for a public rule name, refusing an unknown one."""
    if name not in RULES:
        raise ValueError(f"control zone rule must be a ThermalZone or one of "
                         f"{sorted(RULES)}, not {name!r}")
    return RULES[name]


def mark_for_election(air_loop, rule=LARGEST_HEATING_LOAD):
    """Record that this loop's control zone is to be elected from sizing."""
    air_loop.additionalProperties().setFeature(FEATURE, rule)


def marked_rule(air_loop):
    """The rule a loop is marked with, or None."""
    value = opt(air_loop.additionalProperties().getFeatureAsString(FEATURE))
    return value if value in RULES.values() else None


def is_marked(air_loop):
    return marked_rule(air_loop) is not None


def controls(air_loop):
    """Every object on ``air_loop`` that follows one control zone."""
    found = []
    for component in air_loop.supplyComponents():
        node = opt(component.to_Node())
        if node is None:
            continue
        for manager in node.setpointManagers():
            for name in _ZONE_MANAGERS:
                cast = opt(getattr(manager, f"to_{name}")())
                if cast is not None:
                    found.append(cast)
                    break
    model = air_loop.model()
    for unitary in (list(model.getAirLoopHVACUnitarySystems())
                    + list(model.getAirLoopHVACUnitaryHeatPumpAirToAirMultiSpeeds())):
        loop = opt(unitary.airLoopHVAC())
        if loop is not None and loop.handle() == air_loop.handle():
            found.append(unitary)
    return found


def _control_zone(control):
    if hasattr(control, "controlZone"):
        return opt(control.controlZone())
    return opt(control.controllingZoneorThermostatLocation())


def _set_control_zone(control, zone):
    if hasattr(control, "setControlZone"):
        return control.setControlZone(zone)
    return control.setControllingZoneorThermostatLocation(zone)


def _largest(zones, loads):
    largest = max(loads.values())
    return next(z for z in zones if loads[z.nameString()] == largest)


def elect_control_zones(model, *, by=None, audit=None):
    """Carry out each marked shared loop's control-zone rule from the model's
    sizing results.

    Run it after ``btap.simulation.run(model, ..., sizing_only=True)``, which
    leaves the sizing results attached to the model. Only loops that
    ``build_system`` marked are touched; a control zone the user chose is
    never changed.

    :param by: ``"heating"`` or ``"cooling"`` to apply that rule to every
        marked loop; None (the default) applies the rule each loop was marked
        with.
    :returns: ``{air loop name: elected zone name}``.
    :raises ValueError: when the model carries no sizing results, or on an
        unknown rule.
    """
    override = rule_of(by) if by is not None else None
    marked = [loop for loop in sorted_by_name(model.getAirLoopHVACs())
              if is_marked(loop)]
    if not marked:
        return {}
    if opt(model.sqlFile()) is None:
        raise ValueError(
            "elect_control_zones needs sizing results: run "
            "btap.simulation.run(model, ..., sizing_only=True) first, in the "
            "same session, so the model carries them")

    elected = {}
    for loop in marked:
        rule = override or marked_rule(loop)
        which = "heating" if rule == LARGEST_HEATING_LOAD else "cooling"
        zones = sorted_by_name(loop.thermalZones())
        reader = {"heating": "autosizedHeatingDesignLoad",
                  "cooling": "autosizedCoolingDesignLoad"}[which]
        loads = {z.nameString(): opt(getattr(z, reader)()) for z in zones}
        if not zones or any(v is None for v in loads.values()):
            if audit is not None:
                audit.warn("hvac",
                           f"CONTROL ZONE NOT ELECTED — the sizing results carry "
                           f"no design {which} load for every zone this unit "
                           f"serves, so it stays on its provisional zone",
                           target=loop.nameString(),
                           inputs={"rule": rule, f"design_{which}_load_w": loads})
            continue
        before = sorted({zone.nameString() for zone in
                         (_control_zone(c) for c in controls(loop)) if zone})
        winner = _largest(zones, loads)
        for control in controls(loop):
            _set_control_zone(control, winner)
        elected[loop.nameString()] = winner.nameString()
        if audit is not None:
            audit.decision("hvac",
                           f"shared unit controlled from the zone with the "
                           f"largest design {which} load",
                           target=loop.nameString(),
                           inputs={"rule": rule, "provisional": before,
                                   f"design_{which}_load_w":
                                       {k: round(v, 1) for k, v in loads.items()}},
                           value=winner.nameString())
    return elected
