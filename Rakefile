# Rakefile for the NECB gem family.
#
# Deliberately does NOT `require 'bundler/gem_tasks'` — that binds a Rakefile to
# a single gemspec, and this repo holds nine. Build individual gems from their
# own directory (`cd openstudio-hvac && gem build openstudio-hvac.gemspec`).
#
# Every task below assumes it is run from the repository root, with the nine gem
# directories as direct children.

require 'rbconfig'
require 'etc'

GEM_DIRS = Dir.glob('openstudio-*').select { |d| File.directory?(d) }.sort.freeze

# Default parallelism: every core but a few.
#
# The reserve is for the parent process, the OS, and — the reason it is not
# zero — the EnergyPlus child processes the heavier suites spawn, which are not
# counted by the job slots holding them. Measured on this workload a test
# process is ~124 MB resident, so memory is not the binding constraint; the real
# ceiling is the file count, beyond which extra slots idle and wall time is just
# the slowest single file.
#
# JOBS= overrides it.
def default_jobs
  # The floor of 2 is load-bearing, not a nicety: a GitHub-hosted runner has
  # very few cores, and `nprocessors - reserve` would clamp to 1 there and make
  # the "parallel" runner strictly sequential. Two still overlaps one suite's
  # EnergyPlus wait with another's startup, which is where the CI gain comes
  # from — those runs are as much I/O as CPU.
  [Etc.nprocessors - 4, 2].max
end


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

# --- Tests -----------------------------------------------------------------
# The suites are plain `ruby test/test_x.rb` files with no shared state, so they
# parallelize across FILES for free. CI's matrix already parallelizes across
# gems; within a gem it runs them one at a time, which is why openstudio-hvac
# (46 files) is the slowest leg by a wide margin.
#
# Parity suites are excluded: they need the pinned oracle and are covered by the
# `parity` job, where they cannot pass vacuously.
namespace :test do
  desc 'Run one gem\'s suite in parallel (rake test:gem[openstudio-hvac] [JOBS=n])'
  task :gem, [:name] do |_t, args|
    name = args[:name] or abort('usage: rake test:gem[openstudio-hvac]')
    dir = File.expand_path(name)
    abort("no such gem: #{name}") unless Dir.exist?(dir)

    files = Dir.glob('test/test_*.rb', base: dir)
                .reject { |f| f.end_with?('test_helper.rb') || f.end_with?('_parity.rb') }
                .sort
    jobs = ENV.fetch('JOBS', default_jobs.to_s).to_i
    failed = []
    started = Time.now

    # A sliding window, NOT each_slice: a batch barrier makes every slot wait on
    # the slowest file in its batch, which is invisible with 44 slots and one
    # batch but is most of the loss with the 2 slots a hosted runner gets.
    # Start a replacement the moment any job finishes.
    queue = files.dup
    running = {}
    until queue.empty? && running.empty?
      while running.size < jobs && !queue.empty?
        f = queue.shift
        running[Process.spawn(RbConfig.ruby, f, chdir: dir,
                              out: File::NULL, err: [:child, :out])] = f
      end
      pid, status = Process.waitpid2(-1)
      f = running.delete(pid)
      failed << f if f && !status.success?
    end

    elapsed = (Time.now - started).round(1)
    if failed.empty?
      puts "#{name}: #{files.size} files OK in #{elapsed}s (#{jobs}-way)"
    else
      # Re-run the failures serially so their output is readable rather than
      # interleaved with eleven other suites.
      puts "#{name}: #{failed.size} of #{files.size} FAILED in #{elapsed}s — re-running for output"
      failed.each { |f| system(RbConfig.ruby, f, chdir: dir) }
      abort("failed: #{failed.join(', ')}")
    end
  end

  desc 'Run every gem suite in parallel ([JOBS=n])'
  task :all do
    GEM_DIRS.each { |d| Rake::Task['test:gem'].execute(Rake::TaskArguments.new([:name], [d])) }
  end
end

# --- The HVAC catalog ------------------------------------------------------
namespace :hvac do
  desc 'Build EVERY catalog system and put each through an EnergyPlus sizing run ([JOBS=n])'
  task :simulate_systems do
    jobs = ENV.fetch('JOBS', default_jobs.to_s)
    ok = system(RbConfig.ruby, 'openstudio-hvac/scripts/simulate_all_systems.rb', '--jobs', jobs)
    abort('one or more systems do not produce a simulate-able model') unless ok
  end
end

# --- Windows packaging ------------------------------------------------------
# Stages the payload tree the Inno Setup script packages. Pure file copying, so
# it runs anywhere — but it CANNOT supply the bundled OpenStudio: the SDK in a
# Linux dev container is the Linux build, and the installer needs the Windows
# one. That has to be fetched and unpacked separately (see OPENSTUDIO_WINDOWS).
namespace :windows do
  # Absolute from the start: the copy loop joins this with the repo root, and an
  # absolute STAGE_DIR joined onto a root yields a mangled in-repo path.
  STAGE = File.expand_path(ENV.fetch('STAGE_DIR', 'packaging/windows/stage'))

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

        dest = File.join(STAGE, 'gems', dir, rel)
        FileUtils.mkdir_p(File.dirname(dest))
        FileUtils.cp(src, dest)
        total += 1
      end
    end
    FileUtils.chmod(0o755, "#{STAGE}/gems/openstudio-necb/exe/necb-compliance.rb")

    # Sample + weather, taken from the shared fixtures.
    fixtures = 'openstudio-hvac/test/fixtures'
    FileUtils.mkdir_p(["#{STAGE}/samples", "#{STAGE}/weather", "#{STAGE}/bin"])
    # The sample set: one building, many HVAC systems (see
    # openstudio-necb/scripts/generate_samples.rb). Generated rather than
    # committed — they are derived from the fixture and the catalog.
    system(RbConfig.ruby, 'openstudio-necb/scripts/generate_samples.rb',
           File.join(STAGE, 'samples')) || abort('sample generation failed')
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
  # --- release ---------------------------------------------------------------
  # Publish the built installer as a GitHub release asset.
  #
  # A local release is a CONVENIENCE, not the ideal. A CI-built release is
  # reproducible from its tag by construction; this one is only as trustworthy
  # as the guards below, which exist to prevent the failure that matters —
  # shipping a binary that corresponds to no commit anyone can check out. Move
  # this to a tag-triggered workflow once the audience is external.
  #
  # Credentials come from git's own credential helper, so there is no second
  # secret to manage and nothing to put in the environment.
  desc 'Publish the built installer as a GitHub release (rake windows:release[v0.1.0])'
  task :release, [:tag] do |_t, args|
    tag = args[:tag] or abort('usage: rake windows:release[v0.1.0]')
    exe = Dir.glob('packaging/windows/Output/*.exe').max_by { |f| File.mtime(f) }
    abort('no installer built — run: rake windows:stage && rake windows:installer') if exe.nil?

    # 1. The tree must be clean. A release built from uncommitted work cannot be
    #    reproduced by anyone, including you, a week later.
    dirty = `git status --porcelain`.strip
    abort("working tree is dirty — commit or stash first:\n#{dirty}") unless dirty.empty?

    # 2. The commit must exist on the remote, or the tag points at nothing others can fetch.
    sha = `git rev-parse HEAD`.strip
    abort('HEAD is not on the remote — push first') unless system("git branch -r --contains #{sha} > /dev/null 2>&1")

    # 3. The installer must be NEWER than every source it claims to contain.
    #    This is the guard that catches the common mistake: editing a gem, then
    #    publishing yesterday's build.
    newest = Dir.glob('openstudio-*/lib/**/*.{rb,json,csv}').max_by { |f| File.mtime(f) }
    if newest && File.mtime(newest) > File.mtime(exe)
      abort("#{File.basename(exe)} is OLDER than #{newest} — rebuild before releasing")
    end

    token = `printf 'protocol=https\nhost=github.com\n\n' | git credential fill 2>/dev/null`
            .lines.find { |l| l.start_with?('password=') }&.split('=', 2)&.last&.strip
    abort('no GitHub token from the git credential helper') if token.nil? || token.empty?

    size_mb = (File.size(exe) / 1_048_576.0).round
    notes = <<~NOTES
      Built from `#{sha[0, 12]}` on #{`git log -1 --format=%cs`.strip}.

      **#{File.basename(exe)}** — #{size_mb} MB. Installs per-user, needs no
      administrator rights, and carries its own OpenStudio 3.11.0 and
      EnergyPlus 25.2.0, so nothing else has to be installed.

      Run `necb-compliance --help` from the Start-menu console, or double-click
      `samples\\run-demo.cmd`. See README-windows.txt in the install directory.

      NOT YET VALIDATED ON WINDOWS — the CLI has been exercised on Linux and the
      installer verified to install, but the packaged tool has not been run on a
      real Windows machine.
    NOTES

    puts "publishing #{tag} -> #{File.basename(exe)} (#{size_mb} MB) from #{sha[0, 12]}"
    ok = system({ 'GH_TOKEN' => token }, 'gh', 'release', 'create', tag, exe,
                '--title', "NECB Compliance #{tag}", '--notes', notes, '--target', sha)
    abort('gh release create failed') unless ok
    puts "published: https://github.com/canmet-energy/openstudio-necb-gems/releases/tag/#{tag}"
  end
end
