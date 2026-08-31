# Rakefile for the NECB gem family.
#
# Deliberately does NOT `require 'bundler/gem_tasks'` — that binds a Rakefile to
# a single gemspec, and this repo holds five. Build individual gems from their
# own directory (`cd btap-necb && gem build btap-necb.gemspec`).
#
# Every task below assumes it is run from the repository root, with the five gem
# directories as direct children.

require 'rbconfig'
require 'etc'

# EXPLICIT, not a glob. A glob fails OPEN when directories rename (the btap-*
# migration): test:all, windows:stage and the release staleness guard would all
# go green while doing nothing. Editing this list is part of every gem move;
# forgetting aborts every rake invocation instead of silently no-oping.
GEM_DIRS = %w[
  btap-audit
  btap-costing
  btap-modeling
  btap-necb
  btap-simulation
].freeze
missing = GEM_DIRS.reject { |d| File.directory?(d) }
abort("GEM_DIRS is stale — missing: #{missing.join(', ')}") unless missing.empty?

# EXPLICIT: the fold renames these files with domain prefixes, so a
# name-pattern derivation would silently lose them.
HOSTILE_TESTS = %w[
  btap-necb/test/test_envelope_necb_hostile_reference.rb
  btap-necb/test/test_lighting_necb_hostile_reference.rb
].select { |f| File.file?(f) }.freeze
abort('HOSTILE_TESTS list is stale') unless HOSTILE_TESTS.size == 2

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
    # Most gems keep VERSION in lib/<name>/version.rb; btap-audit declares
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
    abort('legacy:whatsnew failed') unless system(RbConfig.ruby, 'btap-necb/scripts/legacy_whatsnew.rb')
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
# btap-necb/docs/necb_rule_verification.md for what each check proves.
namespace :necb do
  desc 'Lint: every rule key in a NECB ruleset JSON is read by that gem lib/'
  task :orphan_keys do
    # Pure Ruby, no OpenStudio SDK — safe on any CI node.
    abort('necb:orphan_keys failed') unless system(RbConfig.ruby, 'btap-necb/scripts/necb_orphan_keys.rb')
  end

  desc 'Hostile-outcome tests: reference transforms must overwrite non-compliant proposed values'
  task :hostile do
    # These need the SDK (require "openstudio") but NOT the openstudio CLI —
    # reference generation runs no EnergyPlus.
    abort('no hostile-outcome tests found — HOSTILE_TESTS went stale') if HOSTILE_TESTS.empty?
    failed = HOSTILE_TESTS.reject do |test|
      # chdir into the gem so the test's require_relative + fixture paths
      # resolve; pass the path RELATIVE to that new working directory.
      system(RbConfig.ruby, test.split('/', 2).last, chdir: test.split('/', 2).first)
    end
    abort("necb:hostile failed in: #{failed.join(', ')}") unless failed.empty?
  end

  desc 'Regenerate NECB_8_4_COVERAGE.html (+ NECB_GEM_COVERAGE.md) from manifests, citations and the cached 8.4 text'
  task :coverage_doc do
    # Pure Ruby, no SDK. Text cache refresh (btap-necb/scripts/fetch_necb_8_4_text.rb)
    # needs codes-MCP access and is NOT run here — CI regenerates from the
    # committed cache. Pass run evidence via NECB_AUDIT_JSONS=dir1:dir2
    # (directories containing audit.json + report.json from real runs).
    abort('necb:coverage_doc failed') unless system(RbConfig.ruby, 'btap-necb/scripts/generate_necb_gem_coverage.rb') &&
                                             system(RbConfig.ruby, 'btap-necb/scripts/generate_necb_8_4_coverage.rb')
  end

  desc 'Verify as-applied part-load curves against NECB 2025 Subsection 8.4.6 coefficients'
  task :curves do
    # SDK only, no CLI (components are hard-sized). Compares MODEL curves under
    # the documented transforms (FHeatPLC = PLR/eff, degF->degC surfaces).
    abort('necb:curves failed') unless system(RbConfig.ruby, 'btap-necb/scripts/necb_8_4_6_curve_probe.rb')
  end

  desc 'All NECB rule-verification checks (runs every check, then reports)'
  task :verify do
    # Deliberately NOT `task verify: %i[orphan_keys hostile]` — prerequisite
    # chaining aborts at the first failure, which hides the rest of the work
    # list. This is a "what still needs doing" report, so run everything.
    results = {
      'orphan_keys' => system(RbConfig.ruby, 'btap-necb/scripts/necb_orphan_keys.rb'),
      'curves_8_4_6' => system(RbConfig.ruby, 'btap-necb/scripts/necb_8_4_6_curve_probe.rb'),
      # .map(&:...).all? — NOT .all? { }, which short-circuits on the first
      # failing gem and hides the remaining work.
      'hostile' => !HOSTILE_TESTS.empty? && HOSTILE_TESTS.map do |test|
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
# gems; within a gem it runs them one at a time, which is why btap-necb
# (57 files) is the slowest leg by a wide margin.
#
# Parity suites are excluded: they need the pinned oracle and are covered by the
# `parity` job, where they cannot pass vacuously.
namespace :test do
  desc 'Run one gem\'s suite in parallel (rake test:gem[btap-necb] [JOBS=n])'
  task :gem, [:name] do |_t, args|
    name = args[:name] or abort('usage: rake test:gem[btap-necb]')
    dir = File.expand_path(name)
    abort("no such gem: #{name}") unless Dir.exist?(dir)

    # Tests that MUTATE shared on-disk state cannot share the pool:
    # test_cli.rb hides the priced costing CSVs mid-test (restored in ensure),
    # and any pooled neighbour reading them in that window dies with
    # "costs.csv not found". Before the btap-necb fold this could never
    # collide — the reader and the mutator lived in different gems' legs,
    # which test:all runs sequentially. They run AFTER the pool, serially.
    serial = { 'btap-necb' => %w[test/test_cli.rb] }.fetch(name, [])
    files = Dir.glob('test/test_*.rb', base: dir)
                .reject { |f| f.end_with?('test_helper.rb') || f.end_with?('_parity.rb') }
                .reject { |f| serial.include?(f) }
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
    logs = {}
    require 'tempfile'
    until queue.empty? && running.empty?
      while running.size < jobs && !queue.empty?
        f = queue.shift
        # Capture each file's output rather than nulling it: a failure that
        # only reproduces UNDER the pool (load-dependent) would otherwise be
        # invisible — the old rerun-for-output ran serially and could pass,
        # reporting a failure with green output.
        log = Tempfile.create(['testlog-', '.txt'])
        logs[f] = log
        running[Process.spawn(RbConfig.ruby, f, chdir: dir,
                              out: log.fileno, err: [:child, :out])] = f
      end
      pid, status = Process.waitpid2(-1)
      f = running.delete(pid)
      failed << f if f && !status.success?
    end

    serial.each do |f|
      next if File.exist?(File.join(dir, f)) == false

      log = Tempfile.create(['testlog-', '.txt'])
      logs[f] = log
      ok = system(RbConfig.ruby, f, chdir: dir, out: log.fileno, err: [:child, :out])
      failed << f unless ok
    end

    elapsed = (Time.now - started).round(1)
    if failed.empty?
      puts "#{name}: #{files.size + serial.size} files OK in #{elapsed}s (#{jobs}-way + #{serial.size} serial)"
    else
      puts "#{name}: #{failed.size} of #{files.size} FAILED in #{elapsed}s — captured output:"
      failed.each do |f|
        log = logs[f]
        log.rewind
        puts "--- #{f} " + '-' * 40
        puts log.read
      end
      abort("failed: #{failed.join(', ')}")
    end
    logs.each_value { |l| l.close rescue nil }
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
    ok = system(RbConfig.ruby, 'btap-modeling/scripts/simulate_all_systems.rb', '--jobs', jobs)
    abort('one or more systems do not produce a simulate-able model') unless ok
  end
end

# --- Windows packaging ------------------------------------------------------
# Stages the payload tree the Inno Setup script packages. Pure file copying, so
# it runs anywhere — but it CANNOT supply the bundled OpenStudio: the SDK in a
# Linux dev container is the Linux build, and the installer needs the Windows
# one. That has to be fetched and unpacked separately (see OPENSTUDIO_WINDOWS).
namespace :windows do
  # DORMANT since R5 (D-83). These tasks build the RUBY installer — OpenStudio
  # plus the five gem trees — which the Python installer succeeds:
  # `python3 packaging/windows/stage_python.py` stages embedded CPython and a
  # pre-installed site-packages tree instead, and release.yml drives it.
  #
  # They abort rather than being deleted because the Ruby side stays frozen
  # verification infrastructure until R6. The guard is here, not merely in a
  # comment, so a v-tag can never accidentally ship the superseded artifact:
  # both paths write the same stage/ directory and the same Output/*.exe name,
  # so "whichever ran last wins" was a real way to publish the wrong thing.
  def self.dormant!(task)
    return if ENV['BTAP_RUBY_INSTALLER'] == '1'

    abort <<~MSG
      rake windows:#{task} is DORMANT since R5 (D-83).

      The installer is now Python, staged by:
        python3 packaging/windows/stage_python.py --version <v>
      and built by .github/workflows/release.yml.

      For archaeology only: BTAP_RUBY_INSTALLER=1 rake windows:#{task}
      (deleted at R6).
    MSG
  end

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
    dormant!('stage')
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
    FileUtils.chmod(0o755, "#{STAGE}/gems/btap-necb/exe/btap-compliance.rb")

    # Sample + weather, taken from the shared fixtures.
    fixtures = 'btap-modeling/test/fixtures'
    FileUtils.mkdir_p(["#{STAGE}/samples", "#{STAGE}/weather", "#{STAGE}/bin"])
    # The sample set: one building, many HVAC systems (see
    # btap-necb/scripts/generate_samples.rb). Generated rather than
    # committed — they are derived from the fixture and the catalog.
    system(RbConfig.ruby, 'btap-necb/scripts/generate_samples.rb',
           File.join(STAGE, 'samples')) || abort('sample generation failed')
    # The seed lives in the gem's lib data (spec.files ships it); the old
    # test/fixtures copy is gone — staging from it broke silently (D-80 R1).
    FileUtils.cp('btap-modeling/lib/btap_modeling/hvac/data/5ZoneNoHVAC.osm', "#{STAGE}/samples/")
    Dir.glob("#{fixtures}/weather/CAN_ON_Toronto*.{epw,ddy,stat}").each { |f| FileUtils.cp(f, "#{STAGE}/weather/") }

    %w[btap-compliance.cmd].each { |f| FileUtils.cp("packaging/windows/#{f}", "#{STAGE}/bin/") }
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
    dormant!('installer')
    iss = 'packaging/windows/btap-compliance.iss'
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
  # This task is BOTH paths: pushing a v* tag runs it in CI
  # (.github/workflows/release.yml, which also has a workflow_dispatch
  # rehearsal that stops at DRY_RUN), and it still runs locally as a
  # convenience. The guards below exist to prevent the failure that matters —
  # shipping a binary that corresponds to no commit anyone can check out.
  #
  # Credentials come from git's own credential helper, so there is no second
  # secret to manage and nothing to put in the environment.
  desc 'Publish the built installer as a GitHub release (rake windows:release[v0.1.0] [DRY_RUN=1])'
  task :release, [:tag] do |_t, args|
    dormant!('release')
    tag = args[:tag] or abort('usage: rake windows:release[v0.1.0]')
    # DRY_RUN runs every guard and prints exactly what WOULD be published,
    # without creating a tag, a release or an upload. It exists because the
    # first exercise of this task published a live 168 MB release by accident:
    # the guards were being tested one at a time, and the last one legitimately
    # passed. A release is outward-facing and effectively public within the org
    # the moment it exists, so it needs a way to be rehearsed.
    dry_run = !ENV['DRY_RUN'].to_s.empty?

    # The .iss AppVersion is stamped into the exe name and the install tree.
    # Publishing v0.2.0 with a 0.1.0-named installer is a mislabel no later
    # guard catches, so refuse the mismatch here (suffixes like -rc1 are fine).
    iss_version = File.read('packaging/windows/btap-compliance.iss')[/#define AppVersion\s+"([^"]+)"/, 1]
    unless tag == "v#{iss_version}" || tag.start_with?("v#{iss_version}-")
      abort("tag #{tag} does not match AppVersion #{iss_version} in btap-compliance.iss — bump the .iss first")
    end

    exe = Dir.glob('packaging/windows/Output/*.exe').max_by { |f| File.mtime(f) }
    abort('no installer built — run: rake windows:stage && rake windows:installer') if exe.nil?

    # 1. The tree must be clean. A release built from uncommitted work cannot be
    #    reproduced by anyone, including you, a week later.
    dirty = `git status --porcelain`.strip
    abort("working tree is dirty — commit or stash first:\n#{dirty}") unless dirty.empty?

    # 2. The commit must exist on the remote, or the tag points at nothing others can fetch.
    sha = `git rev-parse HEAD`.strip
    # `git branch -r --contains` exits 0 whether or not it finds anything, so the
    # OUTPUT is the answer, not the status. Checking the status silently passed
    # an unpushed commit straight through to the publish step.
    # In a CI run the commit is on the remote by construction (it arrived by
    # push), and the shallow single-ref checkout means `branch -r --contains`
    # sees nothing either way — the guard could only ever false-abort there.
    unless ENV['GITHUB_ACTIONS']
      on_remote = `git branch -r --contains #{sha} 2>/dev/null`.strip
      abort("HEAD (#{sha[0, 12]}) is not on any remote branch — push first") if on_remote.empty?
    end

    # 3. The installer must be NEWER than every source it claims to contain.
    #    This is the guard that catches the common mistake: editing a gem, then
    #    publishing yesterday's build.
    sources = GEM_DIRS.flat_map { |d| Dir.glob("#{d}/lib/**/*.{rb,json,csv}") }
    abort('release staleness guard found no sources — GEM_DIRS went stale') if sources.empty?
    newest = sources.max_by { |f| File.mtime(f) }
    if newest && File.mtime(newest) > File.mtime(exe)
      abort("#{File.basename(exe)} is OLDER than #{newest} — rebuild before releasing")
    end

    token = ENV['GH_TOKEN']
    if token.nil? || token.empty?
      token = `printf 'protocol=https\nhost=github.com\n\n' | git credential fill 2>/dev/null`
              .lines.find { |l| l.start_with?('password=') }&.split('=', 2)&.last&.strip
    end
    abort('no GitHub token — set GH_TOKEN or configure the git credential helper') if token.nil? || token.empty?

    size_mb = (File.size(exe) / 1_048_576.0).round
    notes = <<~NOTES
      Built from `#{sha[0, 12]}` on #{`git log -1 --format=%cs`.strip}.

      **#{File.basename(exe)}** — #{size_mb} MB. Installs per-user, needs no
      administrator rights, and carries its own OpenStudio 3.11.0 and
      EnergyPlus 25.2.0, so nothing else has to be installed.

      Run `btap-compliance --help` from the Start-menu console, or double-click
      `samples\\run-demo.cmd`. See README-windows.txt in the install directory.

      Validated on Windows Server 2022 (2026-08-24, clean EC2 instance): silent
      per-user install into a path with spaces, `--list-cities`, a full annual
      determination (exit 1), the quick-run refusal (exit 6), usage errors
      (exit 2), UTF-8 report glyphs intact, immunity to a different OpenStudio
      on PATH, and clean uninstall preserving user output. Not yet field-tested
      on desktop Windows 10/11 — reports welcome.
    NOTES

    if dry_run
      puts '--- DRY RUN: nothing will be created or uploaded ---'
      puts "  tag      #{tag}  ->  #{sha[0, 12]}"
      puts "  asset    #{exe} (#{size_mb} MB)"
      puts "  title    BTAP Compliance #{tag}"
      existing = `git ls-remote --tags origin refs/tags/#{tag} 2>/dev/null`.strip
      puts "  WARNING  tag #{tag} ALREADY EXISTS on the remote" unless existing.empty?
      puts '  notes:'
      notes.each_line { |line| puts "    #{line.rstrip}" }
      puts '--- all guards passed; re-run without DRY_RUN to publish ---'
      next
    end

    puts "publishing #{tag} -> #{File.basename(exe)} (#{size_mb} MB) from #{sha[0, 12]}"
    ok = system({ 'GH_TOKEN' => token }, 'gh', 'release', 'create', tag, exe,
                '--title', "BTAP Compliance #{tag}", '--notes', notes, '--target', sha)
    abort('gh release create failed') unless ok
    puts "published: https://github.com/canmet-energy/btap-gems/releases/tag/#{tag}"
  end
end
