param([string]$Output = 'reports/source_state.json')
. "$PSScriptRoot\common.ps1"
if (Test-Path -LiteralPath $Output) { throw 'Source evidence exists; choose a new output.' }
$env:PYTHONPATH = Join-Path $Workspace 'src'
Invoke-Checked (Join-Path $Workspace '.venv\Scripts\python.exe') @('scripts/capture_source.py', '--output', $Output)

