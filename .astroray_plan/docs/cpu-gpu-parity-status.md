# CPU/GPU parity — status, the caustics fork, and the new work to do

**Created:** 2026-05-30 (after the pkg109/110 forward-caustics refactor).
**Why this doc exists:** the owner asked whether the GPU/CPU **parity** work done
so far overlaps the caustic/spectral code refactored in pkg109/110 — i.e. whether
any parity work now needs to be **redone** — and asked to capture the answer plus
spec the **new** parity work the general-caustics chain creates. This is the
single place a future session should start for the CPU↔GPU-equivalence picture.

---

## TL;DR

- **The long-term goal (now written down): full CPU↔GPU rendering equivalence** —
  every integrator/feature runs on the GPU and matches the CPU result within a
  pinned numerical tolerance. Today this is pursued **per-feature** (each feature
  gets a GPU port + its own parity gate); there is **no single umbrella acceptance
  spec** that says "everything, with parity." This doc + the matrix below is the
  closest thing to that umbrella.
- **Does the pkg109/110 refactor invalidate existing parity work? NO.** The code
  changed in pkg109/110 (the **forward light-tracer + photon map**) is **net-new
  CPU code with no GPU counterpart and no parity gate**. It did **not** touch the
  SMS caustic path, the spectral pipeline, or any `src/gpu/*` file. Nothing needs
  redoing. Evidence below.
- **What IS new:** the general-caustics chain (pkg109/110/111) is a **second,
  CPU-only caustic mechanism** with **no GPU equivalence yet**. Porting it to the
  GPU with parity is brand-new work — filed as **pkg113** — and it forces an
  architectural fork with the existing **SMS** GPU caustics (pkg64-gpu). See §3.

---

## 1. Why the refactor does NOT touch existing parity (evidence)

pkg109 + pkg110 changed exactly **four** code files (`git diff --stat 6e22a11..HEAD`):

| File | Change | GPU-parity surface? |
|---|---|---|
| `include/astroray/photon/photon_map.h` | NEW (kd-tree + k-NN + density estimate) | none — no GPU photon map exists |
| `plugins/integrators/light_tracer_caustic.cpp` | rewrote the forward caustic tracer (grid→kd-tree; hybrid explicit-2-face / general loop) | none — this integrator is CPU-only (`capabilities()` = `{gpuSupported=false}`); no `src/gpu` reference |
| `include/astroray/param_dict.h` | added `getNumber` (additive) | none |
| `module/blender_module.cpp` | added test bindings + `set_integrator_param_float` (additive) | none |

Not touched: any `src/gpu/*.cu`, `sms_attempt*.{h,cuh}`, `spectral_path_tracer.cpp`,
`sms_caustic_path_tracer.cpp`, `raytracer.h` (the `SMSHook`/`pathTraceSpectral`),
`dielectric.cpp`, `spectrum.h`, `gpu_types.h`. The forward tracer **consumes** the
spectral pipeline (`SampledWavelengths`/`SampledSpectrum`/`XYZ`/`cieCmf1964_10deg`/
`iorAt`) unchanged. So the **spectral GPU parity (pkg54*) and the SMS GPU parity
(pkg64-gpu) are intact** — they gate code that this refactor did not modify.

> One-line answer to the owner's question: *no parity work needs to be redone; the
> refactor added a new CPU-only caustic path beside the existing ones.*

---

## 2. Existing CPU/GPU parity surface (what's already done / in-flight)

| Feature | CPU | GPU | Parity gate | Status |
|---|---|---|---|---|
| Backend capability contract (materials lower to a shared CPU/GPU closure or fall back) | ✓ | ✓ | declared per-material | **done** (pkg34–37) |
| Spectral / multi-wavelength path tracer (megakernel mirror, CMF table, Jakob–Hanika upsample, profile dispatch) | ✓ | ✓ | visible-band SSIM 0.999 @8192 spp | **done, HW-verified** (pkg35, pkg54/54a–d) |
| **SMS / MNEE refractive caustics** (camera-side specular-manifold Newton solve, per-bounce hook) | ✓ | ✓ (megakernel) | GPU-vs-CPU SMS SSIM ≥ 0.97; receiver-energy ratio; empty-hook cost | **code landed**; HW acceptance partly **blocked on multi-IOR** (pkg64-gpu Session 2) | 
| Sellmeier dispersion upload (hero-λ IOR on GPU) | ✓ | ✓ | BK7 IOR ≤1e-4 rel-err | **done** (pkg64-gpu-sellmeier-upload) |
| Wavefront CUDA port (SoA path state; per-stage kernels) | ✓ (reference wavefront) | partial | **per-stage CPU↔GPU ULP/threshold gates** (PostInit ULP=2, PostIntersect ≤32, NEE/RR p99.9) | **in-flight** (pkg55, pkg55-B' sessions) — the bit-equivalence backbone |
| GPU Light Tree (SAOH split + Conty 2018) | ✓ | — | 2× variance gate | CPU Phase 1 done; **GPU deferred** (pkg86-B) |
| Viewport interactivity parity (CUDA vs CPU walltime) | ✓ | ✓ | ≤ Cycles on equal load | measured; CUDA slower (register pressure) → pkg55 Phase B (pkg81) |
| Denoiser (OIDN + OptiX, CUDA backend) | ✓ | ✓ | SSIM / variance-reduction gates | **done** (pkg33/68/69/70/72/73/75) |
| World/HDRI, vertex normals, etc. | ✓ | ✓ | SSIM | **done** (pkg61/63/85-D …) |
| **Forward photon-map caustics** (Jensen 1996: light-tracer + kd-tree + gather) | ✓ (pkg106/109/110; pkg111 pending) | **— none —** | **— none —** | **CPU-ONLY; NO GPU; the new gap** |

**The pkg55 wavefront port is the methodology for "full equivalence":** it rebuilds
the path tracer as CUDA wavefront stages and gates each stage to bit-/ULP-identical
CPU output. Extending that *discipline* (a pinned CPU↔GPU tolerance per feature) to
the remaining features — including the new caustics — is what "full equivalence"
concretely means here.

---

## 3. The caustics fork (the real new decision)

Astroray now has **two caustic mechanisms** that overlap for focusing casters:

1. **Camera-side SMS / MNEE** (pkg64 CPU, pkg64-gpu GPU). Receiver→caster→light
   specular-manifold Newton connection, hooked into the default `path_tracer` at
   non-delta vertices via `use_refractive_caustics` + per-object `is_caustic_caster`.
   **Has a GPU port** (megakernel; parity-gated; HW acceptance partly blocked on
   multi-IOR). Good for a focusing caster (sphere/lens). pkg106 found it **unsuitable
   for a flat prism** (no focus → spatially-chaotic connection → salt-and-pepper).
2. **Forward photon-map** (pkg106/109/110/111). Trace photons *from the light through
   glass*, deposit on diffuse surfaces, gather (kd-tree k-NN density estimate). The
   **general** approach: a flat prism rainbow AND a focusing sphere both work (pkg110
   hybrid auto-selects explicit-2-face for flat prisms, general loop for curved
   casters). **CPU-only today.** Will be wired into the default path by pkg111.

These overlap: a **glass sphere** caustic is now achievable by *both* the SMS-GPU
path and the forward photon map. That redundancy is fine on CPU, but on GPU it is a
fork: **which is the canonical GPU caustic path?**

**Owner decision needed (not made here):**
- **(a) Photon map becomes the canonical caustic path** (CPU + GPU); SMS-GPU
  (pkg64-gpu) is frozen/legacy or kept only for pure specular-manifold cases not
  covered by forward tracing. Simplest long-term story; means pkg113 (GPU photon
  map) is the priority and pkg64-gpu Session 2 (multi-IOR) may be deprioritized.
- **(b) Keep both on GPU**: SMS for camera-side specular connections, photon map for
  general/diffuse-receiver caustics, combined (VCM-like). Most capable, most work.
- **(c) SMS stays the GPU caustic path; the forward photon map is CPU-only** (e.g.
  a preview/reference path). Cheapest, but contradicts the "everything on GPU"
  goal and leaves the prism rainbow CPU-only on GPU renders.

Recommendation to evaluate: **(a)**, because the forward photon map is strictly more
general (handles flat prisms, which SMS cannot) and pkg111 puts it on the default
path anyway — but this is the owner's call and should be decided before pkg113 starts.

---

## 4. The new parity work (filed)

- **pkg113 — GPU photon-map caustics + CPU/GPU parity** (`packages/pkg113-gpu-photon-map-caustics.md`).
  Port `photon_map.h` (build + k-NN gather) and the forward photon bounce to CUDA,
  with CPU↔GPU parity gates (mirroring the pkg64-gpu SSIM gate + the pkg55 ULP/
  threshold discipline). **GPU-gated**: CI has no GPU, so correctness must be
  RTX-`/verify`-ed; CI-green ≠ correct for it. **Depends on** pkg109 (done), pkg110
  (done), pkg111 (the CPU default-path gather — do first), and the §3 fork decision.

Related already-filed GPU follow-ups that stay relevant: **pkg64-gpu Session 2**
(multi-IOR), **pkg86-B** (GPU light tree), **pkg55-B'** (wavefront sessions) — and,
per the pkg64-gpu spec, when **pkg55-C** removes the megakernel, the SMS dispatch
must move to the wavefront `stage_shade_*` kernels (and likewise any GPU caustic
chosen in §3).

---

## 5. Maintenance

Update the §2 matrix whenever a feature's GPU/parity status changes, and resolve §3
when the owner picks a/b/c. Keep this doc linked from `STATUS.md` and
`NEXT_STAGE_REPORT.md`.
