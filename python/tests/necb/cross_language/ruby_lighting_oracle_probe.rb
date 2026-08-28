# frozen_string_literal: true

# The Ruby half of the PYTHON Leg-A lighting-costing gate (M8): compute the
# LIVE pinned oracle's lighting total for the LED/NECB2020 costed fixture —
# the same OracleProbes recipe the Ruby parity gate
# (btap-necb/test/test_lighting_costing.rb#test_legacy_parity_led_2020) runs
# — and write it as JSON for the Python test to compare against.
#
# Needs the oracle bundle:
#   BUNDLE_GEMFILE=legacy_pin/Gemfile bundle exec ruby ruby_lighting_oracle_probe.rb OUT.json
#
# Exits 3 (a distinct, checkable status) when the oracle is not bundled, so
# the Python side can tell "no oracle here" from a real probe failure.

require 'json'
require 'openstudio'

ROOT = File.expand_path('../../../..', __dir__)
require File.join(ROOT, 'btap-necb/lib/btap_necb')
require File.join(ROOT, 'btap-necb/test/support/oracle_probes')

coster = OracleProbes::Access.lighting_coster
std = OracleProbes::Access.standard
if coster == :unavailable || std == :unavailable
  warn 'legacy oracle not bundled — run under BUNDLE_GEMFILE=legacy_pin/Gemfile'
  exit 3
end

FIXTURE = File.join(ROOT, 'btap-modeling/lib/btap_modeling/hvac/data/5ZoneNoHVAC.osm')
OFFICE = ['Space Function', 'Office enclosed > 25 m2'].freeze

model = OpenStudio::Model::Model.load(OpenStudio::Path.new(FIXTURE)).get
map = model.getSpaces.to_h { |s| [s.nameString, OFFICE] }
BtapNECB::Loads.assign_space_types(model, map, vintage: '2020')
# NECB2020 template => the legacy coster forces LED, so the gem side costs LED too
BtapNECB::Lighting.apply_lights(model, vintage: '2020', lights_type: 'LED')

total = OracleProbes::Costing.lighting_total(coster, std, model, 'ONTARIO', 'TORONTO')
File.write(ARGV[0], JSON.generate({ 'led_2020_total' => total.to_f }))
warn "oracle lighting total: #{total}"
