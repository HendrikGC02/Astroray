#!/usr/bin/env pwsh
# Shared helper for PreToolUse hooks: resolve which repo checkout to run
# staged/unstaged checks against, given the Bash command about to run and
# the hook's JSON payload.
#
# A commit issued via `git -C <path> commit ...` or `cd <path> && git commit
# ...` (or `cd <path>; git commit ...`) targets <path>, which may be a linked
# worktree, not the main checkout. Blindly checking $env:CLAUDE_PROJECT_DIR
# in that case inspects the wrong repo's staged files.
#
# Resolution order:
#   1. `git -C <path> ...` in the command -> that path
#   2. command starts with `cd <path>` chained via && or ; -> that path
#   3. the hook payload's .cwd field, if present
#   4. $env:CLAUDE_PROJECT_DIR (main checkout) as the final fallback

function Resolve-HookRepoPath {
    param(
        [string]$Command,
        [string]$PayloadCwd
    )

    if ($Command) {
        # git -C <path> ...
        if ($Command -match "git\s+-C\s+(?:'([^']+)'|\`"([^\`"]+)\`"|(\S+))") {
            $path = $Matches[1]
            if (-not $path) { $path = $Matches[2] }
            if (-not $path) { $path = $Matches[3] }
            if ($path) { return $path }
        }

        # cd <path> && ... / cd <path>; ...  (must lead the command)
        if ($Command -match "^\s*cd\s+(?:'([^']+)'|\`"([^\`"]+)\`"|(\S+))\s*(?:&&|;)") {
            $path = $Matches[1]
            if (-not $path) { $path = $Matches[2] }
            if (-not $path) { $path = $Matches[3] }
            if ($path) { return $path }
        }
    }

    if ($PayloadCwd) {
        return $PayloadCwd
    }

    return $env:CLAUDE_PROJECT_DIR
}
