# pkg265 — Multiple-scattering microfacet dielectric (Heitz 2016) — Research

**Date:** 2026-09-09
**Author:** Claude (Opus 4.8, package-implementer)
**Spec:** `.astroray_plan/packages/pkg265-multiscatter-microfacet-glass.md`
**Status of this note:** Phase 1 complete (equations + numpy oracle + divergence
table). Lead confirmed **Option A (clean-room from the paper equations)** on
2026-09-09 — see §Reference / licence below.

---

## Paper

- **Title:** Multiple-Scattering Microfacet BSDFs with the Smith Model
- **Authors:** Eric Heitz, Johannes Hanika, Eugene d'Eon, Carsten Dachsbacher
- **Year / Venue:** ACM Transactions on Graphics 35(4) (SIGGRAPH 2016)
- **DOI:** 10.1145/2897824.2925943
- **PDF (freely readable mirror):** https://jo.dreggn.org/home/2016_microfacets.pdf
  (author co-host, Johannes Hanika). Also
  https://eheitzresearch.wordpress.com/240-2/.
- **Sections used:** §5 (intersection with the microsurface: height statistics,
  Λ, free-path sampling Alg 1), §6 (phase functions: dielectric Alg 3), §7 (random
  walk Alg 7 + the dielectric vertical flip Fig 11), §8 (the multiple-scattering
  BSDF as the expectation of walks, Eq 42-45), §9 (implementation: importance
  sampling weight = final throughput, stochastic eval, MIS PDF).

## Reference / licence — Option A (clean-room), lead-confirmed 2026-09-09

The `cite-algorithm` skill requires a *licence-compatible* reference implementation
to mirror and classifies an **unstated licence as Reject**. The previous lane
instance surveyed the candidates and raised a STOP:

| Candidate | Where | Licence | Verdict |
|---|---|---|---|
| Heitz supplemental `MicrosurfaceScattering.cpp` | linked from eheitzresearch.wordpress.com/240-2 (Drive `0BzvWIdpUpRx_bTdXTEFfaWlQRUE`); replicability.graphics records "license: unspecified" | **UNSTATED** | Reject for porting |
| Heitz's Mitsuba 0.5/0.6 plugin (bundled) | same download | **GPLv3** (Mitsuba 0.5) | Incompatible with MIT |
| Mitsuba 3 `roughdielectric` | github.com/mitsuba-renderer/mitsuba3 | BSD-3 | Compatible but **single-scatter only** (not the Heitz walk) |
| pbrt-v4 layered BxDF | github.com/mmp/pbrt-v4 | Apache-2.0 | Compatible but **different model** (Guo 2018 layered media) |

**No licence-compatible reference implementation of the Heitz Smith random walk
exists to port.** The published paper is freely readable and contains every
equation of the model (§5–9).

**Lead decision (2026-09-09, Option A):** implement the random walk **clean-room
from the paper's published equations**, citing Heitz 2016 (DOI 10.1145/2897824.2925943)
in this note and in every code header; **copy zero lines** from the unstated-licence
supplemental or the GPL plugin (they were not reopened while writing code). The numpy
oracle is likewise written from the equations. This is the standard reading of
CLAUDE.md §6 — the algorithm and mathematical formulae are cited provenance; the
reference code's textual expression is not used. The one auxiliary routine that is a
separate, freely-implementable published algorithm — GGX visible-normal sampling — is
the Heitz JCGT-2018 bounded-VNDF method, which Astroray already ships independently in
`plugins/materials/principled.cpp:724` (`sampleGgxVNDF`); the oracle reuses that same
construction. Fresnel and refraction reuse the exact single-interface math already in
`.astroray_plan/docs/pkg264/glass_energy_oracle.py`.

---

## The model, term by term (all from the paper text)

Notation: microsurface normals ωm point up (ωm.z > 0); D(ωm) is the GGX NDF; α is
the (isotropic) GGX roughness; the engine maps `roughness → α = max(roughness², 0.0064)`.

### Height statistics (§5.1, Eq 18-19)
The Smith microsurface height is standard-normal:
- density `P1(h) = N(0,1) = exp(-h²/2)/√(2π)`,
- CDF `C1(h) = ½(1 + erf(h/√2))`,
- quantile `C1⁻¹(u) = √2 · erf⁻¹(2u − 1)` (with `C1⁻¹(u≥1) = +∞`).

### Signed Smith Λ (§5.1, Eq 21-22, Appendix B)
Extended to both hemispheres so downward rays are handled:
`Λ(ω) = ½( sign(ω_z)·√(1 + α² tan²θ) − 1 )`, with `tan²θ = (1 − ω_z²)/ω_z²`.
`Λ(ω_z→+1) = 0` (up ray always leaves), `Λ(ω_z→−1) = −1` (down ray always intersects).
`σ_Smith(−ω) = (1 + Λ(ω)) cosθ` (projected area, Eq 22).

### Masking-from-height (§5.2, Eq 25-26)
`G1dist(ωr, hr, ∞) = C1(hr)^Λ(ωr)` — probability a ray at height hr in direction ωr
leaves the microsurface without another intersection.

### Free-path / height sampling (§5.2, Alg 1, Eq 30)
Given the current height hr, direction ωr and a uniform U:
```
if U ≥ 1 − C1(hr)^Λ(ωr):  hr₊₁ = +∞          # ray leaves the microsurface
else:                     hr₊₁ = C1⁻¹( C1(hr) / (1−U)^(1/Λ(ωr)) )
```
With the *signed* Λ this single expression reproduces Table 3: up rays (Λ>0) can
escape and otherwise move up toward taller peaks; down rays (Λ<0, escape prob 0)
always intersect and move down. Numerically we special-case ω_z→+1 (return +∞) and
ω_z→−1 (Λ=−1: `hr₊₁ = C1⁻¹(C1(hr)(1−U))`), and |ω_z|<1e-4 (stay at hr).

### Dielectric phase function (§6.2, Eq 34, Alg 3)
At an intersection set the phase-incident `ωi = −ωr`; sample a visible micronormal
`ωm ~ Dωi` (GGX VNDF, Eq 32); then
```
if U < F(ωi, ωm):  ωo = reflect(ωi, ωm)      # Fresnel reflection off the microfacet
else:              ωo = refract(ωi, ωm, η)    # Snell refraction through it
weight w = 1                                   # dielectric is non-absorptive
```
`F` is the exact dielectric Fresnel with the side-appropriate η (air→glass entering,
glass→air after a transmission). The **weight is always 1** — this is why the
dielectric walk conserves energy *by construction* (§6.3 Eq 40).

### Random walk (§7, Alg 7) + dielectric flip (Fig 11)
```
h₀ = +∞;  ω₁ = −ω_i;  e₁ = 1;  r = 1
loop:
  hr = sampleHeight(hr₋₁, ωr)          # Alg 1
  if hr = ∞: break                     # ray left the microsurface
  (ωr₊₁, w) = samplePhase(−ωr)         # Alg 3, w=1
  er₊₁ = w · er                        # stays 1 for a dielectric
```
On a genuine **transmission** event the configuration is vertically flipped (Fig 11):
`hr → −hr`, the ray's z is flipped, and the interface iors are swapped so the "surface
is always below the ray" invariant holds. The parity of flips at exit decides the
outcome: **even → reflected (exits the incident side), odd → transmitted**. The
outgoing macro-direction is the current ray direction with the net z-flip undone.

### Importance sampling & PDF for MIS (§9)
Alg 7 *is* the importance sampler; the sample weight is the final throughput er,
which is 1 for a lossless dielectric — so the sampler is unbiased and "perfect"
(no dead samples). For MIS, the PDF is **not** the true (intractable) sampling PDF;
per §9 we return the closed-form single-scattering VNDF PDF of the *first* event plus
a small diffuse floor — a valid quantity for unbiased MIS weights. (This is what the
engine's `pdf()` will return; the directional test checks it against the sampled
first-bounce histogram, not against the multi-bounce distribution.)

### Stochastic eval (§8.1, Eq 42)
No closed form exists; each eval runs a fresh walk and sums the per-bounce
contribution toward the queried ωo:
`f(ωi,ωo) cosθo = E[ Σr er · p(−ωr, ωo) · G1dist(ωo, hr) ]`.
Implemented in the oracle as `stochastic_eval`; the engine may keep the cheaper
sampled estimator for shading and reserve the stochastic eval for NEE/MIS legs.

## What Astroray reproduces vs simplifies

- **Reproduced:** the full dielectric random walk (height sampling Alg 1, dielectric
  phase Alg 3, Alg 7 loop, the Fig 11 flip), giving both reflection and transmission
  from one model; `scatteringOrderMax` bound (walk terminates at ∞-escape; the
  oracle uses 32, which truncates < 0.05 % of energy — see the R+T=1.000 column).
- **Simplified:** the §9.1 variance reductions (closed-form single-scatter first
  bounce, integrated intersection probability, bidirectional walks) are optimisations,
  not correctness requirements; the engine ships the plain unbiased walk first and can
  add them later. The MIS PDF uses the first-event VNDF PDF + diffuse floor (§9).

## Divergence: MS walk vs single-scatter vs Cycles' 1/E (oracle, IOR 1.45, M=2·10⁵)

Directional-hemispherical reflectance R and transmittance T by incidence cosine μ.
`SS` = single-scatter-only (one phase event; `SS_dead%` is the energy lost); `E_ss =
SS_R+SS_T`; Cycles' `energy_scale = 1/E_ss` rescales SS uniformly to totalise 1.

```
rough  mu  | MS_R   MS_T   MS_R+T dead% | SS_R   SS_T   SS_dead% | E_ss  comp=1/E | Cyc_R  Cyc_T
------------------------------------------------------------------------------------------------
0.3    0.1 | 0.347  0.653  1.000   0.0 | 0.321  0.602    7.7 | 0.923  1.084  | 0.348  0.652
0.3    0.5 | 0.081  0.919  1.000   0.0 | 0.078  0.915    0.6 | 0.994  1.007  | 0.079  0.921
0.3    0.9 | 0.035  0.965  1.000   0.0 | 0.034  0.964    0.1 | 0.999  1.001  | 0.034  0.966
0.5    0.1 | 0.173  0.827  1.000   0.0 | 0.165  0.698   13.7 | 0.863  1.159  | 0.191  0.809
0.5    0.5 | 0.065  0.935  1.000   0.0 | 0.060  0.900    4.0 | 0.960  1.041  | 0.063  0.937
0.5    0.9 | 0.033  0.967  1.000   0.0 | 0.032  0.958    1.0 | 0.990  1.010  | 0.032  0.968
0.85   0.1 | 0.077  0.923  1.000   0.0 | 0.069  0.250   68.1 | 0.319  3.136  | 0.217  0.783
0.85   0.5 | 0.033  0.967  1.000   0.0 | 0.028  0.740   23.3 | 0.767  1.303  | 0.036  0.964
0.85   0.9 | 0.020  0.980  1.000   0.0 | 0.018  0.905    7.7 | 0.923  1.083  | 0.019  0.981
1.0    0.1 | 0.064  0.936  1.000   0.0 | 0.053  0.096   85.1 | 0.149  6.694  | 0.354  0.646
1.0    0.5 | 0.024  0.976  1.000   0.0 | 0.021  0.593   38.7 | 0.613  1.630  | 0.033  0.967
1.0    0.9 | 0.014  0.986  1.000   0.0 | 0.012  0.857   13.0 | 0.870  1.150  | 0.014  0.986
```
(Full 4×5 grid: `benchmarks/cycles-parity/glass_ms_oracle/table_full.txt`, regenerate
with `python heitz_random_walk.py`.)

**Reading of the table:**
1. **Energy conservation is exact for the MS walk** — `MS_R+T = 1.000`, `dead = 0.0%`
   across the whole grid. This is the correctness self-check: a lossless dielectric
   walk deposits its full unit of energy. It also validates the transcription (a
   sign error in the flip or Λ breaks conservation immediately).
2. **The single-scatter deficit is real and large** — `SS_dead%` reaches 68 % at
   r 0.85 / μ 0.1 and 85 % at r 1.0 / μ 0.1. This dead energy is precisely what the
   current engine's #771 delta reroute redistributes as a Dirac; the walk instead
   returns it as a *smooth* multiply-scattered distribution.
3. **Cycles' 1/E and the MS walk agree on the total but disagree on the split.**
   `1/E` rescales SS *uniformly*, so it preserves the single-scatter **R:T ratio**.
   The true multiple-scattering walk sends the recovered energy preferentially into
   **forward transmission** at grazing / high roughness. At r 1.0 / μ 0.1 Cycles
   predicts R:T = 0.354:0.646 while the walk gives 0.064:0.936 — a 5.5× reflection
   over-count by the 1/E model. This is the "different angular shape" the owner's
   physics-first rule anticipated: `1/E` is an energy patch, not the mechanism.

**Premise check (spec Phase-1 gate):** the table does **not** contradict the premise —
it confirms it. The engine's rough-glass darkness is the SS dead-energy loss, the MS
walk removes it with zero dead samples, and it diverges from Cycles' 1/E in exactly the
predicted way. Proceeding to Phase 2 (CPU engine).

## Differences from the reference (Astroray-specific)

- α floor `max(roughness², 0.0064)` matches the engine (not the paper, which uses α
  directly). Fresnel/refraction reuse the pkg264 single-interface routines.
- `scatteringOrderMax = 32` in the oracle; the engine will use a smaller bound (start
  10, measured truncation < 0.1 %) to cap the CPU/GPU cost — recorded in Phase 2.
- Transmission radiance compression (`/η²`) is an engine radiometric convention applied
  to `eval`, orthogonal to the walk's *directions*; it does not change the sampled
  distribution the directional test checks.

## Phase 2 (CPU) — results (2026-09-09)

Both glass lobes (`principled` transmission, `disney` glass) now sample the
clean-room Heitz-2016 walk in `include/astroray/microsurface_dielectric.h`.
`sample()`/`sampleSpectral()` set `f/pdf = throughput` directly (the walk is a
perfect importance sampler, phase weight == 1); the §9 first-bounce VNDF density
plus a 0.05 diffuse floor is the MIS pdf (always > 0, so a walk direction is never
dropped as a dead pdf==0 sample). The #771 delta reroute (principled) and the
pkg138 dead-sample delta fallback (disney) are removed; `ggxGlassComp` /
`ggxGlassCompensationFactor` are no longer applied to these lobes.

- **scatteringOrderMax = 16** in the engine (the oracle used 32). Measured dead
  fraction 0.00 % over the 4×5 (roughness,μ) grid at IOR 1.45 (directional test),
  so 16 is enough; the truncation is below MC noise.
- **Directional gate** `tests/test_pkg265_ms_glass_directional.py`: RED on main,
  **GREEN after** — 41/41. Per-bin θ histogram within ±5 % (bins ≥2 % mass),
  R:T albedo within ±2 % of the oracle, pdf coverage ≥ 98 % (100 % measured),
  entry AND exit interface.
- **White furnace (linear, applyGamma=False), 256 spp, seed 7:**
  - principled IOR 1.45  r0.2/0.5/0.85/1.0 = 0.992 / 0.996 / 0.995 / 0.996
  - disney     IOR 1.45  r0.2/0.5/0.85/1.0 = 0.992 / 0.993 / 0.986 / 0.981
  - disney     IOR 1.5   r0.1/0.3/0.6/1.0  = 0.992 / 0.993 / 0.990 / 0.980
  All within the tightened [0.97, 1.02] band. R=1.0 (pkg167's carved-out near-TIR
  corner, previously recovered to 0.926 by a single-scatter compensation table)
  folds back into the conserving set with NO table — the walk conserves it.

### Finding (class-of-bug): the render uses `sampleSpectral`, not `sample`

The CPU integrator calls `Material::sampleSpectral`. `PrincipledPlugin` overrides
it, but `DisneyPlugin` did not — it fell to the base `Material::sampleSpectral`,
whose non-delta branch **re-evaluates `evalSpectral(bs.wi)` (single-scatter)**
whenever `|bs.f| ≤ 1`, discarding the walk's `bs.f`. Symptom: the disney furnace
collapsed 0.97→0.40 with roughness while `debug_bsdf_sample_batch` (which calls
`sample()`) showed byte-identical f/pdf to the conserving principled lobe. Fix: a
`DisneyPlugin::sampleSpectral` override that upsamples `sample()`'s `bs.f`
directly (magnitude-factored for the JH albedo-LUT clamp). Any future material
that sets its own walk/importance-sampled `f/pdf` in `sample()` MUST override
`sampleSpectral` or the base will silently re-evaluate a different (analytic) BSDF.

## GPU (Phase 3) status

The GPU glass lowers to `GMAT_CLOSURE_GRAPH` and samples via
`gpu_principled_sample` / `gpu_closure_graph_sample` in the REG:254-pinned shade
kernel (`stageShadeBucketedKernel`). It still carries the pkg264 #771 dead-sample
delta reroute, which conserves energy (GPU furnace: principled 0.958–0.996, disney
1.00–1.03) but is the Dirac patch, not the walk. A device twin of the walk is a
large, register-sensitive port (a while-loop with erfinv/VNDF/height sampling) into
a saturated kernel; the same base-`sampleSpectral` re-eval trap exists on GPU
(`gpu_closure_graph_sample` non-delta → `gpu_closure_graph_eval`). See the PR body
for the CPU-lands / GPU-phase decision.

## Phase 4 — Cycles cross-check band (2026-09-09)

pkg263 harness re-run (`benchmarks/cycles-parity/metal_ab/harness.py --material
glass`, unchanged driver), Blender 5.2 Cycles CPU oracle vs the Astroray CPU addon
staged from this worktree (`build_blender_addon.py --backend cpu`, staged to
`dist/astroray/` — the raw `build_blender_addon/` build dir is missing the bundled
MinGW/OIDN runtime DLLs the harness needs when importing `astroray` inside Blender,
so `ASTRORAY_PYD_DIR` must point at the staged `dist/astroray/`, not the bare build
dir). Same scene/settings as pkg263/pkg264 §7.5: 256², 128 spp both engines, native
`principled` translation of `ShaderNodeBsdfGlass` (IOR 1.45), grey world + one area
light. Report: `test_results/pkg265_postfix_harness/`.

### Per-ROI Astroray/Cycles ratio (mean of R/G/B; before = post-#771/pkg264, after = post-#778/pkg265)

| ROI | r | before (#771) | after (#778) | Cycles (=1.0, reference) |
|---|---|---|---|---|
| centre | 0.00 | 0.963 | 0.997 | 1.0 |
| centre | 0.20 | 0.950 | 0.976 | 1.0 |
| centre | 0.50 | 0.873 | 1.076 | 1.0 |
| centre | 0.85 | 0.742 | 1.518 | 1.0 |
| limb | 0.00 | 0.815 | 0.832 | 1.0 |
| limb | 0.20 | 0.673 | 0.861 | 1.0 |
| limb | 0.50 | 0.490 | 1.019 | 1.0 |
| limb | 0.85 | 0.556 | 1.053 | 1.0 |
| background | all | ~1.00 (roughness-independent, calibration check) | ~1.00 (unchanged, no glass in the ROI) | 1.0 |

Full per-channel R/G/B table: `test_results/pkg265_postfix_harness/glass_ab_report.md`
(`.json` for the raw numbers). Background is unchanged from pkg263/pkg264 (pure
world-sky pixels, no glass BSDF involved) — the calibration check still holds:
colour pipeline / exposure / world sampling match between engines.

### Direction check against the oracle divergence table

The oracle (§Divergence above, IOR 1.45) shows the MS walk and Cycles' `1/E`
single-scatter compensation agree on **total** single-interface albedo (both sum
to 1.000 by construction — `1/E` is defined to conserve energy too) but disagree
on the **R:T split**, worst at grazing incidence (low μ, i.e. the sphere's limb):
at r 0.85/μ 0.1, Cycles predicts R:T = 0.217:0.783 vs the walk's 0.077:0.923 — Cycles
over-counts reflection and under-counts transmission at grazing by re-scaling the
*single-scatter* GGX lobe uniformly rather than redistributing the recovered energy
into the true multiply-scattered (more-forward, more-diffuse) shape.

- **Limb (grazing, low μ) — direction predicted correctly, magnitude overshoots
  parity.** Before #778 the limb was severely dark (0.49–0.56× Cycles) because the
  #771 delta reroute discarded dead microfacet samples as flux without ever giving
  them a direction the rough lobe's `eval`/`pdf` could see in a lit scene — the walk
  removes that dead-sample loss entirely (0.0% dead, oracle table) and correctly
  redistributes it into transmission. The limb ratio moves from ~0.5× to ~1.0–1.05×
  Cycles at r ≥ 0.5 — the walk lands almost exactly on the Cycles band, the direction
  the oracle predicts (transmission-favoured redistribution reads as "more light
  reaching the camera through/around the grazing rim," matching what darkened the
  #771 render).
- **Centre (near-normal, high μ) — same direction, larger overshoot.** The oracle's
  high-μ rows show Cycles and the walk nearly agree on the *single-interface* split
  (r 0.85/μ 0.9: Cyc_R 0.019 vs MS_R 0.020) — the single-bounce prediction is that
  centre should diverge *least*. The render disagrees: centre overshoots Cycles by
  1.08–1.52× at r ≥ 0.5, growing faster than the limb. The single-interface oracle
  does not model what the full render integrates: a glass sphere refracts through
  **two** rough interfaces (entry + exit), each independently redistributing energy
  into a broader multiply-scattered lobe; the walk's per-interface distribution is
  unbiased and each interface individually conserves energy exactly (furnace
  0.992–0.996 linear, Phase 2 §), but two unbiased-but-differently-shaped
  redistributions compound non-linearly along the transmitted path in a way the
  single-interface table cannot predict. Cycles' `1/E`, by contrast, keeps the
  original single-scatter GGX *shape* (only the total is rescaled), so the same
  double-refraction compounding under Cycles stays closer to a single-scatter
  angular profile. This is consistent with the owner's physics-first framing: the
  walk is the more physically complete model (each interface conserves energy
  exactly and unbiasedly), and the divergence is a **shape** difference through two
  interfaces that the oracle's single-interface table only partially predicts —
  not a bug signature (no dead samples, furnace in-band, background ROI unchanged).
- **r 0.00/0.20 also moved** (limb 0.815→0.832, 0.673→0.861) even though #771 only
  targeted dead *microfacet* samples — the walk also replaced the reflection lobe
  (spec "both lobes, one model"), so even lightly-rough dielectrics now sample the
  walk instead of the previous VNDF-reflection code path, shifting these ROIs too.
  This is expected under the "both lobes, one model" design decision, not a
  regression.

**Verdict:** the severe under-brightness the owner reported (`dark ball`) is fixed
in the predicted direction (limb goes from ~0.5× to ~1.0–1.05× Cycles); the residual
is now an **overshoot** at the centre, growing with roughness, that the oracle's
single-interface table explains qualitatively (both interfaces individually conserve
energy exactly and redistribute the shape) but does not fully quantify (it does not
model the two-interface compounding). This residual is the natural target for a
follow-up two-interface/whole-sphere oracle extension, not evidence the walk is
wrong — the furnace (single-interface energy conservation) is in-band on both CPU
backends and the background-ROI calibration check is unchanged.

### Contact sheets (visually inspected)

`.astroray_plan/docs/pkg265/postfix_harness/`:
- `glass_r000__contact_sheet.png`, `glass_r020__contact_sheet.png`,
  `glass_r050__contact_sheet.png`, `glass_r085__contact_sheet.png` — Cycles |
  Astroray | abs-diff×3, sRGB for viewing (all numbers above computed on linear
  arrays). At r=0.5 the two spheres are visually close (matches the ~1.0–1.08×
  ratio). At r=0.85 the Astroray sphere is visibly a touch brighter/more diffuse
  than Cycles' already-bright frosted look (matches the 1.52× centre ratio) — no
  longer the pkg263 dark ball, and no longer a directional/Dirac artifact (the
  #771-era single-direction reroute produced a visibly patchy grazing rim; this
  render is smooth).
- `glass_r085__cycles_roi.png` / `glass_r085__astroray_roi.png` — the three ROI
  overlays (red = centre disc, green = limb annulus, blue = background patch) on
  each engine's own r=0.85 render.

### Wall time (CPU, this worktree, no GPU lock)

Per-config leg finish-to-finish deltas (includes each subprocess's own Blender
`--factory-startup` overhead): Cycles legs ≈ 2.9 s each (after the first); Astroray
legs scale with roughness as the walk's mean bounce count grows — r0.00 ≈ 14 s,
r0.20 ≈ 17 s, r0.50 ≈ 21 s, r0.85 ≈ 25 s. Full 4-config × 2-leg sweep ≈ 100 s wall
time end to end.

## Phase 5 — eval/NEE consistency and the centre brightening (2026-09-09)

Eval-fix lane (`feat/pkg265-eval-fix`) after the cycles-parity-reviewer CRITICAL and
cpp-abi-guard nit on PR #778. Two problems were on the table: **(A)** eval()/pdf() on
the glass lobes were bare single-scatter while sample() carried the walk throughput
(MIS inconsistent at NEE vertices); **(B)** the Phase-4 harness centre over-brightens
by up to +52 % growing with roughness — which A (a *darkening*) cannot explain.

### Localisation (in-process, CPU build, `test_results/2026-09-09-pkg265evalfix/repro.py`)

Raw engine binding, analytic glass sphere (native `principled`, IOR 1.45), path_tracer,
160²/96 spp, centre disc r<0.35R. One lever at a time, byte-compared:

| lever | centre c/c(r=0) @ r0.2/0.5/0.85 | reading |
|---|---|---|
| dedicated area light, NEE on (no bright hittable geometry) | 1.00 / 1.00 / 1.00 (flat) | NEE does **not** drive the brightening |
| emissive SPHERE (hittable, radiance 20; NO NEE, NO MIS) | 1.00 / 1.11 / **1.48** | the brightening lives in the **BSDF leg** |
| full scene, plane + **non-hittable** dedicated light | 0.99 / 0.92 / **0.86** (darkens) | a non-hittable light cannot brighten the centre |
| full scene, plane + **hittable** emissive quad (= a Blender area light) | 1.01 / 1.34 / **2.48** | reproduces the harness: BSDF rays through the rough glass gather the hittable light |

The +52 % is the walk's BSDF-transmission leg: rough glass **diffuses the bright,
hittable area-light geometry across the sphere including the centre** — exactly what a
frosted-glass ball near a lamp does, and exactly what a *clear* ball (r=0, sees only
the dim grey world through refraction) does not. It grows with roughness because the
transmitted lobe widens. The harness's Blender area light is hittable geometry (Cycles
emitters are), so its centre brightens; a non-hittable dedicated light darkens instead.

**This is NOT hypotheses (1)–(4).** Ruled out decisively:
- **(1)/(2) η² accounting** — the walk's `radianceScale` telescopes EXACTLY (the Fig-11
  flip swaps the interface iors on each transmission and multiplies by (n1/n2)² before
  the swap, so the product depends only on the transmission *parity* = final side).
  `tests/cpp/test_pkg265_walk_eta.cpp` measures maxErr **0.0** over 1.6 M walks at IOR
  1.45 and ~1e-7 at 1.5, for reflected (→1), entering-transmitted (→1/ior²=0.4756) and
  exiting (→ior²=2.1025), across roughness 0.2–1.0 and any micro-bounce count. The CPU
  render applies the factor exactly once (throughput *= f/pdf; sample() folds
  `walkRadiance` in once), and the addon renders through `path_tracer::pathTraceSpectral`
  which has **no** separate eta² step — so there is no double application.
- **(3) reflection-walk paths** — reflected walks carry `radianceScale==1` exactly (unit
  test), no stray factor.
- **(4) proxy-pdf MIS imbalance** — the +48 % survives in the emissive-**sphere** path
  which has NO dedicated light (no NEE) and hits a plain emitter at full weight (no MIS
  reweighting). So the brightening is not an MIS-weight artefact.

The walk matches the numpy oracle (directional gate ±5 %/bin, 41/41), conserves energy
exactly (furnace, R+T=1), and the eta is exact. So the centre brightening is the
**physically-correct Heitz multiple-scattering behaviour diverging from Cycles' 1/E
single-scatter compensation** (the Phase-4 verdict, now with a mechanism, not a
bug). Per the owner's physics-first rule (spec §Context / north-star §7) it is kept and
recorded, with Cycles as a cross-check band, not the criterion. **The centre will remain
brighter than Cycles after this fix** — that is by design; forcing it to match Cycles
would mean adopting Cycles' 1/E model, which the spec forbids.

### Fix for A — skip-NEE delta contract (reviewer option (b))

`eval()`/`evalSpectral()` on the glass walk lobes now return **0** (principled:
`transmissionEvalRGB` early-out when `!filmActive()`, covering RGB + non-film spectral,
both the reflection and refraction sub-lobes; disney: the transmission branch and the
`roughReflectionEval` blend), and `sample()`/`sampleSpectral()` set `isDelta=true`. This
is the SAME delta-for-NEE contract smooth glass already uses (eval==0 ⇒ NEE contributes
0; the next emitter hit is taken at full MIS weight via `wasSpecular`). It is unbiased —
all light transport for rough glass is BSDF sampling + emitter-hit MIS — at the cost of
noisier direct light on rough glass. `pdf()` is left as the §9 proxy (harmless: unused
for weighting once `isDelta`, and it keeps the directional gate's `debug_bsdf_pdf_batch`
check green).

**Why not the stochastic eval (Eq 42, the lead's first choice).** `msdiel::stochasticEval`
is shipped but `eval()`/`evalSpectral()`/`pdf()` carry **no RNG parameter**, so a
per-NEE-sample stochastic eval would require either a signature change rippling across
~20 materials and every call site, or a `thread_local` RNG that makes the eval path
non-deterministic — breaking the chi²/guiding callers that assume `eval()` is pure — plus
a full extra walk per NEE sample. The measured payoff is small: the uniform lit furnace
already reads **0.993–0.997** with the current single-scatter eval (A's bias washes out in
a uniform field / is dominated by BSDF-hit where the light is hittable). Cost/risk not
justified vs the unbiased delta-contract skip; recorded here per CLAUDE.md §1.

### Verification (CPU build, this worktree)

- **eta unit test** `tests/cpp/test_pkg265_walk_eta.cpp`: PASS — telescoping exact,
  scatterMax=16 dead 0.0000 % at IOR 1.45 and 1.50.
- **LIT furnace** `tests/test_pkg265_lit_furnace.py` (uniform field + area light,
  exercises NEE): principled 0.992–0.996, disney 0.986–0.995 across r 0.2/0.5/0.85/1.0 —
  all in [0.97, 1.02]. Same numbers with the light off (BSDF-only), confirming the
  skip-NEE leg is unbiased.
- **Directional gate** `tests/test_pkg265_ms_glass_directional.py`: 41/41 (unchanged —
  sample()/pdf() untouched).
- **Glass furnace suites** (pkg264 parity, disney/dielectric rough-glass furnace): green.
- **#ifndef __CUDACC__** guard added to `microsurface_dielectric.h` (host-only).

### Still open

- **B (centre vs Cycles) is a documented divergence, not fixed** — it is the physically
  correct walk. A whole-sphere / two-interface oracle (Phase-4 §"Centre" follow-up) would
  independently quantify it beyond the single-interface directional gate; filed as a
  tangent, not a blocker.
- **GPU leg (Phase 3)** unchanged — still the pkg264 #771 reroute stub; a later phase.
