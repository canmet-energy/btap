# frozen_string_literal: true

# D-80: RETIRES WITH R6. This driver runs the RUBY implementation as the
# cross-language baseline, so it lives exactly as long as the gems do; when
# the Ruby product is deleted (R6), the test that shells out to this file
# retires with it (its cross-language duty passes to the R4 frozen
# scenario suite).

# Cross-language M2 gate (D-79): run the SAME model through the RUBY
# btap-simulation gem (Local backend = the `openstudio` CLI) that
# test_local_run.py runs through the PYTHON port (Local backend = in-process
# ForwardTranslator + the provisioned energyplus binary). Writes results.json:
#
#   { "sizing": { "clean": bool },
#     "annual": { "clean": bool, "energy": {...},
#                 "unmet_occupied_hours": {...} } }
#
# The Python test diffs the two languages' results.json under
# verification/compare_runs.py's Leg-B rules — energies are pre-rounded so
# they compare exactly; unmet hours are raw and take the spec tolerance.
#
#   ruby ruby_reference.rb OUT_DIR

require 'json'
require 'fileutils'
require File.expand_path('../../../../btap-simulation/lib/btap_simulation', __dir__)

FIXTURES = File.expand_path('../../../../btap-modeling/test/fixtures', __dir__)
FIXTURE = File.expand_path('../../../../btap-modeling/lib/btap_modeling/hvac/data/5ZoneNoHVAC.osm', __dir__)
EPW = File.join(FIXTURES, 'weather/CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw')
DDY = File.join(FIXTURES, 'weather/CAN_ON_Toronto.Intl.AP.716240_CWEC2020.ddy')

out_dir = ARGV[0] or abort('usage: ruby_reference.rb OUT_DIR')
FileUtils.mkdir_p(out_dir)

load_model = -> { OpenStudio::Model::Model.load(OpenStudio::Path.new(FIXTURE)).get }

sizing = BtapSimulation.run(load_model.call, run_dir: File.join(out_dir, 'sizing'),
                            weather: { epw: EPW, ddy: DDY }, sizing_only: true)

# The annual leg carries a real HVAC system (as the Ruby gem's own
# test_local_run does) so heating/fan end-uses are non-zero and the
# cross-language equality is exercised on real numbers. Both languages build
# 'Baseboard gas boiler' with their OWN btap-modeling port.
require File.expand_path('../../../../btap-modeling/lib/btap_modeling', __dir__)
annual_model = load_model.call
BtapModeling.build_system(annual_model, 'Baseboard gas boiler',
                          annual_model.getThermalZones.sort_by(&:nameString))
annual = BtapSimulation.run(annual_model, run_dir: File.join(out_dir, 'annual'),
                            weather: { epw: EPW, ddy: DDY },
                            run_period: { begin_month: 1, begin_day: 1, end_month: 1, end_day: 7 })

File.write(File.join(out_dir, 'results.json'), JSON.pretty_generate(
  'sizing' => { 'clean' => sizing.clean? },
  'annual' => { 'clean' => annual.clean?, 'energy' => annual.energy,
                'unmet_occupied_hours' => annual.unmet_hours }
))
puts 'ruby reference complete'
