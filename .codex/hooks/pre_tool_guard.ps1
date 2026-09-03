#!/usr/bin/env pwsh
# Ports the useful Claude guards to Codex's PreToolUse event.

$ErrorActionPreference = 'Stop'

function Block([string]$Message) {
    throw "ASTRORAY_BLOCK: $Message"
}

function Write-Context([string]$Message) {
    @{ hookSpecificOutput = @{ hookEventName = 'PreToolUse'; additionalContext = $Message } } | ConvertTo-Json -Compress
}

try {
    $raw = [Console]::In.ReadToEnd()
    if (-not $raw) { exit 0 }
    $payload = $raw | ConvertFrom-Json
    $tool = [string]$payload.tool_name
    $command = [string]$payload.tool_input.command
    $repo = (git rev-parse --show-toplevel 2>$null).Trim()
    if (-not $repo) { exit 0 }
    Set-Location -LiteralPath $repo

    if ($tool -eq 'apply_patch') {
        if ($command -match '(?im)^\*\*\* (?:Add|Update|Delete) File:\s+.*\.pyd\s*$' -or $command -match '(?im)^\+\+\+\s+(?:b/)?[^\r\n]*\.pyd\s*$') {
            Block '[astroray] BLOCKED: .pyd files are build artifacts; rebuild from source instead of patching them.'
        }
        exit 0
    }
    if ($tool -ne 'Bash' -or -not $command) { exit 0 }

    if ($command -match '\bpytest\b' -or ($command -match '\bpython\b' -and $command -match 'astroray')) {
        $legitimate = '(^|[\\/])(build|build_cuda|build_tcnn|build_blender_addon[^\\/]*|dist)([\\/]|$)|(^|[\\/])blender_addon[\\/]Release([\\/]|$)'
        $shadows = @(Get-ChildItem -LiteralPath $repo -Recurse -Filter 'astroray*.pyd' -Force -ErrorAction SilentlyContinue | Where-Object {
            $_.FullName.Substring($repo.Length).TrimStart('\\', '/') -notmatch $legitimate
        })
        if ($shadows.Count) {
            $listed = ($shadows | Select-Object -First 6 | ForEach-Object { $_.FullName.Substring($repo.Length).TrimStart('\\', '/') }) -join ', '
            if (@($shadows | Where-Object { $_.DirectoryName -eq $repo }).Count) {
                Block "[astroray] BLOCKED: root-level shadow .pyd detected ($listed). Remove build debris before trusting tests."
            }
            Write-Context "[astroray] Warning: .pyd shadow(s) outside recognised build output: $listed. Check the import path before trusting tests."
            exit 0
        }
    }

    if ($command -match '\bgit\s+commit\b') {
        $diff = (@(git diff --cached 2>$null) + @(git diff 2>$null)) -join "`n"
        if ($diff -match '(?im)\[pkg\d+-diag\]|REMOVE AFTER|XXX DEBUG|printf[^\r\n]*pkg[^\r\n]*diag|// \[diag\]') {
            Block '[astroray] BLOCKED: diagnostic markers are present in staged or unstaged changes. Remove them before committing.'
        }
    }

    if ($command -match '\bgit\s+push\b|\bgh\s+pr\s+create\b') {
        Write-Context '[astroray] Before push/PR: list changed function or class signatures and inspect all unchanged callers, including tests, mocks, and bindings.'
    }
} catch {
    if ($_.Exception.Message -like 'ASTRORAY_BLOCK:*') {
        $reason = $_.Exception.Message.Substring('ASTRORAY_BLOCK: '.Length)
        @{ decision = 'block'; reason = $reason } | ConvertTo-Json -Compress
        exit 0
    }
    # A guard/runtime failure must not make Codex unusable.
    exit 0
}
