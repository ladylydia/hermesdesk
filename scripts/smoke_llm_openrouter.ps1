# One-shot live LLM call via OpenRouter (same stack as HermesDesk docs).
# Usage (PowerShell):
#   $env:OPENROUTER_API_KEY = "sk-or-..."
#   .\scripts\smoke_llm_openrouter.ps1
#
# Uses the bundled CPython + site-packages from python/dist/runtime (build first).

[CmdletBinding()]
param(
    [string]$Model = "google/gemini-2.0-flash-001"
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\python\dist\runtime")
$py = Join-Path $root "python\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "Bundled Python not found at $py — run: .\python\build_bundle.ps1"
}

$key = [Environment]::GetEnvironmentVariable("OPENROUTER_API_KEY", "Process")
if (-not $key) {
    Write-Error "Set OPENROUTER_API_KEY in this shell first."
}

$env:PYTHONPATH = (Join-Path $root "site-packages")
$code = @'
import os, sys
from openai import OpenAI
key = os.environ["OPENROUTER_API_KEY"].strip()
client = OpenAI(api_key=key, base_url="https://openrouter.ai/api/v1")
model = os.environ.get("SMOKE_MODEL", "google/gemini-2.0-flash-001")
resp = client.chat.completions.create(
    model=model,
    messages=[{"role": "user", "content": "Reply with exactly the single word: pong"}],
    max_tokens=32,
)
text = (resp.choices[0].message.content or "").strip()
print(text)
sys.exit(0 if "pong" in text.lower() else 1)
'@

$env:SMOKE_MODEL = $Model
$env:OPENROUTER_API_KEY = $key
& $py -c $code
