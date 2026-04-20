# External References

**Use these, do not reinvent.** Every entry has been vetted against the
pillars. Copying, linking, or depending on these saves weeks of
implementation time. When a work package calls for something, check
here first.

---

## 1. Plugin architecture (Pillar 1)

No external dependency. The registry pattern is ~50 lines of standard
C++. The inspiration is PBRT v4's `Registry` and Mitsuba 3's
`PluginManager`, but neither is directly usable as-is — we write our
own because a dependency for 40 lines of code is ridiculous.

---

## 2. Spectral core (Pillar 2)

### Reference implementations (read, learn, selectively port)

- **PBRT v4** — https://github.com/mmp/pbrt-v4
  - `src/pbrt/util/spectrum.h/.cpp` — canonical `SampledSpectrum`,
    `SampledWavelengths`, `RGBAlbedoSpectrum` design. Apache 2.0 —
    permissive, but we port the idea not the code (to avoid license
    contamination).
  - `src/pbrt/util/color.h` — CIE color matching functions.
- **Mitsuba 3** — https://github.com/mitsuba-renderer/mitsuba3
  - `src/librender/spectrum.cpp` — alternative design for cross-ref.
- **simple-spectral** — https://github.com/geometrian/simple-spectral
  - Minimal spectral renderer in ~1000 lines. Good reference for the
    Jakob-Hanika LUT reader specifically.

### Direct data dependencies

- **Jakob-Hanika coefficient tables** — pre-trained sigmoid coefficient
  LUTs for sRGB, ACES, etc. Download from the paper's supplementary
  materials page (Zenodo). Ship in `data/spectra/`. Apache 2.0.
  Loader is ~30 lines; format is documented.
- **CIE color matching functions** — ship as constants in
  `data/spectra/cie_cmf.inc`. Public domain data from
  http://cvrl.ucl.ac.uk/ (download the 1964 10° observer).

### Measured BRDFs

- **RGL material database** — https://rgl.epfl.ch/materials
  Spectral measured BRDFs. Permissive for research/artistic use.
  Integration as a plugin: `plugins/materials/measured.cpp` loads
  the `.bsdf` files directly.
- **MERL BRDF database** — https://www.merl.com/brdf/
  ~100 isotropic BRDFs, no spectral info (RGB only). Secondary.

---

## 3. Light transport (Pillar 3)

### ReSTIR DI

- **RTXDI SDK** — https://github.com/NVIDIA-RTX/RTXDI
  Production-quality ReSTIR implementation. MIT license. We port the
  CUDA kernels, not the D3D12 plumbing.
- **Ray Tracing Gems II, ch. 23** — https://github.com/Apress/Ray-Tracing-Gems-II
  Simpler reference implementation.
- **Original paper**: Bitterli et al. 2020.

### Neural Radiance Caching

- **tiny-cuda-nn** — https://github.com/NVlabs/tiny-cuda-nn
  Fused-MLP library on Tensor Cores. BSD-3. Add as submodule.
- **instant-ngp** — https://github.com/NVlabs/instant-ngp
  Reference for tiny-cuda-nn inference/training pattern.
- **Original paper**: Müller et al. 2021.

---

## 4. Astrophysics (Pillar 4)

### Cross-check tools (cannot link; GPL-3)

- **GYOTO** — https://github.com/gyoto/Gyoto — CPU GR ray tracer.
- **GRay2** — https://github.com/luxsrc/GRay2 — GPU GR ray tracer.
- **BlackHoleRaytracer** — several reference implementations; look for
  Odyssey and BHOSS.

### Libraries we can use

- **CFITSIO** — https://heasarc.gsfc.nasa.gov/fitsio/ — FITS I/O.
- **EleFits** — https://github.com/CNES/EleFits — modern C++20 FITS
  wrapper. LGPL-3 (dynamic link OK).
- **HighFive** — https://github.com/BlueBrain/HighFive — header-only
  HDF5 wrapper. BSD-3.

### Preprocessing tools (Python, offline)

- **yt** — https://yt-project.org/ — BSD-3. Simulation data regridding.
- **pyCloudy** — https://github.com/Morisset/pyCloudy — GPL-3. Drives
  CLOUDY for emissivity tables.
- **CLOUDY** — https://www.nublado.org/ — GPL. Plasma physics code.
- **WebbPSF/STPSF** — BSD. PSF simulation for JWST/HST.

### Key papers

- Novikov & Thorne 1973 — thin accretion disk (done).
- Narayan & Yi 1994 — ADAF.
- Sądowski 2009 — slim disk.
- Cárdenas-Avendaño et al. 2022 — photon ring analytic.
- Eggleton 1983 — Roche lobe approximation.
- Dexter & Agol 2009 — geokerr.
- Chan et al. 2013 — GRay performance analysis.

---

## 5. Production polish (Pillar 5)

- **Intel OIDN** — https://github.com/OpenImageDenoise/oidn — Apache 2.0.
  Already integrated. Upgrade to 3.0 when released.
- **OptiX denoiser** — part of OptiX SDK. NVIDIA EULA; link only, no
  redistribution.
- **OpenEXR** — https://github.com/AcademySoftwareFoundation/openexr —
  BSD-3. HDR output.
- **Blender Python API** — viewport render needs
  `bpy.types.RenderEngine.view_draw`. Docs:
  https://docs.blender.org/api/current/

---

## 6. AI coding tools

- **Claude Code** — https://docs.claude.com/en/docs/claude-code/overview
- **GitHub Copilot coding agent** — https://docs.github.com/en/copilot/customizing-copilot/customizing-the-development-environment-for-copilot-coding-agent
- **Cline** — https://cline.bot/ and https://docs.cline.bot/
- **Ralph loop** — https://github.com/snarktank/ralph (reference
  implementation; our shell script is simpler, see `scripts/ralph_loop.sh`).
- **AGENTS.md convention** — https://github.blog/ai-and-ml/github-copilot/how-to-write-a-great-agents-md-lessons-from-over-2500-repositories/

---

## License compatibility reminder

Astroray targets MIT (or Apache 2.0). Compatible:
- Apache 2.0, BSD-2/3, MIT, ISC — link freely.
- LGPL-3 — dynamic link only; do not statically bundle.
- GPL-3 — **cannot use**. Reference for cross-check or inspiration
  only. GYOTO, GRay2, CLOUDY fall here.

When in doubt, ask before adding a dependency.
