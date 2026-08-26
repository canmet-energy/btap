"""Built-up multizone VAV with reheat (port of NECB sys6): per building story, one air
handler with variable-volume supply AND return fans, hot-water or electric heating
coil, chilled-water cooling coil, constant 13C supply-air setpoint, and per-zone VAV
reheat terminals with NECB minimums, plus zone baseboards. Chilled/condenser water
plant is created by the builder (plant_loops.chilled_water) and passed in."""

from __future__ import annotations

import re

import openstudio

from btap.modeling.geometry import helpers
from btap.modeling.hvac import naming
from btap.modeling.hvac.components import coils, schedules
from btap.modeling.hvac.systems import baseboards
from btap.modeling.hvac.systems.base_system import BaseSystem

# System grouping per NECB Note (3) to Table 8.4.4.7.-B (D-18; the former
# one-air-handler-per-storey convention had NO code basis and was caught
# by the archetype fixed-point comparison):
#   <= 4 above-ground storeys: ONE system serves the thermal blocks of
#     all storeys.
#   > 4 storeys: EXTERNAL thermal blocks group by facade orientation
#     (N/E/S/W, 45-degree-centred bins), INTERNAL blocks form one group,
#     each grouping served by a single system.
#   UNDERGROUND thermal blocks always form one independent group.
# Corner blocks (exterior walls on several facades) bin by the LARGEST
# exterior-wall area among orientations; ties resolve N > E > S > W.
COMPASS = ('N', 'E', 'S', 'W')


class VAVReheat(BaseSystem):
    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        """
        :param model: openstudio.model.Model
        :param zones: list of openstudio.model.ThermalZone
        :param control_zone: unused (multizone system); accepted for the shared
            build contract
        :param namer: 'default' or 'necb_pipe_name'
        :param hw_loop: openstudio.model.PlantLoop or None, for hot-water
            coil/reheat/baseboards
        :param chw_loop: openstudio.model.PlantLoop — chilled-water loop for the
            cooling coil
        :return: list of openstudio.model.AirLoopHVAC

        config 'cooling_type': 'chilled_water' (default, NECB sys6) or 'dx'
        (packaged VAV — the CBECS PVAV pattern: two-speed DX cooling, no chiller
        plant).
        """
        dx_cooling = self.config.get('cooling_type', 'chilled_water') == 'dx'
        if chw_loop is None and not dx_cooling:
            raise ValueError('VAVReheat requires a chilled water loop (needs_chiller)')

        heating_coil_type = self.config.get('heating_coil_type')
        baseboard_type = self.config.get('baseboard_type')
        air_loops = []

        for group in self._zone_groups(model, zones):
            air_loops.append(self._build_air_loop(
                model, group,
                heating_coil_type=heating_coil_type,
                baseboard_type=baseboard_type,
                hw_loop=hw_loop, chw_loop=chw_loop,
                namer=namer))
        return air_loops

    def _zone_groups(self, model, zones):
        underground = [z for z in zones if self._is_underground_zone(z)]
        above = [z for z in zones if not self._is_underground_zone(z)]
        groups = []
        if helpers.above_ground_storeys(model) <= 4:
            if above:
                groups.append(above)
        else:
            external = [z for z in above
                        if sum(self._facade_wall_areas(z).values()) > 0.0]
            internal = [z for z in above
                        if not sum(self._facade_wall_areas(z).values()) > 0.0]
            for direction in COMPASS:
                face = [z for z in external
                        if self._dominant_orientation(z) == direction]
                if face:
                    groups.append(face)
            if internal:
                groups.append(internal)
        if underground:
            groups.append(underground)
        return groups

    def _is_underground_zone(self, zone):
        """Below grade: ground-contact walls and no walls to Outdoors."""
        walls = [srf for space in zone.spaces() for srf in space.surfaces()
                 if srf.surfaceType() == 'Wall']
        return (not any(w.outsideBoundaryCondition() == 'Outdoors' for w in walls)
                and any(re.search(r'Ground|Foundation', w.outsideBoundaryCondition(),
                                  re.IGNORECASE)
                        for w in walls))

    def _facade_wall_areas(self, zone):
        """Exterior wall area per compass bin (azimuth from outward normal)."""
        areas = {}
        for space in zone.spaces():
            for srf in space.surfaces():
                if not (srf.surfaceType() == 'Wall'
                        and srf.outsideBoundaryCondition() == 'Outdoors'):
                    continue

                az = (openstudio.radToDeg(srf.azimuth())
                      + space.directionofRelativeNorth()
                      + space.model().getBuilding().northAxis()) % 360.0
                # Ruby's exclusive-end ranges (45...135 etc.) written out explicitly.
                if 45 <= az < 135:
                    direction = 'E'
                elif 135 <= az < 225:
                    direction = 'S'
                elif 225 <= az < 315:
                    direction = 'W'
                else:
                    direction = 'N'
                areas[direction] = areas.get(direction, 0.0) + srf.grossArea()
        return areas

    def _dominant_orientation(self, zone):
        areas = self._facade_wall_areas(zone)
        return max(COMPASS, key=lambda d: (areas.get(d, 0.0), -COMPASS.index(d)))

    def _build_air_loop(self, model, group, *, heating_coil_type, baseboard_type,
                        hw_loop, chw_loop, namer):
        sizing = self.sizing
        always_on = model.alwaysOnDiscreteSchedule()

        air_loop = openstudio.model.AirLoopHVAC(model)
        self.apply_system_sizing(air_loop)

        supply_fan = openstudio.model.FanVariableVolume(model, always_on)
        supply_fan.setName('Sys6 Supply Fan')   # 'Supply'/'Return' substrings are load-bearing
        return_fan = openstudio.model.FanVariableVolume(model, always_on)
        return_fan.setName('Sys6 Return Fan')   # for host fan rules

        htg_coil = coils.heating_coil(model, heating_coil_type, always_on, hw_loop=hw_loop)
        if self.config.get('cooling_type', 'chilled_water') == 'dx':
            clg_coil = openstudio.model.CoilCoolingDXTwoSpeed(model)
            clg_coil.setName('CoilCoolingDXTwoSpeed_PVAV')
        else:
            clg_coil = openstudio.model.CoilCoolingWater(model, always_on)
            chw_loop.addDemandBranchForComponent(clg_coil)

        oa_system = self.build_oa_system(model)

        supply_inlet_node = air_loop.supplyInletNode()
        supply_fan.addToNode(supply_inlet_node)
        htg_coil.addToNode(supply_inlet_node)
        clg_coil.addToNode(supply_inlet_node)
        oa_system.addToNode(supply_inlet_node)
        return_air_node = oa_system.returnAirModelObject().get().to_Node().get()
        return_fan.addToNode(return_air_node)

        sat = sizing.get('system_supply_air_temperature', 13.0)
        spm = openstudio.model.SetpointManagerScheduled(
            model, schedules.constant_ruleset(model, 'Supply Air Temp', sat))
        spm.addToNode(air_loop.supplyOutletNode())

        for zone in group:
            self.apply_zone_sizing(zone)
            baseboards.add(model, zone, baseboard_type, hw_loop=hw_loop)

            reheat_coil = coils.heating_coil(model, heating_coil_type, always_on,
                                             hw_loop=hw_loop)
            terminal = openstudio.model.AirTerminalSingleDuctVAVReheat(
                model, always_on, reheat_coil)
            air_loop.addBranchForZone(zone, terminal.to_StraightComponent())
            # NECB minimum zone airflow settings
            if sizing.get('zone_vav_min_flow_factor_per_floor_area') is not None:
                terminal.setFixedMinimumAirFlowRate(
                    sizing['zone_vav_min_flow_factor_per_floor_area'] * zone.floorArea())
            if sizing.get('zone_vav_max_reheat_temp') is not None:
                terminal.setMaximumReheatAirTemperature(sizing['zone_vav_max_reheat_temp'])
            if sizing.get('zone_vav_damper_action') is not None:
                terminal.setDamperHeatingAction(sizing['zone_vav_damper_action'])
            # Legacy NECB sys6 hard-sets max-flow-fraction-during-reheat to 0.5: with the
            # 'Single Maximum' damper action, a VAV box in reheat may open to at most half
            # its cooling design flow (air_loop_hvac_apply_vav_damper_action,
            # necb/NECB2011/hvac_systems.rb:466). T11: legacy parity (T11 = 2026-07-25 audit
            # register item; see btap-necb/docs/README.md).
            terminal.setMaximumFlowFractionDuringReheat(0.5)

        # NOTE parts order: sys6 legacy emits sys_htg BEFORE sys_clg (insertion order).
        naming.apply(namer, air_loop,
                     system_name=self.config['name'],
                     sys_abbr=self.config['sys_abbr'],
                     sys_oa='mixed',
                     parts={
                         'sys_hr': 'none',
                         'sys_htg': heating_coil_type,
                         'sys_clg': ('dx'
                                     if self.config.get('cooling_type', 'chilled_water') == 'dx'
                                     else 'Chilled Water'),
                         'sys_sf': 'vv',
                         'zone_htg': baseboard_type,
                         'zone_clg': 'none',
                         'sys_rf': 'vv',
                     },
                     suffix=group[0].nameString())
        return air_loop
