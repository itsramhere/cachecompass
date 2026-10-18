param([string]$Output = 'reports/source_state.json')
. "$PSScriptRoot\common.ps1"
if (Test-Path -LiteralPath $Output) { throw 'Source evidence exists; choose a new output.' }
$env:PYTHONPATH = Join-Path $Workspace 'src'
$env:PAPER2_FINGERPRINT_OUTPUT = $Output
Invoke-Checked (Join-Path $Workspace '.venv\Scripts\python.exe') @('-c', 'import os; from pathlib import Path; from cache_scaleout.evidence import source_fingerprint, write_json; value = source_fingerprint(); write_json(Path(os.environ["PAPER2_FINGERPRINT_OUTPUT"]), value); print(value["aggregate_sha256"])')

