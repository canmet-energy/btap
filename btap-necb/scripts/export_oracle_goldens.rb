#!/usr/bin/env ruby
# frozen_string_literal: true

# Exports the Leg-C ORACLE GOLDENS (D-78): every oracle-side value the eleven
# parity gates compare, frozen to test/goldens/oracle/*.json — the files the
# Python port tests against DIRECTLY, so a bug faithfully ported from
# Ruby still fails even when Ruby and Python agree.
#
#   BUNDLE_GEMFILE=<repo>/legacy_pin/Gemfile bundle exec \
#     ruby btap-necb/scripts/export_oracle_goldens.rb
#
# Runs ONLY under the pin (refuses otherwise — a golden not generated from
# the pinned oracle would be a fabrication). The probes are the SAME code the
# gates run (test/support/oracle_probes.rb), so goldens and gates cannot
# drift; test/test_oracle_goldens_current.rb re-verifies the committed files
# against the live oracle in the parity job.
#
# In CI the pin lives on the parity runner: .github/workflows/goldens.yml
# (workflow_dispatch) runs this and uploads the result as an artifact to
# download and commit.

require 'json'
require 'digest'
require 'date'

ROOT = File.expand_path('../..', __dir__)
OUT_DIR = File.expand_path('../test/goldens/oracle', __dir__)
REF = File.read(File.join(ROOT, 'legacy_pin/REF')).strip

require File.join(ROOT, 'btap-necb/lib/btap_necb')
require File.join(ROOT, 'btap-necb/test/support/oracle_probes')

std = OracleProbes::Access.standard
abort('the pinned oracle is not bundled — run under BUNDLE_GEMFILE=legacy_pin/Gemfile') if std == :unavailable
coster = OracleProbes::Access.coster
abort('the BTAP costing oracle failed to load') if coster == :unavailable

FIXTURE = File.join(ROOT, 'btap-modeling/lib/btap_modeling/hvac/data/5ZoneNoHVAC.osm')
EPW = File.join(ROOT, 'btap-modeling/test/fixtures/weather/CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw')
DDY = File.join(ROOT, 'btap-modeling/test/fixtures/weather/CAN_ON_Toronto.Intl.AP.716240_CWEC2020.ddy')

def load_fixture
  OpenStudio::Model::Model.load(OpenStudio::Path.new(FIXTURE)).get
end

def attach_weather!(model)
  epw = OpenStudio::EpwFile.new(OpenStudio::Path.new(EPW))
  OpenStudio::Model::WeatherFile.setWeatherFile(model, epw)
  ddy = OpenStudio::EnergyPlus.loadAndTranslateIdf(DDY).get
  ddy.getDesignDays.each { |dd| model.addObject(dd.clone) }
  model
end

def office_tagged(model)
  map = model.getSpaces.to_h { |s| [s.nameString, ['Space Function', 'Office enclosed > 25 m2']] }
  BtapNECB::Loads.assign_space_types(model, map, vintage: '2020')
  model
end

# The prescriptive gate's subsurface patch, verbatim (fills default-set gaps
# that crash legacy customize_default_sub_surface_constructions_conductance).
def complete_default_subsurface_set!(model)
  model.getDefaultConstructionSets.each do |set|
    subs = set.defaultExteriorSubSurfaceConstructions
    next if subs.empty?

    subs = subs.get
    fallback_glazing = subs.fixedWindowConstruction
    fallback_opaque = subs.doorConstruction
    next if fallback_glazing.empty?

    subs.setOperableWindowConstruction(fallback_glazing.get) if subs.operableWindowConstruction.empty?
    subs.setGlassDoorConstruction(fallback_glazing.get) if subs.glassDoorConstruction.empty?
    subs.setSkylightConstruction(fallback_glazing.get) if subs.skylightConstruction.empty?
    subs.setTubularDaylightDomeConstruction(fallback_glazing.get) if subs.tubularDaylightDomeConstruction.empty?
    subs.setTubularDaylightDiffuserConstruction(fallback_glazing.get) if subs.tubularDaylightDiffuserConstruction.empty?
    subs.setOverheadDoorConstruction(fallback_opaque.get) if !fallback_opaque.empty? && subs.overheadDoorConstruction.empty?
  end
end

# The daylighting gate's synthetic box, verbatim (goldens key on the params).
def add_surface(model, space, points, type)
  vec = OpenStudio::Point3dVector.new
  points.each { |x, y, z| vec << OpenStudio::Point3d.new(x, y, z) }
  surface = OpenStudio::Model::Surface.new(vec, model)
  surface.setSpace(space)
  surface.setSurfaceType(type)
  surface
end

def glazing_construction(model, vt)
  glazing = OpenStudio::Model::SimpleGlazing.new(model)
  glazing.setUFactor(2.0)
  glazing.setSolarHeatGainCoefficient(0.4)
  glazing.setVisibleTransmittance(vt)
  construction = OpenStudio::Model::Construction.new(model)
  construction.setLayers([glazing])
  construction
end

def build_case(window: nil, skylight: nil)
  model = OpenStudio::Model::Model.new
  space = OpenStudio::Model::Space.new(model)
  floor = add_surface(model, space, [[0, 0, 0], [0, 8, 0], [10, 8, 0], [10, 0, 0]], 'Floor')
  wall = add_surface(model, space, [[0, 0, 3], [0, 0, 0], [10, 0, 0], [10, 0, 3]], 'Wall')
  wall.setOutsideBoundaryCondition('Outdoors')
  roof = add_surface(model, space, [[0, 0, 3], [10, 0, 3], [10, 8, 3], [0, 8, 3]], 'RoofCeiling')
  roof.setOutsideBoundaryCondition('Outdoors')
  if window
    x0, x1, z0, z1 = window
    vec = OpenStudio::Point3dVector.new
    [[x0, 0, z1], [x0, 0, z0], [x1, 0, z0], [x1, 0, z1]].each { |x, y, z| vec << OpenStudio::Point3d.new(x, y, z) }
    sub = OpenStudio::Model::SubSurface.new(vec, model)
    sub.setSurface(wall)
    sub.setSubSurfaceType('FixedWindow')
    sub.setConstruction(glazing_construction(model, 0.6))
  end
  if skylight
    x0, x1, y0, y1 = skylight
    vec = OpenStudio::Point3dVector.new
    [[x0, y0, 3], [x1, y0, 3], [x1, y1, 3], [x0, y1, 3]].each { |x, y, z| vec << OpenStudio::Point3d.new(x, y, z) }
    sub = OpenStudio::Model::SubSurface.new(vec, model)
    sub.setSurface(roof)
    sub.setSubSurfaceType('Skylight')
    sub.setConstruction(glazing_construction(model, 0.7))
  end
  [model, space, floor]
end

SIDELIGHTING_CASES = { 'window=2,6,0.8,2.5' => { window: [2.0, 6.0, 0.8, 2.5] },
                       'window=0.2,3,0.5,2.9' => { window: [0.2, 3.0, 0.5, 2.9] },
                       'window=0,10,0,3' => { window: [0.0, 10.0, 0.0, 3.0] } }.freeze
SKYLIGHT_CASES = { 'skylight=4,6,3,5+window=2,6,0.8,2.5' =>
                     { window: [2.0, 6.0, 0.8, 2.5], skylight: [4.0, 6.0, 3.0, 5.0] },
                   'skylight=4,6,3,5' => { skylight: [4.0, 6.0, 3.0, 5.0] } }.freeze

goldens = {}

puts 'envelope lookups…'
goldens['envelope_lookups'] = OracleProbes::Envelope.lookups(std)

puts 'envelope hdd18 (Toronto)…'
hdd_model = load_fixture
epw = OpenStudio::EpwFile.new(OpenStudio::Path.new(EPW))
OpenStudio::Model::WeatherFile.setWeatherFile(hdd_model, epw)
goldens['envelope_lookups']['hdd18'] = { File.basename(EPW) => OracleProbes::Envelope.hdd18(std, hdd_model) }

puts 'envelope prescriptive (fixture mutation)…'
goldens['envelope_prescriptive'] = OracleProbes::Envelope.prescriptive(
  std, attach_weather!(load_fixture), attach_weather!(load_fixture),
  subsurface_patch: method(:complete_default_subsurface_set!)
).merge('fixture' => File.basename(FIXTURE), 'weather' => File.basename(EPW),
        'note' => 'gem side: std.model_add_constructions on the raw fixture first, ' \
                  'then apply_prescriptive(include_films: false); D-32 ground floors excluded')

puts 'envelope U-table (pinned data file)…'
goldens['envelope_u_table'] = OracleProbes::Envelope.u_table(OracleProbes::Access.pin_root)

puts 'costing: interpolations, construction dollars, TBD RSI, bridging…'
database = BtapCosting::Envelope::Database.new
rsi_model = load_fixture
BtapNECB::Envelope.apply_prescriptive(rsi_model, vintage: '2020', hdd: 3890, audit: BtapNECB::AuditLog.new)
rsi_wall = rsi_model.getSurfaces.find { |s| s.outsideBoundaryCondition == 'Outdoors' && s.surfaceType == 'Wall' }
rsi_wall.setWindowToWallRatio(0.3)
BtapNECB::Envelope.apply_prescriptive(rsi_model, vintage: '2020', hdd: 3890, audit: BtapNECB::AuditLog.new)
goldens['costing_envelope'] = {
  'interpolations' => OracleProbes::Costing.interpolations,
  'construction_costs' => OracleProbes::Costing.construction_costs(coster, database, 'ONTARIO', 'TORONTO'),
  'priced_table' => 'vendored placeholder costs.csv (btap-costing data/); licensed values never frozen',
  'tbd_rsi' => OracleProbes::Costing.tbd_rsi(rsi_model),
  'tb_material_quantities' => OracleProbes::Costing.tb_material_quantities
}

puts 'loads: schedules, apply, merged tables…'
names = BtapNECB::Loads.table('2020', 'schedules').map { |r| r['name'] }.uniq
goldens['loads_schedules'] = OracleProbes::Loads.schedules(std, names)
goldens['loads_apply'] = OracleProbes::Loads.apply(std, OracleProbes::Loads::PAIRS)
goldens['loads_merged_tables'] = OracleProbes::Loads.merged_tables(std)

puts 'lighting: lights, daylighting, costing…'
goldens['lighting_lights'] = {
  'NECB_Default' => OracleProbes::Lighting.lights(std, OracleProbes::Lighting::PAIRS, 'NECB_Default'),
  'LED' => OracleProbes::Lighting.lights(std, OracleProbes::Lighting::PAIRS, 'LED')
}
side = SIDELIGHTING_CASES.to_h do |key, params|
  _, space, floor = build_case(**params)
  [key, OracleProbes::Lighting.sidelighting(std, space, floor)]
end
sky = SKYLIGHT_CASES.to_h do |key, params|
  _, space, = build_case(**params)
  [key, OracleProbes::Lighting.skylight(std, space)]
end
controls_model = office_tagged(load_fixture)
controls_wall = controls_model.getSurfaces.find { |s| s.outsideBoundaryCondition == 'Outdoors' && s.surfaceType == 'Wall' }
controls_wall.setWindowToWallRatio(0.4)
goldens['lighting_daylighting'] = { 'sidelighting' => side, 'skylight' => sky,
                                    'controls_on_fixture' => OracleProbes::Lighting.daylighting_controls(std, controls_model) }

lighting_coster = OracleProbes::Access.lighting_coster
abort('the BTAP lighting costing oracle failed to load') if lighting_coster == :unavailable
lc_model = office_tagged(load_fixture)
BtapNECB::Lighting.apply_lights(lc_model, vintage: '2020', lights_type: 'LED')
lc_model.getBuilding.setStandardsTemplate('NECB2020')
goldens['lighting_costing'] = {
  'led_2020_total' => OracleProbes::Costing.lighting_total(lighting_coster, std, lc_model, 'ONTARIO', 'TORONTO'),
  'context' => 'fixture office-tagged, apply_lights LED, sensors+LED audits stubbed to 0, ONTARIO/TORONTO'
}

puts 'shw: demand + efficiency bins…'
goldens['shw'] = { 'swh' => OracleProbes::Shw.swh(std, office_tagged(load_fixture)),
                   'efficiencies' => OracleProbes::Shw.efficiencies(std) }

require 'fileutils'
FileUtils.mkdir_p(OUT_DIR)
files = {}
goldens.each do |name, data|
  path = File.join(OUT_DIR, "#{name}.json")
  File.write(path, JSON.pretty_generate(data))
  files["#{name}.json"] = Digest::SHA256.hexdigest(File.read(path))
  puts "  wrote #{name}.json (#{File.size(path)} bytes)"
end
File.write(File.join(OUT_DIR, 'manifest.json'),
           JSON.pretty_generate('legacy_ref' => REF, 'exported' => Date.today.to_s, 'files' => files))
puts "manifest.json written — legacy_ref #{REF[0, 12]}, #{files.size} golden files"
