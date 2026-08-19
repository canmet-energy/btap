#!/usr/bin/env ruby
# frozen_string_literal: true

# Generate the sample .osm set the Windows package ships.
#
#   ruby openstudio-necb/scripts/generate_samples.rb [outdir]
#
# ONE building, MANY HVAC systems. That is the point: the demo is about the
# compliance pipeline's response to different mechanical systems, and holding
# the envelope and loads constant makes the comparison legible.
#
# Why not openstudio-standards archetypes, which would be more realistic:
#   * they need the pinned oracle checked out (a ~4.6 GB clone) to generate, so
#     nobody could regenerate these from a fresh checkout; and
#   * the legacy archetypes' Kiva OS:Foundation objects currently hit an
#     EnergyPlus fatal in the reference sizing run (see CLAUDE.md / Open work).
#     Shipping demo files that crash would be worse than shipping simple ones.
#
# Why not wizard geometry, which would be prettier: wizard output carries NO
# constructions, and openstudio-envelope cannot build an opaque construction
# from nothing (the one real physics gap in Open work), so apply_prescriptive
# would silently skip and the reference envelope would be wrong. The shared
# fixture is a real DOE prototype and carries constructions.

require 'fileutils'
require 'set'
require 'openstudio'

ROOT = File.expand_path('../..', __dir__)
%w[audit hvac loads lighting shw].each do |g|
  require File.expand_path("openstudio-#{g}/lib/openstudio_#{g}", ROOT)
end

FIXTURE = File.join(ROOT, 'openstudio-hvac/test/fixtures/5ZoneNoHVAC.osm')
OUT = ARGV[0] || File.join(ROOT, 'packaging/windows/samples')

# One per family where the family is distinct enough to be worth a file, chosen
# to span fuel types and delivery types rather than to be exhaustive: 97 systems
# would be a test suite, not a sample set.
SAMPLES = [
  ['01-baseboard-gas',        'Baseboard gas boiler'],
  ['02-psz-gas-dx',           'PSZ RTU Gas and DX Coils and Hot Water Baseboard'],
  ['03-vav-reheat-chiller',   'MZ BU RTU Electric Heating Coil Scroll Chiller and Electric Baseboard'],
  ['04-fancoil-chiller',      'FPFC MAU DX Coils with Scroll Chiller'],
  ['05-ptac-electric',        'PTAC with baseboard electric'],
  ['06-unit-heaters-gas',     'Gas unit heaters'],
  ['07-furnace-forced-air',   'Forced air furnace'],
  ['08-vrf',                  'VRF'],
  ['09-water-source-hp',      'Water source heat pumps'],
  ['10-ashp-pthp',            'hs11_ashp_pthp']
].freeze

def seed(vintage)
  model = OpenStudio::Model::Model.load(OpenStudio::Path.new(FIXTURE)).get
  # The fixture is ASHRAE-tagged; the NECB pre-flight (correctly) rejects that.
  # Tag it so the samples run with no --space-type on the command line — a demo
  # whose first step is a refusal is a bad demo.
  model.getSpaceTypes.select { |st| st.spaces.any? }.each do |st|
    st.setStandardsBuildingType('Space Function')
    st.setStandardsSpaceType('Office enclosed > 25 m2')
  end
  audit = OpenStudioHVAC::AuditLog.new
  OpenStudioLoads::NECB.apply_loads(model, vintage: vintage, audit: audit)
  OpenStudioLighting.apply_lights(model, vintage: vintage, audit: audit)
  OpenStudioSHW.apply_shw(model, vintage: vintage, fuel: 'NaturalGas', audit: audit)
  model
end

# Never ship a model that cannot simulate. The catalog sweep
# (rake hvac:simulate_systems) records which systems produce a simulate-able
# model; honour it here so this list self-corrects when a system is fixed rather
# than needing a human to remember. Eight heat-pump systems currently fail on an
# unset defrost curve — see openstudio-hvac/test/test_system_simulation_status.rb.
STATUS = File.join(ROOT, 'openstudio-hvac/test/fixtures/system_simulation_status.json')
SIMULATABLE = if File.exist?(STATUS)
                require 'json'
                JSON.parse(File.read(STATUS, encoding: 'UTF-8'))
                    .select { |r| r['status'] == 'ok' }.map { |r| r['name'] }.to_set
              end

FileUtils.mkdir_p(OUT)
built = []
skipped = []
SAMPLES.each do |slug, system|
  if SIMULATABLE && !SIMULATABLE.include?(system)
    skipped << [slug, system]
    next
  end

  model = seed('2020')
  OpenStudioHVAC.build_system(model, system, model.getThermalZones.sort_by(&:nameString))
  path = File.join(OUT, "#{slug}.osm")
  model.save(OpenStudio::Path.new(path), true)
  built << [slug, system, File.size(path)]
  puts format('  %-24s %-64s %6.1f MB', slug, system, File.size(path) / 1_048_576.0)
rescue StandardError => e
  warn("  FAILED #{slug} (#{system}): #{e.class}: #{e.message[0, 120]}")
end

File.write(File.join(OUT, 'README.txt'), <<~TXT)
  Sample models — one building, #{built.size} HVAC systems
  #{'=' * 60}

  The same 5-zone office (a DOE prototype, real constructions) with a different
  mechanical system in each file, so you can watch the compliance verdict move
  with the HVAC rather than with the building.

  They are tagged with NECB space types already, so no --space-type is needed:

    necb-compliance samples\\01-baseboard-gas.osm --city toronto --quick

  Drop --quick for a real 8.4.1.2 determination (40-90 min, four simulations).

  #{built.map { |slug, sys, _| "  #{slug.ljust(24)} #{sys}" }.join("\n")}
TXT
unless skipped.empty?
  puts "\nSKIPPED — these systems do not currently produce a simulate-able model:"
  skipped.each { |slug, sys| puts format('  %-24s %s', slug, sys) }
end
puts "\n#{built.size}/#{SAMPLES.size} written to #{OUT}"
