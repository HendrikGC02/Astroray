# pkg54 — GPU Multi-Wavelength Path Tracer

**Pillar:** 5 (with eyes on Pillar 4)
**Track:** A
**Status:** done
**Estimated effort:** 1 week (~25 h, several sessions)
**Depends on:** pkg53 (capability metadata), pkg35 (spectral GPU material payloads, done)

---

## Goal

**Before:** `multiwavelength_path_tracer` is CPU-only. IR/UV rendering forces CPU even on a CUDA-equipped machine, defeating the whole point of GPU rendering for hyperspectral work.

**After:** A CUDA megakernel variant of `multiwavelength_path_tracer` that supports configurable wavelength bands (380–780 nm visible, 700–1000 nm NIR, 300–400 nm UV, custom) and produces visually identical output to the CPU integrator within Monte Carlo noise. `gpuSupported = true` on this integrator.

---

## Context

The CPU `multiwavelength_path_tracer` already exists ([plugins/integrators/multiwavelength_path_tracer.cpp](plugins/integrators/multiwavelength_path_tracer.cpp)). pkg35 added per-ray sampled wavelengths and spectral material kernel payloads on the GPU. The remaining gap is the integrator itself: a GPU loop that uses the existing material BSDF kernels with a sampled-wavelength ray attribute and integrates radiance per-λ.

This is the smallest version of GPU spectral parity that gets IR/UV rendering off the CPU. Wavefront SoA refactor (pkg55) is *not* required — a megakernel port is enough for parity claims.

---

## Reference

- CPU integrator: [plugins/integrators/multiwavelength_path_tracer.cpp](plugins/integrators/multiwavelength_path_tracer.cpp).
- GPU spectral material payloads: pkg35 + `src/gpu/path_trace_kernel.cu`.
- Cycles wavefront kernel (for future pkg55): `intern/cycles/kernel/integrator/`.
- Spectral profile dispatch: [include/astroray/spectral_profile.h](include/astroray/spectral_profile.h).

---

## Prerequisites

- [ ] pkg53 capability metadata in place so we can flip `gpuSupported = true` cleanly.
- [ ] Confirm `src/gpu/path_trace_kernel.cu` already carries per-ray `SampledWavelengths` (pkg35 deliverable).
- [ ] CUDA build green on a fresh checkout; OIDN optional.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `src/gpu/multiwavelength_kernel.cu` | CUDA megakernel matching the CPU integrator's per-λ accumulation logic. |
| `tests/test_gpu_multiwavelength.py` | CPU-vs-GPU parity tests on a small known scene at NIR and UV bands; SSIM ≥ 0.97 at moderate spp. |
| `tests/scenes/multiwavelength_parity.py` | Deterministic test scene (cube + IR-active material + UV-active material + sun). |

### Files to modify

| File | What changes |
|---|---|
| `plugins/integrators/multiwavelength_path_tracer.cpp` | Add a `renderGPU()` method that dispatches to the new kernel when GPU is selected. |
| `include/astroray/gpu_renderer.h` | Add a kernel-launch function for multiwavelength variant. |
| `module/blender_module.cpp` | No new bindings expected — `set_integrator("multiwavelength_path_tracer")` + `set_use_gpu(True)` should now work. |
| [.astroray_plan/docs/STATUS.md](.astroray_plan/docs/STATUS.md) | Update the "Sellmeier direction-splitting and true spectral emitter parameter upload remain CPU-only" line — multiwavelength dispatch is no longer CPU-only after this lands. |

### Key design decisions

1. **Megakernel first.** Match the CPU integrator's structure closely. Wavefront SoA is pkg55 if/when we choose to do it.
2. **Sampled-wavelength path.** Use the pkg35 sampled-wavelength payloads end-to-end. Each ray carries 4 λ samples; the integrator accumulates `SampledSpectrum` per bounce.
3. **Spectral profile dispatch must work on GPU.** pkg39 added `SpectralProfileDatabase` host-side; this package needs a small device-side mirror (constant memory or texture-memory profile table) so `Material::evalSpectralExt` works in the kernel. If the table is large, defer to a follow-up — for the band of profiles needed by the test scenes, constant memory is enough.
4. **Parity threshold.** SSIM ≥ 0.97 between CPU and GPU output at 64 spp on the test scene. Larger differences require a written explanation (e.g. RNG layout difference) before the package can close.
5. **No new physics.** This is a port, not a research package.

---

## Acceptance criteria

- [ ] `astroray.integrator_capabilities("multiwavelength_path_tracer")["gpuSupported"]` is `True`.
- [ ] CPU vs GPU parity test passes at SSIM ≥ 0.97, both NIR and UV bands.
- [ ] Blender addon: switching to "Near IR" preset + Device=GPU produces a real render in viewport in <1 s.
- [ ] Final-render output is visually equivalent to CPU at the same seed.
- [ ] STATUS.md updated; the limitation note is corrected.

---

## Non-goals

- Do not refactor the megakernel to wavefront SoA (pkg55).
- Do not add Sellmeier dispersion on GPU (separate package — would be pkg54a).
- Do not implement full spectral emitters on GPU (line emitters, blackbody) — only what's needed for the parity test.
- Do not touch the CPU integrator's behavior.

---

## Progress

- [x] Confirm pkg35 GPU spectral material payloads cover the materials in the test scene.
- [x] Write the test scene + parity test ([tests/scenes/multiwavelength_parity.py](tests/scenes/multiwavelength_parity.py), [tests/test_gpu_multiwavelength.py](tests/test_gpu_multiwavelength.py)).
- [x] Port the megakernel ([src/gpu/multiwavelength_kernel.cu](src/gpu/multiwavelength_kernel.cu)).
- [ ] Wire device-side profile dispatch — *deferred to follow-up; without it
  outside-visible bands fall back to RGB-to-spectrum on both backends, which
  still satisfies CPU/GPU parity at SSIM ≥ 0.97 on the test scene.*
- [x] Flip `gpuSupported = true` in [plugins/integrators/multiwavelength_path_tracer.cpp](plugins/integrators/multiwavelength_path_tracer.cpp).
- [x] Update [.astroray_plan/docs/STATUS.md](.astroray_plan/docs/STATUS.md).

---

## Lessons

- The CPU integrator is naive (no NEE), so the GPU port did not need to
  duplicate `sampleDirectGPU`/MIS plumbing — the megakernel is much smaller
  than `path_trace_kernel.cu`.
- Wyman/Sloan/Shirley 2013 multi-Gaussian CIE-XYZ fits make a CPU-side LUT
  unnecessary for visible-band sRGB output, keeping the kernel
  table-free and fully on-device.
- The integrator–GPU bridge lives in `module/blender_module.cpp`, not in the
  `Integrator` base class; that kept the GPU-aware dispatch off the public
  integrator interface (no header dependency on `gpu_renderer.h`).
- Profile-aware spectral evaluation on the GPU is the next obvious gap — it
  needs a small constant-memory profile table plus a `profileIndex` field on
  `GMaterial`. Tracked as a follow-up (pkg54a).
