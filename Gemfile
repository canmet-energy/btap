
source 'http://rubygems.org'
ruby '2.2.4'

gem 'rake', '~> 12.3.0'

# uncomment if you need to update the bcl measures
gem "bcl", "~> 0.5"
# gem "bcl", :path => "../bcl-gem"
# gem 'bcl', github: 'NREL/bcl-gem', branch: 'develop'

gem 'colored', '~> 1.2'


# gem 'openstudio_measure_tester', path: "../OpenStudio-measure-tester-gem"
gem 'openstudio_measure_tester', github: "NREL/OpenStudio-measure-tester-gem"

if RUBY_PLATFORM =~ /win32/
  gem 'win32console', '~> 1.3.2', platform: [:mswin, :mingw]
else
  # requires native extensions
  gem 'ruby-prof', '~> 0.15.1', platform: :ruby
end
gem "openstudio-standards", :git => 'https://github.com/NREL/openstudio-standards.git', :branch => 'nrcan'

#These gems are present only in nrcan's standards and nrcan's OS server aws image.
gem 'roo'
gem 'aes'
gem 'rest-client','2.0.2'
gem 'pry'
