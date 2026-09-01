# frozen_string_literal: true

# Generate a whole-building archetype with the PINNED oracle.
#
#   BUNDLE_GEMFILE=legacy_pin/Gemfile bundle exec ruby \
#     verification/oracle/gen_legacy_archetype.rb <out.osm> <sizing_dir> \
#     [template] [building_type] [epw]
#
# Oracle-side infrastructure, deliberately placed beside export_goldens.rb
# rather than inside a gem test: it depends ONLY on openstudio-standards at
# legacy_pin/REF, never on the btap gems, so it outlives them (D-80 R6) the
# same way the Leg-C exporter does. The consumer drives the comparison; this
# script only produces the oracle's model.
#
# Extracted verbatim from btap-necb/test/test_legacy_archetype_e2e.rb's
# Phase 1 so the Ruby gate and the Python successor generate byte-identical
# inputs from one implementation and cannot drift.

output_osm = ARGV[0] or raise 'usage: gen_legacy_archetype.rb <output_osm> <sizing_run_dir> [template] [building_type] [epw]'
sizing_run_dir = ARGV[1] or raise 'usage: gen_legacy_archetype.rb <output_osm> <sizing_run_dir> [template] [building_type] [epw]'
template = ARGV[2] || 'NECB2020'
building_type = ARGV[3] || 'SmallOffice'
epw = ARGV[4] || 'CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw'

# Resolved by bundler from legacy_pin/Gemfile — the PINNED oracle revision.
require 'openstudio-standards'

std = Standard.build(template)
model = std.model_create_prototype_model(
  template: template,
  building_type: building_type,
  epw_file: epw,
  sizing_run_dir: sizing_run_dir
)

if model.nil? || model.is_a?(FalseClass)
  warn "GENERATION FAILED: model_create_prototype_model returned #{model.inspect}"
  exit 1
end

model.save(OpenStudio::Path.new(output_osm), true)
puts "OK osm=#{output_osm} template=#{template} building_type=#{building_type}"
