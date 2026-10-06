# Next session (written 2026-10-07, checkpoint of the 10-05 → 10-07 long haul)

Read first: `run-report-2026-10-06.md` (gates, merges, lessons), memory `owner-decisions-2026-10-06`, `lane-rules.md`.

## State
Gates:
- (a) GREEN
- (c) GREEN under Welch-1b (#1121)
- (d) GREEN
- (e) no open highs
- (g) RED: CPU 2/8, GPU 1/8, threshold 6/8
- (b) needs a re-freeze
- (f) waits on the owner's second PC

The integration sweep (main + the last PRs) was 4726 passed, 0 failed.

## First jobs
1. **Land the pending PRs** if they are not merged yet: #1105 (Pointiness), #1116 (smooth-glass Fresnel), #1121 (gate (c) Welch). Then rebuild main and record row (c) with the formal command from #1121's body, using a FRESH `--out`.
2. **Rough glass (i16):**
   - Branch `batch-i16/cycles-multiggx-glass`; read `astra_run/batch-i/i16/review-cycles-parity.md`.
   - Read lane i19's M3 result (`astra_run/batch-i/i19/`).
   - If the attribution is confirmed: rebase onto main after #1116, re-run the GPU glass suite plus cuobjdump, and open the PR. State the divergence (Cycles light leak at r ≥ 0.85) in the PR and the research note.
   - Minor review items: film-glass reflect probability, `average(darkening)` sample weight, `rough_glass_walk` ignored on GPU, Ng check. Fix them or document them.
3. **Gate (b) re-freeze** on the owner population (corpus v2 + production). Steps:
   - Produce a new scanner-integration receipt for the merged pkg320 scanner. F7 makes the old receipt fail with "re-review required"; review route: one blind Claude reviewer plus a brief opencode review.
   - Regenerate the artifacts #1113 lists: `nine_scene.json`, `coverage_input_v4.json`, `node_uses_v4.json`, the provisional runner results and sidecars.
   - Score.
4. **Row (g) burn-down:** #1117 (scanner credits Pointiness), then the production materials (`docs/pkg310-production-corpus-burndown.md`).

## Plan-b items left
- pkg321 (DROPPED-row audit)
- pkg323 (gate (b) witnesses; the textures_mapping scene was re-frozen in #1113)
- #875 (100k move < 20 ms; OFF is now 77.7 ms)
- M2 (pkg310 re-measure)

## Follow-ups filed this session
- #1108: Voronoi 3D vs Cycles
- #1112: smooth glass (PR #1116)
- #1117: scanner Pointiness
- #1120: GPU spectral transmission weight fold; blocks the pkg188 coat row
- Disney delta-glass Schlick: same pattern as #1112; not filed yet
- Row (d) committed `evidence_path` uses Windows separators, so it fails `validate_manifest` on Linux; not filed yet
- ReSTIR leaves `c_wfTransparentLimit` stale; not filed yet

## Rules that bit this session
- **GPU results are test-order dependent.** Bisect with IDENTICAL test selections, and run the failing test alone first.
- **CI has no GPU.** Before declaring clean, merge pending device PRs into an integration branch, build it, and run the full CPU+GPU sweep (~52 min).
- **Codex is out until 2026-11-04.** Reviews are blind Claude plus opencode (`delegate --tier verify --agent critic`).
