require_relative 'test_helper'

# P3b gate: NECB 3.1.1.7 effective transmittance via TBD — assemblies are uprated so
# the derated Ut meets the table targets; unavailability/omission is loud, never silent.
class TestThermalBridging < Minitest::Test
  include FixtureHelper

  HDD = 3890

  def tbd_available?
    BtapNECB::Envelope::ThermalBridging.available?
  end

  def test_not_requested_warns
    model = load_raw_fixture
    audit = BtapNECB::Envelope.apply_prescriptive(model, vintage: '2020', hdd: HDD)
    warning = audit.warnings.find { |w| w[:action].include?('thermal bridging not requested') }
    refute_nil warning
    assert_equal '3.1.1.7.', warning[:article]
  end

  def test_unavailable_is_loud
    ENV['OPENSTUDIO_ENVELOPE_DISABLE_TBD'] = '1'
    audit = BtapNECB::AuditLog.new
    result = BtapNECB::Envelope::ThermalBridging.apply(load_raw_fixture, vintage: '2020', hdd: HDD, audit: audit)
    assert_equal false, result
    assert audit.warnings.any? { |w| w[:action].include?("NOT accounted") && w[:article] == '3.1.1.7.' }
  ensure
    ENV.delete('OPENSTUDIO_ENVELOPE_DISABLE_TBD')
  end

  def test_uprate_derate_meets_effective_targets
    # A skipped TBD gate is a green-but-vacuous gate: 3.1.1.7 is declared
    # `implemented`, and THIS is the only test that proves the uprate/derate math
    # actually lands on the effective-U targets. tbd is a declared runtime
    # dependency, but the suites run under plain `ruby`, so nothing enforces it —
    # it went missing from the devcontainer and from CI, and this test skipped in
    # both while the summary line stayed green. Same contract as the parity
    # gates: TBD_REQUIRED=1 turns "not installed" from a skip into a failure.
    unless tbd_available?
      msg = 'tbd gem not available (gem install tbd)'
      ENV['TBD_REQUIRED'] == '1' ? flunk(msg) : skip(msg)
    end

    model = load_raw_fixture
    audit = BtapNECB::Envelope.apply_prescriptive(model, vintage: '2020', hdd: HDD,
                                                        thermal_bridging: 'efficient (BETBG)',
                                                        audit: BtapNECB::AuditLog.new)

    decision = audit.entries.find { |e| e[:step] == :thermal_bridging && e[:level] == :decision }
    refute_nil decision, 'TBD uprate/derate decision logged'
    assert_operator decision[:inputs][:surfaces_derated], :>, 0
    assert_match(/Σψ/, decision[:article])

    # ROOFS: uprating succeeds — the derated effective U lands at/below the target
    roof = model.getSurfaces.find { |s| s.outsideBoundaryCondition == 'Outdoors' && s.surfaceType == 'RoofCeiling' }
    roof_u = roof.construction.get.to_Construction.get.thermalConductance.to_f
    assert_operator roof_u, :<=, 0.156 + 1e-3,
                    "derated roof U (#{roof_u.round(4)}) meets the effective target 0.156"

    # WALLS: this fixture's tiny walls have edge losses alone above the target —
    # physically infeasible — and TBD's refusal must be LOUD in the audit
    infeasible = audit.warnings.find { |w| w[:action].include?('Unable to uprate') }
    refute_nil infeasible, 'infeasible uprate must surface as an audit warning'

    per_surface = audit.entries.select { |e| e[:action].include?('surface derated') }
    refute_empty per_surface, 'per-surface derating evidence in the audit'
  end

  # Review (2026-08-28): TBD reports invalid input by LOGGING fatal/error and
  # returning a PARTIAL result — before this fix, apply() narrated that
  # partial result as 'assemblies uprated' (reproduced: invalid PSI set,
  # status 5, 30 surfaces returned, decision emitted). A failing AVAILABLE
  # engine must ABORT, never claim success or be relabeled unavailability.
  def test_engine_failure_aborts_never_claims_success
    unless tbd_available?
      msg = 'tbd gem not available (gem install tbd)'
      ENV['TBD_REQUIRED'] == '1' ? flunk(msg) : skip(msg)
    end

    audit = BtapNECB::AuditLog.new
    error = assert_raises(RuntimeError) do
      BtapNECB::Envelope::ThermalBridging.apply(load_raw_fixture, vintage: '2020', hdd: HDD,
                                                psi_set: 'no such set', audit: audit)
    end
    assert_includes error.message, 'TBD FAILED'
    assert_includes error.message, 'NOT been applied'
    refute(audit.entries.any? { |e| e[:step] == :thermal_bridging && e[:level] == :decision },
           'no uprated decision may be recorded for a failed run')
    refute(audit.warnings.any? { |w| w[:action].include?('NOT accounted') },
           'a processing failure must never be relabeled as unavailability')
  end

  def test_coverage_manifest_reflects_tbd_status
    %w[2020 2025].each do |v|
      art = BtapNECB::Envelope.rules(v)['article_coverage']['articles']
                                    .find { |a| a['article'] == '3.1.1.7.' }
      assert_equal 'implemented', art['status']
      assert_match(/tbd gem/, art['gaps'])
    end
  end
end
