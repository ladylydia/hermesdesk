# scripts/audit_posix_imports.ps1
#
# Greps the upstream Hermes tree for posix-only imports and risky os.* calls,
# then categorizes hits as: STRIP / POWER_USER / KEEP-NEEDS-PATCH / KEEP-OK.
#
# Usage:
#   .\scripts\audit_posix_imports.ps1                    # human-readable
#   .\scripts\audit_posix_imports.ps1 -Json > audit.json # machine-readable
#
# Exit code is the number of KEEP-NEEDS-PATCH files (0 = green light).

[CmdletBinding()]
param(
    [string]$HermesRoot = "",
    [switch]$Json
)

if (-not $HermesRoot) {
    $base = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
    $HermesRoot = Join-Path $base "..\hermes"
}
$HermesRoot = (Resolve-Path -LiteralPath $HermesRoot).ProviderPath

$ErrorActionPreference = "Stop"

if (-not (Test-Path $HermesRoot)) {
    Write-Error "Hermes submodule not found at $HermesRoot. Run: git submodule update --init"
    exit 2
}

# --- Configuration: keep / strip / power-user lists -------------------------

$STRIP_PREFIXES = @(
    "gateway/",
    "tui_gateway/",
    "acp_adapter/",
    "acp_registry/",
    "tinker-atropos/",
    "rl_cli.py",
    "batch_runner.py",
    "mini_swe_runner.py",
    "trajectory_compressor.py",
    "mcp_serve.py",
    "tools/environments/file_sync.py",
    "hermes_cli/gateway.py",
    "tests/"
)

$POWER_USER_FILES = @(
    "tools/code_execution_tool.py",
    "tools/browser_tool.py",
    "tools/browser_camofox.py",
    "tools/terminal_tool.py",
    "tools/mcp_tool.py",
    "tools/mcp_oauth.py",
    "tools/mcp_oauth_manager.py",
    "tools/cronjob_tools.py",
    "tools/delegate_tool.py",
    "tools/mixture_of_agents_tool.py",
    "tools/rl_training_tool.py",
    "tools/send_message_tool.py",
    "tools/feishu_doc_tool.py",
    "tools/feishu_drive_tool.py",
    "tools/homeassistant_tool.py",
    "tools/process_registry.py",
    "tools/environments/local.py",
    "tools/environments/base.py"
)

# Posix-only stdlib modules (will fail to import on Windows)
$POSIX_MODULES = @(
    "fcntl", "pty", "termios", "tty", "grp", "pwd",
    "resource", "posix", "crypt", "spwd", "nis", "syslog",
    "ptyprocess"
)

# Posix-only os.* calls that need a _IS_WINDOWS guard
$POSIX_OS_CALLS = @(
    "os\.fork", "os\.setsid", "os\.setpgid", "os\.setpgrp",
    "os\.killpg", "os\.geteuid", "os\.getuid",
    "os\.WIFEXITED", "os\.WEXITSTATUS", "os\.WIFSIGNALED"
)

# --- Helpers ---------------------------------------------------------------

function Get-Disposition([string]$relPath) {
    foreach ($p in $STRIP_PREFIXES) {
        if ($relPath -like "$p*" -or $relPath -eq $p.TrimEnd('/')) {
            return "STRIP"
        }
    }
    foreach ($f in $POWER_USER_FILES) {
        if ($relPath -eq $f) { return "POWER_USER" }
    }
    return "KEEP"
}

function Is-Guarded([string]$absPath, [string]$pattern) {
    # Accept any of three guard styles:
    #   1. `_IS_WINDOWS` constant
    #   2. `sys.platform == "win..."` checks
    #   3. `try: import X / except (ImportError|Exception): X = None` pattern
    #      followed by `if X:` checks before use
    $content = Get-Content -Raw -LiteralPath $absPath -ErrorAction SilentlyContinue
    if (-not $content) { return $false }
    if ($content -match "_IS_WINDOWS|sys\.platform\s*[!=]=\s*['""]win") { return $true }
    if ($content -match "try:\s*\r?\n\s*import\s+(fcntl|termios|pty|grp|pwd|resource|ptyprocess)") { return $true }
    return $false
}

# --- Scan ------------------------------------------------------------------

$importPattern = '^\s*(import|from)\s+(' + ($POSIX_MODULES -join '|') + ')\b'
$callPattern = '\b(' + ($POSIX_OS_CALLS -join '|') + ')\b'

$results = @()

$rootLen = $HermesRoot.TrimEnd('\','/').Length
Get-ChildItem -Path $HermesRoot -Recurse -Filter *.py -File | ForEach-Object {
    $abs = $_.FullName
    $rel = if ($abs.Length -gt $rootLen) { $abs.Substring($rootLen).TrimStart('\','/').Replace('\','/') } else { $abs }

    $hits = @()
    $lines = Get-Content -LiteralPath $abs
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $line = $lines[$i]
        if ($line -match $importPattern) {
            $hits += [PSCustomObject]@{
                kind = "import"
                line = $i + 1
                text = $line.Trim()
            }
        }
        if ($line -match $callPattern) {
            $hits += [PSCustomObject]@{
                kind = "call"
                line = $i + 1
                text = $line.Trim()
            }
        }
    }

    if ($hits.Count -gt 0) {
        $disp = Get-Disposition $rel
        $guarded = Is-Guarded $abs $callPattern
        $action = switch ($disp) {
            "STRIP"      { "STRIP" }
            "POWER_USER" { "POWER_USER" }
            "KEEP" {
                if ($guarded) { "KEEP-OK" } else { "KEEP-NEEDS-PATCH" }
            }
        }
        $results += [PSCustomObject]@{
            path        = $rel
            disposition = $disp
            action      = $action
            hits        = $hits
        }
    }
}

# --- Output ----------------------------------------------------------------

if ($Json) {
    $results | ConvertTo-Json -Depth 6
} else {
    $byAction = $results | Group-Object action
    Write-Host ""
    Write-Host "Posix-import audit against $HermesRoot" -ForegroundColor Cyan
    Write-Host ("=" * 72)
    foreach ($g in $byAction | Sort-Object Name) {
        $color = switch ($g.Name) {
            "STRIP"            { "DarkGray" }
            "POWER_USER"       { "Yellow" }
            "KEEP-OK"          { "Green" }
            "KEEP-NEEDS-PATCH" { "Red" }
        }
        Write-Host ""
        Write-Host "[$($g.Name)] $($g.Count) file(s)" -ForegroundColor $color
        foreach ($r in $g.Group | Sort-Object path) {
            Write-Host "  $($r.path)"
            foreach ($h in $r.hits) {
                Write-Host "    L$($h.line) ($($h.kind)) $($h.text)" -ForegroundColor DarkGray
            }
        }
    }
    Write-Host ""
    $needsPatch = ($byAction | Where-Object Name -eq "KEEP-NEEDS-PATCH").Count
    $color = if ($needsPatch -eq 0) { "Green" } else { "Red" }
    Write-Host "KEEP-NEEDS-PATCH count: $needsPatch" -ForegroundColor $color
}

$needsPatch = ($results | Where-Object action -eq "KEEP-NEEDS-PATCH").Count
exit $needsPatch
