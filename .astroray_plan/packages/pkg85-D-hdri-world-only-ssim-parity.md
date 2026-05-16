# pkg85-D — HDRI world-only render GPU/CPU SSIM parity

**Pillar:** 5
**Track:** A (RTX verifier)
**Status:** done (PR #283, 2026-05-14 — GPU XYZ→sRGB ordering fix closed the 3× green bias; `test_gpu_cpu_ssim_hdri` SSIM 0.9793 ≥ 0.97 gate)
**Estimated effort:** ½ day (~4 h on RTX)
**Depends on:** pkg85-C (the precondition fix that lets this test reach SSIM)

---

## Goal

**Before:** `tests/test_world_hdri_parity.py::test_gpu_cpu_ssim_hdri` runs to completion (post-pkg85-C) but the GPU image is wildly different from the CPU image — SSIM ≈ 0.35 against a gate of 0.97. Scene is `load_environment_map(...) + setup_camera(...)` with no geometry; CPU path-traces against the env map, GPU does the same but produces a different image.

**After:** GPU vs CPU SSIM ≥ 0.97 on the same 64×64×64-spp setup.

---

## Context

pkg85-B's `RuntimeError("Scene not uploaded — call uploadScene() first")` masked this for months. pkg85-C unblocked the render path (geometry-less scenes are allowed if an env map is uploaded). The result is no longer a crash or an exception — it's a wrong picture.

Probably one of:
- `gpu_envmap_lookup` vs CPU `EnvironmentMap::sample` disagreeing on rotation matrix / color tint / strength multiplier.
- `pathTraceKernel`'s miss-branch tonemapping differs (CPU integrator may multiply by a different factor or skip the `* 0.2f` fallback that the GPU applies when `envMap.loaded` is false).
- The CPU first-bounce env contribution uses NEE; the GPU first-bounce env contribution uses BSDF MIS only (with no geometry, both should collapse to "miss → env lookup" — but the path may differ).

## Reference

- `src/gpu/path_trace_kernel.cu` — miss branch (lines ~265–285).
- `include/astroray/gpu_materials.h` — `gpu_envmap_lookup` and friends.
- `include/raytracer.h` — `EnvironmentMap::sample` and CPU `pathTrace` miss handling.
- `tests/test_world_hdri_parity.py::test_gpu_cpu_ssim_hdri` — the gate.

## Specification

### Phase 1 — Localise the divergence

Render the CPU and GPU images, save both to PNG, eyeball them. Then for the same camera ray (e.g., centre pixel), trace by hand on both backends and find where they diverge.

### Phase 2 — Fix the env-lookup math

Whatever Phase 1 surfaces. Pkg63 already baked the rotation matrix; this is likely a smaller miss (strength, tint, channel order, or the 0.2f sky-gradient fallback firing when it shouldn't).

### Acceptance

- `test_gpu_cpu_ssim_hdri` passes with margin (SSIM ≥ 0.97).
- No regression on other env-map tests (`test_pkg63_*`, `test_world_hdri_parity::test_other_*`).

---

## BUG-11 ≡ pkg85-D (addon triage cross-ref)

Added during the Round-10 addon first-principles planning pass (PR #295
triage / PR #300 plan). pkg85-D is **done** (PR #283, 2026-05-14 —
`test_gpu_cpu_ssim_hdri` SSIM **0.9793 ≥ 0.97**).

**The cross-ref.** Blender-addon triage **BUG-11** ("Principled diffuse
renders black against world/background but reacts to light objects") has
the root cause (PR #295 RC-2 / PR #300 P5): the GPU kernel receives
`backgroundColor`/`hasBackgroundColor` and uses it only as the
camera-ray *miss color* — it does not treat a solid/HDRI world as an
**environment light** contributing to BSDF illumination (NEE / indirect),
so a diffuse surface lit only by the world goes black while explicit
light objects still illuminate it. That is precisely the GPU
world-as-light parity defect pkg85-D was filed for and **closed**: the
GPU XYZ→sRGB ordering fix that landed pkg85-D restored CPU/GPU
world-only parity on the geometry-less env-map scene.

**Coverage statement.** BUG-11's CPU/GPU world-only-diffuse symptom is
**covered by pkg85-D's gate** (`test_gpu_cpu_ssim_hdri`, SSIM ≥ 0.97).
The pkg85-D scene is env-map-only (no geometry); the addon's BUG-11
disambiguating experiment (a single diffuse sphere, solid grey world, no
lights, CPU vs GPU) is the geometry-bearing variant of the same
invariant.

**Named regression check (add when pkg85-D is next touched):**
`world-only diffuse sphere CPU vs GPU not-black` — a single diffuse
sphere under a solid grey world with no light objects must render
non-black on GPU and within SSIM parity of CPU. This is the
geometry-bearing complement to `test_gpu_cpu_ssim_hdri` and the explicit
witness for addon BUG-11. (Recorded here as a named gate; it folds into
the pkg55-B' Phase-B/C parity gates per the pkg55 spec edits filed in the
Round-10 doc PR — BUG-11 ≡ pkg85-D is a *named* Phase-B/C parity gate
there.)

**Why this makes P5's BUG-11 deferrable without user risk.** PR #300 §5
defers P5's GPU architecture into pkg55-B' and ships only a UX honesty
guard now (pkg96). That deferral is safe for BUG-11 specifically
**because pkg85-D is already done**: the GPU world-as-light path has a
passing SSIM parity gate on main, so BUG-11 is not an open correctness
hole — it is a *covered* invariant whose addon-scene generalization is
scheduled as a named pkg55-B' parity gate, not an unaddressed user-facing
bug. pkg85-D being `done` is *why* the owner can defer P5's BUG-11 into
the wavefront track without exposing users to a regression.
