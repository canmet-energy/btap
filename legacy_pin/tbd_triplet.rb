#!/usr/bin/env ruby
# frozen_string_literal: true

# Print the tbd/osut/topolys triplet EXACTLY as the pinned oracle resolves it.
#
# Why this exists: the parity gates run our gem code and the legacy oracle in
# ONE bundler process (BUNDLE_GEMFILE=legacy_pin/Gemfile), so both sides see the
# triplet this lock pins. Every other suite runs under plain `ruby`, where
# rubygems activates the NEWEST installed version instead. Leave that to chance
# and the two disagree — osut 0.9.1 changes generated insulation conductivities
# (SmallOffice A/B: OSut:K material drift, see legacy_pin/Gemfile), so a parity
# comparison would be measuring a library upgrade rather than our code.
#
# openstudio-standards itself does NOT solve this: on phylroy_dnd its gemspec
# declares `tbd ~> 3` and never mentions osut or topolys, and it commits no
# lockfile. Copying that constraint reproduces the drift. legacy_pin/Gemfile.lock
# is the only place the triplet is nailed down, so it is the single source of
# truth — bump it there (alongside REF) and setup.sh + CI follow automatically.
#
#   ruby legacy_pin/tbd_triplet.rb   # -> topolys:0.6.2 osut:0.8.2 tbd:3.5.2
#
# ONE output format, because it is both human-readable and valid `gem install`
# arguments:  gem install $(ruby legacy_pin/tbd_triplet.rb)
# The `name:version` colon form is required — `gem install a -v 1 b -v 2` is an
# ERROR ("Can't use --version with multiple gems"), and swallowing that error
# leaves whatever was already installed in place while the command looks fine.
#
# DEPENDENCY ORDER (topolys, osut, then tbd) is deliberate: tbd's own
# `osut ~> 0` is maximally loose, so resolving tbd first would pull the newest
# osut and defeat the pin.
LOCK = File.expand_path('Gemfile.lock', __dir__)
ORDER = %w[topolys osut tbd].freeze

deps = File.read(LOCK)[/^DEPENDENCIES$.*/m].to_s
       .scan(/^\s+(tbd|osut|topolys) \(= ([\d.]+)\)$/).to_h

missing = ORDER - deps.keys
abort("tbd_triplet: #{LOCK} pins no exact version for: #{missing.join(', ')}") unless missing.empty?

puts ORDER.map { |g| "#{g}:#{deps.fetch(g)}" }.join(' ')
