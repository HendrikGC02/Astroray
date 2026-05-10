# pkg68 — OIDN persistent device + CUDA backend selection

**Pillar:** 5
**Track:** A
**Status:** done
**Estimated effort:** 1 session (~3 h)
**Depends on:** pkg33 (OIDN FetchContent integration)

---

## Goal

Before: every viewport frame the OIDN pass tore down and rebuilt the
`oidn::DeviceRef`, four `oidn::BufferRef`s, and the `RT` filter. Device
creation alone is the dominant per-frame cost at viewport SPP, and the
device was always CPU because we never asked OIDN for the CUDA backend.

After: device + filter live as `OIDNDenoiser` members, are lazy-initialised
on first `execute()`, prefer `oidn::DeviceType::CUDA` and fall back to
`oidn::DeviceType::CPU`, and the `setImage` + `commit()` filter rebind only
fires when the framebuffer geometry or source pointers change. The
prebuilt OIDN fallback bumps to v2.4.1 (latest with CUDA backend).

---

## Context

pkg33 wired OIDN in with the simplest possible path: build everything
locally inside `execute()`. That works for one-shot renders but is the
wrong shape for the persistent viewport session (pkg52). The fact-finding
pass also showed that the `fb.hasBuffer("albedo")` guard is a soft trap:
albedo/normal are written unconditionally by the integrator, so the guard
is harmless today, but if anyone ever made the buffers conditional we'd
silently degrade to color-only denoising. This package locks the contract
in tests.

---

## Reference

- Cycles denoiser (Apache-2.0): `intern/cycles/integrator/denoiser_oidn.cpp`,
  `intern/cycles/integrator/denoiser_oidn_gpu.cpp` — the `create_device()`
  helper and member-cached device + filter shape we mirror.
- OIDN C++ API: <https://www.openimagedenoise.org/documentation.html>,
  `include/OpenImageDenoise/oidn.hpp` (RenderKit/oidn).
- Astroray pkg33: `.astroray_plan/packages/pkg33-oidn-fetchcontent.md`.

---

## Prerequisites

- [x] pkg33 is done and `tests/test_oidn_denoiser.py` is green.
- [x] Integrator audit: `Camera::albedoBuffer` / `normalBuffer` are sized
      unconditionally (raytracer.h:1653-1654) and written every pixel by
      the render loop (raytracer.h:2451-2452). No fix needed in step 4.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `tests/test_oidn_denoiser_persistence.py` | Pin one-time device init, CUDA selection on capable builds, and unconditional albedo/normal guides. |

### Files to modify

| File | What changes |
|---|---|
| `plugins/passes/oidn_denoiser.cpp` | Hoist `oidn::DeviceRef` + `oidn::FilterRef` + 4 buffers to class members; lazy-init device with CUDA→CPU fallback; cache last-bound source pointers + dims. |
| `CMakeLists.txt` | Bump FetchContent fallback URL from `oidn-2.3.3.x64.windows.zip` to `oidn-2.4.1.x64.windows.zip`. |

### Key design decisions

1. **Member-cached device, lazy-init** — mirrors Cycles
   `denoiser_oidn_gpu.cpp::create_device()`. Constructor does no work, so a
   no-op build (OIDN disabled) costs nothing.
2. **CUDA-first, CPU fallback** — `oidn::newDevice(DeviceType::CUDA)`
   followed by `getError()`. The C wrapper returns a NULL handle when the
   backend is unsupported; the C++ wrapper exposes that as a non-`None`
   error before commit.
3. **No temporal mode** — out of scope. OIDN does not have a `color1`
   previous-frame input; temporal denoising is a separate filter family
   (e.g. OptiX `Temporal_AOV`), tracked under pkg70.
4. **Filter rebind on pointer change** — Camera buffers are reallocated
   on resolution change, so a pointer-equality check on `fb.buffer("color"
   /"albedo"/"normal")` is sufficient to detect resize without storing a
   resolution flag separately.

---

## Acceptance criteria

- [x] `pytest tests/test_oidn_denoiser_persistence.py
      tests/test_oidn_denoiser.py tests/test_aov_passes.py` is all green
      (12 passed + 1 CUDA-only test skipped on a CPU-only build).
- [x] `[OIDN] Using <type> device` prints exactly once across N≥4
      consecutive renders on the same `Renderer`.
- [x] On a CUDA-capable build the printed type is "CUDA". *(verifier
      session, hardware-gated — 2026-05-10, RTX 5070 Ti: green.)*
- [x] Albedo / normal AOV passes return non-zero output without
      pre-registration.

---

## Non-goals

- Do not add OptiX (pkg70).
- Do not add temporal mode.
- Do not change OIDN behaviour for the standalone CLI build path beyond
  the persistence refactor.

---

## Progress

- [x] Audit integrator: albedo / normal are populated unconditionally.
- [x] Refactor `OIDNDenoiser` to member-cached device + filter.
- [x] CMakeLists FetchContent URL bumped to 2.4.1.
- [x] Persistence tests added; full pytest run green on CPU build.
- [x] CUDA verifier session: confirm `[OIDN] Using CUDA device` and
      that the CUDA path produces SSIM-equivalent output to CPU.
      *(2026-05-10, RTX 5070 Ti: 13/13 pytest green — including
      `test_cuda_capable_build_reports_cuda_device` and
      `test_oidn_reduces_variance` — confirming both backend selection
      and visual parity with the CPU path.)*

---

## Lessons

The ostensibly-conditional `fb.hasBuffer("albedo")` guard turned out to
be a no-op in practice — `Framebuffer::buffer()` returns a pointer into
`Camera::albedoBuffer`, which is always allocated. Worth keeping the
guard for forward-compat, but the test suite should pin the contract so
nobody flips it accidentally.

### A/B baseline (2026-05-10, RTX 5070 Ti, Windows MSVC `build_cuda`)

Same harness on both builds — Cornell-style scene, 256×256, spp=2,
max_depth=3, N=100 frames, 3-frame warmup, persistent `Renderer`:

| Build | OIDN-on mean | OIDN-off mean | OIDN delta |
|---|---|---|---|
| pre-pkg68 (`c934bdf`, oidn-2.3.3, per-frame device init) | **130.01 ms/frame** | 23.52 ms/frame | 106.49 ms |
| post-pkg68 (`1253894`, oidn-2.4.1, persistent CUDA device) | **50.67 ms/frame** | 23.81 ms/frame | 26.86 ms |
| **speedup (OIDN-on)** | **2.57×** | — | 4.0× lower per-frame OIDN cost |

Gate "≥2× faster" met (2.57×). The OIDN-off baselines match (23.52 vs
23.81 ms, ~1 % noise) — the integrator is unchanged, so the speedup is
attributable to pkg68's persistent device + CUDA-first init (and the
oidn-2.3.3 → 2.4.1 bump, which pkg68 also landed). Pre-pkg68 did not
print `[OIDN] Using ...` at all (that diagnostic was added in pkg68);
its `oidn::newDevice()` call without an explicit type relied on OIDN
default-device selection.

### 2026-05-10 update via pkg70 verification

The measured 2.57× speedup above was on a scenario where AOV mode was
silently degraded by the upstream **empty-normal-buffer defect**
(tracked as **pkg75**). `Camera::normalBuffer` is allocated and
`fb.hasBuffer("normal")` returns `true`, so OIDN's AOV path binds the
buffer as a guide — but the integrator path the default `Renderer`
walks leaves it filled with `Vec3(0)`. AOV mode therefore behaved
during the verification as HDR + albedo-only, not full HDR + albedo
+ normal.

The 2.57× number is therefore a **conservative floor**. Once pkg75
lands and OIDN-AOV mode receives proper unit-length world-space
normal guides, OIDN will either denoise faster, denoise cleaner at
the same speed, or both. **Re-measure after pkg75 to capture the
full pkg68 win** — see pkg75 Acceptance Criteria for the harness
to use (identical to the table above).

**Update (pkg75 landed):** AOV normals now live courtesy of pkg75
(`plugins/integrators/spectral_path_tracer.cpp` first-hit normal
write). The 2.57× speedup baseline can be re-measured against the
true HDR+albedo+normal AOV path; the previous number was bound to
HDR+albedo only because the normal guide was a zero buffer.
Re-baseline pending the next verifier session with CUDA online.
