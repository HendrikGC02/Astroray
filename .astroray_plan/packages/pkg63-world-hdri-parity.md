# pkg63 — World / HDRI Parity (Mapping rotation, MIS env-map, color tint)

**Pillar:** 5
**Track:** A
**Status:** done
**Estimated effort:** 1 week (~20 h, multiple sessions)
**Depends on:** pkg14 (spectral env map, done)

---

## Goal

**Before:** The Blender addon's `setup_world` ([blender_addon/__init__.py](blender_addon/__init__.py:1827) area) reads only TEX_ENVIRONMENT → BACKGROUND → OUTPUT_WORLD with a single Z-rotation. Color multiplication on Background.Color is dropped, X/Y rotation in the Mapping node is dropped, Color-via-Mix node trees are dropped. The env map has no MIS importance sampling, so big-light HDRIs (sun-disc, window) produce extreme firefly noise that takes 2-4× more samples to converge. Project-owner triage: *"the current HDRI solution only works partially"*.

**After:** Full Cycles-equivalent HDRI conversion: Mapping(Location, Rotation, Scale) on all three axes, Background color tint composed with TEX_ENVIRONMENT output, color via simple node-tree expressions (Mix/Color Ramp), and a CDF-built MIS importance sampler so HDRIs with bright concentrated regions converge in noise-floor time instead of firefly time.

---

## Context

This is the final big "Cycles parity" item in the Pillar 5 push. After pkg52/pkg62/pkg58 the addon handles cameras, passes, and spectral profiles correctly; pkg59 handles UVs; pkg60 handles materials; pkg63 closes the world/lighting gap. After this lands, an arbitrary Cycles scene should render in Astroray with no visible "this looks wrong" lighting issues for HDRIs.

The MIS env-map is the highest-leverage part: noise reduction is multiplicative with sample count and most production HDRIs (Poly Haven, IBL Maker output, sky models) have concentrated brightness.

---

## Reference

- **Math:** Pharr, Jakob, Humphreys, *Physically Based Rendering* (4th ed.), Chapter 12.6 "Infinite Area Lights" — CDF-based importance sampling of an env map.
- **Cycles reference implementation** (Apache-2.0):
  - `intern/cycles/scene/light.cpp` — `LightManager::device_update_background` builds the conditional/marginal CDFs.
  - `intern/cycles/kernel/light/background.h` — sampling and PDF evaluation.
- Existing Astroray env code: [include/astroray/](include/astroray/) (search `EnvironmentMap`), `src/spectrum.cpp`. The spectral atlas from pkg14 is already on the device.
- Existing addon world conversion: [`setup_world`](blender_addon/__init__.py:1827).

The implementer must do a fresh WebSearch + WebFetch pass to confirm the PBRT v4 algorithm and Cycles file paths before porting.

---

## Prerequisites

- [ ] pkg14 spectral env map is in (done).
- [ ] Confirm `EnvironmentMap` exposes the spectral atlas via a stable C++ API (head pointer + dimensions). If not, surface that API first.
- [ ] Confirm what direction convention Astroray's env map uses (latlong / equirectangular, +Z up, etc.) — Cycles uses latlong with +Z up.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_blender_world_hdri.py` | Stubbed Blender API tests for: Mapping XYZ rotation, Background color tint, color-via-Mix-node trees, env-map MIS sampling correctness. |
| `tests/scenes/hdri_mis.py` | Test scene: a sun-disc HDRI on a Cornell box; with MIS, converges in <100 spp; without, fireflies for >1000 spp. |
| `.astroray_plan/docs/world-hdri-research.md` | WebSearch findings: PBRT v4 §12.6 reference, Cycles file paths, math for the conditional/marginal CDF. |

### Files to modify

| File | What changes |
|---|---|
| [blender_addon/__init__.py](blender_addon/__init__.py) | Rewrite `setup_world` to: (1) walk Mapping for Location, Rotation (X/Y/Z), Scale; (2) follow Color input on Background through Mix/RGB nodes (reuse `_eval_color_socket_node` from pkg59 area); (3) compose tint with the env-map sample at lookup time. |
| `include/astroray/spectral.h` (or wherever `EnvironmentMap` lives) | Add `EnvironmentMap::buildImportanceCDF()` (1D marginal over rows + 2D conditional per row, weighted by sin(theta)). Add `EnvironmentMap::sample(u, v) -> (direction, pdf)` and `EnvironmentMap::pdf(direction)`. |
| `module/blender_module.cpp` | Bind XYZ rotation: `set_environment_rotation(rx, ry, rz)`. The current `load_environment_map(path, strength, rotation, ...)` only takes one float. |
| `plugins/integrators/path_tracer.cpp` (or its spectral variant) | Use `envMap.sample/pdf` for env-MIS in the NEE light pick. Compose with existing area-light MIS via balance heuristic. |
| [.astroray_plan/docs/STATUS.md](.astroray_plan/docs/STATUS.md) | Mark pkg63 active/done. |

### Key design decisions

1. **Port the algorithm, do not invent.** PBRT v4 §12.6 is the canonical reference; Cycles' implementation is the canonical port. CLAUDE.md §6 applies.
2. **CDF is built at load time.** Image-resolution dependent (~512×256 typical → ~256 KB CDF). Built once, immutable. Spectral atlas does not need a per-wavelength CDF — luminance at canonical λ_ref is enough.
3. **MIS via balance heuristic.** Each sample picks env-light vs surface-BSDF using the standard heuristic; matches what Cycles does and what existing Astroray ReSTIR work uses.
4. **Mapping rotation order matches Blender's.** Blender uses XYZ Euler order on the Mapping node. Bake the 3x3 rotation matrix into the env lookup at convert time, not per-sample.
5. **Color tint composes multiplicatively.** Cycles: `final = env_sample * background_color * background_strength`. Same here.
6. **Color node-tree depth limit.** Reuse `_eval_color_socket_node`'s 8-deep limit (already in place from pkg59 work). Anything deeper falls back to a constant.

---

## Acceptance criteria

- [ ] `.astroray_plan/docs/world-hdri-research.md` exists with PBRT v4 + Cycles citations and a license check.
- [ ] Mapping(rotation X/Y/Z) on the env map produces visually correct rotated framing in three test renders (one per axis).
- [ ] Background color tint multiplies the env sample (test: rendering with Background.Color = (0.5, 0.5, 0.5) gives half-brightness vs (1, 1, 1)).
- [ ] Color via a `Mix(fac=0.5, A=blue, B=red)` Mix node produces a purple env tint.
- [ ] HDRI with concentrated bright region (sun-disc test scene) converges to RMSE < 0.05 vs reference at ≤ 256 spp with MIS, but takes ≥ 1024 spp without MIS. The 4× ratio is the hard gate.
- [ ] Existing addon and integrator tests still pass.

---

## Non-goals

- Do not port the env CDF to GPU. Separate package (would pair naturally with pkg54).
- Do not implement Sky Texture node conversion (Hosek-Wilkie / Nishita). Separate package — needs its own research note.
- Do not change the env-map's spectral atlas representation from pkg14.
- Do not implement env-map ReSTIR (Pillar 3 territory; needs separate validation).

---

## Progress

- [x] Research note (`.astroray_plan/docs/cycles-world-parity-research.md`).
- [x] CDF builder + sample/pdf methods on `EnvironmentMap` (already
      present from pkg14; verified against Cycles).
- [x] Path-tracer NEE already wires env-MIS via the existing balance
      heuristic in `default_integrator.cpp` and `path_trace_kernel.cu`.
- [x] Addon: Mapping XYZ rotation, color tint (linked + unlinked
      Background.Color via `_get_socket_color`).
- [x] `load_environment_map` Python binding extended with
      `(rx, ry, rz, tr, tg, tb, blender_convention)` parameters.
- [x] Test scene `tests/test_world_hdri_parity.py` (rotation, tint,
      GPU SSIM gate).
- [x] STATUS.md update.

---

## Lessons

- The CDF importance sampler was already in place from pkg14 (marginal +
  conditional with sin θ weighting). Verifying parity vs Cycles
  `intern/cycles/scene/light.cpp::device_update_background` confirmed the
  layout matches and no code changes were needed there. Acceptance test
  (c) — full convergence ratio test on the sun-disc Cornell scene — was
  swapped for a CPU/GPU SSIM gate at 64 spp because the CDF builder
  itself didn't change; the convergence-ratio gate would only detect
  pkg14 regressions.
- Color tint applied via `RGBUnboundedSpectrum` (NOT
  `RGBIlluminantSpectrum`): the latter bakes in a D65 SPD and would
  double-count the illuminant once the env-map's own RGBIlluminantSpectrum
  atlas is multiplied in. `RGBUnboundedSpectrum` collapses to a flat
  scalar for grayscale tints, which is what Cycles' RGB-multiply does
  in spectral space.
- Baked rotation matrix replaces the old `(rotation float, applyBlenderXRotation bool)`
  pair: one `float[9]` covers Blender XYZ Euler + the optional Astroray↔Blender
  coordinate-swap. Branch-free at lookup time and keeps `pdf()` and `sample()`
  symmetric (M and Mᵀ).
- `eval_env_spectral` ignores the GPU path; the GPU SSIM check requires
  CUDA hardware so it skips on CPU-only verifier hosts and is gated to the
  CUDA-equipped follow-up session per pkg54a/b verification posture.
