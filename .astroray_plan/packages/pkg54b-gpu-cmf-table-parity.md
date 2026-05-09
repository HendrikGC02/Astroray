# pkg54b — GPU CIE-CMF Table Parity

**Pillar:** 5
**Track:** A
**Status:** implemented (pending CUDA build + parity verification on a CUDA box)
**Estimated effort:** ~2 h
**Depends on:** pkg54

---

## Goal

**Before:** The pkg54 GPU multi-wavelength megakernel projects sampled
spectra to XYZ via Wyman/Sloan/Shirley 2013 multi-Gaussian fits to the
CIE 1931 2° observer. The CPU integrator uses
`cieCmf1964_10deg` from [src/spectrum.cpp](src/spectrum.cpp) — a 1 nm
table for the CIE 1964 10° observer. The two CMFs differ in peak
weighting (~5 % on Y) and slightly in chromaticity, so visible-band CPU
vs GPU output picks up a small uniform luminance/chroma bias even at
identical samples.

**After:** GPU and CPU evaluate the *same* CMF — the existing
`data/spectra/cie_cmf.inc` table — by uploading the 471-sample 1 nm grid
to CUDA `__constant__` memory and replacing the Wyman fit with a linear
interpolated lookup.

---

## Context

This was a deliberate shortcut taken in pkg54 to avoid host-side LUT
plumbing on the GPU. The Wyman fits keep the kernel table-free and ship
as plain C math, but they are not the same observer — visible-band
parity should be picked up by the pkg54 SSIM ≥ 0.97 gate, but exact
parity (≥ 0.99) requires the same observer on both sides.

---

## Reference

- Existing CPU table: [src/spectrum.cpp](src/spectrum.cpp)
  (`cieCmf1964_10deg` + `data/spectra/cie_cmf.inc`).
- Wyman, Sloan, Shirley, "Simple Analytic Approximations to the CIE XYZ
  Color Matching Functions", JCGT 2(2), 2013 — what we currently use on
  GPU; replace with the 1964 10° table for parity.

---

## Specification

### Files to modify

| File | What changes |
|---|---|
| `src/gpu/multiwavelength_kernel.cu` | Replace `wymanCmf()` with a `__constant__`-memory table lookup mirroring `sampleTable()` from spectrum.cpp. Drop the Wyman gauss helper. |
| `src/gpu/cuda_renderer.cu` | One-time upload of `data/spectra/cie_cmf.inc` to the kernel's constant-memory CMF arrays. |
| `tests/test_gpu_multiwavelength.py` | Tighten visible-band SSIM gate from 0.97 to 0.99. |

### Key design decisions

1. **Constant memory.** 471 × 3 × 4 B = 5.6 KB — trivially fits.
2. **Upload at module init or first MW render** (one-time copy from the
   baked C table to the device).
3. **Same interpolation semantics** as `sampleTable()`: linear, clamped
   to grid endpoints.

---

## Acceptance criteria

- [ ] Visible-band CPU vs GPU SSIM ≥ 0.99 on the pkg54 parity scene at
  64 spp.
- [ ] Bit-equal CMF values between CPU `cieCmf1964_10deg(λ)` and a small
  Python harness that calls a new test-only `gpu_cmf_lookup(λ)` binding,
  to within ε = 1e-6.
- [ ] No regression in NIR/UV gates.

---

## Non-goals

- No change to the CPU CMF (still 1964 10°).
- No host-side observer switching (no UI for picking 1931 vs 1964).

---

## Progress

- [x] Embed CMF table in constant memory ([src/gpu/multiwavelength_kernel.cu](src/gpu/multiwavelength_kernel.cu): `g_cmfX/Y/Z`).
- [x] Replace Wyman 2013 fit with table lookup (`cmfSample()` + new `spectrumToXYZ()`).
- [x] Upload table from cuda_renderer.cu via `uploadCmfTables()` (called once in `renderMultiwavelength`).
- [x] Tighten visible-band SSIM gate to 0.99 ([tests/test_gpu_multiwavelength.py](tests/test_gpu_multiwavelength.py)).
- [ ] Verification on a CUDA box still pending.

---

## Lessons

*(Fill in after the package is done.)*
