#!/usr/bin/env ruby
# frozen_string_literal: true

# ONE-TIME bootstrap input dump for verification/oracle/request_manifest.json
# (D-80). This is deliberately THE LAST GEM-DERIVED ACT in the verification
# stack: the request manifest must be implementation-independent, so its
# schedule-name and costing-candidate inventories are bootstrapped once from
# the gem data that defined them historically, recorded with provenance, and
# thereafter immutable except by adjudicated update. This script is kept for
# provenance and re-adjudication only — nothing in CI runs it.
#
#   ruby verification/oracle/dump_bootstrap_inputs.rb > /tmp/bootstrap_inputs.json

require 'json'
require 'digest'

ROOT = File.expand_path('../..', __dir__)
require File.join(ROOT, 'btap-necb/lib/btap_necb')

schedule_names = BtapNECB::Loads.table('2020', 'schedules').map { |r| r['name'] }.uniq

database = BtapCosting::Envelope::Database.new
candidates = []
database.constructions.each do |sheet, assemblies|
  assemblies.each_key do |assembly|
    database.construction_candidates(sheet, assembly).each do |rsi, construction|
      candidates << { 'key' => "#{sheet}/#{assembly}/#{rsi.round(3)}",
                      'type' => construction['type'],
                      'id_layers' => construction['id_layers'] }
    end
  end
end

# Provenance: the gem data files these inventories came from.
sources = {}
[File.join(ROOT, 'btap-necb/lib/btap_necb/data'),
 File.join(ROOT, 'btap-costing/data')].each do |dir|
  Dir[File.join(dir, '**', '*.{json,csv}')].sort.each do |path|
    sources[path.sub("#{ROOT}/", '')] = Digest::SHA256.hexdigest(File.read(path))
  end
end

puts JSON.pretty_generate(
  'schedule_names' => schedule_names,
  'costing_candidates' => candidates,
  'source_hashes' => sources,
  'commit' => `git -C #{ROOT} rev-parse HEAD`.strip
)
