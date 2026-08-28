require_relative 'test_helper'
require_relative '../../verification/oracle/oracle_probes'

# P3 gate (parity half): per-object load values match legacy
# space_type_apply_internal_loads(set_lights: false) + schedule/thermostat applies
# on identically tagged models, across several space types (occupancy-heavy,
# ventilation-ACH, gas-equipment). Runs under the repo bundle.
# Oracle-side signatures come from OracleProbes::Loads.apply — the same
# function the Leg-C golden exporter freezes (D-78).
class TestApplyParity < Minitest::Test
  include FixtureHelper

  PAIRS = OracleProbes::Loads::PAIRS

  def legacy
    OracleProbes::Access.gate!(self, OracleProbes::Access.standard)
  end

  def existing_pairs
    PAIRS.select do |building_type, space_type|
      BtapNECB::Loads::SpaceTypes.find(building_type: building_type, space_type: space_type)
    end
  end

  def tagged_model(pairs)
    model = OpenStudio::Model::Model.new
    pairs.each do |building_type, space_type|
      st = OpenStudio::Model::SpaceType.new(model)
      st.setName("#{building_type} #{space_type}")
      st.setStandardsBuildingType(building_type)
      st.setStandardsSpaceType(space_type)
    end
    model
  end

  def optional_name(optional)
    OracleProbes::Signatures.optional_name(optional)
  end

  def test_per_object_parity
    std = legacy
    pairs = existing_pairs
    assert_operator pairs.size, :>=, 4, "enough real space types to compare (#{pairs.inspect})"

    gem_model = tagged_model(pairs)
    BtapNECB::Loads.apply_loads(gem_model, vintage: '2020')

    legacy_signatures = OracleProbes::Loads.apply(std, pairs)

    mismatches = []
    pairs.each do |building_type, space_type_name|
      full = "#{building_type} #{space_type_name}"
      gem_st = gem_model.getSpaceTypes.find { |s| s.nameString == full }
      gem_signature = OracleProbes::Signatures.loads_signature(gem_st)
      legacy_signature = legacy_signatures.fetch(full)['loads']
      next if gem_signature == legacy_signature

      diff = gem_signature.keys.select { |k| gem_signature[k] != legacy_signature[k] }
                          .map { |k| "#{k}: gem=#{gem_signature[k].inspect} legacy=#{legacy_signature[k].inspect}" }
      mismatches << "#{space_type_name}: #{diff.join('; ')}"
    end
    assert_empty mismatches, "per-object parity mismatches:\n#{mismatches.join("\n")}"

    # thermostat schedule parity
    pairs.each do |building_type, space_type_name|
      full = "#{building_type} #{space_type_name} Thermostat"
      gem_t = gem_model.getThermostatSetpointDualSetpoints.find { |t| t.nameString == full }
      legacy_t = legacy_signatures.fetch("#{building_type} #{space_type_name}")['thermostat']
      refute_nil gem_t, full
      refute_nil legacy_t, full
      assert_equal legacy_t['heating'],
                   optional_name(gem_t.heatingSetpointTemperatureSchedule), full
      assert_equal legacy_t['cooling'],
                   optional_name(gem_t.coolingSetpointTemperatureSchedule), full
    end
  end
end
