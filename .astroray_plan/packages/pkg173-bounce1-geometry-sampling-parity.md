# pkg173 — bounce-1 geometry-sampling parity: GPU escape-event RATE +6% and throughput-per-escape +5.5% vs CPU (owns pkg156's 0.998 clause, transferred from pkg172)

**Pillar:** 3 (GPU/CPU transport parity)
**Track:** A (RTX-gated; the counters are cheap instrumentation both legs)
**Status:** superseded — bounce-1 +6% escape-rate parity sits below the Integration Milestone; reopen only if a paper needs bit-level CPU/GPU parity (2026-09-07 backlog triage)
**Estimated effort:** S–M (the counter harness already exists from pkg172's UPDATE-3 trace; the work is convicting two discrete causes and fixing them mirrored)
**Depends on:** PR #541 (pkg168 Step 2). Parent: **pkg172** (this spec owns its effect-(B') decomposition; pkg172 retains effect (A), the epsilon fix + re-pin batch). Cross-links: **pkg156** (BLOCKED-ON pointer moves here), pkg55 PostInit ≤4-ULP acceptance (NOT implicated — see Scope rationale), memory `ssim-wrong-gate-for-independent-rng` (why the CONDITIONAL fallback below is shaped the way it is).

**Origin:** pkg172 (B') conviction (2026-08-02, branch `dfa7517`, trace table in
`.astroray_plan/docs/pkg172-triangle-transport-diagnosis.md` UPDATE 3). With
#541 present, the pkg156 room residual is dominated by bounce-1 escapes
(+11.8%), decomposed into: **(i)** GPU records ~6% MORE bounce-1-escape events
(6115 vs 5769 — BVH continuation-ray visibility); **(ii)** ~5.5% higher
throughput-per-escape (camera rays land on a brighter surface distribution).
Persists at 8192 spp. Per-surface throughput is bit-matching post-#541 — the
divergence is purely which-surface/whether-hit.

---

## Scope rationale (architect adjudication of the pkg172 fork — why this is neither "broad BVH parity package" nor "re-baseline the target")

**The two measured quantities are EXPECTATIONS, and unbiased legs must agree
on expectations.** Independent RNG streams (mt19937 vs PCG32) change *which*
rays escape and raise the spp needed for image-space agreement (that is the
`ssim-wrong-gate-for-independent-rng` lesson) — they cannot change *how many*
rays escape in expectation, nor the mean throughput per escape. At 8192 spp
the MC error on a ~6000-event counter is ~1%; the observed 6% is systematic.
Likewise the pkg55 stage_init camera simplification was accepted at ≤4 ULP —
ULP-level ray perturbations cannot produce a 5.5% surface-distribution shift
outside silhouette-measure pixels. **Neither accepted design decision is
implicated; both observed gaps must have discrete, fixable causes.**
Re-baselining pkg156's target now would enshrine a 6% visibility bias as
"irreducible" — the same trap as the rejected branch-2 of the previous pkg172
fork (declaring a measured gap a convention because two things agree on it).

A same-stream comparison is APPROVED as a *diagnostic* (it isolates
stream-independent bias beautifully) and REJECTED as the shipping gate (it
would permanently mask exactly this class of visibility bias).

## The two scalar parities (each an expectation; each gets its own conviction)

1. **Escape-event rate (i).** Counter: bounce-1 escape events / camera
   samples, both legs, fixed scene, 8192 spp, `.pyd` mtimes stated (pkg172
   Lessons rule). Suspects, in order of prior: continuation-ray origin offset
   (self-intersection epsilon / normal-offset convention differing between
   `stage_advance`'s continuation rays and the CPU's), `t_min`/`t_max`
   conventions, BVH traversal epsilon or watertightness difference
   (CPU BVH vs GPU TLAS path). Conviction method: for a sample of
   discordant rays (GPU-escape but CPU-hit), dump origin/direction/t of the
   continuation ray on both legs — the first differing field names the
   convention. Fix mirrored; cite the existing repo convention rather than
   inventing a new epsilon (CLAUDE.md §6; watertight traversal reference:
   Woop, Benthin & Wald 2013 if traversal is implicated).
2. **Throughput-per-escape / camera-ray surface distribution (ii).** Suspects:
   pixel filter parity (box vs tent — a filter difference changes per-pixel
   expectations near edges), subpixel jitter DISTRIBUTION (not stream: e.g.
   stratified vs uniform), camera-ray generation differences beyond the
   accepted ULP simplification. Conviction: per-surface camera-hit histograms
   both legs at high spp — the surface whose hit-share differs most, cross-
   referenced against filter/jitter code diff. Fix mirrored.

## Definition of done — and the CONDITIONAL fallback (the (b)-branch, demoted to evidence-gated)

- Both scalar expectations converge: escape-rate ratio and
  throughput-per-escape ratio GPU/CPU within **±1% each** at 8192 spp
  (statistically indistinguishable at that budget), fixes mirrored and cited.
- **pkg156's 0.998 restoration clause lives HERE now:** after both parities
  land, re-measure `test_visible_band_cpu_gpu_ssim` at its pinned spp.
  Predicted outcome: 0.998 is reachable and the gate is restored (measured,
  in the fix PR).
- **Fallback, only with evidence:** if BOTH scalar parities are in-band and
  the SSIM still cannot reach 0.998 at pinned spp, the remaining gap is
  demonstrated (not assumed) stream-variance — THEN the gate's aspiration
  converts to the decomposed acceptance: 0.995 SSIM standing pin +
  per-surface throughput bit-match (post-#541) + both scalar-expectation
  parities as first-class gates. That conversion is an architect sign-off
  item recorded in pkg156, not an implementer call. This ordering exists so
  the aspiration is only lowered AFTER the bias is gone, never instead of
  removing it.

## Non-goals

- pkg172's effect (A) (the epsilon fix + coordinated re-pin batch — stays in
  pkg172).
- Unifying the RNG streams (mt19937 vs PCG32 stay independent; same-stream
  runs are diagnostic-only).
- Re-opening the pkg55 PostInit ULP acceptance (not implicated).
- pkg153's chromatic/emitter-linked drift (opposite discriminator signature;
  report effects as intel only).

## Provenance

Filed by the architect 2026-08-02, adjudicating the pkg172 (B') fork as
hybrid (c): narrow two-scalar parity package instead of (a)'s broad
sampler/BVH program, with (b)'s re-baseline demoted to an evidence-gated
fallback. Statistical basis: expectations of unbiased estimators are
RNG-stream-independent; 6%/5.5% systematic offsets at 8192 spp are defects
with discrete causes, not irreducible stream noise.

## Progress

- 2026-09-07 backlog triage: status flipped to `superseded`. Previous status text: open — dispatchable after PR #541 merges (its fix is the floor this package measures on; #541 disposition now settled: option A confirmed by the owner 2026-08-03, lands in the supervised settlement round — see pkg168 Status). **PRIORITY DOWNGRADED 2026-08-03 (owner-endorsed):** this is sub-percent parity tail; it is explicitly DE-PRIORITIZED below the Integration Milestone (pkg175/pkg176/pkg177 + pkg119-B/C) and is NOT part of the settlement round. It re-enters the queue after the milestone, or earlier ONLY if the paper turns out to require bit-level parity.
