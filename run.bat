@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" goto :install
".venv\Scripts\python.exe" -c "import PyQt6.QtWidgets, imageio_ffmpeg" >nul 2>&1
if errorlevel 1 goto :install
goto :start

:install
echo Lan dau chay (hoac thieu thu vien): dang cai dat...
call "%~dp0install.bat" --quiet
if errorlevel 1 exit /b 1

:start
start "" ".venv\Scripts\pythonw.exe" "%~dp0launcher.py"
exit /b 0
