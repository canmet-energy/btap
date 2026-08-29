require_relative 'test_helper'
require_relative '../../verification/oracle/inventory'
require 'json'

# Negative tests for the Ruby half of the D-80 recursive inventory validator
# (verification/oracle/inventory.rb) — the exporter's completeness gate.
# The Python twin is python/tests/test_inventory_validation.py.
class TestOracleInventory < Minitest::Test
  SKELETON = {
    '__list__' => 'keyed', 'key' => ['id'],
    'items' => { 'a' => { '__dict__' => { 'id' => 'str', 'v' => 'num' } },
                 'b' => { '__dict__' => { 'id' => 'str', 'v' => 'num' } } }
  }.freeze
  CLEAN = [{ 'id' => 'a', 'v' => 1.0 }, { 'id' => 'b', 'v' => 2.0 }].freeze

  def test_clean_data_validates
    assert_empty OracleInventory.validate(CLEAN, SKELETON)
  end

  def test_duplicate_keys_are_refused_not_collapsed
    # The post-merge High: to_h silently overwrote one duplicate with the
    # other and returned zero errors — a false-green in the export gate.
    malformed = [{ 'id' => 'a', 'v' => 1.0 }, { 'id' => 'a', 'v' => 99.0 },
                 { 'id' => 'b', 'v' => 2.0 }]
    errors = OracleInventory.validate(malformed, SKELETON)
    assert errors.any? { |e| e.include?('duplicate item "a"') },
           "duplicate key collapsed silently: #{errors.inspect}"
  end

  def test_missing_and_extra_items_are_named
    errors = OracleInventory.validate([CLEAN.first], SKELETON)
    assert errors.any? { |e| e.include?('missing item "b"') }
    errors = OracleInventory.validate(CLEAN + [{ 'id' => 'c', 'v' => 3.0 }], SKELETON)
    assert errors.any? { |e| e.include?('unexpected item "c"') }
  end

  def test_nested_shrinkage_named_by_path
    skeleton = { '__dict__' => { 'inner' => { '__list__' => 'ordered', 'items' => %w[num num] } } }
    errors = OracleInventory.validate({ 'inner' => [1.0] }, skeleton)
    assert errors.any? { |e| e.include?('length 1 != 2') }, errors.inspect
  end
end
