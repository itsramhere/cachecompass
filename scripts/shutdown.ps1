. "$PSScriptRoot\common.ps1"
Set-ResearchPassword
$Docker = Find-Docker
Invoke-Checked $Docker @('compose', '--project-name', 'paper2-research', '--env-file', 'infra/images.env', '-f', 'infra/compose.yaml', 'down', '--volumes', '--timeout', '10')
$remaining = & $Docker ps -aq --filter 'label=com.docker.compose.project=paper2-research'
if ($LASTEXITCODE -ne 0 -or $remaining) { throw 'Shutdown verification failed: research containers remain or inspection failed.' }
Write-Output 'Shutdown verified: no paper2-research containers remain.'

