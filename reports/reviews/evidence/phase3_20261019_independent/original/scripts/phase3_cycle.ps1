param(
    [Parameter(Mandatory=$true)][string]$FirstRunId,
    [Parameter(Mandatory=$true)][string]$SecondRunId,
    [string]$Config = 'configs/phase3_smoke.yaml',
    [string]$ValidationOutput = 'reports/evidence/phase3/reset-comparison.json'
)
. "$PSScriptRoot\common.ps1"
$Python = Join-Path $Workspace '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw 'Bootstrap the documented virtual environment first.' }
$env:PYTHONPATH = Join-Path $Workspace 'src'
try {
    & "$PSScriptRoot\shutdown.ps1"
    & "$PSScriptRoot\start.ps1"
    Invoke-Checked $Python @('-B', '-m', 'cache_scaleout', 'phase3-run', '--config', $Config, '--run-id', $FirstRunId)
    & "$PSScriptRoot\shutdown.ps1"
    & "$PSScriptRoot\start.ps1"
    Invoke-Checked $Python @('-B', '-m', 'cache_scaleout', 'phase3-run', '--config', $Config, '--run-id', $SecondRunId)
    Invoke-Checked $Python @('-B', '-m', 'cache_scaleout', 'phase3-validate', '--run', "runs/$FirstRunId", '--compare-run', "runs/$SecondRunId", '--output', $ValidationOutput)
}
finally {
    & "$PSScriptRoot\shutdown.ps1"
}
