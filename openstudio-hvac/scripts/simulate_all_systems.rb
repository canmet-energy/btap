#!/usr/bin/env ruby
# frozen_string_literal: true

# Build EVERY catalog system and put each through a real EnergyPlus sizing run.
#
#   ruby openstudio-hvac/scripts/simulate_all_systems.rb [--jobs N] [--only substring]
#
# Why a SIMULATION and not a unit assertion: the defect class this exists to
# catch is a required field left unset — e.g. the VRF outdoor unit's defrost
# EIR curve — which every in-process check happily ignores because the SDK
# models an unset optional field as simply absent. EnergyPlus is the only thing
# that calls it what it is:
#
#   ** Severe ** AirConditioner:VariableRefrigerantFlow, "VRF OUTDOOR UNIT"
#                Defrost Energy Input Ratio Modifier Function of Temperature
#                Curve Name not found:
#
# A user who builds that system gets a fatal, so the catalog owes them a system
# that at least starts. Sizing-only: this proves the input is VALID, not that
# the annual energy is right.

require 'json'
require 'fileutils'
require 'tmpdir'
require 'etc'
require 'etc'
require 'openstudio'

# Every core but a few: the reserve covers the parent, the OS, and the
# EnergyPlus child each job spawns, which the job slot does not account for.
DEFAULT_JOBS = [Etc.nprocessors - 4, 2].max

ROOT = File.expand_path('../..', __dir__)
# Explicit literal paths, not interpolation — the btap-* migration renames
# directories, and a literal token is what a rename's sed pass can catch.
%w[
  btap-audit/lib/btap_audit
  openstudio-hvac/lib/openstudio_hvac
  openstudio-loads/lib/openstudio_loads
  btap-simulation/lib/btap_simulation
].each { |entry| require File.expand_path(entry, ROOT) }

FIXTURES = File.join(ROOT, 'openstudio-hvac/test/fixtures')
EPW = File.join(FIXTURES, 'weather/CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw')
DDY = File.join(FIXTURES, 'weather/CAN_ON_Toronto.Intl.AP.716240_CWEC2020.ddy')

jobs = (ARGV[ARGV.index('--jobs') + 1].to_i if ARGV.include?('--jobs')) || DEFAULT_JOBS
only = (ARGV[ARGV.index('--only') + 1] if ARGV.include?('--only'))

systems = OpenStudioHVAC::Catalog.rows.map { |r| [r['name'], r['family']] }
systems.select! { |n, _| n.include?(only) } if only
puts "#{systems.size} systems, #{jobs} at a time"

def build(name)
  model = OpenStudio::Model::Model.load(OpenStudio::Path.new(File.join(FIXTURES, '5ZoneNoHVAC.osm'))).get
  model.getSpaceTypes.select { |st| st.spaces.any? }.each do |st|
    st.setStandardsBuildingType('Space Function')
    st.setStandardsSpaceType('Office enclosed > 25 m2')
  end
  OpenStudioLoads::NECB.apply_loads(model, vintage: '2020', audit: OpenStudioHVAC::AuditLog.new)
  OpenStudioHVAC.build_system(model, name, model.getThermalZones.sort_by(&:nameString))
  model
end

# Fork per system: a build or a translate can abort the process outright, and one
# bad system must not take the sweep with it.
results = []
systems.each_slice(jobs) do |batch|
  reader_by_pid = {}
  batch.each do |name, family|
    r, w = IO.pipe
    pid = fork do
      r.close
      outcome = begin
        Dir.mktmpdir do |dir|
          model = build(name)
          BtapSimulation::Runner.attach_weather!(model, epw: EPW, ddy: DDY)
          BtapSimulation::Runner.run_energyplus!(model, dir, sizing_only: true)
          { 'status' => 'ok' }
        end
      rescue StandardError => e
        severe = e.message[/\*\* Severe {2}\*\*(.+?)(?:\n|\z)/m, 1]&.strip
        { 'status' => 'fail', 'error' => (severe || e.message)[0, 220] }
      end
      w.write(JSON.generate(outcome.merge('name' => name, 'family' => family)))
      w.close
      exit!(0)
    end
    w.close
    reader_by_pid[pid] = r
  end
  reader_by_pid.each do |pid, r|
    raw = r.read
    r.close
    Process.wait(pid)
    results << (raw.empty? ? { 'status' => 'crash', 'name' => '?', 'family' => '?' } : JSON.parse(raw))
  end
  print '.'
end
puts

bad = results.reject { |x| x['status'] == 'ok' }.sort_by { |x| [x['family'].to_s, x['name'].to_s] }
puts "\n#{results.size - bad.size}/#{results.size} systems produce a simulate-able model"
unless bad.empty?
  puts "\nFAILING (#{bad.size}):"
  bad.each { |x| puts format("  %-22s %-62s %s", x['family'], x['name'], x['error']) }
end

out = File.join(ROOT, 'openstudio-hvac/test/fixtures/system_simulation_status.json')
File.write(out, "#{JSON.pretty_generate(results.sort_by { |x| x['name'].to_s })}\n")
puts "\nwrote #{out}"
exit(bad.empty? ? 0 : 1)
