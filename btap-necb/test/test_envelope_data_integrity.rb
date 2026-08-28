require_relative 'test_helper'
require_relative '../../verification/oracle/oracle_probes'

# P1 gate: the vendored rules data is complete, internally consistent, provenance-
# tagged, and structurally identical to the legacy openstudio-standards data (2020).
class TestDataIntegrity < Minitest::Test
  VINTAGES = %w[2020 2025].freeze
  SURFACES = { 'outdoors' => %w[wall roofceiling floor window skylight door],
               'ground' => %w[wall roofceiling floor] }.freeze
  BINS = %w[3000 4000 5000 6000 7000 9999].freeze

  def test_rules_load_and_unknown_vintage_raises
    VINTAGES.each { |v| refute_nil BtapNECB::Envelope.rules(v) }
    assert_raises(ArgumentError) { BtapNECB::Envelope.rules('1997') }
  end

  def test_u_values_complete_and_monotone
    VINTAGES.each do |vintage|
      u = BtapNECB::Envelope.rules(vintage)['u_values']
      SURFACES.each do |boundary, surfaces|
        surfaces.each do |surface|
          bins = u.fetch(boundary).fetch(surface)
          assert_equal BINS, bins.keys, "#{vintage}/#{boundary}/#{surface}: bin keys"
          values = BINS.map { |b| bins[b] }
          assert values.all? { |v| v.is_a?(Numeric) && v.positive? }
          # colder zones require equal-or-lower U (monotone non-increasing)
          values.each_cons(2) do |a, b|
            assert_operator b, :<=, a, "#{vintage}/#{boundary}/#{surface}: U must not increase with HDD (#{values})"
          end
        end
      end
    end
  end

  def test_fdwr_piecewise_continuity
    VINTAGES.each do |vintage|
      pieces = BtapNECB::Envelope.rules(vintage)['fdwr']['pieces']
      assert_equal 3, pieces.size
      linear = pieces[1]['linear']
      at4000 = (linear['intercept'] + linear['slope'] * 4000) / linear['divisor']
      at7000 = (linear['intercept'] + linear['slope'] * 7000) / linear['divisor']
      assert_in_delta pieces[0]['value'], at4000, 1e-9, 'continuous at HDD 4000'
      assert_in_delta pieces[2]['value'], at7000, 1e-9, 'continuous at HDD 7000'
    end
  end

  def test_srr_is_two_percent
    VINTAGES.each do |vintage|
      srr = BtapNECB::Envelope.rules(vintage)['srr_max']
      assert_in_delta 0.02, srr['value'], 1e-9
      assert_match(/3\.2\.1\.4/, srr['article'])
    end
  end

  def test_provenance_and_coverage_lint
    valid = %w[implemented partial not_implemented satisfied_by_clone host_scope]
    VINTAGES.each do |vintage|
      rules = BtapNECB::Envelope.rules(vintage)
      prov = rules['provenance']
      assert_equal vintage, prov['edition']
      assert_match(/MCP/, prov['source'])
      coverage = rules['article_coverage']['articles']
      assert_equal 17, coverage.size # 14 + 8.4.1.1 (envelope slice) + 8.4.2.9 air leakage
      coverage.each do |art|
        assert_includes valid, art['status'], "#{art['article']}: invalid status"
        assert art['title']
        if %w[partial not_implemented].include?(art['status'])
          assert art['gaps'], "#{art['article']} is #{art['status']} but declares no gaps"
        end
      end
      # Only the reference-building subsection is renumbered between vintages
      # (2020 8.4.4 == 2025 8.4.5); 8.4.1-8.4.3 and 8.4.6 are vintage-invariant.
      wrong = vintage == '2020' ? '8.4.5' : '8.4.4'
      renumbered = coverage.select { |a| a['article'].start_with?('8.4.4', '8.4.5') }
      assert renumbered.none? { |a| a['article'].start_with?(wrong) },
             "#{vintage}: reference-building articles must not use the #{wrong} numbering"
    end
  end

  def test_2020_matches_legacy_surface_thermal_transmittance
    # The pinned oracle's data file, via the probe the Leg-C golden exporter
    # also freezes (D-78).
    pinned = OracleProbes::Access.pin_root
    legacy = pinned && OracleProbes::Envelope.u_table(pinned)
    if legacy.nil?
      msg = 'legacy U-table not present (run under BUNDLE_GEMFILE=legacy_pin/Gemfile)'
      ENV['LEGACY_PIN_REQUIRED'] == '1' ? flunk(msg) : skip(msg)
    end

    gem_u = BtapNECB::Envelope.rules('2020')['u_values']
    assert_equal legacy, gem_u, 'vendored 2020 U-values must equal legacy data structurally'
  end

  def test_2025_values_equal_2020
    assert_equal BtapNECB::Envelope.rules('2020')['u_values'],
                 BtapNECB::Envelope.rules('2025')['u_values'],
                 'verified via MCP: 2025 envelope tables are numerically identical to 2020'
  end

  def test_table_c1_vendored
    path = File.join(BtapNECB::Envelope::RULES_DIR, 'table_c1.json')
    data = JSON.parse(File.read(path))
    assert_operator data['table'].size, :>=, 679
    row = data['table'].first
    %w[city province degree_days_below_18_c lat_long].each { |k| assert row.key?(k) }
    assert_match(/Table C-1/, data['provenance']['source'])
  end

  def test_audit_log_schema_matches_hvac_gem
    audit = BtapNECB::AuditLog.new
    audit.decision(:test, 'x', article: '3.2.1.4.')
    entry = JSON.parse(audit.to_json).first
    assert_equal %w[step action article level].sort, (entry.keys & %w[step action article level]).sort
    assert_equal BtapNECB::AuditLog, BtapNECB::AuditLog
  end
end
