@echo off
setlocal

cd /d C:\GIT\clustree

set VENV_DIR=.venv

where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python launcher "py" was not found.
    echo [HINT] Install Python 3.11 or 3.12 from python.org and enable "Add python.exe to PATH".
    pause
    exit /b 1
)

set PYTHON_CMD=

py -3.11 --version >nul 2>nul
if not errorlevel 1 set PYTHON_CMD=py -3.11

if "%PYTHON_CMD%"=="" (
    py -3.12 --version >nul 2>nul
    if not errorlevel 1 set PYTHON_CMD=py -3.12
)

if "%PYTHON_CMD%"=="" (
    py -3 --version >nul 2>nul
    if not errorlevel 1 set PYTHON_CMD=py -3
)

if "%PYTHON_CMD%"=="" (
    echo [ERROR] No usable Python 3 found.
    pause
    exit /b 1
)

if not exist "%VENV_DIR%\Scripts\python.exe" (
    echo [INFO] Creating local virtual environment: %VENV_DIR%
    %PYTHON_CMD% -m venv "%VENV_DIR%"
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
)

set VENV_PYTHON=%VENV_DIR%\Scripts\python.exe

echo [INFO] Python:
"%VENV_PYTHON%" --version

echo [INFO] Checking dependencies...
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -q --upgrade pip setuptools wheel
"%VENV_PYTHON%" -m pip install --disable-pip-version-check -q -r requirements.txt

if errorlevel 1 (
    echo.
    echo [ERROR] Dependency install failed.
    echo [HINT] Delete .venv and retry after fixing requirements.txt:
    echo        rmdir /s /q .venv
    echo        start.bat
    pause
    exit /b 1
)

echo [INFO] Starting Clustree...
"%VENV_PYTHON%" main.py

if errorlevel 1 (
    echo.
    echo [ERROR] Clustree exited with an error.
    pause
    exit /b 1
)

echo.
echo [INFO] Clustree finished.
pause

endlocal