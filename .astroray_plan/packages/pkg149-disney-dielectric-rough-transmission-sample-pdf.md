# pkg149 — Disney dielectric rough-TRANSMISSION lobe: sample()/pdf() re-derivation (owns the glass[0.3-45] chi² un-xfail)

**Pillar:** 3 (BSDF correctness / MIS density consistency)
**Track:** A
**Codex-paste-ready:** no (sampling-math re-derivation with a chi² + furnace + CPU/GPU parity validation loop)
**Status:** HELD — root-cause fix COMPLETE in worktree `Astroray-pkg149` (local commit `670e583`, deliberately NOT pushed, no PR); **ships stacked on pkg151** (rough-transmission multi-scatter energy compensation). See ✅ ADJUDICATION below. **SCHEDULED: Lane A of the 2026-07-24 overnight run, slot 2** — once pkg151's compensation is green, rebase/stack `670e583` on it and ship the pair as one PR chain (one implementer owns both; the stacking note here substitutes for "open — dispatchable"). Do NOT rebase or push the branch while a hardware-verifier is mid-run on it (memory `hw-verify-branch-freeze`).

> **✅ ADJUDICATION (2026-07-24 ~04:30, architect — overnight last-call ~06:15): Option 1 — HOLD tonight; pkg151 filed; pkg149+pkg151 stack heads the day queue.**
>
> **What the implementer found (accepted as the true root cause):** `sampleGgxVNDF` transcribed pbrt-v4's `Lerp(t, a, b)` disk-warp with two arguments SWAPPED, biasing every sampled half-vector to the azimuth opposite `wo`. Fix measured: transmission sample/pdf peak offset **15.7° → 0.7°** (gate <2°, N=181k); chi² glass[0.3-45] **143,140,779 → 34,988** (~4092×, still red, xfail honestly kept); side effect: pkg150's reflection-candidate masking improves **100% → ~5–22% acceptance** without touching pkg150 scope. Citations pbrt-v4 `scattering.h`/`math.h` (Apache-2.0). This is exactly the class predicted by the spec ("half-vector sign/normalization ... inconsistent between the two functions").
>
> **Why HOLD, not ship (option 3 rejected):** the corrected sampler regresses the rough-glass furnace **0.94–1.0 → 0.09–0.82**. This spec's gates call the furnace **non-negotiable**, and 0.09 means visibly dark rough glass — it would fail the HW visual gate and poison the morning report with a visible regression dressed as a correctness win. The broken sampler was evidently **masking a missing rough-transmission multi-scatter/energy-compensation term** (single-scatter estimator median matches `G1(wi)/ior²` theory almost exactly; three alternative hypotheses ruled out by rebuild-and-measure — full trail in `.astroray_plan/docs/pkg149-disney-rough-transmission-research.md`, worktree). Shipping a correct sampler without the compensation term trades an invisible density bug for a visible energy bug.
>
> **Why not scope-expand tonight (option 2 rejected for tonight, ADOPTED for the day queue):** ~04:20 vs ~06:15 last-call — a compensation-table derivation + furnace re-gate is a multi-hour loop. For the **day queue** this is the recommended path: **pkg151 first (or jointly), then pkg149 rebases/stacks on it, and one PR chain ships peak-alignment + furnace-green together.** The un-xfail of chi² glass[0.3-45] stays owned by this package and may only flip when BOTH alignment and furnace gates are green.
>
> **Critical supersession note (recorded in pkg151):** pkg118's Part-B conclusion "Kulla-Conty multi-scatter for transmission correctly REJECTED" was measured **with the azimuth-swapped sampler** — that rejection is confounded and must be re-measured on the corrected sampler. Do not cite pkg118 Part B as evidence against pkg151's compensation term.
>
> **Worktree/commit `670e583` stays in place for the day team.** Do not delete `Astroray-pkg149`.
**Estimated effort:** M
**Depends on:** pkg138/PR #517 merged (the eval() reflection fix + re-xfailed chi² gate this package inherits). Coordinate with **pkg150** (reflection-candidate masking, same gate's secondary term) and **pkg124** (VNDF, opaque lobe) — all edit `disney.cpp`; serialize merges.

**Origin:** pkg138/PR #517 adjudication (2026-07-23). Measured there: at chi²
glass[0.3-45] the rough transmission lobe carries **~92–96% of sampled weight**
and has a **~16–18° sample/pdf peak mismatch** — `pdf()` peaks at 152° (per
Snell), `sample()` peaks at 168–170°. Transmission was an explicit pkg138
Non-goal; the defect dominates the chi² statistic, so **this package owns
un-xfailing the glass[0.3-45] chi² gate** (with pkg150 as the secondary
contributor — neither closes while the gate is xfail; memory
`xfail-gated-features-must-unxfail`).

---

## Defect

Sampled transmission directions and the reported transmission pdf disagree in
*shape*: a stable ~16–18° angular offset between the sampled-direction density
peak and the pdf's predicted peak. This is a wrong-construction bug (half-vector
/ refraction mapping or its Jacobian), not a tolerance issue — the same class as
pkg138's delta-vs-continuous mismatch, on the other lobe.

## Canonical references (cite in code; CLAUDE.md §6)

- **Walter et al. 2007, "Microfacet Models for Refraction through Rough
  Surfaces," EGSR 2007** — §5.2 sampling (sample the microfacet normal from
  D, refract through it via eq. 40's half-vector convention
  `h_t = −(η_i·ω_i + η_o·ω_o)` normalized) and **eq. 17/38 Jacobian**
  `‖dω_h/dω_o‖ = η_o²·|ω_o·h| / (η_i(ω_i·h) + η_o(ω_o·h))²` — the pdf MUST be
  D(h)·(visible-normal or plain-D weighting, matching the sampler)·this
  Jacobian. A peak offset like 152° vs 168° is the classic symptom of the
  half-vector sign/normalization or the Jacobian denominator being inconsistent
  between the two functions.
- **pbrt-v4 `DielectricBxDF::Sample_f` / `PDF` refraction branches**
  (`src/pbrt/bxdfs.cpp`, Apache-2.0, github.com/mmp/pbrt-v4) — the reference
  implementation pairing `Refract()` through the sampled microfacet normal with
  the matching `dwm/dwi` denominator `Sqr(Dot(wi, wm) + Dot(wo, wm)/eta)`.
  License verified Apache-2.0 (pbrt-v4 repo LICENSE.txt); mirror with
  attribution.
- Implementer's measurement record: `pkg138-disney-dielectric-rough-reflection-research.md`
  (landed with PR #517) — contains the peak-mismatch evidence and N≥100k
  histograms.

## Fix contract

1. Re-derive `sample()`'s transmission construction and `pdf()`'s transmission
   term **from the same half-vector convention and the same Jacobian**
   (Walter eq. 40 + eq. 17/38, or the pbrt-v4 equivalent) — one derivation,
   two call sites; no independent re-tuning of either side.
2. Mirror on the GPU dielectric/closure-graph path (memory
   `gpu-dielectric-lowers-to-closure-graph`); RTX parity gate.
3. Do NOT touch the reflection candidate's same-hemisphere masking — that is
   pkg150; keep the diffs disjoint so the two chi² contributions stay
   attributable.

## Gates

- **chi² glass[0.3-45] un-xfailed and green** (run with `--runxfail` first;
  never accept XFAIL as evidence). If pkg150 has not landed, quantify the
  residual reflection-masking contribution and show transmission's term is
  fixed (peak alignment <2°, N≥100k); the un-xfail may then be joint with
  pkg150 — state which PR flips it.
- Sampled-vs-pdf transmission peak alignment demonstrated (histogram overlay,
  before/after — the 152°-vs-168° figure goes green).
- **Furnace/white-furnace + rough-glass furnace unchanged**; glass caustic +
  prism refbank scenes visually verified (memory
  `general-photon-loop-needs-solid-glass`).
- CPU==GPU parity on a rough-glass render (per-channel mean-ratio band).
- Build evidence per CLAUDE.md (`.pyd` mtime, canonical path).

## Non-goals

- Reflection-candidate masking compensation (pkg150).
- VNDF swap for the opaque specular lobe (pkg124).
