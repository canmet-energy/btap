require_relative 'test_helper'
require 'json'

# Every catalog system must produce a model EnergyPlus can at least start.
#
# The defect class this guards is a required performance-curve field left UNSET
# — the SDK models that as merely absent, so every in-process assertion passes
# and the model looks fine right up until E+ refuses it:
#
#   ** Severe ** AirConditioner:VariableRefrigerantFlow, "VRF OUTDOOR UNIT"
#                Defrost Energy Input Ratio Modifier Function of Temperature
#                Curve Name not found:
#
# Simulating 97 systems takes ~7 minutes even 12-way parallel, so the sweep
# itself lives in scripts/simulate_all_systems.rb (rake hvac:simulate_systems)
# and commits its verdict. This test reads that verdict and is hard in BOTH
# directions: a newly-broken system fails here, and so does a system that starts
# working, because leaving it on the known-bad list would hide the next
# regression behind a stale exemption.
class TestSystemSimulationStatus < Minitest::Test
  STATUS = File.expand_path('fixtures/system_simulation_status.json', __dir__)

  # Known broken, with the root cause. EMPTY, and the goal is to keep it that
  # way: every one of the 97 catalog systems produces a model EnergyPlus will
  # start. It held eight entries until the defrost-curve fix — four VRF systems
  # and four DX heat-pump systems, all setting Defrost Strategy = ReverseCycle
  # without the Defrost EIR curve that makes required.
  KNOWN_BAD = {}.freeze

  def setup
    @rows = JSON.parse(File.read(STATUS, encoding: 'UTF-8'))
    @failing = @rows.reject { |r| r['status'] == 'ok' }.map { |r| r['name'] }.sort
  end

  def test_the_status_file_covers_every_catalog_system
    catalog = BtapModeling::Catalog.rows.map { |r| r['name'] }.sort
    recorded = @rows.map { |r| r['name'] }.sort
    missing = catalog - recorded
    assert_empty(missing, "system(s) never simulated — re-run `rake hvac:simulate_systems`: #{missing.join(', ')}")
  end

  def test_no_system_has_newly_broken
    regressions = @failing - KNOWN_BAD.keys
    assert_empty(regressions,
                 "system(s) that used to build a simulate-able model now do not: #{regressions.join(', ')}")
  end

  # The other direction. A fixed system left on the list would silently absorb
  # the next regression in its family.
  def test_no_stale_exemptions
    fixed = KNOWN_BAD.keys.sort - @failing
    assert_empty(fixed,
                 "system(s) now simulate — remove them from KNOWN_BAD: #{fixed.join(', ')}")
  end

  # Pins the blast radius: whatever else changes, the conventional families are
  # the ones a user reaches for first and none of them may regress.
  def test_every_non_heat_pump_family_is_clean
    dirty = @rows.reject { |r| r['status'] == 'ok' }.map { |r| r['family'] }.uniq
    conventional = %w[psz vav_reheat fan_coils mau_ptac baseboards zone_terminal
                      unit_heaters furnace evap_cooler doas wshp zone_ervs]
    assert_empty(dirty & conventional,
                 "a conventional family broke: #{(dirty & conventional).join(', ')}")
  end
end
