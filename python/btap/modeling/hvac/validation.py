"""Precondition checks with clear errors (silent no-ops and deep SDK crashes are the
failure modes these guard against)."""

from __future__ import annotations


def require_thermostats(zones):
    """Every zone must carry a dual-setpoint thermostat: without setpoint schedules,
    sizing runs yield zero design loads and zone equipment silently conditions nothing.

    :param zones: list of openstudio.model.ThermalZone
    """
    bad = [z for z in zones if not z.thermostatSetpointDualSetpoint().is_initialized()]
    if not bad:
        return

    raise ValueError(
        'zones need a dual-setpoint thermostat before adding an HVAC system: '
        + ', '.join(z.nameString() for z in bad))


def require_control_zone(zones, control_zone):
    """The control zone (for single-zone systems) must be one of the served zones.

    Membership is by SDK handle (the Ruby ``Array#include?`` compares the wrapped
    objects; handles are the stable identity across wrapper instances).

    :return: the validated control zone
    """
    if not any(str(z.handle()) == str(control_zone.handle()) for z in zones):
        raise ValueError('control_zone must be one of the passed zones')

    return control_zone


def require_zones(zones):
    """Zones must be a non-empty list of ThermalZones (a tuple — the shape the
    Python SDK's getters return — is accepted too)."""
    if not isinstance(zones, (list, tuple)) or not zones:
        raise ValueError('zones must be a non-empty Array of ThermalZones')
