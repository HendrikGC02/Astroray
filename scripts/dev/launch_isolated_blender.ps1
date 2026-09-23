# Launch an ISOLATED GUI Blender 5.2 whose MCP bridge is forced onto a non-default
# port (default 9877) so measurement lanes never touch the owner's live instance
# on 9876. By default uses the installed user-profile addon; pass -StagedAddon
# <worktree>/dist/astroray to load a WORKTREE build instead WITHOUT installing into
# the user profile: the staged addon is copied to <StateDir>/extensions/user_default/astroray
# and BLENDER_USER_EXTENSIONS points the isolated instance at that root (Blender >= 4.2;
# the owner's live 9876 profile is never touched). Writes <StateDir>/blender_<port>.pid.
#   powershell -File scripts/dev/launch_isolated_blender.ps1 -Worker 1 -Port 9877 -StateDir <dir> [-StagedAddon <dist/astroray>]
param([int]$Worker = 0, [int]$Port = 9877, [string]$StateDir = $env:TEMP,
      [string]$StagedAddon = '',
      [switch]$Visible,
      [string]$Blender = 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe')
$ErrorActionPreference = 'Stop'
$stateRoot = (Resolve-Path -LiteralPath $StateDir).Path
foreach ($name in 'BLENDER_USER_CONFIG','BLENDER_USER_SCRIPTS','BLENDER_USER_DATAFILES','BLENDER_USER_EXTENSIONS','BLENDER_USER_RESOURCES') {
    $path = Join-Path $stateRoot ($name.ToLowerInvariant())
    New-Item -ItemType Directory -Force $path | Out-Null
    Set-Item -Path ("Env:{0}" -f $name) -Value $path
}
if ($StagedAddon -ne '') {
    if (-not (Test-Path (Join-Path $StagedAddon '__init__.py'))) { throw "StagedAddon '$StagedAddon' has no __init__.py (stage with scripts/build_blender_addon.py first)" }
    $extRoot = $env:BLENDER_USER_EXTENSIONS
    $dest = Join-Path $extRoot 'user_default/astroray'
    $resolvedDest = [IO.Path]::GetFullPath($dest)
    if (-not $resolvedDest.StartsWith($stateRoot, [StringComparison]::OrdinalIgnoreCase)) { throw "refusing staged-addon removal outside StateDir: $resolvedDest" }
    if (Test-Path $dest) { Remove-Item -Recurse -Force -LiteralPath $dest }
    New-Item -ItemType Directory -Force (Join-Path $extRoot 'user_default') | Out-Null
    Copy-Item -Recurse -Force $StagedAddon $dest
    # The MCP bridge extension lives only in the user profile; with BLENDER_USER_EXTENSIONS
    # redirected it would be invisible and the 9877 bridge would never bind (Batch M, 2026-09-19).
    $profileExt = Get-ChildItem (Join-Path $env:APPDATA 'Blender Foundation/Blender') -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | ForEach-Object { Join-Path $_.FullName 'extensions/user_default/mcp' } |
        Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($profileExt) {
        $mcpDest = Join-Path $extRoot 'user_default/mcp'
        $resolvedMcp = [IO.Path]::GetFullPath($mcpDest)
        if (-not $resolvedMcp.StartsWith($stateRoot, [StringComparison]::OrdinalIgnoreCase)) { throw "refusing mcp removal outside StateDir: $resolvedMcp" }
        if (Test-Path $mcpDest) { Remove-Item -Recurse -Force -LiteralPath $mcpDest }
        Copy-Item -Recurse -Force $profileExt $mcpDest
    } else { Write-Warning 'mcp extension not found in the user profile; the isolated bridge will not bind' }
    Write-Host "isolated extensions root: $extRoot (addon from $StagedAddon)"
}
$startup = Join-Path $PSScriptRoot 'blender_mcp_isolated.py'
$pidFile = Join-Path $StateDir ("blender_{0}.pid" -f $Port)
$log = Join-Path $StateDir ("blender_{0}.log" -f $Port)
$env:ASTRORAY_MCP_PORT = "$Port"
$env:ASTRORAY_BLENDER_PID_FILE = Join-Path $StateDir ("blender_{0}_inner.pid" -f $Port)
if ($Worker -eq 1) { $env:ASTRORAY_VIEWPORT_WORKER = '1' } else { Remove-Item Env:ASTRORAY_VIEWPORT_WORKER -ErrorAction SilentlyContinue }
$window = if ($Visible) { 'Normal' } else { 'Hidden' }
$proc = Start-Process -FilePath $Blender -ArgumentList @('--python', ('"{0}"' -f $startup)) -WindowStyle $window -PassThru -RedirectStandardOutput $log -RedirectStandardError ($log + '.err')
$proc.Id | Out-File -FilePath $pidFile -Encoding ascii
Write-Host "launched Blender pid $($proc.Id) worker=$Worker port=$Port log=$log"
