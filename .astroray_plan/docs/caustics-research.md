# pkg64 — Caustics research note (literature pass for prism-accurate rendering)

**Status:** awaiting project-owner sign-off before pkg64 implementation begins.
**Author:** Claude Code, 2026-05-09 literature pass.
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
convergence, recommends one (**Manifold Next Event Estimation,
modeled after Cycles' implementation**), and flags open questions for
project-owner sign-off before any code is written.

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

## License question — **needs project-owner answer before code**

Cycles' MNEE implementation is **GPL-2.0-or-later**. Astroray's
license is not declared in any file I've checked in the repo
(`grep -i "license\|copyright" CMakeLists.txt include/raytracer.h`
turns up no obvious LICENSE.txt). Two paths:

- **(A) If Astroray is GPL-compatible** (or the project owner is
  willing to make it so): port the Cycles MNEE algorithm directly,
  citing the Cycles file paths. Minimal risk, fastest implementation,
  most production-validated.
- **(B) If Astroray must stay permissive** (Apache-2.0 / BSD / MIT):
  re-derive the Hanika et al. 2015 algorithm from the paper itself,
  cite the paper but not Cycles code. Slower to implement, same
  algorithmic result. SMS (BSD) is also viable for a re-spec at this
  point.

**This is the single decision that gates the implementation.** I will
not write code until the project owner confirms which path.

---

## Recommended scope for pkg64 (subject to sign-off)

Given the user's stated goal (prism rainbow), the existing Astroray
machinery (spectral, Sellmeier), and the MNEE-via-Cycles availability,
the recommended scope is:

1. **Phase 1: MNEE for refractive shadow caustics.** Wrap the existing
   `path_tracer` integrator with an MNEE NEE strategy when the user
   sets `use_refractive_caustics = True` and a refractive object marks
   itself as a "caustic caster" (Cycles' UI pattern). Per-wavelength
   Newton iteration uses the sampled hero wavelength's IOR. Validation
   scene: pkg29's prism, but at moderate spp (target: visible rainbow
   at 256 spp). Hard gate: per-channel centroid spread ≥ 1.5× the
   no-caustic baseline.
2. **Phase 2: fold into the default path tracer.** Drop
   `caustic_path_tracer` as a user-facing integrator (keep as a
   regression baseline). MNEE composes with ReSTIR/NEE because it's a
   light-sampling strategy, not a separate integrator.
3. **Out of scope for pkg64:** reflective caustics (need SMS or a
   reflective MNEE extension; Cycles' MNEE explicitly excludes them),
   GPU MNEE port (after pkg54), >4 refractive bounces (matches Cycles
   limitation; revisit if user has a scene that needs more).

---

## Open questions for the project owner

1. **License — A or B above?** Determines whether we port from
   Cycles directly or re-derive from the paper.
2. **"Caustic caster" UX.** Cycles uses an opt-in per-object
   property — only objects flagged as casters trigger MNEE
   sampling. Should we mirror that, or always-on?
3. **Acceptance gate.** "Visible rainbow at 256 spp" is an
   approximate gate. Do you want a numerical gate (centroid spread,
   per-wavelength SNR) or a visual gate (saved reference render) as
   the hard PR-merge condition?
4. **Future scope.** Reflective caustics (mirror pool, polished metal
   floor) are out of pkg64. Confirmed acceptable, or do you want them
   in scope (would push toward SMS as primary instead of MNEE)?

---

## Implementation pointers (for the post-sign-off phase)

If license path A (GPL-OK):
- Cycles MNEE entry points: `intern/cycles/kernel/integrator/mnee.h`,
  called from `intern/cycles/kernel/integrator/shade_surface.h`.
- The patch: Blender developer site `D13533` (Olivier Maury). Search
  the linked diff for `MNEE_SOLVER_MAX_ITERATIONS` and `mnee_sample`
  to find the Newton solver and connection logic.
- License/source attribution must be added to every ported file per
  CLAUDE.md §6.

If license path B (paper port):
- Hanika et al. 2015, §3-5 (algorithm) and §6 (results). Newton solver
  is ~30 lines, the half-vector residual is the standard one. SMS code
  on GitHub (BSD) is a useful cross-reference for the Newton inner
  loop even though the outer algorithm differs.

In both cases:
- Wavelength = sampled hero wavelength from `SampledWavelengths` (pkg10).
- IOR query = `Sellmeier(λ_hero)` from pkg31's `SellmeierDielectric`.
- Validation = `tests/scenes/prism_reference.py` (pkg29) at 256 spp,
  with the new `use_refractive_caustics=True` flag.

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
