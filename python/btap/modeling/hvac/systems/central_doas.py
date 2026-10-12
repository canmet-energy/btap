"""A CENTRAL dedicated outdoor-air system feeding several zone air loops.

This is the SDK's `AirLoopHVACDedicatedOutdoorAirSystem`, which the rest of
this package does not build. `systems/doas.py` builds a DOAS *pattern* — a
100% outdoor-air loop delivering neutral air through uncontrolled diffusers —
and that is a different object graph: its coils sit on its own supply side
and it serves zones directly.

The SDK object is the other arrangement, and the one a model authored in the
OpenStudio App contains: ONE outdoor-air unit preconditions outdoor air and
feeds the OA inlet of SEVERAL air loops, each of which conditions its own
zone. Nothing in this package produced that graph, so the attribution code in
`btap.codes.necb.path` that resolves it was exercised only by hand-built
fixtures (Fable, `228`/`229`). A catalogue row puts it under the 97-system
lattice instead.

**Scope.** This is generic OpenStudio SDK authoring: ventilation delivery and
a preconditioning coil arrangement. It makes no NECB claim, carries no
`article=` citation, and takes no position on dehumidification — see the
limits below, which are deliberate and stated rather than implied by a
setpoint.
"""
from __future__ import annotations

import openstudio

from btap.modeling.hvac import naming
from btap.modeling.hvac.components import coils, schedules
from btap.modeling.hvac.systems.base_system import BaseSystem

#: Neutral supply temperature for the preconditioned outdoor air, in C. The
#: same value `systems/doas.py` uses, and for the same reason: it is a
#: ventilation system, so it delivers air that neither heats nor cools the
#: zone on its own.
#:
#: **A fixed neutral setpoint does NOT establish dehumidification.** The plan
#: for chilled beams and radiant (`docs/HVAC_MODERN_SYSTEMS_PLAN.md`, 1.1) is
#: explicit that latent control needs its own control inputs, a measured
#: dew-point margin and a humid-weather lockout test before any cooled
#: surface may be enabled. This row does not attempt that and must not be
#: treated as having done it.
NEUTRAL_SUPPLY_C = 20.0


class CentralDoas(BaseSystem):
    """One `AirLoopHVACDedicatedOutdoorAirSystem` over per-zone air loops."""

    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        always_on = model.alwaysOnDiscreteSchedule()
        heating_type = self.config.get('heating_type', 'Electric')

        # A loop per zone, so each has its own OA inlet for the DOAS to feed.
        # One shared loop would make the central unit indistinguishable from
        # an ordinary OA system on that loop, which is the graph this row
        # exists to produce.
        air_loops = []
        for zone in zones:
            air_loop = openstudio.model.AirLoopHVAC(model)
            self.apply_system_sizing(air_loop)
            fan = openstudio.model.FanConstantVolume(model, always_on)
            fan.setName(f'{zone.nameString()} Supply Fan')
            fan.addToNode(air_loop.supplyInletNode())
            zone_clg = coils.dx_cooling_single_speed(
                model, always_on, name=f'{zone.nameString()} DX Clg Coil')
            zone_clg.addToNode(air_loop.supplyInletNode())
            zone_htg = coils.heating_coil(model, heating_type, always_on,
                                          hw_loop=hw_loop)
            zone_htg.addToNode(air_loop.supplyInletNode())
            # EACH SERVED LOOP NEEDS ITS OWN OUTDOOR-AIR SYSTEM. This is a
            # hard precondition of `AirLoopHVACDedicatedOutdoorAirSystem`
            # and the SDK does not report it: the forward translator hits
            # `BOOST_ASSERT: Assertion oas failed` and the process DUMPS
            # CORE, with no exception and no translator error to catch.
            # Measured both ways on a two-zone model — without it the
            # translator crashes, with it the model translates to 73 objects
            # and zero errors.
            #
            # The DOAS does not replace this OA system; it FEEDS it, which
            # is why the dedicated unit's own coils sit on its stream and
            # these stay bare.
            self.build_oa_system(model).addToNode(air_loop.supplyInletNode())
            terminal = (openstudio.model
                        .AirTerminalSingleDuctConstantVolumeNoReheat(
                            model, always_on))
            air_loop.addBranchForZone(
                zone, terminal.to_StraightComponent().get())
            setpoint = openstudio.model.SetpointManagerSingleZoneReheat(model)
            setpoint.setControlZone(zone)
            setpoint.addToNode(air_loop.supplyOutletNode())
            air_loops.append(air_loop)

        # THE CENTRAL UNIT. `build_oa_system` is not used here: that helper
        # attaches an OA system to one loop's supply path, and this one
        # belongs to no loop — the `AirLoopHVACDedicatedOutdoorAirSystem`
        # owns it and distributes its air.
        controller = openstudio.model.ControllerOutdoorAir(model)
        controller.setName('Central DOAS OA Controller')
        oa_system = openstudio.model.AirLoopHVACOutdoorAirSystem(
            model, controller)
        dedicated = (openstudio.model
                     .AirLoopHVACDedicatedOutdoorAirSystem(oa_system))
        dedicated.setName('Central DOAS')
        for air_loop in air_loops:
            dedicated.addAirLoop(air_loop)

        # Preconditioning. `addToNode(outboardOANode())` always inserts at
        # the OUTDOOR-AIR INLET, so each component added pushes the previous
        # ones inboard: the LAST added is nearest the outdoors. Adding fan,
        # then precool, then preheat therefore yields the physical order a
        # DOAS runs in, outdoors inward — preheat to protect the coil from
        # freezing air, precool to condition it, then the fan that
        # distributes it.
        #
        # That also puts the COOLING COIL far from its own outdoor-air
        # system, which is the arrangement a depth-bounded attribution walk
        # could not resolve (Fable, `228`): with the coil nearest the OAS it
        # sits four hops away and every version of that walk found it. This
        # row exists partly so the containment rung is exercised by a built
        # system instead of a hand-made fixture.
        # DX, not a water coil. A `Coil:Cooling:Water` with no plant is
        # accepted by the SDK and refused by EnergyPlus — "Missing required
        # property 'water_inlet_node_name'" and a Fatal — and this row
        # requests no chiller, so it must not depend on one. The existing
        # `doas` family makes the same choice for the same reason.
        #
        # The attribution topology is unaffected: a DX cooling coil on the
        # OA stream is still a cooling object at the far end of that chain
        # from its own outdoor-air system, which is the arrangement the
        # containment rung exists for.
        # `Fan:SystemModel`, because EnergyPlus REFUSES the alternatives
        # here: "the FAN:CONSTANTVOLUME can not be used as a component.
        # Please remove it." A dedicated unit's fan must be the system or
        # component model, and the SDK accepts the wrong one silently —
        # only a run says so.
        supply_fan = openstudio.model.FanSystemModel(model)
        supply_fan.setName('DOAS Supply Fan')
        supply_fan.addToNode(oa_system.outboardOANode().get())
        if chw_loop is None:
            precool = coils.dx_cooling_single_speed(
                model, always_on, name='DOAS Precool Coil')
        else:
            # A row with `needs_chiller` gets the water coil, which is the
            # more usual DOAS arrangement where a plant exists. The builder
            # creates the loop from that flag and passes it here; there is
            # no public `chw_loop=` argument, so a branch reachable only by
            # one would be dead code no catalogue row could exercise.
            precool = openstudio.model.CoilCoolingWater(model, always_on)
            precool.setName('DOAS Precool Water Coil')
        precool.addToNode(oa_system.outboardOANode().get())
        if chw_loop is not None:
            chw_loop.addDemandBranchForComponent(precool)
        preheat = coils.heating_coil(model, heating_type, always_on,
                                     hw_loop=hw_loop)
        preheat.setName('DOAS Preheat Coil')
        preheat.addToNode(oa_system.outboardOANode().get())
        # THE COILS NEED A SETPOINT, and EnergyPlus says so rather than
        # guessing: "Missing temperature setpoint for heating coil ... use a
        # Setpoint Manager to establish a setpoint at the coil temperature
        # setpoint node", and the same for the DX coil's system. Creating
        # the schedule without a manager to apply it leaves both coils
        # uncontrolled and the run Fatal.
        #
        # ONE PER CONTROLLED NODE, not one for the stream. A setpoint at
        # the stream's inboard end satisfied the DX coil's system and left
        # the heating coil still Fatal: each coil reads a setpoint at ITS
        # OWN outlet. So every node inboard of the outdoor-air inlet gets
        # one — the inlet itself is raw outdoor air and has nothing to
        # control.
        #
        # The same neutral value at each is the series preheat/precool
        # arrangement: cold outdoor air is raised toward it and hot outdoor
        # air lowered toward it, so only one coil acts at a time.
        neutral = schedules.constant_ruleset(
            model, 'DOAS Neutral Supply Air Temp', NEUTRAL_SUPPLY_C)
        nodes = [component.to_Node().get()
                 for component in oa_system.oaComponents()
                 if component.to_Node().is_initialized()]
        for node in nodes[1:]:
            openstudio.model.SetpointManagerScheduled(
                model, neutral).addToNode(node)

        for air_loop in air_loops:
            naming.apply(
                namer, air_loop,
                system_name=self.config['name'], sys_abbr='cdoas',
                sys_oa='doas',
                parts={'sys_hr': 'none', 'sys_clg': 'dx',
                       'sys_htg': heating_type, 'sys_sf': 'cv',
                       'zone_htg': 'none', 'zone_clg': 'none',
                       'sys_rf': 'none'},
                suffix=None)
        return air_loops
