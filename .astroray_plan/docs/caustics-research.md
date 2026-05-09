# pkg64 — Caustics research note (literature pass for prism-accurate rendering)

**Status:** project-owner answers received 2026-05-09. Recommendation revised: **SMS code skeleton (BSD-3) + per-wavelength Newton extension from the MNEE paper.** Implementation pending capacity.
**Author:** Claude Code, 2026-05-09.
**Policy:** [CLAUDE.md §6](../../CLAUDE.md) — no invented algorithms.

---

## Executive summary

The user's primary goal is *"place a prism in front of a light, get an
accurate rainbow cascade behind it."* Astroray already has the physical
basis for this: a spectral path tracer (pkg11/pkg14), Sellmeier
dispersion (pkg31), and a prism validation scene (pkg29). What's
missing is **caustic-finding sampling** — without it, refractive
caustic paths are found by brute-force unidirectional path tracing,
which converges so slowly that the rainbow only appears after tens of
thousands of samples per pixel.

This note evaluates four published techniques for accelerating caustic
convergence and (after the project owner's 2026-05-09 sign-off) recommends:

> **Use the BSD-3-Clause SMS reference code as the implementation
> skeleton, extended with the per-wavelength Newton-iteration math
> from the MNEE paper.** This satisfies all four owner answers
> (reflective caustics in scope, opt-in caster UX, both numerical and
> visual gates, MIT-compatible licensing).

The license analysis below explains why the original "port from
Cycles' MNEE" recommendation is no longer viable.

---

## The four candidates

### 1. Manifold Next Event Estimation (MNEE) — *recommended primary*

- **Paper:** Hanika, Droske, Manakov, "Manifold Next Event Estimation",
  Computer Graphics Forum 34(4) — Eurographics Symposium on Rendering
  (EGSR) 2015. **DOI: 10.1111/cgf.12681.**
  ([RGL/EG digital library](https://diglib.eg.org/items/8c90eb94-3232-4136-9b24-0d7d896399de),
  [Wiley](https://onlinelibrary.wiley.com/doi/10.1111/cgf.12681))
- **What it does:** at NEE (next event estimation) time, instead of
  shooting a straight shadow ray to the light, finds the point on a
  refractive surface chain where Fermat's principle holds — i.e. the
  point through which a refracted ray actually reaches the light.
  Solves the half-vector constraint via a pseudo-Newton iteration on
  the manifold of valid specular bounces.
- **Production-tested reference:** **Cycles ships MNEE as of Blender
  3.2** (Olivier Maury, patch D13533), as the *Shadow Caustics* feature.
  ([Blender 3.2 release notes](https://developer.blender.org/docs/release_notes/3.2/cycles/),
  [BlenderNation 2022 announcement](https://www.blendernation.com/2022/04/11/fast-shadow-caustics-coming-to-blender-3-2/))
  Sharp refractive caustics in <100 spp instead of 1000s. Limitations:
  refractive shadows only, ≤4 bounces, smooth normals required.
- **Wavelength compatibility:** **direct.** The Newton iteration uses
  the per-ray sampled wavelength's IOR. Combined with Astroray's
  existing Sellmeier dispersion, each spectral sample finds its own
  wavelength-correct caustic path. Prism rainbow falls out for free.
- **License of the Cycles reference:** **GPL-2.0-or-later** (Blender's
  blanket license). See "License question" below.
- **Why this is the right primary:** every requirement maps directly:
  prism (refractive), spectral (per-wavelength Newton), Astroray
  already has Sellmeier dispersion, the algorithm has been validated
  in shipping production renderer.

### 2. Specular Manifold Sampling (SMS) — *strong secondary*

- **Paper:** Zeltner, Georgiev, Jakob, "Specular Manifold Sampling for
  Rendering High-Frequency Caustics and Glints", ACM Transactions on
  Graphics 39(4) — SIGGRAPH 2020. **DOI: 10.1145/3386569.3392408.**
  ([RGL project page](https://rgl.epfl.ch/publications/Zeltner2020Specular),
  [paper PDF](https://rgl.s3.eu-central-1.amazonaws.com/media/papers/Zeltner2020Specular.pdf))
- **Reference implementation:** [tizian/specular-manifold-sampling](https://github.com/tizian/specular-manifold-sampling)
  on GitHub, built on **Mitsuba 2**. **License confirmed BSD 3-Clause**
  (`Copyright (c) 2017 Wenzel Jakob`).
- **What it does:** unifies caustic and glint rendering. More general
  than MNEE — handles reflective caustics, rough microfacet surfaces,
  and high-frequency normal-mapped detail. Works with both biased and
  unbiased modes.
- **Wavelength compatibility:** **not direct.** The SMS paper does not
  address dispersion explicitly; the implementation is RGB. A spectral
  extension is plausible (per-wavelength manifold solve, same
  structure as MNEE) but is research work — we'd be the first to
  publish it.
- **Why this is secondary:** more powerful but more code, and the
  prism-rainbow benefit comes from the manifold solve being
  per-wavelength, which MNEE already gives us at lower complexity.
  SMS becomes the right primary if/when we want **reflective
  caustics on rough surfaces** (e.g. a rough metal mirror pool) —
  scope beyond pkg64.
- **Follow-up worth tracking:** *Batch SMS* (Springer Visual Computer
  2025, [link](https://link.springer.com/article/10.1007/s00371-025-03955-0))
  reports significant speedups; revisit if SMS becomes primary.

### 3. Photon mapping — *fallback only*

- **Paper:** Jensen, "Global Illumination using Photon Maps",
  Eurographics Workshop on Rendering 1996. ([Jensen author page](http://graphics.ucsd.edu/~henrik/papers/photon_map/),
  [original PDF](https://graphics.stanford.edu/~henrik/papers/ewr7/egwr96.pdf))
- **Status:** old (1996), well-understood, simple. Two-pass: trace
  photons from lights, build kd-tree, gather at shading time.
- **Wavelength compatibility:** straightforward — store wavelength on
  each photon. Caustic photons + spectral path tracer is the original
  approach for prism rainbows in research code.
- **Open-source references:** no single canonical BSD-licensed
  implementation. Many academic / hobbyist GitHub repos exist of
  varying quality. RenderPark (K.U. Leuven, 1996-2001) is the
  closest open-source production implementation; license unverified.
- **Why this is fallback only:** introduces a separate data structure
  (photon kd-tree), adds memory cost (millions of photons for
  production scenes), and converges noisily without density
  estimation tricks (gradient-domain photon mapping, etc.). MNEE
  gives sharper results in fewer samples for the refractive case
  Astroray cares about.
- **When we'd reach for it:** complex multi-bounce caustics through
  rough refractive media where MNEE's Newton iteration fails to
  converge. Phase-3 fallback, not primary.

### 4. Path-space MLT with manifold mutations (MMLT) — *out of scope*

- **Paper:** Jakob, Marschner, "Manifold Exploration: A Markov Chain
  Monte Carlo Technique for Rendering Scenes with Difficult Specular
  Transport", SIGGRAPH 2012.
- **Status:** powerful but heavy — adds Markov-chain machinery and
  loses temporal stability. Hanika et al. 2015 explicitly cite MMLT
  as the technique they wanted to avoid the instability of.
- **Recommendation:** out of scope for pkg64. MMLT is not necessary
  to get a clean prism rainbow.

---

## Supporting technique: Hero Wavelength Spectral Sampling

Worth flagging for the implementation phase even though it's not new:

- **Paper:** Wilkie, Nawaz, Droske, Weidlich, Hanika, "Hero Wavelength
  Spectral Sampling", Computer Graphics Forum 33(4) — EGSR 2014.
  **DOI: 10.1111/cgf.12419.** ([CGG Charles University](https://cgg.mff.cuni.cz/publications/hero-wavelength-spectral-sampling/),
  [DL.ACM](https://dl.acm.org/doi/10.1111/cgf.12419))
- **What it does:** propagates a small constant number of wavelengths
  per ray; one "hero" wavelength is sampled randomly, additional
  wavelengths are placed at equal distances. All directional sampling
  is based on the hero. Used by Mitsuba, Cycles, PBRT v4, and Astroray
  (`SampledWavelengths` from pkg10 — 4 samples).
- **Why it matters here:** when MNEE is wrapped around hero-wavelength
  sampling, the Newton iteration must use the hero's IOR, but the
  *result* is integrated using all 4 wavelengths via spectral MIS.
  This is the mechanism that turns the manifold solve into a
  wavelength-stratified prism rainbow without per-wavelength path
  duplication.
- **Astroray status:** already implemented (pkg10 + pkg11). pkg64
  does not need to re-derive it.

---

## License analysis — resolved 2026-05-09

Astroray's [`LICENSE`](../../LICENSE) declares the project as
**MIT License (Copyright © 2026 HendrikGC02)**.

**MIT cannot consume GPL-2.0+ code.** GPL is "viral": derivative works
must be re-licensed GPL. Direct ports of Cycles' MNEE
(`intern/cycles/kernel/integrator/mnee.h` and friends) into the MIT
Astroray codebase would either re-license Astroray as GPL (a breaking
change for any current/future consumer) or constitute a license
violation. Neither is acceptable.

Project-owner clarification 2026-05-09: *"Use your own discretion on
how to handle the Cycles MNEE implementation, ideally it would be
best to use as much as is rather than rederiving."*

**Resolution: use SMS code (BSD-3-Clause), not Cycles MNEE.**

- **SMS** is BSD-3-Clause (verified by fetching
  `github.com/tizian/specular-manifold-sampling/blob/master/LICENSE` —
  *Copyright © 2017 Wenzel Jakob*). BSD-3 is **MIT-compatible**: we
  can include the SMS source files directly under their original
  BSD-3 header, preserve the copyright notice, and link the result
  into our MIT codebase without any re-licensing.
- **MNEE paper math is free to read and re-derive.** The Hanika et al.
  2015 paper itself is academic publication, not GPL — re-deriving
  the per-wavelength Newton solver from the paper is fine. Reading
  Cycles' MNEE source for "what does it do at runtime" behavior
  inspection (e.g. the `caustic_caster` flag) is also fine, as long
  as we do not copy code patterns directly.

**Practical division of sources:**

| What | Source | License at point of use |
|---|---|---|
| Newton-iteration scaffolding | SMS reference code (Mitsuba 2) | BSD-3 (kept verbatim header) |
| Reflective + refractive + glint manifold logic | SMS | BSD-3 |
| Per-wavelength solve (use sampled λ's IOR in the half-vector residual) | Hanika 2015 paper §3-5 | Re-derived from paper |
| Caustic-caster opt-in UX pattern | Cycles behavior, no code copy | None — we only copy the *idea* |
| Spectral integration + Sellmeier dispersion | Astroray pkg10/pkg11/pkg31 | Existing MIT |

---

## Recommended scope for pkg64 (post-sign-off)

The four 2026-05-09 owner answers are folded in here. Scope grew vs
the pre-sign-off draft because reflective caustics moved in — which
is exactly what made SMS the right code source, since SMS handles
both refractive and reflective uniformly.

1. **Vendor SMS reference code.** Drop the relevant SMS
   single-scattering and multi-scattering manifold files into
   `external/sms/` (or equivalent), preserving the BSD-3 header.
   Add a third-party-licenses note. SMS handles refractive,
   reflective, and (later) glint paths uniformly — the user's
   confirmed in-scope set.
2. **Astroray adapter layer.** Map SMS's `Mitsuba 2`-shaped types to
   Astroray's `HitRecord`, `Vec3`, `Material::sample`, etc. Thin
   wrapper, no re-implementation.
3. **Per-wavelength Newton iteration.** Replace SMS's RGB residual
   with a wavelength-aware residual: at each Newton step, query the
   IOR using the *sampled hero wavelength* (Astroray
   `SampledWavelengths` from pkg10) instead of a fixed RGB IOR.
   Re-derived from Hanika et al. 2015, §3-5 — paper math, no Cycles
   code. This is what produces the prism rainbow.
4. **Caustic-caster opt-in UX.** Mirror Cycles: per-object boolean
   property (`object.astroray.is_caustic_caster`). Only objects
   flagged as casters trigger SMS sampling. Saves perf when caustics
   aren't relevant; matches Cycles workflow so a Cycles user
   transitions naturally.
5. **Default-path-tracer integration.** Wire SMS as an MIS strategy
   inside `path_tracer` when `use_refractive_caustics` or
   `use_reflective_caustics` is True. Keep `caustic_path_tracer` as a
   registered regression baseline.
6. **Acceptance gates — both numerical AND visual.** Owner confirmed
   *both* are wanted unless one is too expensive:
   - **Numerical (cheap):** per-channel centroid spread ≥ 1.5× the
     no-caustic baseline on the prism scene; PSNR ≥ 28 dB vs the
     reference render at the matched spp.
   - **Visual (cheap because we already render reference PNGs):**
     pixel-diff or SSIM ≥ 0.95 vs `tests/reference/prism_rainbow_*.png`.
   Both fit in the existing test infrastructure. Including both.

**Out of scope** for pkg64 (each is its own follow-up):

- GPU port — sits behind pkg54 wavefront (or a megakernel SMS port);
  CPU first.
- Glint rendering on rough microfacet normal-mapped surfaces —
  SMS supports it but the use case is different from prism caustics.
- SMBS / Batch SMS speedups — phase 2 if convergence is unsatisfactory.

---

## Implementation pointers

The path is now **single-rooted** (SMS code + spectral extension):

- **SMS reference layout** (relevant files in
  [`tizian/specular-manifold-sampling`](https://github.com/tizian/specular-manifold-sampling)):
  - `src/integrators/sms_*.cpp` — caustic SMS integrators (single,
    multi, combined). These are the algorithmic skeleton.
  - `src/libcore/manifold.cpp` (or equivalent) — Newton-iteration core.
  - `src/libcore/glints.cpp` — glint variant (out of scope for
    initial pkg64 but worth keeping intact for the future).
- **Mitsuba 2 → Astroray type mapping**: SMS uses Mitsuba's
  `SurfaceInteraction3f`, `Vector3f`, `BSDF::sample` etc. The adapter
  layer converts these to `HitRecord`, `Vec3`, `Material::sample`.
  Thin shim, no algorithmic changes.
- **Per-wavelength residual** (the only real new code): replace any
  RGB IOR / refraction in the SMS Newton inner loop with a
  wavelength-aware version using:
  - Wavelength = the hero wavelength of the current
    `SampledWavelengths` (pkg10).
  - IOR = `Sellmeier(λ_hero)` from pkg31's `SellmeierDielectric`.
  - Reference: Hanika et al. 2015 §4 (the half-vector residual is
    `h(λ) = 0` where `h` depends on the wavelength-specific IOR).
- **Caustic-caster property**: add `is_caustic_caster: BoolProperty`
  to the addon's per-object Astroray panel. Convert it to a flag on
  `Hittable` (or the material) in C++.
- **Validation** = `tests/scenes/prism_reference.py` (pkg29) at 256
  spp, `use_refractive_caustics=True`. Plus a new mirror-pool scene
  for the reflective-caustic acceptance gate.
- **Attribution requirements** per CLAUDE.md §6 + the SMS BSD-3
  notice: every vendored SMS file keeps its original copyright
  header; a top-level `external/sms/README.md` summarizes attribution
  and points at the upstream repo + paper DOI.

---

## Sources

- [Specular Manifold Sampling — RGL EPFL project page](https://rgl.epfl.ch/publications/Zeltner2020Specular)
- [Specular Manifold Sampling — paper PDF](https://rgl.s3.eu-central-1.amazonaws.com/media/papers/Zeltner2020Specular.pdf)
- [Specular Manifold Sampling — reference code (BSD-3, GitHub)](https://github.com/tizian/specular-manifold-sampling)
- [Manifold Next Event Estimation — EG digital library](https://diglib.eg.org/items/8c90eb94-3232-4136-9b24-0d7d896399de)
- [Manifold Next Event Estimation — Wiley](https://onlinelibrary.wiley.com/doi/10.1111/cgf.12681)
- [Cycles MNEE patch landing in Blender 3.2 — release notes](https://developer.blender.org/docs/release_notes/3.2/cycles/)
- [Cycles MNEE feature announcement — BlenderNation](https://www.blendernation.com/2022/04/11/fast-shadow-caustics-coming-to-blender-3-2/)
- [Hero Wavelength Spectral Sampling — CGG Charles University](https://cgg.mff.cuni.cz/publications/hero-wavelength-spectral-sampling/)
- [Hero Wavelength Spectral Sampling — DL.ACM](https://dl.acm.org/doi/10.1111/cgf.12419)
- [Jensen 1996 photon mapping — author page](http://graphics.ucsd.edu/~henrik/papers/photon_map/)
- [Jensen 1996 photon mapping — original PDF](https://graphics.stanford.edu/~henrik/papers/ewr7/egwr96.pdf)
- [Batch SMS (2025 follow-up)](https://link.springer.com/article/10.1007/s00371-025-03955-0)
- [Specular Manifold Bisection Sampling (Jhang 2022)](https://onlinelibrary.wiley.com/doi/abs/10.1111/cgf.14673) — phase-2 alternative if SMS convergence is unsatisfactory
- [SMS supports refractive + reflective + glint paths](https://tizianzeltner.com/projects/Zeltner2020Specular/) — confirmed via README fetch 2026-05-09
