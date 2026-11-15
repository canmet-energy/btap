"""Zone baseboards (electric or hot-water), ported from openstudio-standards
add_zone_baseboards."""

from __future__ import annotations

import openstudio


def add(model, zone, baseboard_type, hw_loop=None):
    """Add a baseboard to a thermal zone.

    :param model: openstudio.model.Model
    :param zone: openstudio.model.ThermalZone
    :param baseboard_type: 'Electric' or 'Hot Water'
    :param hw_loop: openstudio.model.PlantLoop or None (required for 'Hot Water')
    :return: None
    """
    if baseboard_type == 'Electric':
        baseboard = openstudio.model.ZoneHVACBaseboardConvectiveElectric(model)
        baseboard.addToThermalZone(zone)
    elif baseboard_type in ('Hot Water', 'HotWater'):
        if hw_loop is None:
            raise ValueError('a hot water loop is required for Hot Water baseboards')

        coil = openstudio.model.CoilHeatingWaterBaseboard(model)
        hw_loop.addDemandBranchForComponent(coil)
        baseboard = openstudio.model.ZoneHVACBaseboardConvectiveWater(
            model, model.alwaysOnDiscreteSchedule(), coil)
        baseboard.addToThermalZone(zone)
    elif baseboard_type in ('None', None):
        pass  # no baseboards
    else:
        raise ValueError(f"'{baseboard_type}' is not a valid baseboard type")
