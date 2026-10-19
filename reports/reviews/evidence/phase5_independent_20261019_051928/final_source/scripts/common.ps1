$ErrorActionPreference = 'Stop'
$Workspace = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Workspace
function Find-Docker {
    $candidates = @(
        "$env:LOCALAPPDATA\Programs\DockerDesktop\resources\bin\docker.exe",
        'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
    )
    $command = Get-Command docker -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    throw 'Docker CLI unavailable. No software will be installed automatically.'
}
function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed with exit code $LASTEXITCODE : $Executable $($Arguments -join ' ')" }
}
function Set-ResearchPassword {
    if (-not $env:PAPER2_DB_PASSWORD) {
        # Public disposable local credential, never use on shared/production services.
        $env:PAPER2_DB_PASSWORD = 'paper2-disposable-local-only'
    }
}

