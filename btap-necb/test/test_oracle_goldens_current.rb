require_relative 'test_helper'
require 'json'
require 'digest'

# The TWELFTH pin-gated test (D-78/D-80): the committed Leg-C oracle goldens
# (verification/oracle/goldens/) are internally consistent and current with
# the pin. Slimmed in D-80 R1 to EXACTLY FOUR duties — REF equality, file
# existence, checksums, and request-manifest inventory consistency. Live
# freshness (frozen values vs the live oracle) is the freshness comparator's
# job — verification/oracle/compare_goldens.py inside live_leg_c.sh — so
# there are never two overlapping freshness implementations.
class TestOracleGoldensCurrent < Minitest::Test
  GOLDEN_DIR = File.expand_path('../../verification/oracle/goldens', __dir__)
  REQUEST = File.expand_path('../../verification/oracle/request_manifest.json', __dir__)
  REMEDY = 'regenerate under the pin: python/scripts/oracle_prep.py then ' \
           'verification/oracle/export_goldens.rb (or dispatch the goldens workflow)'

  def manifest
    path = File.join(GOLDEN_DIR, 'manifest.json')
    flunk("goldens manifest missing — #{REMEDY}") unless File.exist?(path)
    JSON.parse(File.read(path, encoding: 'UTF-8'))
  end

  # Duty 1: the goldens describe THE pinned oracle revision.
  def test_manifest_ref_equals_the_pin
    ref = File.read(File.expand_path('../../legacy_pin/REF', __dir__)).strip
    assert_equal ref, manifest['legacy_ref'],
                 "goldens were exported from a DIFFERENT oracle revision — #{REMEDY}"
  end

  # Duties 2 + 3: every listed file exists and matches its checksum — and
  # the directory holds NOTHING beyond the listed files (an obsolete group
  # with a valid checksum and no consumer is a failure, not an extra).
  def test_files_exist_and_match_checksums
    listed = manifest['files']
    refute_empty listed
    listed.each do |name, sha|
      file = File.join(GOLDEN_DIR, name)
      assert File.exist?(file), "manifest lists #{name} but it is missing — #{REMEDY}"
      assert_equal sha, Digest::SHA256.hexdigest(File.read(file, encoding: 'BINARY')),
                   "#{name} does not match its manifest checksum — hand-edited? #{REMEDY}"
    end
    on_disk = Dir[File.join(GOLDEN_DIR, '*.json')].map { |f| File.basename(f) } - ['manifest.json']
    assert_equal listed.keys.sort, on_disk.sort,
                 "goldens directory does not hold exactly the manifest's file set — #{REMEDY}"
  end

  # Duty 4: every golden matches the request manifest's recursive inventory
  # (the implementation-independent statement of what the oracle was asked).
  def test_request_manifest_inventory_consistency
    require_relative '../../verification/oracle/inventory'
    request = JSON.parse(File.read(REQUEST, encoding: 'UTF-8'))
    assert_equal request['golden_groups'].sort, manifest['files'].keys.map { |f| f.sub('.json', '') }.sort,
                 'the goldens file set and the request manifest golden_groups disagree'
    request['golden_groups'].each do |group|
      data = JSON.parse(File.read(File.join(GOLDEN_DIR, "#{group}.json"), encoding: 'UTF-8'))
      violations = OracleInventory.validate(data, request['golden_inventory'][group])
      assert_empty violations.first(10),
                   "#{group} violates the request-manifest inventory — #{REMEDY}"
    end
  end
end
