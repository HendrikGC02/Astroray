# pkg110 — BSDF-driven photon emission + bounce

**Pillar:** 3 (Light transport)
**Track:** A (CPU integrator)
**Status:** WIP (branch `pkg110-photon-bounce`, 2026-05-30) — general DETERMINISTIC refraction photon loop done + validated on a glass sphere (peak 0.673, ~41× concentration; `tests/test_glass_sphere_caustic.py` passes). Prism `hue_spread` gate NOT reproduced under any general loop (root cause: the gate relies on the exactly-2-slant-face purity) → needs an OWNER DECISION (re-derive the prism gate, or keep a special-case flat-caster path). See `.astroray_plan/docs/pkg110-status-finding.md`.
**Estimated effort:** M (~3-4 days)
**Depends on:** pkg109 (photon-map kd-tree store)

---

## Goal

After pkg109, photons are stored in a general kd-tree but are still emitted via
the hard-coded 2-face prism refraction in `light_tracer_caustic`. This package
replaces that with a **general BSDF-driven photon loop** so photons traverse ANY
glass shape, multi-bounce specular chains, and total internal reflection — i.e.
"drop in any glass-like object and the light passing through it disperses
correctly." This is what makes the caustic feature general rather than
prism-specific.

## Approach (cite — CLAUDE.md §6)

- **Jensen 1996** §photon tracing: emit photons from each light (power = Φ/N),
  trace through the scene, at each surface sample the BSDF (`Material::sampleSpectral`)
  to continue, store a photon on each **diffuse** interaction, Russian-roulette
  terminate. Specular/dielectric interactions scatter (refract/reflect) and carry
  on — this is where dispersion happens (the dielectric's `iorAt(λ)` +
  `terminateSecondary()` already give correct per-hero-λ Sellmeier refraction,
  `plugins/materials/dielectric.cpp:103,188`).
- **Reference:** PBRT photon tracing loop (Apache-2.0/BSD); smallpt (public domain)
  for the minimal skeleton.

## Chunks

1. Photon emission from each light type (start: the distant sun + area/point —
   reuse `LightList`/`getDedicatedLights`). Power normalization so total emitted
   flux = light power.
2. Photon bounce loop using `Material::sampleSpectral` + BVH (delta dielectrics
   refract/reflect; diffuse → deposit photon into the pkg109 kd-tree + RR
   continue or terminate). Hero-λ carry through the chain.
3. Tests: (a) a **sphere/lens** caustic (focusing caster — the case camera-side
   MNEE was meant for) now renders via photons; (b) a **two-glass / TIR** scene
   produces a caustic the 2-face stub could not; (c) the prism regression still
   passes.

## Acceptance

- [ ] Photons trace through arbitrary flagged glass via BSDF sampling (no
      hard-coded face count); TIR + multi-bounce handled.
- [ ] A glass-sphere caustic scene renders a focused chromatic caustic (new gate).
- [ ] Prism regression (`prism-bk7-collimated`) still passes.
- [ ] Cite Jensen 1996 §photon-tracing + the dielectric hero-λ reuse.

## Non-goals

- Not the default-path integration (pkg111) — still a dedicated integrator.
- Not GPU. Not SPPM progressive convergence.
