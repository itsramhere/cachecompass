param([string]$Output = 'reports/environment.json')
. "$PSScriptRoot\common.ps1"
$env:PYTHONPATH = Join-Path $Workspace 'src'
Invoke-Checked (Join-Path $Workspace '.venv\Scripts\python.exe') @('-m', 'cache_scaleout', 'doctor', '--config', 'configs/environment.json', '--output', $Output)

