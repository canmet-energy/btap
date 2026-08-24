@echo off
rem One-click demo: the README quick-start, as a command line.
rem
rem --quick shortens the run period to one week so this finishes in minutes
rem rather than in an hour. That is NOT a code-compliant determination and the
rem tool says so loudly - drop --quick for a real 8.4.1.2 verdict.
setlocal
set "HERE=%~dp0"

"%HERE%..\bin\btap-compliance.cmd" "%HERE%5ZoneNoHVAC.osm" ^
  --epw "%HERE%..\weather\CAN_ON_Toronto.Intl.AP.716240_CWEC2020.epw" ^
  --storeys 1 ^
  --space-type "Space Function/Office enclosed > 25 m2" ^
  --shw-fuel NaturalGas ^
  --hvac-system "Baseboard gas boiler" ^
  --quick ^
  --project "Sample Office" ^
  --prepared-by "NECB Compliance demo" ^
  --out "%USERPROFILE%\Documents\necb_demo"

echo.
echo Exit code: %ERRORLEVEL%   (0 compliant, 1 not compliant, 6 no determination)
echo Report: %USERPROFILE%\Documents\necb_demo\compliance_report.html
pause
