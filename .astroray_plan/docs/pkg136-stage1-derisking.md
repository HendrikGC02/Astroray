# pkg136 Stage-1 de-risking note — SD-tree path guiding core validated

Numpy-prototype de-risking pass for pkg136 Stage 1 (CPU SD-tree path guiding),
same discipline as the pkg227 2b prototypes: validate the core algorithm and
surface the implementation gotchas BEFORE the C++ port. Prototype:
`scratchpad/proto_sdtree.py` (session scratchpad — the algorithm is captured
below so it survives).

Source (CLAUDE.md §6; builds on the web-verified research note
`pkg136-svo-path-guiding-research.md`, no new algorithm): Müller, Gross, Novák
2017, "Practical Path Guiding for Efficient Light-Transport Simulation", CGF
36(4) (EGSR 2017), DOI 10.1111/cgf.13227. SD-tree = spatial binary tree +
per-leaf directional quadtree over an equal-area 2D direction map; learn-then-
sample iterations, radiance splatting, MIS with the BSDF. OpenPGL (Apache-2.0)
structural reference; clean-room from the paper.

---

## What was tested

The directional-quadtree half of the SD-tree (the algorithmic risk; the spatial
binary tree is bookkeeping around it) on a single shade point:
- **Integrand** `I = ∫_hemisphere f(ω)·Li(ω) dω`, the hard-transport regime:
  `f` = diffuse cosine lobe about +z (broad); `Li` = a bright, NARROW incident
  spike at a low-cosθ direction the BSDF lobe mostly misses.
- **Compared** the MC variance of (A) BSDF (cosine) sampling, (B) guided sampling
  from the trained quadtree, (C) MIS(guided, BSDF) — all must agree on `I`
  (unbiased), and guiding must cut variance.

## Result — the pkg136 thesis holds decisively

Ground truth `I = 0.04308`. 400 trials × 64 spp, trained quadtree ~1000 leaves:

| estimator | mean (bias) | variance | vs BSDF |
|---|---|---|---|
| BSDF (cosine) | 0.0344 (noisy, unbiased) | 9.8e-3 | 1× |
| **guided** | 0.0415 (−3.6%, in noise) | **2e-5** | **~490× lower** |
| **MIS(guided,BSDF)** | 0.0420 (−2.6%, in noise) | **9e-5** | **~110× lower** |

MIS is unbiased and ~110× lower variance on the hard integrand — far beyond the
spec's ≥2× MSE gate. Pure-guided has even lower variance but is only unbiased
where the guide has support (see finding 1); **MIS is the production estimator**
because the BSDF term fills the guide's zero-support holes.

## Key findings for the C++ Stage-1 implementation (in priority order)

1. **Training samples MUST be drawn from the evolving guide (MIS), not BSDF-only —
   this is the #1 gotcha.** BSDF-only training undersamples exactly the hard spike
   region you are trying to learn, leaving zero-flux → zero-density → zero-support
   holes in the guide; those directions are then never sampled and the guided
   estimate is badly (−80%+) biased, and it gets WORSE with a finer tree (more
   empty leaves). Fix (core PPG): iteration 0 trains with BSDF; every later
   iteration draws training samples from a **frozen snapshot of the previous
   iteration's guide, MIS-mixed with the BSDF**, so samples land on the learned
   spike and fill the distribution. This single change moved guided from −83%
   biased to −3.6% (in-noise) and unlocked the ~100× win.
2. **Refine the structure BEFORE the final splat.** Order per iteration: (a) refine
   one level from the previous flux, (b) reset flux, (c) re-splat. If you refine
   AFTER the last splat the tree samples from seed-even (or stale) flux, not the
   trained distribution → biased. `flux` must hold a fresh splat on the final
   structure when sampling begins.
3. **Splat the incident radiance `Li(ω)/pdf`, not `f·Li/pdf`** (radiance-based
   PPG): the guide approximates the incident-radiance field `Li`; the BSDF cosine
   is applied at sample time. (Product guiding — learning `f·Li` — is a later
   refinement; basic radiance PPG already gives the ~100× here.)
4. **Equal-area direction map** `x = cosθ ∈ [0,1]`, `y = φ/2π ∈ [0,1]`; `dω =
   2π·dx·dy`, so the solid-angle pdf is `p(ω) = p_square / 2π`. Uniform square ↔
   uniform hemisphere (no jacobian in the tree; fold the `2π` in once at the pdf).
5. **Refine = split any LEAF holding > ρ of total flux, ONE level per iteration**
   (ρ ≈ 0.003–0.01); the next iteration's flux drives further growth. Hierarchical-
   warp sample: descend choosing child ∝ child.flux, uniform within the final leaf;
   pdf accumulates `Π (child_flux/node_flux · 4)` (each split quarters the area).
6. **MIS = one-sample balance heuristic** over the mixture `p = α·p_guide +
   (1−α)·p_bsdf`, α≈0.5: draw from guide with prob α else BSDF, weight by
   `f·Li / (α·p_guide + (1−α)·p_bsdf)`. Unbiased for any α∈(0,1] because the BSDF
   term guarantees full support.

## Prototype algorithm (reference; `scratchpad/proto_sdtree.py`)

```
class DTree (quadtree over [0,1]^2):
    flux; children[4] or leaf
    splat(x,y,v): flux+=v; recurse into the child containing (x,y)
    refine(total, rho): if leaf and flux/total>rho and depth<max: subdivide (1 level)
    sample(u1,u2): descend child ∝ flux (rescale u1), uniform in leaf; pdf=Π(p·4)
    pdf(x,y): descend, Π (flux[child]/flux[node] · 4)
    snapshot(): deep copy (frozen guide for training draws)

train(iters, spi):
    for it in range(iters):
        if it>0: refine(flux)                    # grow from previous flux
        guide = None if it==0 else snapshot()    # frozen previous guide
        reset_flux()
        repeat spi times:
            w,pw = (bsdf_sample) if guide is None else MIS_sample(guide, bsdf)
            splat(dir_to_square(w), Li(w)/pw)     # radiance-based
    # flux now = last splat on final structure -> ready to sample

estimator (production): MIS(guide, bsdf) as in finding 6.
```

## Stage-1 scope reminder (from the spec)

- **Stage 1A** — host `SDTree` (spatial binary tree, split on point count, +
  per-leaf `DTree`) + the doubling-budget iteration driver + inverse-variance
  image combination.
- **Stage 1B** — wire the guide into `pathTraceSpectral`: wrap the
  `Material::sampleSpectral` draw with the guide/BSDF MIS, splat path radiance on
  the return sweep. Gate `guiding: on/off` (off byte-identical).
- **Gates** (§6): unbiasedness (mean-ratio vs unguided converged, NOT SSIM), ≥2×
  MSE reduction on a hard-indirect scene, no-harm-when-off (byte-identical),
  no-blowup-on-easy. The spatial-tree half still needs its own de-risk (point-
  count split + the leaf lookup from `rec.point`); the directional core above is
  proven.
- Stage 2 (GPU) stays deferred — the `__noinline__` runtime-flag side-body pattern
  + `__constant__` quadtree-CDF side table, designed with Stage-1 data.
