source 'http://rubygems.org'
gem 'rake', '~> 11.2.2'

# uncomment if you need to update the bcl measures
gem "bcl", "~> 0.5"
# gem "bcl", :path => "../bcl-gem"
# gem 'bcl', github: 'NREL/bcl-gem', branch: 'develop'

# Specify the JSON dependency so that rubocop and other gem do not try to install it
gem 'json', '~> 1.8.6'
gem 'rest-client', '~> 2.0.2'
gem 'aes', '~> 0.5.0'
gem 'geocoder', '~> 1.4.4'
if RUBY_PLATFORM =~ /win32/
  gem 'win32console', '~> 1.3.2', platform: [:mswin, :mingw]
else
  # requires native extensions
  gem 'ruby-prof', '~> 0.15.1', platform: :ruby
end
group :test do
  gem 'minitest', '~> 5.4.0'
  gem 'rubocop', '~> 0.26.0'
  gem 'rubocop-checkstyle_formatter', '~> 0.1.1'
  gem 'ci_reporter_minitest', '~> 1.0.0'
end
gem 'docker-api', require: 'docker'

# openstudio-standards
gem "openstudio-standards", :git => 'https://github.com/NREL/openstudio-standards.git', :branch => 'nrcan'
gem 'colored', '~> 1.2'
gem 'git', require: false
gem 'openstudio-aws', '0.5.0.rc8'
gem 'openstudio-analysis', '1.0.0.rc19'
gem 'nokogiri', '1.6.8.1'
