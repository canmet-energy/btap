#!/usr/bin/env ruby
# frozen_string_literal: true

# MOVED (D-80 R1): the Leg-C goldens exporter now lives at
# verification/oracle/export_goldens.rb, is gem-free, and requires a prep
# directory built by python/scripts/oracle_prep.py:
#
#   .venv/bin/python python/scripts/oracle_prep.py --out PREP
#   BUNDLE_GEMFILE=legacy_pin/Gemfile bundle exec \
#     ruby verification/oracle/export_goldens.rb --prep PREP --out DIR
#
# This exec-style stub forwards ALL arguments and returns the replacement's
# exit status — but the new exporter cannot run without --prep/--out, so a
# bare historical invocation gets the usage message above, never a generic
# missing-file error.
target = File.expand_path('../../verification/oracle/export_goldens.rb', __dir__)
if ARGV.empty?
  warn File.read(__FILE__).lines.grep(/^#/).join
  abort("this script moved to #{target} and now needs --prep/--out (see above)")
end
exec(RbConfig.ruby, target, *ARGV)
