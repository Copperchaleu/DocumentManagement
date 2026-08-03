@echo off
setlocal EnableExtensions
cd /d "%~dp0web"

echo ============================================
echo   Build Vue frontend -^> frontend\dist
echo ============================================

where npm >nul 2>nul
if errorlevel 1 (
  echo [ERROR] npm not found. Install Node.js first.
  pause
  exit /b 1
)

if not exist "node_modules" (
  echo [1/2] npm install...
  call npm install
  if errorlevel 1 (
    echo [ERROR] npm install failed
    pause
    exit /b 1
  )
) else (
  echo [1/2] node_modules ready
)

echo [2/2] npm run build...
call npm run build
if errorlevel 1 (
  echo [ERROR] build failed
  pause
  exit /b 1
)

echo.
echo Build OK: frontend\dist
echo Then run start.bat to use the app.
endlocal
