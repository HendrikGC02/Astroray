# pkg136 Stage-1B findings — CPU path-guiding: correct primitives, three real blockers

Stage 1B wired the SD-tree guide into `pathTraceSpectral` (raytracer.h). The
**data structures are correct** (unbiased warp, sample==pdf, no MIS-measure bug —
verified below), but path guiding **does not yet reduce variance**, and on hard
(Veach-door) scenes it makes noise 3–9× *worse*. This note gives the root-caused,
independently-corroborated reason and the corrected fix priority.

The diagnosis below was reached two ways that agree: (a) direct measurement on
this build (knob sweeps + a bias/variance decomposition + an isolated warp
consistency test via the `test_helpers` DTree/SDTree bindings), and (b) an
independent code+math review by a second model (glm-5.1 via the `delegate`
critic; its full analysis is in the session transcript — it corroborated the
warp/MIS correctness and surfaced the discarded-training and 1/(1−α) points).

## What is correct and verified (do not re-investigate)

- **Warp is measure-consistent — there is NO normalization bug.** A 2D histogram
  of `DTree::sample()` outputs matches `DTree::pdf()` cell-for-cell (ratio 1.00).
  `E[1/pdf]` equals the *support area* (0.5 for a half-supported tree, 1.0 for a
  full one), NOT 1 — this is expected and was twice misread as a bug in this
  package. Do not chase it again. Test: `scratchpad dtree_consistency.py` /
  `dtree_hist.py` against `astroray_test_helpers`.
- **MIS is measure-consistent.** `ls.pdf` (solid-angle × selection) and the
  mixture `bsdfPdf` are both solid-angle; NEE `wt` and the emitter-hit `wB` both
  use the same mixture pdf → wL+wB≈1. (One pre-existing pkg120 joint-vs-marginal
  subtlety exists for multi-emitter directions; benign for single-light scenes.)
- **Guide trains and concentrates** toward incident radiance (conc→1.0 via
  `guide_probe`). The machinery works end-to-end.

## The three real blockers (corrected priority)

### 1. [DOMINANT, architectural] Training samples were discarded — NOW FIXED
`render()` cast `K·trainSpp` samples/pixel to build the guide, then **threw every
one away** (`sampleFull(...); // discard`) and rendered the image separately. At
24 image spp with defaults (K=6, trainSpp=8) the guided render cast ~24+48=72 spp
of rays but showed 24 — 2/3 of the work discarded, making an equal-*cost* win
arithmetically impossible. **Fixed** (raytracer.h, this branch): the training
passes are full unbiased path traces, so their radiance + light-path passes are
now accumulated per-pixel and folded into the final image (equal-weight — still
unbiased; Σpasses==beauty preserved; default-off byte-identical). This also
removed the high-α dark bias (the folded lower-α training samples dilute the
final-pass clamp bias: α=0.9 mean-ratio 0.37→0.99). Follow-up headroom:
inverse-variance pass weighting instead of equal-weight.

### 2. [dominant on hard scenes] The 1/(1−α) undercover penalty
One-sample guide/BSDF MIS with mixture `p_mix = α·p_guide + (1−α)·p_bsdf`. Where
the guide has ~zero mass but the integrand has variance mass, `p_mix ≈
(1−α)·p_bsdf`, so that region's second moment is inflated by **1/(1−α)**: α=0.3→
1.43×, 0.5→2×, 0.9→10×. Measured MSE-ratios on the Veach-door track this closely
(α=0.5→0.11×, α=0.9→0.14×), and interacting with the energy clamps
(`clampContribSpectral`, the `maxC>10` throughput cap) it also produces a
**persistent dark bias that grows with α** (guided-512 mean ratio-to-ref: α=0.1→
1.00, α=0.7→0.69, α=0.9→0.37). This is the "guiding actively hurts" mechanism.
**Fix: a coverage floor** — blend a uniform (or BSDF-cosine) component into the
guide so `p_guide>0` wherever the BSDF has support, and/or cap α. Removes the
active harm; brings hard-scene guiding back to ≥ break-even.

### 3. [ceiling] Radiance guiding on Lambertian-isotropic light is capped ~1.3×
With `divPdf=false` the splat positions are drawn from the training pdf `q`, so
the learned density converges to `L_i·q`; for Lambertian+cosine that is already
product-optimal, i.e. the guide converges to the BSDF you already have. On a
near-isotropic diffuse box the oracle bound is ~1.1–1.3×, so ≥2× is **impossible
there regardless of algorithm**. A real ≥2× needs a scene where cosine is far
from optimal: glossy interreflection, or hard directional indirect where NEE
fails. Note the de-risked 110× prototype used `divPdf=true` (`L_i/pdf`); the
shipped default is `false` — the labels in raytracer.h:2300-2303 are inverted vs
the prototype and should be reconciled when this is revisited.

## Secondary defects (fix opportunistically)
- **Data-starved DTrees**: constant `trainSpp` instead of a doubling budget →
  ~200 records/leaf on the 48² gate scene (design §4 wants 1,2,4,… doubling).
- **refine() off-by-one**: `refine()` runs only at the *start* of it>0, so the
  final guide carries iteration K-1 flux on topology adapted to K-2 data; the
  last iteration's records never drive a refinement.
- **clamp-before-snapshot**: the `maxC>10` throughput clamp (3392-3394) fires
  *before* the `betaSnap` capture (3402-3406), biasing the L_i records low on the
  brightest paths (guide-quality only).

## Measured outcome after the blocker-1 fix (equal total budget, this build)
With training folded in and the corrected `div_pdf=true` (Li/pdf) config, at
equal total sample budget (finalSpp + K·trainSpp vs unguided at that total):
- **hard_transport_slot: ~1.3×** (a real, repeatable equal-cost win; α≈0.3, K=8–10).
- moderate_indirect: ~0.7–0.9× (guiding ≈ neutral-to-slightly-worse).
- veach_door (heavily baffled): ~0.4–0.6× (too hard for the coarse guide).

**≥2× did not materialise on any scene, and this is now understood as a ceiling,
not a remaining bug.** The de-risked prototype's 110× (pkg136-stage1-derisking.md)
was measured **without NEE** — there, guiding captured the entire direct-light
spike. In the real integrator NEE already handles that spike, so guiding only
reduces *residual-indirect* variance: near-isotropic on diffuse (oracle ~1.3×),
and, where it is genuinely directional+hard, too fine for a 16–1000-leaf guide
trained in a handful of iterations to resolve. Note also the spatial tree splits
one binary level per training iteration, so leaves ≤ 2^(K−1) — spatial resolution
is iteration-bound, and adding leaves did not help (often hurt) on these scenes.

## If ≥2× is later pursued (in order)
1. **Product guiding** (sample ∝ f·cosθ·L_i) — the only lever with headroom on
   diffuse-isotropic, though still capped ~1.3× there; worth it only alongside (3).
2. A scene class where NEE fundamentally fails AND the transport is learnable by a
   coarse guide (glossy interreflection; a *moderately* occluded emitter). The
   pure-diffuse and over-baffled scenes here bracket the two failure modes.
3. Doubling sample budget + multi-level spatial splits per iteration (lift the
   2^(K−1) leaf ceiling) + inverse-variance pass combination.
4. Coverage floor (uniform blend so p_guide>0 on the BSDF support) to bound the
   1/(1−α) penalty if higher α is ever wanted.

## Tunable knobs shipped (all runtime, no rebuild)
`set_guiding_params(iterations, train_spp, alpha, spatial_frac, dir_rho, div_pdf,
value_clamp)`, `guide_probe(...)`, `get_guide_debug()`. `div_pdf` toggles
`L_i/pdf` vs `L_i` splatting.
