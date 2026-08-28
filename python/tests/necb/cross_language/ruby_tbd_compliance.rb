# frozen_string_literal: true

# D-80: RETIRES WITH R6. This driver runs the RUBY implementation as the
# cross-language baseline, so it lives exactly as long as the gems do; when
# the Ruby product is deleted (R6), the test that shells out to this file
# retires with it (its cross-language duty passes to the R4 frozen
# scenario suite).

# The Ruby half of the M7 assembled Leg-B thermal-bridging gate: a full
# performance_compliance run (simulate: :none — the reference transforms,
# incl. the 3.1.1.7 TBD pass with 'efficient (BETBG)') on the tagged
# fixture, leaving audit.json/report.json in ARGV[0] for compare_runs.py.
# The existing Leg-B corpus never requests thermal bridging, so re-running
# it is not M7 evidence — THIS case is.
#
#   ruby ruby_tbd_compliance.rb RUN_DIR

require 'openstudio'
require 'tbd'

abort('the Ruby side must be the PINNED 3.5.2 baseline') unless TBD::VERSION == '3.5.2'

ROOT = File.expand_path('../../../..', __dir__)
require File.join(ROOT, 'btap-necb/lib/btap_necb')

FIXTURE = File.join(ROOT, 'btap-modeling/lib/btap_modeling/hvac/data/5ZoneNoHVAC.osm')

model = OpenStudio::Model::Model.load(OpenStudio::Path.new(FIXTURE)).get
model.getSpaceTypes.select { |st| st.spaces.any? }.each do |st|
  st.setStandardsBuildingType('Space Function')
  st.setStandardsSpaceType('Office enclosed > 25 m2')
end

BtapNECB.performance_compliance(
  model, vintage: '2020', simulate: :none, hdd: 3890,
  building: { storeys: 1 }, thermal_bridging: 'efficient (BETBG)',
  run_dir: ARGV[0])
warn 'ruby tbd compliance run ok'
