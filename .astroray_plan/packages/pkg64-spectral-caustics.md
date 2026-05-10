# pkg64 — Spectral Caustics (Prism-Accurate)

**Pillar:** 3 (light transport) and 5
**Track:** A (research-grade — research note signed off 2026-05-09)
**Status:** research signed off — **ready to implement when capacity allows**. See [`caustics-research.md`](../docs/caustics-research.md) for the licensing analysis and the four owner answers.
**Estimated effort:** 3-4 weeks (~80 h, multiple sessions).
**Depends on:** pkg29 (prism validation, done), pkg29a (caustic test scenes, done)

---

## Goal

**Before:** Caustics live in `caustic_path_tracer` as a separate integrator. Users have to choose: ReSTIR + NEE (no caustics) or caustic-aware path tracing (no ReSTIR). The user's reference test case — *"place a prism in front of a light, get a real rainbow cascade behind it"* — is not satisfied at production quality.

**After:** Path tracing produces a wavelength-accurate prism rainbow. The selected caustic algorithm is folded into the default `path_tracer` so that ReSTIR + NEE benefits compose with caustic sampling. `caustic_path_tracer` is retained as a regression baseline.

---

## Context

This is the highest-effort package on the roadmap and the only one explicitly research-grade. The 2026-05-09 literature pass and project-owner sign-off resolved the algorithm + licensing choice:

- **Code skeleton: Specular Manifold Sampling (SMS)** — Zeltner et al., SIGGRAPH 2020 — taken from the BSD-3-Clause [Mitsuba 2 reference implementation](https://github.com/tizian/specular-manifold-sampling). MIT-compatible, handles refractive + reflective + glint paths uniformly.
- **Spectral extension on top: per-wavelength Newton iteration** — math from the Hanika et al. 2015 MNEE paper (DOI 10.1111/cgf.12681), re-derived from the paper itself.
- **NOT used: Cycles' MNEE source** — Cycles is GPL-2.0+, incompatible with Astroray's MIT license. Cycles is consulted for runtime-behavior patterns (the "caustic caster" opt-in property) only; no Cycles source code is copied.
- **NOT used as primary: photon mapping** — older, no canonical permissive reference. Kept as a phase-2 fallback if SMS+spectral underperforms.

The four open questions from the original draft are answered:

1. **License path:** SMS skeleton (BSD-3, MIT-compat) + paper-derived spectral extension. *Not* Cycles.
2. **Caustic-caster UX:** opt-in per-object property, mirroring Cycles.
3. **Acceptance gate:** both numerical (centroid spread, PSNR) and visual (SSIM ≥ 0.95 against saved reference renders).
4. **Reflective caustics:** in scope. SMS handles them natively, which is what made SMS the right code skeleton.

---

## Reference

- Existing Astroray work: [plugins/integrators/caustic_path_tracer.cpp](plugins/integrators/caustic_path_tracer.cpp), [pkg29a-scoped-caustic-validation.md](.astroray_plan/packages/pkg29a-scoped-caustic-validation.md), [tests/test_spectral_prism.py](tests/test_spectral_prism.py).
- **External (must verify with WebSearch before relying on):**
  - Zeltner, Georgiev, Jakob, "Specular Manifold Sampling for Rendering High-Frequency Caustics and Glints", SIGGRAPH 2020. Mitsuba 3 reference.
  - Hanika, Droske, Manakov, "Manifold Next Event Estimation", EGSR 2015.
  - Jensen, "Global Illumination using Photon Maps", EGSR 1996.

---

## Prerequisites

- [x] Research phase complete. See [`caustics-research.md`](../docs/caustics-research.md). Recommended approach: SMS code (BSD-3, from Mitsuba 2 reference) + per-wavelength Newton extension from Hanika 2015.
- [x] Project-owner sign-off received 2026-05-09.
- [ ] Confirm the existing prism test scene (`tests/test_spectral_prism.py`) reproduces a measurable but not yet visually-correct caustic baseline — needed for regression tests.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `external/sms/` | Vendored SMS reference code (BSD-3, originally from `tizian/specular-manifold-sampling`). Files preserve their original copyright headers; a top-level `external/sms/README.md` records the upstream commit hash and license attribution. |
| `external/sms/THIRD_PARTY_LICENSES.md` | License attribution for the BSD-3 code we vendor. |
| `include/astroray/sms_adapter.h` | Thin Astroray-side adapter mapping `HitRecord`/`Vec3`/`Material` to the SMS code's expected Mitsuba 2 types. No algorithm in here. |
| `src/sms_adapter.cpp` | Adapter implementation. |
| `plugins/integrators/sms_caustics.cpp` | Astroray plugin that wires SMS sampling into the existing `path_tracer` as an MIS strategy. Gated by `use_refractive_caustics` / `use_reflective_caustics` *and* per-object `is_caustic_caster`. |
| `tests/test_spectral_caustic_prism.py` | Visual + numerical regression on the prism scene. |
| `tests/test_reflective_caustic_pool.py` | Reflective caustic acceptance test (mirror-pool / polished metal). |
| `tests/scenes/prism_rainbow.py`, `tests/scenes/mirror_pool.py` | Reference scenes. |
| `tests/reference/prism_rainbow_256spp.png`, `tests/reference/mirror_pool_256spp.png` | Saved reference renders for the visual gate. |

### Files to modify

| File | What changes |
|---|---|
| `plugins/integrators/path_tracer.cpp` (or its spectral variant) | Add SMS dispatch as an MIS strategy gated by `use_refractive_caustics` / `use_reflective_caustics` and per-caster opt-in. |
| `include/raytracer.h` (Hittable) | Add `bool isCausticCaster_` flag with `setCausticCaster(bool)` / `isCausticCaster() const` accessors. |
| `module/blender_module.cpp` | Bind `set_caustic_caster(material_id_or_object_id, enabled)`. |
| [blender_addon/__init__.py](blender_addon/__init__.py) | Add `is_caustic_caster: BoolProperty` to the Astroray per-object panel; pass it to the renderer in `convert_objects`. |
| `CMakeLists.txt` | Build rule for `external/sms/` and the adapter; link into `astroray_plugins`. |

### Key design decisions

1. **One unified integrator path.** SMS sampling is an MIS strategy *inside* `path_tracer`, not a parallel integrator. ReSTIR + NEE compose. Matches the user's "compose, don't replace" requirement from the original triage.
2. **Per-wavelength Newton solve.** Each spectral sample's Newton iteration uses `Sellmeier(λ_hero)` — re-derived from Hanika 2015 §3-5. This is the math change vs vanilla SMS that gives us the prism rainbow.
3. **Opt-in caster property.** Mirrors Cycles' UX. Per-object boolean. Saves perf when caustics aren't needed and matches what a Cycles-trained user expects.
4. **Performance budget.** No-caustic scenes (no caster flagged): < 1.2× slowdown vs current `path_tracer` with caustics flag off. Rainbow scene at 256 spp: visible rainbow (centroid spread ≥ 1.5×, SSIM ≥ 0.95 vs reference).
5. **Both numerical and visual gates.** Owner's explicit request. Centroid spread + PSNR + SSIM all checked. Visual reference PNGs live in `tests/reference/`.
6. **Regression baseline retained.** `caustic_path_tracer` stays in the registry as a tested baseline.
7. **Vendored SMS, not git-submodule.** SMS is small enough to vendor; no git submodule overhead. Upstream commit hash recorded in `external/sms/README.md` for traceability.

---

## Acceptance criteria

- [x] Research note `.astroray_plan/docs/caustics-research.md` exists and is signed off by the project owner.
- [ ] **Refractive prism rainbow:** prism scene at 256 spp shows a visible rainbow cascade with chromatic separation.
  - Numerical: per-channel centroid spread ≥ 1.5× the no-caustic baseline.
  - Numerical: PSNR ≥ 28 dB vs the reference render at the matched spp.
  - Visual: SSIM ≥ 0.95 vs `tests/reference/prism_rainbow_256spp.png`.
- [ ] **Reflective caustic:** mirror-pool / polished-metal scene renders a coherent caustic pattern.
  - Visual: SSIM ≥ 0.95 vs `tests/reference/mirror_pool_256spp.png`.
- [ ] **Performance:** no-caustic scenes (no caster flagged) show < 1.2× slowdown vs `path_tracer` with caustics off.
- [ ] **Composability:** ReSTIR DI tests still pass when caustics flag is on (compose-don't-replace).
- [ ] **License hygiene:** vendored SMS code keeps its BSD-3-Clause headers; `external/sms/THIRD_PARTY_LICENSES.md` lists attribution; CLAUDE.md §6 citations on every wavelength-extension call site.

---

## Non-goals

- Do not invent a new caustic algorithm. Use the SMS code skeleton + paper-derived spectral extension. CLAUDE.md §6 applies.
- Do not consume Cycles' MNEE source code. GPL-2.0+ is incompatible with Astroray's MIT license. Cycles is a runtime-behavior reference (the caster opt-in pattern) only.
- Do not delete `caustic_path_tracer`. It stays as a registered regression baseline.
- Do not port to GPU in this package. SMS GPU port is a follow-up after pkg54.
- Do not implement glint rendering on rough microfacet normal-mapped surfaces. SMS supports it but the use case is outside the prism/mirror-pool target. Phase-2.
- Do not implement SMBS / Batch SMS speedups. Phase-2 if convergence is unsatisfactory.
- Do not couple this to Pillar 4 / GR rendering. Curved-spacetime caustics are out of scope.

---

## Progress

- [x] **Research phase**: WebSearch + WebFetch literature pass; `caustics-research.md` drafted 2026-05-09.
- [x] **Project-owner sign-off** (2026-05-09): SMS code (BSD-3) + spectral extension; opt-in caster UX; both numerical + visual gates; reflective caustics in scope.
- [x] **Phase 1 (RGB SMS skeleton)**: opt-in `sms_caustic_path_tracer`
  integrator built on top of `caustic_path_tracer`. Geometric Newton
  iteration on the half-vector constraint (Zeltner 2020 §4.2,
  Mitsuba 2 reference commit `1f0e4034`) lives in
  `include/astroray/manifold/`; integrator is sphere-caster only for
  Phase 1. Phase 1 acceptance test:
  `tests/test_sms_caustic_validation.py`.
- [x] **Phase 2 (spectral)**: per-wavelength Newton residual using
  `Sellmeier(λ_hero)` from pkg31 — math from Hanika 2015 §4. Sphere-only
  caster scope retained from Phase 1; the Newton solve, refraction
  direction and Schlick Fresnel are evaluated at the hero wavelength of
  the current `SampledWavelengths` bundle and the contribution is
  written to the hero spectral channel only. Gated behind a new
  `spectral_newton` integrator param (default off, so the Phase 1
  regression in `tests/test_sms_caustic_validation.py` is unchanged).
  Acceptance test: `tests/test_sms_caustic_spectral.py`.
  Triangle-mesh reprojection and the analytic Jacobian replacement
  (Zeltner 2020 §4.3) remain follow-ups, scoped out of Phase 2.
- [ ] **Phase 3 (default-integrator integration)**: fold SMS into
  `path_tracer` as an MIS strategy under `use_refractive_caustics` /
  `use_reflective_caustics`. Add `is_caustic_caster` per-object
  property + Blender UI. Reference renders + visual SSIM gate.
- [ ] Implementation phase continues.
- [ ] Vendor `external/sms/` from upstream commit hash (recorded in `external/sms/README.md`).
- [ ] Astroray adapter layer (`include/astroray/sms_adapter.h`).
- [ ] Per-wavelength Newton residual (Hanika 2015 §3-5 derivation).
- [ ] `is_caustic_caster` per-object property + Blender UI.
- [ ] Reference renders saved to `tests/reference/`.
- [ ] Numerical + visual regression tests.
- [ ] Performance gate verification (< 1.2× slowdown when no caster flagged).
- [ ] STATUS.md updated.

---

## Lessons

### Phase 2 — spectral wavelength-Newton (2026-05-10)

- **Hero-wavelength residual is the right level of decoupling.**
  Hanika 2015 §4's observation that `h(λ) = ω_i + η(λ)·ω_o` is linear in
  the wavelength-dependent η means each ray only needs one Newton solve
  at λ_hero, not one per channel. Different rays sample different
  λ_hero, so per-pixel accumulation across rays is what produces the
  prism rainbow — no per-RGB-channel iteration required.
- **Reuse the dispersive-dielectric convention for hero-only output.**
  After running the Newton solve and refraction with η(λ_hero), the
  refracted direction is wavelength-specific, so the secondary
  wavelengths of the bundle are not valid for that path. The integrator
  writes the contribution into channel 0 of a `SampledSpectrum` and
  leaves the rest at zero — exactly the same convention that
  `plugins/materials/dielectric.cpp` already uses on dispersive
  refraction events (`SampledWavelengths::terminateSecondary`-equivalent
  semantics).
- **`set_integrator_param` only routes ints.** The Python binding for
  `setIntegratorParam` (module/blender_module.cpp:1052) takes `int`,
  and `ParamDict::getBool` only matches `bool`-typed entries, so a
  `getBool("spectral_newton")` reads as the default. Toggle is now
  read via `getInt("spectral_newton", 0) != 0`.
- **Performance ratio measured.** On the 64×64 BK7-sphere acceptance
  scene, spectral mode runtime ≈ 0.98× of RGB mode — the work per ray
  is identical (one Newton solve in both cases); the spectral path
  only adds a Sellmeier evaluation and a hero-only spectrum write.
  Well inside the ≤ 2× budget.
- **Visual chromatic-spread metric was noise-dominated at the test's
  spp budget.** The PSNR-vs-spectral-reference delta (≥ 8 dB on the
  acceptance scene, target ≥ 3 dB) is the strict gate; the spread
  metric is logged for diagnostics but not asserted. If a stricter
  visual gate is wanted later, the right move is to compute spread on
  `(sms_spectral − sms_rgb)` so the path-tracer baseline noise cancels
  out, rather than on the raw image.

*(Phase 3 lessons to follow.)*
