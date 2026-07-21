---
name: dispatch-next
description: Read the current Round's recommended deployable set, pick the top-priority open package not already in flight, and route it to the correct agent.
invocation: /dispatch-next
---

# /dispatch-next

Read `.astroray_plan/docs/NEXT_STAGE_REPORT.md` §2 (Recommended next
deployable set). Identify the highest-priority open package that does not
already have an open PR or an active worktree.

## Routing rules

1. Spawn `package-implementer` in a fresh worktree
   (use `EnterWorktree` or `superpowers:using-git-worktrees`).
   Codex is retired — legacy `Track: E` / `Codex-paste-ready` tags in spec
   frontmatter are inert and route here too.

2. Pass to the spawned agent:
   - The drop-in prompt from NEXT_STAGE_REPORT.md §3 for that package
     (verbatim — those prompts are purpose-written)
   - The package spec path
   - The worktree name (e.g., `pkg55-phase-b`)

3. DRY-RUN mode: if invoked with `--dry-run`, print the routing decision
   (package name, agent, worktree) without spawning the agent.

## Example output (non-dry-run)

```
Dispatching: pkg55 Phase B → package-implementer
Worktree: .claude/worktrees/pkg55-phase-b
Prompt: [NEXT_STAGE_REPORT.md §3.1 verbatim]
```
