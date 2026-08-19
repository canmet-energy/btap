@echo off
rem NECB compliance CLI launcher.
rem
rem OpenStudio ships INSIDE this install, so there is nothing to detect: no
rem registry probe, no PATH search, no version gate. That also means we cannot
rem collide with any OpenStudio the user already has, and we always run the
rem exact 3.11.0 build the gems are pinned against.
rem
rem openstudio.exe carries its own Ruby 3.2.2 and its own EnergyPlus, so no
rem Ruby and no E+ need to be installed either.
setlocal
chcp 65001 >nul 2>&1

set "NECB_HOME=%~dp0.."

rem The escape hatch, for developers pointing at another build.
if not defined OPENSTUDIO_CLI set "OPENSTUDIO_CLI=%NECB_HOME%\openstudio\bin\openstudio.exe"

if not exist "%OPENSTUDIO_CLI%" (
  echo ERROR: openstudio.exe not found at "%OPENSTUDIO_CLI%".
  echo The installation looks incomplete - reinstall, or set OPENSTUDIO_CLI
  echo to the full path of an OpenStudio 3.11 openstudio.exe.
  exit /b 4
)

rem Flags forward through execute_ruby_script unchanged - verified. Do NOT add
rem a "--" separator: it arrives literally in ARGV and optparse would then treat
rem every following flag as a positional argument.
"%OPENSTUDIO_CLI%" execute_ruby_script "%NECB_HOME%\gems\openstudio-necb\exe\necb-compliance.rb" %*
exit /b %ERRORLEVEL%
