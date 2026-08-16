# Rakefile for the NECB gem family.
#
# Deliberately does NOT `require 'bundler/gem_tasks'` — that binds a Rakefile to
# a single gemspec, and this repo holds nine. Build individual gems from their
# own directory (`cd openstudio-hvac && gem build openstudio-hvac.gemspec`).
#
# Every task below assumes it is run from the repository root, with the nine gem
# directories as direct children.

require 'rbconfig'

GEM_DIRS = Dir.glob('openstudio-*').select { |d| File.directory?(d) }.sort.freeze

desc 'List the gems in this repository'
task :gems do
  GEM_DIRS.each do |dir|
    # Most gems keep VERSION in lib/<name>/version.rb; openstudio-audit declares
    # it inline in its entry file. Search both rather than assuming.
    source = Dir.glob("#{dir}/lib/**/version.rb").first || Dir.glob("#{dir}/lib/*.rb").first
    version = source && File.read(source)[/VERSION\s*=\s*'([^']+)'/, 1]
    puts format('  %-24s %s', dir, version || '?')
  end
end

# --- NECB gem-family rule verification -------------------------------------
# Checks that declared NECB rules actually DO something, rather than trusting
# the `article_coverage` manifests' prose. See
# openstudio-necb/docs/necb_rule_verification.md for what each check proves.
namespace :necb do
  desc 'Lint: every rule key in a NECB ruleset JSON is read by that gem lib/'
  task :orphan_keys do
    # Pure Ruby, no OpenStudio SDK — safe on any CI node.
    abort('necb:orphan_keys failed') unless system(RbConfig.ruby, 'openstudio-necb/scripts/necb_orphan_keys.rb')
  end

  desc 'Hostile-outcome tests: reference transforms must overwrite non-compliant proposed values'
  task :hostile do
    # These need the SDK (require "openstudio") but NOT the openstudio CLI —
    # reference generation runs no EnergyPlus.
    failed = Dir.glob('openstudio-*/test/test_necb_hostile_reference.rb').sort.reject do |test|
      # chdir into the gem so the test's require_relative + fixture paths
      # resolve; pass the path RELATIVE to that new working directory.
      system(RbConfig.ruby, test.split('/', 2).last, chdir: test.split('/', 2).first)
    end
    abort("necb:hostile failed in: #{failed.join(', ')}") unless failed.empty?
  end

  desc 'Regenerate NECB_8_4_COVERAGE.html (+ NECB_GEM_COVERAGE.md) from manifests, citations and the cached 8.4 text'
  task :coverage_doc do
    # Pure Ruby, no SDK. Text cache refresh (openstudio-necb/scripts/fetch_necb_8_4_text.rb)
    # needs codes-MCP access and is NOT run here — CI regenerates from the
    # committed cache. Pass run evidence via NECB_AUDIT_JSONS=dir1:dir2
    # (directories containing audit.json + report.json from real runs).
    abort('necb:coverage_doc failed') unless system(RbConfig.ruby, 'openstudio-necb/scripts/generate_necb_gem_coverage.rb') &&
                                             system(RbConfig.ruby, 'openstudio-necb/scripts/generate_necb_8_4_coverage.rb')
  end

  desc 'Verify as-applied part-load curves against NECB 2025 Subsection 8.4.6 coefficients'
  task :curves do
    # SDK only, no CLI (components are hard-sized). Compares MODEL curves under
    # the documented transforms (FHeatPLC = PLR/eff, degF->degC surfaces).
    abort('necb:curves failed') unless system(RbConfig.ruby, 'openstudio-necb/scripts/necb_8_4_6_curve_probe.rb')
  end

  desc 'All NECB rule-verification checks (runs every check, then reports)'
  task :verify do
    # Deliberately NOT `task verify: %i[orphan_keys hostile]` — prerequisite
    # chaining aborts at the first failure, which hides the rest of the work
    # list. This is a "what still needs doing" report, so run everything.
    results = {
      'orphan_keys' => system(RbConfig.ruby, 'openstudio-necb/scripts/necb_orphan_keys.rb'),
      'curves_8_4_6' => system(RbConfig.ruby, 'openstudio-necb/scripts/necb_8_4_6_curve_probe.rb'),
      # .map(&:...).all? — NOT .all? { }, which short-circuits on the first
      # failing gem and hides the remaining work.
      'hostile' => Dir.glob('openstudio-*/test/test_necb_hostile_reference.rb').sort.map do |test|
        gem_dir, rel = test.split('/', 2)
        system(RbConfig.ruby, rel, chdir: gem_dir)
      end.all?
    }
    puts "\n#{'=' * 70}\nnecb:verify summary"
    results.each { |name, ok| puts format('  %-14s %s', name, ok ? 'OK' : 'WORK REQUIRED') }
    puts '=' * 70
    abort('necb:verify: see failures above') unless results.values.all?
  end
end
