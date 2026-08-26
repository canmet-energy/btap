# frozen_string_literal: true

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
FIXTURE = File.join(FIXTURES, '5ZoneNoHVAC.osm')
EPW = File.join(FIXTURES, 'weather/CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw')
DDY = File.join(FIXTURES, 'weather/CAN_ON_Toronto.Intl.AP.716240_CWEC2020.ddy')

out_dir = ARGV[0] or abort('usage: ruby_reference.rb OUT_DIR')
FileUtils.mkdir_p(out_dir)

load_model = -> { OpenStudio::Model::Model.load(OpenStudio::Path.new(FIXTURE)).get }

sizing = BtapSimulation.run(load_model.call, run_dir: File.join(out_dir, 'sizing'),
                            weather: { epw: EPW, ddy: DDY }, sizing_only: true)

annual = BtapSimulation.run(load_model.call, run_dir: File.join(out_dir, 'annual'),
                            weather: { epw: EPW, ddy: DDY },
                            run_period: { begin_month: 1, begin_day: 1, end_month: 1, end_day: 7 })

File.write(File.join(out_dir, 'results.json'), JSON.pretty_generate(
  'sizing' => { 'clean' => sizing.clean? },
  'annual' => { 'clean' => annual.clean?, 'energy' => annual.energy,
                'unmet_occupied_hours' => annual.unmet_hours }
))
puts 'ruby reference complete'
