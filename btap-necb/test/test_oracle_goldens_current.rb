require_relative 'test_helper'
require_relative 'support/oracle_probes'
require 'json'
require 'digest'

# The TWELFTH pin-gated test (D-78): the committed Leg-C oracle goldens
# (test/goldens/oracle/) are PROVABLY-CURRENT snapshots of the pinned oracle —
# re-run a fast representative subset of the probes live and assert equality
# with the frozen files, and assert the manifest's legacy_ref equals
# legacy_pin/REF. A REF bump without re-export
# (scripts/export_oracle_goldens.rb) is a loud failure here, never a silently
# stale golden. The Python port consumes these same files directly.
class TestOracleGoldensCurrent < Minitest::Test
  GOLDEN_DIR = File.expand_path('goldens/oracle', __dir__)
  REMEDY = 'regenerate under the pin: BUNDLE_GEMFILE=legacy_pin/Gemfile bundle exec ' \
           'ruby btap-necb/scripts/export_oracle_goldens.rb (or dispatch the goldens workflow)'

  def golden(name)
    path = File.join(GOLDEN_DIR, "#{name}.json")
    flunk_or_skip("golden #{name}.json missing — #{REMEDY}") unless File.exist?(path)
    JSON.parse(File.read(path))
  end

  def flunk_or_skip(msg)
    ENV['LEGACY_PIN_REQUIRED'] == '1' ? flunk(msg) : skip(msg)
  end

  def legacy
    OracleProbes::Access.gate!(self, OracleProbes::Access.standard)
  end

  def test_manifest_matches_the_pin
    path = File.join(GOLDEN_DIR, 'manifest.json')
    flunk_or_skip("goldens manifest missing — #{REMEDY}") unless File.exist?(path)
    manifest = JSON.parse(File.read(path))
    ref = File.read(File.expand_path('../../legacy_pin/REF', __dir__)).strip
    assert_equal ref, manifest['legacy_ref'],
                 "goldens were exported from a DIFFERENT oracle revision — #{REMEDY}"
    manifest['files'].each do |name, sha|
      file = File.join(GOLDEN_DIR, name)
      assert File.exist?(file), "manifest lists #{name} but it is missing — #{REMEDY}"
      assert_equal sha, Digest::SHA256.hexdigest(File.read(file)),
                   "#{name} does not match its manifest checksum — hand-edited? #{REMEDY}"
    end
  end

  def test_envelope_lookups_current
    std = legacy
    frozen = golden('envelope_lookups')
    live = OracleProbes::Envelope.lookups(std)
    mismatches = frozen['max_u'].reject { |k, v| (live['max_u'][k] - v).abs < 1e-12 }.keys +
                 frozen['max_fdwr'].reject { |k, v| (live['max_fdwr'][k] - v).abs < 1e-12 }.keys
    assert_empty mismatches, "frozen envelope lookups drifted from the live oracle: #{mismatches.first(5)} — #{REMEDY}"
    assert_in_delta frozen['srr_max'], live['srr_max'], 1e-12
  end

  def test_loads_schedules_current_sample
    std = legacy
    frozen = golden('loads_schedules')
    # A representative sample keeps this test fast; the exporter froze all 86.
    sample = frozen.keys.sort.each_slice((frozen.size / 8.0).ceil).map(&:first)
    live = OracleProbes::Loads.schedules(std, sample)
    stale = sample.reject { |name| frozen[name] == live[name] }
    assert_empty stale, "frozen schedule goldens drifted: #{stale.inspect} — #{REMEDY}"
  end

  def test_shw_efficiencies_current
    std = legacy
    frozen = golden('shw')['efficiencies']
    live = OracleProbes::Shw.efficiencies(std)
    stale = frozen.reject { |k, v| live[k] == v }.keys
    assert_empty stale, "frozen SHW efficiency goldens drifted: #{stale.inspect} — #{REMEDY}"
  end
end
