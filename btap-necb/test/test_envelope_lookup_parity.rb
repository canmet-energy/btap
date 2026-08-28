require_relative 'test_helper'
require_relative '../../verification/oracle/oracle_probes'

# P2 gate (parity half): gem lookups byte-match legacy openstudio-standards NECB2020.
# Skips when the host repo isn't loadable (the gem suite must stand alone).
# The oracle-side values come from OracleProbes::Envelope — the same functions
# the Leg-C golden exporter freezes (D-78), so gate and goldens cannot drift.
class TestLookupParity < Minitest::Test
  HDD_SWEEP = OracleProbes::Envelope::HDD_SWEEP

  def legacy
    OracleProbes::Access.gate!(self, OracleProbes::Access.standard)
  end

  def test_max_u_parity_full_sweep
    lookups = OracleProbes::Envelope.lookups(legacy)
    mismatches = []
    OracleProbes::Envelope::SURFACES.each do |boundary, surfaces|
      surfaces.each do |surface|
        HDD_SWEEP.each do |hdd|
          gem_u = BtapNECB::Envelope.max_u(vintage: '2020', surface: surface, boundary: boundary, hdd: hdd)
          legacy_u = lookups['max_u'].fetch("#{boundary}/#{surface}/#{hdd}")
          next if (gem_u - legacy_u).abs < 1e-9

          mismatches << "#{boundary}/#{surface}@#{hdd}: gem #{gem_u} vs legacy #{legacy_u}"
        end
      end
    end
    assert_empty mismatches, mismatches.join("\n")
  end

  def test_max_fdwr_parity_sweep
    lookups = OracleProbes::Envelope.lookups(legacy)
    HDD_SWEEP.each do |hdd|
      gem_v = BtapNECB::Envelope.max_fdwr(vintage: '2020', hdd: hdd)
      assert_in_delta lookups['max_fdwr'].fetch(hdd.to_s), gem_v, 1e-9, "fdwr mismatch at hdd=#{hdd}"
    end
  end

  def test_srr_parity
    legacy_srr = OracleProbes::Envelope.lookups(legacy)['srr_max']
    assert_in_delta legacy_srr, BtapNECB::Envelope.max_srr(vintage: '2020'), 1e-9
  end

  def test_hdd_parity_toronto
    std = legacy
    model = OpenStudio::Model::Model.load(OpenStudio::Path.new(FixtureHelper::FIXTURE)).get
    epw = OpenStudio::EpwFile.new(OpenStudio::Path.new(FixtureHelper::EPW))
    OpenStudio::Model::WeatherFile.setWeatherFile(model, epw)

    legacy_hdd = OracleProbes::Envelope.hdd18(std, model)
    gem_hdd = BtapNECB::Envelope::Climate.hdd18(model)
    assert_equal legacy_hdd, gem_hdd, 'nearest-Table-C-1-city HDD must match legacy'
  end
end
