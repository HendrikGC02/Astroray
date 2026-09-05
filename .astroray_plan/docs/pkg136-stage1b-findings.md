# pkg136 Stage-1B findings — CPU path-guiding integration: correct, not yet a win

Stage 1B wired the SD-tree guide into `pathTraceSpectral` (raytracer.h). The
integration is **correct** — unbiased, byte-identical when off, sample/pdf
consistent, and the guide provably concentrates toward incident radiance — but
**basic radiance guiding does not yet beat BSDF sampling** on the scenes tried
(≈break-even on smooth scenes, worse on firefly-heavy ones). This note records
what was built, what was verified, the mechanisms behind the non-win, and the
concrete path to a real ≥2× variance reduction. It is the honest state so the
follow-up starts with the diagnosis in hand rather than re-deriving it.

## What is correct and verified

- **Unbiased.** Guided render converges to the unguided image (per-channel
  mean-ratio within noise). Gate: `test_pkg136_guiding_render.py`.
- **No-harm-when-off.** `guiding=off` is byte-identical (every hook gated on
  `guidingEnabled_`). Gate: same file.
- **Sample/pdf consistent.** `DTree::sample()` returns exactly `DTree::pdf()`
  (ratio 1.0) and `E[1/pdf]` over samples equals the support area (=1 for a
  full-support tree; <1 for a peaked one — this is expected, not a bug; an early
  misread of this invariant sent me chasing a phantom sample/pdf bug that did not
  exist). The directional sampler was rewritten to a proper 2D hierarchical warp
  (u2→row, u1→column, each rescaled) — the textbook method; the prior flattened
  4-way warp was equivalent but less clearly correct.
- **The guide concentrates correctly.** The `guide_probe` API (sample the trained
  guide at a world point, report mean direction + concentration + pdf toward a
  target) shows, e.g., a back-wall point's guide pointing into the room (conc
  0.69) and a floor point under a side-door pointing at the door (conc up to
  1.0). The machinery learns the incident-radiance field as designed.

## Why it does not (yet) beat BSDF — the mechanisms

1. **Diffuse-box indirect is near-isotropic.** In a closed diffuse room the
   dominant indirect radiance arrives from the large lit walls over a wide solid
   angle; cosine sampling is already near-optimal there, so a directional guide
   cannot improve it and a mis-concentrated one hurts. Path guiding needs
   *directional, hard-to-find* indirect light.
2. **NEE already handles direct light well; the guide competes with it and
   loses variance.** The guide learns *incident radiance*, which includes the
   direct light. When it over-concentrates (conc→1.0) its pdf toward the light
   becomes huge, so the balance-heuristic MIS cedes the light to the
   guided-continuation strategy and suppresses NEE (`wt≈0`). But hitting a small
   light via a continuation ray is *higher* variance than NEE's direct
   connection — so ceding to the guide raises variance. The balance heuristic
   misweights because the guide's per-sample variance for the light is worse than
   its pdf implies.
3. **Fireflies are not guide-addressable.** On bright-light scenes the variance
   is dominated by high-throughput emitter/NEE spikes; guiding the continuation
   direction cannot reduce that and can worsen it by steering more rays at the
   bright source.

Empirically: smooth indirect scenes gave ~0.9–1.1× (break-even) at low α;
firefly/bright scenes gave 0.2–0.8× (worse), worse with higher α — the signature
of (2)+(3), not a code defect.

## The path to a real ≥2× (Stage-1B continuation)

In rough priority order — these are the 2017 paper's robustness + the 2019 course
improvements that basic radiance guiding omits:

1. **Product guiding** (sample ∝ `f·cosθ·L_i`, not `L_i`). Cures both the
   isotropic-diffuse non-win and much of the NEE-competition misweighting, because
   the guide then targets the actual integrand. Needs the BSDF evaluated at
   guide-build time or a cosine-product approximation.
2. **Filtered splatting** (2019 course, box-filter each splat across neighbouring
   spatial/directional cells). Denoises the guide so it is smooth rather than a
   near-delta — directly fixes the over-concentration in mechanism (2).
3. **Guide/NEE MIS that respects each strategy's true variance**, or simply
   restrict guiding to the *indirect* continuation (bounce ≥1) and leave NEE to
   own direct light. The simplest robust step: cap the directional-quadtree depth
   so the guide can never become a near-delta that dwarfs NEE.
4. **Inverse-variance iteration combination** (2019 course) for the training
   image, and a proper **doubling sample budget** per iteration (currently a
   constant per-iteration budget).
5. **A guiding-favourable benchmark scene**: a true Veach-door where the
   camera-visible surfaces are lit by *smooth, strongly directional* indirect
   light through a moderate aperture, with the emitter neither directly visible
   nor easily NEE-connectable, and modest intensity (no fireflies). The scenes in
   this investigation were each missing one of these (emission-dominated, too
   isotropic, or firefly-heavy).

## Tunable knobs shipped (for the follow-up, all runtime)

`set_guiding_params(iterations, train_spp, alpha, spatial_frac, dir_rho,
div_pdf, value_clamp)` and `guide_probe(...)` / `get_guide_debug()` — so the
continuation work can sweep and diagnose without rebuilds. `div_pdf` toggles
radiance (`L_i/pdf`) vs product-ish (`L_i`) splatting; both are implemented.
