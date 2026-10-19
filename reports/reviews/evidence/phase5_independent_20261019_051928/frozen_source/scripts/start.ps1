. "$PSScriptRoot\common.ps1"
Set-ResearchPassword
$Docker = Find-Docker
$osType = & $Docker info --format '{{.OSType}}'
if ($LASTEXITCODE -ne 0 -or $osType -ne 'linux') { throw 'A healthy Linux Docker engine is required; no engine settings are changed automatically.' }
Invoke-Checked $Docker @('compose', '--project-name', 'paper2-research', '--env-file', 'infra/images.env', '-f', 'infra/compose.yaml', 'up', '-d', '--wait', '--wait-timeout', '90')

