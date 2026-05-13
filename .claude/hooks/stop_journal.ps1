#!/usr/bin/env pwsh
# Stop hook: append a timestamped entry to the session journal

$journalPath = Join-Path $env:CLAUDE_PROJECT_DIR ".astroray_plan\session-journal.md"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm"

# Ensure the journal exists
if (-not (Test-Path $journalPath)) {
    "# Astroray Session Journal`n`n" | Set-Content $journalPath -Encoding UTF8
}

# Append a timestamped entry. The agent fills in the summary during the session;
# this hook records the session boundary so nothing is silently lost.
$entry = "$timestamp | claude | (session end — update this line with the main decision/output)"
Add-Content -Path $journalPath -Value $entry -Encoding UTF8
