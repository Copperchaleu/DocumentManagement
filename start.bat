@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "VENV_DIR=%~dp0.venv"
set "PY=%VENV_DIR%\Scripts\python.exe"
set "PORT=8765"

echo ============================================
echo   Local Document Manager - Starting
echo ============================================

if not exist "%PY%" goto NEED_VENV
echo [1/3] Virtual environment ready.
goto AFTER_VENV

:NEED_VENV
echo [1/3] Creating virtual environment...
where py >nul 2>nul
if errorlevel 1 goto USE_PYTHON
py -3 -m venv "%VENV_DIR%"
goto CHECK_VENV

:USE_PYTHON
python -m venv "%VENV_DIR%"

:CHECK_VENV
if exist "%PY%" goto INSTALL_DEPS
echo [ERROR] Failed to create venv. Install Python 3.10+ and add to PATH.
pause
exit /b 1

:INSTALL_DEPS
echo [2/3] Installing dependencies...
"%PY%" -m pip install --upgrade pip -q
"%PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
  echo [ERROR] pip install failed.
  pause
  exit /b 1
)

:AFTER_VENV
echo [2/3] Checking port %PORT%...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%PORT% " ^| findstr LISTENING') do (
  echo       Port in use, killing PID %%a
  taskkill /F /PID %%a >nul 2>nul
)

echo [3/3] Starting server and opening browser...
echo       URL: http://127.0.0.1:%PORT%
echo       Close this window to stop the server.
echo ============================================
"%PY%" -m backend.main
if errorlevel 1 (
  echo.
  echo [ERROR] Server exited with error.
  pause
)
endlocal
