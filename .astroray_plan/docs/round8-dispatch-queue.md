# Round 8 dispatch queue — next-session pickup

**Updated:** 2026-05-14 after owner answered the open questions list at session close.

## Owner-confirmed direction

- **Round 8 closure can slip pkg55-B to Round 9** if needed. Visible work per engineering week beats forcing pkg55-B prioritization.
- **External writes** under user identity (PR comments) — current "authorize in dispatch brief, agent acts" model is fine. No change.
- **Parallelism cap:** max 3 concurrent implementation agents; unlimited doc-only agents. Worktree-verification preamble required in every implementer brief.

## pkg-by-pkg owner answers

- **pkg43:** worktree version is canonical (handle-based, caller-supplied lambdas). Picks up next session per the handoff doc.
- **pkg55-B Phase B' implementation:** dispatch next session (the spec amendment is now authoritative on main at fa896ff).
- **pkg64-gpu:** my call on timing — see "Recommended ordering" below.
- **pkg85 partial fix:** merged. Full CUDA-call audit filed as follow-up (pkg85-B); see "Follow-up packages to file" below.
- **pkg86 Light Tree:** needs pkg89's `Light::orientationCone()` + `Light::power()` accessors per the pkg89 research note. Pick up AFTER pkg89 Phase A.
- **pkg87 Cryptomatte:** independent; can pick up any time.
- **pkg88 motion blur:** DRAFT spec; design questions deferred per owner ("get to that later").
- **pkg89 dedicated lights:** 4 blocking design Qs answered → promote DRAFT to real spec:
  - Q1: `std::variant<PointLight, ...>` tagged union (Cycles-style — better Blender integration)
  - Q6: extend `LightSample.emission_spec` (don't replace; ReSTIR depends on the RGB field)
  - Q7: staged signature break across 5 integrators (one integrator at a time)
  - Q11: implementer's judgment on the `normalize` flag (Cycles-parity per default)

## Recommended ordering

**Session 1 (next) — parallel-safe, 3 implementers + N doc agents:**

| Track | Type | Notes |
|---|---|---|
| pkg43 finish | implementer (CUDA build) | Worktree exists; handoff doc lists exact next steps. Static-init registration debug is the blocker. |
| pkg55-B Phase B' Session 2 | implementer (CPU-only) | Spec is now authoritative on main. Brief should quote the 8 design decisions verbatim. Worktree `pkg55-restart` already exists. |
| pkg89 spec promotion → Phase A | doc + implementer | Promote DRAFT to real spec with the 4 Q answers; then start Phase A (Light interface + 5 type stubs, no rewiring yet). |
| pkg85-B (full CUDA-call audit) spec filing | doc | File the follow-up spec capturing what the pkg85 partial fix didn't catch. Multi-day implementation later. |

**Session 2 — assumes Session 1 lands:**

| Track | Type | Notes |
|---|---|---|
| pkg44 ADAF | implementer | After pkg43 lands; same VolumetricEmission interface, same handle-based API. |
| pkg89 Phase A continued | implementer | Light types + emission interface + addon wiring. |
| pkg87 Cryptomatte implementation | implementer | Spec on main; independent. |
| pkg64-gpu Phase 1 | implementer (CUDA) | Megakernel target. Acknowledged that pkg55-C will eventually re-port. Worth shipping because pkg55-C is many sessions away. |

**Session 3+ — depends on earlier:**

| Track | Notes |
|---|---|
| pkg86 Light Tree | After pkg89 Phase A ships `Light::orientationCone()` + `Light::power()` |
| pkg55-B Phase B' Session 3+ | Continued CPU wavefront + diff harness expansion |
| pkg85-B full audit | When prioritized |

## Follow-up packages to file (small, file when next-session has bandwidth)

1. **pkg85-B — Full CUDA-call audit.** Audit every CUDA API call in `src/gpu/` and `src/cpu/` (if it ever calls CUDA), ensure each is wrapped in `CUDA_CHECK()` or followed by `cudaGetLastError()`. Estimated multi-day. The pkg85 partial fix (now merged) caught the highest-impact site; this is the systematic pass.
2. **test_disney_clearcoat_adds_gloss variance investigation.** Owner notes "always been flakey; clearcoat may not be working well; needs its own investigation". Similar to pkg82 (variance characterization) — file as a pkg85-style measurement/triage spec.

## Hygiene

- Safety branch + stash dropped at session close — clean state.
- pkg85 worktree had a file-permission lock at session close; will resolve on next session start. Run `git worktree remove .claude/worktrees/pkg85 --force` then `git worktree prune` early next session.
- No outstanding PR review backlog at session close.

## Memory updates from this session

- `cuda_verifier_concurrency.md` — corrected after the original hypothesis was refuted; the real cause is test-harness CUDA state leak in long pytest runs.
- `parallel_agent_worktree_contamination.md` — describes the multi-agent worktree-state failure mode; updated with the 3-implementer cap + worktree-verification preamble owner approved.
