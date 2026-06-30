@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: ========= SETTINGS =========
set APPNAME=GeradorApp
set ICON=icon.ico
set OUTDIR=dist
set MODE=onedir   :: use "onefile" only if you know it works for you

:: ========= SAFETY GUARDS =========
if /I "%OUTDIR%"=="." (
  echo ❌ OUTDIR cannot be ".". Change OUTDIR to a subfolder like "dist".
  exit /b 1
)
if "%OUTDIR%"=="" (
  echo ❌ OUTDIR is empty.
  exit /b 1
)

echo Cleaning...
if exist build rd /s /q build
if exist "%OUTDIR%" rd /s /q "%OUTDIR%"
if exist "%APPNAME%" rd /s /q "%APPNAME%"
if exist main.spec del /f /q main.spec

echo Activating venv...
call .venv\Scripts\activate || (echo ❌ venv not found at .venv\Scripts\activate & exit /b 1)

echo Ensuring toolchain...
:: Remove legacy pin that conflicts with flet version
pip uninstall -y flet-desktop >nul 2>&1

python -m pip install -U "flet==0.28.3" pyinstaller pyinstaller-hooks-contrib || (
  echo ❌ Failed to install build deps.
  exit /b 1
)

:: Verify PyInstaller importable in this venv
python -c "import PyInstaller, sys; print('PyInstaller', PyInstaller.__version__)" || (
  echo ❌ PyInstaller not importable in this environment.
  exit /b 1
)

echo Packing (%MODE% -> %OUTDIR%)...

:: First try the flet CLI
where flet >nul 2>&1
if %errorlevel%==0 (
  flet pack main.py ^
    --name "%APPNAME%" ^
    --icon "%ICON%" ^
    --%MODE% ^
    --distpath "%OUTDIR%" ^
    --product-name "%APPNAME%" ^
    --file-version "2.1.0" ^
    --product-version "2.1.0" ^
    --hidden-import httpx --hidden-import httpcore --hidden-import h11 --hidden-import anyio --hidden-import sniffio ^
    --add-data ".env;."
) else (
  echo flet CLI not on PATH, trying module entrypoint...
  python -m flet.cli pack main.py ^
    --name "%APPNAME%" ^
    --icon "%ICON%" ^
    --%MODE% ^
    --distpath "%OUTDIR%" ^
    --product-name "%APPNAME%" ^
    --file-version "2.1.0" ^
    --product-version "2.1.0" ^
    --hidden-import httpx --hidden-import httpcore --hidden-import h11 --hidden-import anyio --hidden-import sniffio ^
    --add-data ".env;."
)

if errorlevel 1 (
  echo ❌ Build failed. See log above.
  exit /b 1
)

echo.
echo ✅ Build done. Run:
echo     .\%OUTDIR%\%APPNAME%\%APPNAME%.exe
exit /b 0
