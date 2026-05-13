---
name: close-round
description: Spawn docs-updater to close the current round, then check whether a strategy review should fire.
invocation: /close-round
---

# /close-round

## Step 1 — Spawn docs-updater

Spawn the `docs-updater` agent. Pass it the list of PRs merged since the
last STATUS.md update. Wait for it to return and confirm the doc PR is
open or merged.

## Step 2 — Check for strategy review trigger

After docs-updater returns, check whether any of these conditions are met:

| Condition | Action |
|---|---|
| 3 or more packages have deferred targets (measurement-vs-spec divergence events) since the last architect review | Spawn architect in `state+refine` mode |
| This is the 3rd round since the last architect review | Spawn architect in `state+refine` mode |
| Every round | Spawn architect in `state+refine` mode (light pass: current-state surface + one question) |

A "light" state+refine pass is: read the current render output + status,
ask one short question, accept "no changes needed" as a complete answer.

## Step 3 — Report to user

After docs-updater and (if triggered) the architect return:

- Confirm the doc PR is open/merged
- Summarise what the architect decided (if it ran)
- State what the next dispatch will pick up (top of NEXT_STAGE_REPORT.md §2)
