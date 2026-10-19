param([string]$RedisTag = 'redis:7.4-alpine', [string]$PostgresTag = 'postgres:17-alpine')
. "$PSScriptRoot\common.ps1"
if (Test-Path infra\images.env) { throw 'Image lock already exists; preserve it. Remove/change only with a decision record.' }
$Docker = Find-Docker
$lines = @('# Immutable images resolved for linux/amd64; original tags recorded in phase evidence.')
foreach ($item in @(@('REDIS_IMAGE', $RedisTag), @('POSTGRES_IMAGE', $PostgresTag))) {
    Invoke-Checked $Docker @('pull', '--platform', 'linux/amd64', $item[1])
    $digest = & $Docker image inspect $item[1] --format '{{index .RepoDigests 0}}'
    if ($LASTEXITCODE -ne 0 -or $digest -notmatch '@sha256:[0-9a-f]{64}$') { throw 'Could not resolve immutable image digest' }
    $lines += "$($item[0])=$digest"
}
$lines | Set-Content -Encoding ascii infra\images.env

