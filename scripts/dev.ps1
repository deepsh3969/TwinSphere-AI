# TwinSphere AI — development launcher (Windows PowerShell)
#
# Usage:
#   .\scripts\dev.ps1 setup     # one-time: venv + deps + .env + migrate + seed
#   .\scripts\dev.ps1 backend   # start backend (terminal 1)
#   .\scripts\dev.ps1 frontend  # start frontend (terminal 2)
#   .\scripts\dev.ps1 migrate   # run alembic migrations
#   .\scripts\dev.ps1 test      # run backend pytest + frontend typecheck/tests
#   .\scripts\dev.ps1 stop      # stop backend on port 8000
#   .\scripts\dev.ps1 health    # probe /health
#   .\scripts\dev.ps1 status    # show what is running
#
# Requires: Python 3.11+, Node 18+. Does NOT require Docker (SQLite default).

param(
    [Parameter(Position = 0)]
    [ValidateSet('setup', 'backend', 'frontend', 'migrate', 'seed', 'test', 'stop', 'health', 'status', 'help')]
    [string]$Command = 'help'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$VenvPy = Join-Path $Backend '.venv\Scripts\python.exe'
$VenvPip = Join-Path $Backend '.venv\Scripts\pip.exe'

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    OK  $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    WARN $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "    FAIL $msg" -ForegroundColor Red }

function Test-Prereqs {
    $ok = $true
    Write-Step "Checking prerequisites"
    try {
        $py = & python --version 2>&1
        if ($py -match 'Python 3\.1[1-9]') { Write-Ok "Python: $py" }
        else { Write-Err "Python 3.11+ required, found: $py"; $ok = $false }
    } catch { Write-Err "Python not found on PATH"; $ok = $false }
    try {
        $node = & node --version 2>&1
        if ($node -match '^v(1[8-9]|[2-9]\d)') { Write-Ok "Node: $node" }
        else { Write-Err "Node 18+ required, found: $node"; $ok = $false }
    } catch { Write-Err "Node not found on PATH"; $ok = $false }
    return $ok
}

function Ensure-Env {
    $envFile = Join-Path $Root '.env'
    if (-not (Test-Path $envFile)) {
        Write-Step "Creating .env from .env.example (development defaults)"
        Copy-Item (Join-Path $Root '.env.example') $envFile
        # generate a random JWT secret so the dev default warning goes away
        $secret = -join ((1..48) | ForEach-Object { '{0:x}' -f (Get-Random -Max 16) })
        (Get-Content $envFile) -replace '^JWT_SECRET=.*', "JWT_SECRET=$secret" | Set-Content $envFile
        Write-Ok ".env created with random JWT_SECRET"
        Write-Warn "Review .env before production use — never commit it."
    } else {
        Write-Ok ".env already exists"
    }
}

function Ensure-Venv {
    if (-not (Test-Path $VenvPy)) {
        Write-Step "Creating Python virtual environment"
        & python -m venv (Join-Path $Backend '.venv')
        Write-Ok "venv created"
    } else {
        Write-Ok "venv exists"
    }
    Write-Step "Installing backend dependencies"
    & $VenvPip install --quiet -r (Join-Path $Backend 'requirements-dev.txt')
    Write-Ok "backend deps installed"
}

function Ensure-NodeDeps {
    Write-Step "Installing frontend dependencies"
    Push-Location $Frontend
    if (Test-Path 'package-lock.json') { & npm ci --silent } else { & npm install --silent }
    Pop-Location
    Write-Ok "frontend deps installed"
}

function Invoke-Migrate {
    Write-Step "Running alembic migrations"
    Push-Location $Backend
    $env:PYTHONPATH = $Root
    & $VenvPy -m alembic upgrade head
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { throw "alembic upgrade failed (exit $code)" }
    Write-Ok "migrations applied"
}

function Invoke-Seed {
    Write-Step "Seeding demonstration data (idempotent — safe to rerun)"
    Push-Location $Backend
    $env:PYTHONPATH = $Root
    & $VenvPy -m app.services.seed
    Pop-Location
    Write-Ok "seed complete"
}

switch ($Command) {
    'help' {
        Get-Content $PSCommandPath | Select-String '^#' | ForEach-Object { $_.Line.TrimStart('#').Trim() }
    }
    'setup' {
        if (-not (Test-Prereqs)) { exit 1 }
        Ensure-Env
        Ensure-Venv
        Ensure-NodeDeps
        Invoke-Migrate
        Invoke-Seed
        Write-Host ""
        Write-Host "Setup complete. Start services in two terminals:" -ForegroundColor Green
        Write-Host "  Terminal 1:  .\scripts\dev.ps1 backend"
        Write-Host "  Terminal 2:  .\scripts\dev.ps1 frontend"
        Write-Host "  Then open:   http://localhost:5173"
    }
    'backend' {
        if (-not (Test-Path $VenvPy)) { Write-Err "venv missing — run .\scripts\dev.ps1 setup first"; exit 1 }
        Write-Step "Starting backend on http://127.0.0.1:8000 (Ctrl+C to stop)"
        Push-Location $Backend
        $env:PYTHONPATH = $Root
        & $VenvPy -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
        Pop-Location
    }
    'frontend' {
        if (-not (Test-Path (Join-Path $Frontend 'node_modules'))) { Write-Err "node_modules missing — run .\scripts\dev.ps1 setup first"; exit 1 }
        Write-Step "Starting frontend on http://localhost:5173 (Ctrl+C to stop)"
        Push-Location $Frontend
        & npm run dev
        Pop-Location
    }
    'migrate' { Invoke-Migrate }
    'seed'    { Invoke-Seed }
    'test' {
        Write-Step "Backend pytest"
        Push-Location $Backend
        $env:PYTHONPATH = $Root
        & $VenvPy -m pytest tests -q --tb=short
        $be = $LASTEXITCODE
        Pop-Location
        Write-Step "Frontend typecheck + tests"
        Push-Location $Frontend
        & npm run typecheck
        $tc = $LASTEXITCODE
        & npm run test -- --run
        $fe = $LASTEXITCODE
        Pop-Location
        if ($be -eq 0 -and $tc -eq 0 -and $fe -eq 0) { Write-Ok "all tests passed" ; exit 0 }
        else { Write-Err "some tests failed (backend=$be typecheck=$tc frontend=$fe)"; exit 1 }
    }
    'stop' {
        Write-Step "Stopping backend on port 8000"
        $conns = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
        if ($conns) {
            foreach ($c in $conns) { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue }
            Write-Ok "stopped"
        } else { Write-Warn "nothing listening on port 8000" }
    }
    'health' {
        try {
            $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 5
            Write-Ok "backend healthy: $($r.StatusCode) $($r.Content)"
        } catch { Write-Err "backend not reachable: $($_.Exception.Message)"; exit 1 }
    }
    'status' {
        $be = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
        $fe = Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue
        Write-Host "Backend  (8000): $(if ($be) { 'RUNNING' } else { 'stopped' })"
        Write-Host "Frontend (5173): $(if ($fe) { 'RUNNING' } else { 'stopped' })"
    }
}
