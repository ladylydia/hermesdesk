# python/build_bundle.ps1
#
# Produces a self-contained Python bundle suitable for shipping inside
# the Tauri installer.
#
# Output: python/dist/runtime/
#   ├── python/                   <- standalone CPython 3.11 (python.exe etc.)
#   ├── site-packages/            <- pruned Hermes + its deps
#   ├── hermes/                   <- the upstream submodule, prune-copied in
#   ├── overlays/                 <- HermesDesk runtime overlays
#   ├── desktop_entrypoint.py     <- Tauri spawns this
#   ├── weixin_qr_worker.py       <- optional Route C Weixin QR child
#   └── BUNDLE_INFO.json          <- versions + hashes for the updater
#
# Usage:
#   .\python\build_bundle.ps1                # build
#   .\python\build_bundle.ps1 -Verify        # build + smoke-test
#   .\python\build_bundle.ps1 -Clean         # wipe and rebuild
#   .\python\build_bundle.ps1 -SkipWebBuild  # faster: reuse existing hermes_cli/web_dist (risk: stale UI)

[CmdletBinding()]
param(
    [string]$PythonVersion = "3.11.15",
    [string]$PbsRelease    = "20260414",   # python-build-standalone tag (latest as of 2026-04-19)
    [switch]$Clean,
    [switch]$Verify,
    [switch]$SkipWebBuild
)

$ErrorActionPreference = "Stop"
$Root      = Resolve-Path (Join-Path $PSScriptRoot "..")
$BuildDir  = Join-Path $PSScriptRoot "_build"
$Download  = Join-Path $PSScriptRoot "_download"
$Dist      = Join-Path $PSScriptRoot "dist\runtime"
$HermesDir = Join-Path $Root "hermes_vendor"

if ($Clean) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $BuildDir, $Dist
}

New-Item -ItemType Directory -Force -Path $BuildDir, $Download, $Dist | Out-Null

if (-not (Test-Path (Join-Path $HermesDir "pyproject.toml"))) {
    Write-Error "hermes_vendor/ directory not found. The frozen upstream source is missing."
    exit 2
}

# ------------------------------------------------------------------ 1. CPython
$asset = "cpython-$PythonVersion+$PbsRelease-x86_64-pc-windows-msvc-install_only.tar.gz"
$pbsUrl = "https://github.com/astral-sh/python-build-standalone/releases/download/$PbsRelease/$asset"
$tarball = Join-Path $Download $asset

if (-not (Test-Path $tarball)) {
    Write-Host "Downloading $pbsUrl"
    Invoke-WebRequest -Uri $pbsUrl -OutFile $tarball -UseBasicParsing
}

$pyDir = Join-Path $Dist "python"
if (-not (Test-Path (Join-Path $pyDir "python.exe"))) {
    Write-Host "Extracting CPython"
    tar -xzf $tarball -C $Dist
    if (Test-Path (Join-Path $Dist "python\python.exe")) {
        # Already named "python\python.exe" by the tarball
    } else {
        Rename-Item (Join-Path $Dist "python") $pyDir -ErrorAction SilentlyContinue
    }
}

$Py = Join-Path $pyDir "python.exe"
if (-not (Test-Path $Py)) {
    Write-Error "python.exe not found in $pyDir after extraction"
    exit 3
}

Write-Host "Using Python: " (& $Py --version)

# ------------------------------------------------------------------ 2. pip
& $Py -m pip install --upgrade pip wheel | Out-Null

# ------------------------------------------------------------------ 3. Prune Hermes into the bundle
$bundledHermes = Join-Path $Dist "hermes"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $bundledHermes
New-Item -ItemType Directory -Force -Path $bundledHermes | Out-Null

# Files / directories we copy.
$keep = @(
    "agent",
    "tools",
    "gateway",                          # session_context, approval.py — required for terminal + desk
    "hermes_cli",
    "skills",
    "plugins",
    "cron",
    "pyproject.toml",
    "run_agent.py",
    "model_tools.py",
    "toolsets.py",
    "toolset_distributions.py",
    "trajectory_compressor.py",          # imported by agent code; harmless if unused
    "cli.py",
    "hermes_constants.py",
    "hermes_state.py",
    "hermes_time.py",
    "hermes_logging.py",
    "utils.py",
    "MANIFEST.in",
    "LICENSE"
)

foreach ($name in $keep) {
    $src = Join-Path $HermesDir $name
    if (Test-Path $src) {
        Copy-Item -Recurse -Force $src (Join-Path $bundledHermes $name)
    } else {
        Write-Warning "keep-list item missing in upstream: $name"
    }
}

# Drop unwanted subtrees that snuck in (gateway is in keep-list? no — but defensive)
$drop = @(
    "hermes_cli\gateway.py",
    "hermes_cli\curses_ui.py",     # POSIX termios-only, not used by web_server
    "hermes_cli\uninstall.py",     # POSIX geteuid; we have our own MSI uninstaller
    # Keep tools/environments/file_sync.py — ssh/modal/daytona import it; dropping it breaks agent init.
    "tools\rl_training_tool.py",
    "tools\feishu_doc_tool.py",
    "tools\feishu_drive_tool.py",
    "tools\homeassistant_tool.py",
    "tools\browser_camofox.py",
    "tools\browser_camofox_state.py",
    "tools\mixture_of_agents_tool.py"
)
foreach ($d in $drop) {
    $f = Join-Path $bundledHermes $d
    if (Test-Path $f) { Remove-Item -Force -Recurse $f }
}

# Prevent implicit namespace package causing subthread import failures
# (gateway/run.py spawns cron-ticker thread — from cron.scheduler import tick)
$hermesInit = Join-Path $bundledHermes "__init__.py"
if (-not (Test-Path $hermesInit)) {
    "" | Set-Content -Path $hermesInit -Encoding ASCII
}

function ConvertTo-GitBashPath([string]$WindowsPath) {
    $full = (Resolve-Path -LiteralPath $WindowsPath).Path
    if ($full -match '^([A-Za-z]):\\(.*)$') {
        $dl = $Matches[1].ToLowerInvariant()
        $tail = $Matches[2] -replace '\\', '/'
        return "/$dl/$tail"
    }
    throw "Cannot convert path to Git Bash form: $WindowsPath"
}

# Hermes `hermes/web/package.json` prebuild runs `sync-assets` with POSIX `rm`/`cp`; use Git Bash on Windows.
function Invoke-HermesWebNpmCommand {
    param(
        [string]$WebDir,
        [string[]]$NpmCmd
    )
    $gitBash = Join-Path ${env:ProgramFiles} "Git\bin\bash.exe"
    if (Test-Path -LiteralPath $gitBash) {
        $bashPath = ConvertTo-GitBashPath $WebDir
        $argsLine = $NpmCmd -join ' '
        $line = "set -e; cd '$bashPath' && npm $argsLine"
        & $gitBash -lc $line
        if ($LASTEXITCODE -ne 0) { throw "npm in hermes/web failed (exit $LASTEXITCODE): npm $argsLine" }
    } else {
        Push-Location $WebDir
        try {
            & npm @NpmCmd
            if ($LASTEXITCODE -ne 0) { throw "npm failed (exit $LASTEXITCODE): $($NpmCmd -join ' ')" }
        } finally { Pop-Location }
    }
}

# ------------------------------------------------------------------ 4b. Build Hermes' SPA (web/ -> hermes_cli/web_dist)
# `hermes_cli/web_server.py` expects the built SPA at
# `<package>/web_dist/`. Without this, every HTTP path returns
# {"error":"Frontend not built. Run: cd web && npm run build"}.
# Hermes dashboard SPA lives under the frozen source: hermes_vendor/web → hermes_vendor/hermes_cli/web_dist.
#
# IMPORTANT: always run `npm run build` by default. A stale hermes_cli/web_dist
# (e.g. from an older run) would previously skip the build and bundle an
# outdated UI — users saw old behaviour (e.g. desk chat stuck on a fallback).
$hermesWeb     = Join-Path $HermesDir "web" | Resolve-Path | Select-Object -ExpandProperty Path
$hermesWebDist = Join-Path $HermesDir "hermes_cli\web_dist"
if ($SkipWebBuild) {
    Write-Host "  (skip) npm run build — using existing hermes_cli\web_dist" -ForegroundColor DarkYellow
} else {
    # Always install so `sync-assets` (prebuild) sees a complete `node_modules` — a prior Windows-only
    # `npm install` can leave packages half-installed because `sync-assets` uses POSIX rm/cp.
    Write-Host "  npm install (hermes/web)..." -ForegroundColor DarkGray
    Invoke-HermesWebNpmCommand -WebDir $hermesWeb -NpmCmd @("install", "--no-audit", "--no-fund")
    Write-Host "  npm run build (hermes/web)..." -ForegroundColor DarkGray
    Invoke-HermesWebNpmCommand -WebDir $hermesWeb -NpmCmd @("run", "build")
}
if (-not (Test-Path (Join-Path $hermesWebDist "index.html"))) {
    throw "Hermes SPA build failed: $hermesWebDist\index.html not found (run without -SkipWebBuild to build)"
}
Copy-Item -Recurse -Force $hermesWebDist (Join-Path $bundledHermes "hermes_cli\web_dist")

# ------------------------------------------------------------------ 5. Install deps into a target dir (no venv)
$siteDir = Join-Path $Dist "site-packages"
function Clear-BundleSitePackages {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $lastErr = $null
    for ($i = 0; $i -lt 6; $i++) {
        try {
            Remove-Item -Recurse -Force -LiteralPath $Path -ErrorAction Stop
            return
        } catch {
            $lastErr = $_
            Start-Sleep -Seconds 2
        }
    }
    $stale = "$Path.stale_" + [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    try {
        Move-Item -LiteralPath $Path -Destination $stale -Force -ErrorAction Stop
        Write-Host "Note: could not delete site-packages in place (files locked). Renamed to:" -ForegroundColor Yellow
        Write-Host "  $stale" -ForegroundColor Yellow
        Write-Host "Quit HermesDesk / kill any python.exe using this runtime, then delete that folder manually." -ForegroundColor Yellow
        return
    } catch {
        $hint = "Usually a .pyd is still loaded: close HermesDesk, end any python.exe under:`n  $Dist`nthen rerun: .\python\build_bundle.ps1"
        throw ("Cannot remove or rename site-packages: " + $lastErr.Exception.Message + "`n`n" + $hint)
    }
}
Clear-BundleSitePackages -Path $siteDir
New-Item -ItemType Directory -Force -Path $siteDir | Out-Null

# ``--upgrade`` avoids "Target directory … already exists" when anything survived under
# ``site-packages`` or pip merges wheels that touch the same top-level names.
& $Py -m pip install `
    --upgrade `
    --target $siteDir `
    --no-warn-script-location `
    --platform win_amd64 `
    --python-version 3.11 `
    --only-binary=:all: `
    -r (Join-Path $PSScriptRoot "requirements-desktop.txt")

Write-Host "Verifying pip install (PyYAML / fastapi / uvicorn)..." -ForegroundColor DarkGray
$verifyScript = Join-Path $PSScriptRoot "tools\verify_bundle_site_packages.py"
& $Py $verifyScript $Dist
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip verification failed (exit $LASTEXITCODE). Fix errors above, or delete python/dist/runtime and rebuild."
    exit 11
}

# ------------------------------------------------------------------ 6. Copy overlays + entrypoint
$overlaysDest = Join-Path $Dist "overlays"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $overlaysDest
Copy-Item -Recurse -Force (Join-Path $PSScriptRoot "overlays") $overlaysDest
$helpersDest = Join-Path $Dist "helpers"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $helpersDest
Copy-Item -Recurse -Force (Join-Path $PSScriptRoot "helpers") $helpersDest
Copy-Item -Force (Join-Path $PSScriptRoot "src\desktop_entrypoint.py") (Join-Path $Dist "desktop_entrypoint.py")
Copy-Item -Force (Join-Path $PSScriptRoot "src\desktop_config.py") (Join-Path $Dist "desktop_config.py")
Copy-Item -Force (Join-Path $PSScriptRoot "src\desktop_contract.py") (Join-Path $Dist "desktop_contract.py")
Copy-Item -Force (Join-Path $PSScriptRoot "src\path_policy.py") (Join-Path $Dist "path_policy.py")
Copy-Item -Force (Join-Path $PSScriptRoot "src\secret_store.py") (Join-Path $Dist "secret_store.py")
Copy-Item -Force (Join-Path $PSScriptRoot "src\approval_backend.py") (Join-Path $Dist "approval_backend.py")
Copy-Item -Force (Join-Path $PSScriptRoot "src\network_policy.py") (Join-Path $Dist "network_policy.py")
Copy-Item -Force (Join-Path $PSScriptRoot "src\tool_policy.py") (Join-Path $Dist "tool_policy.py")
Copy-Item -Force (Join-Path $PSScriptRoot "src\gateway_policy.py") (Join-Path $Dist "gateway_policy.py")
Copy-Item -Force (Join-Path $PSScriptRoot "src\weixin_qr_worker.py") (Join-Path $Dist "weixin_qr_worker.py")
Copy-Item -Force (Join-Path $PSScriptRoot "src\qqbot_qr_worker.py") (Join-Path $Dist "qqbot_qr_worker.py")
Copy-Item -Force (Join-Path $PSScriptRoot "src\env_validate.py") (Join-Path $Dist "env_validate.py")
Copy-Item -Force (Join-Path $PSScriptRoot "src\feishu_qr_worker.py") (Join-Path $Dist "feishu_qr_worker.py")

# A pth file so the bundled hermes/ + site-packages are on sys.path
$pthBody = @(
    "..\hermes",
    "..\site-packages"
) -join "`n"
Set-Content -Path (Join-Path $pyDir "Lib\site-packages\hermesdesk.pth") -Value $pthBody -Encoding ASCII

# ------------------------------------------------------------------ 7. Bundle metadata
$info = @{
    pythonVersion  = $PythonVersion
    pbsRelease     = $PbsRelease
    builtAt        = (Get-Date).ToString("o")
    frozenCommit   = "90b304b7c (v2026.4.23 — frozen upstream snapshot)"
    bundleSizeMb   = [math]::Round(((Get-ChildItem -Recurse $Dist | Measure-Object Length -Sum).Sum / 1MB), 1)
}
$info | ConvertTo-Json | Set-Content -Path (Join-Path $Dist "BUNDLE_INFO.json") -Encoding UTF8

Write-Host ""
Write-Host "Bundle ready at $Dist  ($($info.bundleSizeMb) MB)" -ForegroundColor Green

# ------------------------------------------------------------------ 8. Verify
if ($Verify) {
    Write-Host "`n--- Smoke test ---" -ForegroundColor Cyan
    $env:HERMESDESK_BUNDLE_DIR = $Dist
    $env:HERMESDESK_DATA_DIR   = (Join-Path $env:TEMP "hermesdesk-smoke")
    $env:HERMESDESK_WORKSPACE  = (Join-Path $env:TEMP "hermesdesk-smoke\workspace")
    $env:HERMES_HOME           = (Join-Path $env:TEMP "hermesdesk-smoke\hermes-home")
    $env:HERMESDESK_OVERLAY_LENIENT = "1"
    New-Item -ItemType Directory -Force -Path $env:HERMESDESK_WORKSPACE, $env:HERMES_HOME | Out-Null
    & $Py -c @"
import sys
sys.path.insert(0, r'$Dist')
sys.path.insert(0, r'$Dist\hermes')
sys.path.insert(0, r'$Dist\site-packages')
from overlays import apply_all
apply_all()
import hermes_cli.web_server
print('OK: hermes_cli.web_server importable')
"@
    if ($LASTEXITCODE -ne 0) {
        Write-Error "smoke test FAILED"
        exit $LASTEXITCODE
    }
    Write-Host "smoke test passed" -ForegroundColor Green
}
