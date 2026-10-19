param(
    [Parameter(Mandatory=$true)][ValidateSet('calibrate','immediate')][string]$Mode,
    [Parameter(Mandatory=$true)][string]$RunId,
    [Parameter(Mandatory=$true)][double]$Rate,
    [ValidateSet('control','immediate')][string]$Condition = 'control',
    [string]$Config = 'configs/phase4_calibration.yaml'
)
. "$PSScriptRoot\common.ps1"
$Python = Join-Path $Workspace '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw 'Bootstrap the documented virtual environment first.' }
$env:PYTHONPATH = Join-Path $Workspace 'src'
try {
    # A full project recreation is required: namespace isolation alone cannot
    # establish equivalent LRU/allocator state under bounded Redis memory.
    & "$PSScriptRoot\shutdown.ps1"
    & "$PSScriptRoot\start.ps1"
    if ($Mode -eq 'calibrate') {
        Invoke-Checked $Python @('-B','-m','cache_scaleout','phase4-calibrate','--config',$Config,'--run-id',$RunId,'--rate',$Rate)
    } else {
        Invoke-Checked $Python @('-B','-m','cache_scaleout','phase4-immediate','--config',$Config,'--run-id',$RunId,'--rate',$Rate,'--condition',$Condition)
    }
}
finally {
    & "$PSScriptRoot\shutdown.ps1"
}
