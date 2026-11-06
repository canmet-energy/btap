"""#163 — warn when a declaration contradicts the model, narrowed to one value.

PR #162 grouped FOUR refrigerant-cycle values and was withdrawn after four
review rounds, each exempting one more arrival path. The premise was the
defect: `packaged_terminal`, `room_air_conditioner` and `heat_pump` name
equipment routinely found ZONAL under a hydronic make-up-air unit, so the
declaration and the model AGREE and the warning was false. Only
`air_cooled_unitary` is a claim about the LOOP's own cooling.

The withdrawn work is preserved at `wip/155-contradiction-warning-4-rounds`
(`3a90ec42`) and was read rather than re-derived.

**Two of these tests exist because the old module could not see its own bug.**
Stamping every warning with `groups[0]`'s loop name, and checking only
`groups[:1]`, both passed the entire 659-line module at that tag, because
every fixture it had was single-loop.
"""

from __future__ import annotations

import unittest

from tests.support import needs_sdk


@needs_sdk
class ContradictionBase(unittest.TestCase):

    def setUp(self):
        import openstudio

        self.os = openstudio
        self.model = openstudio.model.Model()
        self.sched = openstudio.model.ScheduleConstant(self.model)
        self.sched.setValue(1.0)

    def chilled_water_loop(self, name, declare=None):
        """An air loop whose own cooling is a chilled-water coil."""
        os = self.os
        loop = os.model.AirLoopHVAC(self.model)
        loop.setName(name)
        os.model.FanConstantVolume(self.model, self.sched).addToNode(
            loop.supplyInletNode())
        chw = os.model.PlantLoop(self.model)
        chw.setName(f'{name} CHW')
        os.model.PumpVariableSpeed(self.model).addToNode(chw.supplyInletNode())
        chw.addSupplyBranchForComponent(
            os.model.ChillerElectricEIR(self.model))
        coil = os.model.CoilCoolingWater(self.model, self.sched)
        coil.addToNode(loop.supplyOutletNode())
        chw.addDemandBranchForComponent(coil)
        if declare is not None:
            from btap.modeling.hvac import equipment_class

            equipment_class.declare(loop, declare)
        return loop

    def add_dx_to(self, loop):
        self.os.model.CoilCoolingDXSingleSpeed(self.model).addToNode(
            loop.supplyOutletNode())

    def zone_on(self, loop, name, with_ptac=False):
        os = self.os
        zone = os.model.ThermalZone(self.model)
        zone.setName(name)
        space = os.model.Space(self.model)
        space.setThermalZone(zone)
        thermostat = os.model.ThermostatSetpointDualSetpoint(self.model)
        temperature = os.model.ScheduleConstant(self.model)
        temperature.setValue(21.0)
        thermostat.setHeatingSetpointTemperatureSchedule(temperature)
        thermostat.setCoolingSetpointTemperatureSchedule(temperature)
        zone.setThermostatSetpointDualSetpoint(thermostat)
        terminal = os.model.AirTerminalSingleDuctConstantVolumeNoReheat(
            self.model, self.sched)
        loop.addBranchForZone(zone, terminal.to_StraightComponent().get())
        if with_ptac:
            os.model.ZoneHVACPackagedTerminalAirConditioner(
                self.model, self.sched,
                os.model.FanConstantVolume(self.model, self.sched),
                os.model.CoilHeatingElectric(self.model, self.sched),
                os.model.CoilCoolingDXSingleSpeed(self.model),
            ).addToThermalZone(zone)
        return zone

    def contradictions(self):
        from btap.audit import AuditLog
        from btap.modeling.hvac import classify

        audit = AuditLog()
        self.facts = classify.characterize(self.model, audit=audit)
        return [e for e in audit.warnings
                if 'equipment_class' in e['action']]


class TestTheHydronicClaimFiresForOneValueOnly(ContradictionBase):

    def test_air_cooled_unitary_on_a_chilled_water_loop_WARNS(self):
        loop = self.chilled_water_loop('CHW loop',
                                       declare='air_cooled_unitary')
        self.zone_on(loop, 'Z1')

        found = self.contradictions()
        self.assertEqual(1, len(found), found)
        self.assertEqual('CHW loop', found[0]['target'])
        self.assertIn('CHILLED WATER', found[0]['action'])

    def test_the_other_three_values_are_SILENT_on_the_same_loop(self):
        """The fourth-round finding, and the reason #162 was withdrawn.

        Each of these names equipment routinely found ZONAL under a hydronic
        make-up-air unit, so the declaration and the model agree.
        """
        for value in ('packaged_terminal', 'room_air_conditioner',
                      'heat_pump'):
            with self.subTest(declared=value):
                self.setUp()
                loop = self.chilled_water_loop('CHW loop', declare=value)
                self.zone_on(loop, 'Z1')
                self.assertEqual([], self.contradictions())

    def test_a_chilled_water_loop_with_a_zonal_PTAC_is_silent(self):
        """Round four's case, with its precondition asserted.

        A zonal PTAC under a chilled-water loop declaring `packaged_terminal`
        is the model describing itself correctly.
        """
        loop = self.chilled_water_loop('CHW loop',
                                       declare='packaged_terminal')
        self.zone_on(loop, 'Z1', with_ptac=True)

        self.assertEqual([], self.contradictions())
        group = next(g for g in self.facts['zone_groups']
                     if g['air_loop'] == 'CHW loop')
        self.assertIn('ptac', group['zonal_units'],
                      'precondition: without the PTAC recognised, this test '
                      'would pass for the wrong reason')

    def test_a_loop_with_BOTH_chilled_water_and_DX_is_silent(self):
        """No catalogue row carries both, so this is bare objects — and a DX
        coil present means the refrigerant-cycle claim is corroborated."""
        loop = self.chilled_water_loop('Mixed loop',
                                       declare='air_cooled_unitary')
        self.add_dx_to(loop)
        self.zone_on(loop, 'Z1')

        self.assertEqual([], self.contradictions())
        group = next(g for g in self.facts['zone_groups']
                     if g['air_loop'] == 'Mixed loop')
        self.assertTrue(group['loop_dx_cooling'])
        self.assertTrue(group['loop_hydronic_cooling'])

    def test_no_declaration_is_silence_not_contradiction(self):
        """A declaration exists for identity the topology cannot establish, so
        absence must never warn."""
        loop = self.chilled_water_loop('CHW loop')
        self.zone_on(loop, 'Z1')
        self.assertEqual([], self.contradictions())


class TestTheContainerBranchIsUnchanged(ContradictionBase):
    """Sound through all four rounds of #162 and needing no exemption."""

    def packaged_loop(self, name, declare):
        os = self.os
        loop = os.model.AirLoopHVAC(self.model)
        loop.setName(name)
        unitary = os.model.AirLoopHVACUnitarySystem(self.model)
        unitary.setCoolingCoil(os.model.CoilCoolingDXSingleSpeed(self.model))
        unitary.setSupplyFan(
            os.model.FanConstantVolume(self.model, self.sched))
        unitary.addToNode(loop.supplyOutletNode())
        from btap.modeling.hvac import equipment_class

        equipment_class.declare(loop, declare)
        return loop

    def test_built_up_on_a_packaged_container_WARNS(self):
        loop = self.packaged_loop('Packaged loop', 'built_up')
        self.zone_on(loop, 'Z1')

        found = self.contradictions()
        self.assertEqual(1, len(found), found)
        self.assertIn('not factory-packaged', found[0]['action'])
        self.assertEqual('Packaged loop', found[0]['target'])

    def test_no_exemption_reaches_the_container_branch(self):
        """PR #162's `ventilation_sized` exemption short-circuited BEFORE this
        branch. It is deleted, so a ventilation-sized packaged loop must still
        warn."""
        loop = self.packaged_loop('MAU loop', 'built_up')
        self.zone_on(loop, 'Z1')
        sizing = loop.sizingSystem()
        sizing.setTypeofLoadtoSizeOn('VentilationRequirement')
        sizing.setAllOutdoorAirinCooling(True)
        sizing.setAllOutdoorAirinHeating(True)

        found = self.contradictions()
        self.assertEqual(1, len(found), found)
        self.assertEqual('MAU loop', found[0]['target'])


class TestTwoLoopsBecauseOneCouldNotSeeTheBug(ContradictionBase):
    """The gap that let two mutations pass 659 lines of tests at `3a90ec42`.

    Every fixture there was single-loop, so stamping each warning with
    `groups[0]`'s name, or checking only `groups[:1]`, was invisible.
    """

    def setUp(self):
        super().setUp()
        self.clean = self.chilled_water_loop('A clean CHW loop')
        self.zone_on(self.clean, 'Z-clean')
        self.offender = self.chilled_water_loop('The offending loop',
                                                declare='air_cooled_unitary')
        self.zone_on(self.offender, 'Z-offender')

    def test_the_warning_names_the_OFFENDING_loop_not_the_first_one(self):
        found = self.contradictions()
        self.assertEqual(1, len(found), found)
        self.assertEqual(
            'The offending loop', found[0]['target'],
            "stamping every warning with groups[0]'s loop name passed the "
            'whole module at 3a90ec42 — every fixture was single-loop')

    def test_a_loop_AFTER_the_first_is_still_checked(self):
        """`groups` is ordered by loop name, so 'A clean CHW loop' sorts first
        and the offender is NOT groups[0]. Checking only `groups[:1]` would
        find nothing."""
        names = [g['air_loop'] for g in
                 self.contradictions() and self.facts['zone_groups']
                 if g['air_loop'] is not None]
        self.assertEqual('A clean CHW loop', names[0],
                         'precondition: the clean loop must sort first, or '
                         'this test cannot catch a groups[:1] check')
