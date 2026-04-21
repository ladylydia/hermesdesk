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
#   └── BUNDLE_INFO.json          <- versions + hashes for the updater
#
# Usage:
#   .\python\build_bundle.ps1                # build
#   .\python\build_bundle.ps1 -Verify        # build + smoke-test
#   .\python\build_bundle.ps1 -Clean         # wipe and rebuild

[CmdletBinding()]
param(
    [string]$PythonVersion = "3.11.15",
    [string]$PbsRelease    = "20260414",   # python-build-standalone tag (latest as of 2026-04-19)
    [switch]$Clean,
    [switch]$Verify
)

$ErrorActionPreference = "Stop"
$Root      = Resolve-Path (Join-Path $PSScriptRoot "..")
$BuildDir  = Join-Path $PSScriptRoot "_build"
$Download  = Join-Path $PSScriptRoot "_download"
$Dist      = Join-Path $PSScriptRoot "dist\runtime"
$HermesDir = Join-Path $Root "hermes"

if ($Clean) {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $BuildDir, $Dist
}

New-Item -ItemType Directory -Force -Path $BuildDir, $Download, $Dist | Out-Null

if (-not (Test-Path (Join-Path $HermesDir "pyproject.toml"))) {
    Write-Error "Hermes submodule not initialised. Run: git submodule update --init"
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

# ------------------------------------------------------------------ 3. Apply patches (none in v1, but keep the hook)
$patchDir = Join-Path $Root "patches"
foreach ($p in (Get-ChildItem -Path $patchDir -Filter *.patch -ErrorAction SilentlyContinue | Sort-Object Name)) {
    Write-Host "Applying patch: $($p.Name)"
    & git -C $HermesDir apply --3way --ignore-whitespace $p.FullName
}

# ------------------------------------------------------------------ 4. Prune Hermes into the bundle
$bundledHermes = Join-Path $Dist "hermes"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $bundledHermes
New-Item -ItemType Directory -Force -Path $bundledHermes | Out-Null

# Files / directories we copy.
$keep = @(
    "agent",
    "tools",
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
    "tools\environments\file_sync.py",
    "tools\rl_training_tool.py",
    "tools\send_message_tool.py",
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

# ------------------------------------------------------------------ 4b. Build Hermes' SPA (web/ -> hermes_cli/web_dist)
# `hermes_cli/web_server.py` expects the built SPA at
# `<package>/web_dist/`. Without this, every HTTP path returns
# {"error":"Frontend not built. Run: cd web && npm run build"}.
# Hermes dashboard SPA lives under the submodule: hermes/web → hermes/hermes_cli/web_dist (see vite.config.ts).
$hermesWeb     = Join-Path $HermesDir "web" | Resolve-Path | Select-Object -ExpandProperty Path
$hermesWebDist = Join-Path $HermesDir "hermes_cli\web_dist"
if (-not (Test-Path (Join-Path $hermesWebDist "index.html"))) {
    if (-not (Test-Path (Join-Path $hermesWeb "node_modules"))) {
        Write-Host "  npm install (hermes/web)..." -ForegroundColor DarkGray
        Push-Location $hermesWeb
        try { npm install --no-audit --no-fund 2>&1 | Out-Null } finally { Pop-Location }
    }
    Write-Host "  npm run build (hermes/web)..." -ForegroundColor DarkGray
    Push-Location $hermesWeb
    try { npm run build 2>&1 | Out-Null } finally { Pop-Location }
}
if (-not (Test-Path (Join-Path $hermesWebDist "index.html"))) {
    throw "Hermes SPA build failed: $hermesWebDist\index.html not found"
}
Copy-Item -Recurse -Force $hermesWebDist (Join-Path $bundledHermes "hermes_cli\web_dist")

# ------------------------------------------------------------------ 5. Install deps into a target dir (no venv)
$siteDir = Join-Path $Dist "site-packages"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $siteDir
New-Item -ItemType Directory -Force -Path $siteDir | Out-Null

& $Py -m pip install `
    --target $siteDir `
    --no-warn-script-location `
    -r (Join-Path $PSScriptRoot "requirements-desktop.txt")

# ------------------------------------------------------------------ 6. Copy overlays + entrypoint
$overlaysDest = Join-Path $Dist "overlays"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $overlaysDest
Copy-Item -Recurse -Force (Join-Path $PSScriptRoot "overlays") $overlaysDest
$helpersDest = Join-Path $Dist "helpers"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $helpersDest
Copy-Item -Recurse -Force (Join-Path $PSScriptRoot "helpers") $helpersDest
Copy-Item -Force (Join-Path $PSScriptRoot "src\desktop_entrypoint.py") (Join-Path $Dist "desktop_entrypoint.py")

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
    hermesCommit   = (& git -C $HermesDir rev-parse HEAD).Trim()
    hermesDescribe = (& git -C $HermesDir describe --tags --always).Trim()
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
