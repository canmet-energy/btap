#!/usr/bin/env ruby
# frozen_string_literal: true

# Exports the Leg-C ORACLE GOLDENS (D-78/D-80): every oracle-side value the
# Python golden tests compare, frozen to verification/oracle/goldens/*.json.
#
#   .venv/bin/python python/scripts/oracle_prep.py --out PREP
#   BUNDLE_GEMFILE=<repo>/legacy_pin/Gemfile bundle exec \
#     ruby verification/oracle/export_goldens.rb --prep PREP --out DIR
#
# python-prep / ruby-probe (D-80): this exporter is GEM-FREE. Every input
# whose preparation historically needed a btap-gem call arrives as an .osm
# built by python/scripts/oracle_prep.py (with its composition contract in
# prep_manifest.json); probe requests (schedule names, costing candidates)
# come from the committed request_manifest.json; SDK-only prep (weather
# attachment, the synthetic daylighting boxes) happens here. Runs ONLY under
# the pin (refuses otherwise — a golden not generated from the pinned oracle
# would be a fabrication).
#
# Guarantees on every export:
#   - OpenStudio identity (sdk_version AND build_sha) must equal the prep
#     run's, or the export aborts (BTAP_ORACLE_ALLOW_VERSION_SKEW=1 is the
#     explicit rebaseline override, recorded in the manifest).
#   - Publication is atomic and completeness-gated: every group is validated
#     against the request manifest's recursive inventory and the produced
#     file set must be EXACTLY the declared group set, all in a temporary
#     sibling directory, before a backup-swap promotion. A partial or
#     shape-drifted export can never land.
#
# In CI the pin lives on the parity runner: .github/workflows/goldens.yml
# (workflow_dispatch) runs this and uploads the result as an artifact.

require 'json'
require 'digest'
require 'date'
require 'fileutils'
require 'optparse'

ROOT = File.expand_path('../..', __dir__)
REF = File.read(File.join(ROOT, 'legacy_pin/REF')).strip

options = {}
OptionParser.new do |op|
  op.on('--prep DIR', 'directory written by python/scripts/oracle_prep.py') { |v| options[:prep] = v }
  op.on('--out DIR', 'goldens destination (backup-swapped if non-empty)') { |v| options[:out] = v }
end.parse!
abort('--prep and --out are required') unless options[:prep] && options[:out]

PREP = File.expand_path(options[:prep])
OUT_DIR = File.expand_path(options[:out])
REQUEST = JSON.parse(File.read(File.join(__dir__, 'request_manifest.json'), encoding: 'UTF-8'))
PREP_MANIFEST = JSON.parse(File.read(File.join(PREP, 'prep_manifest.json'), encoding: 'UTF-8'))

require File.join(__dir__, 'oracle_probes')
require File.join(__dir__, 'inventory')

std = OracleProbes::Access.standard
abort('the pinned oracle is not bundled — run under BUNDLE_GEMFILE=legacy_pin/Gemfile') if std == :unavailable
coster = OracleProbes::Access.coster
abort('the BTAP costing oracle failed to load') if coster == :unavailable

# ---- OpenStudio identity: prep and probe must be the same build ----------
prep_os = PREP_MANIFEST['provenance']['openstudio']
export_os = { 'sdk_version' => OpenStudio.openStudioVersion, 'build_sha' => OpenStudio.openStudioVersionBuildSHA }
version_skew = prep_os != export_os
if version_skew && ENV['BTAP_ORACLE_ALLOW_VERSION_SKEW'] != '1'
  abort("OpenStudio identity skew between prep #{prep_os} and exporter #{export_os} — " \
        'a golden must not mix builds. Re-run oracle_prep.py under this build, or set ' \
        'BTAP_ORACLE_ALLOW_VERSION_SKEW=1 (an explicit rebaseline decision) to proceed.')
end

FIXTURE = File.join(ROOT, 'btap-modeling/lib/btap_modeling/hvac/data/5ZoneNoHVAC.osm')
EPW = File.join(ROOT, 'btap-modeling/test/fixtures/weather/CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw')
DDY = File.join(ROOT, 'btap-modeling/test/fixtures/weather/CAN_ON_Toronto.Intl.AP.716240_CWEC2020.ddy')

def load_osm(path)
  model = OpenStudio::Model::Model.load(OpenStudio::Path.new(path))
  abort("cannot load #{path}") if model.empty?
  model.get
end

def load_prep(name)
  entry = PREP_MANIFEST['models'][name] or abort("prep_manifest has no entry for #{name}")
  path = File.join(PREP, name)
  actual = Digest::SHA256.hexdigest(File.read(path, encoding: 'BINARY'))
  abort("#{name}: checksum mismatch against prep_manifest") unless actual == entry['sha256']
  load_osm(path)
end

def load_fixture
  load_osm(FIXTURE)
end

def attach_weather!(model)
  epw = OpenStudio::EpwFile.new(OpenStudio::Path.new(EPW))
  OpenStudio::Model::WeatherFile.setWeatherFile(model, epw)
  ddy = OpenStudio::EnergyPlus.loadAndTranslateIdf(DDY).get
  ddy.getDesignDays.each { |dd| model.addObject(dd.clone) }
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
goldens['costing_envelope'] = {
  'interpolations' => OracleProbes::Costing.interpolations,
  'construction_costs' => OracleProbes::Costing.construction_costs(
    coster, REQUEST['costing_candidates'], 'ONTARIO', 'TORONTO'
  ),
  'priced_table' => 'vendored placeholder costs.csv (btap-costing data/); licensed values never frozen',
  'tbd_rsi' => OracleProbes::Costing.tbd_rsi(load_prep('tbd_rsi.osm')),
  'tb_material_quantities' => OracleProbes::Costing.tb_material_quantities
}

puts 'loads: schedules, apply, merged tables…'
goldens['loads_schedules'] = OracleProbes::Loads.schedules(std, REQUEST['schedule_names'])
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
goldens['lighting_daylighting'] = {
  'sidelighting' => side, 'skylight' => sky,
  'controls_on_fixture' => OracleProbes::Lighting.daylighting_controls(std, load_prep('daylighting_controls.osm'))
}

lighting_coster = OracleProbes::Access.lighting_coster
abort('the BTAP lighting costing oracle failed to load') if lighting_coster == :unavailable
goldens['lighting_costing'] = {
  'led_2020_total' => OracleProbes::Costing.lighting_total(
    lighting_coster, std, load_prep('lighting_costing.osm'), 'ONTARIO', 'TORONTO'
  ),
  'context' => 'fixture office-tagged, apply_lights LED, sensors+LED audits stubbed to 0, ONTARIO/TORONTO'
}

puts 'shw: demand + efficiency bins…'
goldens['shw'] = { 'swh' => OracleProbes::Shw.swh(std, load_prep('shw.osm')),
                   'efficiencies' => OracleProbes::Shw.efficiencies(std) }

# ---- completeness gate: every group, validated recursively, exact set ----
declared = REQUEST['golden_groups'].sort
produced = goldens.keys.sort
abort("produced group set #{produced} != declared #{declared}") unless produced == declared

violations = []
goldens.each do |group, data|
  round_tripped = JSON.parse(JSON.generate(data))
  violations.concat(OracleInventory.validate(round_tripped, REQUEST['golden_inventory'][group])
                                   .map { |v| "#{group}: #{v}" })
end
unless violations.empty?
  warn "INVENTORY VIOLATIONS (#{violations.length}) — refusing to publish:"
  violations.first(40).each { |v| warn "  #{v}" }
  abort('a golden that does not match the request manifest inventory is either an oracle ' \
        'shape change (adjudicate + update the manifest) or a broken probe. Nothing was written.')
end

# ---- atomic publication: temp sibling, manifest last, backup-swap --------
FileUtils.mkdir_p(File.dirname(OUT_DIR))
tmp = "#{OUT_DIR}.tmp.#{Process.pid}"
FileUtils.rm_rf(tmp)
FileUtils.mkdir_p(tmp)
files = {}
goldens.each do |name, data|
  path = File.join(tmp, "#{name}.json")
  File.write(path, JSON.pretty_generate(data))
  files["#{name}.json"] = Digest::SHA256.hexdigest(File.read(path, encoding: 'BINARY'))
  puts "  wrote #{name}.json (#{File.size(path)} bytes)"
end
File.write(File.join(tmp, 'manifest.json'), JSON.pretty_generate(
  'legacy_ref' => REF,
  'exported' => Date.today.to_s,
  'files' => files,
  'prep_provenance' => PREP_MANIFEST['provenance'],
  'version_skew_override' => version_skew
))

if File.directory?(OUT_DIR) && !Dir.empty?(OUT_DIR)
  backup = "#{OUT_DIR}.backup.#{Process.pid}"
  File.rename(OUT_DIR, backup)
  begin
    File.rename(tmp, OUT_DIR)
    FileUtils.rm_rf(backup)
  rescue StandardError
    File.rename(backup, OUT_DIR) unless File.directory?(OUT_DIR)
    raise
  end
else
  FileUtils.rm_rf(OUT_DIR) # empty dir, if any
  File.rename(tmp, OUT_DIR)
end
puts "manifest.json written — legacy_ref #{REF[0, 12]}, #{files.size} golden files, " \
     "prep commit #{PREP_MANIFEST['provenance']['commit'][0, 12]}"
