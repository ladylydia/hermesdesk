# scripts/dev.ps1 - one-command developer loop
#
# Builds the Python bundle if missing, then runs the Tauri dev server
# (which itself runs `npm run dev` for the web/).

[CmdletBinding()]
param([switch]$Rebuild)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $root
try {
    if ($Rebuild -or -not (Test-Path "python\dist\runtime\python\python.exe")) {
        Write-Host "Building Python bundle..." -ForegroundColor Cyan
        ./python/build_bundle.ps1
    } else {
        Write-Host "Python bundle present (use -Rebuild to force)." -ForegroundColor DarkGray
    }

    if (-not (Test-Path "web\node_modules")) {
        Write-Host "Installing web deps..." -ForegroundColor Cyan
        Push-Location web
        npm ci
        Pop-Location
    }

    Write-Host "Launching Tauri dev..." -ForegroundColor Cyan
    Push-Location tauri
    cargo tauri dev
    Pop-Location
} finally {
    Pop-Location
}
