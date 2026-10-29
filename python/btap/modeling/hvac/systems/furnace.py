"""Forced-air furnace / central AC (port of the generic
model_add_furnace_central_ac essentials): a CV air loop with a heating coil
(config 'heating': true) and/or single-speed DX cooling (config 'cooling':
true); outdoor air per config 'ventilation'.

Three switches make this family serve the reconstruction cases issue #152
asks for without a parallel builder:

- `heating_type` names the coil fuel, routed through `coils.heating_coil`, so
  'Hot Water' gives a hydronic coil off the system's hot-water loop. Defaults
  to 'Gas', which is what the coil was hard-coded to.
- `cooling` already defaulted to FALSE, so a heating-only air handler is
  existing behaviour rather than something new.
- `per_zone` chooses one loop per zone or ONE SHARED loop serving all of them.
  It defaults to TRUE here, unlike `psz`, where shared is the default —
  because `Forced air furnace` has always built per zone and
  `tests/modeling/test_cbecs_families.py` asserts one air loop per zone for
  it. Preserving a shipped row's behaviour outranks consistency between
  families.

A shared loop tracks ONE control zone's thermostat, like `psz`'s shared form:
every served zone gets the same supply air, which is the point when
reconstructing a multiple-zone loop and is wrong if the zones were really
separate systems."""

from __future__ import annotations

import openstudio

from btap._compat import sorted_by_name
from btap.modeling.hvac import equipment_class
from btap.modeling.hvac.components import coils
from btap.modeling.hvac.systems.base_system import BaseSystem


class Furnace(BaseSystem):
    def preflight(self, model, zones, control_zone=None, namer='default',
                  remove_existing=False):
        """Refuse an impossible combination BEFORE anything is torn down.

        `builder.build_system` removes the model's existing HVAC and only then
        calls `build`, so a refusal raised mid-build leaves the submitter with
        neither their original system nor a complete new one — and, when the
        loop, fan and coil are already placed, a dangling air loop too. Fable
        witnessed exactly that in the PR #153 review: air loops, fans and gas
        coils went 0 to 1 and stayed. `preflight` runs before the teardown,
        which is why `Crah` uses it for the same kind of check.
        """
        if self.config.get('reheat') and self.config.get('per_zone', True):
            raise ValueError(
                f"{self.config['name']!r} sets both 'reheat' and 'per_zone': a "
                f"per-zone loop already tracks its own zone, so a reheat "
                f"terminal has nothing to correct")
        return None

    def build(self, model, zones, control_zone=None, namer='default',
              hw_loop=None, chw_loop=None):
        ordered = sorted_by_name(zones)
        if self.config.get('per_zone', True):
            return [self._build_loop(model, [zone], zone, hw_loop=hw_loop,
                                     suffix=zone.nameString())
                    for zone in ordered]

        if not ordered:
            return []
        # A shared loop needs a control zone to track. The caller's choice
        # wins; the first served zone by name is the fallback, which keeps the
        # build deterministic rather than depending on model ordering.
        return [self._build_loop(model, ordered, control_zone or ordered[0],
                                 hw_loop=hw_loop, suffix=None)]

    def _build_loop(self, model, zones, control_zone, *, hw_loop, suffix):
        always_on = model.alwaysOnDiscreteSchedule()
        heating = self.config.get('heating', True)
        cooling = self.config.get('cooling', False)
        ventilation = self.config.get('ventilation', True)
        heating_type = self.config.get('heating_type', 'Gas')

        air_loop = openstudio.model.AirLoopHVAC(model)
        name = self.config['name']
        air_loop.setName(f"{name} | {suffix}" if suffix else name)

        fan = openstudio.model.FanConstantVolume(model, always_on)
        fan.setName(f"{air_loop.nameString()} Fan")

        supply_inlet_node = air_loop.supplyInletNode()
        fan.addToNode(supply_inlet_node)
        if heating:
            # Through `coils.heating_coil`, which maps 'Hot Water' to a
            # CoilHeatingWater on `hw_loop` and RAISES when the loop is
            # missing. The coil was hard-coded `CoilHeatingGas`; 'Gas' is the
            # default so every shipped row keeps the coil it had.
            htg = coils.heating_coil(model, heating_type, always_on,
                                     hw_loop=hw_loop)
            htg.setName(f"{air_loop.nameString()} Heating Coil")
            htg.addToNode(supply_inlet_node)
        if cooling:
            clg = openstudio.model.CoilCoolingDXSingleSpeed(model)
            clg.setName(f"{air_loop.nameString()} Cooling Coil")
            clg.addToNode(supply_inlet_node)
        if ventilation:
            self.build_oa_system(model).addToNode(supply_inlet_node)

        # A row may DECLARE what its equipment physically is, and that
        # declaration is written into the model rather than consulted from the
        # catalogue at classification time. The difference is the whole point:
        # a loop name resolved later makes the answer depend on who authored
        # the file, while a declaration serialized here is a fact about the
        # building that any consumer reads the same way — which is what Sol
        # asked for in `329` and is consistent with his `331` ruling against
        # name resolution. `furnace` builds everything from a shared air
        # handler, so this cannot live on the BUILDER: one row is a residential
        # split AC and another is a Campus unit whose class nobody has
        # established, and the undeclared one must stay undeclared.
        declared = self.config.get('equipment_class')
        if declared is not None:
            equipment_class.declare(air_loop, declared)

        spm = openstudio.model.SetpointManagerSingleZoneReheat(model)
        spm.setControlZone(control_zone)
        spm.addToNode(air_loop.supplyOutletNode())

        # `reheat` gives each zone a CONSTANT-VOLUME REHEAT terminal instead of
        # an uncontrolled diffuser — issue #152 requirement 2, three
        # MaintenanceShop-Small loops with water reheat terminals. Neither the
        # terminal class nor the coil is new: `mau_ptac` already builds this
        # exact pair on its reference-heat-pump branch. Terminal reheat is only
        # meaningful on a shared loop, where one supply temperature serves
        # zones with different loads, so it is refused per zone rather than
        # silently ignored.
        reheat = self.config.get('reheat')
        for zone in zones:
            if reheat:
                rh_coil = coils.heating_coil(model, reheat, always_on,
                                             hw_loop=hw_loop)
                rh_coil.setName(f"{zone.nameString()} Reheat Coil")
                terminal = openstudio.model.\
                    AirTerminalSingleDuctConstantVolumeReheat(
                        model, always_on, rh_coil)
            else:
                terminal = openstudio.model.AirTerminalSingleDuctUncontrolled(
                    model, always_on)
            air_loop.addBranchForZone(zone, terminal.to_StraightComponent())
        return air_loop
