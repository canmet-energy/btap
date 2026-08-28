# frozen_string_literal: true

# D-80: RETIRES WITH R6. This driver runs the RUBY implementation as the
# cross-language baseline, so it lives exactly as long as the gems do; when
# the Ruby product is deleted (R6), the test that shells out to this file
# retires with it (its cross-language duty passes to the R4 frozen
# scenario suite).

# The Ruby half of the M7 TBD process-parity gate (D-79 Option A): run the
# PINNED Ruby engine triplet (tbd 3.5.2 / osut 0.8.2 / topolys 0.6.2) on the
# btap fixture with the SAME arguments btap's thermal_bridging module builds,
# and dump the comparable snapshot — surfaces (deratable/heatloss/ratio/u),
# io edges (type/psi set/length/surfaces) and warning texts. The Python test
# reproduces the identical snapshot through py-tbd's tbd-3.5.2-compat branch
# and compares key sets in BOTH directions.
#
#   ruby ruby_tbd_reference.rb OUT.json

require 'json'
require 'openstudio'
require 'tbd'

abort('the Ruby side must be the PINNED 3.5.2 baseline') unless TBD::VERSION == '3.5.2'

ROOT = File.expand_path('../../../..', __dir__)
require File.join(ROOT, 'btap-necb/lib/btap_necb')

FIXTURE = File.join(ROOT, 'btap-modeling/lib/btap_modeling/hvac/data/5ZoneNoHVAC.osm')
HDD = 3890

model = OpenStudio::Model::Model.load(OpenStudio::Path.new(FIXTURE)).get

TBD.clean!
argh = {
  option: 'efficient (BETBG)',
  uprate_walls: true, uprate_roofs: true, uprate_floors: true,
  wall_option: 'all wall constructions',
  roof_option: 'all roof constructions',
  floor_option: 'all floor constructions',
  wall_ut: BtapNECB::Envelope.max_u(vintage: '2020', surface: 'wall', boundary: 'outdoors', hdd: HDD),
  roof_ut: BtapNECB::Envelope.max_u(vintage: '2020', surface: 'roofceiling', boundary: 'outdoors', hdd: HDD),
  floor_ut: BtapNECB::Envelope.max_u(vintage: '2020', surface: 'floor', boundary: 'outdoors', hdd: HDD)
}
result = TBD.process(model, argh)

surfaces = {}
(result[:surfaces] || {}).each do |name, s|
  surfaces[name.to_s] = {
    'deratable' => !!s[:deratable],
    'heatloss' => s[:heatloss].nil? ? nil : s[:heatloss].to_f,
    'ratio' => s[:ratio].nil? ? nil : s[:ratio].to_f,
    'u' => s[:u].nil? ? nil : s[:u].to_f
  }
end

edges = {}
((result[:io] || {})[:edges] || []).each do |e|
  key = format('%s|%s|%.6f', e[:type], e[:surfaces].map(&:to_s).sort.join('/'), e[:length].to_f)
  edges[key] = { 'type' => e[:type].to_s, 'psi_set' => e[:psi].to_s,
                 'length' => e[:length].to_f,
                 'surfaces' => e[:surfaces].map(&:to_s).sort }
end

warnings = TBD.logs.select { |l| l[:level].to_i >= 3 }.map { |l| l[:message].to_s }

File.write(ARGV[0], JSON.pretty_generate(
  { 'engine' => "ruby tbd #{TBD::VERSION}",
    'surfaces' => surfaces, 'edges' => edges, 'warnings' => warnings }))
warn "ruby tbd probe ok: #{surfaces.size} surfaces, #{edges.size} edges"
