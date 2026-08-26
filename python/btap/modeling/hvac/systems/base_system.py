"""Shared behavior for system builders: sizing-block application helpers.

Subclass contract: ``build(model, zones, control_zone=..., namer=...)`` returning
the list of AirLoopHVACs created.
"""

from __future__ import annotations

import openstudio


class BaseSystem:
    def __init__(self, config):
        """:param config: a resolved catalog row (dict, string keys; 'sizing' is a dict)"""
        self._config = config

    @property
    def config(self):
        return self._config

    @property
    def sizing(self):
        return self.config.get('sizing') or {}

    def apply_system_sizing(self, air_loop):
        """Apply the sizing block's air-loop-level fields to a Sizing:System object.
        Ported from openstudio-standards common_air_loop."""
        s = air_loop.sizingSystem()
        s.autosizeDesignOutdoorAirFlowRate()
        z = self.sizing
        if z.get('preheat_design_temperature') is not None:
            s.setPreheatDesignTemperature(z['preheat_design_temperature'])
        if z.get('preheat_design_humidity_ratio') is not None:
            s.setPreheatDesignHumidityRatio(z['preheat_design_humidity_ratio'])
        if z.get('precool_design_temperature') is not None:
            s.setPrecoolDesignTemperature(z['precool_design_temperature'])
        if z.get('precool_design_humidity_ratio') is not None:
            s.setPrecoolDesignHumidityRatio(z['precool_design_humidity_ratio'])
        if z.get('sizing_option') is not None:
            s.setSizingOption(z['sizing_option'])
        if z.get('cooling_design_air_flow_method') is not None:
            s.setCoolingDesignAirFlowMethod(z['cooling_design_air_flow_method'])
        if z.get('cooling_design_air_flow_rate') is not None:
            s.setCoolingDesignAirFlowRate(z['cooling_design_air_flow_rate'])
        if z.get('heating_design_air_flow_method') is not None:
            s.setHeatingDesignAirFlowMethod(z['heating_design_air_flow_method'])
        if z.get('heating_design_air_flow_rate') is not None:
            s.setHeatingDesignAirFlowRate(z['heating_design_air_flow_rate'])
        if z.get('system_outdoor_air_method') is not None:
            s.setSystemOutdoorAirMethod(z['system_outdoor_air_method'])
        if z.get('central_cooling_design_supply_air_humidity_ratio') is not None:
            s.setCentralCoolingDesignSupplyAirHumidityRatio(
                z['central_cooling_design_supply_air_humidity_ratio'])
        if z.get('central_heating_design_supply_air_humidity_ratio') is not None:
            s.setCentralHeatingDesignSupplyAirHumidityRatio(
                z['central_heating_design_supply_air_humidity_ratio'])
        if z.get('type_of_load_to_size_on') is not None:
            s.setTypeofLoadtoSizeOn(z['type_of_load_to_size_on'])
        if z.get('central_cooling_design_supply_air_temperature') is not None:
            s.setCentralCoolingDesignSupplyAirTemperature(
                z['central_cooling_design_supply_air_temperature'])
        if z.get('central_heating_design_supply_air_temperature') is not None:
            s.setCentralHeatingDesignSupplyAirTemperature(
                z['central_heating_design_supply_air_temperature'])
        if z.get('all_outdoor_air_in_cooling') is not None:
            s.setAllOutdoorAirinCooling(z['all_outdoor_air_in_cooling'])
        if z.get('all_outdoor_air_in_heating') is not None:
            s.setAllOutdoorAirinHeating(z['all_outdoor_air_in_heating'])
        if z.get('minimum_system_air_flow_ratio') is not None:
            s.setCentralHeatingMaximumSystemAirFlowRatio(z['minimum_system_air_flow_ratio'])
        return s

    def apply_zone_sizing(self, zone):
        """Apply the sizing block's zone-level fields: either the TemperatureDifference
        method (NECB reference systems) or absolute supply temperatures (ECM systems),
        plus factors."""
        sz = zone.sizingZone()
        z = self.sizing
        if z.get('zone_cooling_design_supply_air_temperature') is not None:
            sz.setZoneCoolingDesignSupplyAirTemperature(
                z['zone_cooling_design_supply_air_temperature'])
        if z.get('zone_heating_design_supply_air_temperature') is not None:
            sz.setZoneHeatingDesignSupplyAirTemperature(
                z['zone_heating_design_supply_air_temperature'])
        if z.get('zone_cooling_design_supply_air_temperature_input_method') is not None:
            sz.setZoneCoolingDesignSupplyAirTemperatureInputMethod(
                z['zone_cooling_design_supply_air_temperature_input_method'])
        if z.get('zone_cooling_design_supply_air_temperature_difference') is not None:
            sz.setZoneCoolingDesignSupplyAirTemperatureDifference(
                z['zone_cooling_design_supply_air_temperature_difference'])
        if z.get('zone_heating_design_supply_air_temperature_input_method') is not None:
            sz.setZoneHeatingDesignSupplyAirTemperatureInputMethod(
                z['zone_heating_design_supply_air_temperature_input_method'])
        if z.get('zone_heating_design_supply_air_temperature_difference') is not None:
            sz.setZoneHeatingDesignSupplyAirTemperatureDifference(
                z['zone_heating_design_supply_air_temperature_difference'])
        if z.get('zone_cooling_sizing_factor') is not None:
            sz.setZoneCoolingSizingFactor(z['zone_cooling_sizing_factor'])
        if z.get('zone_heating_sizing_factor') is not None:
            sz.setZoneHeatingSizingFactor(z['zone_heating_sizing_factor'])
        self.apply_doas_zone_sizing(sz, z)
        return sz

    def apply_doas_zone_sizing(self, sizing_zone, z):
        """8.4.4.9.(3)/8.4.4.10.(7) (2025: 8.4.5.x) terminal/secondary capacity
        split, D-50. Where the selection table puts heating (or cooling) in BOTH
        a zone terminal and a make-up-air secondary system, the terminal is sized
        for the space loads and the ventilation air is carried at system level.
        EnergyPlus expresses exactly that as Sizing:Zone dedicated-outdoor-air
        accounting with a NEUTRAL supply-air strategy: the DOAS stream neither
        adds nor removes zone load, so the terminal's design load is the
        envelope(-and-internal) load alone.

        The low/high setpoint pair must be strictly increasing (EnergyPlus
        rejects low >= high with a Severe), hence the 0.1 degC spread — the same
        convention the make-up-air sizing block already uses for its own
        setpoint pair."""
        if not z.get('account_for_dedicated_outdoor_air_system'):
            return

        sizing_zone.setAccountforDedicatedOutdoorAirSystem(True)
        if z.get('dedicated_outdoor_air_system_control_strategy') is not None:
            sizing_zone.setDedicatedOutdoorAirSystemControlStrategy(
                z['dedicated_outdoor_air_system_control_strategy'])
        if z.get('dedicated_outdoor_air_low_setpoint_temperature_for_design') is not None:
            sizing_zone.setDedicatedOutdoorAirLowSetpointTemperatureforDesign(
                z['dedicated_outdoor_air_low_setpoint_temperature_for_design'])
        if z.get('dedicated_outdoor_air_high_setpoint_temperature_for_design') is None:
            return

        sizing_zone.setDedicatedOutdoorAirHighSetpointTemperatureforDesign(
            z['dedicated_outdoor_air_high_setpoint_temperature_for_design'])

    def build_oa_system(self, model):
        """ZoneSum outdoor-air controller with autosized minimum OA (the NECB
        convention)."""
        oa_controller = openstudio.model.ControllerOutdoorAir(model)
        oa_controller.autosizeMinimumOutdoorAirFlowRate()
        oa_controller.controllerMechanicalVentilation().setSystemOutdoorAirMethod('ZoneSum')
        return openstudio.model.AirLoopHVACOutdoorAirSystem(model, oa_controller)
