"""Packaged single-zone rooftop unit: one shared constant-volume air handler with DX
cooling + a heating coil, tracking ONE control zone's thermostat, delivering to all
served zones through uncontrolled diffusers, with per-zone baseboards.

This is the unified port of NECB sys3 (packaged rooftop) and sys4 (make-up air unit
with exhaust) — topologically identical (the legacy code's own comment: "This is the
same as system type 3... SHOULD WE COMBINE sys3 and sys4"); they differ only in
catalog config (sys_abbr and descriptive name).

The control zone is an explicit caller choice (default: first zone) — no sizing run
or stored loads are needed to elect it.
"""

from __future__ import annotations

import openstudio

from btap.modeling.hvac import naming
from btap.modeling.hvac.components import coils
from btap.modeling.hvac.systems import baseboards
from btap.modeling.hvac.systems.base_system import BaseSystem


class PSZ(BaseSystem):
    def build(self, model, zones, *, control_zone, namer='default',
              hw_loop=None, chw_loop=None):
        """
        :param model: openstudio.model.Model
        :param zones: list of openstudio.model.ThermalZone
        :param control_zone: openstudio.model.ThermalZone driving the shared handler
        :param namer: 'default' or 'necb_pipe_name'
        :param hw_loop: openstudio.model.PlantLoop or None, for hot-water coil/baseboards
        :param chw_loop: unused (DX cooling); shared contract
        :return: list of openstudio.model.AirLoopHVAC

        Config 'per_zone': true builds ONE packaged unit PER ZONE (each zone its own
        control zone) — the CBECS/90.1 PSZ convention — instead of the NECB convention
        of one shared unit over the zone group controlled by ``control_zone``.
        """
        if self.config.get('per_zone'):
            return [self._build_unit(model, [zone], zone, namer=namer, hw_loop=hw_loop)
                    for zone in zones]

        return [self._build_unit(model, zones, control_zone, namer=namer, hw_loop=hw_loop)]

    def _build_unit(self, model, zones, control_zone, *, namer, hw_loop):
        config = self.config
        sizing = self.sizing
        always_on = model.alwaysOnDiscreteSchedule()
        # The reference-ASHP marker is `heat_source: 'ashp'`. The legacy spelling —
        # `heating_coil_type: 'DX'`, which meant "this is a reference ASHP build"
        # rather than naming a heating coil — is still ACCEPTED as an alias so
        # out-of-tree configs keep working; internally it normalizes to 'DX' so the
        # build below is byte-for-byte the one the old catalog rows produced.
        reference_hp = (config.get('heat_source') == 'ashp'
                        or config.get('heating_coil_type') == 'DX')
        heating_coil_type = 'DX' if reference_hp else config.get('heating_coil_type')
        baseboard_type = config.get('baseboard_type')

        # --- air handler ---
        air_loop = openstudio.model.AirLoopHVAC(model)
        self.apply_system_sizing(air_loop)

        fan = openstudio.model.FanConstantVolume(model, always_on)
        fan.setName(f"{config['sys_abbr']} Supply Fan")

        # Coil names are load-bearing for host efficiency dispatch (NECB '_dx'/'_ashp'
        # selectors). 8.4.4.9.(7)/8.4.4.10.(8) staged coils: set ONLY by the NECB
        # reference ruleset (system_definitions config), so catalog defaults, proposed
        # models and CBECS builds keep the bare single-speed topology.
        staged_value = config.get('staged_coils')
        staged = staged_value is not None and staged_value is not False
        if reference_hp:
            if staged:
                clg_coil = coils.dx_cooling_multi_speed(
                    model, always_on, name='CoilCoolingDXMultiSpeed_ashp')
                htg_coil = coils.dx_heating_multi_speed(
                    model, always_on, name='CoilHeatingDXMultiSpeed_ashp')
            else:
                clg_coil = coils.dx_cooling_single_speed(
                    model, always_on, name='CoilCoolingDXSingleSpeed_ashp')
                htg_coil = coils.dx_heating_single_speed(
                    model, always_on, name='CoilHeatingDXSingleSpeed_ashp')
            supp_coil = coils.heating_coil(model, config.get('supp_htg_fuel', 'Electric'),
                                           always_on, hw_loop=hw_loop)
        elif staged:
            clg_coil = coils.dx_cooling_multi_speed(model, always_on)
            # D-49: electric resistance is not a furnace — 8.4.4.9.(7) staging does
            # not reach it, so an electric-heat staged PSZ pairs the multispeed DX
            # cooling coil with a plain single-stage electric coil.
            if heating_coil_type in ('Gas', 'NaturalGas'):
                htg_coil = coils.gas_heating_multi_stage(model, always_on)
            else:
                htg_coil = coils.heating_coil(model, heating_coil_type, always_on,
                                              hw_loop=hw_loop)
            supp_coil = None
        else:
            clg_coil = coils.dx_cooling_single_speed(model, always_on)
            htg_coil = coils.heating_coil(model, heating_coil_type, always_on,
                                          hw_loop=hw_loop)
            supp_coil = None

        oa_system = self.build_oa_system(model)

        supply_inlet_node = air_loop.supplyInletNode()
        if staged:
            # Multispeed coils cannot sit bare on an air loop (addToNode returns
            # false) — an AirLoopHVACUnitarySystem container is mandatory.
            # The supplemental coil goes on the LOOP, downstream of the unitary
            # (added first, so the unitary lands upstream of it), NOT in the
            # unitary's supplemental slot: EnergyPlus sizes a unitary's
            # supplemental heater to the heat-pump capacity, which measured 26-70%
            # short of the loop-sized coil and failed the cold-week conditioning
            # gate below the -10 degC compressor cutoff. On the loop it sizes on
            # the loop's heating design and is driven by the outlet
            # SetpointManagerSingleZoneReheat — the legacy arrangement.
            if supp_coil is not None:
                supp_coil.addToNode(supply_inlet_node)
            self._add_staged_unitary(model, air_loop, control_zone, fan,
                                     clg_coil, htg_coil, always_on)
        else:
            # Legacy insertion order at the supply inlet: fan, (supp), htg, clg, oa ->
            # airflow OA -> clg -> htg -> (supp) -> fan.
            fan.addToNode(supply_inlet_node)
            if supp_coil is not None:
                supp_coil.addToNode(supply_inlet_node)
            htg_coil.addToNode(supply_inlet_node)
            clg_coil.addToNode(supply_inlet_node)
        oa_system.addToNode(supply_inlet_node)

        # Single-zone reheat setpoint manager tracking the control zone.
        spm = openstudio.model.SetpointManagerSingleZoneReheat(model)
        spm.setControlZone(control_zone)
        if sizing.get('setpoint_manager_single_zone_reheat_supply_temp_min') is not None:
            spm.setMinimumSupplyAirTemperature(
                sizing['setpoint_manager_single_zone_reheat_supply_temp_min'])
        if sizing.get('setpoint_manager_single_zone_reheat_supply_temp_max') is not None:
            spm.setMaximumSupplyAirTemperature(
                sizing['setpoint_manager_single_zone_reheat_supply_temp_max'])
        spm.addToNode(air_loop.supplyOutletNode())

        # --- zones: sizing, baseboards, diffusers ---
        for zone in zones:
            self.apply_zone_sizing(zone)
            baseboards.add(model, zone, baseboard_type, hw_loop=hw_loop)
            diffuser = openstudio.model.AirTerminalSingleDuctUncontrolled(model, always_on)
            air_loop.addBranchForZone(zone, diffuser.to_StraightComponent())

        htg_part = heating_coil_type
        clg_part = 'dx'
        if reference_hp:
            clg_part = 'ashp'
            supp = self.config.get('supp_htg_fuel', 'Electric')
            if supp in ('Gas', 'NaturalGas'):
                htg_part = 'ashp>c-g'
            elif supp in ('Hot Water', 'HotWater'):
                htg_part = 'ashp>c-hw'
            else:
                htg_part = 'ashp>c-e'
        naming.apply(namer, air_loop,
                     system_name=config['name'],
                     sys_abbr=config['sys_abbr'],
                     sys_oa='mixed',
                     parts={
                         'sys_hr': 'none',
                         'sys_clg': clg_part,
                         'sys_htg': htg_part,
                         'sys_sf': 'cv',
                         'zone_htg': baseboard_type,
                         'zone_clg': 'none',
                         'sys_rf': 'none',
                     },
                     suffix=control_zone.nameString())
        return air_loop

    def _add_staged_unitary(self, model, air_loop, control_zone, fan, clg_coil,
                            htg_coil, always_on):
        """Wrap the fan and staged coils in an AirLoopHVACUnitarySystem — the only
        SDK container that can host multispeed coils on an air loop.

        Control mirrors the legacy multi-speed sys3 build: Load control tracking
        the elected control zone, an always-on fan schedule, and the
        SetpointManagerSingleZoneReheat left on the loop outlet. Capacities and
        flows are AUTOSIZED throughout; the equal capacity increments the code
        asks for are realized by the UnitarySystemPerformanceMultispeed flow
        ratios (stage k -> k/N), NOT by hard-setting stage capacities.

        :return: openstudio.model.AirLoopHVACUnitarySystem
        """
        unitary = openstudio.model.AirLoopHVACUnitarySystem(model)
        unitary.setName(
            f"{self.config['sys_abbr']} Staged Unitary {control_zone.nameString()}")
        unitary.setControlType('Load')
        unitary.setControllingZoneorThermostatLocation(control_zone)
        unitary.setSupplyFan(fan)
        unitary.setFanPlacement('BlowThrough')
        # The unitary's OWN availability schedule gates the fan inside it — the
        # air loop's availability does not reach it, and left at the always-on
        # default the reference fan runs 8760 h whatever 8.4.3.2.(1) says the
        # system's hours are. It follows the loop's schedule (the D-14 pass
        # re-points it at the schedule inherited from the proposed).
        # The fan OPERATING MODE stays continuous — a constant-volume system
        # runs its fan whenever it is available, and EnergyPlus rejects a mode
        # schedule containing zeros for this field anyway (it must be blank for
        # cycling, or strictly positive).
        unitary.setAvailabilitySchedule(air_loop.availabilitySchedule())
        unitary.setSupplyAirFanOperatingModeSchedule(always_on)
        unitary.setCoolingCoil(clg_coil)
        unitary.setHeatingCoil(htg_coil)
        if self.sizing.get('setpoint_manager_single_zone_reheat_supply_temp_max') is not None:
            unitary.setMaximumSupplyAirTemperature(
                self.sizing['setpoint_manager_single_zone_reheat_supply_temp_max'])
        performance = openstudio.model.UnitarySystemPerformanceMultispeed(model)
        performance.setName(
            f"{self.config['sys_abbr']} Multispeed Performance {control_zone.nameString()}")
        unitary.setDesignSpecificationMultispeedObject(performance)
        coils.set_stage_flow_ratios(unitary)
        unitary.addToNode(air_loop.supplyInletNode())
        return unitary
