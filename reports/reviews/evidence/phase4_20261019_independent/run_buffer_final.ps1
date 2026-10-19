$ErrorActionPreference = 'Stop'
$reviewRoot = 'C:\Users\ramst\Documents\antigravity\paper2'
Set-Location -LiteralPath $reviewRoot
. "$reviewRoot\scripts\common.ps1"
$env:PYTHONPATH = Join-Path $reviewRoot 'src'
try {
    & "$reviewRoot\scripts\shutdown.ps1"
    & "$reviewRoot\scripts\start.ps1"
    Invoke-Checked "$reviewRoot\.venv\Scripts\python.exe" @('-B','scripts/phase4_buffer_probe.py',
        '--run-id','p4final_buffer_20261019','--output','reports/reviews/evidence/phase4_20261019_independent/final_buffer_probe.json')
} finally {
    & "$reviewRoot\scripts\shutdown.ps1"
}
