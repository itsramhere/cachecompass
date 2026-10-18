param([string]$RunId = 'phase0-health-review', [string]$RetryOf = '')
. "$PSScriptRoot\common.ps1"
Set-ResearchPassword
$env:PYTHONPATH = Join-Path $Workspace 'src'
$arguments = @('-m', 'cache_scaleout', 'health', '--config', 'configs/environment.json', '--run-id', $RunId)
if ($RetryOf) { $arguments += @('--retry-of', $RetryOf) }
Invoke-Checked (Join-Path $Workspace '.venv\Scripts\python.exe') $arguments

