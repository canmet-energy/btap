require_relative 'test_helper'
require_relative '../../verification/oracle/oracle_probes'

# P2 gate (parity half): EVERY schedule name in the vendored 2020 table builds
# identically via the gem and via legacy model_add_schedule — default day values,
# design days, rule day-of-week flags and dates. Runs under the repo bundle.
# Oracle-side signatures come from OracleProbes::Loads.schedules — the same
# function the Leg-C golden exporter freezes (D-78).
class TestSchedulesParity < Minitest::Test
  include FixtureHelper

  def legacy
    OracleProbes::Access.gate!(self, OracleProbes::Access.standard)
  end

  def test_all_schedules_parity
    std = legacy
    names = BtapNECB::Loads.table('2020', 'schedules').map { |r| r['name'] }.uniq
    legacy_signatures = OracleProbes::Loads.schedules(std, names)
    mismatches = []

    names.each do |name|
      gem_model = OpenStudio::Model::Model.new
      gem_schedule = BtapNECB::Loads::Schedules.add(gem_model, name)
      gem_signature = OracleProbes::Signatures.ruleset_signature(gem_schedule)
      mismatches << name unless gem_signature == legacy_signatures[name]
    end

    assert_operator names.size, :>=, 85, 'the full catalog was compared (86 unique names over 240 rows)'
    assert_empty mismatches, "schedule parity mismatches: #{mismatches.first(10).inspect}"
  end
end
