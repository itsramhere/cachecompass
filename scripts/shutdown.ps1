. "$PSScriptRoot\common.ps1"
Set-ResearchPassword
$Docker = Find-Docker
$researchIds = @(& $Docker ps -aq --filter 'label=com.docker.compose.project=paper2-research')
if ($LASTEXITCODE -ne 0) { throw 'Cannot verify disposable project before shutdown.' }
foreach ($researchId in $researchIds) {
    if (-not $researchId) { continue }
    $inspection = (& $Docker inspect $researchId | ConvertFrom-Json)[0]
    $service = $inspection.Config.Labels.'com.docker.compose.service'
    if ($LASTEXITCODE -ne 0 -or $inspection.Config.Labels.'org.paper2.purpose' -ne 'disposable-research' -or
        $service -notin @('cache-old-1', 'cache-old-2', 'cache-new', 'database')) {
        throw 'Refusing to remove an unrecognized project container.'
    }
}
Invoke-Checked $Docker @('compose', '--project-name', 'paper2-research', '--env-file', 'infra/images.env', '-f', 'infra/compose.yaml', 'down', '--volumes', '--timeout', '10')
$remaining = & $Docker ps -aq --filter 'label=com.docker.compose.project=paper2-research'
if ($LASTEXITCODE -ne 0 -or $remaining) { throw 'Shutdown verification failed: research containers remain or inspection failed.' }
Write-Output 'Shutdown verified: no paper2-research containers remain.'

