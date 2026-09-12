# Launch an ISOLATED GUI Blender 5.2 whose MCP bridge is forced onto a non-default
# port (default 9877) so measurement lanes never touch the owner's live instance
# on 9876. Uses the installed user-profile addon (restage + --install first when a
# worktree build must be measured). Writes <StateDir>/blender_<port>.pid.
#   powershell -File scripts/dev/launch_isolated_blender.ps1 -Worker 1 -Port 9877 -StateDir <dir>
param([int]$Worker = 0, [int]$Port = 9877, [string]$StateDir = $env:TEMP,
      [string]$Blender = 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe')
$ErrorActionPreference = 'Stop'
$startup = Join-Path $PSScriptRoot 'blender_mcp_isolated.py'
$pidFile = Join-Path $StateDir ("blender_{0}.pid" -f $Port)
$log = Join-Path $StateDir ("blender_{0}.log" -f $Port)
$env:ASTRORAY_MCP_PORT = "$Port"
$env:ASTRORAY_BLENDER_PID_FILE = Join-Path $StateDir ("blender_{0}_inner.pid" -f $Port)
if ($Worker -eq 1) { $env:ASTRORAY_VIEWPORT_WORKER = '1' } else { Remove-Item Env:ASTRORAY_VIEWPORT_WORKER -ErrorAction SilentlyContinue }
$proc = Start-Process -FilePath $Blender -ArgumentList @('--python', ('"{0}"' -f $startup)) -PassThru -RedirectStandardOutput $log -RedirectStandardError ($log + '.err')
$proc.Id | Out-File -FilePath $pidFile -Encoding ascii
Write-Host "launched Blender pid $($proc.Id) worker=$Worker port=$Port log=$log"
