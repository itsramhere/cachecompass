param([double]$Rate=36,[string]$Suffix='')
$ErrorActionPreference = 'Stop'
$reviewRoot = 'C:\Users\ramst\Documents\antigravity\paper2'
Set-Location -LiteralPath $reviewRoot
. "$reviewRoot\scripts\common.ps1"
$env:PYTHONPATH = Join-Path $reviewRoot 'src'
$env:PAPER2_DOCKER = Find-Docker
try {
    & "$reviewRoot\scripts\shutdown.ps1"
    & "$reviewRoot\scripts\start.ps1"
    Invoke-Checked "$reviewRoot\.venv\Scripts\python.exe" @('-B', 'reports/reviews/evidence/phase4_20261019_independent/diagnose_cleanup.py','--rate',"$Rate",'--suffix',"$Suffix")
} finally {
    & "$reviewRoot\scripts\shutdown.ps1"
}
