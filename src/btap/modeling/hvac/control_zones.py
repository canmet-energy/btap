"""Which zone controls a shared single-zone unit.

A packaged single-zone unit can legitimately serve several zones: a house's
furnace serves the basement, main and second floor from ONE thermostat. The
unit then delivers the supply air its CONTROL zone asks for and every other
zone takes what it gets, so the choice of control zone decides which zones go
unmet. Placing it where the heating load is largest is the usual practice,
because the other zones are then over-served rather than starved.

Two ways to choose (phylroy, 2026-11-20):

- **set by the user**: ``build_system(..., control_zone=zone)``. That choice is
  final; nothing here changes it;
- **elected from a sizing run**: with no ``control_zone``, ``build_system``
  controls from the first zone PROVISIONALLY and marks the loop. After a
  sizing run, :func:`elect_control_zones` moves each marked loop's control to
  its zone with the largest design heating load.

Until #237's follow-up the builder took ``zones[0]`` and left it there: on a
five-zone data-centre building the shared unit then left 377 h of heating
unmet after three NECB capacity increases.
"""

from __future__ import annotations

from btap._compat import opt, sorted_by_name

#: The mark ``build_system`` leaves on a shared loop whose control zone is
#: to be elected, and the rule it asks for.
FEATURE = "btap_control_zone"
LARGEST_HEATING_LOAD = "largest_heating_load"

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


def mark_for_election(air_loop):
    """Record that this loop's control zone is to be elected from sizing."""
    air_loop.additionalProperties().setFeature(FEATURE, LARGEST_HEATING_LOAD)


def is_marked(air_loop):
    value = opt(air_loop.additionalProperties().getFeatureAsString(FEATURE))
    return value == LARGEST_HEATING_LOAD


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


def elect_control_zones(model, *, audit=None):
    """Move each marked shared loop's control to its zone with the LARGEST
    design heating load, read from the model's sizing results.

    Run it after ``btap.simulation.run(model, ..., sizing_only=True)``, which
    leaves the sizing results attached to the model. Only loops that
    ``build_system`` marked are touched; a control zone the user chose is
    never changed.

    :returns: ``{air loop name: elected zone name}`` for every marked loop.
    :raises ValueError: when the model carries no sizing results.
    """
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
        zones = sorted_by_name(loop.thermalZones())
        loads = {z.nameString(): opt(z.autosizedHeatingDesignLoad()) for z in zones}
        if not zones or any(v is None for v in loads.values()):
            if audit is not None:
                audit.warn("hvac",
                           "CONTROL ZONE NOT ELECTED — the sizing results carry "
                           "no design heating load for every zone this unit "
                           "serves, so it stays on its provisional zone",
                           target=loop.nameString(),
                           inputs={"design_heating_load_w": loads})
            continue
        # Largest load wins; a tie goes to the first zone by name, so the
        # result does not depend on model insertion order.
        largest = max(loads.values())
        winner = next(z for z in zones if loads[z.nameString()] == largest)
        before = sorted({zone.nameString() for zone in
                         (_control_zone(c) for c in controls(loop)) if zone})
        for control in controls(loop):
            _set_control_zone(control, winner)
        elected[loop.nameString()] = winner.nameString()
        if audit is not None:
            audit.decision("hvac",
                           "shared unit controlled from the zone with the "
                           "largest design heating load",
                           target=loop.nameString(),
                           inputs={"design_heating_load_w": {
                                       k: round(v, 1) for k, v in loads.items()},
                                   "provisional": before},
                           value=winner.nameString())
    return elected
