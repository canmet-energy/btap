#!/usr/bin/env ruby
# frozen_string_literal: true

# Entry point for the NECB compliance CLI.
#
# The .rb extension is REQUIRED, not stylistic: the Windows launcher runs this
# through `openstudio execute_ruby_script`, which loads the file with `require`
# — and require will not load an extensionless path. A POSIX-style
# `exe/necb-compliance` fails there with a bare LoadError.
#
# The encoding line is LOAD-BEARING and must precede every require. Without a
# UTF-8 default external encoding, Ruby tags the bytes it reads with whatever
# the platform says — Windows-1252 on Windows — and the 22 JSON.parse(File.read)
# sites across the nine gems then read their UTF-8 data files as CP1252. That
# does NOT raise: JSON.parse succeeds and 'm²' silently becomes 'mÂ²', which
# flows into the report. Silent corruption, not a crash. (The same defect class
# the CI workflow pins with LANG/LC_ALL=C.UTF-8.)
Encoding.default_external = Encoding::UTF_8
Encoding.default_internal = nil

require_relative '../lib/openstudio_necb'
require_relative '../lib/openstudio_necb/cli'

code = OpenStudioNECB::CLI.run(ARGV)

# exit!, not exit. `execute_ruby_script` loads this file with `require`, so a
# SystemExit raised by `exit` unwinds through its rescue and gets reported as a
# crash with a backtrace — on a perfectly normal exit 6. exit! sets the status
# without raising, but it also skips at_exit and does NOT flush, so flush first.
$stdout.flush
$stderr.flush
exit!(code)
