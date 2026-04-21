# scripts/make_updater_manifest.ps1
#
# Produces latest.json for Tauri's updater plugin. Must be uploaded to the
# release alongside the .msi and the .msi.sig.
#
# Schema: https://v2.tauri.app/plugin/updater/#static-json-file

param(
    [Parameter(Mandatory)] [string]$Version,           # e.g. v0.1.0
    [string]$BundleDir = "tauri/target/release/bundle/msi",
    [string]$Notes = "See release notes on GitHub.",
    [string]$Repo = $env:GITHUB_REPOSITORY            # set by Actions
)

$ErrorActionPreference = "Stop"

if (-not $Repo) { $Repo = "your-org/hermesdesk" }

$msi = Get-ChildItem -Path $BundleDir -Filter "*.msi" | Select-Object -First 1
$sig = Get-ChildItem -Path $BundleDir -Filter "*.msi.sig" | Select-Object -First 1
if (-not $msi) { throw "no .msi found in $BundleDir" }
if (-not $sig) { throw "no .msi.sig found in $BundleDir (configure tauri.conf updater key)" }

$cleanVer = $Version.TrimStart('v')
$url = "https://github.com/$Repo/releases/download/$Version/$($msi.Name)"
$signature = (Get-Content -Raw $sig.FullName).Trim()

$manifest = [ordered]@{
    version    = $cleanVer
    notes      = $Notes
    pub_date   = (Get-Date).ToString("o")
    platforms  = [ordered]@{
        "windows-x86_64" = [ordered]@{
            signature = $signature
            url       = $url
        }
    }
}

$out = "latest.json"
$manifest | ConvertTo-Json -Depth 6 | Set-Content -Path $out -Encoding UTF8
Write-Host "wrote $out for $Version" -ForegroundColor Green
