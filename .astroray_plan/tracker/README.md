# Astroray Project Tracker

## What it is

A Google Sheets dashboard that pulls live state from the GitHub repo into
8 tabs. Auto-refreshes daily at 7 am via an Apps Script time-based trigger.

Tabs: **Dashboard**, **Packages**, **Pillars**, **PRs (open)**, **Issues (open)**,
**Commits**, **Timeline**, **About**.

## Where

The live Sheet URL is stored in `.astroray_plan/tracker/local.toml` (gitignored).
If that file is absent, recreate the Sheet from scratch using the recovery steps
below.

## Source of truth

`astroray_dashboard.gs` in this directory is the authoritative source. Any edit
to the tracker logic lands here first, then gets pasted into the standalone Apps
Script project in Google Drive.

## Recovery procedure

1. Open <https://script.google.com/u/0/home> → **New project**.
2. Paste the full contents of `astroray_dashboard.gs` into the `Code.gs` editor.
   Save the project (any name).
3. In the script editor, open **Project settings** → **Script properties** and add:
   - Key: `GITHUB_TOKEN`
   - Value: a GitHub PAT with **no scopes** (public-repo read; raises rate limit
     from 60/hr → 5000/hr; required, not optional).
4. Run `setup()` from the editor. Apps Script will request permissions
   (UrlFetchApp + SpreadsheetApp). Approve. Expect ~60 s on first run.
5. Run `installDailyTrigger()` once to schedule the 7 am auto-refresh.

After step 4, the script prints the new Sheet URL to the Execution Log. Copy it
into `.astroray_plan/tracker/local.toml`:

```toml
[sheet]
url = "https://docs.google.com/spreadsheets/d/..."
```

## Architect note

Agents may reference the tracker when surfacing project state (strategy-review
mode). The Sheet URL is stored in the local config, not here, to keep credentials
out of git.
