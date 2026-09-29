# pkg313 — Spectral data cube + diagnostic AOVs, Phase 1 (CPU oracle): λ-bin accumulator, variance, path depth, ray count, FITS/EXR writer

**Pillar:** 5
**Track:** A
**Status:** open
**Estimated effort:** 2–3 sessions (~8 h), CPU only, no CUDA build
**Depends on:** pkg243, pkg297

---

## Goal

Before: every hero-wavelength sample is folded to XYZ at the pixel. No
spectral information survives the render. Sample count, variance, path depth
and ray count are internal heatmaps or absent. FITS is read-only.

After: an opt-in CPU render mode accumulates:
- a λ-bin radiance cube (user-set λ range and bin count, hero samples
  splatted with f/p);
- per-pixel sample count, per-channel variance (sum of squares), mean path
  depth and ray count (camera + bounce + shadow rays).

It writes them as a FITS cube (spectral WCS axis) and a multi-layer EXR, and
exposes them to Python as numpy arrays. With the mode off, the beauty is
bit-identical.

---

## Context

Owner 2026-09-29: "the output is just an RGB image, but it could output
complex data cubes with all the spectral (and depth, normal, ray count, ray
depth etc.) information — for future scientific analysis and diagnostics."
This is theme 4 Phase 1 (`product-themes-plan-2026-09-29.md` §4). The cube
must be exactly the accumulator pkg51 Phase 1 ("radiance microbins") will
consume, so it is built once. The diagnostic AOVs serve noise and
adaptive-sampling work now. Values are **relative** radiance with pkg243
provenance; no absolute-unit claim (north star "will NOT" #4). The GPU twin
and the Blender View Layer passes are Phase 2. This is an Opus 5.5 lane
(estimator correctness) with Terra review, CPU only. It must follow pkg297
P1a (the `Rng` retype in `raytracer.h`) and adopt the #867 sample-count AOV
contract.

---

## Evidence

- 2026-09-29: `kSpectrumSamples = 4` (`include/astroray/spectrum.h:25`). Samples are converted by `toXYZ(lambdas)` at `plugins/integrators/spectral_path_tracer.cpp:286` and `raytracer.h` ~4217/4479; `xyzToLinearSRGB` at ~5165. No per-bin storage.
- 2026-09-29: `Framebuffer` (`include/raytracer.h:2352`) exposes color/albedo/normal/depth/bounce_count/sample_weight/uv/motion/crypto. Position and IDs live on `Camera` and are not reachable via `buffer()`.
- 2026-09-29: `src/io/exr_writer.{h,cpp}` writes multi-channel float32. `src/io/fits_io.cpp` reads only (cfitsio linked).
- 2026-09-29: 1920×1080 × 64 bins × float32 = 531 MB; ×2 with the sum of squares.

---

## Reference

- Plan: `.astroray_plan/docs/product-themes-plan-2026-09-29.md` §4; pkg51 spec §Phase 1 (microbins); pkg243 (provenance headers); `docs/pillar4-data-io-research.md`.
- Spectral binning of hero-wavelength samples: Mitsuba 3 `specfilm` (BSD-3), the precedent pkg51 already cites; Wilkie et al. 2014 hero wavelength (EGSR). For bin b the estimator is (1/N)·Σ over samples and hero λⱼ ∈ b of f(λⱼ)/(p(λⱼ)·4), divided by Δλ_b for a per-nm density.
- FITS spectral WCS: Greisen et al. 2006, A&A 446, 747 (Paper III): `CTYPE3='WAVE'`, `CUNIT3='nm'`, `CRPIX3/CRVAL3/CDELT3`. cfitsio `fits_create_img` / `fits_write_pix`.
- Variance: Welford/sum-of-squares per pixel; the reported variance is of the per-pixel mean.
- Memory notes: `seed-zero-is-random-sentinel`, `mc-noise-vs-deterministic`, `gamma-vs-linear-comparison-artifact`.

---

## Prerequisites

- [ ] pkg297 P1a (the wide `Rng` retype in `raytracer.h`) merged.
- [ ] #867 (AN-3) merged; adopt its sample-count AOV name and contract.
- [ ] `cite-algorithm` note: `.astroray_plan/docs/pkg313-data-cube-research.md`.

---

## Specification

### Files to create

| File | Purpose |
|---|---|
| `src/io/fits_writer.cpp` | Write a float32 cube + 2D AOV extensions, spectral WCS and pkg243 provenance keywords |
| `include/astroray/fits_writer.h` | Declaration (large structs by `const&`, memory `mingw_large_struct_byval`) |
| `plugins/passes/spectral_cube.cpp` | Pass plugin: owns the cube and diagnostic buffers; registered via the pass registry |
| `tests/test_pkg313_data_cube.py` | Estimator, energy, variance, WCS, off-is-identical tests |

### Files to modify

| File | What changes |
|---|---|
| `include/raytracer.h` | `SampleResult` carries the 4 (λ, value/pdf) pairs and a ray counter; accumulation at ~5044–5190 splats into bins when the cube is enabled; path depth and sample count recorded |
| `plugins/integrators/spectral_path_tracer.cpp` | Populate the per-λ contributions and the ray count before `toXYZ` |
| `module/blender_module.cpp` | `enable_data_cube(lambda_min, lambda_max, bins)`, `get_data_cube()` → numpy dict, `write_data_cube(path, format)` |
| `CMakeLists.txt` | Compile `fits_writer.cpp` |

### Key design decisions

- **Off costs nothing.** A runtime flag; with the cube off, the accumulation
  code path and the beauty are bit-identical (tested).
- **Bins store radiance density.** Per-nm radiance density in relative
  units, pre-display. The RGB beauty is not derived from the cube; the cube
  is a parallel estimator from the same samples.
- **Out-of-range λ** is counted in an under/overflow scalar per pixel, so
  energy bookkeeping is closed.
- **Ray count** = camera + bounce + shadow (NEE) rays actually traced.
  **Path depth** = the terminal bounce index, averaged over samples.
- **Formats.** FITS: primary HDU = cube (NAXIS3 = bins), image extensions
  for the AOVs. EXR: one layer per bin (`spectral.<λ_center_nm>`) plus the
  AOV layers, via `exr_writer`. HDF5/Zarr are out of scope.
- **MW integrator.** The multiwavelength (band) integrator is out of scope
  here. Its grey-average path is pkg243's.

---

## Acceptance criteria

- [ ] Colour consistency: ∫ cube(λ)·CMF(λ) dλ → linear sRGB reproduces the linear beauty per pixel within the 5-seed MC band (Cornell + one textured scene); systematic ratio 1.000 ± 0.01.
- [ ] Line test: a sodium-lamp scene (pkg214 profile) with 380–780 nm / 80 bins puts ≥ 95 % of the lamp-lit cube energy in the bins covering 585–595 nm.
- [ ] Variance: the variance AOV of the per-pixel mean agrees with the empirical variance over 8 independent seeds (seed ≠ 0) within 20 % median over pixels.
- [ ] FITS: astropy opens the file; the WCS spectral axis yields the bin centres to 1e-6 nm; the provenance keywords are present.
- [ ] Off-is-identical: beauty buffer bytes equal with the cube disabled, versus main.
- [ ] Full CPU suite green; `project_index.py lint` clean.

---

## Non-goals

- Do not add the GPU wavefront accumulator (Phase 2).
- Do not add Blender View Layer passes or UI (Phase 2, with pkg311's successor).
- Do not add SRF/QE/PSF or detector counts (pkg51).
- Do not make absolute radiometric claims.
- Do not add HDF5/Zarr writers.

---

## Progress

- [ ] Research note
- [ ] SampleResult + accumulation + off-identical test
- [ ] Diagnostic AOVs (sample count per #867, variance, path depth, ray count)
- [ ] FITS + EXR writers + Python API
- [ ] Consistency, line and variance tests; evidence PNG (cube slice + CMF reconstruction) inspected

---

## Lessons

*(Fill in after the package is done.)*
