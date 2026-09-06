# pkg132 — Host-mapped memory fallback (Cycles `device_impl.cpp` DEVICEMAP spill)

**Pillar:** 1 (CUDA device infrastructure / robustness)
**Track:** A (allocation-fallback logic is CPU/host-side; the degraded-but-correct render is verified on RTX under induced VRAM pressure)
**Codex-paste-ready:** no (device-allocation policy touching every large buffer's alloc path + a coldest-buffer selection heuristic — needs judgment about what to spill)
**Status:** superseded — host-mapped spill never needed; refile from the research doc if a scene exceeds device memory (2026-09-07 backlog triage)
**Estimated effort:** M (1–2 sessions per the research doc — pure CUDA, no architecture change)
**Depends on:** none. Independent of pkg55 Phase C. Complements pkg135 (demand-loaded sparse textures) — this is the low-cost first line of defense; pkg135 is the heavier second tier that only activates on observed texture overflow.

---

## Goal

**Before:** When a large buffer won't fit in VRAM, the allocation fails and the
render dies (OOM). On the 8 GB travel laptop this makes FITS-volume, photon-heavy,
or high-res-envmap scenes simply un-renderable rather than slow.

**After:** Port Cycles' device-mapped **pinned-host fallback**
(`device/cuda/device_impl.cpp`, Apache-2.0): on allocation failure, place the
**coldest** large buffers in device-mapped host memory via
`cuMemHostAlloc(CU_MEMHOSTALLOC_DEVICEMAP | CU_MEMHOSTALLOC_WRITECOMBINED)` (gated
on the `can_map_host` capability). The render **slows down instead of dying** — the
correct behavior for the memory-constrained hardware. Renders that OOM today
complete (slowly) after this lands.

---

## Design sketch (cite the research doc; don't duplicate it)

Full source record: `.astroray_plan/docs/2026-07-other-engines-research.md` §4
(priority 1). Mechanism:

- **Capability probe:** query `can_map_host`; the fallback is only available when the
  device supports mapped pinned memory (all target GPUs do).
- **Mapped allocation:** `shared_alloc()` uses
  `cuMemHostAlloc(... DEVICEMAP | WRITECOMBINED)` and maps the host pointer into the
  device address space. Kernels read it over PCIe — slow, but correct.
- **Headroom prediction:** Cycles uses `CU_CTX_LMEM_RESIZE_TO_MAX` +
  `reserve_local_memory()` to predict headroom *before* deciding what to spill (so it
  doesn't spill something it didn't need to). Port the prediction, not just the
  reactive catch.
- **Coldest-first selection:** spill the least-frequently-touched large buffers
  first. In Astroray those are, roughly coldest→hottest: FITS volume grids
  (`src/io/fits_io.cpp`), photon maps (`src/gpu/photon_store.cu`,
  `photon_emission.cu`), high-res env maps (`src/lights/background_light.cpp`),
  texture-atlas overflow (`src/gpu/scene_upload.cu`). Do **not** spill hot
  per-bounce SoA / BVH.

**Port note (from the research doc's verify-list):** the exact Cycles file owning
`move_textures_to_host` (GPU-device base class) must be pinned when implementing;
`shared_alloc` in `device_impl.cpp` is the verified anchor.

---

## Implementation plan

- **A. Capability + mapped-alloc primitive.** Add a `can_map_host`-gated
  `shared_alloc()` wrapper producing a device-mapped pointer; a compile/run flag to
  force-enable for testing under induced pressure.
- **B. Headroom prediction + coldest-first policy.** Predict VRAM headroom before
  large uploads; when a buffer won't fit, spill the coldest eligible buffer to mapped
  host memory instead of failing. Order the eligible list coldest→hottest as above.
- **C. Degraded-render gate.** A scene sized to exceed a synthetic VRAM cap must
  render correctly (image matches the in-VRAM reference within noise) via the
  fallback, and must **not** spill hot buffers.

---

## Acceptance criteria

- [ ] `can_map_host`-gated device-mapped allocation
      (`cuMemHostAlloc DEVICEMAP|WRITECOMBINED`) wrapper exists and maps into the
      device address space.
- [ ] Headroom predicted before large uploads (Cycles `reserve_local_memory` model);
      spill decision is coldest-first over the enumerated eligible buffers.
- [ ] A scene that OOMs today renders correctly via fallback (image == in-VRAM
      reference within noise) under an induced VRAM cap.
- [ ] Hot per-bounce SoA / BVH are never spilled; the fallback engages only on
      genuine allocation pressure (no perf regression when VRAM is sufficient).
- [ ] Capability-absent path degrades gracefully (clear error, no silent corruption).

---

## Non-goals

- **Not demand-paged sparse textures.** Page-granularity texture streaming is pkg135
  (OTK model); pkg132 is whole-buffer mapped fallback only.
- **Not BLAS/geometry streaming.** Out-of-core triangle streaming is deferred
  indefinitely per the research doc (astro scenes are volume/texture-heavy, not
  triangle-heavy).
- **Not a memory-budget UI.** The fallback is automatic; no new user knob.

---

## Algorithm sourcing (CLAUDE.md §6)

- **Cycles** `github.com/blender/cycles` — **Apache-2.0 (verified)**.
  `src/device/cuda/device_impl.cpp`: `shared_alloc()` with
  `cuMemHostAlloc(CU_MEMHOSTALLOC_DEVICEMAP | CU_MEMHOSTALLOC_WRITECOMBINED)`,
  `can_map_host` flag, `CU_CTX_LMEM_RESIZE_TO_MAX` + `reserve_local_memory()` headroom
  prediction; `move_textures_to_host` in the GPU-device base class (**pin the exact
  file at port** — research-doc verify item).
- **Jaroš et al.**, "GPU Accelerated Path Tracing of Massive Scenes", ACM TOG 40(2),
  2021, DOI 10.1145/3447807 — wavefront batching hides host-memory latency (our
  architecture); fetch the author preprint if the design leans on it (ACM page 403'd
  per the research doc).
- **Research doc:** `.astroray_plan/docs/2026-07-other-engines-research.md` §4
  priority 1 + adoption rank 4.

---

## Provenance

Filed from the **other-engines technique sweep (2026-07-19)**
(`.astroray_plan/docs/2026-07-other-engines-research.md` §4, adoption rank 4:
"robustness for FITS/photon-heavy scenes"). Owner goal: on the 8 GB travel laptop,
large astrophysical scenes should render slowly rather than fail outright.

---

## Progress

- 2026-09-07 backlog triage: status flipped to `superseded`. Previous status text: still-open — never implemented; no host-mapped/DEVICEMAP spill fallback in the repo, only the spec-filing PR #492.

- [ ] A — `can_map_host`-gated mapped-alloc primitive.
- [ ] B — headroom prediction + coldest-first spill policy.
- [ ] C — degraded-render gate under induced VRAM cap; hot buffers never spilled.

---

## Lessons

*(Fill in after the package is done.)*
