<#
.SYNOPSIS
Launch (and optionally babysit) a GUI Blender with the MCP bridge started, so
agents can drive it through the `uvx blender-mcp` server on localhost:9876.

.DESCRIPTION
Starts Blender 5.2 with scripts/dev/blender_mcp_autostart.py, which enables the
community blender_mcp add-on and starts its socket server. With -Watch the
script loops: if Blender exits or the port stops listening, it relaunches.
Read-only diagnostic counterpart: scripts/dev/check_blender_mcp.ps1.

.EXAMPLE
pwsh scripts/dev/launch_blender_mcp.ps1                 # start once
pwsh scripts/dev/launch_blender_mcp.ps1 -Watch          # start + restart on death
pwsh scripts/dev/launch_blender_mcp.ps1 -Stop           # stop the watched instance
#>
[CmdletBinding()]
param(
    [string]$BlenderExe = 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe',
    [int]$Port = 9876,
    [switch]$Watch,
    [switch]$Stop,
    [int]$PollSeconds = 15,
    [string]$BlendFile = ''
)

$ErrorActionPreference = 'Stop'
$repo = (git rev-parse --show-toplevel).Trim()
$stateDir = Join-Path $env:LOCALAPPDATA 'astroray'
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
$pidFile = Join-Path $stateDir 'blender_mcp.pid'
$stopFile = Join-Path $stateDir 'blender_mcp.stop'
$logFile = Join-Path $stateDir 'blender_mcp.log'
$startup = Join-Path $repo 'scripts\dev\blender_mcp_autostart.py'

function Test-PortListening([int]$p) {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue | Select-Object -First 1)
}

function Start-BlenderMcp {
    if (-not (Test-Path -LiteralPath $BlenderExe)) { throw "Blender not found: $BlenderExe" }
    $env:ASTRORAY_MCP_PORT = "$Port"
    $env:ASTRORAY_BLENDER_PID_FILE = $pidFile
    $argList = @()
    if ($BlendFile) { $argList += ('"{0}"' -f $BlendFile) }
    $argList += @('--python', ('"{0}"' -f $startup))
    $proc = Start-Process -FilePath $BlenderExe -ArgumentList $argList -PassThru `
        -RedirectStandardOutput $logFile -RedirectStandardError ($logFile + '.err')
    "$(Get-Date -Format s) started Blender pid $($proc.Id)" | Tee-Object -FilePath ($logFile + '.watch') -Append
    return $proc
}

if ($Stop) {
    New-Item -ItemType File -Force -Path $stopFile | Out-Null
    if (Test-Path -LiteralPath $pidFile) {
        $blenderPid = [int](Get-Content -LiteralPath $pidFile)
        Stop-Process -Id $blenderPid -Force -ErrorAction SilentlyContinue
        "stopped Blender pid $blenderPid"
    }
    exit 0
}

Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue
if (Test-PortListening $Port) {
    "port $Port already listening; not starting a second Blender"
    if (-not $Watch) { exit 0 }
    $proc = $null
} else {
    $proc = Start-BlenderMcp
}

if (-not $Watch) { exit 0 }

while (-not (Test-Path -LiteralPath $stopFile)) {
    Start-Sleep -Seconds $PollSeconds
    $alive = $proc -and -not $proc.HasExited
    if (-not $alive -and -not (Test-PortListening $Port)) {
        "$(Get-Date -Format s) Blender down; relaunching" | Tee-Object -FilePath ($logFile + '.watch') -Append
        $proc = Start-BlenderMcp
        Start-Sleep -Seconds 20
    }
}
"$(Get-Date -Format s) watch stopped" | Tee-Object -FilePath ($logFile + '.watch') -Append
