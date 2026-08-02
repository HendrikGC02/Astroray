# pkg172 — triangle-geometry GPU/CPU transport bias: uniform ~0.6% GPU-bright on triangles, sphere-clean (owns pkg156's 0.995→0.998 restoration)

**Pillar:** 3 (GPU/CPU transport parity)
**Track:** A (RTX-gated)
**Status:** ESCALATED to architect (diagnosis done, no fix, 2026-08-02) — the spec premise is FALSIFIED: the bias is NOT triangle-specific (sphere == triangle == 0.9957 single-bounce) and candidates (a)/(b)/(c) are all CLEARED (epsilon probe negative; achromatic, geometry- & depth-independent). Three-way cross-check: **GPU wavefront AGREES with the canonical CPU `path_tracer` (ratio 1.002); the pkg156 ORACLE (CPU `multiwavelength_path_tracer`) is the ~0.6%/bounce OUTLIER** and is the one matching the energy-conserving analytic. This is a design fork (fix CPU-mw's energy vs fix path_tracer+GPU vs change the gate oracle) requiring owner direction — not a single convicted line. **pkg156 stays at 0.995; NOT re-pinned.** Full decomposition: .astroray_plan/docs/pkg172-triangle-transport-diagnosis.md.
**Estimated effort:** S (diagnosis — the discriminators are already established and the minimal scene is one triangle) + S for the fix once convicted
**Depends on:** PR #541 (pkg168 Step 2) merged — the sphere-clean baseline this spec's discriminator rests on. Cross-links: **pkg156** (its 0.998 restoration is BLOCKED-ON this package; pointer updated 2026-08-02), **pkg168** (charter complete — exonerated the tables in Step 1, fixed the call-structure shape divergence in Step 2; THIS residual is the third mechanism its decomposition exposed), **pkg153** (sibling family, ownership separate — see Scope fence).

**Origin:** pkg168 Step 2 (PR #541 round, 2026-08-02). Evidence:
`.astroray_plan/docs/pkg168-upsampling-parity-step2.md`. After #541's fix
(GPU shaded via `upsample(albedo·cosθ/π)` where CPU does
`upsample(albedo)·cosθ/π` — JH upsampling is nonlinear in magnitude, so the
spectrum SHAPES diverged chroma-dependently; now <0.02%, sphere-isolated
per-channel ratios exactly 1.000), the pkg156 gate is UNCHANGED at 0.9955
because its scene is dominated by a third, geometry-linked mechanism.

---

## The established discriminators (do not re-derive; start from these)

1. **Sphere-clean, triangle-dirty.** The SAME diffuse material reads
   per-channel ratios exactly 1.000 sphere-isolated (post-#541) but diverges
   on triangle geometry. The material/spectral stack is exonerated; the bias
   is in triangle-path transport.
2. **Uniform, achromatic, single-bounce, background-independent.** A neutral
   floor diverges UNIFORMLY ~0.6% GPU-bright with NO channel asymmetry, at
   single bounce, independent of background. This cleanly separates it from
   the chromatic upsampling family (pkg168/pkg163) and gives the acceptance
   signature: whatever is convicted must produce a flat, colorless, per-hit
   multiplicative offset.

## Candidate causes (implementer-named; the diagnosis must distinguish, not assume)

- **(a) Triangle shading-vs-geometric normal handling** — CPU and GPU picking
  different normals (or normalizing differently) for the cosine term on
  flat-shaded triangles. Prediction: bias varies with triangle orientation
  relative to the light; a tilted-triangle sweep separates it.
- **(b) cosθ normalization on triangles** — a missing/extra normalization in
  one leg's triangle shading path. Prediction: angle-dependent, orientation
  sweep also separates it from (c).
- **(c) the `f/(pdf + 1e-3)` epsilon** — an epsilon of 1e-3 against a pdf of
  O(1) is an O(0.1%) systematic UNDER-weighting wherever it appears; if one
  leg carries it and the other doesn't (or pdf magnitudes differ), a flat
  sub-percent bias is exactly the expected signature, and it is
  geometry-linked if the triangle path's pdf differs from the sphere path's.
  Prediction: bias scales inversely with pdf magnitude — vary light solid
  angle / sampling density and watch the bias move. **Cheapest decisive test:
  rebuild with the epsilon at 1e-6 in a scratch tree and re-measure; if the
  0.6% collapses, convicted.**

## Diagnosis contract

1. **Minimal scene:** ONE triangle, neutral albedo, single light,
   single-bounce, linear output — measure the bias in isolation on a recorded
   SHA. Then the orientation sweep (separates a/b) and the epsilon/pdf sweep
   (convicts or clears c). The three candidates make different, cheap,
   mutually exclusive predictions — run all three probes before touching code.
2. **Convict ONE mechanism** (or decompose further with numbers — pkg156's
   history says residuals here come in layers; do not force one cause).
3. **Fix mirrored CPU/GPU with citation** (CLAUDE.md §6): normal-handling per
   the existing repo convention (rec.frontFace discipline — memory
   `refraction-frontface-bug` for the class); if the epsilon is convicted, the
   fix is the standard guarded-pdf form (pbrt-v4's approach: reject/clamp at
   the sample site, never bias every estimate) — cite it, don't invent a new
   guard.
4. **Definition of done — this package owns the pkg156 restoration:**
   `test_visible_band_cpu_gpu_ssim` back to **0.998 measured in the fix PR**
   (depth-4 per-channel ratio within ±0.5% on the pkg156 scene). If 0.998 is
   still unreachable, escalate to the architect with the next-level
   decomposition — the gate does not re-pin below 0.998 a second time without
   an owner.

## Scope fence

- **pkg153 stays separate.** Same broad family (deterministic GPU/CPU ratio
  offsets), but pkg153's R-drift is CHROMATIC and emitter-linked — the
  opposite discriminator signature. Report this fix's effect on the
  quarantined pkg153 ratios as bisect intel; do not take ownership.
- Not the upsampling stack (pkg168 complete; pkg163 class rule stands).
- No SSIM/band re-pins other than the 0.998 restoration named above.

## Provenance

Filed by the architect 2026-08-02 at team-lead request from pkg168 Step 2's
residual decomposition (PR #541). Third mechanism in the pkg156 residual
stack: (1) pkg120's unconditional two-sided term (fixed #537), (2) the
upsample-argument shape divergence (fixed #541), (3) this triangle-geometry
bias. pkg156's BLOCKED-ON pointer now targets this package.
