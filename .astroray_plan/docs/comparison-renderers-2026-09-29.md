# Comparison renderers: shortlist, install plan, benchmark design (2026-09-29)

Companion to `research-noise-2026-09-29.md`. Nothing has been installed; each
install below needs owner approval. Facts are from web reading on 2026-09-29.
Items marked UNVERIFIED could not be confirmed from a primary page.

## Why other engines

- **Cycles is RGB.** It cannot arbitrate spectral effects: dispersion, chromatic
  media, line emitters. Nor can it tell a transport path Astroray renders and
  Cycles skips from an Astroray bug. The `v2_dispersion_caustics` floor tail and
  the GPU prism beam are live examples.
- **Noise per time.** Only Cycles CPU/OptiX is measured today (the Cycles OptiX
  leg works headless with no install; see `rs-noise/e2`). One more independent
  path tracer tells us whether Cycles is simply fast or we are slow.

## Shortlist

| engine | licence / cost | Windows + RTX 5070 Ti | spectral | Blender route | validates | verdict |
|---|---|---|---|---|---|---|
| **Mitsuba 3.9.1** (PyPI, 2026-08-07) with Dr.Jit 1.5.0 | BSD-3, free | wheels cp39-cp314 win_amd64 (~46 MB). Dr.Jit 1.3.0 changelog lists Blackwell SM120 work. `cuda_ad_spectral` on sm_120 is UNVERIFIED until tried; `llvm_ad_spectral`/`scalar_spectral` CPU are the fallback | yes (`*_spectral` variants), `volpath`, spectral IOR dielectric | `mitsuba-blender` extension (Blender ≥ 4.2; bundles Python 3.13 wheels for 5.1+; 5.2 UNVERIFIED): exports Principled/Diffuse/Glass/Emission, meshes, cameras. World/HDRI export UNVERIFIED | **spectral ground truth**: dispersion, chromatic media, emission spectra; noise-per-time of a spectral PT; our chi2 harness already mirrors it | **install first** |
| **pbrt-v4** (source) | Apache-2.0, free | CPU build: CMake + MSVC, supported on Win 10/11. GPU: CUDA + OptiX 7.1+; open issues #429 (MSVC ≥ 14.40 GPU), #532 (`--gpu` crash). sm_120 untested | yes (the reference for `SampleVisible`, which we ported in pkg206) | no maintained Blender 5 exporter (`bpbrt4` maintenance UNVERIFIED; `io_scene_pbrt` v4 "in development"). Hand-written `.pbrt` scenes for 3-4 arbitration cases | second spectral oracle (tie-break vs Mitsuba); `ZSobolSampler` reference for pkg297 follow-ups | **install second, CPU-only** |
| **LuxCoreRender** (BlendLuxCore v2.11.1, runtime LuxCore 2.12.2) | Apache-2.0, free | release notes claim Blender 4.5 and 5.2 LTS; CUDA/OpenCL on Blackwell UNVERIFIED | UNVERIFIED (treat as RGB) | Blender extension; own material system, partial Cycles-node conversion | independent production engine: BiDir + PhotonGI caustic cache on caustic scenes; noise-per-time "big gun" | optional, third |
| Blender EEVEE | free, installed | yes | no | native | viewport-speed context only | no install; not a PT reference |
| Arnold / V-Ray / RenderMan NC / Karma (Houdini Apprentice) / Octane | trial, watermark or non-commercial terms; Karma ~3 GB via USD | mixed | partial at best | weak or USD | would be "big gun" optics, but licence terms bar publishing numbers or automating runs | skip |
| Appleseed, Tungsten | unmaintained | n/a | no / partial | poor | n/a | skip |
| Falcor, LuisaRender | research frameworks | build-heavy | Luisa: yes | custom exporter | n/a vs effort | skip for now |

## Install plan (for the owner)

Keep tools outside OneDrive to avoid sync churn. Obey the machine-load rules: no
build overlapping a CUDA build or GPU suite, `-j 6`.

1. **Mitsuba 3 (about 0.2 GB).**
   ```
   python -m venv C:\Users\hgcom\tools\venv-mitsuba
   C:\Users\hgcom\tools\venv-mitsuba\Scripts\pip install mitsuba==3.9.1
   C:\Users\hgcom\tools\venv-mitsuba\Scripts\python -c "import mitsuba as mi; print(mi.variants()); mi.set_variant('cuda_ad_spectral'); print('ok')"
   ```
   - Source: https://pypi.org/project/mitsuba/ and https://pypi.org/project/drjit/.
     pip pulls `drjit`; its wheel size is UNVERIFIED (the 28-wheel set totals 131 MB).
   - Optional: the `mitsuba-blender` extension zip from
     https://github.com/mitsuba-renderer/mitsuba-blender/releases, installed via
     Blender Preferences > Get Extensions > Install from Disk. Size UNVERIFIED; it
     bundles wheels, so expect ~100 MB. If 5.2 support fails, pkg307 writes a
     minimal exporter for the arbitration scenes only.
2. **pbrt-v4, CPU only (source ~0.2-0.4 GB UNVERIFIED, build ~1 GB).**
   ```
   git clone --recursive https://github.com/mmp/pbrt-v4 C:\Users\hgcom\tools\pbrt-v4
   cmake -S C:\Users\hgcom\tools\pbrt-v4 -B C:\Users\hgcom\tools\pbrt-v4\build -G "Visual Studio 17 2022"
   cmake --build C:\Users\hgcom\tools\pbrt-v4\build --config Release -j 6
   ```
   Leave the OptiX path variable (`PBRT_OPTIX_PATH`) unset. The README says the
   GPU path needs it, so without it the build should be CPU-only. Check the
   configure log before building. The GPU build (OptiX SDK, NVIDIA developer
   login) is deferred.
3. **BlendLuxCore v2.11.1 (optional; zip size UNVERIFIED, plus the LuxCore
   runtime download).** Get it from
   https://github.com/LuxCoreRender/BlendLuxCore/releases/tag/v2.11.1 and
   install from disk.

## Benchmark design (pkg307)

- **Scenes.**
  - Corpus v2 (8). The seed renders and Cycles 1024 spp refs already exist.
  - The pkg294 cubes.
  - Three spectral **arbitration scenes**, authored identically in
    Blender/Mitsuba/pbrt:
    - (a) SF11 prism under a sun, with its floor caustic;
    - (b) a chromatic homogeneous medium (sigma_s varying across RGB) lit by a
      rectangle lamp;
    - (c) a narrow-band emitter on a coloured diffuse wall.
  - Use box pixel filter 1 px, clamps off, filter glossy off, denoise off.
- **Legs.**
  - Astroray CPU and GPU.
  - Cycles CPU and OptiX: `render_leg.py` needs a `--cycles-device gpu` flag;
    today it hard-codes CPU for Cycles.
  - Mitsuba `llvm_ad_spectral` and `cuda_ad_spectral`.
  - pbrt-v4 CPU, on arbitration scenes only.
  - Same resolution per scene. GPU timing at ≥ 1280x720 (small frames under-fill
    the GPU: camera_geometry reads 16x at 320x180 and 3.8x at 1280x720).
- **Reference.**
  - Variance: each engine's own seed scatter.
  - Bias: a 16k spp render. Cycles for RGB-safe scenes; Mitsuba spectral for
    arbitration scenes, with pbrt-v4 as the tie-break.
  - Rule: if Mitsuba and pbrt agree within 3 sigma and Cycles differs, the Cycles
    row is marked "RGB reference limit", not an Astroray failure.
- **Metrics per scene and ROI.**
  - relVar (luminance) and chroma relVar.
  - relMSE split into variance + bias^2.
  - Top-0.1 % variance share (tails).
  - N x relVar slope over 4/16/64/256 spp.
- **Equal spp** at 64 and 256.
- **Equal time** at budgets of 2 s, 10 s and 60 s. Use render-only time via
  spp differencing: t(N2) − t(N1) removes Blender start-up, as done in
  `rs-noise/e1`.
  - Efficiency = 1 / (relMSE x t).
  - Burn-in plus min-of-3 for GPU clock drift (`gpu-perf-ab-clock-drift`).
- **Output.** One committed table per run, plus contact sheets at equal time (not
  against a 1024 spp reference), under `test_results/noise_bench/`.
- **Home.** Extend `benchmarks/reference_corpus/mc_tolerance.py`'s render/leg
  plumbing, or `scripts/diagnostics/convergence_tracker.py` if pkg297 Phase 0
  lands its `--variance-slope` there first. No new parallel harness
  (CLAUDE.md §5b).
