# frozen_string_literal: true

# Ruby-side validator for the D-80 recursive golden inventory — the exact
# counterpart of verification/oracle/inventory.py's +validate+ (the skeleton
# grammar is documented there). The exporter refuses to PUBLISH any golden
# group that does not match its committed skeleton, so an oracle accessor
# quietly returning :unavailable/nil, a shrunk nested table, or a changed
# list length can never become a golden.
module OracleInventory
  module_function

  def leaf_type(value)
    case value
    when nil then 'null'
    when true, false then 'bool'
    when Numeric then 'num'
    when String then 'str'
    end
  end

  def key_of(item, fields)
    fields.map { |f| item[f].to_s }.join('|')
  end

  # @return [Array<String>] violations (empty = valid)
  def validate(value, skeleton, path = '$')
    if skeleton.is_a?(String)
      actual = leaf_type(value)
      return [] if actual == skeleton

      return ["#{path}: expected #{skeleton}, got #{actual || value.class}"]
    end
    return validate_dict(value, skeleton['__dict__'], path) if skeleton.key?('__dict__')

    validate_list(value, skeleton, path)
  end

  def validate_dict(value, spec, path)
    return ["#{path}: expected mapping, got #{value.class}"] unless value.is_a?(Hash)

    errors = []
    (spec.keys - value.keys).sort.each { |k| errors << "#{path}: missing key #{k.inspect}" }
    (value.keys - spec.keys).sort.each { |k| errors << "#{path}: unexpected key #{k.inspect}" }
    (spec.keys & value.keys).sort.each { |k| errors.concat(validate(value[k], spec[k], "#{path}/#{k}")) }
    errors
  end

  def validate_list(value, skeleton, path)
    mode = skeleton['__list__']
    return ["#{path}: expected list (#{mode}), got #{value.class}"] unless value.is_a?(Array)

    case mode
    when 'ordered'
      errors = []
      if value.length != skeleton['items'].length
        errors << "#{path}: ordered list length #{value.length} != #{skeleton['items'].length}"
      end
      value.zip(skeleton['items']).each_with_index do |(v, s), i|
        errors.concat(validate(v, s, "#{path}[#{i}]")) unless s.nil?
      end
      errors
    when 'keyed'
      fields = skeleton['key']
      errors = []
      have = {}
      value.each do |item|
        key = key_of(item, fields)
        # Silently collapsing duplicates would let a malformed oracle result
        # overwrite one entry with another and still validate — a false-green.
        errors << "#{path}: duplicate item #{key.inspect} (key #{fields})" if have.key?(key)
        have[key] = item
      end
      want = skeleton['items']
      (want.keys - have.keys).sort.each { |k| errors << "#{path}: missing item #{k.inspect} (key #{fields})" }
      (have.keys - want.keys).sort.each { |k| errors << "#{path}: unexpected item #{k.inspect} (key #{fields})" }
      (want.keys & have.keys).sort.each { |k| errors.concat(validate(have[k], want[k], "#{path}[#{k}]")) }
      errors
    when 'set'
      want = skeleton['members'].sort_by(&:to_json)
      have = value.sort_by(&:to_json)
      want == have ? [] : ["#{path}: set membership differs"]
    else
      ["#{path}: unknown list mode #{mode.inspect}"]
    end
  end
end
