@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
set "LOG=%~dp0install_log.txt"
echo ==== %date% %time% ==== > "%LOG%"
echo.
echo  ============================================
echo    TTS Clone Studio - CAI DAT
echo  ============================================
echo.
echo [1/5] Tim Python...
call "%~dp0find_python.bat"
if not defined PYEXE goto :nopython
echo       Dung: %PYEXE%
%PYEXE% --version >> "%LOG%" 2>&1

echo [2/5] Tao moi truong rieng (.venv)...
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys" >nul 2>&1
  if errorlevel 1 (
    echo       .venv cu bi hong - dang tao lai...
    rmdir /s /q ".venv"
  )
)
if not exist ".venv\Scripts\python.exe" (
  %PYEXE% -m venv .venv >> "%LOG%" 2>&1
  if errorlevel 1 goto :fail
)

echo [3/5] Cai thu vien (lan dau mat 1-3 phut, can Internet)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >> "%LOG%" 2>&1
".venv\Scripts\python.exe" -m pip install -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

echo [4/5] Kiem tra...
".venv\Scripts\python.exe" -c "import PyQt6.QtWidgets, requests, openpyxl, keyring, imageio_ffmpeg; print('ffmpeg:', imageio_ffmpeg.get_ffmpeg_exe())" >> "%LOG%" 2>&1
if errorlevel 1 goto :fail
".venv\Scripts\python.exe" self_test.py >> "%LOG%" 2>&1
if errorlevel 1 (
  echo       Canh bao: tu kiem tra co loi nho, xem install_log.txt. Ung dung van co the chay.
) else (
  echo       Tu kiem tra: OK
)

echo [5/5] Tao loi tat ngoai Desktop...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'TTS Clone Studio.lnk')); $s.TargetPath='%~dp0run.bat'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0assets\app.ico'; $s.WindowStyle=7; $s.Save()" >> "%LOG%" 2>&1

echo.
echo  CAI DAT XONG!  Mo ung dung bang run.bat hoac bieu tuong "TTS Clone Studio" ngoai Desktop.
echo.
if /i not "%~1"=="--quiet" pause
exit /b 0

:nopython
echo.
echo  KHONG TIM THAY PYTHON (3.10 - 3.14).
echo  Cach 1: Tai Python 3.12 tai https://www.python.org/downloads/
echo          Khi cai, NHO TICK o "Add python.exe to PATH".
echo  Cach 2: Neu da cai ma van loi: Settings ^> Apps ^> Advanced app settings ^>
echo          App execution aliases ^> TAT 2 muc python.exe va python3.exe
echo.
echo Python not found >> "%LOG%"
pause
exit /b 1

:fail
echo.
echo  CAI DAT LOI. 25 dong cuoi cua install_log.txt:
echo  ------------------------------------------------------------
powershell -NoProfile -Command "Get-Content -Tail 25 -LiteralPath '%LOG%'"
echo  ------------------------------------------------------------
echo  Hay gui file install_log.txt (cung thu muc) cho nguoi ho tro.
pause
exit /b 1
