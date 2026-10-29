"""Cooling-only computer-room air handler (CRAH) with humidity control."""

from __future__ import annotations

import openstudio

from btap._compat import opt, sorted_by_name
from btap.modeling.hvac import naming
from btap.modeling.hvac.components import schedules
from btap.modeling.hvac.systems.base_system import BaseSystem
from btap.modeling.hvac.systems.doas import validate_dehumidifying_doas_inputs

#: A data centre is conditioned to a dewpoint, not merely to a temperature, so a
#: CRAH's humidity ceiling is part of the system rather than an option. These are
#: ordinary data-centre values, and both are overridable per row.
DEFAULT_SUPPLY_AIR_TEMPERATURE_C = 13.0
DEFAULT_MAXIMUM_HUMIDITY_RATIO = 0.009


class Crah(BaseSystem):
    """A RECIRCULATING, cooling-only air handler that also holds a humidity cap.

    Two things make this its own recipe rather than a flag on ``doas``, and they
    are the two that invert:

    - a DOAS conditions 100% OUTDOOR air; a CRAH conditions ROOM air, so it
      carries no outdoor-air system unless a row asks for one;
    - a DOAS cools and REHEATS; a CRAH is cooling-only and has no heating coil
      at all.

    Everything else is shared: the humidity ceiling is the same
    ``MaximumHumidityRatio`` setpoint manager, and the numeric guards are
    ``doas.validate_dehumidifying_doas_inputs``.

    The humidity cap and the dry-bulb setpoint can disagree — dehumidifying
    without reheat overcools, which is what a cooling-only handler does. That is
    the real behaviour of the equipment, so it is left visible rather than hidden
    behind a reheat coil this system does not have.
    """

    def preflight(self, model, zones, control_zone=None, namer='default',
                  remove_existing=False):
        """A hydronic coil with no chilled-water plant cannot be built.

        Refused HERE rather than at the coil, because `preflight` runs before
        any existing HVAC is torn down — a late failure would leave the model
        stripped of the system it came with.
        """
        cooling_type = self.config.get('cooling_type', 'Hydronic')
        if cooling_type != 'Hydronic':
            # DX is REFUSED, and the reason is the system's defining feature.
            # A humidity ceiling is honoured by a coil that keeps dehumidifying
            # past the dry-bulb setpoint. A water coil does that through its
            # controller (`TemperatureAndHumidityRatio`). A DX coil is staged
            # and has no equivalent: EnergyPlus delivers it only through
            # `CoilSystem:Cooling:DX`/`AirLoopHVACUnitarySystem` with
            # `CoolReheat`, which needs a REHEAT coil this cooling-only handler
            # does not have. Building DX here would attach a humidity setpoint
            # manager that EnergyPlus silently ignores — a CRAH that looks like
            # it controls humidity and does not (Fable, PR #153 review).
            raise ValueError(
                f"CRAH cooling_type '{cooling_type}' is not supported: only "
                f"'Hydronic' is, because a humidity ceiling needs water-coil "
                f"control — DX would require CoolReheat and this system is "
                f"cooling-only")
        # Validate the controls before touching the model, for the same reason.
        validate_dehumidifying_doas_inputs(
            supply_air_temperature=self.config.get(
                'crah_supply_air_temperature', DEFAULT_SUPPLY_AIR_TEMPERATURE_C),
            maximum_humidity_ratio=self.config.get(
                'crah_maximum_humidity_ratio', DEFAULT_MAXIMUM_HUMIDITY_RATIO))
        return None

    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        inputs = validate_dehumidifying_doas_inputs(
            supply_air_temperature=self.config.get(
                'crah_supply_air_temperature', DEFAULT_SUPPLY_AIR_TEMPERATURE_C),
            maximum_humidity_ratio=self.config.get(
                'crah_maximum_humidity_ratio', DEFAULT_MAXIMUM_HUMIDITY_RATIO))
        supply_air_temperature = inputs['supply_air_temperature']
        maximum_humidity_ratio = inputs['maximum_humidity_ratio']

        ordered = sorted_by_name(zones)
        if not ordered:
            return []

        system_name = self.config['name']
        always_on = model.alwaysOnDiscreteSchedule()

        air_loop = openstudio.model.AirLoopHVAC(model)
        self.apply_system_sizing(air_loop)

        fan = openstudio.model.FanConstantVolume(model, always_on)
        fan.setName(f'{system_name} Supply Fan')

        if chw_loop is None:
            raise ValueError(
                f"CRAH '{system_name}' asks for hydronic cooling but no "
                f"chilled-water loop was provided; set 'needs_chiller'")
        cooling = openstudio.model.CoilCoolingWater(model, always_on)
        cooling.setName(f'{system_name} Chilled Water Cooling Coil')
        chw_loop.addDemandBranchForComponent(cooling)

        supply_inlet_node = air_loop.supplyInletNode()
        fan.addToNode(supply_inlet_node)
        cooling.addToNode(supply_inlet_node)

        # NO heating coil and, by default, NO outdoor-air system: a CRAH
        # recirculates room air. A row may still ask for ventilation where the
        # computer room's own make-up air is served by this handler.
        if self.config.get('ventilation', False):
            self.build_oa_system(model).addToNode(supply_inlet_node)

        spm = openstudio.model.SetpointManagerScheduled(
            model, schedules.constant_ruleset(
                model, f'{system_name} Supply Air Temp', supply_air_temperature))
        spm.addToNode(air_loop.supplyOutletNode())

        self._add_humidity_control(model, cooling, system_name,
                                   maximum_humidity_ratio)
        self._arm_the_coil_controller(cooling, system_name)

        for zone in ordered:
            diffuser = openstudio.model.AirTerminalSingleDuctUncontrolled(
                model, always_on)
            air_loop.addBranchForZone(zone, diffuser.to_StraightComponent())

        naming.apply(
            namer, air_loop, system_name=system_name,
            sys_abbr=self.config.get('sys_abbr', 'crah'),
            sys_oa='doas' if self.config.get('ventilation', False) else 'none',
            parts={'sys_hr': 'none',
                   'sys_clg': 'chw',
                   'sys_htg': 'none', 'sys_sf': 'cv',
                   'zone_htg': 'none', 'zone_clg': 'none', 'sys_rf': 'none'},
            suffix=None)
        return [air_loop]

    @staticmethod
    def _add_humidity_control(model, cooling, system_name,
                              maximum_humidity_ratio):
        """Cap the supply humidity ratio at the COOLING COIL's outlet.

        The manager has to sit on the coil's own outlet rather than the loop
        outlet: it is what tells the coil to keep dehumidifying past the
        dry-bulb setpoint, and on the loop outlet it would be controlling a node
        downstream of the only component that can act on it.
        """
        schedule = openstudio.model.ScheduleConstant(model)
        schedule.setName(f'{system_name} Maximum Supply Humidity Ratio')
        schedule.setValue(float(maximum_humidity_ratio))
        manager = openstudio.model.SetpointManagerScheduled(model, schedule)
        manager.setName(f'{system_name} Humidity Setpoint Manager')
        manager.setControlVariable('MaximumHumidityRatio')
        # A CoilCoolingWater is a WaterToAirComponent with two sides, so only
        # `airOutletModelObject` names the air one — asking for the water side
        # would put the humidity ceiling on a WATER node.
        outlet = opt(cooling.airOutletModelObject())
        if outlet is None:
            raise ValueError(
                f"CRAH '{system_name}' cooling coil has no outlet node, so its "
                f"humidity ceiling cannot be controlled")
        manager.addToNode(outlet.to_Node().get())

    @staticmethod
    def _arm_the_coil_controller(cooling, system_name):
        """Make the humidity ceiling ACT, instead of merely existing.

        A setpoint manager on the coil's outlet node is necessary and NOT
        sufficient: EnergyPlus reads a maximum-humidity-ratio setpoint only when
        the coil's controller is told to track it. `Controller:WaterCoil`
        defaults to `Temperature`, so the manager sits on the right node and the
        coil still meets the sensible load alone — the ceiling is inert, and
        nothing reports it, because an unused node setpoint is not a Severe and
        the model is otherwise valid.

        Found by Fable in the PR #153 review by forward-translating the shipped
        row and reading the controller field, which is why the test for this
        reads the TRANSLATED object rather than the node placement.
        """
        controller = opt(cooling.controllerWaterCoil())
        if controller is None:
            raise ValueError(
                f"CRAH '{system_name}' cooling coil has no water controller, so "
                f"its humidity ceiling could not be armed and would be inert")
        controller.setControlVariable('TemperatureAndHumidityRatio')
