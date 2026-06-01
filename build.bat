@echo off
setlocal

cd /d "%~dp0"

set VENV_DIR=.venv
set VENV_PYTHON=%VENV_DIR%\Scripts\python.exe

if not exist "%VENV_PYTHON%" (
    echo [ERROR] Virtual environment not found: %VENV_PYTHON%
    echo [HINT] Run run.bat once first to create .venv and install base dependencies.
    pause
    exit /b 1
)

echo [INFO] Python:
"%VENV_PYTHON%" --version

echo [INFO] Installing build dependencies...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -q --upgrade pip setuptools wheel
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [ERROR] Dependency install failed.
    pause
    exit /b 1
)

echo [INFO] Stopping running Clustree processes...
taskkill /f /im Clustree.exe >nul 2>nul

echo [INFO] Removing old build outputs...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist Clustree.spec del /q Clustree.spec
if exist dist (
    echo [ERROR] Could not remove old dist folder. Close Clustree.exe and any Explorer windows inside dist, then retry.
    pause
    exit /b 1
)

echo [INFO] Building Clustree onedir bundle...
"%VENV_PYTHON%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --name Clustree ^
    --icon clustree.ico ^
    --collect-all PyQt5 ^
    --collect-all PIL ^
    --collect-all piexif ^
    --add-data "clustree.ico;." ^
    --add-data "clustree.png;." ^
    main.py

if errorlevel 1 (
    echo [ERROR] PyInstaller build failed.
    pause
    exit /b 1
)

echo [INFO] Cleaning runtime state from bundle...
del /q dist\Clustree\clustree_settings.json 2>nul
del /q dist\Clustree\*.db 2>nul
del /q dist\Clustree\*.db-shm 2>nul
del /q dist\Clustree\*.db-wal 2>nul
if exist Clustree.spec del /q Clustree.spec

echo [OK] Built: %CD%\dist\Clustree\Clustree.exe

endlocal
