# pkg199 — GPU wavefront volume rendering (homogeneous world volume + HG phase)

**Pillar:** 5 / integration-first (also 3 — CPU↔GPU parity)
**Track:** A
**Status:** open (filed 2026-08-13 — GPU-parity vetted set; **design-first**)
**Estimated effort:** L (new transport subsystem in the wavefront; scope deliberately bounded
to the homogeneous world volume first)
**Depends on:** pkg55-C7 wavefront dispatch; the CPU world-volume reference
(`include/raytracer.h:2110-2255`); [[wavefront-shade-kernels-register-saturated]].

---

## Why this exists (verified line refs, current `main`)

`__gpu_features__` reports `volumes=false` with the comment "CPU-only"
(`module/blender_module.cpp:4577`), and the honesty note states the GPU path "ignores volumes"
(`module/blender_module.cpp:4559`). The CPU has a working **homogeneous world volume**:
`worldVolumeDensity/Color/Anisotropy` with Beer-Lambert transmittance
`sigmaT = worldVolumeColor * worldVolumeDensity` and Henyey-Greenstein anisotropy
(`include/raytracer.h:2110-2255`), driven from the addon via `set_world_volume`
(`module/blender_module.cpp:1607-1608, 2800`). The GPU wavefront transport
(`src/gpu/wavefront/stage_advance.cu`) has **no volume interaction at all** — rays pass
straight through. So a scene with atmospheric fog / god-rays / a coloured world medium renders
correctly on CPU and as vacuum on the (default) GPU backend: a visible, owner-facing
divergence, and the last of the four headline GPU-parity capability gaps
(textures→pkg186/pkg190, adaptive→pkg131, denoise-guides→pkg197, **volumes→here**).

## Scope — bounded on purpose

Bring the **homogeneous world volume** to the GPU wavefront, matching the CPU model exactly:

- **Transmittance / free-flight** along each ray segment: Beer-Lambert `exp(-sigmaT · t)` with
  the CPU's `sigmaT = worldVolumeColor · worldVolumeDensity` (mirror `raytracer.h:2152-2154`).
- **In-scatter** with the **Henyey-Greenstein** phase function at the CPU anisotropy
  (`worldVolumeAnisotropy`, clamped [-0.99, 0.99]), NEE toward lights through the medium.
- **Distance sampling** for scatter events (homogeneous → analytic exponential sampling).
- Uphold CPU↔GPU wavefront-diff parity on a fixed foggy reference scene.

**Heterogeneous / object volumes are explicitly OUT of scope.** `add_volume`
(`module/blender_module.cpp:1277-1290`) currently renders volume *objects* as emissive
proxies, not as scattering media, and the black-hole volumetric emission
(`addVolumetricEmission`, lines 1229/1261/1272) is a separate Pillar-4 concern (on pause —
[[pillar4-on-pause]]). Do not touch either. A future package owns heterogeneous grids /
`add_volume` scattering / delta-tracking.

## MANDATORY FIRST STEP — design + register budget

1. **Cite the algorithm** (CLAUDE.md §6 / [[cite-algorithm]]). Homogeneous volume transport,
   HG phase, and analytic distance sampling are textbook — use PBRT-v4
   (`src/pbrt/media.cpp`, `HomogeneousMedium`, phase-function sampling) and Cycles
   (`intern/cycles/kernel/integrator/volume_stack.h` / `volume.h`, Apache-2.0) as references;
   save a short research note to `.astroray_plan/docs/`. Do NOT invent the estimator.
2. **Decide where the volume interaction lives in the wavefront stage graph** — a dedicated
   volume-scatter stage vs folding free-flight/transmittance into `stageAdvance`. Whatever the
   choice, the register-saturated `stageShadeBucketedKernel<false,…>` must stay **REG 254 /
   STACK 3608 / CONSTANT[0] 1700** (isolate the volume path behind a compile-time
   `HasWorldVolume` axis so vacuum scenes are byte-identical — pkg184/pkg189 pattern). Read the
   post-link numbers via `cuobjdump` before scaling up.

## Acceptance criteria

- [ ] GPU wavefront renders the homogeneous world volume: transmittance, HG in-scatter, and
      NEE-through-medium, **matching the CPU render within a tight band** on a fixed foggy
      scene (CPU↔GPU wavefront-diff parity) at multiple density/anisotropy settings.
- [ ] `__gpu_features__["volumes"]` flips to `true` **only** for the world-volume capability,
      with the honesty comment updated to state homogeneous-world-only (do not over-claim
      heterogeneous/object volumes — the pkg186 `__gpu_features__` honesty discipline).
- [ ] Vacuum (no world volume) GPU renders are **byte-identical** to pre-change and show no
      perf regression (compile-time isolation verified via cuobjdump; min-of-N perf,
      [[gpu-perf-ab-clock-drift]]).
- [ ] Headless Blender 5.1: `set_world_volume` from the world panel produces matching fog on
      CPU and GPU.
- [ ] **RTX 5070 Ti hardware gate** ([[ci_has_no_gpu_runtime_blindspot]]), bound to HEAD,
      with a visual confirmation of the fog/god-ray render.

## Hard non-goals

- **No heterogeneous / object volumes, no delta-tracking, no `add_volume` scattering** — the
  emissive-proxy behaviour stays as-is; a later package owns grids.
- **No black-hole / Pillar-4 volumetric emission** work ([[pillar4-on-pause]]).
- **No volume render passes** (`PASS_VOLUME_*`) until this lands — then pkg198 can extend.
- **No shared-kernel register regression** — compile-time isolation only (pkg178/pkg184 rule).
