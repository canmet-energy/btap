require_relative 'test_helper'
require_relative '../../verification/oracle/oracle_probes'

# P2 gate (parity half): Lights objects + lighting schedules match legacy
# NECB2020 space_type_apply_internal_loads(set_lights: true) +
# space_type_apply_internal_load_schedules across representative space types —
# below/above the sensor threshold, NECB_Default and LED. Repo bundle only.
# Oracle-side signatures come from OracleProbes::Lighting.lights — the same
# function the Leg-C golden exporter freezes (D-78).
class TestLightsParity < Minitest::Test
  include FixtureHelper

  PAIRS = OracleProbes::Lighting::PAIRS

  def legacy
    OracleProbes::Access.gate!(self, OracleProbes::Access.standard)
  end

  def build(pairs)
    model = OpenStudio::Model::Model.new
    pairs.each { |bt, st| tagged_space_type(model, bt, st) }
    model
  end

  def run_parity(lights_type)
    std = legacy
    gem_model = build(PAIRS)
    BtapNECB::Lighting.apply_lights(gem_model, vintage: '2020', lights_type: lights_type)

    legacy_signatures = OracleProbes::Lighting.lights(std, PAIRS, lights_type)

    mismatches = []
    PAIRS.each do |bt, st_name|
      full = "#{bt} #{st_name}"
      gem_sig = OracleProbes::Signatures.lights_signature(gem_model.getSpaceTypes.find { |s| s.nameString == full })
      legacy_sig = legacy_signatures.fetch(full)
      next if gem_sig == legacy_sig

      keys = gem_sig.keys.select { |k| gem_sig[k] != legacy_sig[k] }
      mismatches << "#{st_name} [#{lights_type}]: #{keys.map { |k| "#{k}: gem=#{gem_sig[k].inspect[0, 80]} legacy=#{legacy_sig[k].inspect[0, 80]}" }.join('; ')}"
    end
    mismatches
  end

  def test_necb_default_parity
    assert_empty run_parity('NECB_Default').join("\n\n"), 'NECB_Default lights parity'
  end

  def test_led_parity
    assert_empty run_parity('LED').join("\n\n"), 'LED lights parity'
  end
end
