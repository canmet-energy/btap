#!/usr/bin/env ruby
# frozen_string_literal: true

# What has moved in the legacy fork since our pinned oracle?
#
# The gems' only tie to openstudio-standards is `legacy_pin/REF`, ONE commit SHA.
# It is not a branch: bundler fetches the fork by SHA. So "are we behind?" is not
# a question git can answer from inside this repository — nothing here points at
# the fork's history. This script answers it.
#
# It reports the commits between the pin and a fork branch (default `nrcan`),
# and maps each changed path to the gem that should care, so a reviewer or an
# LLM can judge what is worth absorbing before running the bump workflow in
# legacy_pin/README.md.
#
#   rake legacy:whatsnew                     # against nrcan
#   BRANCH=develop rake legacy:whatsnew      # against another branch
#   LEGACY_FORK=/path/to/openstudio-standards rake legacy:whatsnew
#
# Resolution order for the fork, mirroring legacy_pin/Gemfile's own convention:
#   LEGACY_FORK -> LEGACY_PIN_REMOTE (when it is a local path) -> a cached
#   blobless mirror of the GitHub remote under tmp/.
#
# READ-ONLY. It never changes REF, never bundles, never merges.

require 'fileutils'
require 'shellwords'

ROOT = File.expand_path('../..', __dir__)
PIN_DIR = File.join(ROOT, 'legacy_pin')
REF = File.read(File.join(PIN_DIR, 'REF')).strip
BRANCH = ENV['BRANCH'] || 'nrcan'
DEFAULT_REMOTE = 'https://github.com/NatLabRockies/openstudio-standards.git'
CACHE = File.join(ROOT, 'tmp', 'legacy_fork.git')

# Which gem owns a legacy path. Heuristic and deliberately coarse — it points a
# reviewer at the right gem, it does not decide anything. First match wins, so
# the costing sheets are claimed before the per-domain patterns.
# LOCATION rules come first: a file under test/ is a legacy test artifact even
# when its NAME contains 'shw-scale' or 'chiller-type'. Letting the keyword
# patterns match first filed regression fixtures under the domain gems, which
# reads as "this gem has work to do" when it does not.
OWNERS = [
  [%r{^test/},                                                     'legacy TESTS — oracle behaviour, not our source'],
  [%r{^data/},                                                     'legacy DATA — check whether a gem vendored a copy'],
  [%r{/btap/costing/|/btap/common/.*\.csv$}, 'costing (hvac + envelope + lighting + shw)'],
  [%r{/btap/geometry\.rb|create_shape|create_bar},                'btap-modeling'],
  [%r{space_types\.json|schedules\.json|beps_compliance_path\.rb}, 'btap-necb (loads)'],
  [%r{lighting|daylight},                                          'btap-necb (lighting)'],
  [%r{service_water_heating|shw},                                  'btap-necb (shw)'],
  [%r{hvac_system|autozone|efficienc|curves|chiller|boiler|/fan},  'btap-necb (hvac) or btap-modeling'],
  [%r{building_envelope|thermal_transmittance|fdwr|thermal_bridging}, 'btap-necb (envelope)'],
  [%r{necb_20\d\d\.rb},                                            'btap-necb (+ the domain each hunk touches)']
].freeze

def die(msg)
  warn msg
  exit 1
end

def git(dir, *args)
  out = IO.popen([{ 'GIT_TERMINAL_PROMPT' => '0' }, 'git', '-C', dir, *args], &:read)
  [$?.success?, out]
end

# A local checkout beats any network path: it is instant and works offline.
def local_fork
  %w[LEGACY_FORK LEGACY_PIN_REMOTE].each do |var|
    path = ENV[var]
    next if path.nil? || path.empty? || path.start_with?('http', 'git@')
    next unless Dir.exist?(File.join(path, '.git')) || Dir.exist?(File.join(path, 'objects'))

    return File.expand_path(path)
  end
  nil
end

# Blobless mirror: commits and trees only, so --name-status works without
# dragging the fork's blob history across the wire. GitHub honours the filter;
# a plain file:// or dumb server does NOT (git prints "filtering not recognized
# by server, ignoring" and clones everything, ~4.5 GB for this fork). Prefer a
# local checkout via LEGACY_FORK when you have one — it needs no copy at all.
def cached_mirror
  remote = ENV['LEGACY_FORK'] || DEFAULT_REMOTE
  unless Dir.exist?(CACHE)
    FileUtils.mkdir_p(File.dirname(CACHE))
    warn "fetching a blobless mirror of #{remote} into #{CACHE} (first run only)..."
    ok = system('git', 'clone', '--bare', '--filter=blob:none', remote, CACHE)
    die("could not clone #{remote} — pass LEGACY_FORK=/path/to/a/local/checkout instead") unless ok
  end
  system('git', '-C', CACHE, 'fetch', '--quiet', 'origin', "+refs/heads/#{BRANCH}:refs/heads/#{BRANCH}")
  CACHE
end

fork_dir = local_fork
source = fork_dir ? "local checkout #{fork_dir}" : 'cached mirror of the GitHub remote'
fork_dir ||= cached_mirror

ok, = git(fork_dir, 'cat-file', '-e', "#{REF}^{commit}")
die("the pinned revision #{REF[0, 12]} is not in #{fork_dir} — wrong repository?") unless ok

# Prefer the REMOTE-TRACKING ref. In a working checkout the local branch is
# routinely stale (it is only as fresh as the last `git checkout` + pull), and
# "what has moved upstream" is a question about the remote. Fall back to the
# local branch when there is no remote ref — e.g. in the bare mirror.
resolve = ->(cand) { git(fork_dir, 'rev-parse', '--verify', '--quiet', "#{cand}^{commit}") }
remote_ok, remote_sha = resolve.call("origin/#{BRANCH}")
local_ok,  local_sha  = resolve.call("refs/heads/#{BRANCH}")
tip = remote_ok ? "origin/#{BRANCH}" : (local_ok ? "refs/heads/#{BRANCH}" : nil)
die("branch '#{BRANCH}' not found in #{fork_dir} (try BRANCH=develop)") unless tip

if remote_ok && local_ok && remote_sha.strip != local_sha.strip
  warn "note: #{fork_dir} has a local '#{BRANCH}' at #{local_sha.strip[0, 9]} that differs from " \
       "origin/#{BRANCH} at #{remote_sha.strip[0, 9]} — reporting against the remote " \
       '(run `git fetch` in the fork for the freshest answer)'
end

_, pin_line = git(fork_dir, 'log', '-1', '--format=%h %ad %s', '--date=short', REF)
_, tip_line = git(fork_dir, 'log', '-1', '--format=%h %ad %s', '--date=short', tip)
_, behind = git(fork_dir, 'rev-list', '--count', "#{REF}..#{tip}")
_, ahead  = git(fork_dir, 'rev-list', '--count', "#{tip}..#{REF}")

puts '=' * 78
puts "legacy oracle: pinned at #{pin_line.strip}"
puts "fork branch:   #{BRANCH} at #{tip_line.strip}"
puts "source:        #{source}"
puts '=' * 78

if behind.to_i.zero?
  puts "\nThe pin is CURRENT with #{BRANCH}." \
       "#{ahead.to_i.positive? ? " (#{ahead.strip} commit(s) on the pin are not on #{BRANCH})" : ''}"
  exit 0
end

puts "\n#{behind.strip} commit(s) on #{BRANCH} since the pin:\n\n"
_, log = git(fork_dir, 'log', '--format=  %h  %ad  %s', '--date=short', '--reverse', "#{REF}..#{tip}")
puts log

_, names = git(fork_dir, 'diff', '--name-status', REF, tip)
changed = names.lines.map { |l| l.chomp.split("\t", 2) }.reject { |p| p.size < 2 }

grouped = Hash.new { |h, k| h[k] = [] }
changed.each do |status, path|
  owner = OWNERS.find { |re, _| path =~ re }&.last || 'UNMAPPED — review by hand'
  grouped[owner] << "#{status}  #{path}"
end

puts "\n#{changed.size} path(s) changed, by the gem that should care:\n"
# Legacy tests and data last: they are context, not work.
order = ->(k) { k.start_with?('legacy ') ? 1 : (k.start_with?('UNMAPPED') ? 2 : 0) }
grouped.sort_by { |k, v| [order.call(k), -v.size] }.each do |owner, paths|
  puts "\n  #{owner}  (#{paths.size})"
  paths.first(12).each { |p| puts "      #{p}" }
  puts "      ... #{paths.size - 12} more" if paths.size > 12
end

puts <<~NEXT

  #{'-' * 78}
  Absorbing any of this means BUMPING THE PIN, not copying code:
    1. edit legacy_pin/REF to the new fork revision
    2. BUNDLE_GEMFILE=legacy_pin/Gemfile bundle install
    3. run every parity gate with LEGACY_PIN_REQUIRED=1, plus the archetype
       regeneration gates
    4. a flipped assertion means the upstream change reached a COMPARED
       behaviour — attribute each one before accepting it (the D-68 discipline)
  See legacy_pin/README.md.
NEXT
