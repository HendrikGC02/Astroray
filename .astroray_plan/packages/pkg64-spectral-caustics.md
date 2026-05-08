# pkg64 — Spectral Caustics (Prism-Accurate)

**Pillar:** 3 (light transport) and 5
**Track:** A (research-grade — must do WebSearch + WebFetch literature pass first)
**Status:** open — **research phase blocked until `.astroray_plan/docs/caustics-research.md` is filled in**
**Estimated effort:** 3-4 weeks (~80 h, multiple sessions). Includes literature pass.
**Depends on:** pkg29 (prism validation, done), pkg29a (caustic test scenes, done)

---

## Goal

**Before:** Caustics live in `caustic_path_tracer` as a separate integrator. Users have to choose: ReSTIR + NEE (no caustics) or caustic-aware path tracing (no ReSTIR). The user's reference test case — *"place a prism in front of a light, get a real rainbow cascade behind it"* — is not satisfied at production quality.

**After:** Path tracing produces a wavelength-accurate prism rainbow. The selected caustic algorithm is folded into the default `path_tracer` so that ReSTIR + NEE benefits compose with caustic sampling. `caustic_path_tracer` is retained as a regression baseline.

---

## Context

This is the highest-effort package on the roadmap and the only one explicitly research-grade. The user's instruction is firm: **do not invent an algorithm**. The candidate set is:

- **Specular Manifold Sampling (SMS)** — Zeltner et al., SIGGRAPH 2020. Reference implementation: Mitsuba 3, BSD-3-Clause. Handles dispersive specular paths via Newton iteration on the manifold of valid specular bounces. Wavelength-stratified extension is documented in the same paper. *Strong candidate.*
- **Manifold Next Event Estimation (MNEE)** — Hanika et al., 2015. Older. Cycles has an experimental branch. *Backup candidate.*
- **Photon mapping with caustic photons** — Jensen 1996. Adds a separate photon pass. *Strong fallback if SMS proves too complex; well-understood.*
- **Path-space MLT with manifold mutations (MMLT)** — Jakob & Marschner 2012. *Probably overkill for prism caustics specifically.*

**Working hypothesis (subject to research):** SMS + spectral wavelength stratification. Mitsuba 3 already renders dispersive prism caustics with this combination, and its license allows porting.

The research phase must verify the working hypothesis and produce a citation-grade research note before any code is written. See **Prerequisites**.

---

## Reference

- Existing Astroray work: [plugins/integrators/caustic_path_tracer.cpp](plugins/integrators/caustic_path_tracer.cpp), [pkg29a-scoped-caustic-validation.md](.astroray_plan/packages/pkg29a-scoped-caustic-validation.md), [tests/test_spectral_prism.py](tests/test_spectral_prism.py).
- **External (must verify with WebSearch before relying on):**
  - Zeltner, Georgiev, Jakob, "Specular Manifold Sampling for Rendering High-Frequency Caustics and Glints", SIGGRAPH 2020. Mitsuba 3 reference.
  - Hanika, Droske, Manakov, "Manifold Next Event Estimation", EGSR 2015.
  - Jensen, "Global Illumination using Photon Maps", EGSR 1996.

---

## Prerequisites

- [ ] **Research phase (mandatory).** Use WebSearch + WebFetch to:
  1. Confirm the SMS paper exists at the cited venue and read the abstract.
  2. Locate the Mitsuba 3 SMS implementation; record the file path inside Mitsuba and the license header.
  3. Confirm the dispersive-prism rendering claim from the SMS paper (Figure or supplemental).
  4. Identify the licensing constraints of porting Mitsuba 3 code into Astroray.
  5. Cross-reference with how Cycles handles dispersive caustics (or fails to).
  6. Save findings to `.astroray_plan/docs/caustics-research.md` with: paper titles + DOIs/arXiv IDs, license of every reference repo, the specific files we will mirror, the math we will reproduce, and any open questions for the project owner.
- [ ] Project owner sign-off on the research note before implementation begins.
- [ ] Confirm the existing prism test scene (`tests/test_spectral_prism.py`) reproduces a measurable but not yet visually-correct caustic baseline — needed for regression tests.

---

## Specification

### Files to create (after research lands)

*Exact list will be finalized in the research note. Probable shape:*

| File | Purpose |
|---|---|
| `plugins/integrators/sms_path_tracer.cpp` (or extension to `path_tracer.cpp`) | Implementation of the chosen caustic algorithm. |
| `tests/test_spectral_caustic_prism.py` | Visual regression vs reference image (rainbow cascade) and statistical test on per-channel centroid spread. |
| `tests/scenes/prism_rainbow.py` | Production-quality prism scene. |
| `.astroray_plan/docs/caustics-research.md` | Research note (created in the research phase). |

### Files to modify

| File | What changes |
|---|---|
| `plugins/integrators/path_tracer.cpp` (or its spectral variant) | Add SMS / MNEE / photon-map dispatch gated by `use_reflective_caustics` / `use_refractive_caustics`. |
| [blender_addon/__init__.py](blender_addon/__init__.py) | Wire `use_reflective_caustics` / `use_refractive_caustics` to the new dispatch, not just to a flag the integrator ignores. |

### Key design decisions

*Locked in only after the research note.*

Tentative:
1. **One unified integrator path.** Caustic sampling is an MIS strategy inside `path_tracer`, not a parallel integrator. This is the user's explicit request.
2. **Wavelength-stratified.** A single SMS sample carries one wavelength; multi-λ rays sample SMS independently per λ. This is what produces the prism rainbow. (Only valid with SMS; revisit for other candidates.)
3. **Performance gate.** Caustic sampling can be slow; default `caustic_density` parameter must give noticeable rainbow at production sample counts (~256 spp) without a 5× slowdown over the no-caustic case on a non-prism scene.
4. **Regression baseline retained.** `caustic_path_tracer` stays in the registry for regression tests.

---

## Acceptance criteria

- [ ] Research note `.astroray_plan/docs/caustics-research.md` exists and is signed off by the project owner.
- [ ] Prism scene with a Sellmeier-glass prism + small light renders a visibly-correct rainbow cascade with chromatic separation.
- [ ] Centroid-spread metric (per-channel x-position) ≥ 1.5× the no-caustic baseline.
- [ ] No-caustic scenes show < 1.2× slowdown vs path_tracer with caustics flag off.
- [ ] ReSTIR DI tests still pass when caustics flag is on (compose-don't-replace).
- [ ] Visual regression test against a saved reference image (pixel-diff or SSIM ≥ 0.95).

---

## Non-goals

- Do not invent a new caustic algorithm.
- Do not promise reflective-caustic perfection (mirror-pool caustics) — this package targets prism-style refractive dispersive caustics first. Reflective caustic quality is acceptable as long as it does not regress.
- Do not delete `caustic_path_tracer`. It stays as a registered baseline.
- Do not couple this to Pillar 4 / GR rendering. Curved-spacetime caustics are out of scope.

---

## Progress

- [ ] **Research phase**: WebSearch + WebFetch literature pass; write `caustics-research.md`.
- [ ] Project owner reviews and signs off on research note.
- [ ] Implementation phase begins.
- [ ] Reference-image regression test on the prism scene.
- [ ] Performance gate verification.
- [ ] STATUS.md updated.

---

## Lessons

*(Fill in after the package is done.)*
