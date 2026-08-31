@echo off
rem NECB compliance CLI launcher.
rem
rem Python, OpenStudio and EnergyPlus all ship INSIDE this install, so there is
rem nothing to detect: no registry probe, no PATH search, no version gate, and
rem no way to collide with anything the user already has.
rem
rem The runtime is CPython's embeddable distribution. It is a real python.exe,
rem which matters — the report renderer spawns sys.executable.
setlocal
chcp 65001 >nul 2>&1

set "BTAP_HOME=%~dp0.."

rem The escape hatch, for developers pointing at another interpreter.
if not defined BTAP_PYTHON set "BTAP_PYTHON=%BTAP_HOME%\python\python.exe"

if not exist "%BTAP_PYTHON%" (
  echo ERROR: python.exe not found at "%BTAP_PYTHON%".
  echo The installation looks incomplete - reinstall, or set BTAP_PYTHON to
  echo the full path of a CPython 3.12 python.exe with canmet-btap installed.
  exit /b 4
)

rem `-m`, not a console script: pip --target writes POSIX script shims that do
rem not work under the embeddable runtime, so they are removed at stage time.
rem Flags forward unchanged; do NOT add a "--" separator.
"%BTAP_PYTHON%" -m btap.necb.cli %*
exit /b %ERRORLEVEL%
