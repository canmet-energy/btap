require_relative 'lib/openstudio_envelope/version'

Gem::Specification.new do |spec|
  spec.name          = 'openstudio-envelope'
  spec.version       = OpenStudioEnvelope::VERSION
  spec.authors       = ['NRCan / openstudio-standards contributors']

  spec.summary       = 'NECB building-envelope prescriptive rules and reference-envelope transforms for OpenStudio models.'
  spec.description   = 'Applies NECB envelope requirements to OpenStudio models from vendored, ' \
                       'article-tagged rule data: effective U-values by HDD climate zone ' \
                       '(Tables 3.2.2.x/3.2.3.1), FDWR and skylight-area limits (3.2.1.4), and ' \
                       'the performance-path reference-envelope transform (8.4.4.3/8.4.4.4). ' \
                       'SDK-only model manipulation; never executes simulations. Thermal ' \
                       'bridging (3.1.1.7 effective transmittance) integrates the tbd gem when ' \
                       'available and degrades loudly, never silently, without it.'
  spec.homepage      = 'https://github.com/canmet-energy/openstudio-necb-gems'
  spec.metadata      = {
    # These gems are not published: the repository is private and the costing
    # data is licence-encumbered. Publishing is a deliberate act — clear this
    # entry consciously, do not let a stray `gem push` make the decision.
    'allowed_push_host' => 'none',
    'source_code_uri' => 'https://github.com/canmet-energy/openstudio-necb-gems',
    'homepage_uri' => 'https://github.com/canmet-energy/openstudio-necb-gems'
  }
  spec.license       = 'LGPL-3.0-or-later'
  spec.required_ruby_version = '>= 3.2.0'

  spec.files         = Dir['lib/**/*', 'README.md', 'LICENSE*']
  spec.require_paths = ['lib']

  # The OpenStudio SDK ruby bindings are the primary runtime dependency. They are
  # typically provided by an OpenStudio installation rather than rubygems, so they are
  # not declared as a gem dependency here; `require 'openstudio'` must succeed.
  #
  # tbd (rd2/tbd, pure Ruby) powers the NECB 3.1.1.7 effective-transmittance
  # (thermal bridging) calculations. It is lazily required: everything except
  # thermal-bridging derating works without it, and its absence produces explicit
  # audit warnings rather than silent clear-field results.
  # btap-audit: the shared AuditLog + article-coverage emitter.
  # openstudio-hvac: costing/database.rb reads the family's single public
  # vendored copy of the PRICED tables (costs.csv, costs_local_factors.csv)
  # from this gem. Undeclared until the gems were extracted, because a
  # side-by-side checkout resolved it by relative path.
  spec.add_dependency 'btap-audit'
  spec.add_dependency 'openstudio-hvac'
  spec.add_dependency 'tbd'

  spec.add_development_dependency 'minitest', '~> 5.0'
  spec.add_development_dependency 'rake', '~> 13.0'
end
