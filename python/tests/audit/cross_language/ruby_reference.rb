# frozen_string_literal: true

# D-80: RETIRES WITH R6. This driver runs the RUBY implementation as the
# cross-language baseline, so it lives exactly as long as the gems do; when
# the Ruby product is deleted (R6), the test that shells out to this file
# retires with it (its cross-language duty passes to the R4 frozen
# scenario suite).

# Cross-language M1 gate (D-79): build the SAME scripted audit scenario as
# tests/audit/test_cross_language.py and write audit.json + audit.txt. The
# Python test runs this against the Ruby btap-audit gem, then diffs the two
# languages' outputs with verification/compare_runs.py's machinery (JSON) and
# byte-compares the narrative. The scenario is deliberately duplicated in both
# languages — drift between the copies IS a comparison failure, so it cannot
# rot silently.
#
#   ruby ruby_reference.rb OUT_DIR

require 'json'
require File.expand_path('../../../../btap-audit/lib/btap_audit', __dir__)

out_dir = ARGV[0] or abort('usage: ruby_reference.rb OUT_DIR')

audit = BtapAudit::AuditLog.new

audit.with_building('input model') do
  audit.info(:load, 'model loaded — 1,000 m² floor area, climate 4200 HDD·°C',
             inputs: { path: 'model.osm', spaces: 5 })
end

audit.with_building('proposed building') do
  audit.decision(:characterize, 'zones grouped into one thermal block',
                 target: 'Thermal Zone 1',
                 inputs: { zones: ['Zone A', 'Zone B'], floor_area_m2: 123.456, conditioned: true },
                 value: 'System 6', article: '8.4.4.8.(1)', ruling: 'D-14')
  audit.warn(:efficiency, 'boiler efficiency UNKNOWN',
             inputs: { kw: 25.0, fuel: 'gas' }, evidence: "OS:Boiler 'B1'")
  audit.with_building('reference building') do
    audit.decision(:build, 'reference system operates on the proposed operating schedule',
                   article: '8.4.4.7.(1)', ruling: 'D-14 D-21')
  end
  audit.info(:rules, 'infiltration sentinel', value: 1.5e-05)
end

audit.decision(:verdict, 'proposed does not exceed the reference', value: true)
audit.info(:verdict, 'margin below threshold', value: 0)
audit.info(:verdict, 'eui supplement computed', value: false)

coverage = {
  'articles' => [
    { 'article' => '8.4.4.7.', 'title' => 'System selection', 'status' => 'implemented',
      'how' => 'Table 8.4.4.7.-A', 'code' => 'hvac/reference.rb#assign' },
    { 'article' => '8.4.4.9.', 'title' => 'Staged heating', 'status' => 'partial',
      'how' => 'two stages', 'gaps' => 'modulating burners' },
    { 'article' => '8.4.1.1. (HVAC)', 'title' => 'Modeller inputs', 'status' => 'partial',
      'gap_owner' => 'modeller', 'how' => 'schedules read from the model',
      'gaps' => 'occupancy assumptions' }
  ]
}
BtapAudit::Coverage.emit(coverage, audit)

File.write(File.join(out_dir, 'audit.json'), audit.to_json, encoding: 'UTF-8')
File.write(File.join(out_dir, 'audit.txt'), audit.to_s, encoding: 'UTF-8')
puts "wrote #{audit.entries.size} entries"
