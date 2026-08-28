require_relative 'test_helper'
require_relative '../../verification/oracle/oracle_probes'

# Costing parity vs legacy BTAP: (1) the interpolator, (2) cost_construction dollar
# math across EVERY constructions.json candidate, (3) per-surface RSI convention vs
# TBD.rsi. Runs under the repo bundle (openstudio-standards + tbd); skips standalone.
# Oracle-side values come from OracleProbes::Costing — the same functions the
# Leg-C golden exporter freezes (D-78).
class TestCostingParity < Minitest::Test
  include FixtureHelper

  CITY = 'TORONTO'.freeze
  PROVINCE = 'ONTARIO'.freeze

  def legacy
    OracleProbes::Access.gate!(self, OracleProbes::Access.coster)
  end

  def test_interpolate_parity
    legacy
    legacy_values = OracleProbes::Costing.interpolations
    mismatches = []
    OracleProbes::Costing::INTERPOLATE_POINT_SETS.each_with_index do |points, set_index|
      OracleProbes::Costing::INTERPOLATE_XS.each do |x|
        legacy_value = legacy_values.fetch("#{set_index}/#{x}")
        gem_value = BtapCosting::Envelope::Interpolate.interpolate(x_y_array: points.map(&:dup), x2: x).value
        mismatches << [points.first, x, legacy_value, gem_value] unless (legacy_value - gem_value).abs < 1e-9
      end
    end
    assert_empty mismatches, "interpolate mismatches: #{mismatches.inspect[0, 400]}"
  end

  def test_cost_construction_parity_every_candidate
    coster = legacy
    database = BtapCosting::Envelope::Database.new
    legacy_costs = OracleProbes::Costing.construction_costs(coster, database, PROVINCE, CITY)
    checked = 0
    mismatches = []

    database.constructions.each do |sheet, assemblies|
      assemblies.each_key do |assembly|
        database.construction_candidates(sheet, assembly).each do |rsi, construction|
          legacy_cost = legacy_costs.fetch("#{sheet}/#{assembly}/#{rsi.round(3)}")
          gem_cost = BtapCosting::Envelope::EnvelopeCosts.construction_cost(
            database, construction, PROVINCE, CITY)
          checked += 1
          next if (legacy_cost - gem_cost).abs < 0.011 # per-layer cent rounding

          mismatches << [sheet, assembly, rsi.round(3), legacy_cost, gem_cost]
        end
      end
    end

    assert_operator checked, :>=, 90, 'every candidate in every assembly catalog compared (92 in the vendored catalogs)'
    assert_empty mismatches, "$ mismatches (sheet, assembly, rsi, legacy, gem): #{mismatches.inspect[0, 600]}"
  end

  def test_rsi_parity_vs_tbd
    legacy
    model = load_raw_fixture
    BtapNECB::Envelope.apply_prescriptive(model, vintage: '2020', hdd: 3890,
                                                audit: BtapNECB::AuditLog.new)
    wall = model.getSurfaces.find { |s| s.outsideBoundaryCondition == 'Outdoors' && s.surfaceType == 'Wall' }
    wall.setWindowToWallRatio(0.3)
    BtapNECB::Envelope.apply_prescriptive(model, vintage: '2020', hdd: 3890,
                                                audit: BtapNECB::AuditLog.new)

    legacy_rsi = OracleProbes::Costing.tbd_rsi(model)
    mismatches = []
    legacy_rsi['surfaces'].each do |name, l|
      surface = model.getSurfaces.find { |s| s.nameString == name }
      gem_rsi = BtapCosting::Envelope::Quantify.rsi_of(surface, film: true)
      mismatches << [name, l, gem_rsi] unless (l - gem_rsi).abs < 1e-6
    end
    legacy_rsi['sub_surfaces'].each do |name, l|
      sub = model.getSubSurfaces.find { |s| s.nameString == name }
      gem_rsi = BtapCosting::Envelope::Quantify.rsi_of(sub, film: false)
      mismatches << [name, l, gem_rsi] unless (l - gem_rsi).abs < 1e-6
    end
    assert_empty mismatches, "RSI mismatches vs TBD.rsi: #{mismatches.inspect[0, 400]}"
  end

  def test_tb_material_quantities_parity
    legacy
    legacy_quantities = OracleProbes::Costing.tb_material_quantities
    database = BtapCosting::Envelope::Database.new
    gem_quantities, = BtapCosting::Envelope::ThermalBridgingCosts.material_quantities(
      OracleProbes::Costing::TB_TALLIES, database, nil)
    legacy_quantities.each do |id, qty|
      assert_in_delta qty, gem_quantities[id.to_s], 1e-9, "material #{id} quantity"
    end
    assert_equal legacy_quantities.keys.sort, gem_quantities.keys.map(&:to_s).sort
  end
end
