"""Named ERV product profiles, and no implicit default. #217.

phylroy asked what the defaults should be for an ERV's properties. The answer
the evidence forced is: no single default, because the right values differ by
device, and the Code's own numbers belong on the other side of a layer
boundary.

- NECB 5.2.10.1.(4)'s 50% enthalpy minimum and 5.2.10.1.(6)'s overshoot
  control are applied by `btap/codes/necb/hvac/energy_recovery.py` on the
  reference path. Table 5.2.10.4's 65/55/45% by design temperature is a CSA
  C439 dwelling-unit RATING condition. None of them belongs in
  `btap.modeling`, whose value is having no opinion — the pinned gem's own
  default row, `NECB_Default_All` at 0.5/0.5, IS that 50% minimum, which is
  exactly why it is not reproduced here.
- The profiles are keyed CORE x TRANSFER. A plate core can be sensible-only
  (HRV) or an enthalpy membrane (ERV), and the device's NAME is derived from
  whether latent > 0, so one `plate` profile carrying latent 0.564 would
  contradict the shipped plate-HRV row's own name. That decomposition came
  from a Fable review; mine was core-only and would have shipped the
  contradiction.
"""
import unittest

from btap.modeling import build_system
from btap.modeling.hvac import catalog, energy_recovery
from tests.necb.hvac_helpers import load_fixture, sorted_zones
from tests.support import needs_sdk


def _a_row_of(family):
    return next(r['name'] for r in catalog.rows() if r['family'] == family)


class TestTheProfilesThemselves(unittest.TestCase):
    """No SDK needed: the file and the resolver are plain data."""

    def test_the_three_expected_profiles_exist(self):
        self.assertEqual({'plate_erv', 'rotary_erv', 'plate_hrv'},
                         set(energy_recovery.profiles()))

    def test_an_HRV_profile_recovers_NO_moisture(self):
        """Definitional: an HRV recovers heat, not moisture. The device name
        is derived from latent > 0, so a non-zero latent here would produce a
        thing called an ERV from a profile called plate_hrv."""
        self.assertEqual(
            0.0,
            energy_recovery.profiles()['plate_hrv'][
                'erv_latent_effectiveness'])

    def test_an_ERV_profile_DOES_recover_moisture(self):
        for name in ('plate_erv', 'rotary_erv'):
            with self.subTest(profile=name):
                self.assertGreater(
                    energy_recovery.profiles()[name][
                        'erv_latent_effectiveness'], 0.0)

    def test_a_plate_HRV_frosts_EARLIER_than_a_plate_ERV(self):
        """RenewAire: a static-plate ERV has up to an 18 F LOWER frost
        threshold than a comparable HRV. So the HRV's threshold must be the
        WARMER of the two — the shipped catalogue row applies the ERV's
        -23.3 C to an HRV, which is why these differ."""
        p = energy_recovery.profiles()
        self.assertGreater(
            p['plate_hrv']['erv_frost_threshold_temperature'],
            p['plate_erv']['erv_frost_threshold_temperature'])

    def test_no_profile_leaves_frost_control_off(self):
        """The SDK default is `None` — no frost protection at all, in a
        climate reaching -40 C. Every row of the pinned gem sets ExhaustOnly
        and so does every profile here."""
        for name, values in energy_recovery.profiles().items():
            with self.subTest(profile=name):
                self.assertEqual('ExhaustOnly',
                                 values['erv_frost_control_type'])

    def test_no_profile_carries_the_NECB_minimum(self):
        """0.50/0.50 is NECB 5.2.10.1.(4)'s requirement, not a product. It
        belongs to `btap.codes.necb`; shipping it here as a product profile
        would recreate the #183 defect."""
        for name, values in energy_recovery.profiles().items():
            with self.subTest(profile=name):
                self.assertNotEqual(
                    (0.5, 0.5),
                    (values['erv_sensible_effectiveness'],
                     values['erv_latent_effectiveness']))

    def test_every_profile_resolves_to_a_COMPLETE_valid_set(self):
        """A profile that needed extra keys would push the eleven-value
        requirement back onto every caller, defeating the point."""
        for name in energy_recovery.profiles():
            with self.subTest(profile=name):
                energy_recovery.resolve_energy_recovery(
                    {'needs_erv': True, 'erv_profile': name})

    def test_an_explicit_key_OVERRIDES_the_profile(self):
        got = energy_recovery.resolve_energy_recovery({
            'needs_erv': True, 'erv_profile': 'plate_erv',
            'erv_frost_threshold_temperature': -30.0})
        self.assertEqual(-30.0, got['erv_frost_threshold_temperature'])
        self.assertEqual(0.564, got['erv_latent_effectiveness'])

    def test_an_unknown_profile_names_the_available_ones(self):
        with self.assertRaises(ValueError) as caught:
            energy_recovery.resolve_energy_recovery(
                {'needs_erv': True, 'erv_profile': 'enthalpy_wheel'})
        self.assertIn('plate_erv', str(caught.exception))

    def test_metadata_does_not_reach_the_model(self):
        got = energy_recovery.resolve_energy_recovery(
            {'needs_erv': True, 'erv_profile': 'plate_erv'})
        for key in ('label', 'source'):
            self.assertNotIn(key, got)

    def test_the_flag_alone_builds_from_the_DECLARED_default(self):
        """phylroy, 2026-11-14: a default so a user can move ahead to a
        functioning HVAC, modifiable later.

        This replaces an earlier assertion that `needs_erv: true` alone was
        REFUSED. The refusal existed because the alternative was the SDK's
        defaults — uncited, and pairing a plate core with rotary-wheel latent
        performance and no frost control. A named, cited, overridable profile
        is a disclosed assumption, not a fabrication, so the refusal was
        protecting against something a default profile does not do.
        """
        got = energy_recovery.resolve_energy_recovery({'needs_erv': True})
        self.assertEqual(energy_recovery.default_profile_name(),
                         got['erv_profile_used'])
        self.assertEqual('ExhaustOnly', got['erv_frost_control_type'])

    def test_the_resolved_set_SAYS_which_profile_it_came_from(self):
        """What keeps a default from being the silent kind. Without this a
        build could not report whether its values were chosen or inherited."""
        named = energy_recovery.resolve_energy_recovery(
            {'needs_erv': True, 'erv_profile': 'rotary_erv'})
        self.assertEqual('rotary_erv', named['erv_profile_used'])
        defaulted = energy_recovery.resolve_energy_recovery({'needs_erv': True})
        self.assertEqual('plate_erv', defaulted['erv_profile_used'])

    def test_the_default_is_declared_in_DATA_not_code(self):
        """So changing it is a data edit and the reasoning travels with the
        values, rather than being a code change away from its citations."""
        import json

        raw = json.loads(
            energy_recovery._PROFILES_FILE.read_text(encoding='utf-8'))
        self.assertIn('default', raw)
        self.assertIn(raw['default'], raw['profiles'])

    def test_a_PARTIAL_set_is_completed_from_the_default(self):
        """A row changes one field without restating the other ten."""
        got = energy_recovery.resolve_energy_recovery(
            {'needs_erv': True, 'erv_sensible_effectiveness': 0.80})
        self.assertAlmostEqual(0.80, got['erv_sensible_effectiveness'])
        self.assertAlmostEqual(0.564, got['erv_latent_effectiveness'])

    def test_an_INVALID_value_is_still_refused(self):
        """A default completes a set; it does not excuse a bad value."""
        with self.assertRaises(ValueError):
            energy_recovery.resolve_energy_recovery(
                {'needs_erv': True, 'erv_sensible_effectiveness': 1.5})


@needs_sdk
class TestProfilesReachTheModel(unittest.TestCase):
    def test_a_profile_sets_the_exchanger_on_the_ZONAL_path(self):
        model = load_fixture()
        build_system(model, _a_row_of('baseboards'), sorted_zones(model),
                     config={'needs_zone_erv': True,
                             'erv_profile': 'plate_erv'})
        hx = model.getHeatExchangerAirToAirSensibleAndLatents()[0]
        self.assertEqual('ExhaustOnly', hx.frostControlType())
        self.assertAlmostEqual(-23.3, hx.thresholdTemperature())
        self.assertAlmostEqual(
            0.755, hx.sensibleEffectivenessat100HeatingAirFlow())
        self.assertAlmostEqual(
            0.564, hx.latentEffectivenessat100HeatingAirFlow())

    def test_a_profile_sets_the_exchanger_on_the_CENTRAL_path(self):
        model = load_fixture()
        build_system(model, _a_row_of('psz'), sorted_zones(model),
                     config={'needs_erv': True, 'erv_profile': 'rotary_erv'})
        hx = model.getHeatExchangerAirToAirSensibleAndLatents()[0]
        self.assertEqual('Rotary', hx.heatExchangerType())
        self.assertAlmostEqual(-15.0, hx.thresholdTemperature())
        self.assertAlmostEqual(
            0.74, hx.latentEffectivenessat100HeatingAirFlow())

    def test_the_zonal_option_uses_the_default_without_a_profile(self):
        """`needs_zone_erv: true` alone gets a working, frost-protected ERV.

        Briefly this RAISED KeyError from inside the builder, because
        `validate_energy_recovery` gates on `needs_erv` while the zonal flag
        is `needs_zone_erv`, so validation returned early and the absent
        fields surfaced as a KeyError rather than a refusal. The field checks
        are separate from that gate now, which is what lets the default
        complete the set instead.
        """
        model = load_fixture()
        build_system(model, _a_row_of('baseboards'), sorted_zones(model),
                     config={'needs_zone_erv': True})
        hx = model.getHeatExchangerAirToAirSensibleAndLatents()[0]
        self.assertEqual('ExhaustOnly', hx.frostControlType())
        self.assertAlmostEqual(-23.3, hx.thresholdTemperature())

    def test_the_catalogue_ROW_still_resolves_without_a_profile(self):
        """The two shipped `needs_erv` rows carry all eleven keys inline and
        must keep working untouched; their output is pinned byte-identical
        elsewhere."""
        for row in catalog.rows():
            if not row.get('needs_erv'):
                continue
            with self.subTest(row=row['name']):
                energy_recovery.resolve_energy_recovery(dict(row))

    def test_the_build_RESULT_still_reports_the_catalogue_family(self):
        """That adding recovery does not disturb what the build reports.

        Written because I thought I had introduced a bug here — the zonal hook
        first rebound `resolved`, which `return Result(...
        family=resolved['family'] ...)` reads below. Mutation testing proved
        the rebinding HARMLESS: `resolve_energy_recovery` returns
        `dict(config)` with the profile merged in, so its result is a superset
        of the catalogue row and `family` survives. The test is kept because
        the property is worth pinning, not because it caught anything."""
        model = load_fixture()
        result = build_system(
            model, _a_row_of('baseboards'), sorted_zones(model),
            config={'needs_zone_erv': True, 'erv_profile': 'plate_erv'})
        self.assertEqual('baseboards', result.family)


if __name__ == '__main__':
    unittest.main()
