require_relative 'test_helper'
require 'tmpdir'

# The reference-building rules, each proved by a sample where the reference
# VISIBLY diverges from the proposed.
#
# These assert on the AUDIT DECISION, not on the energy numbers: the point is
# which rule fired and what it decided, and an energy assertion would be a
# brittle proxy for that. Everything here runs `simulate: :none` — no
# EnergyPlus — except the two marked as needing an annual run, because the
# rules they cover cannot fire without one.
class TestReferenceRules < Minitest::Test
  include FixtureHelper

  SAMPLES = File.expand_path('../../packaging/windows/samples', __dir__)

  def sample(slug)
    path = File.join(SAMPLES, "#{slug}.osm")
    skip("sample not generated: run ruby btap-necb/scripts/generate_samples.rb") unless File.exist?(path)
    path
  end

  def compliance(slug, dir, **kwargs)
    BtapNECB.performance_compliance(sample(slug), vintage: '2020', hdd: 3890,
                                          simulate: :none, run_dir: dir, **kwargs)
  end

  def article(result, prefix)
    result.audit.entries.select { |e| e[:article].to_s.start_with?(prefix) }
  end

  # The AuditLog schema names the text :action, NOT :message — an entry is
  # {step, action, inputs, value, article, ruling, evidence, building, level}.
  # Reading e[:message] returns nil silently, so an assertion on it fails with a
  # misleading "the rule did not fire" when the rule fired perfectly well.
  def said?(entries, pattern)
    entries.any? { |e| e[:action].to_s.match?(pattern) }
  end

  # 8.4.4.6.(1)(a): purchased heating "shall be represented by" a gas-fired
  # boiler. The proposed has a district object and NO boiler; the reference must
  # have the reverse.
  #
  # This one is layout-sensitive in a way that is easy to get wrong: with several
  # single-zone groups the district loop survives the per-group teardown and is
  # re-adopted by name ('Hot Water Loop'), so the article ends up only
  # half-applied — the energy-type variant flips to gas but the district object
  # stays. The sample is deliberately a SINGLE-group system for that reason.
  def test_purchased_heating_becomes_a_gas_boiler_in_the_reference
    Dir.mktmpdir do |dir|
      r = compliance('13-district-heating', dir)

      district = ->(m) { m.modelObjects.count { |o| o.iddObjectType.valueName.match?(/DistrictHeating/) } }
      assert_equal(1, district.call(r.proposed_model), 'the proposed should carry district heating')
      assert_equal(0, r.proposed_model.getBoilerHotWaters.size, 'the proposed should have no boiler')

      assert_equal(0, district.call(r.reference_model), 'the reference must NOT keep district heating')
      refute_empty(r.reference_model.getBoilerHotWaters, 'the reference must grow a boiler')
      assert_equal(['NaturalGas'], r.reference_model.getBoilerHotWaters.map(&:fuelType).uniq,
                   '8.4.4.6.(1)(a) names a GAS-fired boiler specifically')

      refute_empty(article(r, '8.4.4.6'), 'the purchased-energy decision must be audited')
    end
  end

  # Table 8.4.4.7.-A splits General Area at 2 vs 3 above-ground storeys. Two
  # otherwise-identical buildings must select different reference systems — one
  # sample cannot show a flip, which is why these are a pair.
  def test_storey_count_flips_the_reference_system
    Dir.mktmpdir do |dir|
      low = compliance('14-general-2storey', File.join(dir, 'low'))
      high = compliance('15-general-3storey', File.join(dir, 'high'))

      low_sel = article(low, '8.4.4.7').map { |e| e[:value].to_s }.join(' ')
      high_sel = article(high, '8.4.4.7').map { |e| e[:value].to_s }.join(' ')

      assert_match(/System 3/, low_sel, "2 storeys should select System 3, got: #{low_sel}")
      assert_match(/System 6/, high_sel, "3 storeys should select System 6, got: #{high_sel}")
      refute_equal(low_sel, high_sel)
    end
  end

  # The storey count must come from the MODEL, so the samples stand alone without
  # the CLI's --storeys override.
  def test_the_storey_samples_declare_their_own_storey_count
    { '14-general-2storey' => 2, '15-general-3storey' => 3 }.each do |slug, expected|
      model = OpenStudio::Model::Model.load(OpenStudio::Path.new(sample(slug))).get
      declared = model.getBuilding.standardsNumberOfAboveGroundStories
      assert(declared.is_initialized, "#{slug} must declare its storey count on the Building")
      assert_equal(expected, declared.get)
    end
  end

  # 8.4.4.9.(5)/8.4.4.10.(4) multi-energy capacity ratios are a DECLARED gap: the
  # reference keeps a mixed-fuel plant unchanged rather than apportioning it.
  # Pinned so that implementing the clause has to come here and say so, instead
  # of silently changing what these samples demonstrate.
  def test_mixed_fuel_plant_passes_through_unchanged_the_declared_gap
    Dir.mktmpdir do |dir|
      r = compliance('11-staged-boilers-gas-lead', dir)
      fuels = ->(m) { m.getBoilerHotWaters.sort_by(&:nameString).map { |b| [b.nameString, b.fuelType] } }

      assert_equal(fuels.call(r.proposed_model), fuels.call(r.reference_model),
                   'while 8.4.4.9.(5) is unimplemented the mixed-fuel plant should pass through as-is')
      assert_includes(fuels.call(r.reference_model).map(&:last), 'Electricity')
      assert_includes(fuels.call(r.reference_model).map(&:last), 'NaturalGas')
    end
  end

  # --- these need a real annual run; the rules cannot fire without one ---

  # 8.4.4.13.(2)(g)/D-52. Proof that the ELECTION ran rather than the structural
  # 8.4.4.9.(4) proxy is the (g)(i)/(g)(ii) suffix plus the ELECTED wording — NOT
  # the elected fuel, which may legitimately match what the proxy would have said.
  def test_auxiliary_fuel_election_runs_on_an_annual_run
    skip('openstudio CLI not available') unless BtapNECB::Runner.openstudio_cli?

    Dir.mktmpdir do |dir|
      r = BtapNECB.performance_compliance(
        sample('16-ashp-electric-supp-hw-baseboard'), vintage: '2020', hdd: 3890,
        weather: { epw: EPW, ddy: DDY }, simulate: :annual,
        run_period: { begin_month: 1, begin_day: 1, end_month: 1, end_day: 7 },
        building: { storeys: 1 }, run_dir: dir)

      elected = article(r, '8.4.4.13.(2)(g)(')
      refute_empty(elected, 'the election should have run — only the bare (g) proxy entry was emitted')
      assert(elected.any? { |e| e[:action].to_s.match?(/ELECTED from the proposed annual run/) },
             'expected the ELECTED wording, which distinguishes the election from the proxy')
    end
  end

  # 8.4.1.2.(4) is formally vacuous when the proposed has no mechanical cooling —
  # otherwise passive-overheating hours would be read as a cooling-capacity
  # shortfall. mechanical_cooling? is only populated on an annual run.
  def test_sentence_four_is_vacuous_without_mechanical_cooling
    skip('openstudio CLI not available') unless BtapNECB::Runner.openstudio_cli?

    Dir.mktmpdir do |dir|
      r = BtapNECB.performance_compliance(
        sample('01-baseboard-gas'), vintage: '2020', hdd: 3890,
        weather: { epw: EPW, ddy: DDY }, simulate: :annual,
        run_period: { begin_month: 1, begin_day: 1, end_month: 1, end_day: 7 },
        building: { storeys: 1 }, run_dir: dir)

      assert_equal(false, r.report['proposed']['mechanical_cooling'])
      vacuous = article(r, '8.4.1.2.(4)').select { |e| e[:action].to_s.match?(/vacuous/) }
      refute_empty(vacuous, 'sentence (4) should be declared vacuous for a heating-only proposed')
    end
  end
  # The layout that hid the bug. `Baseboard district hot water` makes FIVE
  # single-zone groups, and the reference builder tears down and rebuilds one
  # group at a time; Teardown only drops a plant loop whose demand side is empty,
  # so the district loop always still carried the other groups' coils and
  # survived. It was then re-adopted by a bare NAME match on 'Hot Water Loop' —
  # the name every loop this builder makes carries, district ones included — so
  # the reference kept purchased heating while its energy type said gas.
  #
  # The single-group sample (13) never showed this. Both layouts are asserted
  # here so the fix cannot regress on the shape that is easy to miss.
  def test_purchased_heating_is_replaced_whatever_the_group_layout
    %w[Baseboard\ district\ hot\ water
       DOAS\ with\ fan\ coil\ air-cooled\ chiller\ with\ district\ hot\ water].each do |escaped|
      system = escaped.tr('\\', '')
      model = load_fixture
      BtapNECB::Loads.apply_loads(model, vintage: '2020', audit: BtapNECB::AuditLog.new)
      BtapModeling.build_system(model, system, model.getThermalZones.sort_by(&:nameString))

      district = ->(m) { m.modelObjects.count { |o| o.iddObjectType.valueName.match?(/DistrictHeating/) } }
      assert_equal(1, district.call(model), "#{system}: the proposed should carry district heating")

      reference = BtapNECB::HVAC.reference_hvac(
        model, vintage: '2020', building: { storeys: 1 }, audit: BtapNECB::AuditLog.new
      ).model

      assert_equal(0, district.call(reference),
                   "#{system}: 8.4.4.6.(1)(a) — the reference must NOT keep purchased heating")
      assert_equal(['NaturalGas'], reference.getBoilerHotWaters.map(&:fuelType).uniq,
                   "#{system}: the reference must be heated by a gas-fired boiler")
    end
  end
end
