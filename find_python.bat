@echo off
rem Finds a working Python 3.10 - 3.14 and stores the command in PYEXE.
rem Windows ships fake "python.exe" Store stubs, so every candidate is RUN and
rem must prove itself by executing real Python code (a stub exits with 9009).
rem No findstr/regex parsing: exit codes only.
set "PYEXE="
for %%C in ("py -3.12" "py -3.11" "py -3.13" "py -3.14" "py -3.10" "py -3" "python" "python3") do (
  if not defined PYEXE call :try %%~C
)
if defined PYEXE exit /b 0
exit /b 1

:try
rem "call" so .bat/.cmd shims (pyenv-win) return here instead of ending this script
call %* -c "import sys; sys.exit(0 if (3, 10) <= sys.version_info[:2] <= (3, 14) else 3)" >nul 2>&1
if errorlevel 1 goto :eof
set "PYEXE=%*"
goto :eof
