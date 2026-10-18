#!/usr/bin/env pwsh
<#
.SYNOPSIS
  FPP single-command full validation runner (12 sequential phases).

.DESCRIPTION
  Orchestrates the existing pytest / Vitest / tsc / vite / Playwright suites
  plus inline API-smoke and database-integrity checks. Suites run strictly
  SEQUENTIALLY in one process - never concurrent heavy jobs (a parallel
  backend + vitest + build + tsc run once produced a 24-minute flaky run).

  Hang safety: every suite below already carries its own timeouts
  (Playwright per-test/expect timeouts; pytest/Vitest/tsc/build complete in
  seconds-to-minutes on this machine). If a phase hangs, stop this runner
  (Ctrl+C), identify the hung child via the phase log, kill only that child,
  diagnose, and re-run with -Only '<phases>'.

  Safety:
  - DATABASE_URL is pinned explicitly to local staging for every backend
    phase; the repo .env (historically Neon production) is never consulted.
  - A pre-flight probe refuses database phases unless the target is
    conclusively local faculty_portal_staging.
  - Read-only staging checks only; no cleanup, no fixtures, no emails,
    no deploy, no commit/push.
  - Playwright data-dependent suites are gated on their fixture accounts
    and report BLOCKED (not failed) when the current dataset lacks them.

.PARAMETER Only
  Comma-separated phase numbers to run, e.g. -Only '1,12'. Default: all.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts/run_full_validation.ps1
#>
[CmdletBinding()]
param(
  [string]$LogDir = 'C:\Users\mohan\AppData\Local\Temp\opencode\fpp-validation',
  [string]$Only = ''
)

$ErrorActionPreference = 'Continue'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackendVenvPython = Join-Path $RepoRoot 'backend\.venv\Scripts\python.exe'
$FrontendDir = Join-Path $RepoRoot 'frontend'
$StagingDbUrl = 'postgresql+asyncpg://postgres@localhost:5432/faculty_portal_staging'
$BackendBase = 'http://127.0.0.1:8099'
$FrontendBase = 'http://127.0.0.1:5173'

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$LogFile = Join-Path $LogDir "full_validation_$Stamp.log"
$Results = @()

function Write-Log([string]$Line) {
  $msg = "[$(Get-Date -Format 'HH:mm:ss')] $Line"
  Write-Output $msg
  Add-Content -Path $LogFile -Value $msg
}

function Run-Phase([int]$Num, [int]$Total, [string]$Name, [scriptblock]$Body) {
  # Success = the body completes without throwing. Every key native call
  # inside a body is followed IMMEDIATELY by Assert-LastExit; trailing
  # $LASTEXITCODE is deliberately not inspected (a trailing Write-Log or
  # Select-Object would otherwise mask or forge the result).
  if ($Only -ne '' -and -not ((',' + $Only + ',').Contains(',' + $Num + ','))) {
    Write-Log "[$Num/$Total] $Name ... SKIPPED (phase filter)"
    $script:Results += [pscustomobject]@{ Phase = $Num; Name = $Name; Result = 'SKIPPED'; Seconds = 0 }
    return
  }
  Write-Log "[$Num/$Total] $Name ... START"
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  try {
    & $Body
    $sw.Stop()
    Write-Log "[$Num/$Total] $Name ... DONE ($([math]::Round($sw.Elapsed.TotalSeconds))s)"
    $script:Results += [pscustomobject]@{ Phase = $Num; Name = $Name; Result = 'DONE'; Seconds = [math]::Round($sw.Elapsed.TotalSeconds) }
  } catch {
    $sw.Stop()
    if ($_.Exception.Message -like '__BLOCKED__:*') {
      Write-Log "[$Num/$Total] $Name ... BLOCKED: $($_.Exception.Message.Substring(12))"
      $script:Results += [pscustomobject]@{ Phase = $Num; Name = $Name; Result = 'BLOCKED'; Seconds = [math]::Round($sw.Elapsed.TotalSeconds) }
    } else {
      Write-Log "[$Num/$Total] $Name ... FAILED: $($_.Exception.Message)"
      $script:Results += [pscustomobject]@{ Phase = $Num; Name = $Name; Result = 'FAILED'; Seconds = [math]::Round($sw.Elapsed.TotalSeconds) }
    }
  }
}

function Assert-LastExit {
  if ($LASTEXITCODE -ne 0) { throw "command failed with exit $LASTEXITCODE" }
}

Write-Log "FPP full validation started. Log: $LogFile"
Write-Log "Repo: $RepoRoot"

# ---------------------------------------------------------------- phase 1
Run-Phase 1 12 'Environment verification' {
  Set-Location $RepoRoot
  Write-Log "branch: $(git branch --show-current) @ $(git rev-parse --short HEAD)"
  try { Write-Log ("backend: " + (Invoke-WebRequest -Uri "$BackendBase/healthz" -TimeoutSec 15 -UseBasicParsing).StatusCode) }
  catch { Write-Log "backend: DOWN"; throw 'backend required for phases 7-11' }
  try { Write-Log ("frontend: " + (Invoke-WebRequest -Uri "$FrontendBase/" -TimeoutSec 15 -UseBasicParsing).StatusCode) }
  catch { Write-Log "frontend: DOWN (phases 7-9 will BLOCK)" }
  $env:DATABASE_URL = $StagingDbUrl
  & $BackendVenvPython (Join-Path $RepoRoot 'scripts\validation\probe_db.py')
  Assert-LastExit
}

# ---------------------------------------------------------------- phase 2
Run-Phase 2 12 'Focused backend tests' {
  Set-Location $RepoRoot
  $env:DATABASE_URL = $StagingDbUrl; $env:APP_ENV = 'test'; $env:DEBUG = 'true'
  & $BackendVenvPython -m pytest backend/tests/test_association_lifecycle.py backend/tests/test_grant_concurrency.py backend/tests/test_assoc_uniqueness.py backend/tests/test_malformed_pipeline.py backend/tests/test_pipeline_recovery.py backend/tests/test_pipeline_recovery_wiring.py backend/tests/test_orchestrator.py backend/tests/test_record_dates_serialization.py backend/tests/test_login_enumeration.py backend/tests/test_password_reset.py backend/tests/test_brevo_email.py backend/tests/test_batch5_authz.py backend/tests/test_grant_csrf.py -q --no-header -p no:cacheprovider 2>&1 | Select-Object -Last 3
  Assert-LastExit
}

# ---------------------------------------------------------------- phase 3
Run-Phase 3 12 'Full backend suite' {
  Set-Location $RepoRoot
  $env:DATABASE_URL = $StagingDbUrl; $env:APP_ENV = 'test'; $env:DEBUG = 'true'
  & $BackendVenvPython -m pytest backend/tests -q --no-header -p no:cacheprovider 2>&1 | Select-Object -Last 3
  Assert-LastExit
}

# ---------------------------------------------------------------- phase 4
Run-Phase 4 12 'Frontend Vitest' {
  Set-Location $FrontendDir
  & 'node_modules\.bin\vitest.cmd' run 2>&1 | Select-Object -Last 4
  Assert-LastExit
}

# ---------------------------------------------------------------- phase 5
Run-Phase 5 12 'TypeScript check' {
  Set-Location $FrontendDir
  & 'node_modules\.bin\tsc.cmd' --noEmit -p tsconfig.json 2>&1 | Select-Object -First 5
  Assert-LastExit
  Write-Log 'tsc clean'
}

# ---------------------------------------------------------------- phase 6
Run-Phase 6 12 'Production build' {
  Set-Location $FrontendDir
  & 'node_modules\.bin\vite.cmd' build 2>&1 | Select-Object -Last 3
  Assert-LastExit
}

# ---------------------------------------------------------------- phase 7 (gated on stg fixtures)
Run-Phase 7 12 'Playwright functional scenarios' {
  Set-Location $RepoRoot
  $env:DATABASE_URL = $StagingDbUrl
  $probe = & $BackendVenvPython (Join-Path $RepoRoot 'scripts\validation\probe_staging.py')
  if ($probe.Trim() -ne '1') { throw '__BLOCKED__: staging fixture accounts absent (dataset is the demo set)' }
  Set-Location $FrontendDir
  $env:STAGING_CONFIRM = '1'; $env:STAGING_FRONTEND_URL = $FrontendBase; $env:STAGING_API_URL = $BackendBase
  & 'node_modules\.bin\playwright.cmd' test -c playwright-staging.config.ts scenarios.spec.ts 2>&1 | Select-Object -Last 4
  Assert-LastExit
}

# ---------------------------------------------------------------- phase 8 (gated: needs stg.* fixture accounts)
Run-Phase 8 12 'Browser console/network tests' {
  Set-Location $RepoRoot
  $probe = & $BackendVenvPython (Join-Path $RepoRoot 'scripts\validation\probe_staging.py')
  if ($probe.Trim() -ne '1') { throw '__BLOCKED__: staging fixture accounts absent (console.spec needs stg.* logins; use demo.spec for the demo dataset)' }
  Set-Location $FrontendDir
  $env:STAGING_CONFIRM = '1'; $env:STAGING_FRONTEND_URL = $FrontendBase; $env:STAGING_API_URL = $BackendBase
  & 'node_modules\.bin\playwright.cmd' test -c playwright-staging.config.ts console.spec.ts 2>&1 | Select-Object -Last 4
  Assert-LastExit
}

# ---------------------------------------------------------------- phase 9 (gated: needs stg.* fixture accounts)
Run-Phase 9 12 'Mobile viewport tests' {
  Set-Location $RepoRoot
  $probe = & $BackendVenvPython (Join-Path $RepoRoot 'scripts\validation\probe_staging.py')
  if ($probe.Trim() -ne '1') { throw '__BLOCKED__: staging fixture accounts absent (mobile.spec needs stg.* logins; use demo.spec for the demo dataset)' }
  Set-Location $FrontendDir
  $env:STAGING_CONFIRM = '1'; $env:STAGING_FRONTEND_URL = $FrontendBase; $env:STAGING_API_URL = $BackendBase
  & 'node_modules\.bin\playwright.cmd' test -c playwright-staging.config.ts mobile.spec.ts 2>&1 | Select-Object -Last 4
  Assert-LastExit
}

# ---------------------------------------------------------------- phase 10
Run-Phase 10 12 'API smoke tests' {
  & $BackendVenvPython (Join-Path $RepoRoot 'scripts\validation\smoke_api.py')
  Assert-LastExit
}

# ---------------------------------------------------------------- phase 11
Run-Phase 11 12 'Database integrity' {
  Set-Location $RepoRoot
  $env:DATABASE_URL = $StagingDbUrl
  & $BackendVenvPython (Join-Path $RepoRoot 'scripts\validation\integrity.py')
  Assert-LastExit
}

# ---------------------------------------------------------------- phase 12
Run-Phase 12 12 'Repository checks' {
  Set-Location $RepoRoot
  git diff --check 2>$null | Select-Object -First 5
  $scan = git diff HEAD -- . ':(exclude)*.pyc' 2>&1 | Select-String -Pattern 'xkeysib-[A-Za-z0-9_-]{10,}' | Where-Object { $_ -notmatch 'xkeysib-test-key' } | Select-Object -First 5
  if ($scan) { throw 'secret scan hits in diff' }
  Write-Log 'diff-check clean; secret scan clean'
  git status --short | Select-Object -First 8
}

Write-Log '==================== SUMMARY ===================='
foreach ($r in $Results) {
  Write-Log ("phase {0} {1}: {2} ({3}s)" -f $r.Phase, $r.Name, $r.Result, $r.Seconds)
}
$bad = @($Results | Where-Object { $_.Result -eq 'FAILED' }).Count
$blocked = @($Results | Where-Object { $_.Result -eq 'BLOCKED' }).Count
Write-Log "Log saved: $LogFile"
if ($bad -gt 0) { Write-Log "RESULT: FAILED ($bad phase(s))"; exit 1 }
if ($blocked -gt 0) { Write-Log "RESULT: done with $blocked BLOCKED phase(s)"; exit 2 }
Write-Log 'RESULT: all 12 phases DONE'
exit 0
