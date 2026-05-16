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

**Coverage statement (accurate scope — do not overstate).**

1. **What pkg85-D's gate actually validates.** pkg85-D's existing SSIM
   gate (`test_gpu_cpu_ssim_hdri`, SSIM 0.9793 ≥ 0.97) validates GPU/CPU
   world-as-light parity on an **env-map-only scene with NO geometry**
   (`load_environment_map(...) + setup_camera(...)`, no objects, no
   lights). It does **not** currently exercise the geometry-bearing
   BUG-11 witness. The BUG-11 disambiguating experiment is "a single
   diffuse sphere, solid grey world, no lights, CPU vs GPU" — that scene
   has *geometry* whose first-bounce BSDF illumination must come from the
   world. pkg85-D's no-geometry scene shares the world-as-light
   *invariant* but not the geometry-bearing *code path* (NEE / indirect
   off a surface), so BUG-11 is **not** already covered by the pkg85-D
   gate as it stands.

2. **The geometry-bearing parity check is DEFERRED, not done.** A
   `world-only diffuse sphere CPU vs GPU not-black` regression check — a
   single diffuse sphere under a solid grey world with no light objects,
   rendering non-black on GPU and within SSIM parity of CPU — is
   **deferred**. It is to be added when pkg85-D is next touched / folded
   into the pkg55-B' Phase-B/C parity gate (see the pkg55 spec edits in
   the Round-10 doc PR, where BUG-11 ≡ pkg85-D is a *named* Phase-B/C
   parity gate). Until that test exists, this geometry-bearing variant of
   BUG-11 is **not** validated on main. Do not claim it is covered.

3. **The fallback / safety net until then.** Because the geometry-bearing
   parity test does not yet exist, **`pkg96`'s world-only-on-GPU honesty
   guard is the only user-facing protection for BUG-11.** If pkg85-D's
   geometry-bearing parity work slips (or pkg55-B' Phase-B/C is delayed),
   pkg96 is the safety net: it makes the GPU world-only-diffuse limitation
   honest to the user rather than silently producing a black surface. The
   pkg96 honesty guard is therefore load-bearing for BUG-11 and must not
   be dropped on the assumption that pkg85-D already covers it.

**Why P5's BUG-11 is still deferrable.** PR #300 §5 defers P5's GPU
architecture into pkg55-B' and ships only the pkg96 UX honesty guard now.
That deferral is acceptable for BUG-11 **not** because pkg85-D fully
covers the geometry-bearing case (it does not — see (1)/(2)), but because
(a) the world-as-light *invariant* has a passing no-geometry SSIM gate on
main, (b) the geometry-bearing parity check is scheduled as a named
pkg55-B' Phase-B/C gate, and (c) until that gate lands, pkg96's honesty
guard prevents users from silently hitting BUG-11. The user-facing risk
is bounded by pkg96, not eliminated by pkg85-D.
