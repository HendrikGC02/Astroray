# Beads (bd) Workflow

This repository uses **bd** for issue tracking.

## Commands

```bash
bd ready --json
bd create "Issue title" --description="Details" -t task -p 2 --json
bd update <id> --claim --json
bd update <id> --priority 1 --json
bd close <id> --reason "Completed" --json
```

## Issue types

- `bug`
- `feature`
- `task`
- `epic`
- `chore`

## Priority levels

- `0` Critical
- `1` High
- `2` Medium
- `3` Low
- `4` Backlog

## Discovered work linking

Use dependencies to link follow-up work:

```bash
bd create "Found issue" --description="..." -p 1 --deps discovered-from:<parent-id> --json
```

## Session completion checklist

1. Run quality gates (build/tests)
2. Update issue status in bd
3. Sync bd state (`bd dolt push`)
4. Push git changes
