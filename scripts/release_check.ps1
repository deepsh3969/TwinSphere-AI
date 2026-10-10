# TwinSphere AI — release verification script (Windows PowerShell)
#
# Runs every available check and reports PASSED / FAILED / SKIPPED / NOT RUN.
# Exits non-zero if any REQUIRED check fails.  Skipped checks are never
# counted as passed.
#
# Usage:
#   .\scripts\release_check.ps1              # full run
#   .\scripts\release_check.ps1 -SkipSmoke   # skip live-server checks
#   .\scripts\release_check.ps1 -SkipFrontend

param(
    [switch]$SkipSmoke,
    [switch]$SkipFrontend,
    [switch]$SkipLoad
)

$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
$Backend = Join-Path $Root 'backend'
$Frontend = Join-Path $Root 'frontend'
$VenvPy = Join-Path $Backend '.venv\Scripts\python.exe'

$script:Results = @()

function Add-Result($name, $status, $detail = '') {
    $script:Results += [PSCustomObject]@{ Check = $name; Status = $status; Detail = $detail }
    $color = switch ($status) {
        'PASSED'   { 'Green' }
        'FAILED'   { 'Red' }
        'SKIPPED'  { 'Yellow' }
        'NOT RUN'  { 'DarkGray' }
        default    { 'White' }
    }
    Write-Host ("[{0,-7}] {1} {2}" -f $status, $name, $detail) -ForegroundColor $color
}

# ---------------------------------------------------------------- git
Write-Host "`n=== Git ===" -ForegroundColor Cyan
$dirty = git -C $Root status --porcelain
if ($dirty) {
    Add-Result 'git working tree' 'SKIPPED' 'uncommitted changes present'
} else {
    Add-Result 'git working tree' 'PASSED' 'clean'
}
$secretHits = git -C $Root grep -n -I -E '(AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|xox[baprs]-|-----BEGIN.*PRIVATE KEY)' -- ':!*.md' ':!docs/*' 2>$null
if ($secretHits) {
    Add-Result 'secret scan' 'FAILED' $secretHits
} else {
    Add-Result 'secret scan' 'PASSED' 'no obvious secrets in tracked files'
}

# ---------------------------------------------------------------- backend tests
Write-Host "`n=== Backend pytest ===" -ForegroundColor Cyan
if (Test-Path $VenvPy) {
    Push-Location $Backend
    $env:PYTHONPATH = $Root
    & $VenvPy -m pytest tests -q --tb=line 2>&1 | Select-Object -Last 3
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -eq 0) { Add-Result 'backend pytest' 'PASSED' }
    else { Add-Result 'backend pytest' 'FAILED' "exit $code" }
} else {
    Add-Result 'backend pytest' 'NOT RUN' 'venv missing'
}

# ---------------------------------------------------------------- migrations
Write-Host "`n=== Migrations (fresh DB) ===" -ForegroundColor Cyan
if (Test-Path $VenvPy) {
    $tmpDb = Join-Path $env:TEMP "twinsphere_release_check.db"
    if (Test-Path $tmpDb) { Remove-Item $tmpDb -Force }
    Push-Location $Backend
    $env:PYTHONPATH = $Root
    $env:DATABASE_URL = "sqlite:///$tmpDb"
    & $VenvPy -m alembic upgrade head 2>&1 | Select-Object -Last 1
    $code = $LASTEXITCODE
    Pop-Location
    Remove-Item Env:\DATABASE_URL -ErrorAction SilentlyContinue
    if ($code -eq 0) { Add-Result 'alembic fresh upgrade' 'PASSED' }
    else { Add-Result 'alembic fresh upgrade' 'FAILED' "exit $code" }
} else {
    Add-Result 'alembic fresh upgrade' 'NOT RUN' 'venv missing'
}

# ---------------------------------------------------------------- config validation
Write-Host "`n=== Config validation ===" -ForegroundColor Cyan
if (Test-Path $VenvPy) {
    Push-Location $Backend
    $env:PYTHONPATH = $Root
    $env:APP_ENV = 'production'
    $env:JWT_SECRET = 'dev-only-change-me-in-production'
    & $VenvPy -c "from app.core.config import validate_security_config; validate_security_config()" 2>&1 | Select-Object -Last 1
    $prodReject = ($LASTEXITCODE -ne 0)
    Pop-Location
    Remove-Item Env:\APP_ENV -ErrorAction SilentlyContinue
    Remove-Item Env:\JWT_SECRET -ErrorAction SilentlyContinue
    if ($prodReject) { Add-Result 'production secret validation' 'PASSED' 'dev secret refused' }
    else { Add-Result 'production secret validation' 'FAILED' 'dev secret was accepted' }
} else {
    Add-Result 'production secret validation' 'NOT RUN' 'venv missing'
}

# ---------------------------------------------------------------- frontend
if (-not $SkipFrontend) {
    Write-Host "`n=== Frontend ===" -ForegroundColor Cyan
    if (Test-Path (Join-Path $Frontend 'node_modules')) {
        Push-Location $Frontend
        & npm run typecheck 2>&1 | Select-Object -Last 1
        $tc = $LASTEXITCODE
        & npm run test -- --run 2>&1 | Select-Object -Last 3
        $fe = $LASTEXITCODE
        & npm run build 2>&1 | Select-Object -Last 1
        $bd = $LASTEXITCODE
        Pop-Location
        if ($tc -eq 0) { Add-Result 'frontend typecheck' 'PASSED' }
        else { Add-Result 'frontend typecheck' 'FAILED' "exit $tc" }
        if ($fe -eq 0) { Add-Result 'frontend unit tests' 'PASSED' }
        else { Add-Result 'frontend unit tests' 'FAILED' "exit $fe" }
        if ($bd -eq 0) { Add-Result 'frontend production build' 'PASSED' }
        else { Add-Result 'frontend production build' 'FAILED' "exit $bd" }
    } else {
        Add-Result 'frontend typecheck' 'NOT RUN' 'node_modules missing'
        Add-Result 'frontend unit tests' 'NOT RUN' 'node_modules missing'
        Add-Result 'frontend production build' 'NOT RUN' 'node_modules missing'
    }
} else {
    Add-Result 'frontend typecheck' 'SKIPPED' '-SkipFrontend'
    Add-Result 'frontend unit tests' 'SKIPPED' '-SkipFrontend'
    Add-Result 'frontend production build' 'SKIPPED' '-SkipFrontend'
}

# ---------------------------------------------------------------- live server checks
if (-not $SkipSmoke) {
    Write-Host "`n=== Live server (smoke + ws) ===" -ForegroundColor Cyan
    $health = $null
    try { $health = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 3 } catch {}
    if ($health -and $health.StatusCode -eq 200) {
        Push-Location $Backend
        $env:PYTHONPATH = $Root
        & $VenvPy tests\smoke_api.py 2>&1 | Select-Object -Last 2
        $sm = $LASTEXITCODE
        & $VenvPy tests\ws_check.py 2>&1 | Select-Object -Last 1
        $ws = $LASTEXITCODE
        Pop-Location
        if ($sm -eq 0) { Add-Result 'API smoke' 'PASSED' }
        else { Add-Result 'API smoke' 'FAILED' "exit $sm" }
        if ($ws -eq 0) { Add-Result 'WebSocket checks' 'PASSED' }
        else { Add-Result 'WebSocket checks' 'FAILED' "exit $ws" }
    } else {
        Add-Result 'API smoke' 'NOT RUN' 'server not reachable on :8000'
        Add-Result 'WebSocket checks' 'NOT RUN' 'server not reachable on :8000'
    }
} else {
    Add-Result 'API smoke' 'SKIPPED' '-SkipSmoke'
    Add-Result 'WebSocket checks' 'SKIPPED' '-SkipSmoke'
}

# ---------------------------------------------------------------- load test
if (-not $SkipLoad) {
    Write-Host "`n=== Load test ===" -ForegroundColor Cyan
    $health = $null
    try { $health = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/health' -UseBasicParsing -TimeoutSec 3 } catch {}
    if ($health -and $health.StatusCode -eq 200) {
        Push-Location $Backend
        $env:PYTHONPATH = $Root
        & $VenvPy tests\load_test.py --iterations 20 --concurrency 1,4 2>&1 | Select-Object -Last 5
        $ld = $LASTEXITCODE
        Pop-Location
        if ($ld -eq 0) { Add-Result 'load test' 'PASSED' }
        else { Add-Result 'load test' 'FAILED' "exit $ld" }
    } else {
        Add-Result 'load test' 'NOT RUN' 'server not reachable on :8000'
    }
} else {
    Add-Result 'load test' 'SKIPPED' '-SkipLoad'
}

# ---------------------------------------------------------------- summary
Write-Host "`n=== Release verification summary ===" -ForegroundColor Cyan
$script:Results | Format-Table -AutoSize
$passed  = @($script:Results | Where-Object Status -eq 'PASSED').Count
$failed  = @($script:Results | Where-Object Status -eq 'FAILED').Count
$skipped = @($script:Results | Where-Object Status -eq 'SKIPPED').Count
$notRun  = @($script:Results | Where-Object Status -eq 'NOT RUN').Count
Write-Host "PASSED: $passed  FAILED: $failed  SKIPPED: $skipped  NOT RUN: $notRun"
if ($failed -gt 0) { exit 1 } else { exit 0 }
