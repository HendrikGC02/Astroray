# Astroray Next Stage Report

**Date:** 2026-05-29 (Round 15 Wave 3 — pkg106 DONE; next = general caustics)
**Prepared by:** Claude (Anthropic Code) — rewritten after the pkg106 forward-light-tracer finish (PR #393).
**Scope:** post-pkg106 next stage.

> Strategic gate: **RELEASED 2026-05-10** by pkg56 Phase C. Strategy in
> [`ROADMAP.md`](ROADMAP.md), full status in [`STATUS.md`](STATUS.md) (Round 15
> Wave 3 section is authoritative for the current state).

> ⚠️ This file was rewritten 2026-05-29. The previous version's "pkg106 Chunk
> D-radiance / wire-MNEE-into-the-integrator" lead track and drop-in prompt are
> **ABANDONED** — pkg106 shipped via a *forward light-tracer*, not camera-side
> MNEE. Do NOT resurrect that work.

---

## 1. Current state (one screen)

- **pkg106 DONE (PR #393 / `6e6fd74`):** a triangulated equilateral BK7 prism
  throws a clean continuous rainbow caustic — `hue_spread` 0.754 (≥0.7),
  `bright_coverage` 0.88 (continuity). New integrator
  `plugins/integrators/light_tracer_caustic.cpp` (forward light-tracing: Arvo
  1986 / Jensen 1996). The Cycles-`mnee.h` MNEE transfer-matrix geometry term was
  ported + FD-validated and is KEPT (`include/astroray/manifold/`) for focusing
  casters, but camera-side MNEE is unsuitable for a flat prism (salt-and-pepper;
  see `pkg106-forward-lighttracing-research.md`).
- **No open PRs.** The PR queue is empty.
- **The caustic feature is NOT general yet.** The light-tracer is prism-specific
  (2-face refraction, horizontal floor receiver, flagged triangle casters, distant
  sun, dedicated integrator). "Drop ANY glass + light → caustics on ANY surface,
  through the default path" is the general-caustics chain in §2.
- **Blocked / not-overnight:** pkg64-gpu multi-IOR, pkg55-B' CUDA sessions, pkg86-B
  GPU light tree — all need RTX hardware-verified gates (CI has NO GPU).

---

## 2. Deployable set (prioritized)

Ordered by value × overnight-shippability. CI is **Linux/CPU only** — pick CPU
work whose correctness can be gated without a GPU.

1. **pkg109 — photon-map kd-tree core** (S/M, cite: Jensen 1996). Replace the
   light-tracer's 2D floor grid with a world-space kd-tree photon store; reproduce
   the prism band (regression). FOUNDATION of general caustics.
2. **pkg110 — BSDF-driven photon bounce** (M, cite: Jensen 1996). Photon loop via
   `Material::sampleSpectral`+`iorAt` → any glass / TIR / multi-bounce; new
   glass-sphere caustic gate. Depends on pkg109.
3. **pkg111 — k-NN gather on any receiver, into the default path** (M). Removes the
   horizontal-floor restriction; caustics on the default `path_tracer`. Ships a
   `prism-tilted-receiver` red test first. Depends on pkg109+pkg110.
4. **pkg101 / pkg102 / pkg100** (S each, no research) — addon viewport vfov, HDRI/DOF
   aperture units, .blend importer camera intrinsics. Branches exist on origin;
   re-verify vs current main, finish, merge. Independent — parallelizable.
5. **Integrator float-param ergonomics** (S) — `set_integrator_param` is int-only;
   `light_tracer_caustic.cpp:58-60` flags `caustic_boost` as an int×0.1 hack. Add a
   float route + test.
6. **pkg76 Classroom Gap 2** (M, partial) — non-Principled shader-graph walk; land
   the importer code + bpy-free unit tests (defer the GPU SSIM gate).

NOT overnight: pkg64-gpu multi-IOR, pkg55-B' sessions, pkg86-B, SPPM-progressive
(pkg112, large), VCM (owner decision).

---

## 3. Drop-in prompt for the next session

The authoritative overnight instructions live with the owner (the "overnight
ship-packages" prompt). In short: **work the §2 set top-down, one mergeable PR per
package, CPU-only, full local test + stale-call-site sweep before each push, poll
CI then `gh pr merge --squash --delete-branch`.** Start the general-caustics chain
at pkg109 (it gates pkg110→pkg111); run the small fixes (pkg100/101/102, float
params) in parallel. Cite papers per CLAUDE.md §6 for any new algorithm
(`/cite-algorithm`). Do NOT touch GPU-gated packages (no GPU in CI). Specs:
`.astroray_plan/packages/pkg109-*.md`, `pkg110-*.md`, `pkg111-*.md`.
