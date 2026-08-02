# pkg172 — triangle-geometry GPU/CPU transport bias: uniform ~0.6% GPU-bright on triangles, sphere-clean (owns pkg156's 0.995→0.998 restoration)

**Pillar:** 3 (GPU/CPU transport parity)
**Track:** A (RTX-gated)
**Status:** open — dispatchable, FINAL-SCOPED 2026-08-02 (see "Architect verdict + data correction" below). The original triangle premise is FALSIFIED. Of the two-effect decomposition: **(A)** the universal `f/(pdf+1e-3)` epsilon energy loss (~0.628%/bounce, exact `2π·ε`) is CONVICTED and remains this package's sole scope — fix + impact sweep + coordinated re-pin batch, **DEFERRED to a supervised round** (owner action item). **UPDATE 2026-08-03: that supervised engine-settlement round is now SCHEDULED FIRST** (owner directive) — its brief is PR #541 option A (confirmed; see pkg168 Status) + this package's effect (A) + pkg174 (register-pressure recovery). Effect (A) runs in that round, supervised, with the architect signing off the re-pin batch per pin. **(B)** the GPU-only residual is CONVICTED as **(B')** and TRANSFERRED to **pkg173** (bounce-1 geometry-sampling parity — BVH continuation-ray visibility rate + camera-ray surface-distribution throughput, both fixable expectation mismatches, not spectral/transport terms); pkg173 now also holds pkg156's 0.998 restoration clause. Escalation-era diagnosis doc: `.astroray_plan/docs/pkg172-triangle-transport-diagnosis.md` — its three-way table is superseded by the data correction below (stale-.pyd contamination; CPU-mw was never exempt).
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

## Architect verdict + data correction (2026-08-02 — AUTHORITATIVE; supersedes the sections below and the diagnosis doc's three-way table)

**The oracle is the ANALYTIC value, not any integrator.** A 0.5-albedo
Lambertian wall under a unit white env must reflect exactly 0.5; the scene is
zero-variance per sample (cosine-sampled diffuse gives `f·cosθ/pdf = albedo`
exactly), so ANY deterministic deviation is a defect. A deterministic
per-bounce loss cannot be a design convention: RR, MIS termination, and
env-miss handling are unbiased by construction (Veach 1997; PBRT-v4; Cycles
furnace closure) — conventions move variance, not expectation. "Re-pin the
gate against `path_tracer`" (the escalation's branch 2) is REJECTED: two
implementations agreeing on the same defect is not an oracle argument.

**Data correction (implementer, 2026-08-02):** the escalation's "CPU-mw =
0.500 analytic-exact" reading was stale-.pyd contamination — the epsilon probe
source was reverted without a rebuild, so the mw leg was measured on a
probe-modified binary. Clean-build truth: **CPU multiwavelength and CPU
`path_tracer` are BIT-IDENTICAL** ([0.49699, 0.49777, 0.48845]); **no
integrator is exempt.** GPU reads a further ~0.4% below both CPU legs even
with the GPU epsilon zeroed ([0.49486, …]).

### The two effects this package now owns

- **(A) Universal ~0.6%/bounce epsilon loss — CONVICTED.** `f/(pdf+1e-3)` in
  the throughput update hits ALL THREE legs. The analytic prediction for an
  additive pdf epsilon under cosine sampling is a loss of exactly
  `2π·ε = 0.628%` per bounce — confirmed: the `1e-6` probe reads exactly
  0.500. **Fix:** the standard guarded-pdf form (reject/clamp at the sample
  site, pbrt-v4 `DielectricBxDF`/sampling conventions — cite it), never an
  additive denominator epsilon and never just a smaller one. **Consequence
  (ordered at verdict, unchanged by the correction):** the fix brightens
  every diffuse bounce on all legs — the fix PR carries an impact sweep and a
  coordinated re-pin with per-pin justification lines (pkg166 precedent),
  architect sign-off on the batch.
- **(B) GPU-only residual — CONVICTED as (B') and TRANSFERRED to pkg173
  (2026-08-02).** The hunt landed (UPDATE 3, branch `dfa7517`): with #541
  present, the pkg156 residual is dominated by bounce-1 escapes (+11.8%),
  decomposed into a +6% escape-event RATE difference (BVH continuation-ray
  visibility, 6115 vs 5769) and +5.5% throughput-per-escape (camera-ray
  surface distribution) — geometry-sampling expectations, not spectral/
  transport terms; per-surface throughput is bit-matching post-#541.
  Architect fork adjudication: both quantities are EXPECTATIONS that unbiased
  legs must agree on (RNG streams move variance, not expectation; ULP-level
  camera differences cannot make 5.5%), so they are discrete fixable defects
  — ownership moves to **pkg173**
  (`pkg173-bounce1-geometry-sampling-parity.md`), which now also holds
  pkg156's 0.998 restoration clause (with an evidence-gated fallback if both
  scalar parities land and SSIM still falls short). **This package retains
  effect (A) only** — the epsilon fix + impact sweep + coordinated re-pin
  batch.

### Lessons (record now, it already paid for itself)

- The escalation's central "mw is exempt" claim was manufactured by the
  stale-.pyd class the repo rules exist for (memory `stale_pyd_locations`;
  CLAUDE.md build-verification rules): a probe revert WITHOUT rebuild. The
  implementer self-caught it by rebuilding before deep-diving — which is the
  rule working, but only on the second pass. Every probe A/B in this package
  from here on states the `.pyd` mtime for BOTH legs next to the numbers.

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
