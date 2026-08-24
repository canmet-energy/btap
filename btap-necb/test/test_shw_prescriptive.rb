require_relative 'test_helper'

# Section 6.2 prescriptive rules: the one the model can answer, and the honest
# declaration of the ones it cannot.
class TestPrescriptive < Minitest::Test
  include FixtureHelper

  P = BtapNECB::SHW::Prescriptive

  # spaces_w_dhw entries only need the two keys the rule reads.
  def sizing(*pairs)
    { 'spaces_w_dhw' => pairs.map { |flow, temp| { 'peak_flow_si' => flow, 'temperature_c' => temp } } }
  end

  def run_check(sizing_hash, water_heaters: 1)
    model = OpenStudio::Model::Model.new
    water_heaters.times { OpenStudio::Model::WaterHeaterMixed.new(model) }
    audit = BtapNECB::AuditLog.new
    result = P.check_booster_heaters(sizing_hash, model, audit)
    [result, audit]
  end

  def entry(audit)
    audit.entries.find { |e| e[:article] == '6.2.5.1.' }
  end

  # 6.2.5.1 fires when the hot fraction is SMALL, which is the counterintuitive
  # direction: a mostly-hot system may run one plant, a minority hot load may not
  # drag the whole plant up with it.
  def test_minority_high_temperature_load_with_one_heater_is_a_violation
    _, audit = run_check(sizing([1.0, 80.0], [9.0, 45.0]))   # 10% of flow above 60 C
    e = entry(audit)
    assert_equal(:warning, e[:level])
    assert_match(/BOOSTER HEATER REQUIRED and NOT present/, e[:action],
                 'violations are SHOUTED — the checklist classifier is case-sensitive')
    assert_in_delta(0.1, e[:inputs][:high_temp_flow_fraction], 1e-6)
  end

  def test_majority_high_temperature_load_needs_no_booster
    _, audit = run_check(sizing([9.0, 80.0], [1.0, 45.0]))   # 90% above 60 C
    e = entry(audit)
    assert_equal(:decision, e[:level])
    assert_match(/not required/, e[:action])
  end

  # Exactly at 50% the sentence does NOT fire — it says "less than 50%".
  def test_the_boundary_is_not_a_violation
    _, audit = run_check(sizing([5.0, 80.0], [5.0, 45.0]))
    assert_equal(:decision, entry(audit)[:level], '50% is not "less than 50%"')
  end

  # 60 C exactly is not "higher than 60 C".
  def test_sixty_exactly_is_not_a_high_temperature_load
    _, audit = run_check(sizing([1.0, 60.0], [9.0, 45.0]))
    assert_match(/vacuous/, entry(audit)[:action])
  end

  def test_no_load_above_sixty_makes_the_sentence_vacuous
    _, audit = run_check(sizing([10.0, 55.0]))
    e = entry(audit)
    assert_equal(:info, e[:level], 'a sentence with no subject is neither a pass nor a failure')
    assert_match(/vacuous/, e[:action])
  end

  # A second water heater is the model's only evidence that the required booster
  # exists, so it must not still be reported as missing.
  def test_a_second_water_heater_satisfies_the_requirement
    _, audit = run_check(sizing([1.0, 80.0], [9.0, 45.0]), water_heaters: 2)
    e = entry(audit)
    assert_equal(:decision, e[:level])
    refute_match(/NOT present/, e[:action])
  end

  def test_no_demand_is_not_a_determination
    result, audit = run_check({ 'spaces_w_dhw' => [] })
    assert_nil(result)
    assert_nil(entry(audit))
  end

  # The clauses no model can answer must still be NAMED, or their silence reads
  # as "not applicable" when they very much apply.
  def test_unanswerable_clauses_are_declared_individually
    audit = BtapNECB::AuditLog.new
    P.declare_field_verified(audit)
    %w[6.2.3.1. 6.2.4.3. 6.2.6.1. 6.2.6.2. 6.2.7.1. 6.2.7.2.].each do |article|
      e = audit.entries.find { |x| x[:article] == article }
      refute_nil(e, "#{article} must be declared, not silently absent")
      assert_equal(:info, e[:level], 'a field-verified clause is not a modelling warning')
      assert_match(/requires field or document verification/, e[:action])
    end
  end

  # The gem had no status whitelist, unlike envelope/hvac/loads/lighting — a
  # typo'd status would have passed CI and rendered as an em-dash in the report.
  def test_every_coverage_status_is_legal
    valid = %w[implemented partial not_implemented satisfied_by_clone host_scope]
    %w[2020 2025].each do |vintage|
      BtapNECB::SHW.rules(vintage)['article_coverage']['articles'].each do |art|
        assert_includes(valid, art['status'], "#{vintage} #{art['article']}: illegal status")
        assert(art['how'] || art['gaps'], "#{vintage} #{art['article']}: needs how or gaps")
        next unless art['gap_owner']

        assert_equal('modeller', art['gap_owner'],
                     "#{vintage} #{art['article']}: only 'modeller' is recognised by Coverage.emit")
      end
    end
  end
end
