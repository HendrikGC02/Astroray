<#
.SYNOPSIS
Read-only diagnostic for Astroray's optional local Blender MCP bridge.

.DESCRIPTION
Checks the Codex project configuration, the uvx launcher, and whether a process
is listening on the configured Blender bridge port. It never launches Blender,
starts an MCP server, changes configuration, or sends commands to Blender.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

function Write-Result([string]$Name, [string]$State, [string]$Detail) {
    [pscustomobject]@{ Check = $Name; State = $State; Detail = $Detail }
}

try {
    $repo = (git rev-parse --show-toplevel).Trim()
    Set-Location -LiteralPath $repo
    $configPath = Join-Path $repo '.codex\config.toml'
    if (-not (Test-Path -LiteralPath $configPath)) {
        Write-Result 'Codex config' 'FAIL' "Missing $configPath"
        exit 1
    }

    $config = Get-Content -LiteralPath $configPath -Raw
    $portMatch = [regex]::Match($config, '(?m)^BLENDER_PORT\s*=\s*"(?<port>\d+)"\s*$')
    $timeoutMatch = [regex]::Match($config, '(?m)^startup_timeout_sec\s*=\s*(?<timeout>\d+)\s*$')
    if (-not $portMatch.Success -or -not $timeoutMatch.Success) {
        Write-Result 'Codex config' 'FAIL' 'Could not read BLENDER_PORT or startup_timeout_sec from .codex/config.toml'
        exit 1
    }

    $port = [int]$portMatch.Groups['port'].Value
    $timeoutSeconds = [int]$timeoutMatch.Groups['timeout'].Value
    Write-Result 'Codex config' 'PASS' "Blender port=$port; startup timeout=${timeoutSeconds}s"

    $uvx = Get-Command uvx -ErrorAction SilentlyContinue
    if ($uvx) {
        Write-Result 'uvx launcher' 'PASS' $uvx.Source
    } else {
        Write-Result 'uvx launcher' 'FAIL' 'uvx is not on PATH; install uv or expose its Scripts directory.'
    }

    $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($listener) {
        $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
        $processName = if ($process) { $process.ProcessName } else { "PID $($listener.OwningProcess)" }
        Write-Result 'Blender bridge' 'PASS' "localhost:$port is listening ($processName)"
    } else {
        Write-Result 'Blender bridge' 'WAITING' "Nothing is listening on localhost:$port. Start Blender and its MCP bridge before using Blender tools."
    }

    if (-not $uvx) { exit 1 }
    if (-not $listener) { exit 2 }
    exit 0
} catch {
    Write-Error $_
    exit 1
}
