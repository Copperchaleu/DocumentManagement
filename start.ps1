# Local Document Manager - start
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$venvDir = Join-Path $PSScriptRoot ".venv"
$py = Join-Path $venvDir "Scripts\python.exe"
$port = 8765

Write-Host "============================================"
Write-Host "  Local Document Manager - Starting"
Write-Host "============================================"

if (-not (Test-Path $py)) {
    Write-Host "[1/3] Creating virtual environment..."
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -m venv $venvDir
    } else {
        & python -m venv $venvDir
    }
    if (-not (Test-Path $py)) {
        Write-Host "[ERROR] Failed to create venv. Install Python 3.10+ and add to PATH."
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "[2/3] Installing dependencies..."
    & $py -m pip install --upgrade pip -q
    & $py -m pip install -r (Join-Path $PSScriptRoot "requirements.txt")
} else {
    Write-Host "[1/3] Virtual environment ready."
}

Write-Host "[2/3] Checking port $port..."
$conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
foreach ($c in $conns) {
    Write-Host "      Port in use, killing PID $($c.OwningProcess)"
    Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
}

Write-Host "[3/3] Starting server and opening browser..."
Write-Host "      URL: http://127.0.0.1:$port"
Write-Host "      Close this window to stop the server."
Write-Host "============================================"
& $py -m backend.main
