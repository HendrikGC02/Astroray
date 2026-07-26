# pkg161 research notes — constructing a scene with a real firefly population

Written 2026-07-26 while implementing `.astroray_plan/packages/pkg161-firefly-bearing-gate-scene.md`.

**Nothing here was measured.** The implementer was explicitly barred from running
renders (no GPU access, no timing data). Everything below is (a) sourced from the
literature, (b) read out of this repository's own source, or (c) derived
analytically from (a)+(b). The numeric defaults are *design targets*, and the
scene ships with a calibration script (`scripts/verify_pkg161_firefly_scene.py`)
whose whole job is to replace them with measured values.

---

## 1. What a firefly is (definitional sources)

**Blender Manual — *Cycles ▸ Render Settings ▸ Light Paths ▸ Clamping***
(<https://docs.blender.org/manual/en/latest/render/cycles/render_settings/light_paths.html>):

> "Some light paths have a low probability of being found while contributing
> much light to the pixel, causing fireflies to be found in some pixels and not
> in others. An example of such a difficult path might be a small light that is
> causing a small specular highlight on a sharp glossy material, which we are
> seeing through a rough glossy material."

> "Clamping limits the maximum brightness any single sample can contribute. […]
> It is often useful to clamp indirect bounces separately, as they tend to cause
> more fireflies than direct bounces."

Retrieval note, for honesty: `docs.blender.org` returns HTTP 403 to this
environment's fetcher (Cloudflare). The two quotes above came back through the
web-search index rather than a direct fetch. They are consistent with the
long-standing wording of that manual section and with the Cycles source cited
below, but they have **not** been verified against a first-party fetch in this
session.

**Zirr, Hanika & Dachsbacher, "Re-Weighting Firefly Samples for Improved
Finite-Sample Monte Carlo Estimates", *Computer Graphics Forum* 37(6):410–421,
2018, DOI [10.1111/cgf.13335](https://doi.org/10.1111/cgf.13335)**
(preprint: <https://jo.dreggn.org/home/2018_fireflies.pdf>) — the standard
academic definition:

> fireflies are "samples with high contribution but low probability density"
> which "lead to excessive variance in finite-sample estimates".

That definition is the whole specification for this package's scene. A firefly
needs **two** properties simultaneously:

1. **contribution ≫ image mean** — which requires an emitter whose *radiance*
   (not power) is orders of magnitude above the scene's normal luminance level,
   i.e. a physically tiny, very bright emitter; and
2. **low probability of being sampled** — which requires that emitter to be
   **unreachable by next-event estimation**, so that only BSDF sampling can find
   it.

Property 2 is the part every existing Astroray scene fails. Every emitter in the
library is NEE-sampled and unoccluded, so its contribution is found by the
low-variance strategy on essentially every sample. That is exactly why the
measured tail across the suite is 1.04–1.82× (pkg157 hardware round, RTX 5070 Ti,
2026-07-26) rather than the tens-to-hundreds of a genuine tail.

**Clamp semantics reference** (unchanged from pkg144, restated here so this
document stands alone): Cycles `film_clamp_light`,
`src/kernel/film/light_passes.h`, Apache-2.0 — `bounce > 0` selects
`sample_clamp_indirect`, `bounce == 0` selects `sample_clamp_direct`, and a
limit of 0 disables. Astroray's port is `Renderer::clampContribSpectral`
(`include/raytracer.h:2089`) and `gpu_clampContribMW`
(`src/gpu/gpu_spectral_tables.h:158`). Full notes:
`.astroray_plan/docs/pkg144-firefly-clamp-research.md`.

---

## 2. Which transport channel in *this* engine can carry a firefly

This is the part that cannot be copied from Cycles, because Astroray's estimator
differs from Cycles' in one decisive way. Read out of the source, not assumed:

| channel | CPU site | verdict |
|---|---|---|
| BSDF ray happens to hit an emitter after a **non-delta** bounce | `include/raytracer.h:2415` | **dead** — `if (bounce == 0 \|\| wasSpecular)`; there is no BSDF-side MIS term, so the contribution is *discarded entirely* and the path breaks. (Known gap, filed as pkg120.) |
| BSDF ray hits an emitter after a **delta** bounce | `include/raytracer.h:2415-2417` | **live, unweighted, unclamped-by-default** — added at full `throughput * Le`. GPU twin: `src/gpu/wavefront/stage_advance.cu:239-243`. |
| NEE / shadow ray | `include/raytracer.h:2429-2457` | low variance by construction: power-heuristic MIS, and `1/(pdf + 0.001)` bounds the near-field singularity at 1000×. |
| Russian roulette | `include/raytracer.h:2479-2484` | **cannot produce unbounded fireflies here.** The survival probability is `p = min(0.95, XYZ.Y(throughput))`, so a surviving path is renormalised to `Y(throughput) == 1` — the boost is self-limiting, not compounding. A further always-on cap (`throughput.maxValue() > 10 → rescale`, `raytracer.h:2528-2530`, GPU twin `stage_advance.cu:649-651`) bounds it again. |

**Conclusion: the only unbounded-variance channel in this engine is
`diffuse → delta-specular → emitter`.** The scene must be built around that one,
and the emitter must be invisible to NEE so the channel is the *only* route to
its energy.

In Heckbert's (1990) light-path notation this is the `L S D E` class — a light
seen through a specular vertex from a diffuse vertex, which next-event estimation
cannot connect to by construction (a delta vertex has zero probability of lying
on a shadow ray).

### Two constraints this implies, both of which bit during design

* **The camera must not reach the emitter through any delta chain either.** A
  small emitter with radiance ~2400 seen through/reflected off a glass sphere
  produces a *deterministic* few-pixel feature at ~10²–10³× the image mean. That
  would set `peak` without a single firefly being involved — a fake tail, and
  exactly the vacuous-pass trap pkg157 round 1 fell into. An early draft used the
  canonical "glass ball caustic on a floor" layout and was discarded for this
  reason: a ball lens has f ≈ 1.5 R, so it must sit within ~one focal length of
  the receiver to concentrate, which puts it in frame.
* **The aperture must be sealed.** If any straight line exists from a visible
  surface to the emitter, NEE finds it, and the emitter's energy arrives as a
  *direct* (bounce-0) contribution that `clampIndirect` cannot touch — which
  destroys the clamp gate rather than enabling it.

---

## 3. The construction that satisfies both: "bright light outside a window"

```
        * emitter (tiny sphere, radiance ~10^3)      OUTSIDE the room
        |
  ======#======   opaque ceiling with a hole, hole sealed by a thin_glass pane
  |            |
  |  [] ... [] |  two ordinary ceiling area lights  -> all the bulk illumination
  |            |
  |    camera  |  looks DOWN; everything above camera height is out of frame
  |____________|  diffuse floor + walls
```

* The pane is `thin_glass` with `roughness = 0`, so
  `plugins/materials/thin_glass.cpp:71` sets `isDelta = true` and
  `:95` transmits straight through (`wi = -wo`). It is a genuine delta vertex.
  It is *not* a solid dielectric: a single `dielectric` quad is the two-quad hack
  that memory `general-photon-loop-needs-solid-glass` warns about, and a
  dielectric sphere cannot seal a square hole without either interpenetrating the
  ceiling or leaving the corners open. `thin_glass` is the material this engine
  provides for exactly this geometry.
* Shadow rays are blocked by *any* geometry (`include/raytracer.h:2437` — the BVH
  hit test is material-agnostic), so the pane makes the emitter 100 %
  NEE-invisible. Every joule it delivers arrives through the delta channel.
* The firefly path is `camera → floor (bounce 0, diffuse) → pane (bounce 1,
  delta) → emitter (bounce 2)`. `bounce == 2 > 0`, so the contribution is
  **indirect** and lands squarely under `clampIndirect`, while the entire bulk
  image is bounce-0 NEE under `clampDirect`. The two halves of pkg157's gate are
  therefore cleanly separated by construction rather than by luck.

### Why the emitter is *outside* rather than a lens *inside*

Because it makes the two things the gate needs into two **independent, monotone,
analytically invertible knobs**, which is the only way to calibrate blind:

Let `L_e` be the emitter radiance, `r_e` its radius, `spp` the sample count,
`N` the pixel count, `μ` the image mean luminance, `k = p99.9 / μ` for the
*normal* (non-firefly) population, `n_ff` the number of firefly pixels,
`R = peak / p99.9` the tail ratio, and `s` the share of image energy carried by
the firefly channel.

```
  R    ∝ L_e / spp                    (firefly magnitude = throughput · L_e / spp)
  n_ff ∝ N · spp · r_e^2              (hit rate ∝ emitter solid angle ∝ r_e^2)
  s    =  n_ff · R · k / N   ∝  r_e^2 · L_e
```

So:

* **`L_e` alone sets the tail ratio `R`.**
* **`r_e` alone sets the firefly *count* (and hence `s`) at fixed `R`.**
* `spp` trades `R` against `n_ff` along the invariant `n_ff · R = s · N / k`.

Two renders are therefore sufficient to solve for both constants exactly; that
is what the calibration script does.

### The design window, and why it is narrow

Three constraints act at once:

1. `R ≥ 10` — the spec's bar (contract item 2).
2. `n_ff ≤ 0.001 · N` — otherwise the 99.9th percentile lands *inside* the
   firefly population and `R` collapses to ~2 (all fireflies from a single
   mechanism have nearly the same magnitude `throughput · L_e / spp`, so the top
   0.1 % would just be the double-hit pixels).
3. `s < 0.02` — pkg157's energy half asserts the mean moves < 2 % when the clamp
   binds, and the energy a p99.9 clamp removes *is* `s`.

Combining 1 and 3 through the invariant: `n_ff ≤ s·N/(k·R) ≤ 0.02·N/(10k)`.
With `k ≈ 1.4` that is `n_ff ≲ 1.4e-3 · N`, and reliability needs `n_ff ≳ 8`
(Poisson: `P(n_ff = 0) < 4e-4`), so **`N ≳ 6000` pixels minimum, and comfortably
`N ≳ 5e4`**. Because `n_ff ∝ N · spp`, the firefly count is directly proportional
to total render cost: ~10 fireflies costs ~5 × 10⁶ primary samples at these
targets. That is trivial on the wavefront and expensive on the CPU, which is why
the CPU leg of the gate renders the same scene with a deliberately enlarged
emitter (`CPU_EMITTER_RADIUS_SCALE`) — enlarging `r_e` raises the *rate* and
leaves the *ratio* untouched, so the CPU leg measures the same phenomenon at a
tenth of the cost.

**This is the one place where pkg161's contract has real internal tension, and it
should be stated in the spec rather than discovered again later:** the `≥ 10×`
tail bar and the `< 2 %` energy bar together pin the firefly *population size* to
a band roughly one decade wide. The hidden-emitter construction is what makes
that band reachable, because `s` becomes a dialled constant instead of an
emergent property of lens geometry.

---

## 4. Numeric design targets (unmeasured — these are the numbers to replace)

Derived from the relations above with: floor/wall albedo 0.73, two 0.9 × 1.1 m
ceiling lights at radiance 15 (matching `tests/base_helpers.py`'s Cornell
convention), room 4 × 4 × 3 m, emitter 0.6 m above a 0.5 × 0.5 m ceiling
aperture, throughput at the emitter hit ≈ 0.66, `μ ≈ 0.6`, `k ≈ 1.4`,
`N = 480 × 360`, `spp = 64`:

| quantity | target | source of the number |
|---|---|---|
| `EMITTER_INTENSITY` | 2400 | solves `R ≈ 30` |
| `EMITTER_RADIUS` | 0.0075 | solves `s ≈ 0.01` given the above |
| expected `peak / p99.9` | ≈ 30 | design target, **not measured** |
| expected `n_ff` | ≈ 22 | design target, **not measured** |
| expected clamp energy cost | ≈ 1 % | design target, **not measured** |

Realistic uncertainty on each of `μ`, `k`, the throughput factor, and the
aperture solid angle is a factor of ~2, which compounds to roughly ±3–5× on both
`R` and `s`. The calibration script prints the corrected constants directly.

### Light-selection sanity check (checked in source, not measured)

`LightList::add` (`include/raytracer.h:1183-1192`) weights the NEE selection CDF
by `luminance(emittedRadiance) × boundingBox.area()`. For the hidden emitter that
is `2400 × 24 r_e² ≈ 3.2`; for the two room lights it is `15 × 7.92 ≈ 119`. So
the always-occluded emitter absorbs ≈ 2.6 % of NEE samples — wasted shadow rays,
but nowhere near the "tiny super-bright light hijacks the CDF and the room goes
black" failure mode that a radiance-only weighting would have produced.

### Adaptive sampling must be off

`include/raytracer.h:3001-3007`: the CPU render loop's adaptive mode is an
*early-out* — a pixel stops once its running relative standard deviation drops
below 1 %. Quiet pixels therefore take fewer than `spp` samples and normalise by
their own count. Applied to this scene that (a) reduces the number of chances a
caustic-region pixel gets to catch a firefly and (b) makes a caught firefly's
magnitude depend on *when* it was caught. Both corrupt the statistic the scene
exists to produce, and neither applies on the GPU wavefront, so it also breaks
CPU/GPU comparability. `build_scene()` calls `set_adaptive_sampling(False)`.

### Measurements must be linear

`module/blender_module.cpp:1803-1811`: `render(..., apply_gamma=True)` (the
**default**) does `pow(clamp(c, 0, 1), 1/2.2)`. The clamp to 1.0 annihilates
precisely the outliers being measured. Every tail measurement in this package
passes `apply_gamma=False`, and
`test_pkg161_firefly_scene_tail.py::test_tail_metric_discriminates` asserts that
the gamma path *does* destroy the tail, so the convention cannot be silently
flipped later. Memory: `gamma-furnace-cannot-detect-energy-gain`.

---

## 5. Licences

| source | licence | how used |
|---|---|---|
| Blender Manual (light-paths / clamping) | CC-BY-SA 4.0 | two short quotations, attributed |
| Cycles `src/kernel/film/light_passes.h` | Apache-2.0 | clamp semantics, already ported in pkg144/pkg157; no new code taken |
| Zirr et al. 2018 (CGF) | © Eurographics/Wiley | definition quoted and attributed; no code or data used |

No code was copied from any of these. The scene is an original arrangement of
this repository's own primitives, built to satisfy a definition taken from the
literature.
