$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $repoRoot ".venv"
$pythonPath = Join-Path $venvPath "Scripts\python.exe"

Push-Location $repoRoot
try {
    if (-not (Test-Path $pythonPath)) {
        uv venv $venvPath --python 3.12
    }

    uv pip install --python $pythonPath sqlite-rx
    Write-Host "Installed sqlite-rx in $venvPath"
    Write-Host "Run: $pythonPath support\sqliteserver.py"
}
finally {
    Pop-Location
}
