param([string]$Python = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe")
. "$PSScriptRoot\common.ps1"
if (-not (Test-Path .venv\Scripts\python.exe)) {
    Invoke-Checked $Python @('-m', 'venv', '.venv')
}
$ResearchPython = Join-Path $Workspace '.venv\Scripts\python.exe'
Invoke-Checked $ResearchPython @('-m', 'pip', 'install', '--require-hashes', '--only-binary=:all:', '-r', 'requirements.lock')
$env:PYTHONPATH = Join-Path $Workspace 'src'
Invoke-Checked $ResearchPython @('-c', 'import redis.asyncio, psycopg, psycopg_pool, yaml; print("Runtime imports OK")')

