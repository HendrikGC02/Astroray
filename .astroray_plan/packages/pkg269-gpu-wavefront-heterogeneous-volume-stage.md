# pkg269 — GPU wavefront heterogeneous volume stage (NanoVDB device grid)

**Pillar:** 3
**Track:** A
**Status:** open
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

- [ ] Confirm `NanoVDB.h` compiles under nvcc for sm_120.
- [ ] Device grid upload + `__constant__` side-table.
- [ ] `stage_volume_hetero.cu` (`template<bool HasGridVolume>`) + snapshot lanes.
- [ ] Dispatch wiring + frame-start publish.
- [ ] CPU↔GPU parity + byte-identity + REG gate; RTX sweep; visual inspection.

---

## Lessons

*(Fill in after the package is done.)*
</content>
