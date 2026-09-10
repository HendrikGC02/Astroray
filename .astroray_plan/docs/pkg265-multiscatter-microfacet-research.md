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

## Phase 6 — harness after the eval/NEE fix (2026-09-09)

Sonnet 5 lane, CPU-only, no GPU lock, on `feat/pkg265-ms-microfacet-glass` HEAD
`fe04324e` (the squashed head carrying both Phase 2 and the Phase 5 eval/NEE fix
— PR #778). Rebuilt `build_cpu/` from this HEAD (`build_cpu_nosccache.bat`,
CUDA-OFF), then restaged the CPU addon from the SAME HEAD
(`build_blender_addon.py --backend cpu` → `dist/astroray/`, matching the
Phase-4 lane's finding that the harness needs the staged runtime DLLs, not the
bare `build_blender_addon/` build dir — `ASTRORAY_PYD_DIR` pointed at
`dist/astroray/`). Re-ran the UNCHANGED pkg263 driver
(`benchmarks/cycles-parity/metal_ab/harness.py --material glass`, 256², 128
spp, CPU both engines) to isolate the eval/NEE fix's effect from Phase 4's
numbers, which were measured on the pre-fix eval()/pdf().

### Per-ROI Astroray/Cycles ratio — three-way comparison (mean of R/G/B)

| ROI | r | before (#771, pkg264) | after CPU walk, pre eval-fix (#778 Phase 4) | after eval/NEE fix (Phase 6, this run) | Cycles |
|---|---|---|---|---|---|
| centre | 0.00 | 0.963 | 0.997 | 0.997 | 1.0 |
| centre | 0.20 | 0.950 | 0.976 | 0.972 | 1.0 |
| centre | 0.50 | 0.873 | 1.076 | 0.899 | 1.0 |
| centre | 0.85 | 0.742 | 1.518 | 0.929 | 1.0 |
| limb | 0.00 | 0.815 | 0.832 | 0.832 | 1.0 |
| limb | 0.20 | 0.673 | 0.861 | 0.765 | 1.0 |
| limb | 0.50 | 0.490 | 1.019 | 0.637 | 1.0 |
| limb | 0.85 | 0.556 | 1.053 | 0.604 | 1.0 |
| background | all | ~1.00 | ~1.00 | 0.994 | 1.0 |

Full per-channel R/G/B table: `test_results/pkg265_postfix_harness_evalfix/glass_ab_report.md`
(`.json` for the raw numbers + raw `.npy` renders per ROI mask).

**Reading:** the eval/NEE fix (Phase 5 — `eval()`/`evalSpectral()` on the rough
glass walk lobes return 0, `sample()`/`sampleSpectral()` set `isDelta=true`, the
smooth-glass delta-for-NEE contract) removes the Phase-4 centre **overshoot**
almost entirely: r 0.50 centre goes from 1.076→0.899 and r 0.85 centre from the
worst offender (1.518, +52%) down to 0.929 — both now UNDER 1.0 and within
~10% of Cycles, a large improvement on the diagnosed bug (NEE double-dipping
into the walk's already-integrated throughput on top of the BSDF-hit MIS leg).
r 0.00/0.20 centre are effectively unchanged (0.997/0.972 vs 0.997/0.976) since
low roughness rarely triggers the walk's multi-bounce NEE leg in the first
place.

The **limb** moves the other direction and by a larger amount: it was closest
to Cycles in the pre-fix Phase-4 numbers (0.83–1.05×) and is now the more
under-shot ROI post-fix (0.60–0.83×, worst at r≥0.5). This is the direct
consequence of the eval-fix's mechanism: rough glass no longer contributes any
NEE estimate at all (`eval()==0`), so all direct light at grazing incidence —
where NEE previously contributed a disproportionate share of the pre-fix
signal, given how hard it is for BSDF sampling alone to land on a small area
light through a wide, forward-scattered transmission lobe — now depends
entirely on a BSDF-sampled ray happening to hit the emitter (`wasSpecular`
MIS full-weight). At 128 spp that BSDF-hit path under-converges at the limb
more than the centre (the transmitted lobe there is wider and more likely to
miss the light), reading as an under-shoot in a 128-spp mean, not a bias in
the unbiased estimator itself (see Noise below). This is the accepted,
documented cost of the unbiased skip-NEE contract (research note "Fix for A"
above): "at the cost of noisier direct light on rough glass."

**background** stays ~1.00 (0.994) — the calibration check is unaffected, as
expected (no glass BSDF in that ROI).

### Noise: Astroray per-ROI std vs Cycles (skip-NEE contract)

Per-pixel std within each ROI mask (256² render, same `.npy` arrays as the
ratio table above), plus each engine's own coefficient of variation
(std/mean) so the roughness-dependent radiance scale doesn't distort the
comparison:

| ROI | r | Cycles std | Astroray std | std ratio (A/C) | Cycles CV | Astroray CV |
|---|---|---|---|---|---|---|
| centre | 0.00 | 0.0202 | 0.0244 | 1.21 | 0.114 | 0.138 |
| centre | 0.20 | 0.0211 | 0.0214 | 1.02 | 0.116 | 0.122 |
| centre | 0.50 | 0.0375 | 0.0410 | 1.09 | 0.172 | 0.208 |
| centre | 0.85 | 0.0647 | 0.0839 | 1.30 | 0.221 | 0.309 |
| limb | 0.00 | 0.1605 | 0.0903 | 0.56 | 0.566 | 0.383 |
| limb | 0.20 | 0.2217 | 0.1220 | 0.55 | 0.698 | 0.502 |
| limb | 0.50 | 0.1967 | 0.1008 | 0.51 | 0.460 | 0.370 |
| limb | 0.85 | 0.1709 | 0.1031 | 0.60 | 0.336 | 0.336 |

At the **centre**, Astroray's coefficient of variation is consistently above
Cycles' (1.02–1.30× the raw std, and CV growing from 1.21× at r=0 to 1.30× at
r=0.85 relative to Cycles' own CV) — this is the predicted skip-NEE noise
penalty: direct light through the centre depends more on BSDF-hit MIS than
before, and that dependence grows with roughness (wider transmitted lobe, same
128 spp budget). At the **limb** the raw std ratio looks like a noise
*reduction* (0.51–0.60×), but that is dominated by the mean itself dropping
(the limb ratio table above) — the CV columns show Astroray's relative noise
at the limb is actually LOWER than or equal to Cycles' there (0.34–0.50 vs
0.34–0.70), i.e. Cycles itself has higher relative variance at grazing
incidence in this scene (its own NEE + MIS at a small, distant area light
across a wide rough-transmission cone is a hard case for both engines) and the
skip-NEE contract does not add a distinguishable extra noise penalty on top of
that at the limb, at least visible in a single 128-spp run. The clearest,
least ambiguous noise signature of the skip-NEE contract is the centre-ROI CV
growth with roughness.

### Contact sheets (visually inspected, force-added — `*.png` gitignored under `docs/`)

`.astroray_plan/docs/pkg265/postfix_harness/` (added alongside the Phase-4
sheets, `_evalfix` suffix so both generations stay comparable side by side):
`glass_r000_evalfix__contact_sheet.png`, `glass_r020_evalfix__contact_sheet.png`,
`glass_r050_evalfix__contact_sheet.png`, `glass_r085_evalfix__contact_sheet.png`,
`glass_r085_evalfix__cycles_roi.png`, `glass_r085_evalfix__astroray_roi.png`.
At r=0.85 the post-eval-fix Astroray sphere is visibly closer to Cycles than
the Phase-4 sheet (no longer conspicuously brighter at the centre); the limb
now reads a touch dimmer/greyer than Cycles rather than matching it, consistent
with the ratio table above.

### Wall time (CPU, this worktree, no GPU lock)

Finish-to-finish per-leg deltas from the `.npy` output timestamps (same method
as Phase 4): Cycles legs ≈2.7–2.85 s each; Astroray legs scale with roughness
(walk bounce count) — r0.00≈18.9 s, r0.20≈21.4 s, r0.50≈26.5 s, r0.85≈30.0 s
(all higher than Phase 4's 14–25 s: `eval()==0` forces every NEE-eligible
vertex through a full extra BSDF-sample-and-continue instead of a cheap
analytic `eval`, and the delta-glass `isDelta=true` path changes bounce
bookkeeping). Full 4-config × 2-leg sweep ≈105 s wall time end to end
(first Cycles leg start to last Astroray leg finish).

### Test gates on this HEAD (rebuilt `build_cpu/`, CPU-only)

`python -m pytest tests/test_pkg265_ms_glass_directional.py
tests/test_pkg265_lit_furnace.py tests/test_pkg264_glass_cycles_parity.py
tests/test_disney_rough_glass_furnace.py tests/test_dielectric_glass_furnace.py
tests/test_rough_glass.py tests/test_issue762_emission_texture.py
tests/test_issue769_energy_compensation_bundling.py -q`:
**57 passed, 6 skipped, 1 failed** — the sole failure is
`test_principled_lit_furnace_conserves_gpu`, which raises
`RuntimeError: CUDA support not compiled` because this build is intentionally
CUDA-OFF (`ASTRORAY_ENABLE_CUDA=OFF`, per this lane's CPU-only scope); it is
not a regression, it is a GPU-marked test hitting a CPU-only build. The C++
eta unit test (`tests/cpp/test_pkg265_walk_eta.cpp`, `compile_eta.bat`) still
PASSes with the numbers already reported in Phase 5: radiance-scale
telescoping maxErr 0.00 (IOR 1.45) / ~4.8e-7 (IOR 1.50), scatterMax=16 dead
fraction 0.0000% at both IOR.
## Phase 7 — thin-film rough glass stays single-scatter (2026-09-09)

Thin-film-fix lane (`feat/pkg265-thinfilm-fix`) after the SECOND cycles-parity
review of PR #778 (CRITICAL #2). Verified with file:line by the reviewer.

### The defect

The walk branch in `principled.cpp` `chooseAndSampleDir` (`if (!L.isDelta)`) had
NO `filmActive()` guard, so a thin-film Principled glass with roughness >
`kDeltaGlassRoughness` (0.03) was routed through the Heitz walk, which
`sample()`/`sampleSpectral()` mark `isDelta=true`. But `eval()`/`evalSpectral()`
return the nonzero single-scatter thin-film f when `filmActive()` (they only
early-out to 0 for a NON-film glass). Two bugs:

1. **Double-counted direct light.** Every integrator does NEE (with `rec.isDelta`
   still false) using the nonzero thin-film `eval()`, then `sample()` flips
   `isDelta` and the emitter hit is taken at full `wasSpecular` MIS weight → the
   light is counted twice.
2. **Iridescence dropped on the sampled path.** The walk uses plain-dielectric
   Fresnel, so the thin film has NO effect on the BSDF-sampled render.

On origin/main this configuration was consistent (single-scatter sample,
`isDelta=false`).

### Fix (lead decision, option 2 — no regression, preserve iridescence)

The walk applies to NON-film rough glass only. Behind `filmActive()`,
`chooseAndSampleDir` restores VERBATIM the origin/main single-scatter rough-
transmission sampler (VNDF reflect/refract + the pkg264 #771 dead-sample →
delta-glass reroute), with `isDelta=false`; `transmissionPdf` returns the exact
single-scatter VNDF density (no §9 diffuse floor) when `filmActive()`. So for a
thin-film rough glass `sample()` takes the `eval()`/`pdf()` path and
sample == eval == pdf are all single-scatter thin-film — exactly as on main.
`eval()`/`pdf()` already routed film → thin-film single-scatter, non-film → 0/§9,
so only the sampler and the pdf floor needed the guard. Non-film glass keeps the
walk + skip-NEE delta contract unchanged.

**Disney glass needs no fix.** `disney.cpp` has NO thin-film / iridescence path
(no `filmActive`/`thin_film_thickness` anywhere in the file), so a Disney glass is
always a plain dielectric and correctly takes the walk. Documented inline.

A thin-film-AWARE walk (the Heitz dielectric phase function with a thin-film
Fresnel/transmittance instead of plain Fresnel) is filed as follow-up **issue
#783**; once it lands the `filmActive()` single-scatter fallback can be removed
and thin-film rough glass gets the multiple-scattering treatment too.

### Measurements (CPU build, this worktree, seed 7)

*Root-cause signal — thin-film glass vs plain glass, world-lit only (no NEE),
r0.85, `test_thinfilm_rough_glass_not_ignored_by_walk_cpu`:*

| build | thin-film RGB | plain RGB | reldiff |
|---|---|---|---|
| pre-fix (walk) | [0.9998, 1.0013, 0.9846] | [0.9998, 1.0013, 0.9846] | **0.0000 (RED)** — walk byte-ignores the film |
| post-fix (single-scatter) | [0.8413, 0.8365, 0.8352] | [0.9998, 1.0013, 0.9846] | **0.158 (GREEN)** — film honoured |

*Double-count evidence — emissive quad behind a glass sphere (hittable + NEE),
black world, thin-film/plain ratio (plain = walk single-count reference):*

| roughness | pre-fix film/plain | note |
|---|---|---|
| 0.3 | 1.049 | +5% double-count excess |
| 0.5 | 1.127 | +13% |
| 0.85 | 1.313 | +31% |

The double count grows with roughness (more NEE mass). Post-fix the ratio is not a
clean metric because plain glass uses the walk while the fixed thin-film glass
uses single-scatter (different directional distributions confound a same-scene
film/plain comparison) — hence the reliable gate is the byte-identical-pre-fix /
different-post-fix signal above, which catches the root cause (routing a thin-film
glass through the plain-Fresnel walk) of BOTH bugs.

*Linear white furnace (no NEE), thin-film single-scatter, no energy gain:* r0.2
0.992, r0.5 0.961, r0.85 0.836, r1.0 0.794 — all ≤ 1.02 (no double-count energy
gain). The high-roughness values below 1.0 are the accepted single-scatter energy
deficit (identical to origin/main thin-film glass; recovered by the #783 walk),
NOT a regression. A naive "uniform furnace ∈ [0.97, 1.02]" gate does NOT go RED
pre-fix (the walk conserves energy in a uniform field), so it is not used as the
discriminator.

### Verification

- `tests/test_pkg265_thinfilm_rough_consistency.py`: 3/3 GREEN post-fix;
  `not_ignored_by_walk` RED pre-fix (reldiff 0.0000).
- Existing suites GREEN (CPU): `test_pkg265_lit_furnace` (14 non-GPU),
  `test_pkg265_ms_glass_directional` (non-film walk unchanged),
  `test_pkg264_glass_cycles_parity`, `test_disney_rough_glass_furnace`,
  `test_dielectric_glass_furnace`, `test_rough_glass`, `test_pkg178_*`,
  `test_thin_film_pr1/pr2/ab_harness`, `test_pkg182_conductor_spectral_native`,
  `test_pkg255_metallic_f82`, `test_chi2_principled` (incl. thin-film specular/
  metallic), `test_chi2_bsdf` — 180+ passed, 0 failed (glass chi² is xfail'd,
  quadrature-dominated, memory `chi2-glass-gate-quadrature-dominated`).

### Still open

- **GPU thin-film rough glass parity.** `test_pkg178_thinfilm_gpu_cpu_parity`
  `glass_r0.2` compares CPU vs GPU thin-film glass; CPU is CPU-only here so it is
  not run in this lane. The fix makes the CPU thin-film rough-glass path single-
  scatter (closer to the GPU #771 reroute stub than the walk was), so parity is
  expected to hold or improve — flagged for the hardware-verifier as a GPU
  backstop (memory `ci_has_no_gpu_runtime_blindspot`).

## Phase 9 — stochastic eval (Eq 42) correctness: the 1e11 firefly and the flip-frame two-branch connection (2026-09-09)

Lead question: is the ~1e11 per-sample value of `stochastic_eval`'s transmission
connection a physical non-convergence (unbounded refractive Jacobian) or a bug?
**Answer: a bug.** Two independent defects, both now fixed in the numpy oracle
(`_vndf_D`, `_refl_lobe`, `_refr_lobe`, `stochastic_eval`) and the C++ twin
(`vndfDwi`, `reflLobe`, `refrLobe`, `stochasticEval` in
`include/astroray/microsurface_dielectric.h`).

### The divergent factor (proven by instrumentation)
Dumping the top-20 per-bounce contributions at r0.85/μ0.3 showed every factor
bounded except `Dwi` (the VNDF value), which reached 1.6e11. Root cause in
`_vndf_D`: the denominator was `|cos_i|·(1+Λ(wi))`. Paper Eq 32,
`Dwi = <wi,wm> D(wm) / (cos_i (1+Λ(wi)))`, is valid for wi in **either**
hemisphere (Sec 6.1); for an upward-going ray (wi.z<0) cos_i<0 **and** (1+Λ)<0,
so the product (the projected area) is positive. Using `|cos_i|` makes it
negative; `max(·,1e-12)` then floors it and Dwi ~ idot·D/1e-12 → 1e11. With
**signed** cos_i the denom → 0.5·alpha as wi.z→0 from either side and stays
positive. This alone caps the per-sample value.

### The lead's bound, confirmed
With `wm = -(n_i ω_r + n_t ω_o)/|·|`, d = n_i(ω_r·wm)+n_t(ω_o·wm) = ±|n_i ω_r+n_t ω_o|,
and |n_i ω_r+n_t ω_o|² = n_i²+n_t²+2 n_i n_t(ω_r·ω_o) ≥ (n_t−n_i)² ≈ 0.2 at IOR 1.45,
so 1/d² ≤ 4.9. D ≤ 1/(πα²), G1 ≤ 1, F ≤ 1, n_t² ≤ 2.1. The single transmission
connection is O(10). **Measured after the fix:** at r≥0.5 max per-sample 4–19,
99.9-pct 2–20; at r=0.3 (near-specular BTDF lobe) max 130–294 — a legitimately
peaked but finite value, not a divergence.

### The R/T split: flip-frame two-branch connection
After the Dwi fix, energy conserved (∫f cosθ dω = R+T ≈ 1) but the reflection/
transmission split was wrong at grazing high roughness. Diagnosis chain:
1. phase-function normalization ∫p dω must be 1 (Eq 40) — it wasn't for wi.z<0 /
   inside. Fixed by computing the phase as the **exact sampler density**: for a
   query direction compute BOTH the reflection half-vector `normalize(wi+ω)` and
   the refraction half-vector `normalize(-(ni wi+nt ω))`, keep each only if it is
   a genuine **upper-hemisphere** microfacet (wm.z>0) that actually reaches ω
   (reflection auto-valid; refraction: orient for visibility, then refract and
   check `dot(refract(wi,wm),ω)>0.999`). Verified ∫p dω = 1.000 for both media
   and both hemispheres.
2. Per-vertex escape must equal the walk's one-step escape probability. Measuring
   it isolated the leak to **inside** vertices: physically the micronormals point
   *down* there (wm.z<0), which the wm.z>0 branches reject. The fix is to evaluate
   the connection in the **same flip frame the walk runs in** (canonical wm.z>0),
   mapping the fixed macro dir to `wifR = flip^nflip(ω)`. The walk only ever
   escapes flip-frame-up, so exactly ONE lobe contributes per vertex:
   - `wifR.z>0`: reflection toward wifR, shadow `C1(hr)^Λ(wifR)`;
   - `wifR.z<0`: refraction whose pre-flip output is wifR; the walk flips it to
     `flip(wifR)` (z>0), shadow `C1(-hr)^Λ(flip(wifR))`.
   This makes R come only from outside-escapes and T only from inside-escapes —
   physical, and it conserves per-vertex energy by construction.

### Sphere-integrated cross-check (oracle, uniform-sphere MC vs the walk R/T)
| r | μ | walk R/T | eval R/T | errR/errT | 99.9-pct | max |
|---|---|----------|----------|-----------|----------|-----|
|0.85|0.1|0.078/0.922|0.079/0.965|+1%/+5%|2.5|4.7|
|0.85|0.5|0.033/0.967|0.032/1.024|−1%/+6%|3.4|5.3|
|0.85|0.9|0.021/0.979|0.020/1.015|−2%/+4%|5.3|6.1|
|1.00|0.1|0.064/0.936|0.064/0.964|−1%/+3%|2.1|4.2|
|1.00|0.9|0.014/0.986|0.014/1.026|+0%/+4%|3.1|4.8|

Reflection matches to ±5% at every grid point; transmission to ±6% at r≥0.85.
The larger errT at r≤0.5, high μ (e.g. r0.5/μ0.9 +22%) is **uniform-sphere
integration variance** on the near-specular BTDF lobe (stderr ~0.1–0.3, R+T
consistent with 1 within 1–1.4σ), not eval bias — the eval value is confirmed
correct by (a) order-0 = single-scatter walk exactly, (b) ∫p dω = 1, and (c) the
per-direction hemisphere split matching the sampler. A ±2% low-roughness gate
needs an importance-sampled integrator (sample ω near the refraction direction);
uniform-sphere MC cannot reach ±2% there at feasible sample counts.

## Phase 10 — the stochastic eval is wired into both glass lobes (2026-09-09)

The lead's decision on PR #778 (issuecomment-5593645050): replace the Phase 5
skip-NEE delta contract — unbiased, but it moved the pkg263 harness limb from
1.05× to 0.60× of Cycles — with the paper's own stochastic evaluation on
`eval()`/`evalSpectral()`, `isDelta=false`, `pdf()` = the §9 proxy.

### What was wired

| File | Change |
|---|---|
| `include/astroray/microsurface_dielectric.h` | `mix64`/`hashFloat`/`HashRng`/`hashRngFor` (the deterministic RNG) and `stochasticEvalHashed` (the material-facing entry point); `kMsEvalWalks = 1`, `kMsScatterMax = 16`. |
| `plugins/materials/principled.cpp` | `transmissionWalkScalar()`; `evalLobeRGB`/`evalLobeSpectral` `LobeKind::Transmission` (film-off) call it for BOTH the reflection and the transmission half; `sample()`/`sampleSpectral()` walk branch: `isDelta=false`, no `const_cast<HitRecord&>`, pdf = the full lobe-mixture density. |
| `plugins/materials/disney.cpp` | `glassWalkScalar()`; `eval()` transmission branch + the reflection term added after the `* NdotL`; `sample()` walk branch un-delta'd, pdf = `pdf(rec,wo,wi)`; `evalSpectral()` magnitude-factored (see the bug below). |
| `include/raytracer.h`, `module/blender_module.cpp` | `set_light_nee(bool)` — the lamp twin of pkg258's `set_env_nee`, so the same scene can be rendered with and without the light-sampling strategy. |
| `tests/test_pkg265_nee_invariance.py` | The three NEE on/off gates (15 tests). |
| `tests/cpp/test_pkg265_eval_vs_walk.cpp` | Engine-side integral(eval) = walk R/T cross-check. |

`pdf()` needed no change: `transmissionPdf` (principled) and the
`transmission_ * firstBouncePdf` term (disney) were already the §9 proxy.

### The RNG — pbrt-v4's `LayeredBxDF` pattern (CLAUDE.md §6)

`Material::eval()` is `const`, called from OpenMP workers, and may be asked for
the same direction pair more than once, so a stochastic eval must be a PURE
function of its arguments. pbrt-v4 solves exactly this for its own stochastic
evaluation, `LayeredBxDF::f` / `LayeredBxDF::PDF` (`src/pbrt/bxdfs.h`,
**Apache-2.0**): `RNG rng(Hash(wo), Hash(wi))`. We reproduce the *construction*,
not pbrt's code:

* bit mixer — **splitmix64** (Steele/Lea/Flood, "Fast splittable pseudorandom
  number generators", OOPSLA 2014; Vigna's reference implementation is public
  domain), over the raw float bits of (wo, wi, alpha, ior, side);
* stream — **PCG32-XSH-RR** (M. E. O'Neill, "PCG: A Family of Better Random
  Number Generators", 2014, pcg-random.org, **Apache-2.0**).

Both are licence-compatible with MIT. No `STOP` was required.

### The eta² radiance factor in closed form

`stochasticEval` estimates the walk's escape DENSITY p(wi): the paper's phase
functions are normalised in direction space (integral of p over the sphere = 1)
and carry no radiance compression, which the sampler instead accumulates per
micro-refraction as `WalkSample::radianceScale`. That product telescopes (proved
in `tests/cpp/test_pkg265_walk_eta.cpp`: reflected 1.0, entering 1/ior² =
0.47562, exiting ior² = 2.10250, maxErr 0.00e+00 over 1.6 M walks), so for a
FIXED query direction it is fully determined by `sign(wiLocal.z)`.
`stochasticEvalHashed` applies it analytically, which keeps `eval()` and
`sample()` on the same units (`sample()`: f/pdf = weight·tint·radianceScale).

### MIS-weight consistency (the reason `sample()` changed too)

With `isDelta=false` the emitter-hit leg is weighted by `w_B(bsdfPdfPrev)` and
the NEE leg by `w_L(pdf(rec,wo,wi))`. These sum to 1 pointwise only if BOTH read
the same density at the same direction. `sample()` previously reported the
single-lobe density `q_j·p_j`, while `pdf()` returns the full mixture — harmless
under the delta contract (NEE was skipped), a dark bias once NEE runs on a MIXED
material. `sample()`/`sampleSpectral()` now report the mixture and rescale `f`
so `f/pdf = through/q_j` is bit-unchanged. For pure glass (q_j = 1, one non-delta
lobe) the two forms are numerically identical, so no furnace number moved.

### Bug found by the gate: the Disney Jakob–Hanika albedo clamp

`DisneyPlugin::evalSpectral` upsampled the RGB eval through
`RGBAlbedoSpectrum`, whose argument is **clamped to [0,1]³**. The Heitz eval is
a heavy-tailed estimator with per-sample values up to ~40, so its tail was
silently truncated: the Disney reflection probe read **28% DARK** with NEE on
versus the same scene NEE off (r0.5). Fixed by factoring the magnitude out
before the upsample — the identical guard `sampleSpectral()` twenty lines below
already applies (#404, memory `gpu-dielectric-lowers-to-closure-graph`). It is
a no-op for any eval <= 1, i.e. for every previously-correct lobe.

### Confound that had to be ruled out first: adaptive sampling

Adaptive sampling is **ON by default** (`useAdaptiveSampling = true` in
`blender_module.cpp`). Its stop metric is colour-blind and sample-count
dependent (pkg237), so it stops the noisier NEE-off leg early: with adaptive ON
the pkg263 repro read NEE-off **4–11% darker** at 512 spp; with it OFF the same
cells agree to <= 1.24%. Every A/B in this phase pins
`set_adaptive_sampling(False)` and renders linear.

### NEE ON/OFF invariance (`tests/test_pkg265_nee_invariance.py`, 15/15 green)

CPU, 6 seeds per leg, adaptive off, linear. Tolerance max(2 sigma, 2% of the mean).

| gate | NEE-on | sem | NEE-off | sem | delta | tol |
|---|---|---|---|---|---|---|
| refl-probe principled r0.3 | 0.00668 | 0.00006 | 0.00656 | 0.00015 | +1.84% | 4.81% |
| refl-probe principled r0.5 | 0.01156 | 0.00009 | 0.01184 | 0.00013 | −2.43% | 2.70% |
| refl-probe principled r0.85 | 0.02147 | 0.00022 | 0.02139 | 0.00018 | +0.36% | 2.65% |
| refl-probe disney r0.3 | 0.00667 | 0.00005 | 0.00653 | 0.00015 | +2.14% | 4.69% |
| refl-probe disney r0.5 | 0.01141 | 0.00008 | 0.01169 | 0.00013 | −2.37% | 2.67% |
| refl-probe disney r0.85 | 0.02104 | 0.00020 | 0.02092 | 0.00017 | +0.59% | 2.53% |
| lit-furnace principled r0.3 | 0.99435 | 0.00049 | 0.99450 | 0.00018 | −0.02% | 2.00% |
| lit-furnace principled r0.5 | 0.99467 | 0.00074 | 0.99499 | 0.00047 | −0.03% | 2.00% |
| lit-furnace principled r0.85 | 0.99452 | 0.00028 | 0.99447 | 0.00053 | +0.00% | 2.00% |
| lit-furnace disney r0.3 | 0.99330 | 0.00049 | 0.99345 | 0.00018 | −0.01% | 2.00% |
| lit-furnace disney r0.5 | 0.99159 | 0.00074 | 0.99189 | 0.00047 | −0.03% | 2.00% |
| lit-furnace disney r0.85 | 0.98387 | 0.00030 | 0.98374 | 0.00051 | +0.01% | 2.00% |
| pkg263 r0.3 centre | 0.18737 | 0.00076 | 0.18656 | 0.00116 | +0.43% | 2.00% |
| pkg263 r0.3 limb | 0.45053 | 0.00312 | 0.44010 | 0.00552 | +2.32% | 2.81% |
| pkg263 r0.5 centre | 0.27353 | 0.00190 | 0.27101 | 0.00325 | +0.92% | 2.76% |
| pkg263 r0.5 limb | 0.61338 | 0.00253 | 0.60810 | 0.00565 | +0.86% | 2.02% |
| pkg263 r0.85 centre | 0.54374 | 0.00273 | 0.54228 | 0.01097 | +0.27% | 4.16% |
| pkg263 r0.85 limb | 0.68580 | 0.00192 | 0.68193 | 0.00550 | +0.56% | 2.00% |
| pkg263 background (every r) | 0.17890 | 0.00014 | 0.17890 | 0.00014 | +0.00% | 2.00% |

Every lit-furnace value is in [0.97, 1.02] on BOTH legs. The pkg263 leg is the
metal_ab glass geometry rebuilt in-process; its calibration check is roughness 0,
where it reads centre 0.175 / limb 0.286 against the pkg263 Cycles reference's
0.1773 / 0.2842 (< 1.5%) — the light conversion that lands there is
radiance = P/A (150 W over a 1 m² area light). It runs at 128 spp rather than
the harness's 64 because the NEE-off leg finds a 1×1 radiance-150 light only by
BSDF sampling and is heavy-tailed: the r0.5 centre delta measures +3.44% at
64 spp, +0.42% at 128, +0.37% at 256, −0.01% at 512 (8 seeds each) —
under-convergence, not bias. A separate 16-seed 512-spp run reads r0.5 centre
+0.05% and r0.5 limb +0.96% (2.9 sigma), the residual being the eval's
grazing-angle error.

### Eval vs walk in the engine (`tests/cpp/test_pkg265_eval_vs_walk.cpp`)

Integral of `stochasticEval` over each hemisphere (900×900 stratified
directions, one hash-seeded walk each) against `sampleWalk`'s own R/T split
(200 k walks), IOR 1.45, entering:

| r | mu | walk R | walk T | eval R | eval T | errR | errT | R+T | max sample |
|---|---|---|---|---|---|---|---|---|---|
| 0.85 | 0.1 | 0.0775 | 0.9225 | 0.0775 | 0.9254 | +0.0% | +0.3% | 1.003 | 14.53 |
| 0.85 | 0.5 | 0.0321 | 0.9679 | 0.0323 | 0.9648 | +0.7% | −0.3% | 0.997 | 8.94 |
| 0.85 | 0.9 | 0.0203 | 0.9797 | 0.0203 | 0.9808 | +0.4% | +0.1% | 1.001 | 16.27 |
| 1.00 | 0.1 | 0.0641 | 0.9359 | 0.0633 | 0.9329 | −1.2% | −0.3% | 0.996 | 18.43 |
| 1.00 | 0.9 | 0.0141 | 0.9859 | 0.0141 | 0.9874 | +0.2% | +0.1% | 1.001 | 12.05 |
| 0.50 | 0.5 | 0.0643 | 0.9357 | 0.0645 | 0.9371 | +0.3% | +0.1% | 1.002 | 24.92 |
| 0.50 | 0.9 | 0.0333 | 0.9667 | 0.0334 | 0.9667 | +0.2% | −0.0% | 1.000 | 42.57 |

This supersedes the Phase 9 oracle table's ±5%/±6%: those errors were the plain
uniform-sphere estimator's variance, exactly as Phase 9 suspected; stratifying
brings the engine's own eval to within **±1.2% on R and ±0.3% on T** at every
grid point, with R+T = 0.996–1.003 (the lossless identity). Per-sample maxima
8.9–42.6 confirm the lead's 1/d² <= 1/(n_t−n_i)² bound. The scatterMax = 16 dead
fraction peaks at 0.0005% (1 walk in 200 000) at r1.0/mu0.1.

### Cost: N = 1 vs N = 4 walks per eval (`kMsEvalWalks`)

CPU, 6 seeds, same scenes as the gates; `rel sigma` is the seed-to-seed standard
error of the ROI mean.

| scene | N=1 mean | N=1 rel sigma | N=1 s/render | N=4 mean | N=4 rel sigma | N=4 s/render |
|---|---|---|---|---|---|---|
| refl-probe r0.5 | 0.01156 | 0.75% | 0.52 | 0.01154 | 0.78% | 0.60 (+15%) |
| refl-probe r0.85 | 0.02147 | 1.04% | 0.58 | 0.02152 | 0.87% | 0.70 (+21%) |
| lit-furnace r0.5 | 0.99467 | 0.074% | 0.69 | 0.99467 | 0.074% | 0.67 (−3%) |
| lit-furnace r0.85 | 0.99452 | 0.028% | 0.72 | 0.99452 | 0.028% | 0.75 (+4%) |
| pkg263 r0.85 centre | 0.54374 | 0.50% | 1.10 | 0.54097 | 0.53% | 1.19 (+8%) |
| pkg263 r0.85 limb | 0.68580 | 0.28% | 1.10 | 0.68619 | 0.24% | 1.19 (+8%) |

N = 4 buys at most a 0.17-point drop in relative sigma (refl-probe r0.85) for
8–21% more time, and moves no mean outside 1 sigma. The path-level MC already
averages the per-eval variance away, so the extra walks are largely wasted.
**Shipped N = 1**; `kMsEvalWalks` is a one-line compile-time constant if a
future gate needs more.

### Phase 8 — the pkg263 Cycles cross-check band after the stochastic eval

Unchanged pkg263 driver (`benchmarks/cycles-parity/metal_ab/harness.py --material
glass`, 256², 128 spp, CPU both engines), CPU addon restaged from this HEAD
(`build_blender_addon.py --backend cpu` → `dist/astroray/`, `ASTRORAY_PYD_DIR`
pointed there — the bare `build_blender_addon/` dir lacks the bundled runtime
DLLs). Report:
`test_results/pkg265_phase10_harness/glass_ab_report.md` (+`.json`, raw `.npy`).

Astroray/Cycles per-ROI ratio (mean of R/G/B):

| ROI | r | before (#771) | Phase 4 (walk, inconsistent eval) | Phase 6 (skip-NEE) | **Phase 10 (stochastic eval)** |
|---|---|---|---|---|---|
| centre | 0.00 | 0.963 | 0.997 | 0.997 | **0.997** |
| centre | 0.20 | 0.950 | 0.976 | 0.972 | **0.977** |
| centre | 0.50 | 0.873 | 1.076 | 0.899 | **1.089** |
| centre | 0.85 | 0.742 | 1.518 | 0.929 | **1.610** |
| limb | 0.00 | 0.815 | 0.832 | 0.832 | **0.832** |
| limb | 0.20 | 0.673 | 0.861 | 0.765 | **0.863** |
| limb | 0.50 | 0.490 | 1.019 | 0.637 | **1.041** |
| limb | 0.85 | 0.556 | 1.053 | 0.604 | **1.131** |
| background | all | ~1.00 | ~1.00 | 0.994 | **0.994** |

**The limb — the owner's named complaint — is fixed and stays fixed.** It was
0.49–0.56 of Cycles before pkg265, 0.60–0.64 under the skip-NEE contract, and is
now 1.04–1.13 at r ≥ 0.5 (and unchanged at r 0/0.2, which barely engage the
walk). The background ROI is 0.994 at every roughness — the calibration check.

**The centre over-shoots at high roughness (1.089 at r0.5, 1.610 at r0.85).**
This is the same signal the lead flagged on Phase 4 (1.518), now measured with a
consistent estimator. Three of the four hypotheses on the table are refuted by
direct measurement:

* *η² applied per micro-refraction / doubled between walk and kernel* — refuted.
  `tests/cpp/test_pkg265_walk_eta.cpp` proves the product telescopes exactly
  (maxErr 0.00e+00 over 1.6 M walks, both IOR 1.45 and 1.5), and the eval uses
  the same factor in closed form.
* *NEE double-counting on top of the walk's throughput* — refuted. The NEE
  on/off invariance gate agrees to ≤ 2.43% on 21 cells including this very
  geometry (a double count would show as a large positive NEE-on delta).
* *energy gain in the BSDF* — refuted. The lit furnace is 0.9819–0.9964 linear
  on both legs, and the eval integrates to R+T = 0.996–1.003.

What remains is a genuine **model-vs-model** divergence, and the oracle locates
it at the **exit interface**, which the Phase-1 divergence table (entry
interface only) could not see. Running the same oracle with `entering=False`
(n₁ = ior → n₂ = 1), IOR 1.45, M = 2·10⁵:

| r | μ | MS_R | MS_T | SS_R | SS_T | SS dead% | 1/E | Cycles_R | Cycles_T |
|---|---|---|---|---|---|---|---|---|---|
| 0.50 | 0.10 | 0.972 | 0.028 | 0.780 | 0.011 | 20.9 | 1.264 | 0.986 | 0.014 |
| 0.50 | 0.90 | 0.172 | 0.828 | 0.104 | 0.815 | 8.2 | 1.089 | 0.113 | 0.887 |
| 0.50 | 0.97 | 0.108 | 0.892 | 0.052 | 0.877 | 7.1 | 1.077 | 0.056 | 0.944 |
| 0.85 | 0.10 | 0.978 | 0.022 | 0.510 | 0.002 | 48.7 | 1.950 | 0.995 | 0.005 |
| 0.85 | 0.50 | 0.668 | 0.332 | 0.263 | 0.275 | 46.2 | 1.860 | 0.489 | 0.511 |
| 0.85 | 0.90 | 0.357 | 0.643 | 0.074 | 0.524 | 40.2 | 1.672 | 0.124 | 0.876 |
| 0.85 | 0.97 | 0.310 | 0.690 | 0.041 | 0.565 | 39.4 | 1.650 | 0.068 | 0.932 |

At the ENTRY interface and near-normal incidence — what the centre of the sphere
sees first — the two models agree to ~0.1% (Phase-1 table, r0.85/μ0.9: MS_T
0.980 vs Cycles_T 0.981), which is why the entry table alone predicts no centre
shift. At the EXIT interface the same cell reads MS_R **0.310** against Cycles'
**0.068** — a **4.6× internal-reflection difference** — because the exit
interface is where single scatter loses the most (dead 39–49% at r0.85, against
7–8% at r0.5) and a uniform `1/E` rescale is therefore furthest from the truth.
A solid glass sphere is entry + an arbitrary number of internal bounces + exit,
so the render-level ratio is a product of that divergence, not of the entry
table. The direction is consistent: the multiple-scattering model keeps ~4.6×
more light inside the sphere for another pass, and in this scene (bright key
light + bright ground under the sphere) that light is redistributed broadly and
a larger share of it reaches the camera through the disc.

Per the owner's 2026-09-08 physics-first rule this is **recorded as a
cross-check band, not a gate**: Astroray implements the published
multiple-scattering model, Cycles implements a `1/E` energy patch, and the
divergence is largest exactly where the patch is weakest. Settling which is
closer to ground truth needs the independent oracle of **#782** — the clean-room
oracle and the engine share the same equations, so their agreement proves
implementation fidelity, not physical truth
(memory `clean-room-oracle-is-self-consistency-not-ground-truth`).

Limb/centre ratio per engine (self-referential shape check): Cycles
1.602/1.754/1.956/1.736 at r 0/0.2/0.5/0.85, Astroray
1.337/1.550/1.872/1.221 — Astroray tracks Cycles' shape to within 6% up to
r 0.5 and then flattens, the shape signature of the over-bright centre.

**Contact sheets** (`_stoch` suffix, alongside the Phase-4 and `_evalfix`
sheets, force-added — `*.png` is gitignored under `docs/`), in
`.astroray_plan/docs/pkg265/postfix_harness/`:
`glass_r000_stoch__contact_sheet.png`, `glass_r020_stoch__contact_sheet.png`,
`glass_r050_stoch__contact_sheet.png`, `glass_r085_stoch__contact_sheet.png`,
`glass_r085_stoch__cycles_roi.png`, `glass_r085_stoch__astroray_roi.png`.

Inspected (Cycles | Astroray | |Δ|×3): at r 0.85 both read as frosted glass, but
Cycles keeps a visible lower-left/upper-right shading gradient across the disc
while Astroray is flatter and brighter, and Astroray's transmitted caustic on
the ground is brighter and wider — the same signature as the 1.61 centre ratio,
i.e. excess *transmitted/redistributed* light, not a reflection difference. At
r 0.5 the two are close, with Astroray marginally brighter. Astroray remains
visibly noisier at equal 128 spp with chromatic (green/purple) speckle on the
sphere and the caustic: the stochastic walk inside the 4-wavelength hero
pipeline. r 0 matches (0.997 centre).

### GPU verification (Phase 3 is still deferred; this is a "did the CPU wiring break it" check)

`include/astroray/gpu_materials.h`, `src/gpu/` and `src/cpu/` are byte-identical
to `origin/main` on this branch, so the GPU glass lobe is still the pkg264 #771
reroute stub. CUDA build (`build_nosccache.bat` in the worktree, under the
orchestrator GPU lock) **exit 0**; build stamp `sha=1c76af36ee2d` == HEAD,
`arch-verify OK ... embeds sm_120`, canary caps read back.

`pytest tests -q -m gpu --ignore=tests/wavefront_diff` on the RTX 5070 Ti:
**2 failed, 737 passed, 24 skipped, 11 xfailed, 1 xpassed, 1978 deselected.**
The first pass (before the Disney narrowing and the xfail) read 4 failed / 736
passed / 10 xfailed. Attribution of all four:

| test | verdict |
|---|---|
| `test_pkg219d_scalar_param_textures::test_cpu_gpu_roughness_parity` | **was ours, fixed.** The first Disney JH fix factored the magnitude for EVERY lobe, un-clamping a metallic (transmission = 0) specular eval: CPU 0.0623 vs GPU 0.0425, ratio 0.682 in a [0.80, 1.25] band. Narrowed to the walk term only (`evalSplit`), passes again. |
| `test_pkg265_lit_furnace::test_principled_lit_furnace_conserves_gpu` | **ours, xfail(strict=True).** The GPU stub conserves to r0.2 0.9958 / r0.5 0.9688 / r0.85 0.9612 / r1.0 0.9570, outside the [0.97, 1.02] band the CPU walk meets (0.9936–0.9964). The GPU-walk PR must delete the marker. |
| `test_pkg188_transmission_colour_upsample_parity[coat_over_tinted_glass]` | **branch-level, pre-dates Phase 10** (table below). |
| `test_blender_parity_harness::test_backdrop_is_parity_safe` | **environment.** `H._pyd_dir()` picks `build_blender_addon/` and ignores `ASTRORAY_PYD_DIR`; the Phase-8 harness needs a CPU (OpenMP-OFF) addon there, and this test then asks it for GPU → "GPU requested but no CUDA GPU is available". Restored by re-running `build_blender_addon.py --backend cuda` after the harness. |

**pkg188 attribution** ([[verify-attribution-with-a-baseline-build]] — three CPU
builds, the GPU value being invariant across the branch at R mean 0.06230):

| source | CPU R mean | GPU/CPU R | band [0.95, 1.05] |
|---|---|---|---|
| `origin/main` | 0.06217 | 1.0022 | PASS |
| `73797ed7` (branch, pre-Phase-10, skip-NEE) | 0.04782 | 1.3027 | FAIL |
| this HEAD (Phase 10) | 0.04951 | 1.2583 | FAIL, 4.4 points closer |

So the failure is the Phase-2 CPU/GPU divergence (CPU multiple-scattering walk vs
GPU single-scatter + reroute) and cannot close before Phase 3. It is left
**failing rather than silently xfail'd**. One observation for the reviewer: this
mixed case (`transmission_weight` 0.8 + coat) is the only row of that test whose
CPU value moved far from main (−20%); the two pure-glass rows moved +1…+4% and
still pass. Worth a look when Phase 3 lands, in case the mixture weighting on a
partly-transmissive Principled hides a second effect.
