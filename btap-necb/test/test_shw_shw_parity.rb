require_relative 'test_helper'
require_relative 'support/oracle_probes'

# Parity vs legacy: (1) auto-size arithmetic + water-use objects vs
# model_add_swh; (2) efficiency values across every bin vs the NECB2020
# water_heater_mixed_apply_efficiency. Repo bundle only.
# Oracle-side signatures come from OracleProbes::Shw — the same functions
# the Leg-C golden exporter freezes (D-78).
class TestSHWParity < Minitest::Test
  include FixtureHelper

  def legacy
    OracleProbes::Access.gate!(self, OracleProbes::Access.standard)
  end

  def optional(value)
    value.is_initialized ? value.get : nil
  end

  def test_demand_and_tank_parity
    std = legacy
    legacy_sig = OracleProbes::Shw.swh(std, tagged_model)

    gem_model = tagged_model
    BtapNECB::SHW.apply_shw(gem_model, vintage: '2020', fuel: 'NaturalGas')

    gem_heater = gem_model.getWaterHeaterMixeds.first
    refute_nil legacy_sig['heater']
    refute_nil gem_heater
    assert_in_delta legacy_sig['heater']['tank_volume_m3'], optional(gem_heater.tankVolume), 1e-9,
                    'tank volume (legacy peak-hour rule)'
    assert_in_delta legacy_sig['heater']['capacity_w'], optional(gem_heater.heaterMaximumCapacity),
                    legacy_sig['heater']['capacity_w'] * 1e-6, 'tank capacity'
    assert_in_delta legacy_sig['heater']['parasitic_w'],
                    gem_heater.onCycleParasiticFuelConsumptionRate, 1e-6, 'parasitic loss'
    assert_equal legacy_sig['heater']['fuel'], gem_heater.heaterFuelType

    legacy_wue = legacy_sig['water_use']
    gem_wue = OracleProbes::Signatures.water_use_signatures(gem_model)
    assert_equal legacy_wue.size, gem_wue.size, 'same demanding spaces'
    legacy_wue.zip(gem_wue).each do |l, g|
      assert_equal l['space'], g['space']
      assert_in_delta l['peak_flow_m3s'], g['peak_flow_m3s'], 1e-12,
                      "peak flow for #{l['space']}"
      assert_equal l['schedule'], g['schedule']
    end
  end

  def test_efficiency_parity_every_bin
    std = legacy
    legacy_bins = OracleProbes::Shw.efficiencies(std)
    mismatches = []
    OracleProbes::Shw::EFFICIENCY_CASES.each do |fuel, capacity_w, volume_m3|
      gem_model = OpenStudio::Model::Model.new
      gem_heater = OpenStudio::Model::WaterHeaterMixed.new(gem_model)
      gem_heater.setTankVolume(volume_m3)
      gem_heater.setHeaterMaximumCapacity(capacity_w)
      gem_heater.setHeaterFuelType(fuel)
      BtapNECB::SHW.apply_water_heater_efficiency(gem_heater, vintage: '2020')

      l = legacy_bins.fetch("#{fuel}/#{capacity_w}/#{volume_m3}")
      g = OracleProbes::Signatures.water_heater_efficiency_signature(gem_heater)
      next if (l['efficiency'] - g['efficiency']).abs < 1e-9 &&
              (l['ua_w_k'] - g['ua_w_k']).abs < 1e-9 &&
              l['plf_curve'] == g['plf_curve'] &&
              l['parasitic_frac_to_tank'] == g['parasitic_frac_to_tank']

      mismatches << "#{fuel} #{capacity_w}W #{volume_m3}m3: eff #{l['efficiency']} vs " \
                    "#{g['efficiency']}; UA #{l['ua_w_k']} vs #{g['ua_w_k']}; curve #{l['plf_curve']}/#{g['plf_curve']}"
    end
    assert_empty mismatches, "efficiency parity mismatches:\n#{mismatches.join("\n")}"
  end
end
