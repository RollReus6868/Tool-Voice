@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"
set "LOG=%~dp0build_log.txt"
echo ==== %date% %time% ==== > "%LOG%"
echo.
echo  ============================================
echo    TTS Clone Studio - DONG GOI FILE .EXE
echo  ============================================
echo.
if not exist ".venv\Scripts\python.exe" (
  echo [0/3] Chua cai dat - dang chay install.bat...
  call "%~dp0install.bat" --quiet
  if errorlevel 1 exit /b 1
)
echo [1/3] Cai PyInstaller...
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

echo [2/3] Dong goi (mat 1-3 phut)...
set "TTS_BUILD_MODE=onefile"
if exist "dist\TTSCloneStudio.exe" del /f /q "dist\TTSCloneStudio.exe" >nul 2>&1
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean TTSCloneStudio.spec >> "%LOG%" 2>&1
if errorlevel 1 goto :fail

echo [3/3] Kiem tra ket qua...
if not exist "dist\TTSCloneStudio.exe" (
  echo  Khong thay dist\TTSCloneStudio.exe - co the phan mem diet virus da xoa file vua tao.
  echo  Hay them thu muc nay vao danh sach loai tru cua Windows Security roi chay lai.
  goto :fail
)
echo.
echo  XONG!  File: %~dp0dist\TTSCloneStudio.exe
echo  Co the chep file .exe nay sang may khac (Windows 10/11 64-bit) de dung, khong can cai Python.
echo  Lan dau mo, Windows SmartScreen co the bao "Unknown publisher":
echo  bam "More info" ^> "Run anyway" - day la binh thuong voi phan mem tu dong goi.
echo.
explorer "%~dp0dist"
pause
exit /b 0

:fail
echo.
echo  DONG GOI LOI. 25 dong cuoi cua build_log.txt:
echo  ------------------------------------------------------------
powershell -NoProfile -Command "Get-Content -Tail 25 -LiteralPath '%LOG%'"
echo  ------------------------------------------------------------
echo  Ban van dung duoc ung dung binh thuong bang run.bat.
echo  Hay gui file build_log.txt cho nguoi ho tro.
pause
exit /b 1
