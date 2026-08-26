#!/usr/bin/env ruby
# frozen_string_literal: true

# Leg-B corpus runner (D-78): drive the Ruby btap-compliance CLI over the
# committed corpus deterministically, so two invocations (or, later, the Ruby
# and Python CLIs) produce comparable run directories for compare_runs.py.
#
#   ruby verification/run_corpus.rb OUT_ROOT [--tier none|sizing]
#
# Corpus v1: the 17 generated installer samples (regenerated on demand — they
# are derived artifacts, never committed) + the raw 5-zone fixture driven
# through the space-type on-ramp. Tier `none` runs every model with
# --simulate none (fast; full reference-transform + rules coverage); tier
# `sizing` runs a subset through real E+ sizing (needs the openstudio CLI).
require 'fileutils'
require 'rbconfig'

ROOT = File.expand_path('..', __dir__)
OUT_ROOT = ARGV[0] or abort('usage: run_corpus.rb OUT_ROOT [--tier none|sizing]')
TIER = ARGV.include?('--tier') ? ARGV[ARGV.index('--tier') + 1] : 'none'
CLI = File.join(ROOT, 'btap-necb/exe/btap-compliance.rb')
SAMPLES = File.join(OUT_ROOT, '_samples')

# Samples are generated, not committed — build them once per corpus root.
unless File.exist?(File.join(SAMPLES, '01-baseboard-gas.osm'))
  puts 'generating the sample corpus…'
  system(RbConfig.ruby, File.join(ROOT, 'btap-necb/scripts/generate_samples.rb'), SAMPLES,
         out: File::NULL, err: File::NULL) or abort('sample generation failed')
end

BASE_ARGS = ['--hdd', '3890', '--storeys', '1', '--no-report', '--quiet'].freeze
FIXTURE_ARGS = (BASE_ARGS + ['--space-type', 'Space Function/Office enclosed > 25 m2']).freeze
SIZING_SUBSET = %w[01-baseboard-gas 02-psz-gas-dx 09-water-source-hp].freeze

runs = Dir.glob(File.join(SAMPLES, '*.osm')).sort.map { |m| [File.basename(m, '.osm'), m, BASE_ARGS] }
runs << ['5zone-onramp', File.join(ROOT, 'btap-modeling/test/fixtures/5ZoneNoHVAC.osm'), FIXTURE_ARGS]
runs.select! { |name, _, _| SIZING_SUBSET.include?(name) } if TIER == 'sizing'

failures = []
runs.each do |name, model, args|
  out_dir = File.join(OUT_ROOT, TIER, name)
  FileUtils.mkdir_p(out_dir)
  cmd = [RbConfig.ruby, CLI, model, '--simulate', TIER, *args, '-o', out_dir]
  ok = system(*cmd, out: File.join(out_dir, 'stdout.log'), err: %i[child out])
  # --simulate none/sizing exit 6 (no determination) BY DESIGN; only crashes
  # (nil exitstatus) and internal errors (5) are failures here.
  code = Process.last_status&.exitstatus
  audit_written = File.exist?(File.join(out_dir, 'audit.json'))
  failures << "#{name} (exit #{code.inspect}, audit=#{audit_written})" unless ok || (code == 6 && audit_written)
  puts format('  %-24s exit %-3s %s', name, code.inspect, audit_written ? 'audit.json ok' : 'NO AUDIT')
end

abort("corpus failures: #{failures.join(', ')}") unless failures.empty?
puts "corpus complete: #{runs.size} runs under #{File.join(OUT_ROOT, TIER)}"
