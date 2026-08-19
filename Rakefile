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

# --- The legacy oracle ------------------------------------------------------
# This repository's ONLY tie to openstudio-standards is legacy_pin/REF, one
# commit SHA — not a branch, and not a git remote. So "has the fork moved?" is
# not a question git can answer from in here.
namespace :legacy do
  desc 'What has changed in the legacy fork since our pinned oracle (BRANCH=nrcan, LEGACY_FORK=/path for speed)'
  task :whatsnew do
    abort('legacy:whatsnew failed') unless system(RbConfig.ruby, 'openstudio-necb/scripts/legacy_whatsnew.rb')
  end

  desc 'Show the pinned oracle revision'
  task :pin do
    ref = File.read('legacy_pin/REF').strip
    puts "legacy_pin/REF = #{ref}"
    puts 'fork           = https://github.com/NatLabRockies/openstudio-standards'
    puts 'bump workflow  = legacy_pin/README.md'
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

# --- Windows packaging ------------------------------------------------------
# Stages the payload tree the Inno Setup script packages. Pure file copying, so
# it runs anywhere — but it CANNOT supply the bundled OpenStudio: the SDK in a
# Linux dev container is the Linux build, and the installer needs the Windows
# one. That has to be fetched and unpacked separately (see OPENSTUDIO_WINDOWS).
namespace :windows do
  STAGE = ENV.fetch('STAGE_DIR', 'packaging/windows/stage')

  # The priced RS-Means-derived tables are NOT redistributed. Costing still
  # works — the machinery and the unpriced sheets ship — but the user points
  # --costs-csv at their own licensed table, which is the injection route the
  # costing README already mandates.
  PRICED_CSVS = %w[costs.csv costs_local_factors.csv].freeze

  desc 'Stage the Windows payload tree (STAGE_DIR=, OPENSTUDIO_WINDOWS=<unpacked win SDK>)'
  task :stage do
    require 'fileutils'
    FileUtils.rm_rf(STAGE)
    FileUtils.mkdir_p("#{STAGE}/gems")

    # Mirror each gemspec's own spec.files rather than a glob written here, so
    # the staged tree cannot drift from what the gem declares it contains.
    total = 0
    root = Dir.pwd
    GEM_DIRS.each do |dir|
      # spec.files is `Dir['lib/**/*', ...]` evaluated at load time, and those
      # globs are relative to the CWD — NOT to the gemspec. Loading from the
      # repo root silently yields a near-empty file list, so chdir first.
      spec = Dir.chdir(dir) { Gem::Specification.load(File.basename(Dir.glob('*.gemspec').first.to_s)) }
      abort("cannot load gemspec in #{dir}") unless spec

      spec.files.each do |rel|
        next if PRICED_CSVS.include?(File.basename(rel)) && rel.include?('costing')

        src = File.join(root, dir, rel)
        next unless File.file?(src)

        dest = File.join(root, STAGE, 'gems', dir, rel)
        FileUtils.mkdir_p(File.dirname(dest))
        FileUtils.cp(src, dest)
        total += 1
      end
    end
    FileUtils.chmod(0o755, "#{STAGE}/gems/openstudio-necb/exe/necb-compliance.rb")

    # Sample + weather, taken from the shared fixtures.
    fixtures = 'openstudio-hvac/test/fixtures'
    FileUtils.mkdir_p(["#{STAGE}/samples", "#{STAGE}/weather", "#{STAGE}/bin"])
    FileUtils.cp("#{fixtures}/5ZoneNoHVAC.osm", "#{STAGE}/samples/")
    Dir.glob("#{fixtures}/weather/CAN_ON_Toronto*.{epw,ddy,stat}").each { |f| FileUtils.cp(f, "#{STAGE}/weather/") }

    %w[necb-compliance.cmd].each { |f| FileUtils.cp("packaging/windows/#{f}", "#{STAGE}/bin/") }
    FileUtils.cp('packaging/windows/run-demo.cmd', "#{STAGE}/samples/")
    FileUtils.cp('packaging/windows/README-windows.txt', STAGE)
    FileUtils.cp('LICENSE', "#{STAGE}/LICENSE-gems.txt")

    stage_openstudio

    puts "staged #{total} gem files -> #{STAGE}"
    puts "  size: #{`du -sh #{STAGE} 2>/dev/null`.split.first || '?'}"
    puts '  NOTE: no OpenStudio staged — set OPENSTUDIO_WINDOWS to an unpacked' unless ENV['OPENSTUDIO_WINDOWS']
    puts '        Windows OpenStudio 3.11.0 tree to make this installable.' unless ENV['OPENSTUDIO_WINDOWS']
  end

  # The bundled SDK must be the WINDOWS build. Copying the container's tree
  # would produce an installer full of ELF binaries, so refuse rather than
  # silently stage the wrong platform.
  def stage_openstudio
    src = ENV.fetch('OPENSTUDIO_WINDOWS', nil)
    return if src.nil? || src.empty?

    abort("OPENSTUDIO_WINDOWS=#{src} does not exist") unless File.directory?(src)
    unless File.exist?(File.join(src, 'bin', 'openstudio.exe'))
      abort("#{src} has no bin/openstudio.exe — that is not a Windows OpenStudio tree")
    end

    FileUtils.mkdir_p("#{STAGE}/openstudio")
    # Python/, include/, Radiance/ and Examples/ are unused by these gems (Ruby
    # only, no Radiance) and account for ~227 MB. Dropping them is optional —
    # set OPENSTUDIO_FULL=1 to stage the whole tree if anything misbehaves.
    skip = ENV['OPENSTUDIO_FULL'] ? [] : %w[Python include Radiance Examples]
    Dir.children(src).each do |entry|
      next if skip.include?(entry)

      FileUtils.cp_r(File.join(src, entry), "#{STAGE}/openstudio/")
    end
    puts "  bundled OpenStudio from #{src}#{skip.empty? ? '' : " (dropped: #{skip.join(', ')})"}"
  end
  desc 'Compile the staged tree into setup.exe via Inno Setup under wine'
  task :installer do
    iss = 'packaging/windows/necb-compliance.iss'
    abort("stage first: rake windows:stage (no #{STAGE})") unless Dir.exist?(STAGE)

    prefix = ENV['WINEPREFIX'] || File.expand_path('~/.wine-innosetup')
    iscc = File.join(prefix, 'drive_c/Program Files (x86)/Inno Setup 6/ISCC.exe')
    unless File.exist?(iscc)
      abort("Inno Setup not found at #{iscc}\n" \
            'Install it with: bash .devcontainer/setup.sh --wine')
    end

    # wine maps the filesystem root at Z:, and it needs a display even for a
    # headless compile — xvfb-run supplies one.
    win_iss = "Z:#{File.expand_path(iss).tr('/', '\\')}"
    ok = system({ 'WINEPREFIX' => prefix, 'WINEDEBUG' => '-all' },
                'xvfb-run', '-a', 'wine', iscc, win_iss)
    abort('ISCC failed') unless ok

    out = Dir.glob('packaging/windows/Output/*.exe').max_by { |f| File.mtime(f) }
    puts out ? "built #{out} (#{(File.size(out) / 1_048_576.0).round} MB)" : 'ISCC reported success but wrote no .exe'
  end
end
