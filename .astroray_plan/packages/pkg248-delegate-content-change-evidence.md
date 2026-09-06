# pkg248 — Delegate content-change evidence

**Pillar:** 5 (delivery tooling)
**Track:** A
**Status:** OPEN — detailed architect review required before implementation
**Estimated effort:** TBD at detailed architecture review
**Depends on:** [pkg232](pkg232-delegate-timeout-process-tree.md) cleanup contract.
Not dispatch eligible. Detailed architecture and independent review are required
before implementation. No priority promotion; Pillar 4 remains PAUSED.

Independent Terra SIGN-OFF to file, 2026-09-06, under the owner's authorization
to use Terra/DeepSeek while Claude is unavailable. Implementation gates remain UNRUN.

## Evidence and limited inference

Pkg232 landed in PR #705, merge `d997c499`; reviewed source
`32458d64be8ed444df63f3fdbf49339b467702bc` remained unchanged through delivery.
Current canonical `.claude/skills/delegate/scripts/delegate.py` captures HEAD and sorted porcelain
inventory in `_git_snapshot:200`; the final difference near `:525` is
`set(post["dirty_files"]) - set(pre["dirty_files"])`.

Astra imported this read-only helper in a disposable temporary Git repository,
without opencode or live-index mutation. Before/after inventories both contained
`M tracked.txt`; its content SHA256 changed but reported `files_changed`
was empty. Reverting that dirty file to clean also produced an empty difference.
This proves the narrow helper gap, not attribution of all worker changes.

## Bounded scope

Phase 0 defines content-aware before/after evidence and schema compatibility.
Distinguish pre-existing dirty state from observed byte/content changes, including
same-status tracked/staged edits, reverts, existing/new untracked files, deletes,
and renames. Record the limits of observation under concurrent edits.
Pin snapshot cost, size/path limits, unreadable-file, encoding, and symlink
policy before implementation; unavailable evidence must be explicit.
Phase 1 extends the canonical helper and tests using read-only Git/content
operations. Never mutate the live index, stage files, or reset/revert user work.
Phase 2 verifies the evidence matrix and bounded-cost/failure behavior.

## Acceptance — implementation/hardware gates UNRUN

- [ ] Temporary-repository tests cover the complete change matrix, including
      identical porcelain status with different bytes and dirty-to-clean reverts.
- [ ] Tests cover failed/partial/oversized snapshots and the declared cost bound;
      unobservable changes are reported unavailable, never silently clean.
- [ ] Preserve existing JSON consumers or document reviewed schema compatibility;
      results distinguish baseline state from observed content change.
- [ ] Snapshot operations leave the live index and user files unchanged;
      no opencode process is needed for these unit tests.
- [ ] Retain pkg232's confirmed-cleanup gate before final snapshot evidence
      and require independent review before implementation delivery.

## Risks and exclusions

Large trees, binary/untracked files, and partial reads can make snapshots costly
or incomplete. Content differences do not prove which concurrent actor caused
them. Neither worker narrative nor exit code substitutes for evidence.
No pkg247 launch-protocol, pkg232 process-containment, model-routing, or review
policy changes; this is a separate implementation package.
