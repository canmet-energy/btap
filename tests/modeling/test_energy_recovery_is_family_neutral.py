"""#217: energy recovery belongs to every family that builds outdoor air.

It was implemented inside `systems/vav_reheat.py`, so of the TEN families
calling `BaseSystem.build_oa_system` only that one could carry it — 55 of 77
OA-bearing catalogue rows across nine families had no heat-recovery option at
all, including `doas`, where a recovery device is arguably the expected
configuration, and `mau_ptac`, where an HRV on a make-up air unit is standard
practice in the climate NECB addresses.

Neither public function was ever VAV-specific, so the move to
`hvac/energy_recovery.py` is a pure relocation. What is NEW is the attachment
point: `build_oa_system` returns an UNATTACHED system whose outboard-OA,
mixed-air and return-air nodes do not exist yet, so the shared step had to be
create-AND-attach (`add_oa_system`) or attach-only (`attach_oa_system`) rather
than the creation call it first appeared to be.
"""
import unittest

from btap.modeling import build_system
from btap.modeling.hvac import catalog, energy_recovery
from tests.necb.hvac_helpers import load_fixture, sorted_zones
from tests.support import needs_sdk

# A complete, valid recovery request. All eleven parameters, because
# `validate_energy_recovery` requires every one of them.
ERV = {
    'needs_erv': True,
    'erv_heat_exchanger_type': 'Plate',
    'erv_sensible_effectiveness': 0.75,
    'erv_latent_effectiveness': 0.0,
    'erv_frost_control_type': 'ExhaustOnly',
    'erv_frost_threshold_temperature': -23.3,
    'erv_initial_defrost_time_fraction': 0.167,
    'erv_defrost_time_fraction_increase_rate': 1.44,
    'erv_economizer_lockout': True,
    'erv_supply_air_outlet_temperature_control': True,
    'erv_bypass_control_type': 'BypassWhenOAFlowGreaterThanMinimum',
    'erv_nominal_electric_power': 150.0,
}

# Every family that reaches an outdoor-air stream. Ten call
# `build_oa_system` directly; `chilled_beams` reaches one through
# `doas.build_dehumidifying_doas`, a SECOND module-level attach site that
# migrating only `DOAS.build` left behind — so a chilled-beam system
# requesting recovery silently got none until that was fixed too.
OA_FAMILIES = ('chilled_beams', 'crah', 'doas', 'doas_pthp', 'dual_duct',
               'evap_cooler', 'fan_coils', 'furnace', 'mau_ptac', 'psz',
               'vav_reheat')


def _build(name, **config):
    model = load_fixture()
    build_system(model, name, sorted_zones(model), config=dict(config))
    return model


def _a_row_of(family):
    return next(r['id'] for r in catalog.rows() if r['family'] == family)


@needs_sdk
class TestEveryOABearingFamilyCanCarryRecovery(unittest.TestCase):
    def test_recovery_is_OFF_unless_asked(self):
        """The control for the whole suite: every one of these builds no
        exchanger without the request, so a positive result above is the
        request working rather than a device that was always there."""
        for family in OA_FAMILIES:
            with self.subTest(family=family):
                model = _build(_a_row_of(family))
                self.assertEqual(
                    0, len(model.getHeatExchangerAirToAirSensibleAndLatents()),
                    f'{family} built recovery nobody asked for')

    def test_each_family_builds_an_exchanger_when_asked(self):
        """`crah` is excluded: it recirculates room air and builds no OA
        system unless a row asks for ventilation, so it has nothing to recover
        from. That case is pinned separately below."""
        for family in OA_FAMILIES:
            if family == 'crah':
                continue
            with self.subTest(family=family):
                model = _build(_a_row_of(family), **ERV)
                self.assertGreater(
                    len(model.getHeatExchangerAirToAirSensibleAndLatents()), 0,
                    f'{family} requested recovery and built none')

    def test_the_exchanger_sits_on_the_OUTDOOR_AIR_stream(self):
        """Building one somewhere else would satisfy a count and recover
        nothing. `classify` finds recovery by walking `oaComponents`."""
        from btap._compat import opt

        model = _build(_a_row_of('mau_ptac'), **ERV)
        found = []
        for loop in model.getAirLoopHVACs():
            oa = loop.airLoopHVACOutdoorAirSystem()
            if not oa.is_initialized():
                continue
            found += [
                c.nameString() for c in opt(oa).oaComponents()
                if c.to_HeatExchangerAirToAirSensibleAndLatent().is_initialized()
            ]
        self.assertTrue(found, 'no exchanger on any outdoor-air stream')

    def test_a_family_that_has_no_outdoor_air_builds_none(self):
        """`crah` without ventilation has no OA stream, so HX=0 is CORRECT —
        the comment in `crah.py` says a CRAH recirculates room air. With
        ventilation it gains the stream and the exchanger."""
        name = _a_row_of('crah')
        self.assertEqual(
            0,
            len(_build(name, **dict(ERV, ventilation=False))
                .getHeatExchangerAirToAirSensibleAndLatents()))
        self.assertEqual(
            1,
            len(_build(name, **dict(ERV, ventilation=True))
                .getHeatExchangerAirToAirSensibleAndLatents()))


@needs_sdk
class TestTheFlagAloneIsNotARequest(unittest.TestCase):
    """`needs_erv` cannot supply effectiveness, frost control, bypass
    behaviour or parasitic power. A caller that sets it without them must FAIL
    rather than receive a device built from invented defaults — otherwise
    making recovery family-neutral would just spread a fabrication."""

    def test_needs_erv_without_parameters_uses_the_DEFAULT_profile(self):
        """Changed 2026-11-14. This asserted a refusal, on the reasoning that
        a boolean cannot supply effectiveness, frost control or parasitic
        power. It cannot — but a NAMED, CITED profile can, and phylroy asked
        for a default so a user reaches a functioning HVAC. What the refusal
        actually protected against was the SDK's uncited defaults, which a
        declared profile does not reintroduce."""
        model = _build(_a_row_of('psz'), needs_erv=True)
        hx = model.getHeatExchangerAirToAirSensibleAndLatents()[0]
        self.assertEqual('ExhaustOnly', hx.frostControlType())

    def test_an_out_of_range_effectiveness_is_refused(self):
        with self.assertRaises(ValueError):
            _build(_a_row_of('psz'), **dict(ERV,
                                            erv_sensible_effectiveness=1.4))

    def test_an_unknown_exchanger_type_is_refused(self):
        with self.assertRaises(ValueError):
            _build(_a_row_of('psz'),
                   **dict(ERV, erv_heat_exchanger_type='Enthalpy Wheel'))


@needs_sdk
class TestTheTwoCatalogueRowsAreUnchanged(unittest.TestCase):
    """The safety property of the whole change.

    Only two shipped rows set `needs_erv`, both `vav_reheat`. Their output was
    compared at the ForwardTranslator level before and after the move and was
    byte-identical; these assertions are what a future reader can run.
    """

    def test_each_shipped_ERV_row_still_builds_one_exchanger(self):
        rows = [r['id'] for r in catalog.rows() if r.get('needs_erv')]
        self.assertEqual(2, len(rows), 'the shipped ERV row count moved')
        for name in rows:
            with self.subTest(row=name):
                model = _build(name)
                self.assertEqual(
                    1, len(model.getHeatExchangerAirToAirSensibleAndLatents()))
                self.assertEqual(
                    1, len(model.getSetpointManagerOutdoorAirPretreats()),
                    'the pretreat setpoint manager did not come with it')

    def test_the_exchanger_is_tagged_as_catalogue_sourced(self):
        """`teardown` uses this tag to tell a catalogue-built exchanger from a
        proposed one, so losing it in the move would break the NECB path."""
        name = next(r['id'] for r in catalog.rows() if r.get('needs_erv'))
        model = _build(name)
        exchanger = model.getHeatExchangerAirToAirSensibleAndLatents()[0]
        source = exchanger.additionalProperties().getFeatureAsString(
            energy_recovery.ENERGY_RECOVERY_SOURCE_FEATURE)
        self.assertTrue(source.is_initialized())
        self.assertEqual(
            energy_recovery.ENERGY_RECOVERY_SOURCE_CATALOG, source.get())


@needs_sdk
class TestZoneLevelRecoveryIsTheOtherMechanism(unittest.TestCase):
    """phylroy, 2026-11-13: "we can apply an ERV to any system, right?"

    Nearly — and it takes TWO devices. `attach_oa_system` puts an exchanger on
    an air loop's outdoor-air stream, which the eleven OA-bearing families
    reach. The other twelve build no outdoor air at all, and for those the
    device is a `ZoneHVAC:EnergyRecoveryVentilator`, which carries its own
    supply and exhaust fans and IS that zone's ventilation source.

    `needs_zone_erv` is separate from `needs_erv` because they are different
    devices with different parameters; reusing the flag would have changed
    what the two shipped `needs_erv` rows build.
    """

    ZONAL = ('baseboards', 'unit_heaters', 'vrf', 'wshp', 'zone_terminal')

    def test_a_zonal_family_can_carry_one(self):
        for family in self.ZONAL:
            with self.subTest(family=family):
                model = _build(_a_row_of(family), needs_zone_erv=True)
                self.assertEqual(
                    len(sorted_zones(load_fixture())),
                    len(model.getZoneHVACEnergyRecoveryVentilators()),
                    f'{family} did not get one per zone')

    def test_none_appears_unless_asked(self):
        for family in self.ZONAL:
            with self.subTest(family=family):
                model = _build(_a_row_of(family))
                self.assertEqual(
                    0, len(model.getZoneHVACEnergyRecoveryVentilators()))

    def test_a_CENTRALLY_ventilated_family_is_REFUSED(self):
        """The guard that matters.

        A zone ERV brings its own outdoor air, so adding one to a family that
        already ventilates centrally moves roughly twice the outdoor air the
        building asked for. Measured before the guard: `psz`, `doas` and
        `vav_reheat` each built a central OA system AND one ERV per zone, and
        the result simulates and reports plausible numbers.
        """
        for family in ('psz', 'doas', 'vav_reheat', 'mau_ptac'):
            with self.subTest(family=family):
                with self.assertRaises(ValueError) as caught:
                    _build(_a_row_of(family), needs_zone_erv=True)
                self.assertIn('ventilate twice', str(caught.exception))

    def test_the_refusal_comes_BEFORE_the_old_system_is_torn_down(self):
        """#244: the guard above ran after `remove_existing` had torn the
        zones' existing system down, so a refused rebuild left them with
        neither. The model must come back exactly as it was: same object
        count, same objects by type and name."""
        def inventory(model):
            return sorted((o.iddObjectType().valueName(), o.nameString())
                          for o in model.modelObjects())
        for existing, replacement in (
                ('bb-elecbb', _a_row_of('psz')),
                ('bb-elecbb', _a_row_of('vav_reheat')),
                (_a_row_of('psz'), _a_row_of('doas')),
                ('bb-elecbb', 'doas-vrf-elec'),          # a composite
                ('bb-elecbb', 'evap-elecbb')):           # a composite
            with self.subTest(existing=existing, replacement=replacement):
                model = load_fixture()
                build_system(model, existing, sorted_zones(model))
                before = inventory(model)
                with self.assertRaises(ValueError) as caught:
                    build_system(model, replacement, sorted_zones(model),
                                 remove_existing=True,
                                 config={'needs_zone_erv': True})
                self.assertIn('ventilate twice', str(caught.exception))
                self.assertEqual(before, inventory(model),
                                 'a refused rebuild must leave the model untouched')

    def test_an_accepted_request_still_builds_once_per_zone(self):
        """The probe runs on a clone: the real model gets one device per zone
        and nothing left over from the dry run."""
        model = load_fixture()
        build_system(model, _a_row_of('psz'), sorted_zones(model))
        build_system(model, _a_row_of('baseboards'), sorted_zones(model),
                     remove_existing=True, config={'needs_zone_erv': True})
        self.assertEqual(len(sorted_zones(model)),
                         len(model.getZoneHVACEnergyRecoveryVentilators()))
        self.assertEqual(0, len(model.getAirLoopHVACs()), 'the old loop is gone')

    def test_the_standalone_row_and_the_option_build_the_SAME_device(self):
        """`systems/zone_ervs.py` now delegates to the shared function, so the
        shipped 'zone-erv' row cannot drift from the option."""
        standalone = _build('zone-erv')
        option = _build(_a_row_of('baseboards'), needs_zone_erv=True)
        self.assertEqual(
            len(standalone.getZoneHVACEnergyRecoveryVentilators()),
            len(option.getZoneHVACEnergyRecoveryVentilators()))
        for model in (standalone, option):
            hx = model.getHeatExchangerAirToAirSensibleAndLatents()[0]
            # These WERE the SDK defaults — 0.76 / 0.68 / frostControlType
            # 'None' — pinned here so that changing them would have to be a
            # deliberate act on this row's output rather than a side effect.
            # 2026-11-14 is that act: phylroy raised that no frost protection
            # makes no sense for northern Canada, the pinned gem sets
            # ExhaustOnly in all five of its rows, and the row now carries
            # `erv_profile: plate_erv`.
            #
            # The SDK pair was also internally inconsistent: a Plate core with
            # latent 0.68, which is enthalpy-WHEEL performance. The profile's
            # 0.564 is the gem's measured plate figure.
            self.assertAlmostEqual(
                0.755, hx.sensibleEffectivenessat100HeatingAirFlow())
            self.assertAlmostEqual(
                0.564, hx.latentEffectivenessat100HeatingAirFlow())
            self.assertEqual('ExhaustOnly', hx.frostControlType())
            self.assertAlmostEqual(-23.3, hx.thresholdTemperature())


if __name__ == '__main__':
    unittest.main()
