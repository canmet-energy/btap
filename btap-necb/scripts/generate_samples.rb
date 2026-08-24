#!/usr/bin/env ruby
# frozen_string_literal: true

# Generate the sample .osm set the Windows package ships.
#
#   ruby btap-necb/scripts/generate_samples.rb [outdir]
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
# constructions, and the envelope domain cannot build an opaque construction
# from nothing (the one real physics gap in Open work), so apply_prescriptive
# would silently skip and the reference envelope would be wrong. The shared
# fixture is a real DOE prototype and carries constructions.

require 'fileutils'
require 'set'
require 'openstudio'

ROOT = File.expand_path('../..', __dir__)
# Explicit literal paths, not interpolation — the btap-* migration renames
# directories, and a literal token is what a rename's sed pass can catch.
%w[
  btap-audit/lib/btap_audit
  openstudio-hvac/lib/openstudio_hvac
  btap-necb/lib/btap_necb/loads
  openstudio-lighting/lib/openstudio_lighting
  openstudio-shw/lib/openstudio_shw
].each { |entry| require File.expand_path(entry, ROOT) }

FIXTURE = File.join(ROOT, 'btap-modeling/test/fixtures/5ZoneNoHVAC.osm')
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

# The staged mixed-fuel plants, built by hand because no single catalog name
# produces a two-boiler set on two different fuels.
STAGED = [
  ['11-staged-boilers-gas-lead',      'NaturalGas', 'Electricity'],
  ['12-staged-boilers-electric-lead', 'Electricity', 'NaturalGas']
].freeze

# Cases chosen to make the REFERENCE-BUILDING logic visibly do something, rather
# than to cover another system. Each names the article it exercises, and the
# optional lambda is model-level setup the plain SAMPLES tuple cannot express.
#
#   [slug, catalog system, article + what to look for, ->(model) { setup }]
STRESS_CASES = [
  ['13-district-heating',
   'DOAS with fan coil air-cooled chiller with district hot water',
   '8.4.4.6.(1)(a) — purchased heating: the reference grows a gas-fired boiler ' \
   'where the proposed has none. MUST be a single-group system: with several ' \
   'single-zone groups the district loop survives the per-group teardown and is ' \
   'adopted by name, so the article is only half-applied.',
   nil],
  ['14-general-2storey',
   'Baseboard gas boiler',
   'Table 8.4.4.7.-A — General Area at 2 storeys selects reference System 3. ' \
   'Pairs with 15; one sample cannot show a flip.',
   ->(m) { m.getBuilding.setStandardsNumberOfAboveGroundStories(2) }],
  ['15-general-3storey',
   'Baseboard gas boiler',
   'Table 8.4.4.7.-A — the same building at 3 storeys crosses the threshold and ' \
   'selects System 6 instead.',
   ->(m) { m.getBuilding.setStandardsNumberOfAboveGroundStories(3) }],
  ['16-ashp-electric-supp-hw-baseboard',
   'PSZ RTU ASHP with Electric and ASHP with Electric Supp. Heat Coils and Hot Water Baseboard',
   '8.4.4.13.(2)(g) / D-52 — the auxiliary-fuel election. Needs --simulate annual: ' \
   'under :none it cannot run and the structural 8.4.4.9.(4) proxy answers instead. ' \
   'Proof that it RAN is the (g)(i) suffix on the article and the ELECTED wording, ' \
   'not the answer itself — this building delivers more gas (baseboard) than ' \
   'electric (supp coil), so the election and the proxy happen to agree on gas. ' \
   'A mixed-fuel heat pump is required for the election to be reachable at all; ' \
   'on an all-electric one there is nothing to elect between.',
   nil]
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
  audit = BtapNECB::AuditLog.new
  BtapNECB::Loads.apply_loads(model, vintage: vintage, audit: audit)
  OpenStudioLighting.apply_lights(model, vintage: vintage, audit: audit)
  OpenStudioSHW.apply_shw(model, vintage: vintage, fuel: 'NaturalGas', audit: audit)
  model
end

# Never ship a model that cannot simulate. The catalog sweep
# (rake hvac:simulate_systems) records which systems produce a simulate-able
# model; honour it here so this list self-corrects when a system is fixed rather
# than needing a human to remember. All 97 pass as of the defrost-curve fix; the
# gate stays because the next regression should skip a sample, not ship one.
STATUS = File.join(ROOT, 'btap-modeling/test/fixtures/system_simulation_status.json')
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
  BtapModeling.build_system(model, system, model.getThermalZones.sort_by(&:nameString))
  path = File.join(OUT, "#{slug}.osm")
  model.save(OpenStudio::Path.new(path), true)
  built << [slug, system, File.size(path)]
  puts format('  %-24s %-64s %6.1f MB', slug, system, File.size(path) / 1_048_576.0)
rescue StandardError => e
  warn("  FAILED #{slug} (#{system}): #{e.class}: #{e.message[0, 120]}")
end

# A staged, mixed-fuel hot-water plant: lead boiler on one fuel, second stage on
# the other, SequentialLoad so the staging is real rather than nominal. Exercises
# 8.4.4.9.(5)/8.4.4.10.(4) multi-energy capacity ratios — a DECLARED gap: the
# reference keeps the mixed plant unchanged. These exist as evidence of that.
notes = {}
STAGED.each do |slug, lead, backup|
  model = seed('2020')
  loop_ = BtapModeling::Systems::PlantLoops.hot_water(model, fuel: lead, backup_fuel: backup, reuse: false)
  loop_.setLoadDistributionScheme('SequentialLoad')
  BtapModeling.build_system(model, 'Baseboard gas boiler', model.getThermalZones.sort_by(&:nameString))
  path = File.join(OUT, "#{slug}.osm")
  model.save(OpenStudio::Path.new(path), true)
  built << [slug, "staged boilers: #{lead} lead, #{backup} second stage", File.size(path)]
  notes[slug] = '8.4.4.9.(5)/8.4.4.10.(4) multi-energy capacity ratios (a DECLARED gap: ' \
                'the reference keeps the mixed-fuel plant unchanged)'
  puts format('  %-36s %-52s %6.1f MB', slug, "#{lead} lead / #{backup} backup", File.size(path) / 1_048_576.0)
rescue StandardError => e
  warn("  FAILED #{slug}: #{e.class}: #{e.message[0, 120]}")
end

STRESS_CASES.each do |slug, system, note, setup|
  if SIMULATABLE && !SIMULATABLE.include?(system)
    skipped << [slug, system]
    next
  end

  model = seed('2020')
  setup&.call(model)
  BtapModeling.build_system(model, system, model.getThermalZones.sort_by(&:nameString))
  path = File.join(OUT, "#{slug}.osm")
  model.save(OpenStudio::Path.new(path), true)
  built << [slug, system, File.size(path)]
  notes[slug] = note
  puts format('  %-36s %-52s %6.1f MB', slug, system[0, 52], File.size(path) / 1_048_576.0)
rescue StandardError => e
  warn("  FAILED #{slug} (#{system}): #{e.class}: #{e.message[0, 120]}")
end

File.write(File.join(OUT, 'README.txt'), <<~TXT)
  Sample models — #{built.size} files, one building
  #{'=' * 62}

  The same 5-zone office (a DOE prototype, so it carries real constructions) in
  every file. Only the mechanical system changes, so the compliance verdict moves
  with the HVAC rather than with the building.

  All are tagged with NECB space types already, so no --space-type is needed:

    necb-compliance samples\\01-baseboard-gas.osm --city toronto --quick

  Drop --quick for a real 8.4.1.2 determination (40-90 min, four simulations).
  --quick shortens the run to a week and the tool refuses to call that a verdict.

  SYSTEMS — one per catalog family, spanning fuels and delivery types
  #{'-' * 62}
  #{built.reject { |slug, _, _| notes.key?(slug) }
         .map { |slug, sys, _| "  #{slug.ljust(36)} #{sys}" }.join("\n")}

  REFERENCE-LOGIC CASES — these make the NECB rules visibly do something
  #{'-' * 62}
  Run each with --simulate none first and read audit.txt; the interesting part is
  the decision, not the energy number.

  #{built.select { |slug, _, _| notes.key?(slug) }
         .map { |slug, sys, _| "  #{slug}\n    system: #{sys}\n    tests:  #{notes[slug]}\n" }
         .join("\n")}
TXT
unless skipped.empty?
  puts "\nSKIPPED — these systems do not currently produce a simulate-able model:"
  skipped.each { |slug, sys| puts format('  %-24s %s', slug, sys) }
end
puts "\n#{built.size} of #{SAMPLES.size + STAGED.size + STRESS_CASES.size} written to #{OUT}"
