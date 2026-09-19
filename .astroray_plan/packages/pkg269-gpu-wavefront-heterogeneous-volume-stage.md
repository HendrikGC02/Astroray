# pkg269 — GPU wavefront heterogeneous volume stage (NanoVDB device grid)

**Pillar:** 3
**Track:** A
**Status:** done (PR #820, 2026-09-19 — NanoVDB device grid + HasGridVolume intersect/shadow axes + dedicated hetero scatter kernel; GPU/CPU ROI ratios slab 1.011/0.979/0.996, smoke 1.007/1.005/0.998, emission 0.986/0.981/1.026; stageShadeBucketedKernel 128/128 instantiations identical REG 254 + STACK; grid-free GPU render byte-identical vs main). Was: in-progress
**Estimated effort:** 1 week
**Depends on:** pkg268

---

## Goal

Before: the GPU wavefront renders only the homogeneous world volume
(`GWorldVolume` `__constant__` + `stageVolumeScatterKernel`); heterogeneous grids
are CPU-only (pkg268). After: a NanoVDB device grid is uploaded per frame and a
new wavefront volume stage performs delta-tracking free-flight + ratio-tracking
transmittance NEE through spatially-varying σ_t on the GPU, matching the CPU
oracle within parity. Grid-free scenes stay byte-identical to the current fleet.

---

## Context

The RTX 5070 Ti is the primary hardware gate; heterogeneous volumes must run on
the GPU wavefront to be production-usable. This mirrors pkg268 onto the device
using the proven pkg199/pkg204 pattern. It is CUDA- and physics-heavy: dispatch
to an **Opus-tier** implementer (memory `delegate-tier-stalls-on-hard-packages`
and `delegated-agents-cant-build-cuda` — the parent builds/verifies), serialize
under the GPU lock (memory `concurrent-nvcc-builds-kill-each-other`). Research:
`docs/volumes-track-research-2026-09-12.md` §1a, §5.

---

## Reference

- Design doc: `.astroray_plan/docs/volumes-track-research-2026-09-12.md` §2, §5
- External: NanoVDB device grid access (Museth 2021, Apache-2.0 header vendored in
  pkg267); pbrt-v4 GPU volume path (Apache-2.0); Cycles `integrator/shade_volume.h`
  (Apache-2.0).
- Pattern to imitate: pkg199 Stage 2 (`stageVolumeScatterKernel`,
  `template<bool HasWorldScatter>` fleet isolation, `src/gpu/wavefront/stage_advance.cu`);
  pkg204 (volume pass split); memory `shade-axis-side-table-avoids-spill`,
  `gpu-hitbuffer-drops-uvtangent-hairv`.

---

## Prerequisites

- [ ] pkg268 is done and green (CPU oracle exists to parity against).
- [ ] pkg267's vendored `NanoVDB.h` compiles under `nvcc` for `sm_120`
      (`cuobjdump --list-elf` confirms the arch).
- [ ] The `.pyd` is fresh vs HEAD before any GPU verification (memory
      `stale_pyd_locations`, `worktree-cmake-cuda-arch-stale-cache`).

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `src/gpu/wavefront/stage_volume_hetero.cu` | Heterogeneous volume stage: NanoVDB device-grid delta-tracking free-flight + ratio-tracking transmittance NEE, isolated behind a `template<bool HasGridVolume>` axis |
| `tests/test_pkg269_gpu_hetero_parity.py` | GPU↔CPU ROI mean-ratio parity on a heterogeneous scene; grid-free byte-identity; REG report |

### Files to modify

| File | What changes |
|---|---|
| `src/gpu/scene_upload.cu` | Upload the NanoVDB device grid + a `__constant__` side-table of grid handles/transforms (per memory `shade-axis-side-table-avoids-spill`) |
| `include/astroray/gpu_types.h` | Add a grid-medium handle descriptor (device pointer, transform, majorant, Principled params) alongside `GWorldVolume` |
| `include/astroray/gpu_wavefront_state.h` | Add the wavefront lanes the hetero stage needs (medium id / free-flight state), parked/restored in the snapshot |
| `src/gpu/wavefront/stage_advance.cu` | Dispatch the hetero stage when a ray is inside a `GridMedium` AABB |
| `module/blender_module.cpp` | Publish the device grid + params at frame start (mirror `setWavefrontWorldVolume`) |

### Key design decisions

- **REG:254 shade-kernel HARD gate is unchanged.** The heterogeneous stage is a
  DEDICATED kernel isolated behind `template<bool HasGridVolume>` (exactly the
  pkg199 `HasWorldScatter` pattern) — the shared shade kernel must not grow live
  state. Grid-free scenes compile the `<false>` fleet path and stay byte-identical
  (memory `closure-graph-lobe-count-spills-fused-kernel`).
- **Grid handles via a `__constant__` side-table**, not the hit buffer (memory
  `shade-axis-side-table-avoids-spill`, `gpu-hitbuffer-drops-uvtangent-hairv`):
  any new per-hit field must be added to explicit lanes + snapshot park/restore.
- **NanoVDB device grid:** upload the same buffer pkg267 builds; access via NanoVDB's
  device accessor. Delta/ratio tracking mirrors pkg268 exactly (same estimators,
  same majorant), so the CPU parity gate is meaningful.
- **NEE occlusion:** the GPU wavefront resolves shadow rays in a deferred stage
  (memory `gpu-wavefront-nee-occlusion-deferred-stage`) — ratio-tracking
  transmittance must be integrated there, and tests must use mesh/grid emitters
  where the wavefront skips dedicated lights.
- Snapshot semantics: pin the capture moment so CPU/GPU capture the same
  free-flight vertex (memory `wavefront-snapshot-semantics-class-of-bug`).

---

## Acceptance criteria

- [ ] `test_pkg269_gpu_hetero_parity.py` passes: GPU↔CPU per-channel ROI mean
      ratio within ±5 % on a heterogeneous VDB scene; grid-free scenes render
      **byte-identical** to the pre-change fleet.
- [ ] `cuobjdump` shows the shared shade kernel REG unchanged (HARD gate); the new
      stage's REG/STACK reported on the PR.
- [ ] The built `.pyd` embeds `sm_120` (`cuobjdump --list-elf`) and is fresh vs
      HEAD; RTX sweep run at closeout.
- [ ] A heterogeneous VDB smoke renders on the GPU and is inspected qualitatively
      by Astra or Claude (visual evidence saved).

---

## Non-goals

- Do not add emission / blackbody / temperature grids — pkg270.
- Do not add heterogeneous volume passes/AOVs — pkg271.
- Do not change the homogeneous world-volume path (`GWorldVolume`).
- Do not grow the shared shade kernel's register footprint.
- Do not add velocity/motion blur or multi-scatter — pkg272.

---

## Progress

- [x] Confirm `NanoVDB.h` compiles under nvcc for sm_120 (standalone probe
      `nvcc -arch=sm_120 -std=c++17`, exit 0, before any engine code).
- [x] Device grid upload + `__constant__` side-table (`GWavefrontGridVolumeBinding`,
      ≤ 8 media; the position-independent NanoVDB buffer is byte-copied).
- [x] `stage_volume_hetero.cu` (the only CUDA TU with NanoVDB.h): tracker,
      per-λ ratio-tracking Tr, `stageVolumeHeteroScatterKernel`. The isolation
      axis `HasGridVolume` sits on `intersectPathSlotT` / `stageIntersectQueuedKernel`
      / `stageShadowKernel`; per-path r_u + medium-id lanes ride the side table.
- [x] Dispatch wiring + frame-start publish (driver `gpu_wavefront_snapshot.cu`,
      next to `setWavefrontWorldVolume`; snapshot/ReSTIR drivers publish empty).
- [x] CPU↔GPU parity + byte-identity + REG gate + visual inspection (PR #820).
      The full RTX sweep is the lead's closeout.

### Known limitations (documented for reviewers)

- GPU emission = the CONSTANT term only. Blackbody emission is CPU-only (the
  Planck luminance normalisation is a host table) — a blackbody volume renders
  without its blackbody glow on the GPU. Follow-up.
- Global majorant per medium (no DDA over the pkg267 majorant grid) and
  nearest-entered-medium only, mirroring the CPU oracle (pkg272 scope).
- NanoVDB buffers are re-uploaded on every `render()` call (not part of the #801
  device scene cache); ≤ 8 media per scene (extra media are ignored with a stderr
  note).

---

## Lessons

- `GPUWavefrontState` is passed BY VALUE to every wavefront kernel: adding five
  lanes to it grew the STACK of all 128 `stageShadeBucketedKernel` instantiations
  by 40 B (REG stayed 254). New per-path data belongs in a driver-allocated array
  published through a `__constant__` binding, never in the state struct.
- A runtime `if (binding.count > 0)` in a "lean" kernel is NOT free: it changed
  the fleet shadow kernel's REG/STACK (108/584 → 109/864). Only a `template<bool>`
  axis restored byte-identical fleet kernels.
- `far`/`near` are `windef.h` macros under MSVC+nvcc; and a second CUDA TU must
  sit in the same namespace as the TU that includes a shared `.cuh` inside one,
  or the rdc device symbols and `extern __constant__` names will not match.
</content>
